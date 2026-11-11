"""TDD RED tests for the news advisory service (Task 1).

Contract source: docs/supergraph/plans/2026-11-10-crypto-news-risk-advisory.md
Sources: SEC + Federal Reserve press RSS (public domain) and tier-1 filtered
Google News RSS (personal feed-reader license). Advisory only: the service
never touches signal generation.
"""
import asyncio
import time

import pytest

from news_service import (
    NewsService,
    dedup_key,
    event_tags,
    match_symbols,
    normalize_url,
    parse_feed_entries,
    sanitize_text,
)

# ---------------------------------------------------------------------------
# Fakes (no live network in unit tests)
# ---------------------------------------------------------------------------

class FakeContent:
    def __init__(self, chunks):
        self._chunks = list(chunks)

    async def iter_chunked(self, n):  # noqa: ARG002 - signature parity
        for chunk in self._chunks:
            yield chunk


class FakeResponse:
    def __init__(self, status=200, content_type="application/rss+xml",
                 body=b"", chunks=None, enter_exc=None, read_exc=None):
        self.status = status
        self.content_type = content_type
        self.body = body
        self.closed = False
        self._enter_exc = enter_exc
        self._read_exc = read_exc
        self.content = FakeContent(chunks if chunks is not None else ([body] if body else []))

    async def __aenter__(self):
        if self._enter_exc:
            raise self._enter_exc
        return self

    async def __aexit__(self, *exc):
        self.close()
        return False

    def close(self):
        self.closed = True


class FakeSession:
    def __init__(self, responses):
        # responses: url -> FakeResponse | Exception (raised on enter)
        self._responses = responses
        self.calls = []
        self.closed = False

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        resp = self._responses[url]
        if isinstance(resp, Exception):
            raise resp
        return resp

    async def close(self):
        self.closed = True


def make_service(responses, now=1_794_400_000.0, feeds=None):
    session = FakeSession(responses)
    service = NewsService(
        clock=lambda: now,
        session_factory=lambda: session,
        feeds=feeds,
    )
    return service, session


RSS_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">
<channel>
<title>Test Feed</title>
<link>https://news.google.com/rss/search?q=test</link>
<description>Test</description>
{items}
</channel>
</rss>"""


def rss_item(title, link, pubdate="Tue, 11 Nov 2026 10:00:01 GMT", guid=None):
    g = f"<guid isPermaLink=\"false\">{guid or link}</guid>" if (guid or link) else ""
    d = f"<pubDate>{pubdate}</pubDate>" if pubdate else ""
    return (f"<item><title>{title}</title><link>{link}</link>{g}{d}"
            f"<description>&lt;a href=\"https://news.google.com/stub\"&gt;stub&lt;/a&gt;</description></item>")


def google_item(headline, source, link=None, pubdate="Tue, 11 Nov 2026 10:00:01 GMT"):
    return rss_item(f"{headline} - {source}", link or f"https://news.google.com/rss/articles/{source.replace(' ', '')}_{pubdate}", pubdate)


SEC_FEED = {"source": "SEC", "url": "https://www.sec.gov/news/pressreleases.xml", "official": True}
FED_FEED = {"source": "Federal Reserve", "url": "https://www.federalreserve.gov/feeds/press_all.xml", "official": True}
GN_FEED = {"source": "Google News — crypto",
           "url": "https://news.google.com/rss/search?q=cryptocurrency+OR+bitcoin+OR+ethereum+when:2d&hl=en-US&gl=US&ceid=US:en"}


# ---------------------------------------------------------------------------
# Parsing / sanitizing
# ---------------------------------------------------------------------------

def test_parse_rss_entry_plain_text_and_https_link():
    body = RSS_TEMPLATE.format(items=google_item(
        "Bitcoin &amp; &lt;b&gt;ETF&lt;/b&gt; approved", "Bloomberg",
        link="https://news.google.com/rss/articles/CBMiabc?utm_source=chatgpt.com")).encode()
    entries, err = parse_feed_entries(GN_FEED, body, fetch_time=1_794_400_000.0)
    assert err is None
    assert len(entries) == 1
    e = entries[0]
    assert e["source"] == "Bloomberg"
    assert e["title"] == "Bitcoin & ETF approved"  # markup stripped, entities decoded
    assert "<" not in e["title"] and "&amp;" not in e["title"]
    assert e["url"].startswith("https://news.google.com/")
    assert e["published_at_estimated"] is False


def test_parse_atom_entry():
    body = b"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
<title>Atom Feed</title>
<entry><title type="html">Ethereum upgrade &amp; roadmap - Bloomberg</title>
<link href="https://news.google.com/rss/articles/atom1"/>
<updated>2026-11-11T09:00:00Z</updated></entry>
</feed>"""
    entries, err = parse_feed_entries(GN_FEED, body, fetch_time=1_794_400_000.0)
    assert err is None
    assert entries[0]["title"] == "Ethereum upgrade & roadmap"
    assert entries[0]["source"] == "Bloomberg"
    assert entries[0]["url"] == "https://news.google.com/rss/articles/atom1"


def test_rejects_dtd_and_entity_payload():
    body = (b'<?xml version="1.0"?><!DOCTYPE rss [<!ENTITY x "expanded">]>'
            b'<rss version="2.0"><channel><title>&x;</title></channel></rss>')
    entries, err = parse_feed_entries(GN_FEED, body, fetch_time=1_794_400_000.0)
    assert entries == []
    assert err == "unsafe_xml"


def test_streaming_body_limit_includes_compressed_payload():
    big = b"x" * (512 * 1024)
    responses = {GN_FEED["url"]: FakeResponse(body=b"<rss>", chunks=[big, b"more"])}
    service, _ = make_service(responses, feeds=[GN_FEED])
    asyncio.run(service.refresh())
    assert service.items(symbol="BTCUSDT") == []
    assert service.status()["source_status"][0]["error_code"] == "body_too_large"


def test_redirects_are_disabled():
    responses = {GN_FEED["url"]: FakeResponse(body=RSS_TEMPLATE.format(items="").encode())}
    service, session = make_service(responses, feeds=[GN_FEED])
    asyncio.run(service.refresh())
    url, kwargs = session.calls[0]
    assert kwargs.get("allow_redirects") is False
    assert kwargs.get("timeout").total == 4


def test_article_link_host_allowlist():
    body = RSS_TEMPLATE.format(items=(
        google_item("Crypto market rallies", "Bloomberg", link="https://news.google.com/rss/articles/ok1")
        + google_item("SEC charges exchange", "Reuters", link="https://evil.example.com/article")
        + google_item("Fed holds rates", "CNBC", link="http://news.google.com/rss/articles/plain")
    )).encode()
    entries, err = parse_feed_entries(GN_FEED, body, fetch_time=1_794_400_000.0)
    urls = [e["url"] for e in entries]
    assert "https://news.google.com/rss/articles/ok1" in urls
    assert not any("evil.example.com" in u for u in urls)
    assert not any(u.startswith("http://") for u in urls)


def test_google_news_source_allowlist_drops_untrusted_sources():
    # Junk items carry symbol matches too, so only the source filter can drop them.
    body = RSS_TEMPLATE.format(items=(
        google_item("Bitcoin jumps", "TechBullion", link="https://news.google.com/rss/articles/junk1")
        + google_item("Ethereum rallies", "24/7 Wall St.", link="https://news.google.com/rss/articles/junk2")
        + google_item("Bitcoin ETF approved by SEC", "Bloomberg", link="https://news.google.com/rss/articles/good1")
    )).encode()
    entries, err = parse_feed_entries(GN_FEED, body, fetch_time=1_794_400_000.0)
    titles = [e["title"] for e in entries]
    assert "Bitcoin ETF approved by SEC" in titles
    assert not any("junk" in e["url"] for e in entries)


# ---------------------------------------------------------------------------
# URL normalization / dedup
# ---------------------------------------------------------------------------

def test_normalizes_tracking_query_fragment_and_trailing_slash():
    a = normalize_url("https://news.google.com/rss/articles/abc?utm_source=chatgpt.com&b=2&a=1#frag")
    b = normalize_url("https://news.google.com/rss/articles/abc/?a=1&b=2")
    assert a == b
    assert dedup_key(a) == dedup_key(b)
    assert "#" not in a and "utm_" not in a


def test_deduplicates_same_article_across_feeds_and_merges_metadata():
    shared = "https://news.google.com/rss/articles/shared1"
    body_a = RSS_TEMPLATE.format(items=google_item("Bitcoin ETF approved", "Bloomberg", link=shared,
                                                  pubdate="Tue, 11 Nov 2026 10:00:01 GMT")).encode()
    body_b = RSS_TEMPLATE.format(items=google_item("Bitcoin ETF approved by SEC", "Reuters", link=shared,
                                                  pubdate="Tue, 11 Nov 2026 12:00:01 GMT")).encode()
    gn_reg_feed = {"source": "Google News — regulation",
                   "url": "https://news.google.com/rss/search?q=crypto+regulation+when:3d&hl=en-US&gl=US&ceid=US:en"}
    responses = {
        GN_FEED["url"]: FakeResponse(body=body_a),
        gn_reg_feed["url"]: FakeResponse(body=body_b),
    }
    service, _ = make_service(responses, feeds=[GN_FEED, gn_reg_feed])
    asyncio.run(service.refresh())
    items = service.items(symbol="BTCUSDT")
    assert len(items) == 1
    it = items[0]
    assert set(it["sources"]) == {"Bloomberg", "Reuters"}
    assert it["published_at"] > 0  # newest valid timestamp kept


# ---------------------------------------------------------------------------
# Symbol / alias matching
# ---------------------------------------------------------------------------

def test_matches_ticker_alias_with_token_boundaries():
    symbols, scope = match_symbols("Bitcoin ETF approved by SEC")
    assert "BTC" in symbols and scope == "symbol"
    symbols, _ = match_symbols("Ripple wins case as XRP surges")
    assert "XRP" in symbols
    symbols, _ = match_symbols("Chainlink and Solana lead gains")
    assert "LINK" in symbols and "SOL" in symbols


def test_does_not_false_match_short_ticker_in_word():
    for title in ["Click the link in bio", "Arbitrage opportunity explained",
                  "Original post deleted", "Connect the dots on DOT", "Tons of leverage",
                  "Apt to rally", "University research on crypto market"]:
        symbols, _ = match_symbols(title)
        assert symbols == [], title


def test_ambiguous_tickers_only_match_explicit_aliases():
    symbols, _ = match_symbols("Polkadot parachain auction closes")  # DOT alias
    assert "DOT" in symbols
    symbols, _ = match_symbols("Near protocol ships update")  # NEAR alias
    assert "NEAR" in symbols
    symbols, _ = match_symbols("Optimism announces upgrade")  # OP alias
    assert "OP" in symbols
    symbols, _ = match_symbols("Solana outage hits network")  # SOL bare ticker ok
    assert "SOL" in symbols
    symbols, _ = match_symbols("Gas fees spike on Ethereum")  # GAS denied bare ticker
    assert "GAS" not in symbols


def test_broad_market_rule_does_not_match_unrelated_story():
    symbols, scope = match_symbols("Federal Reserve holds rates as inflation cools")
    assert scope == "market"
    symbols, scope = match_symbols("Local bakery wins award for best croissant")
    assert scope is None and symbols == []


# ---------------------------------------------------------------------------
# Event tags
# ---------------------------------------------------------------------------

def test_event_tag_sec_requires_uppercase_token():
    tags = event_tags("SEC approves Bitcoin ETF")
    assert "SEC" in tags and "ETF" in tags
    tags = event_tags("Please secure your wallet etc")
    assert "SEC" not in tags and "ETF" not in tags


def test_event_tag_negation_is_suppressed_within_three_tokens():
    assert "hack" not in event_tags("Exchange reports no hack after review")
    assert "ban" not in event_tags("Official denies ban on crypto trading")
    assert "hack" in event_tags("Major exchange hack drains funds")


# ---------------------------------------------------------------------------
# Freshness / staleness
# ---------------------------------------------------------------------------

def test_missing_and_future_timestamps_are_estimated():
    body = RSS_TEMPLATE.format(items=(
        google_item("Bitcoin moves", "Bloomberg", link="https://news.google.com/rss/articles/nodate1", pubdate=None)
        + google_item("Ethereum news", "Reuters", link="https://news.google.com/rss/articles/future1",
                      pubdate="Fri, 01 Jan 2100 00:00:00 GMT")
    )).encode()
    entries, err = parse_feed_entries(GN_FEED, body, fetch_time=1_794_400_000.0)
    by_url = {e["url"]: e for e in entries}
    nodate = by_url["https://news.google.com/rss/articles/nodate1"]
    assert nodate["published_at"] == 1_794_400_000.0 and nodate["published_at_estimated"] is True
    future = by_url["https://news.google.com/rss/articles/future1"]
    assert future["published_at"] == 1_794_400_000.0 and future["published_at_estimated"] is True


def test_cache_expires_and_marks_stale_at_15_minutes():
    body = RSS_TEMPLATE.format(items=google_item(
        "Bitcoin holds gains", "Bloomberg", link="https://news.google.com/rss/articles/stale1",
        pubdate="Tue, 11 Nov 2026 09:00:01 GMT")).encode()
    service, _ = make_service({GN_FEED["url"]: FakeResponse(body=body)}, now=1_794_400_000.0, feeds=[GN_FEED])
    asyncio.run(service.refresh())
    service._clock = lambda: 1_794_400_000.0 + 14 * 60 + 59
    assert service.status()["stale"] is False
    service._clock = lambda: 1_794_400_000.0 + 15 * 60 + 1
    assert service.status()["stale"] is True
    # 24h retention: item older than a day is dropped
    service._clock = lambda: 1_794_400_000.0 + 24 * 3600 + 5
    assert service.items(symbol="BTCUSDT") == []


# ---------------------------------------------------------------------------
# Failure isolation
# ---------------------------------------------------------------------------

def test_one_feed_failure_preserves_other_feed_items():
    good = RSS_TEMPLATE.format(items=google_item(
        "Bitcoin rallies", "Bloomberg", link="https://news.google.com/rss/articles/keep1",
        pubdate="Tue, 11 Nov 2026 09:30:00 GMT")).encode()
    responses = {
        GN_FEED["url"]: FakeResponse(body=good),
        SEC_FEED["url"]: FakeResponse(status=500, body=b"oops"),
    }
    service, _ = make_service(responses, feeds=[GN_FEED, SEC_FEED])
    asyncio.run(service.refresh())
    titles = [i["title"] for i in service.items(symbol="BTCUSDT")]
    assert "Bitcoin rallies" in titles
    status = service.status()
    by_source = {s["source"]: s for s in status["source_status"]}
    assert by_source["Google News — crypto"]["ok"] is True
    assert by_source["SEC"]["ok"] is False
    assert by_source["SEC"]["error_code"] == "http_500"
    assert status["sources_ok"] is False


def test_cancelled_refresh_closes_response():
    class CancelContent:
        async def iter_chunked(self, n):  # noqa: ARG002
            yield b"<rss>"
            raise asyncio.CancelledError()

    resp = FakeResponse()
    resp.content = CancelContent()
    service, _ = make_service({GN_FEED["url"]: resp}, feeds=[GN_FEED])
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(service.refresh())
    assert resp.closed is True


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def test_sanitize_text_caps_and_strips():
    assert sanitize_text("<b>Bold</b> &amp; <i>italic</i>") == "Bold & italic"
    assert len(sanitize_text("a" * 500)) == 300
