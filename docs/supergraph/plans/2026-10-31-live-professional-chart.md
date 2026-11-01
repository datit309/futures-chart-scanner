# Plan: Professional Realtime Futures Chart

## Analysis Decisions
- Approach: Keep Lightweight Charts 4.2.2, refine overlays, and add Binance USDⓈ-M public kline WebSocket for the selected symbol/timeframe. This directly addresses the user's selected A option and explicit request for realtime.
- Alternatives: Advanced Charts access is not established; REST polling is not true realtime; auto-scanning every market tick is wasteful and out of scope.
- Live candle behavior: update the currently forming candle and show a visibly provisional state; mark signal/analysis confirmed only after kline close. No order execution.
- Manual chart drawing tools are deferred; this pass focuses on clear auto overlays and live data.
- Frontend tests: keep server/protocol tests in pytest; extract candle merge + overlay throttle into `static/chart_stream.js` as a browser/Node-compatible ES module, test it with Node built-in `node --test`. Browser visual, zoom/pan retention, canvas geometry and mobile layout are verified through browser-agent manual automation, not claimed as pytest coverage.

## Architecture & Contracts
- REST history: existing `/api/chart?symbol=...&timeframe=...&limit=...` supplies initial ordered klines.
- Realtime transport: add `/ws/market?symbol=BTCUSDT&timeframe=15m`. Supported intervals are exactly `15m`, `1h`, and `4h` (passed literally to Binance stream); symbols must match `^[A-Z0-9]{2,30}USDT$` and be present in the cached active USDT perpetual universe. Send status events and normalized candle events `{type, symbol, timeframe, candle:{time,open,high,low,close,volume,closed,event_time}}`. On browser disconnect cancel and close upstream connection. Reconnect with capped exponential backoff (1, 2, 4, 8, 16, max 30 seconds), reset after a successful connection, honor Retry-After/server close information where available, and do not spin on invalid requests or auth/rate-limit closes; browser reloads recent history after reconnect to heal gaps.
- History/live merge: for same candle timestamp replace latest bar via LWC `series.update`; append only newer timestamps; ignore older events. Preserve chart visible range on timeframe/data refresh; `fitContent()` only on initial load or explicit reset.
- User requested true realtime: apply incoming kline ticks to the displayed candle immediately; throttle expensive overlays and provisional analysis to at most 4 updates/sec. Implement this pure update/throttle logic in a small browser ES module and test it with Node's built-in test runner. Current-open-candle signals are labeled provisional; recalculate/finalize on close. Existing top-N discovery scanner remains periodic and does not run on every market tick.
- Upstream safety: one subscription per selected browser chart, bounded reconnect backoff, no parallel reconnect attempts; no reconnect storm on HTTP/WS rate-limit or policy close; respect `Retry-After` when present. Public market stream only; do not subscribe per watched pair.
- Chart overlays: use LWC 4.2 API. Choose at most one resistance/support trendline deterministically: touches descending, anchor recency descending, then residual ascending. Render S/R and FVG as translucent canvas bands synchronized with chart coordinate transforms; redraw on resize, visible time range, and scale changes. Add accessible toggles for trendlines, zones/FVG, trade levels. Avoid duplicate series/labels.
- Contract/watchlist: only active `TRADING`, `PERPETUAL`, quoteAsset `USDT` symbols. Join exchangeInfo with 24h tickers and return `lastPrice`, `priceChangePercent`, `quoteVolume`; preserve existing `/api/symbols` `symbols` key and add metrics.
- Status: only show LIVE when stream is connected and receiving updates; show connecting/reconnecting/stale with last update time. No API keys or trading permissions.

## Environment Context
- Language: Python backend + vanilla HTML/CSS/JavaScript frontend
- Runtime: aiohttp; Lightweight Charts 4.2.2 via CDN
- Tests: `PYTHONPATH=. ./venv/bin/pytest tests/ -q`
- Lint/format/build: none configured
- Branch: currently `main`; execute only after creating feature branch `feat/realtime-chart`
- Commit style: Conventional Commits, e.g. `feat(scanner): ...`
- Graph: `futures-chart-scanner`, 166 nodes / 663 edges, ready. Key boundary: `server.py` ↔ `BinanceClient` and `TechnicalEngine`; chart page is excluded from Python graph. `/api/chart` returns static REST payload; current background loop periodically broadcasts signals, not candle ticks. Changed scope stays under 20 files. No hub mutation identified.

## Task 1: Deterministic market-structure line selection
Wave: 1
Status: completed
Risk: low
Dependencies: none
Model: inherit
Files:
- Modify: `technical_engine.py`
- Modify: `tests/test_technical_engine.py`
Blast radius:
- `technical_engine.py`
Acceptance:
- Add pure selector choosing one strongest support and resistance line using touches, recency, and residual tie-break.
- Equivalent duplicate lines are not returned; existing detection behavior remains compatible.
TDD:
- Behavior: stable choice among competing trendlines
- Test file: `tests/test_technical_engine.py`
- Test name: `test_select_strongest_trendlines_is_deterministic`
- 🔴 RED command: `PYTHONPATH=. ./venv/bin/pytest tests/test_technical_engine.py::test_select_strongest_trendlines_is_deterministic -q`
- Expected 🔴 RED failure: selector missing
- Minimal 🟢 GREEN change: add deterministic pure function and test
- Refactor candidates: none
- Mocking: none
Steps:
1. 🔴 RED: add synthetic competing lines; run focused test; expect missing selector
2. 🟢 GREEN: implement selector; focused test passes
3. REFACTOR: none
4. VERIFY: `PYTHONPATH=. ./venv/bin/pytest tests/test_technical_engine.py -q`
Checkpoint:
- Files: `technical_engine.py` `tests/test_technical_engine.py`
- Commit: `feat(scanner): select strongest market structure lines`

## Task 2: Filter contract universe and expose watchlist metrics
Wave: 1
Status: completed
Risk: medium
Dependencies: none
Model: inherit
Files:
- Modify: `binance_client.py`
- Modify: `server.py`
- Modify: `tests/test_binance_client.py`
- Modify: `tests/test_server.py`
Blast radius:
- `binance_client.py` `server.py`
Acceptance:
- Restrict symbols to `TRADING` USDⓈ-M `PERPETUAL` contracts with quoteAsset `USDT`.
- Return last price, 24h percent change, and quote volume joined by symbol; preserve `/api/symbols`' current `symbols` key and add ticker metrics.
- Missing ticker rows are handled; non-trading, delivery, and non-USDT markets excluded.
TDD:
- Behavior: only eligible USDT perpetuals rank in watchlist and carry 24h metrics
- Test file: `tests/test_binance_client.py`
- Test name: `test_top_symbols_filters_contracts_and_merges_tickers`
- 🔴 RED command: `PYTHONPATH=. ./venv/bin/pytest tests/test_binance_client.py::test_top_symbols_filters_contracts_and_merges_tickers -q`
- Expected 🔴 RED failure: exchange metadata filtering/merge absent
- Minimal 🟢 GREEN change: merge mocked exchangeInfo and 24h ticker rows
- Refactor candidates: bounded exchangeInfo cache if needed
- Mocking: required for deterministic public API payloads
Steps:
1. 🔴 RED: test valid, inactive, delivery, wrong quote, missing ticker cases
2. 🟢 GREEN: implement filtered merge and endpoint response
3. REFACTOR: none unless duplicate conversion logic appears
4. VERIFY: `PYTHONPATH=. ./venv/bin/pytest tests/test_binance_client.py tests/test_server.py -q`
Checkpoint:
- Files: `binance_client.py` `tests/test_binance_client.py`
- Commit: `feat(scanner): filter perpetual universe and add ticker metrics`

## Task 3: Relay Binance Futures live kline stream
Wave: 2
Status: completed
Risk: medium
Dependencies: none
Model: inherit
Files:
- Modify: `server.py`
- Modify: `tests/test_server.py`
Blast radius:
- `server.py`
Acceptance:
- Add `/ws/market`; allowed timeframes exactly `15m`, `1h`, `4h`; symbol regex + membership in active USDT perpetual universe are checked before upstream connect.
- Relay normalized kline events and connecting/connected/reconnecting/stale status.
- Cancel/close upstream on downstream disconnect; reconnect delays are capped exponential 1/2/4/8/16/30s, reset on success; never parallelize retries, respect Retry-After, and stop retrying policy/rate-limit closes. Safely ignore malformed frames.
- Tests cover timeframe/symbol rejection, normalization, malformed messages, disconnect cleanup, retry schedule cap/reset, and no retry storm for policy/rate-limit closes.
- Existing `/ws/stream` signal and status protocol remains unchanged.
TDD:
- Behavior: safely relay validated live kline stream with bounded reconnect and cleanup
- Test file: `tests/test_server.py`
- Test name: `test_market_websocket_validation_relay_retry_and_cleanup`
- 🔴 RED command: `PYTHONPATH=. ./venv/bin/pytest tests/test_server.py::test_market_websocket_validation_relay_retry_and_cleanup -q`
- Expected 🔴 RED failure: route/relay/validation/retry behavior absent
- Minimal 🟢 GREEN change: aiohttp client-WebSocket relay with one per-subscription connection, normalized events, capped backoff and cleanup
- Refactor candidates: extract parameter validation/normalizer
- Mocking: fake upstream WS and clock/sleeper for deterministic retries and rate-limit close coverage
Steps:
1. 🔴 RED: add focused cases for bad interval/symbol, kline normalization, malformed frame, retry cap/reset and disconnect
2. 🟢 GREEN: implement handler and bounded lifecycle
3. REFACTOR: verify no retry storm on policy/rate-limit close
4. VERIFY: `PYTHONPATH=. ./venv/bin/pytest tests/test_server.py -q`
Checkpoint:
- Files: `server.py` `tests/test_server.py`
- Commit: `feat(scanner): relay Binance Futures kline WebSocket`

## Task 4: Implement testable live candle merge and redraw throttling
Wave: 3
Status: completed
Risk: high
Dependencies: Task 1, Task 2, Task 3
Model: pro
Files:
- Modify: `static/index.html`
- Create: `static/chart_stream.js`
- Create: `tests/chart_stream.test.js`
Blast radius:
- `static/index.html` `static/chart_stream.js` `tests/chart_stream.test.js`
Acceptance:
- `chart_stream.js` exposes pure functions to upsert a kline (same timestamp replace; newer append; older ignore) and a fake-clock throttle that executes expensive overlay analysis no more than 4 times/sec while candle updates remain immediate.
- Node built-in tests cover duplicate/open candle update, append, stale event ignore, and throttle cadence.
- No DOM, canvas or chart viewport behavior is claimed by pytest/Node tests; Task 5 browser-agent QA covers those.
TDD:
- Behavior: live candle state merge + bounded analysis redraw frequency
- Test file: `tests/chart_stream.test.js`
- Test name: `test_upsertKlineAndThrottleOverlayUpdates`
- 🔴 RED command: `node --test tests/chart_stream.test.js`
- Expected 🔴 RED failure: module/test missing
- Minimal 🟢 GREEN change: browser-compatible pure helper module
- Refactor candidates: keep functions dependency-free for browser and Node import
- Mocking: inject clock for deterministic throttle test
Steps:
1. 🔴 RED: write Node tests for open update, append, stale ignore, throttle cap
2. 🟢 GREEN: implement pure helper module
3. REFACTOR: none
4. VERIFY: `node --test tests/chart_stream.test.js`
Checkpoint:
- Files: `static/chart_stream.js` `tests/chart_stream.test.js`
- Commit: `feat(scanner): test live candle merge and redraw throttle`

## Task 5: Rebuild chart UI, document, and browser-verify
Wave: 4
Status: completed
Risk: high
Dependencies: Task 1, Task 2, Task 3, Task 4
Model: pro
Files:
- Modify: `static/index.html`
- Modify: `server.py`
- Modify: `tests/test_server.py`
- Modify: `README.md`
- Browser QA: local dashboard at `http://127.0.0.1:8766`
Blast radius:
- `static/index.html` `server.py` `tests/test_server.py` `README.md`
Acceptance:
- Subscribe to selected chart after history; dispose prior stream on symbol/timeframe change; merge updates using Task 4 helpers.
- Show truthful connection state/last update and provisional current candle; reconnect and refresh history while preserving viewport.
- Render only the strongest support/resistance lines; draw S/R/FVG as translucent chart-synced canvas bands; accessible toggles; don't auto-fit after initial load.
- Watchlist displays real price, 24h change, quote volume.
- README documents run command, realtime source, public-only data and research/risk caveat.
- pytest validates only route/payload/static contract; browser-agent QA validates interactions, zoom retention, overlay rendering/toggles, reconnect presentation, scan control and mobile layout.
TDD:
- Behavior: dashboard wires selected market stream and clear chart controls
- Test file: `tests/test_server.py` for protocol/static contract only
- Test name: `test_dashboard_exposes_realtime_chart_controls`
- 🔴 RED command: `PYTHONPATH=. ./venv/bin/pytest tests/test_server.py::test_dashboard_exposes_realtime_chart_controls -q`
- Expected 🔴 RED failure: dashboard lacks stream wiring/controls
- Minimal 🟢 GREEN change: wire JS stream lifecycle, chart series updates and overlay canvas
- Refactor candidates: isolate subscription and rendering lifecycle
- Mocking: mocked upstream WS in pytest; browser-agent for DOM visual/interaction checks
Steps:
1. 🔴 RED: add server and static integration assertion
2. 🟢 GREEN: wire live dashboard, watchlist and controls
3. REFACTOR: remove duplicate listeners and preserve chart viewport
4. VERIFY: `PYTHONPATH=. ./venv/bin/pytest tests/ -q`; `node --test tests/chart_stream.test.js`; browser-agent matrix against local server
Checkpoint:
- Files: `static/index.html` `server.py` `tests/test_server.py` `README.md`
- Commit: `feat(scanner): render selected market in realtime`

## Plan Review & Approval Gate
- Initial reviewer feedback requested concrete interval allowlist, reconnect-rate safety, explicit malformed/retry tests, testable ≤4/sec throttle, separate Node/browser test strategy, and one coherent UI task. These have been incorporated.
- Initial final reviewer: APPROVED; subsequent independent code review findings were addressed, then re-reviewed with no blocking issues.
- User approval: YES — user replied `ok` to the final plan and execution request.
- Follow-up review-fix task: current S/R object zones paint as full-width bands; stale monitor and browser disconnect cleanup covered by added regression tests.
- Execution branch: `feat/realtime-chart` (created before implementation); never execute on `main`.

## Analysis decisions recap
- Keep Lightweight Charts 4.2; no Advanced Charts dependency.
- Binance USDⓈ-M `bookTicker` updates the selected symbol continuously; it provides bid/ask midpoint ticks, not trade-by-trade kline OHLC. The UI updates the displayed current candle with the midpoint and labels it provisional; authoritative OHLC history still comes from REST until the interval closes.
- Realtime line/SR/FVG presentation and trustworthy watchlist metrics are in scope.
- No order placement; manual drawing tools deferred.
- Realtime indicator is based on Binance `bookTicker` midpoint; REST supplies historical OHLC. Current candle is a live estimate built from midpoint ticks, and indicator is CONNECTED until first tick, LIVE only after ticks, then STALE if ticks stop.
- Files: technical_engine.py, binance_client.py, server.py, static/index.html, README.md, focused tests; expected total under 20 files. Backend contracts are tested in pytest, JS pure logic in Node, actual DOM/chart behavior in browser-agent.
- Upstream retry is capped/backed off and avoids reconnect storms on rate-limit/policy closes.
