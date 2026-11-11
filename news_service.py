"""News advisory service — bounded public RSS headlines for advisory context only.

Sources (fixed allowlist, maintainer-editable here only):
- SEC press releases and Federal Reserve press releases: US federal government
  works, public domain by statute (17 U.S.C. §105); highest-signal market
  movers (ETF approvals, enforcement actions, FOMC/rates).
- Google News RSS search feeds: in-feed license grants "rendering Google News
  results within a personal feed reader for personal, non-commercial use".
  Items are gated by a tier-1 source allowlist (title suffix) so low-signal /
  fake-news outlets never reach the UI.

Hard invariants:
- Advisory only: this service never creates, modifies, suppresses or executes
  a trade signal, and never changes Entry/SL/TP or risk sizing.
- No request-path upstream HTTP: the API route reads the in-memory cache only.
- Fixed HTTPS allowlist, no redirects, short timeout, bounded body, DTD/entity
  rejection before XML parse, host-validated article links, text-only rendering.
"""
import asyncio
import hashlib
import os
import re
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import aiohttp
import xml.etree.ElementTree as ET

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# SEC fair-access policy requires a declared User-Agent with a contact address;
# override per deployment via the NEWS_USER_AGENT environment variable.
USER_AGENT = os.environ.get("NEWS_USER_AGENT", "futures-chart-scanner admin@example.com")
PER_FEED_TIMEOUT_SECONDS = 4
MAX_BODY_BYTES = 512 * 1024  # decompressed read cap
POLL_INTERVAL_SECONDS = 300  # 5 minutes
STALE_AFTER_SECONDS = 15 * 60
CACHE_MAX_ITEMS = 200
CACHE_TTL_SECONDS = 24 * 3600
TITLE_CAP = 300
MAX_API_ITEMS = 50

FEEDS: List[Dict[str, Any]] = [
    {"source": "SEC", "url": "https://www.sec.gov/news/pressreleases.xml", "official": True},
    {"source": "Federal Reserve", "url": "https://www.federalreserve.gov/feeds/press_all.xml", "official": True},
    {
        "source": "Google News — crypto",
        "url": "https://news.google.com/rss/search?q=cryptocurrency+OR+bitcoin+OR+ethereum+when:2d&hl=en-US&gl=US&ceid=US:en",
    },
    {
        "source": "Google News — regulation",
        "url": "https://news.google.com/rss/search?q=crypto+regulation+OR+sec+OR+cftc+when:3d&hl=en-US&gl=US&ceid=US:en",
    },
]

# Tier-1 outlets (Google News title suffix, lowercase). Tin-vịt gate.
TIER1_SOURCES = {
    "bloomberg", "reuters", "cnbc", "wsj", "financial times", "fortune",
    "forbes", "barron's", "marketwatch", "benzinga", "coindesk",
    "cointelegraph", "the block", "decrypt", "bitcoin magazine",
}

# Allowed article link hosts (SSRF boundary; feed URLs are the FEEDS allowlist).
ALLOWED_ARTICLE_HOSTS = {
    "news.google.com",
    "sec.gov", "www.sec.gov",
    "federalreserve.gov", "www.federalreserve.gov",
}

# Symbol alias map: symbol -> pipe-separated alias phrases (whole-phrase match).
ALIASES: Dict[str, str] = {
    "BTC": "bitcoin",
    "ETH": "ethereum|ether",
    "BNB": "binance coin",
    "SOL": "solana",
    "XRP": "ripple",
    "DOGE": "dogecoin",
    "ADA": "cardano",
    "AVAX": "avalanche",
    "LINK": "chainlink",
    "DOT": "polkadot",
    "TRX": "tron",
    "NEAR": "near protocol",
    "LTC": "litecoin",
    "BCH": "bitcoin cash",
    "SUI": "sui",
    "SHIB": "shiba inu",
    "PEPE": "pepe",
    "INJ": "injective",
    "OP": "optimism",
    "ARB": "arbitrum",
    "WLD": "worldcoin",
    "TON": "toncoin",
    "FIL": "filecoin",
    "APT": "aptos",
    "TIA": "celestia",
    "SEI": "sei network",
    "UNI": "uniswap",
}

# Symbols allowed to match their bare ticker token (others are ambiguous
# ordinary words / abbreviations and match alias phrases only).
BARE_TICKER_SYMBOLS = {
    "BTC", "ETH", "BNB", "SOL", "XRP", "DOGE", "ADA", "AVAX", "TRX", "LTC",
    "BCH", "SUI", "SHIB", "PEPE", "INJ", "WLD", "FIL", "TIA", "SEI",
}

BROAD_MARKET_PHRASES = [
    "bitcoin", "crypto market", "cryptocurrency market", "digital assets",
    "crypto industry", "federal reserve", "fomc", "inflation", "interest rate",
    "cpi", "etf flows", "crypto regulation", "crypto hack", "exchange outage",
    "market liquidation",
]

# Event tags: lowercase whole-word/phrase tags plus uppercase-only acronyms.
EVENT_TAG_WORDS = [
    "hack", "exploit", "security breach", "lawsuit", "ban", "sanction",
    "regulation", "delisting", "insolvency", "bankruptcy", "liquidation",
]
EVENT_TAG_ACRONYMS = ["SEC", "CFTC", "ETF"]

NEGATION_TOKENS = {"no", "not", "without", "unlikely", "denies", "denied", "rejects", "false"}
NEGATION_WINDOW = 3

_TRACKING_QUERY_KEYS = ("utm_*", "ref", "source", "campaign", "fbclid", "gclid")


# ---------------------------------------------------------------------------
# Text / URL helpers
# ---------------------------------------------------------------------------

class _TextStripper(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: List[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def sanitize_text(raw: str) -> str:
    """Strip markup, decode entities, collapse whitespace, cap length."""
    if not raw:
        return ""
    stripper = _TextStripper()
    try:
        stripper.feed(raw)
        stripper.close()
    except Exception:
        pass
    text = " ".join("".join(stripper.parts).split())
    return text[:TITLE_CAP]


def _is_tracking_key(key: str) -> bool:
    lowered = key.lower()
    return any(lowered == pat or (pat.endswith("*") and lowered.startswith(pat[:-1])) for pat in _TRACKING_QUERY_KEYS)


def normalize_url(url: str) -> Optional[str]:
    """Canonical article URL, or None when unsafe/unapproved."""
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return None
    if parts.scheme.lower() != "https":
        return None
    if parts.username or parts.password:
        return None
    host = (parts.hostname or "").lower()
    if host not in ALLOWED_ARTICLE_HOSTS:
        return None
    port = parts.port
    netloc = host if port in (None, 443) else f"{host}:{port}"
    kept = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not _is_tracking_key(k)]
    query = urlencode(sorted(kept))
    path = parts.path or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/") or "/"
    return urlunsplit(("https", netloc, path, query, ""))


def dedup_key(normalized_url: str) -> str:
    return hashlib.sha256(normalized_url.encode("utf-8")).hexdigest()


def _parse_timestamp(raw: Optional[str], fetch_time: float) -> Tuple[float, bool]:
    """Return (epoch_seconds, estimated_flag). Missing/invalid/future -> fetch_time."""
    if raw:
        raw = raw.strip()
        dt = None
        try:
            dt = parsedate_to_datetime(raw)
        except (TypeError, ValueError):
            dt = None
        if dt is None:
            try:
                dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            except ValueError:
                dt = None
        if dt is not None:
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            epoch = dt.timestamp()
            if epoch <= fetch_time:
                return epoch, False
    return fetch_time, True


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def _word_tokens(text: str) -> List[Tuple[int, str]]:
    return [(m.start(), m.group(0)) for m in re.finditer(r"[A-Za-z0-9]+", text)]


def match_symbols(title: str) -> Tuple[List[str], Optional[str]]:
    """Return (matched symbols, scope) using token-boundary/alias matching."""
    lowered = title.lower()
    tokens = {tok for _, tok in _word_tokens(title)}
    matched = set()
    for symbol, alias_blob in ALIASES.items():
        for phrase in alias_blob.split("|"):
            phrase = phrase.strip().lower()
            if not phrase:
                continue
            if re.search(rf"\b{re.escape(phrase)}\b", lowered):
                matched.add(symbol)
                break
        else:
            if symbol in BARE_TICKER_SYMBOLS and symbol.lower() in tokens:
                matched.add(symbol)
    symbols = sorted(matched)
    if symbols:
        return symbols, "symbol"
    for phrase in BROAD_MARKET_PHRASES:
        if re.search(rf"\b{re.escape(phrase)}\b", lowered):
            return [], "market"
    return [], None


def event_tags(title: str) -> List[str]:
    """Exact-phrase event tags; acronyms require uppercase; negation suppresses."""
    tags = set()
    lowered = title.lower()
    word_spans = [(m.start(), m.end(), m.group(0)) for m in re.finditer(r"[A-Za-z]+", title)]

    def negated(word_idx: int) -> bool:
        """True when a negation token appears within NEGATION_WINDOW words before."""
        preceding = [w for _s, _e, w in word_spans[:word_idx]]
        return any(w.lower() in NEGATION_TOKENS for w in preceding[-NEGATION_WINDOW:])

    # Lowercase whole-word / phrase tags
    for tag in EVENT_TAG_WORDS:
        for m in re.finditer(rf"\b{re.escape(tag)}\b", lowered):
            # find matching index in original-case word list for negation check
            idx = next((i for i, (s, _e, _w) in enumerate(word_spans) if s >= m.start()), len(word_spans))
            if not negated(idx):
                tags.add(tag)
                break  # only stop once a real (non-negated) hit is found
    # Uppercase-only acronym tags
    for tag in EVENT_TAG_ACRONYMS:
        for m in re.finditer(rf"\b{re.escape(tag)}\b", title):
            idx = next((i for i, (s, _e, _w) in enumerate(word_spans) if s >= m.start()), len(word_spans))
            if not negated(idx):
                tags.add(tag)
                break
    return sorted(tags)


# ---------------------------------------------------------------------------
# Feed parsing
# ---------------------------------------------------------------------------

class _BodyTooLarge(Exception):
    pass


def _decode_strict(body: bytes) -> Optional[str]:
    """Decode feed bytes as UTF-8/ASCII only.

    A literal ASCII byte check for ``<!DOCTYPE``/``<!ENTITY`` is bypassable
    when the document declares another encoding (e.g. UTF-16), because the
    marker bytes differ. Restricting to UTF-8/ASCII (and rejecting bodies
    whose XML declaration claims anything else) keeps the DTD/entity
    pre-check sound.
    """
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        return None
    decl = re.match(r"\s*<\?xml[^>]*?encoding=[\"']([\w.\-]+)[\"']", text, re.IGNORECASE)
    if decl and decl.group(1).lower() not in ("utf-8", "utf8", "us-ascii", "ascii"):
        return None
    return text


def parse_feed_entries(feed: Dict[str, Any], body: bytes, fetch_time: float) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """Parse one feed body into advisory entries. Returns (entries, error_code)."""
    text = _decode_strict(body)
    if text is None:
        return [], "unsupported_encoding"
    if "<!DOCTYPE" in text or "<!ENTITY" in text:
        return [], "unsafe_xml"
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return [], "malformed_xml"

    tag = root.tag.rsplit("}", 1)[-1].lower()
    if tag == "rss":
        items = root.findall("./channel/item")
        date_field = "pubDate"
    elif tag == "feed":
        items = root.findall("./{*}entry") or root.findall("./entry")
        date_field = "updated"
    else:
        return [], "unsupported_format"

    official = bool(feed.get("official"))
    feed_source = feed.get("source", feed["url"])
    entries: List[Dict[str, Any]] = []
    for item in items:
        raw_title = (item.findtext("{*}title") or "").strip()
        raw_link = (item.findtext("{*}link") or "").strip()
        link_el = item.find("{*}link")
        href = (link_el.get("href") or "").strip() if link_el is not None else ""
        if not raw_link and href:
            raw_link = href  # Atom <link href="..."/> element form
        if not raw_title or not raw_link:
            continue

        title = sanitize_text(raw_title)
        source = feed_source
        if not official:
            headline, sep, suffix = title.rpartition(" - ")
            if not sep or suffix.strip().lower() not in TIER1_SOURCES:
                continue  # tin-vịt gate: untrusted Google News source
            title = headline.strip()
            source = suffix.strip()

        normalized = normalize_url(raw_link)
        if not normalized:
            continue
        symbols, scope = match_symbols(title)
        if scope is None:
            continue  # unmatched item kept only when broad-market relevant
        published_at, estimated = _parse_timestamp(item.findtext("{*}" + date_field), fetch_time)
        entries.append({
            "id": dedup_key(normalized),
            "source": source,
            "title": title[:TITLE_CAP],
            "url": normalized,
            "published_at": published_at,
            "published_at_estimated": estimated,
            "symbols": symbols,
            "scope": scope,
            "event_tags": event_tags(title),
        })
    return entries, None


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

def _default_session_factory() -> aiohttp.ClientSession:
    return aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=PER_FEED_TIMEOUT_SECONDS),
        headers={"User-Agent": USER_AGENT},
    )


class NewsService:
    """Bounded, fail-open RSS headline cache. Advisory context only."""

    def __init__(
        self,
        *,
        clock: Optional[Callable[[], float]] = None,
        session_factory: Optional[Callable[[], Any]] = None,
        feeds: Optional[List[Dict[str, Any]]] = None,
    ):
        self._clock = clock or time.time
        self._session_factory = session_factory or _default_session_factory
        self._feeds = feeds if feeds is not None else FEEDS
        self._session: Any = None
        self._items: Dict[str, Dict[str, Any]] = {}
        self._last_success: Optional[float] = None
        self._source_status: List[Dict[str, Any]] = [
            {"source": f.get("source", f["url"]), "ok": None, "error_code": None} for f in self._feeds
        ]
        self._lock = asyncio.Lock()

    # -- lifecycle ---------------------------------------------------------

    async def _get_session(self) -> Any:
        if self._session is None or getattr(self._session, "closed", False):
            self._session = self._session_factory()
        return self._session

    async def close(self) -> None:
        if self._session is not None and not getattr(self._session, "closed", False):
            await self._session.close()
        self._session = None

    async def _read_limited(self, resp: Any) -> bytes:
        chunks: List[bytes] = []
        total = 0
        async for chunk in resp.content.iter_chunked(65536):
            total += len(chunk)
            if total > MAX_BODY_BYTES:
                raise _BodyTooLarge()
            chunks.append(chunk)
        return b"".join(chunks)

    def _acceptable_content_type(self, resp: Any, body: bytes) -> bool:
        ctype = (getattr(resp, "content_type", "") or "").lower()
        if not ctype:
            # Absent header: sniff the XML declaration / root element instead
            # of trusting the body blindly.
            head = body[:512].lstrip().lower()
            return head.startswith(b"<?xml") or head.startswith(b"<rss") or head.startswith(b"<feed")
        return any(tok in ctype for tok in ("xml", "rss", "atom"))

    async def _refresh_one(self, feed: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        session = await self._get_session()
        try:
            async with session.get(
                feed["url"],
                allow_redirects=False,
                timeout=aiohttp.ClientTimeout(total=PER_FEED_TIMEOUT_SECONDS),
            ) as resp:
                if resp.status != 200:
                    return [], f"http_{resp.status}"
                try:
                    body = await self._read_limited(resp)
                except _BodyTooLarge:
                    return [], "body_too_large"
                if not self._acceptable_content_type(resp, body):
                    return [], "bad_content_type"
        except asyncio.CancelledError:
            raise
        except Exception:
            return [], "fetch_failed"
        return parse_feed_entries(feed, body, fetch_time=self._clock())

    async def refresh(self) -> None:
        async with self._lock:
            results = await asyncio.gather(
                *(self._refresh_one(feed) for feed in self._feeds),
                return_exceptions=True,
            )
            for result in results:
                if isinstance(result, asyncio.CancelledError):
                    raise result
            any_ok = False
            for feed, result in zip(self._feeds, results):
                label = feed.get("source", feed["url"])
                status = next((s for s in self._source_status if s["source"] == label), None)
                if status is None:
                    status = {"source": label, "ok": None, "error_code": None}
                    self._source_status.append(status)
                if isinstance(result, BaseException):
                    status["ok"], status["error_code"] = False, "fetch_failed"
                    continue
                entries, error_code = result
                if error_code:
                    status["ok"], status["error_code"] = False, error_code
                    continue
                status["ok"], status["error_code"] = True, None
                any_ok = True
                self._merge(entries)
            if any_ok:
                self._last_success = self._clock()
            self._trim_cache()

    def _merge(self, entries: List[Dict[str, Any]]) -> None:
        for entry in entries:
            existing = self._items.get(entry["id"])
            if existing is None:
                self._items[entry["id"]] = dict(entry)
                continue
            if entry["published_at"] > existing["published_at"]:
                existing["published_at"] = entry["published_at"]
                existing["published_at_estimated"] = entry["published_at_estimated"]
                existing["title"] = entry["title"]
                existing["url"] = entry["url"]
            if entry["source"] not in existing.setdefault("sources", [existing["source"]]):
                existing["sources"].append(entry["source"])
            existing["symbols"] = sorted(set(existing["symbols"]) | set(entry["symbols"]))
            existing["event_tags"] = sorted(set(existing["event_tags"]) | set(entry["event_tags"]))
            existing["scope"] = "symbol" if existing["symbols"] else "market"

    def _trim_cache(self) -> None:
        """Retention + cap, run once per refresh cycle (not per feed)."""
        now = self._clock()
        fresh = {k: v for k, v in self._items.items() if v["published_at"] >= now - CACHE_TTL_SECONDS}
        ordered = sorted(fresh.values(), key=lambda i: i["published_at"], reverse=True)
        self._items = {i["id"]: i for i in ordered[:CACHE_MAX_ITEMS]}

    # -- reads -------------------------------------------------------------

    def items(self, symbol: Optional[str] = None, active_symbols: Tuple[str, ...] = ()) -> List[Dict[str, Any]]:
        now = self._clock()
        wanted = set()
        if symbol:
            base = symbol[:-4] if symbol.endswith("USDT") else symbol
            wanted.add(base)
        for sym in active_symbols:
            wanted.add(sym[:-4] if sym.endswith("USDT") else sym)
        selected = []
        for item in self._items.values():
            if item["published_at"] < now - CACHE_TTL_SECONDS:
                continue
            if item["scope"] == "symbol":
                if not wanted & set(item["symbols"]):
                    continue
            selected.append(dict(item, sources=list(item.get("sources", [item["source"]]))))
        selected.sort(key=lambda i: i["published_at"], reverse=True)
        return selected[:MAX_API_ITEMS]

    def status(self) -> Dict[str, Any]:
        now = self._clock()
        stale = self._last_success is None or (now - self._last_success) > STALE_AFTER_SECONDS
        return {
            "fetched_at": self._last_success,
            "stale": stale,
            "source_status": [dict(s) for s in self._source_status],
            "sources_ok": bool(self._source_status) and all(s["ok"] is True for s in self._source_status),
        }

    def snapshot(self, symbol: Optional[str] = None, active_symbols: Tuple[str, ...] = ()) -> Dict[str, Any]:
        payload = self.status()
        payload["items"] = self.items(symbol=symbol, active_symbols=active_symbols)
        return payload
