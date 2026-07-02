"""Circuit-breaker des flux RSS (presse_rss.FeedCircuitBreaker) : un flux en
échec chronique est mis de côté quelques runs puis re-testé, au lieu d'être
re-tenté à chaque ingestion. Tests hors-ligne, logique pure."""
from app.connectors.presse_rss import FeedCircuitBreaker

URL = "https://exemple.fr/rss"


def _run(cb: FeedCircuitBreaker) -> None:
    cb.begin_run()


def test_stays_closed_below_threshold():
    cb = FeedCircuitBreaker(threshold=3, skip_runs=8)
    _run(cb)
    assert cb.record_failure(URL) is False   # 1er échec
    assert cb.record_failure(URL) is False   # 2e échec
    assert cb.should_skip(URL) is False      # pas encore ouvert


def test_opens_at_threshold_and_skips():
    cb = FeedCircuitBreaker(threshold=3, skip_runs=2)
    _run(cb)
    cb.record_failure(URL)
    cb.record_failure(URL)
    assert cb.record_failure(URL) is True    # 3e échec → ouverture
    assert cb.open_count == 1
    _run(cb)
    assert cb.should_skip(URL) is True       # run suivant : sauté
    _run(cb)
    assert cb.should_skip(URL) is True       # toujours sauté (fenêtre de 2)


def test_half_open_retries_after_window():
    cb = FeedCircuitBreaker(threshold=1, skip_runs=2)
    _run(cb)
    cb.record_failure(URL)                   # ouverture immédiate (threshold=1)
    _run(cb); assert cb.should_skip(URL) is True
    _run(cb); assert cb.should_skip(URL) is True
    _run(cb)
    assert cb.should_skip(URL) is False      # fenêtre écoulée → re-test


def test_failure_during_half_open_reopens():
    cb = FeedCircuitBreaker(threshold=2, skip_runs=1)
    _run(cb)
    cb.record_failure(URL)
    cb.record_failure(URL)                   # ouverture
    _run(cb); assert cb.should_skip(URL) is True
    _run(cb); assert cb.should_skip(URL) is False   # demi-ouvert : re-test
    # Le re-test échoue : ré-ouverture immédiate (compteur déjà ≥ seuil).
    assert cb.record_failure(URL) is True
    _run(cb); assert cb.should_skip(URL) is True


def test_success_resets_everything():
    cb = FeedCircuitBreaker(threshold=2, skip_runs=3)
    _run(cb)
    cb.record_failure(URL)
    cb.record_failure(URL)                   # ouverture
    _run(cb)
    cb.record_success(URL)                   # (re-test réussi)
    assert cb.should_skip(URL) is False
    assert cb.open_count == 0
    # Le compteur repart de zéro : un échec isolé ne rouvre pas le circuit.
    assert cb.record_failure(URL) is False


def test_urls_are_independent():
    cb = FeedCircuitBreaker(threshold=1, skip_runs=5)
    _run(cb)
    cb.record_failure("https://mort.fr/rss")
    assert cb.should_skip("https://vivant.fr/rss") is False
    _run(cb)
    assert cb.should_skip("https://mort.fr/rss") is True
    assert cb.should_skip("https://vivant.fr/rss") is False
