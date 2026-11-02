# Plan: Real OHLC Candle Stream (Replace Midpoint Hack)

## Analysis Decisions
- **Approach**: Replace bookTicker midpoint estimation with REST klines polling inside the server `/ws/market` handler. Evidence: Binance `@kline_*` WebSocket streams handshake successfully but deliver zero frames in this network environment (verified 3x), while `/fapi/v1/klines` REST returns real updating OHLC in ~0.17s. Polling REST every 3s gives true open/high/low/close/volume for the forming candle.
- **Alternatives considered**: (a) keep bookTicker midpoint — rejected, produces fake candles with no real OHLC; (b) combined `/stream?streams=` endpoint — rejected, also delivered only bookTicker frames, no kline; (c) direct browser polling Binance REST — rejected, CORS and rate-limit exposure, server proxy is safer.
- **Consolidation**: Move live structure analysis back to server `TechnicalEngine` (single source of truth). Remove client-side `analyzeLive` heuristic (2-point slope, bullish-only FVG) that diverges from backend.
- **Risk**: REST polling adds ~3s latency vs true WS push; acceptable for 15m/1h/4h chart scanning. Mitigated by keeping bookTicker as an optional fast price overlay if needed later.

## Architecture & Contracts
- **`/ws/market` new protocol**:
  - Status events unchanged: `{type:"status", state:"connecting|connected|stale|reconnecting|error"}`
  - New candle event: `{type:"kline", symbol, timeframe, candle:{time,open,high,low,close,volume,closed}}` — real OHLC from REST
  - New structure event: `{type:"structure", symbol, timeframe, trendlines:[...], sr_zones:[...], zone_bands:[...], fvgs:[...], signal:{...}}` — computed by server `TechnicalEngine`
  - Downstream close watcher + bounded reconnect + stale detection preserved from current implementation
- **Polling loop**: inside handler, `while not ws.closed`, `await asyncio.sleep(3)`, call `state.client.get_klines(symbol, interval=timeframe, limit=2)`, emit last candle if changed. `last_event_at` reset on each successful poll; stale after `MARKET_STALE_AFTER_SECONDS`.
- **`TechnicalEngine` reuse**: call existing `find_swing_points`, `detect_trendlines`, `detect_sr_zones`, `detect_fvg`, `analyze_market` on the full kline set (fetch `limit=100` once on connect, then poll `limit=2` and merge). Emit structure only when candle closes or every 5th poll to avoid WS spam.
- **Frontend contract**: remove `applyBookTicker` / `rollLiveCandle` / `analyzeLive`. On `kline` message → `upsertKline` + `series.update`. On `structure` message → re-render trendlines/zones/FVG from server data. `closed:true` removes provisional label.
- **No API keys, no order execution.**

## Environment Context
- Language: Python backend + vanilla HTML/CSS/JavaScript frontend
- Runtime: Python 3.13, aiohttp; Lightweight Charts 4.2.2 via CDN; Node 24
- Test: `PYTHONPATH=. ./venv/bin/pytest tests/ -q`
- Node test: `node --test tests/chart_stream.test.js`
- Lint/format/build: none configured
- Branch: create `fix/real-ohlc-stream` from `feat/realtime-chart` (do not execute on `main`)
- Commit style: Conventional Commits, `fix(scanner): ...`
- Codebase conventions: async aiohttp handlers, dataclass config, pytest asyncio markers, node:test for JS pure logic
- Graph context: project `futures-chart-scanner` ready (190 nodes / 834 edges). `server.py` ↔ `BinanceClient` / `TechnicalEngine` boundaries. No hub mutation. Blast radius ≤ 7 files.

## Task 1: Server REST kline polling for /ws/market
Wave: 1
Status: pending
Risk: medium
Dependencies: none
Model: inherit

Files:
- Modify: `futures-chart-scanner/server.py`
- Modify: `futures-chart-scanner/tests/test_server.py`

Blast radius:
- `futures-chart-scanner/server.py`

Acceptance:
- `/ws/market` polls `/fapi/v1/klines` every 3s instead of connecting to bookTicker WS.
- Emits `{type:"kline", candle:{time,open,high,low,close,volume,closed}}` with real OHLC.
- Stale status fires when polls stop succeeding; downstream close still cancels poll loop and cleans up.
- Invalid symbol/timeframe still rejected with 400 before any poll.

TDD:
- Behavior: market websocket relays real REST kline OHLC and cleans up on disconnect
- Test file: `futures-chart-scanner/tests/test_server.py`
- Test name: `test_market_websocket_polls_rest_klines_and_cleans_up`
- 🔴 RED command: `PYTHONPATH=. ./venv/bin/pytest tests/test_server.py::test_market_websocket_polls_rest_klines_and_cleans_up -q`
- Expected 🔴 RED failure: handler still emits bookTicker `price` type, no `kline` type
- Minimal 🟢 GREEN change: replace upstream WS connect with `get_klines` poll loop inside handler
- Refactor candidates: extract poll interval constant
- Mocking: patch `BinanceClient.get_klines` — external REST not suitable for deterministic tests

Steps:
1. 🔴 RED: rewrite relay test to assert `kline` message with OHLC fields from mocked `get_klines`
   Command: `PYTHONPATH=. ./venv/bin/pytest tests/test_server.py::test_market_websocket_polls_rest_klines_and_cleans_up -q`
   Expected: FAIL (no kline event)
2. 🟢 GREEN: replace bookTicker upstream with REST poll loop, keep downstream watcher + stale + reconnect
   Command: `PYTHONPATH=. ./venv/bin/pytest tests/test_server.py -q`
   Expected: PASS
3. REFACTOR: keep `normalize_binance_kline_event` helper for REST→WS payload mapping
4. VERIFY:
   - `PYTHONPATH=. ./venv/bin/pytest tests/test_server.py -q`
   - Lint: none configured

Checkpoint:
- Files: `futures-chart-scanner/server.py` `futures-chart-scanner/tests/test_server.py`
- Commit: `fix(scanner): poll rest klines for real ohlc market stream`

## Task 2: Server-side structure emission from TechnicalEngine
Wave: 2
Status: pending
Risk: medium
Dependencies: Task 1
Model: inherit

Files:
- Modify: `futures-chart-scanner/server.py`
- Modify: `futures-chart-scanner/tests/test_server.py`

Blast radius:
- `futures-chart-scanner/server.py`

Acceptance:
- On connect, server fetches `limit=100` klines, computes structure via `TechnicalEngine`, emits `{type:"structure", ...}`.
- Structure re-emitted when a candle closes (`closed:true`) or every 5th successful poll.
- Structure payload matches `/api/chart` shape: `trendlines` with `next_time`/`next_price`, `zone_bands`, `fvgs`, `signal`.
- Client heuristic `analyzeLive` becomes dead code and is removed in Task 4.

TDD:
- Behavior: market websocket emits server-computed structure alongside klines
- Test file: `futures-chart-scanner/tests/test_server.py`
- Test name: `test_market_websocket_emits_structure_from_technical_engine`
- 🔴 RED command: `PYTHONPATH=. ./venv/bin/pytest tests/test_server.py::test_market_websocket_emits_structure_from_technical_engine -q`
- Expected 🔴 RED failure: no `structure` message type emitted
- Minimal 🟢 GREEN change: call TechnicalEngine on initial klines, emit structure message
- Refactor candidates: extract `build_structure_payload` helper
- Mocking: patch `get_klines`; real engine runs on synthetic data

Steps:
1. 🔴 RED: add test asserting `structure` message with `trendlines`/`zone_bands` keys
   Command: `PYTHONPATH=. ./venv/bin/pytest tests/test_server.py::test_market_websocket_emits_structure_from_technical_engine -q`
   Expected: FAIL
2. 🟢 GREEN: compute and emit structure on connect + on candle close
   Command: `PYTHONPATH=. ./venv/bin/pytest tests/test_server.py -q`
   Expected: PASS
3. REFACTOR: reuse `handle_api_chart` payload-building logic via shared helper
4. VERIFY:
   - `PYTHONPATH=. ./venv/bin/pytest tests/test_server.py -q`
   - Lint: none configured

Checkpoint:
- Files: `futures-chart-scanner/server.py` `futures-chart-scanner/tests/test_server.py`
- Commit: `feat(scanner): emit server structure over market websocket`

## Task 3: Missing regression tests (sr_zones + close race)
Wave: 2
Status: pending
Risk: low
Dependencies: none
Model: flash

Files:
- Modify: `futures-chart-scanner/tests/test_technical_engine.py`
- Modify: `futures-chart-scanner/tests/test_server.py`

Blast radius:
- `futures-chart-scanner/tests/test_technical_engine.py`
- `futures-chart-scanner/tests/test_server.py`

Acceptance:
- `detect_sr_zones` has a direct unit test covering the 0.6% clustering threshold (adjacent swings merge, distant swings separate).
- WebSocket close race test: downstream close during upstream poll wait cancels poll task and closes session (no leaked task).
- Existing 30 Python + 12 Node tests still pass.

TDD:
- Behavior: sr zone clustering and websocket disconnect cleanup under race
- Test file: `futures-chart-scanner/tests/test_technical_engine.py`
- Test name: `test_detect_sr_zones_clusters_nearby_swings`
- 🔴 RED command: `PYTHONPATH=. ./venv/bin/pytest tests/test_technical_engine.py::test_detect_sr_zones_clusters_nearby_swings -q`
- Expected 🔴 RED failure: no direct sr_zones test exists
- Minimal 🟢 GREEN change: add test with synthetic swings (implementation already correct)
- Refactor candidates: none
- Mocking: none for sr_zones; close race uses fake upstream

Steps:
1. 🔴 RED: add `test_detect_sr_zones_clusters_nearby_swings` and `test_market_ws_close_race_cleans_up`
   Command: `PYTHONPATH=. ./venv/bin/pytest tests/test_technical_engine.py tests/test_server.py -q`
   Expected: FAIL for missing test
2. 🟢 GREEN: verify implementation passes (tests only, or minimal fix if race leaks)
   Command: `PYTHONPATH=. ./venv/bin/pytest tests/ -q`
   Expected: PASS
3. REFACTOR: none
4. VERIFY:
   - `PYTHONPATH=. ./venv/bin/pytest tests/ -q`
   - `node --test tests/chart_stream.test.js`
   - Lint: none configured

Checkpoint:
- Files: `futures-chart-scanner/tests/test_technical_engine.py` `futures-chart-scanner/tests/test_server.py`
- Commit: `test(scanner): cover sr zones and websocket close race`

## Task 4: Frontend consumes real kline + server structure
Wave: 3
Status: pending
Risk: high
Dependencies: Task 1, Task 2
Model: pro

Files:
- Modify: `futures-chart-scanner/static/index.html`
- Modify: `futures-chart-scanner/static/chart_stream.js`
- Modify: `futures-chart-scanner/tests/chart_stream.test.js`
- Modify: `futures-chart-scanner/README.md`

Blast radius:
- `futures-chart-scanner/static/index.html`
- `futures-chart-scanner/static/chart_stream.js`

Acceptance:
- Frontend handles `kline` messages via `upsertKline` + `series.update` (real OHLC, no midpoint).
- Frontend handles `structure` messages: renders trendlines/zones/FVG from server payload, same as initial `loadChart`.
- `applyBookTicker`, `rollLiveCandle`, `analyzeLive` removed from `index.html`; `rollLiveCandle` removed from `chart_stream.js` and its tests.
- Provisional label driven by `candle.closed` from server, not client inference.
- README updated: realtime source is REST klines polling, not bookTicker midpoint.

TDD:
- Behavior: frontend renders server structure and real kline updates
- Test file: `futures-chart-scanner/tests/chart_stream.test.js`
- Test name: `test_render_structure_payload_from_server`
- 🔴 RED command: `node --test --test-name-pattern='render_structure_payload_from_server' tests/chart_stream.test.js`
- Expected 🔴 RED failure: no structure-rendering helper exists
- Minimal 🟢 GREEN change: add pure `structureToOverlays(payload)` helper + test
- Refactor candidates: remove dead helpers once frontend migrated
- Mocking: none — pure payload transform

Steps:
1. 🔴 RED: add `structureToOverlays` test; remove `rollLiveCandle` tests
   Command: `node --test tests/chart_stream.test.js`
   Expected: FAIL (missing helper)
2. 🟢 GREEN: implement `structureToOverlays`, rewire `index.html` message handler, delete midpoint code
   Command: `node --test tests/chart_stream.test.js`
   Expected: PASS
3. REFACTOR: update README realtime section
4. VERIFY:
   - `node --test tests/chart_stream.test.js`
   - `PYTHONPATH=. ./venv/bin/pytest tests/ -q`
   - Browser QA at `http://127.0.0.1:8766`: real OHLC updates, structure overlays, symbol/timeframe switch, stale→live recovery
   - Lint: none configured

Checkpoint:
- Files: `futures-chart-scanner/static/index.html` `futures-chart-scanner/static/chart_stream.js` `futures-chart-scanner/tests/chart_stream.test.js` `futures-chart-scanner/README.md`
- Commit: `fix(scanner): render real ohlc candles and server structure`

## Plan Review
- Reviewer: required before execute
- Review status: pending
- User approval: pending
- Execution branch: `fix/real-ohlc-stream` from `feat/realtime-chart`; never `main`
- Evidence for approach: 3x probe showing kline WS handshake-OK-but-no-frames, combined stream also bookTicker-only, REST klines 0.17s with live-updating OHLC (close 78513.7→78498.2, volume 45.9→53.4 across polls)
