"""Agrégats quotidiens (daily_stats) : comptes par jour × catégorie × département.

Calculés juste avant la purge de 3h00 (voir scheduler) sur TOUS les événements
encore présents en base : comme le TTL le plus court est de 36 h, chaque journée
est re-calculée au moins deux fois avant que ses événements ne disparaissent —
l'upsert idempotent écrase simplement les comptes partiels de la veille.
"""
import logging
from datetime import date, datetime, timezone

from sqlalchemy import case, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.database import AsyncSessionLocal
from app.models import DailyStat, Event

logger = logging.getLogger(__name__)


async def aggregate_daily_stats() -> int:
    """Upsert des agrégats pour chaque jour présent en base.

    Renvoie le nombre de lignes d'agrégat écrites (insérées ou mises à jour).
    Le jour est la date UTC de publication ; le département suit la même
    convention que /stats/geo (DOM-TOM sur 3 chiffres, Corse 2A/2B).
    """
    dept_col = case(
        (Event.lieu_code_insee.is_(None), ""),
        (Event.lieu_code_insee.like("97%"), func.left(Event.lieu_code_insee, 3)),
        (Event.lieu_code_insee.like("98%"), func.left(Event.lieu_code_insee, 3)),
        else_=func.left(Event.lieu_code_insee, 2),
    ).label("dept")
    jour_col = func.date(Event.date_publication).label("jour")

    async with AsyncSessionLocal() as session:
        try:
            rows = (
                await session.execute(
                    select(jour_col, Event.categorie, dept_col, func.count().label("n"))
                    .group_by(jour_col, Event.categorie, dept_col)
                )
            ).all()

            # Les événements « prévus » (vigilance J1 datée de demain) produisent
            # des jours futurs dont les comptes bougeraient encore : on ne fige
            # que jusqu'à aujourd'hui inclus.
            today = datetime.now(timezone.utc).date()
            values = [
                {
                    "jour": r.jour if isinstance(r.jour, date) else date.fromisoformat(str(r.jour)),
                    "categorie": r.categorie,
                    "departement": (r.dept or "")[:3],
                    "count": r.n,
                }
                for r in rows
                if r.jour is not None and r.jour <= today
            ]
            if not values:
                return 0

            insert_stmt = pg_insert(DailyStat).values(values)
            stmt = insert_stmt.on_conflict_do_update(
                constraint="uq_daily_stats_jour_cat_dept",
                set_={"count": insert_stmt.excluded.count},
            )
            await session.execute(stmt)
            await session.commit()
            logger.info("daily_stats: %d agrégats écrits", len(values))
            return len(values)
        except Exception:
            await session.rollback()
            raise
