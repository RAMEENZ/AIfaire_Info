"""Tests for the presse_rss connector's conditional-HTTP caching and RSS parsing.

Exercises the module-level ``_fetch_feed`` coroutine in isolation, with no real
network: a small hand-written fake async httpx-like client supplies canned
responses (200 / 304) and records the request headers it received. This lets us
assert the ETag / Last-Modified (conditional GET) cache behaviour and the basic
RSS 2.0 parsing without hitting any feed.

``feedparser.parse`` is run in a thread executor by the connector, so these
tests need a running event loop — the project's ``asyncio_mode = auto`` (see
pytest.ini) provides one for every coroutine test, so no per-test marker is
needed.
"""
import httpx
import pytest

from app.connectors.presse_rss import _fetch_feed


# --- Fakes --------------------------------------------------------------

class FakeResponse:
    """Minimal stand-in for httpx.Response.

    Emulates only the attributes/methods ``_fetch_feed`` touches:
    ``status_code``, ``content`` (bytes), ``headers`` (case-insensitive via
    httpx.Headers) and ``raise_for_status()``.
    """

    def __init__(self, status_code: int, content: bytes = b"", headers: dict | None = None):
        self.status_code = status_code
        self.content = content
        # httpx.Headers is case-insensitive, matching a real response.
        self.headers = httpx.Headers(headers or {})

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"status {self.status_code}", request=None, response=None
            )
        return None


class FakeClient:
    """Fake async httpx client. Returns a queued response and records the
    request headers it was called with so tests can assert conditional headers.
    """

    def __init__(self, response: FakeResponse):
        self._response = response
        self.last_headers: dict | None = None
        self.calls: int = 0

    async def get(self, url, *, timeout=None, headers=None):
        self.calls += 1
        self.last_headers = headers
        return self._response


class RaisingClient:
    """Fake client whose get() raises, to exercise the error-isolation path."""

    async def get(self, url, *, timeout=None, headers=None):
        raise httpx.ConnectError("boom")


# --- Fixtures / helpers -------------------------------------------------

FEED_CFG = {
    "name": "Test Feed",
    "url": "https://example.test/rss.xml",
    "region": "Bretagne",
}

# A fixed, recent-enough pubDate so the article passes the 72h cutoff.
# Using a far-future date keeps the test deterministic regardless of run date.
RSS_BODY = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Test Channel</title>
    <link>https://example.test/</link>
    <item>
      <title>Premier article</title>
      <link>https://example.test/article-1</link>
      <pubDate>Wed, 01 Jan 2099 12:00:00 +0000</pubDate>
      <description>Resume du premier article</description>
    </item>
    <item>
      <title>Deuxieme article</title>
      <link>https://example.test/article-2</link>
      <pubDate>Wed, 01 Jan 2099 13:00:00 +0000</pubDate>
      <description>Resume du deuxieme article</description>
    </item>
  </channel>
</rss>
"""


# --- 1. 200 + parse -----------------------------------------------------

async def test_200_parses_items_and_stores_etag():
    client = FakeClient(FakeResponse(200, RSS_BODY, {"ETag": '"abc123"'}))
    cache: dict = {}

    items, not_modified = await _fetch_feed(client, FEED_CFG, cache)

    assert not_modified is False
    assert len(items) == 2

    # Each item carries the keys the connector produces.
    for it in items:
        assert it["source"] == "presse_rss"
        assert it["categorie"] == "actualite"
        assert it["auteur"] == "Test Feed"
        assert it["lieu_nom"] == "Bretagne"
        assert it["lieu_niveau"] == "region"
        assert it["source_url"].startswith("https://example.test/article-")
        # date_publication is an ISO-8601 string (don't assert exact tz value).
        assert isinstance(it["date_publication"], str)
        assert "T" in it["date_publication"]

    titles = {it["titre"] for it in items}
    assert titles == {"Premier article", "Deuxieme article"}

    # Cache now holds the validator keyed by feed URL.
    assert cache[FEED_CFG["url"]] == {"etag": '"abc123"'}


# --- 2. 304 path --------------------------------------------------------

async def test_304_returns_not_modified_and_sends_if_none_match():
    cache: dict = {FEED_CFG["url"]: {"etag": '"abc123"'}}
    client = FakeClient(FakeResponse(304))

    items, not_modified = await _fetch_feed(client, FEED_CFG, cache)

    # Conditional request header was sent.
    assert client.last_headers is not None
    assert client.last_headers.get("If-None-Match") == '"abc123"'

    # 304: no parse, empty items, not_modified flag set.
    assert items == []
    assert not_modified is True

    # Cache entry preserved unchanged.
    assert cache[FEED_CFG["url"]] == {"etag": '"abc123"'}


# --- 3. Last-Modified ---------------------------------------------------

async def test_last_modified_is_stored_and_resent_as_if_modified_since():
    lm = "Wed, 01 Jan 2099 12:00:00 GMT"

    # First call: 200 with only Last-Modified -> cache stores last_modified.
    client = FakeClient(FakeResponse(200, RSS_BODY, {"Last-Modified": lm}))
    cache: dict = {}
    items, not_modified = await _fetch_feed(client, FEED_CFG, cache)

    assert not_modified is False
    assert len(items) == 2
    assert cache[FEED_CFG["url"]] == {"last_modified": lm}

    # Second call: cache makes _fetch_feed send If-Modified-Since with that value.
    client2 = FakeClient(FakeResponse(304))
    items2, not_modified2 = await _fetch_feed(client2, FEED_CFG, cache)

    assert not_modified2 is True
    assert items2 == []
    assert client2.last_headers is not None
    assert client2.last_headers.get("If-Modified-Since") == lm
    assert client2.last_headers.get("If-None-Match") is None


# --- 4. No validators ---------------------------------------------------

async def test_no_validators_clears_cache_entry():
    # Pre-seed a stale validator; a 200 with no ETag/Last-Modified must remove it
    # so no stale validator is re-sent next time.
    cache: dict = {FEED_CFG["url"]: {"etag": '"stale"'}}
    client = FakeClient(FakeResponse(200, RSS_BODY, {}))

    items, not_modified = await _fetch_feed(client, FEED_CFG, cache)

    assert not_modified is False
    assert len(items) == 2
    # URL absent from cache afterwards (code calls feed_cache.pop).
    assert FEED_CFG["url"] not in cache


# --- 5. Error isolation -------------------------------------------------

async def test_get_exception_is_wrapped_in_runtimeerror():
    client = RaisingClient()
    cache: dict = {}

    with pytest.raises(RuntimeError):
        await _fetch_feed(client, FEED_CFG, cache)
