"""Endpoints d'abonnement aux notifications Web Push."""
import logging
import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models import PushSubscription
from app.pipeline.push import push_enabled

logger = logging.getLogger(__name__)

router = APIRouter()

_DEPT_RE = re.compile(r"^(\d{2,3}|2[AB])$")


class SubscriptionKeys(BaseModel):
    p256dh: str = Field(max_length=255)
    auth: str = Field(max_length=255)


class SubscriptionIn(BaseModel):
    endpoint: str = Field(max_length=2000)
    keys: SubscriptionKeys
    # "" = alertes nationales ; sinon code département.
    departement: str = Field(default="", max_length=3)
    gravite_min: int = Field(default=3, ge=2, le=3)


class UnsubscribeIn(BaseModel):
    endpoint: str = Field(max_length=2000)


@router.get("/push/public-key")
async def get_public_key() -> dict:
    """Clé publique VAPID à passer à `pushManager.subscribe`.

    Renvoie `enabled: false` plutôt qu'une erreur quand les notifications ne
    sont pas configurées : l'interface masque simplement l'option.
    """
    return {"enabled": push_enabled(), "public_key": settings.VAPID_PUBLIC_KEY or None}


@router.post("/push/subscribe")
async def subscribe(payload: SubscriptionIn, db: AsyncSession = Depends(get_db)) -> dict:
    if not push_enabled():
        raise HTTPException(status_code=503, detail="Notifications non configurées sur ce serveur")

    dept = payload.departement.upper()
    if dept and not _DEPT_RE.match(dept):
        raise HTTPException(status_code=422, detail="Code département invalide")
    if not payload.endpoint.startswith("https://"):
        raise HTTPException(status_code=422, detail="Endpoint de push invalide")

    # Un même navigateur qui se réabonne (changement de département) doit
    # mettre à jour son enregistrement, pas en créer un second.
    stmt = pg_insert(PushSubscription).values(
        endpoint=payload.endpoint,
        p256dh=payload.keys.p256dh,
        auth=payload.keys.auth,
        departement=dept,
        gravite_min=payload.gravite_min,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["endpoint"],
        set_={
            "p256dh": stmt.excluded.p256dh,
            "auth": stmt.excluded.auth,
            "departement": stmt.excluded.departement,
            "gravite_min": stmt.excluded.gravite_min,
        },
    )
    await db.execute(stmt)
    await db.commit()
    return {"status": "subscribed", "departement": dept or "national", "gravite_min": payload.gravite_min}


@router.post("/push/unsubscribe")
async def unsubscribe(payload: UnsubscribeIn, db: AsyncSession = Depends(get_db)) -> dict:
    await db.execute(delete(PushSubscription).where(PushSubscription.endpoint == payload.endpoint))
    await db.commit()
    return {"status": "unsubscribed"}


@router.get("/push/status")
async def status(db: AsyncSession = Depends(get_db)) -> dict:
    """Nombre d'abonnements — utile pour la supervision, sans donnée personnelle."""
    total = len((await db.execute(select(PushSubscription.id))).all())
    return {"enabled": push_enabled(), "subscriptions": total}
