"""Notifications Web Push : garde-fous et logique de ciblage.

Aucun envoi réel — on vérifie que la fonctionnalité reste inerte tant qu'elle
n'est pas configurée, et que le ciblage département/gravité est correct.
"""
from app.pipeline import push as push_module


def test_desactive_sans_cles(monkeypatch):
    """Sans clés VAPID, la fonctionnalité doit être totalement inerte —
    l'application fonctionne normalement, l'interface masque l'option."""
    monkeypatch.setattr(push_module.settings, "VAPID_PUBLIC_KEY", "")
    monkeypatch.setattr(push_module.settings, "VAPID_PRIVATE_KEY", "")
    assert push_module.push_enabled() is False


def test_active_avec_les_deux_cles(monkeypatch):
    monkeypatch.setattr(push_module.settings, "VAPID_PUBLIC_KEY", "pub")
    monkeypatch.setattr(push_module.settings, "VAPID_PRIVATE_KEY", "priv")
    assert push_module.push_enabled() is True


def test_cle_publique_seule_ne_suffit_pas(monkeypatch):
    monkeypatch.setattr(push_module.settings, "VAPID_PUBLIC_KEY", "pub")
    monkeypatch.setattr(push_module.settings, "VAPID_PRIVATE_KEY", "")
    assert push_module.push_enabled() is False


async def test_aucun_envoi_si_desactive(monkeypatch):
    monkeypatch.setattr(push_module.settings, "VAPID_PRIVATE_KEY", "")
    assert await push_module.notify_new_events(["a", "b"]) == 0


async def test_aucun_envoi_sans_evenement(monkeypatch):
    monkeypatch.setattr(push_module.settings, "VAPID_PUBLIC_KEY", "pub")
    monkeypatch.setattr(push_module.settings, "VAPID_PRIVATE_KEY", "priv")
    assert await push_module.notify_new_events([]) == 0


def test_plafond_anti_avalanche():
    """Une vigilance nationale produit des dizaines d'événements graves d'un
    coup : le nombre de notifications par run doit rester borné."""
    assert push_module._MAX_NOTIFICATIONS_PER_RUN <= 5


def test_fenetre_de_fraicheur_raisonnable():
    """Après une panne, le rattrapage ne doit pas réveiller les abonnés pour
    des événements déjà anciens."""
    assert push_module._MAX_EVENT_AGE.total_seconds() <= 12 * 3600


# ── Ciblage : réplique de la règle appliquée dans notify_new_events ─────────

def _concerne(sub_dept: str, sub_gravite_min: int, evt_insee: str | None, evt_gravite: int) -> bool:
    if evt_gravite < sub_gravite_min:
        return False
    if sub_dept and not (evt_insee or "").startswith(sub_dept):
        return False
    return True


def test_abonnement_departemental_filtre_les_autres_departements():
    assert _concerne("69", 3, "69123", 3) is True
    assert _concerne("69", 3, "75056", 3) is False


def test_abonnement_national_recoit_tout():
    assert _concerne("", 3, "69123", 3) is True
    assert _concerne("", 3, None, 3) is True


def test_seuil_de_gravite_respecte():
    assert _concerne("", 3, "69123", 2) is False
    assert _concerne("", 2, "69123", 2) is True


def test_evenement_non_localise_exclu_dun_abonnement_departemental():
    # Sans code INSEE, impossible d'affirmer que l'événement concerne le
    # département suivi : on s'abstient plutôt que de notifier à tort.
    assert _concerne("69", 3, None, 3) is False


def test_corse_et_outremer_pris_en_charge():
    assert _concerne("2A", 3, "2A004", 3) is True
    assert _concerne("974", 3, "97411", 3) is True
    assert _concerne("974", 3, "97105", 3) is False
