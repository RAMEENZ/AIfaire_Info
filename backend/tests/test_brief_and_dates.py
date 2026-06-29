"""Tests pour :
- le garde-fou anti-date-future à l'ingestion (_build_event),
- l'agrégation des vigilances dans le brief (_aggregate_alerts).
"""
from datetime import datetime, timedelta, timezone

from app.pipeline.ingestor import _build_event
from app.pipeline.brief import _aggregate_alerts, _hazard_of


_GEO_NATIONAL = {"lat": None, "lon": None, "code_insee": None, "niveau": "national", "confiance_geo": 0.0}


def _item(date_pub: str) -> dict:
    return {"source": "presse_rss", "source_url": "http://x/1", "titre": "t", "date_publication": date_pub}


def test_far_future_date_is_clamped_to_now():
    future = (datetime.now(timezone.utc) + timedelta(days=27)).isoformat()
    rec = _build_event(_item(future), _GEO_NATIONAL)
    assert rec["date_publication"] <= datetime.now(timezone.utc) + timedelta(minutes=1)


def test_near_future_date_is_preserved():
    # Vigilance météo valable dans 12h : ne doit PAS être ramenée à maintenant.
    soon = datetime.now(timezone.utc) + timedelta(hours=12)
    rec = _build_event(_item(soon.isoformat()), _GEO_NATIONAL)
    assert abs((rec["date_publication"] - soon).total_seconds()) < 5


class _Ev:
    def __init__(self, categorie, gravite, titre, lieu_nom):
        self.categorie, self.gravite, self.titre, self.lieu_nom = categorie, gravite, titre, lieu_nom
        self.resume_ia = None


def test_vigilances_are_grouped_by_hazard():
    fmt = lambda e: f"- {e.titre}"
    alerts = [
        _Ev("meteo", 2, "Vigilance orange – Canicule – Drôme", "Drôme"),
        _Ev("meteo", 2, "Vigilance orange – Canicule – Var", "Var"),
        _Ev("meteo", 2, "Vigilance orange – Canicule – Paris", "Paris"),
        _Ev("ordre_public", 2, "Accident grave sur l'A7", "national"),
    ]
    out = _aggregate_alerts(alerts, fmt)
    # Les 3 canicules deviennent UNE ligne ; l'alerte non-vigilance reste listée.
    assert out.count("Canicule") == 1
    assert "3 départements" in out
    assert "Accident grave" in out


def test_hazard_extraction():
    e = _Ev("meteo", 2, "Vigilance orange – Orages – Nord", "Nord")
    assert _hazard_of(e) == "Orages"
    assert _hazard_of(_Ev("actualite", 0, "Un match de foot", None)) is None
