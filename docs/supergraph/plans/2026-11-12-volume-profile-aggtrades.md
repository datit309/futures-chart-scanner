# Exact-Trade Volume Profile — Implementation Plan

## Goal
Render an interactive horizontal Volume Profile on the TradingView chart from Binance USDⓈ-M `aggTrades` (actual aggregated trades), with POC/VAH/VAL levels, a fixed rolling 24-hour window, clear partial-data states, and no influence on trading signals.

## Analysis Decisions
- **Approach:** Use the Binance public endpoint `GET /fapi/v1/aggTrades`; actual trade prices and quantities are allocated into price bins. Probe confirmed endpoint returns fields `p` (price), `q` (quantity), `T` (timestamp), and `a` (aggregate trade id), with max `limit=1000` and max look-back two days.
- **Scope:** Rolling last 24 hours only; do not silently stretch the window to 48h. Cap at 20 pages × 1000 items = 20,000 returned aggregate trades per request. Query page 1 with `startTime=start_ms`, `endTime=end_ms`, and `limit=1000` to anchor the time window and obtain the first aggregate id. For each subsequent request send `fromId=last_id+1` and `limit=1000` only; filter overlap/any returned row outside `[start_ms,end_ms]` locally. Stop once the returned trades reach/past `end_ms`, the endpoint returns a short/empty page, or the cap is reached. Require IDs to be strictly increasing within returned pages; deduplicate repeated IDs at page boundaries. An ID jump alone is NOT a coverage failure because aggregate IDs may advance without an item visible to this request; treat only repeated/backwards cursors or page-loop/no-progress as pagination failure. The API cannot prove the exact first-trade id at `start_ms`; therefore `start_covered=true` only if the first returned trade is within 300 seconds of `start_ms`, otherwise set `partial_reason=start_uncovered`. `caught_up=true` only after short/empty page or seeing a trade at/after `end_ms`. `complete=true` requires `start_covered AND caught_up AND not capped AND no pagination/error condition`; this deliberately prefers an honest partial badge to claiming completeness when the start boundary cannot be evidenced.
- **Data policy:** Cache by symbol (window fixed at 24h) for 60 seconds; coalesce concurrent same-symbol requests; serialize aggTrades fetches per BinanceClient with one shared semaphore and minimum request spacing; do not fetch on every kline tick, timeframe tick, or signal scan. Retry 429/418/5xx at most twice with bounded exponential backoff (honor numeric `Retry-After` only up to a fixed maximum); never retry invalid-symbol/time-window 4xx. Hard total deadline 25s/request, including retries, and 20-page cap; timeout returns current trades with `partial=true, partial_reason=timeout`. Validate symbol against existing `MARKET_SYMBOL_RE` before requests. Upstream failure never blocks `/api/chart`, scan or app startup.
- **Calculation:** Browser-only pure helper bins price from min/max returned trade prices into 128 equal-width bins (one fallback bin if range is zero), summing actual aggregate-trade `q` base quantity per bin. POC is max-quantity bin. Value Area expands outward from POC by adding the larger adjacent-quantity bin until >=70% total quantity; deterministic tie-break lower-price side first. Server does not calculate bins, POC, VAH or VAL; it returns raw validated trades and coverage metadata only.
- **Rendering:** Draw the horizontal histogram as a canvas overlay positioned at the chart pane's right edge (not a million TradingView line entities). Align bins using TradingView `priceToCoordinate` where supported; redraw on data/range/resize/crosshair lifecycle events without blocking chart interaction. POC/VAH/VAL as three horizontal visual lines with labels. Responsive cap histogram width and opacity so candles remain readable.
- **Truthfulness:** This uses real aggregate trades (not approximate allocation of candle volume), but Binance aggregate trades are not an order-book/footprint profile. Use normalized base quantity (`q`), not notional quote volume; label the metric accordingly. It is a visual tool only; do not change or imply signal quality.
- **Alternatives rejected:** (1) OHLCV volume distributed uniformly over price: cheap but only approximate (user requested real source); (2) unlimited 48h aggTrades pull: unbounded API calls/latency and Binance hard limit; (3) persist trades in SQLite: unnecessary state and migration for a 60-second rolling view.

## Architecture & Contracts
- `BinanceClient.get_aggregate_trades(symbol,start_time_ms,end_time_ms,page_cap=20)` returns raw trades plus coverage `{symbol,window_start_ms,window_end_ms,partial,partial_reason,pages,trade_count,oldest_trade_time,newest_trade_time,start_covered,caught_up,trades:[{id,price,quantity,timestamp}]}`. Page 1 uses time bounds; subsequent pages use `fromId=last_id+1` only. Validate symbol, cap page size at 1000, dedupe IDs, require monotonic progress, but do not treat an ID gap alone as missing data. The API cannot prove the exact first-trade id at `start_ms`; therefore `start_covered=true` only if the first returned trade is within 300s of `start_ms`, otherwise set `partial_reason=start_uncovered`. A short/empty later page only means caught up, never proves start coverage.
- Binance USDⓈ-M `/fapi/v1/aggTrades` request weight is treated as 20 per request (verify/update against Binance documentation at implementation). A per-client semaphore of 1 serializes aggregate-trade paging across symbols and a minimum 100ms inter-request spacing plus the 20-page cap bounds a single 24h profile; absolute deadline 25s. Retry 429/418/5xx at most twice with bounded exponential backoff (honor numeric `Retry-After` only up to 2s); do not retry other 4xx. Errors return current rows plus `partial=true`, never block chart or scanner. Keep fetch opt-in/on-demand because request weight consumes shared Binance IP budget.
- Cache-backed `GET /api/volume-profile?symbol=BTCUSDT` returns raw trades + coverage metadata only: `{symbol,window_start_ms,window_end_ms,fetched_at,partial,partial_reason,pages,trade_count,oldest_trade_time,newest_trade_time,start_covered,caught_up,trades:[{id,price,quantity,timestamp}]}`. No server-side bins/POC/VAH/VAL. HTTP 400 for invalid symbol. Cache key `{symbol,24h-window-anchor}` with 60s TTL, same-key in-flight coalescing, cap-aware memory (<=20k rows per cached symbol, bounded number of symbols), explicit cache eviction. Empty valid data is distinct from error and partial coverage.
- Browser helper `buildVolumeProfile(trades,{binCount:128,valueAreaPercent:0.70})` is the only bin/POC/VAH/VAL calculator, pure deterministic code with no DOM or signal coupling.
- Browser controller fetches/cache-handles endpoint only when overlay is enabled and selected symbol changes or TTL expires; abort in-flight request on symbol switch; no request on every market tick or chart resolution event. Keep the last valid profile when only resolution changes because the profile window is fixed 24h.
- Renderer reuses the existing TradingView pane and chart price/time coordinate accessors (`drawZoneBands` precedent); never edits vendor `static/charting_library`. Use a pointer-events-none canvas overlay, DPR-aware resize, redraw on chart resize/profile update/range change, and clear listeners/RAF on disable/symbol switch/pagehide. If price coordinate conversion is unavailable at the active scale, show unavailable state rather than misplacing profile. Responsive width <=24% and 180px desktop, <=28% and 112px under 640px; labels do not force horizontal page overflow.
- Overlay shows “VOLUME PROFILE · AGGTRADES · 24H”, base quantity, POC, VAH/VAL and coverage badge (`ĐẦY ĐỦ`, `MỘT PHẦN · n trades`, `CHƯA CÓ GIAO DỊCH`, `LỖI TẢI`). Partial reasons distinguish `start_uncovered`, cap and upstream failure. Toggle off hides/clears the profile; failures never affect signals.
- Signal algorithm, SL/TP, scan flow, and database signal rows remain unchanged.

## Environment Context
- Language: Python 3.13 + vanilla JavaScript/HTML; aiohttp server and self-hosted TradingView Advanced Chart.
- TEST_CMD: `PYTHONPATH=. ./venv/bin/pytest tests/ -q`
- NODE_TEST_CMD: `node --test tests/chart_stream.test.js`
- LINT_CMD: `python3 -m py_compile server.py binance_client.py technical_engine.py risk_manager.py config.py chart_renderer.py telegram_notifier.py news_service.py signal_tracker.py`
- BUILD_CMD: no build step; server.py serves static assets.
- Branch: `feat/symbol-filtered-history`; current origin may lag; do not alter unrelated commits.
- Conventions: aiohttp route handlers, async BinanceClient, tests with fake `_fetch_json`/transport, vanilla ES modules, TradingView drawing helpers in `chart_stream.js`, HTML integration in `static/index.html`.
- Graph context: index project `Users-trantandat-GIC-Freelancer-futures-chart-scanner`, status ready after reindex 2026-11-12; static package is a UI entry layer, chart_stream has core boundary to bundled TradingView; do not edit `static/charting_library/**`.
- Blast radius: `binance_client.py`, `server.py`, `static/chart_stream.js`, `static/index.html`, `tests/test_binance_client.py`, `tests/test_server.py`, `tests/chart_stream.test.js` (7 files; no engine, risk manager, signal tracker, or DB schema changes).

## Task 1: Fetch and cache bounded aggTrades for rolling 24h
Wave: 1
Status: pending
Risk: medium
Dependencies: none
Model: inherit

Files:
- Modify: `binance_client.py`
- Modify: `server.py`
- Test: `tests/test_binance_client.py`
- Test: `tests/test_server.py`

Blast radius:
- `binance_client.py` (public REST client)
- `server.py` (profile API cache/route; chart routes untouched)
- `tests/test_binance_client.py`
- `tests/test_server.py`

Acceptance:
- Only validates/requests a USDT futures symbol; endpoint path is fixed `/fapi/v1/aggTrades` and user input cannot control URL/host.
- Pages with `limit=1000` and `fromId`, never exceeds 20 pages/20,000 unique trades, dedupes ids, terminates on 24h start or exhausted page, and never loops on repeated/non-monotonic ids.
- Returns actual p/q/T data plus explicit coverage metadata and partial reason; upstream error/timeout is contained and does not block `/api/chart`, scan, or app startup.
- Cache TTL is 60 seconds; same-key concurrent requests coalesce; API validates bad symbols with HTTP 400.

TDD:
- Behavior: bounded pagination and explicit completeness metadata from actual Binance aggTrades.
- Test file: `tests/test_binance_client.py`
- Test names: `test_aggregate_trades_page_one_uses_time_boundary`, `test_aggregate_trades_start_uncovered_marks_partial`, `test_aggregate_trades_deadline_marks_timeout_partial`, `test_aggregate_trades_followup_uses_from_id_only_and_dedupes_boundary`, `test_aggregate_trades_short_page_after_start_is_caught_up`, `test_aggregate_trades_empty_start_window_is_complete_empty`, `test_aggregate_trades_page_cap_sets_partial_with_coverage`, `test_aggregate_trades_repeated_or_backwards_cursor_sets_no_progress`, `test_aggregate_trades_malformed_rows_are_dropped_and_mark_partial`, `test_aggregate_trades_retries_429_twice_then_returns_partial`, `test_aggregate_trades_400_is_not_retried`, `test_volume_profile_cache_ttl_and_inflight_coalescing`, `test_volume_profile_invalid_symbol_returns_400`, `test_volume_profile_upstream_failure_does_not_block_chart_or_scan`.
- 🔴 RED command: `PYTHONPATH=. ./venv/bin/pytest tests/test_binance_client.py -k aggregate_trades_page_one_uses_time_boundary -q`
- Expected 🔴 RED failure: missing `BinanceClient.get_aggregate_trades`; tests must exist before running the command so it fails on the intended missing method, never pytest exit 5 from zero matches.
- Minimal 🟢 GREEN change: fixed-endpoint API method with first-page time query, subsequent `fromId`-only pagination, monotonic progress guard, bounded backoff and deadline; add cache-backed route.
- Refactor candidates: reusable endpoint query helper only if it reduces duplicate code without changing existing kline behavior.
- Mocking: fake `_fetch_json` with deterministic page IDs/timestamps/errors; no live API in unit tests.

Steps:
1. 🔴 RED: add the explicit test cases above; run the first focused test and confirm intended missing-method failure.
   Command: `PYTHONPATH=. ./venv/bin/pytest tests/test_binance_client.py -k aggregate_trades_page_one_uses_time_boundary -q`
   Expected: FAIL because method is absent.
2. 🟢 GREEN: implement pagination, boundary metadata, retry policy, cap, cache/coalescing and endpoint.
   Command: `PYTHONPATH=. ./venv/bin/pytest tests/test_binance_client.py tests/test_server.py -k 'aggregate_trades or volume_profile' -q`
   Expected: PASS.
3. REFACTOR: verify 60-second TTL, in-flight coalescing and isolated failures.
4. VERIFY:
   - `PYTHONPATH=. ./venv/bin/pytest tests/test_binance_client.py tests/test_server.py -q`
   - `python3 -m py_compile binance_client.py server.py`

Checkpoint:
- Files: `binance_client.py server.py tests/test_binance_client.py tests/test_server.py`
- Commit: `feat(data): add bounded cached Binance aggTrades profile endpoint`

## Task 2: Calculate POC and 70% Value Area from trades
Wave: 2
Status: pending
Risk: medium
Dependencies: Task 1
Model: inherit

Files:
- Modify: `static/chart_stream.js`
- Test: `tests/chart_stream.test.js`

Blast radius:
- `static/chart_stream.js` (pure calculator helper)
- `tests/chart_stream.test.js`

Acceptance:
- `buildVolumeProfile` bins actual aggTrade prices and sums actual base quantities; never distributes OHLCV volume.
- POC is the max-quantity bin midpoint; 70% value area expands to the larger adjacent quantity bin until target quantity is reached.
- Handles empty/all-invalid trades, one-price range, bin edges, deterministic ties, and malformed/non-finite price/quantity.
- Returns stable `{bins,poc,vah,val,totalQuantity,tradeCount}` output; partial coverage remains separate from calculation metadata.

TDD:
- Behavior: known trade fixtures produce deterministic bins, POC, VAH and VAL.
- Test file: `tests/chart_stream.test.js`
- Test names: `buildVolumeProfile calculates POC and 70 percent value area from trade fixtures`, `buildVolumeProfile handles empty malformed and single-price inputs`, `buildVolumeProfile resolves equal-volume ties deterministically`.
- 🔴 RED command: `node --test --test-name-pattern='buildVolumeProfile calculates POC' tests/chart_stream.test.js`
- Expected 🔴 RED failure: `buildVolumeProfile` missing; test file is verified to contain a matching test name before command execution.
- Minimal 🟢 GREEN change: pure deterministic 128-bin calculator and adjacent-bin value-area expansion.
- Refactor candidates: extract bin-index helper only if it improves readability.
- Mocking: none; deterministic trade fixtures.

Steps:
1. 🔴 RED: add exact expected-bin/POC/VA fixtures and malformed/edge tests.
   Command: `node --test --test-name-pattern='buildVolumeProfile calculates POC' tests/chart_stream.test.js`
   Expected: FAIL because helper is absent.
2. 🟢 GREEN: implement `buildVolumeProfile` with clamping for max-price bin and deterministic lower-price tie rule.
   Command: `node --test --test-name-pattern='buildVolumeProfile' tests/chart_stream.test.js`
   Expected: PASS.
3. REFACTOR: verify total binned quantity equals sum of accepted raw quantities within floating tolerance.
4. VERIFY:
   - `node --test tests/chart_stream.test.js`

Checkpoint:
- Files: `static/chart_stream.js tests/chart_stream.test.js`
- Commit: `feat(chart): calculate POC and value area from aggTrades`

## Task 3: Render profile overlay, controls, status and cache-aware browser loading
Wave: 3
Status: pending
Risk: medium
Dependencies: Task 1, Task 2
Model: inherit

Files:
- Modify: `static/chart_stream.js`
- Modify: `static/index.html`
- Test: `tests/chart_stream.test.js`

Blast radius:
- `static/chart_stream.js` (controller/canvas profile renderer)
- `static/index.html` (overlay toggle, status and accessible labels)
- `tests/chart_stream.test.js`

Acceptance:
- “Volume Profile · AggTrades · 24H” toggle renders right-aligned histogram and POC/VAH/VAL; width <= 180 CSS px desktop / 112 px <=640px, DPR-aware canvas, pointer-events none.
- Uses existing widget/container and TradingView pane coordinate API path already used by `drawZoneBands`; if price coordinate conversion returns null/unavailable, show unavailable state and draw no incorrect-price profile.
- Status visibly distinguishes loading, complete, partial with reason/trade count, valid empty window, unavailable/error, and disabled.
- Profile only fetches on enable, selected-symbol change, or 60s expiry; switching symbol aborts stale request; changing timeframe/range redraws cached 24h profile without refetch.
- Canvas/observer/listener cleanup on disable, symbol switch, and `pagehide`; Volume Profile toggle does not control or alter independent Volume Surge markers.
- No signal-engine/scan dependency.

TDD:
- Behavior: request lifecycle handles rapid symbol changes, cache hits, partial/error/empty states; profile renderer stays pointer-transparent and removable.
- Test file: `tests/chart_stream.test.js`
- Test names: `volumeProfileController aborts stale symbol response and preserves partial state`, `volumeProfileController caches for 60 seconds and refetches after expiry`, `renderVolumeProfile reports empty partial and unavailable states`, `renderVolumeProfile clears canvas when disabled`.
- 🔴 RED command: `node --test --test-name-pattern='volumeProfileController aborts stale symbol' tests/chart_stream.test.js`
- Expected 🔴 RED failure: profile controller/renderer is absent; matching test name exists before command execution.
- Minimal 🟢 GREEN change: cache-aware abortable fetch controller, pure canvas renderer with injectable chart coordinate adapter, accessible state label/toggle.
- Refactor candidates: shared listener cleanup helper if existing overlay code supports reuse.
- Mocking: fake fetch, fake chart-coordinate adapter and fake canvas context; live browser QA separately.

Steps:
1. 🔴 RED: add controller cache/abort and renderer state/cleanup tests.
   Command: `node --test --test-name-pattern='volumeProfileController aborts stale symbol' tests/chart_stream.test.js`
   Expected: FAIL because controller/renderer are absent.
2. 🟢 GREEN: add controller, canvas layer and accessible toggle/status in `index.html`.
   Command: `node --test --test-name-pattern='volumeProfileController|renderVolumeProfile' tests/chart_stream.test.js`
   Expected: PASS.
3. REFACTOR: verify redraw events do not add chart entities, event listeners, network calls or horizontal overflow.
4. VERIFY:
   - `node --test tests/chart_stream.test.js`
   - `PYTHONPATH=. ./venv/bin/pytest tests/test_server.py -k volume_profile -q`

Checkpoint:
- Files: `static/chart_stream.js static/index.html tests/chart_stream.test.js`
- Commit: `feat(ui): render aggTrades Volume Profile with POC VAH VAL and coverage state`

## Task 4: End-to-end QA, docs, verification and review evidence
Wave: 4
Status: pending
Risk: low
Dependencies: Task 3
Model: inherit

Files:
- Modify: `README.md`
- Test: `tests/test_server.py`
- Test: `tests/chart_stream.test.js`

Blast radius:
- `README.md`
- `tests/test_server.py`
- `tests/chart_stream.test.js`

Acceptance:
- README explains actual aggTrades input, base-quantity bins, 24h window, 20k cap, 60s cache, POC/70% VA, 300s start-boundary coverage tolerance, partial semantics, endpoint weight/retry limits, and that profile is not a signal.
- Browser QA uses the existing app at `http://127.0.0.1:8766`, routes `/api/volume-profile` to deterministic complete/partial/empty/error fixture JSON, and records screenshots/evidence for 1280x800 desktop and 390x844 narrow viewport.
- QA verifies toggle on/off, actual horizontal bars + POC/VAH/VAL, all 4 status classes, symbol change abort, no extra requests on timeframe/range change, no page horizontal overflow, and unchanged signal counts/payload.
- API cap remains <=20 pages and failure does not block `/api/chart` or `/api/scan`.
- Full Python/Node tests and compile pass.

TDD:
- Behavior: profile failure/partial states are isolated from chart and scanner.
- Test file: `tests/test_server.py`
- Test names: `test_volume_profile_upstream_failure_does_not_block_chart_or_scan`, `test_volume_profile_marks_page_cap_partial`, `test_volume_profile_invalid_symbol_returns_400`.
- 🔴 RED command: `PYTHONPATH=. ./venv/bin/pytest tests/test_server.py -k test_volume_profile_upstream_failure_does_not_block_chart_or_scan -q`
- Expected 🔴 RED failure: route/cache isolation behavior is absent; test is confirmed by collection before execution.
- Minimal 🟢 GREEN change: fake transport route tests and README limitation/QA documentation.
- Refactor candidates: none.
- Mocking: fake Binance transport and deterministic response fixtures; browser QA network route fixture for visual states.

Steps:
1. 🔴 RED: add route isolation, page-cap partial and invalid-symbol tests.
   Command: `PYTHONPATH=. ./venv/bin/pytest tests/test_server.py -k volume_profile -q`
   Expected: FAIL until route behaviors are implemented.
2. 🟢 GREEN: document exact source/limitations and run browser QA at both specified viewports.
   Command: `PYTHONPATH=. ./venv/bin/pytest tests/test_server.py -k volume_profile -q`
   Expected: PASS.
3. REFACTOR: none.
4. VERIFY:
   - `PYTHONPATH=. ./venv/bin/pytest tests/ -q`
   - `node --test tests/chart_stream.test.js`
   - `python3 -m py_compile server.py binance_client.py technical_engine.py risk_manager.py signal_tracker.py news_service.py`

Checkpoint:
- Files: `README.md tests/test_server.py tests/chart_stream.test.js`
- Commit: `docs(volume-profile): document aggTrades profile limitations and QA`

## Task DAG
- Wave 1: Task 1 bounded aggTrades client and cache/API.
- Wave 2: Task 2 pure trade-bin calculator depends on Task 1.
- Wave 3: Task 3 overlay/controller depends on Task 1 and Task 2.
- Wave 4: Task 4 browser QA, documentation and final verification depends on Task 3.

## Plan Review
- Analysis ceremony: spike; verified endpoint `GET /fapi/v1/aggTrades` returns `{a,p,q,T,m}`, supports `limit<=1000`, accepts `startTime+endTime` on page 1 and accepts `fromId+1` pagination on subsequent pages. A 72h time query returns HTTP 400 `-4166` “Search window is restricted to recent 2 days only.”
- Independent review initially returned NEEDS_CHANGES because start-boundary completeness, rate limits, server-vs-browser calculation ownership, TDD cases, and browser setup were underspecified.
- **Review changes applied:** boundary coverage requires first trade within 300s of window start (else explicit `start_uncovered` partial), with named negative-case and timeout tests; subsequent pages use `fromId` only and ID gaps alone are accepted; short/empty page means caught-up only, never proves start coverage. Unified hard deadline at 25s and added shared-IP request budget/throttle/retry policy. API returns raw trades/coverage only; browser owns bins/POC/VAH/VAL. Added explicit pagination/cache/error/bin/tie/partial/abort/cleanup tests and exact desktop+mobile QA setup/evidence acceptance. Renderer uses existing `drawZoneBands` coordinate precedent and does not edit vendor library.
- User decision: actual `aggTrades`, rolling 24h, cap 20,000 trades; no OHLCV approximation.
- Risks: high-activity markets may hit cap or boundary tolerance and produce partial profile; mitigation is a prominent partial badge, immutable cap, and no signal filtering. Trade bins use base quantity, not order-side footprint or quote notional; documentation must say so.
- Graph risk: no signal engine/SL/TP/scan coupling; UI calls a cache-backed route. `static/charting_library/**` is an external bundled core and prohibited from edits.
- **Plan review verdict: APPROVED** — first review NEEDS_CHANGES; revised boundary/cursor/partial semantics, rate limits, single calculation ownership, test coverage and browser QA. Second review found two remaining blockers (deadline mismatch and missing boundary/timeout test cases); unified deadline at 25s, added both explicit tests, final re-review APPROVED.

## User Gate
- User approved approach: actual `aggTrades`, rolling 24h, cap 20,000 trades; no OHLCV approximation.
- Plan approval: granted by user (“ok”) before planning; confirmed chosen scope: 24h, 20k cap, actual aggTrades.
- Execution gate: user approval for the finally reviewed plan required before `/execute`.
- Choices: `yes`, `modify`, `reject`.

## Status
Plan revisions complete; final independent review pending. Do not implement until final review and user execution approval.
