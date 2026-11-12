# Crypto News Risk Advisory — Implementation Plan

## Goal
Show public-RSS crypto headlines and conservative “news event” context for broad crypto-market news plus the selected symbol and symbols with open signals. News is advisory context only: never create, modify, suppress, or execute a trade signal.

## Analysis Decisions
- **Approach:** Poll a fixed, shipped allowlist of two public feeds using the existing aiohttp client stack; parse with bounded stdlib XML handling; deduplicate into a bounded in-memory cache; classify broad-market vs symbol relevance; show source, age, and original article link. Publisher terms precheck must pass before source code implementation begins; that blocking gate is Task 3 Step 0.
- **Meaning of user-selected RSS (UPDATED 2026-11-11 after publisher sweep + user requirement "real market-moving sources only, no tin vịt"):** The user selected RSS as the news source type, not arbitrary URL entry. Task 0 publisher sweep found CoinDesk (ToS unreachable, 429), Cointelegraph (§3 prohibits automated scraping without authorization), Bitcoin Magazine/CryptoSlate/U.Today/NewsBTC/Blockworks/Bitcoin.com (explicit reproduction/automated-extraction restrictions), The Block/Decrypt (unverifiable) — none verifiable-allow. **Approved replacement set: (1) official regulator feeds — SEC press releases and Federal Reserve press releases (US federal government works, public domain by statute, and the highest-signal crypto market movers: ETF approvals, enforcement, FOMC/rates); (2) Google News RSS search feeds** whose in-feed license explicitly grants *"rendering Google News results within a personal feed reader for personal, non-commercial use"* — this dashboard is local, personal, non-commercial. To eliminate tin vịt, Google News items are **filtered by a tier-1 source allowlist** (title suffix): Bloomberg, Reuters, CNBC, WSJ, Financial Times, Fortune, Forbes, Barron's, MarketWatch, Benzinga, CoinDesk, Cointelegraph, The Block, Decrypt, Bitcoin Magazine. Feed URLs/queries are fixed in the code allowlist; no source-selection UI or user-entered URL is in scope. Only headline, source name, timestamp and outbound link are retained — Google News RSS carries no usable article summary, so the summary field is dropped from display; no full articles or images.
- **Alternatives considered:** paid sentiment API (requires key/cost; user selected public RSS); keyword-only signal veto (rejected: brittle and could hide valid signals); on-demand/per-scan RSS fetching (rejected: latency and scan coupling).
- **Risk controls:** Feed URLs are fixed, HTTPS-only, redirects disabled, short connection/read timeout, body-size limit enforced while reading the decompressed response, reject DTD/entity declarations before XML parsing, stdlib `xml.etree.ElementTree` only, no HTML rendering, and per-feed exceptions are isolated. News-service failure never blocks scanning or modifies technical signals. Render RSS text via DOM `textContent`; article links must pass HTTPS URL validation and use `rel="noopener noreferrer"`.
- **Scope:** Global market headlines plus headlines matching selected symbol and symbols with active signals. Only currently selected symbol is sent to the UI request; open-signal symbols are included in one API request from server state, without per-symbol polling. Symbol matching uses ticker token boundaries and an explicit alias map; no fuzzy substring matching. Missing dates are assigned fetch time and flagged `published_at_estimated=true`; invalid/future dates clamp to fetch time and remain flagged.
- **Advisory wording:** No directional sentiment labels. A conservative exact keyword set marks “CÓ TIN SỰ KIỆN — KIỂM TRA NGUỒN” only; it never says “risk is high”, never recommends LONG/SHORT, and never changes signal state. Keyword hits are transparent tags, not a validated risk score.
## Environment Context
- Language: Python 3.13 + vanilla JavaScript/HTML; aiohttp server and self-hosted TradingView chart.
- Tests: `PYTHONPATH=. ./venv/bin/pytest tests/ -q`; `node --test tests/chart_stream.test.js`.
- Lint/syntax: `python3 -m py_compile server.py binance_client.py technical_engine.py risk_manager.py config.py chart_renderer.py telegram_notifier.py`; no JS lint command configured.
- Build: no separate build step; `server.py` serves static HTML/JS.
- Branch: `feat/symbol-filtered-history`; HEAD `03aee3aac7684eaaa61283680dfe50b84c57314e` at planning time. (Current checkout HEAD may have advanced with subsequent history-arrow commits; confirm branch/HEAD before execution.)
- Conventions: aiohttp route handlers, async BinanceClient HTTP session, pytest-asyncio/aiohttp tests, vanilla JS module tests.
- Graph context: ready index, 238 nodes / 1204 edges. Existing `WebServerState.run_scan` is a high-coupling workflow (server-side scan entry; callers include API and background loop). Keep RSS polling isolated from scan decision logic; do not change `TechnicalEngine` or risk acceptance behavior.
- Provider: codebase-memory `futures-chart-scanner`, branch index refreshed 2026-11-10; Serena active on repository.

## Architecture & Contracts
- Fixed feed allowlist (not user/API supplied): `https://www.sec.gov/news/pressreleases.xml` (source label `SEC`); `https://www.federalreserve.gov/feeds/press_all.xml` (source label `Federal Reserve`); `https://news.google.com/rss/search?q=cryptocurrency+OR+bitcoin+OR+ethereum+when:2d&hl=en-US&gl=US&ceid=US:en` (source label `Google News — crypto`); `https://news.google.com/rss/search?q=crypto+regulation+OR+sec+OR+cftc+when:3d&hl=en-US&gl=US&ceid=US:en` (source label `Google News — regulation`). Each feed has its own source label and independent error status. Google News items are dropped unless the title suffix source is in the tier-1 allowlist `{Bloomberg, Reuters, CNBC, WSJ, Financial Times, Fortune, Forbes, Barron's, MarketWatch, Benzinga, CoinDesk, Cointelegraph, The Block, Decrypt, Bitcoin Magazine}` (case-insensitive exact match on the segment after the last ` - `); SEC and Fed items bypass that filter (official source).
- `NewsItem`: `{id, source, title, url, published_at, published_at_estimated, symbols: string[], scope: "market"|"symbol", event_tags: string[]}` (no summary field — Google News RSS carries no usable summary; headline-only display). Canonical URL normalization: parse URL; require allowed HTTPS host; lowercase hostname; remove default port; discard fragment; remove query keys case-insensitively when exactly `utm_*`, `ref`, `source`, `campaign`, `fbclid`, or `gclid`; preserve and lexically sort all other query pairs; strip trailing `/` from non-root path. `dedup_key` is this normalized article URL alone, so same URL across feeds collapses to one; keep entry with newest valid publication timestamp and merge matched symbols/tags while retaining source labels. `id` is SHA-256 of `dedup_key`. Entries without safe valid URL are dropped. Strip markup with stdlib `html.parser.HTMLParser` and decode entities (Google News `<description>` stubs are discarded); cap title at 300 characters; UI renders with `textContent`.
- XML: stdlib `xml.etree.ElementTree`; reject `<!DOCTYPE`/`<!ENTITY` declarations before parse; read/decompress at most 512 KiB; reject malformed XML. Disable redirects (`allow_redirects=False`). Accept HTTP 200 and RSS/Atom/XML content types only; if absent, sniff XML declaration or `<rss`/`<feed`. Article links must be absolute HTTPS, no credentials, host in `{news.google.com, www.sec.gov, sec.gov, www.federalreserve.gov, federalreserve.gov}`. SEC requires a declared `User-Agent` (`<product> <contact>`) per its fair-access policy; the service sends one. Cancel and close responses on timeout/shutdown.
- Poll every 5 minutes and immediately at startup; per-feed timeout 4 seconds; fetch feeds concurrently; cache cap 200 total items and 24 hours. `stale=true` until any successful refresh, or if last success is older than 15 minutes. Missing/invalid/future publication date uses fetch time and sets `published_at_estimated=true`.
- Symbol map: strip trailing `USDT`; exact token-boundary matching, case-insensitive, against title text only (Google News RSS provides no summary; SEC/Fed entries likewise match on title); never match URL slugs. Explicit aliases: `BTC=bitcoin`, `ETH=ethereum|ether`, `BNB=binance coin`, `SOL=solana`, `XRP=ripple`, `DOGE=dogecoin`, `ADA=cardano`, `AVAX=avalanche`, `LINK=chainlink`, `DOT=polkadot`, `TRX=tron`, `NEAR=near protocol`, `LTC=litecoin`, `BCH=bitcoin cash`, `SUI=sui`, `SHIB=shiba inu`, `PEPE=pepe`, `INJ=injective`, `OP=optimism`, `ARB=arbitrum`, `WLD=worldcoin`, `TON=toncoin`, `FIL=filecoin`, `APT=aptos`, `TIA=celestia`, `SEI=sei network`, `UNI=uniswap`. Bare ticker matching is enabled only for BTC, ETH, BNB, SOL, XRP, DOGE, ADA, AVAX, TRX, LTC, BCH, SUI, SHIB, PEPE, INJ, WLD, FIL, TIA, SEI. `LINK`, `NEAR`, `OP`, `ARB`, `UNI`, `DOT`, `TON`, `APT`, `ONE`, `ON`, `GAS`, `HOT`, `ARK`, `ATOM` match only explicit alias phrases (no bare ticker) to avoid ordinary-word/abbreviation collisions. A title matching multiple aliases tags all matched assets; unmatched item is global only if broad-market rule matches. Tests explicitly cover `click the link`, `university`, `arbitrage`, `original post`, `dot-com`, `connect the dots`, `tons of`, `apt to`, `sol` unrelated text, and valid alias matches.
- Broad-market exact phrases: `bitcoin`, `crypto market`, `cryptocurrency market`, `digital assets`, `crypto industry`, `federal reserve`, `fomc`, `inflation`, `interest rate`, `cpi`, `etf flows`, `crypto regulation`, `crypto hack`, `exchange outage`, `market liquidation`. These are relevance tags only.
- No directional sentiment/risk score. Event tags exact whole-phrase matches: `hack`, `exploit`, `security breach`, `lawsuit`, `ban`, `sanction`, `regulation`, `SEC`, `CFTC`, `ETF`, `delisting`, `insolvency`, `bankruptcy`, `liquidation`. Regulatory acronyms `SEC`, `CFTC`, `ETF` require uppercase exact token to avoid ordinary-word matches (`sec`, `etc`). Suppress a tag if match is immediately preceded within 3 tokens by `no`, `not`, `without`, `unlikely`, `denies`, `denied`, `rejects`, or `false`; do not infer polarity beyond this. Neutral chips: `VĨ MÔ`, `QUY ĐỊNH`, `BẢO MẬT`, `SÀN GIAO DỊCH`; show matched phrase. Always show note “Tin tức chỉ để tham khảo; có thể cũ, thiếu hoặc không liên quan. Tự mở nguồn kiểm chứng.” Negation and false positives remain possible.
- `GET /api/news?symbol=BTCUSDT` returns `{items: NewsItem[], fetched_at, stale, source_status: [{source,ok,error_code}], sources_ok}`. Validate query symbol using `MARKET_SYMBOL_RE`; no upstream request in route. Return broad-market + selected symbol + active-signal-symbol items, deduplicated, newest first, max 50. Missing query returns broad-market + active-signal headlines; invalid symbol returns 400.
- Feed outage is fail-open for scanner; cache reports stale/source status. Explicit invariant: **`WebServerState.run_scan` has zero calls to `NewsService`**; news polling is only in background lifecycle and test proves a failing refresh does not block a scan.
- UI uses no RSS-derived `innerHTML`; title, source, tags and timestamps assigned via `textContent`. Links use validated HTTPS URL, `target="_blank"`, `rel="noopener noreferrer"`. Show loading, empty, stale, partial-error and all-source-error states.
- News fetch/poll never changes signal status, Entry/SL/TP, risk sizing or trade execution.

## Task 1: Add bounded public RSS fetch, safe parsing, cache and API endpoint
Wave: 1
Status: completed (commit 360dffc)
Risk: medium
Dependencies: Task 0 (publisher terms allow recorded)
Model: pro
Files:
- Create: `news_service.py`
- Modify: `server.py`
- Test: `tests/test_news_service.py`
- Test: `tests/test_server.py`
Blast radius:
- `server.py` (API route, server state lifecycle)
- `news_service.py` (new isolated integration)
- `tests/test_news_service.py`
- `tests/test_server.py`
Acceptance:
- Fetches only the four fixed allowlist URLs (SEC, Federal Reserve, two Google News search queries), no redirects, under a 4-second per-feed timeout and 512 KiB decompressed body limit; SEC requests send a declared User-Agent.
- Parses RSS 2.0 (Atom tolerated); rejects DTD/entity payloads and unsafe/unapproved article URLs; sanitizes markup into plain text and caps title length.
- Google News items are dropped unless their title-suffix source is in the tier-1 allowlist (no tin vịt); SEC/Fed official items bypass that filter.
- Deduplicates same canonical article URL across feeds; drops missing/unsafe URLs.
- Matches symbol tickers/aliases only on token boundaries of the title; does not false-match short symbols embedded in unrelated words.
- Missing/invalid/future timestamps are marked estimated; cache has a numeric 15-minute stale threshold, 200-item cap and 24-hour retention.
- Failure/timeout/redirect of one feed preserves healthy-feed items and never prevents app startup or a technical scan.
- `/api/news` is cache-only, validates symbol, returns global + requested + active-signal-symbol items (max 50) plus source health; no request-path external HTTP.
- `WebServerState.run_scan` has no call to NewsService; enforce with an isolated service boundary and scan-outage test.
TDD:
- Behavior: feeds fetch and parse safely, then produce bounded, symbol-matched cache items deduplicated by canonical URL across sources while merging source attribution, symbol tags and event tags.
- Test file: `tests/test_news_service.py`
- Test names: `test_parse_rss_entry_plain_text_and_https_link`, `test_parse_atom_entry`, `test_rejects_dtd_and_entity_payload`, `test_streaming_body_limit_includes_compressed_payload`, `test_redirects_are_disabled`, `test_article_link_host_allowlist`, `test_google_news_source_allowlist_drops_untrusted_sources`, `test_deduplicates_same_article_across_feeds_and_merges_metadata`, `test_normalizes_tracking_query_fragment_and_trailing_slash`, `test_matches_ticker_alias_with_token_boundaries`, `test_does_not_false_match_short_ticker_in_word`, `test_ambiguous_tickers_only_match_explicit_aliases`, `test_broad_market_rule_does_not_match_unrelated_story`, `test_event_tag_sec_requires_uppercase_token`, `test_event_tag_negation_is_suppressed_within_three_tokens`, `test_missing_and_future_timestamps_are_estimated`, `test_cache_expires_and_marks_stale_at_15_minutes`, `test_one_feed_failure_preserves_other_feed_items`, `test_cancelled_refresh_closes_response`.
- API test names: `test_api_news_returns_global_active_and_selected_symbol_items`, `test_api_news_rejects_invalid_symbol_and_does_not_fetch_upstream` in `tests/test_server.py`.
- 🔴 RED command: `PYTHONPATH=. ./venv/bin/pytest tests/test_news_service.py tests/test_server.py -k 'news' -q`
- Expected 🔴 RED failure: missing `NewsService` import/service contract or specific behavior assertions; no setup/syntax failure.
- Minimal 🟢 GREEN change: isolated async service with the four fixed allowlist feeds (SEC declared User-Agent), redirect-disabled aiohttp, bounded streaming read, explicit DTD/entity reject before stdlib XML parse, host-validated links, Google News tier-1 source-suffix filter, exact token/alias matching on titles, SHA-256 URL dedup, and deterministic cache clock.
- Refactor candidates: lifecycle cleanup only after tests pass.
- Mocking: fake HTTP responses and injected clock are required for deterministic parsing, security, timeout, and stale-cache tests; no live RSS in unit tests.
Steps:
1. 🔴 RED: write one focused test per parser/security/dedup/match/freshness/error behavior and API contract.
   Command: `PYTHONPATH=. ./venv/bin/pytest tests/test_news_service.py tests/test_server.py -k 'news' -q`
   Expected: targeted failures for missing service and behavior.
2. 🟢 GREEN: implement `NewsService`, background refresh lifecycle and `/api/news` cache endpoint.
   Command: `PYTHONPATH=. ./venv/bin/pytest tests/test_news_service.py tests/test_server.py -k 'news' -q`
   Expected: PASS.
3. REFACTOR: verify refresh failures are isolated and request handlers use cache only.
4. VERIFY:
   - `PYTHONPATH=. ./venv/bin/pytest tests/test_news_service.py tests/test_server.py -k 'news' -q`
   - `python3 -m py_compile server.py news_service.py`
Checkpoint:
- Files: `news_service.py server.py tests/test_news_service.py tests/test_server.py`
- Commit: `feat(news): add safe cached public RSS news service`

## Task 2: Add news panel with Vietnamese UI labels
Wave: 2
Status: completed (commit 06b02ab)
Risk: medium
Dependencies: Task 1
Model: inherit
Files:
- Modify: `static/index.html`
- Modify: `static/chart_stream.js`
- Test: `tests/chart_stream.test.js`
- Test: `tests/test_server.py`
Acceptance:
- Dashboard shows a compact news panel with global headlines, selected-symbol headlines and active-signal-symbol headlines; source/time, clickable original article (headline only, no summary), loading/empty/stale/partial-error/all-error states.
- Headlines are inserted as text, never HTML; link must be HTTPS, `target=_blank`, `rel=noopener noreferrer`.
- Neutral topic chips only; no “high risk” or buy/sell label. Show fixed disclaimer and matching tag.
- Refresh on symbol change and every 5 minutes; no per-scan/per-symbol fetch.
- News has no influence on signal visibility, SL/TP or execution.
TDD:
- Behavior: dashboard safely renders current news cache and state.
- Test file: `tests/chart_stream.test.js` plus `tests/test_server.py`.
- Test names: `renderNewsItems_rendersUntrustedHeadlineAsTextAndOnlyHttpsLinks`; `test_api_news_returns_global_active_and_selected_symbol_items`.
- 🔴 RED command: `node --test --test-name-pattern='renderNewsItems_rendersUntrustedHeadlineAsTextAndOnlyHttpsLinks' tests/chart_stream.test.js && PYTHONPATH=. ./venv/bin/pytest tests/test_server.py -k api_news -q`
- Expected 🔴 RED failure: rendering helper and route are missing.
- Minimal 🟢 GREEN change: add standalone DOM rendering helper to `chart_stream.js`; mount compact panel in `index.html`; use only textContent and validated anchors.
- Refactor candidates: responsive layout/accessibility after green.
- Mocking: JS unit uses small fake document elements; route test injects fake service; browser QA uses controlled route fixture.
Steps:
1. 🔴 RED: add JS safe-render and API contract tests.
   Command: `node --test --test-name-pattern='renderNewsItems_rendersUntrustedHeadlineAsTextAndOnlyHttpsLinks' tests/chart_stream.test.js && PYTHONPATH=. ./venv/bin/pytest tests/test_server.py -k api_news -q`
   Expected: behavior failures, not setup/syntax.
2. 🟢 GREEN: add compact responsive panel, source/link/timestamp, topic chips, states and polling.
   Command: same focused command as RED.
   Expected: PASS.
3. REFACTOR: accessibility, responsive layout and abort in-flight request on symbol change.
4. VERIFY:
   - `PYTHONPATH=. ./venv/bin/pytest tests/ -q`
   - `node --test tests/chart_stream.test.js`
Checkpoint:
- Files: `static/index.html static/chart_stream.js tests/chart_stream.test.js tests/test_server.py`
- Commit: `feat(ui): show symbol-aware Vietnamese crypto news advisory`

## Task 0: Blocking RSS publisher terms and use gate
Wave: 0
Status: completed (2026-11-11) — original CoinDesk/Cointelegraph gate verdict: BLOCKED (see README). User approved source switch to SEC + Federal Reserve + Google News tier-1; new gate record committed in README.
Risk: medium
Dependencies: none
Model: inherit
Files:
- Modify: `README.md`
Blast radius:
- `README.md`
Acceptance:
- Before any code implementation, inspect current terms/robots/feed-use notices for both fixed RSS sources and record checked date, exact URLs, and source-specific allow/deny conclusion in README.
- If either source disallows display of headline + short cleaned summary with attribution/link, or terms are unclear, STOP and ask user for an approved source; no silent substitution or scraping.
- This is a hard prerequisite for Tasks 1–3.
TDD:
- Behavior: source permission decision is explicit and recorded before code starts; this is a manual policy gate, not code behavior.
- Test file: none; manual release-gate evidence is the README record.
- Test name: none.
- 🔴 RED command: none.
- Expected 🔴 RED failure: not applicable.
- Minimal 🟢 GREEN change: add dated, source-specific terms decision in README or STOP for clarification.
- Refactor candidates: none.
- Mocking: none; inspect current publisher policies.
Steps:
1. Inspect the live publisher terms, robots policy, and feed-use guidance for CoinDesk and Cointelegraph.
   Command: `sed -n '/## Crypto News RSS Advisory/,$p' README.md`
   Expected: source-specific checked-date and allow/deny record exists before any implementation; denied/unclear means stop.
2. Verify both sources allow the planned short headline/summary, attribution and link use.
3. VERIFY: no code tasks start until both decisions are recorded as allow.
Checkpoint:
- Files: `README.md`
- Commit: `docs(news): record RSS publisher terms decision`

## Task 3: Verify outage isolation and document RSS advisory limits
Wave: 3
Status: completed (commit 667a9eb)
Risk: low
Dependencies: Task 1, Task 2
Model: inherit
Files:
- Modify: `README.md`
- Test: `tests/test_server.py`
- Test: browser QA on running app
Blast radius:
- `README.md`
- `tests/test_server.py`
Acceptance:
- Document fixed RSS URLs, poll interval, stale/estimated-date behavior, alias limitations, false-positive/negation limits and advisory-only role.
- Browser verifies global headlines, symbol change, no-results, one-feed timeout; scan still emits technical signals while news is stale.
- No claim of profitable news sentiment without separate historical out-of-sample net-of-fees evaluation.
TDD:
- Behavior: feed outage cannot block technical scan.
- Test file: `tests/test_server.py`
- Test name: `test_news_feed_failure_does_not_block_scan`
- 🔴 RED command: `PYTHONPATH=. ./venv/bin/pytest tests/test_server.py -k news_feed_failure_does_not_block_scan -q`
- Expected 🔴 RED failure: missing outage isolation coverage.
- Minimal 🟢 GREEN change: add injected failing-feed scan test and concise docs.
- Refactor candidates: none.
- Mocking: fake feed transport required for deterministic timeout; publisher terms are verified manually in Task 0.
Steps:
1. 🔴 RED: add feed outage does not block scan test.
   Command: `PYTHONPATH=. ./venv/bin/pytest tests/test_server.py -k news_feed_failure_does_not_block_scan -q`
   Expected: FAIL until isolation is explicitly tested.
2. 🟢 GREEN: ensure background refresh errors are caught and document source limitations.
   Command: `PYTHONPATH=. ./venv/bin/pytest tests/test_server.py -k news_feed_failure_does_not_block_scan -q`
   Expected: PASS.
3. REFACTOR: none.
4. VERIFY:
   - `node --test tests/chart_stream.test.js`
   - `PYTHONPATH=. ./venv/bin/pytest tests/ -q`
   - `python3 -m py_compile server.py news_service.py`
Checkpoint:
- Files: `README.md tests/test_server.py`
- Commit: `docs(news): document RSS advisory limitations`

## No-Trade / Risk Contract
- RSS cannot generate orders, alter technical setup calculations, modify SL/TP or automatically increase leverage.
- A risk badge is not a direction prediction; missing/failed/stale news must be explicitly indicated.
- Do not say a headline “caused” price action; expose source timestamp and link.
- Do not ingest RSS markup into `innerHTML`; sanitize / text-render only.

## Feed Configuration and Publisher Use
- Fixed feeds (code allowlist only, maintainer-editable): SEC press releases `https://www.sec.gov/news/pressreleases.xml` and Federal Reserve press releases `https://www.federalreserve.gov/feeds/press_all.xml` — US federal government works, public domain by statute (17 U.S.C. §105), and the highest-signal market movers (ETF approvals, enforcement, FOMC/rates). Both verified live 2026-11-11 (HTTP 200 XML). Google News RSS search feeds `https://news.google.com/rss/search?q=cryptocurrency+OR+bitcoin+OR+ethereum+when:2d&hl=en-US&gl=US&ceid=US:en` and `https://news.google.com/rss/search?q=crypto+regulation+OR+sec+OR+cftc+when:3d&hl=en-US&gl=US&ceid=US:en` — in-feed license: *"made available solely for the purpose of rendering Google News results within a personal feed reader for personal, non-commercial use"* (verified 2026-11-11). Treasury/DOJ/CFTC feeds were unreachable or nonexistent from this network (000/403/404) and are excluded.
- Google News items pass only if the title-suffix source is in the tier-1 allowlist `{Bloomberg, Reuters, CNBC, WSJ, Financial Times, Fortune, Forbes, Barron's, MarketWatch, Benzinga, CoinDesk, Cointelegraph, The Block, Decrypt, Bitcoin Magazine}` — this is the tin-vịt gate (user requirement: real market-moving sources only). SEC/Fed items bypass that filter as official sources.
- No URL-entry UI, source-selection UI, HTML scraping, full-text extraction, or image copying. Poll all four feeds; show the publisher name and outbound source link. Headline + source + timestamp + link only; no summary display.
- Do not add RSS URLs from query parameters or user input (SSRF boundary).

## Plan Review: see final consolidated review section below

## Analysis Decisions
- Ceremony: bounded. The news integration is advisory and user explicitly selected public RSS and global+symbol coverage.
- Recommended shape: separate cached RSS service, cache-backed API, compact dashboard panel; no news veto in signal engine until historical net-of-fees evidence exists.
- Alternatives: paid sentiment API (rejected by user selection); RSS-derived signal veto (rejected as unvalidated/high-risk); on-demand fetch (rejected due latency and scan coupling).
- Persona checks: Architect — isolated service; Security — fixed allowlist, bounded XML/HTTPS parsing, text rendering; Performance — scheduled cache refresh, no per-symbol N+1; UX — source/time and stale state visible; Devil’s Advocate — feeds can be noisy/late, so advisory only.
- Verdict: CAUTION, mitigated by not changing trade signals and not claiming edge before net-of-fees backtest.

## Environment Context
- Language: Python 3.13 + vanilla JavaScript/HTML, aiohttp.
- TEST_CMD=`PYTHONPATH=. ./venv/bin/pytest tests/ -q`; NODE_TEST_CMD=`node --test tests/chart_stream.test.js`.
- LINT_CMD=`python3 -m py_compile server.py binance_client.py technical_engine.py risk_manager.py config.py chart_renderer.py telegram_notifier.py news_service.py`.
- BUILD_CMD: no separate build; served as static assets by `server.py`.
- Branch at scan: `feat/symbol-filtered-history`; HEAD `03aee3aac7684eaaa61283680dfe50b84c57314e`. Reconfirm actual branch/HEAD before execution; this snapshot predates subsequent feature commits.
- Conventions: aiohttp handlers, async client with mocked transport in tests, pytest-aiohttp route tests, vanilla JS module.
- Graph: ready 238 nodes / 1204 edges; existing `WebServerState.run_scan` and `create_app` are hotspots. Keep news polling isolated from the scan hot path.
- Serena: project activated; Python language server available.

## Task DAG
- Wave 0: Task 0 publisher terms/robots/feed-use gate; hard prerequisite before any implementation.
- Wave 1: Task 1 depends on Task 0 result `allow`.
- Wave 2: Task 2 depends on Task 1.
- Wave 3: Task 3 post-implementation outage test, documentation and browser QA; depends on Tasks 1 and 2.

## Plan Review
- Prior review blockers resolved: initial reviewer required explicit source/parser/matching/dedup/stale/UI tests; second reviewer found cross-feed dedup key conflict; third reviewer found source gate ownership, task title, URL normalization, ticker false-positive, SEC-case test, and duplicate-status inconsistencies. The plan now has Task 0 as a hard pre-implementation gate, canonical URL rules, denied ambiguous bare tickers, explicit test names and one authoritative review section.
- **Source-switch review (2026-11-11):** publisher sweep of 11 outlets (CoinDesk, Cointelegraph, The Block, Bitcoin Magazine, Decrypt, CryptoSlate, U.Today, NewsBTC, Blockworks, Bitcoin.com + Google News) found none of the editorial outlets verifiable-allow for automated headline display; Google News RSS carries an explicit personal feed-reader license; SEC/Fed are public-domain government works. User additionally required real market-moving sources only (no tin vịt), so Google News items are gated by a tier-1 source allowlist and official regulator feeds were added. Contract deltas: feed allowlist, article-host allowlist (`news.google.com`, `sec.gov`, `federalreserve.gov`), removal of summary display, title-only symbol matching, SEC declared User-Agent. Test deltas: `test_article_link_host_allowlist` and `test_google_news_source_allowlist_drops_untrusted_sources` replace `test_drops_unapproved_article_host`. No change to no-trade contract, dedup, matching, stale, or advisory-only invariants.
- Final review verdict: approved for execution after source-switch review; re-review still due at `/supergraph:review` before merge.
- User approval: granted 2026-11-11 (source switch to SEC + Federal Reserve + Google News tier-1 confirmed).

## User Gate
- Approval required before implementation.
- Choices: `yes`, `modify`, `reject`.

## Analysis Gate
- Analysis completed before planning. Plan includes selected public RSS scope and non-blocking advisory-only behavior.

## Scan Context
- CBM project: `futures-chart-scanner`.
- Index status: ready, refreshed 2026-11-10T14:01:54Z.
- Serena: activated on absolute repository path.
- Repository root: `/Users/trantandat/GIC/Freelancer/futures-chart-scanner`.
- Current worktree has `.supergraph-env` untracked; do not include it in feature commits.

## Plan Review Checks
- Task fields include exact files, focused test names, commands, expected RED failures, acceptance criteria and commits.
- Plan scope: 6 touched files plus one new service module (server, service, UI, README, 3 test files) and under 20-file escalation.
- No edits to trading algorithm or order execution path.
- Review status must be updated before implementation.

## Status
Approved 2026-11-11 (user confirmed source switch). Executing via Supergraph Team DAG: Wave 1 Task 1 → Wave 2 Task 2 → Wave 3 Task 3.

## Final Review Gate
After implementation: run fix loop, full unit tests, browser QA, and review before merge.
## Review Log (2026-11-11)
- Review range: 03aee3a..0474959 (Full tier: 10 files, +1,824 lines; graph: run_scan has zero NewsService callees — invariant verified via trace_path).
- Reviewer verdict: WITH_FIXES → all findings fixed in 0474959:
  - Important #1 event_tags `break` skipped later non-negated occurrences → break only after an accepted hit; regression test added.
  - Important #2 DTD/entity ASCII-substring gate bypassable via UTF-16 declaration → strict UTF-8/ASCII decode + XML-declaration encoding rejection before the gate; regression tests added.
  - Important #3 createNewsController abort/race untested → focused unit test with out-of-order fake fetch added (implementation was correct).
  - Minor: content-type header absent now sniffs XML declaration/root; cache trim runs once per refresh; news controller stops on pagehide; GAS test assertion made explicit (untracked, not alias-only); USER_AGENT documented as NEWS_USER_AGENT override.
- Final verification after fixes: pytest 72/72, node 30/30, py_compile OK, live 4/4 feeds 200, dashboard 200.
- Verdict: PASS (0 Critical, 0 Important remaining).
