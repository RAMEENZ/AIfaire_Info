"""Regression : la clé de cache /events doit REGROUPER les requêtes voisines.

Le front calcule sa borne temporelle par `Date.now() - heures × 3600000`,
recalculée à chaque requête : elle porte les millisecondes. Reprise telle quelle
dans la clé, elle en faisait une clé neuve à chaque appel — le cache Redis
écrivait des entrées qu'il ne relirait jamais.

Mesuré en production le 30/08/2026, après plusieurs jours de service :

    keyspace_hits:0
    keyspace_misses:104

Zéro sur cent quatre : pas un taux faible, une absence totale de réutilisation.
Ces tests verrouillent le regroupement à la minute.
"""
from datetime import datetime, timedelta, timezone

from app.api.routes.events import _events_cache_key


def _cle(depuis: datetime, **extra) -> str:
    return _events_cache_key(depuis=depuis, limit=200, offset=0, **extra)


def test_deux_requetes_dans_la_meme_minute_partagent_la_cle():
    """Le cas qui ne marchait pas : deux visiteurs à la même seconde."""
    base = datetime(2026, 8, 30, 9, 15, 0, tzinfo=timezone.utc)
    assert _cle(base + timedelta(milliseconds=7)) == _cle(base + timedelta(milliseconds=812))


def test_toute_la_minute_est_regroupee():
    base = datetime(2026, 8, 30, 9, 15, 0, tzinfo=timezone.utc)
    assert _cle(base) == _cle(base + timedelta(seconds=59, microseconds=999_999))


def test_minutes_differentes_donnent_des_cles_differentes():
    """L'arrondi regroupe, il n'aplatit pas : la fenêtre reste discriminante."""
    base = datetime(2026, 8, 30, 9, 15, 0, tzinfo=timezone.utc)
    assert _cle(base) != _cle(base + timedelta(minutes=1))


def test_avant_est_arrondi_comme_depuis():
    base = datetime(2026, 8, 30, 9, 15, 0, tzinfo=timezone.utc)
    fin = datetime(2026, 8, 30, 11, 0, 0, tzinfo=timezone.utc)
    assert _cle(base, avant=fin + timedelta(milliseconds=3)) == _cle(base, avant=fin)


def test_les_autres_parametres_restent_discriminants():
    """L'arrondi ne doit toucher QUE les bornes temporelles : deux filtres
    différents ne doivent jamais se partager une réponse."""
    base = datetime(2026, 8, 30, 9, 15, 0, tzinfo=timezone.utc)
    assert _cle(base, dept="75") != _cle(base, dept="13")
    assert _cle(base, categories=["meteo"]) != _cle(base, categories=["crue"])
    assert _cle(base, gravite_min=0) != _cle(base, gravite_min=2)
    assert _cle(base, full=False) != _cle(base, full=True)


def test_cle_stable_et_prefixee():
    """Le préfixe `events:` est le motif que balaie l'invalidation de fin
    d'ingestion (`scan_iter(match="events:*")`) : le changer rendrait la purge
    silencieusement inopérante."""
    base = datetime(2026, 8, 30, 9, 15, 0, tzinfo=timezone.utc)
    cle = _cle(base)
    assert cle.startswith("events:")
    assert cle == _cle(base)
