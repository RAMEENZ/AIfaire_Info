"""Un article de SPORT ne doit pas être épinglé sur la ville d'un club nommé
d'après une ville (« Paris FC » → Paris). Le repli toponyme-du-titre est
désactivé pour le sport ; le département de l'URL reste utilisé s'il existe."""
from app.pipeline import extractor


async def test_sport_not_pinned_to_club_city(monkeypatch):
    async def fake_extract(titre, description, full_text=None):
        return {"lieu_nom": "national", "categorie": "sport",
                "resume_ia": "x", "gravite": 0, "tags": []}
    monkeypatch.setattr(extractor, "extract_article", fake_extract)
    item = {
        "source": "presse_rss",
        "source_url": "https://www.leparisien.fr/sports/football/paris-fc/mercato-x",
        "titre": "Mercato : le Paris FC vise un nouvel attaquant",
        "description": "",
    }
    out = await extractor.maybe_extract(item)
    assert out["lieu_nom"] == "national"  # et surtout PAS "Paris"


async def test_non_sport_title_still_localizes(monkeypatch):
    async def fake_extract(titre, description, full_text=None):
        return {"lieu_nom": "national", "categorie": "actualite",
                "resume_ia": "x", "gravite": 0, "tags": []}
    monkeypatch.setattr(extractor, "extract_article", fake_extract)
    item = {
        "source": "presse_rss",
        "source_url": "https://example.fr/no-departement-ici",
        "titre": "Grande manifestation à Lyon ce samedi",
        "description": "",
    }
    out = await extractor.maybe_extract(item)
    assert out["lieu_nom"] == "Lyon"  # hors sport, le toponyme du titre est conservé


async def test_sport_local_keeps_department_from_url(monkeypatch):
    async def fake_extract(titre, description, full_text=None):
        return {"lieu_nom": "national", "categorie": "sport",
                "resume_ia": "x", "gravite": 0, "tags": []}
    monkeypatch.setattr(extractor, "extract_article", fake_extract)
    item = {
        "source": "presse_rss",
        "source_url": "https://www.leparisien.fr/essonne-91/tournoi-de-tennis-local-x",
        "titre": "Tournoi de tennis",
        "description": "",
    }
    out = await extractor.maybe_extract(item)
    # Sport mais l'URL donne un département fiable → on le garde.
    assert out["lieu_nom"] == "Essonne"
