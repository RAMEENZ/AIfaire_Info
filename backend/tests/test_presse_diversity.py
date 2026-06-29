"""La sélection presse doit RÉPARTIR le plafond entre flux (round-robin) et non
garder les N plus récents — sinon un gros publicateur (Le Parisien) monopolise."""
from app.connectors.presse_rss import _select_diverse


def _it(feed, ts):
    return {"_feed": feed, "date_publication": ts, "titre": f"{feed}-{ts}"}


def test_high_frequency_feed_does_not_monopolize():
    items = []
    # Flux 0 (« Le Parisien ») : 50 articles très récents.
    for k in range(50):
        items.append(_it(0, f"2026-06-29T10:{k:02d}:00"))
    # 30 flux régionaux : 1 article chacun, légèrement plus anciens.
    for f in range(1, 31):
        items.append(_it(f, "2026-06-29T09:00:00"))

    selected = _select_diverse(items, 20)
    assert len(selected) == 20
    from_feed0 = sum(1 for s in selected if s["_feed"] == 0)
    distinct_feeds = len({s["_feed"] for s in selected})
    # Tri par récence aurait donné 20× le flux 0. Le round-robin en prend 1.
    assert from_feed0 == 1
    assert distinct_feeds == 20


def test_freshest_article_of_each_feed_comes_first():
    items = [_it(0, "2026-06-29T08:00:00"), _it(0, "2026-06-29T10:00:00"),
             _it(1, "2026-06-29T09:00:00")]
    sel = _select_diverse(items, 2)
    # Round 0 : tête de chaque flux (le plus récent), flux les plus frais d'abord.
    assert sel[0]["_feed"] == 0 and sel[0]["date_publication"] == "2026-06-29T10:00:00"
    assert sel[1]["_feed"] == 1


def test_respects_max_and_handles_empty():
    assert _select_diverse([], 10) == []
    items = [_it(f, "2026-06-29T09:00:00") for f in range(100)]
    assert len(_select_diverse(items, 12)) == 12
