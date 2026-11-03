# Plan: Institutional SMC Analysis, Linear Regression Channel, and Native Realtime Charting

## Problem Statement
The user gave direct, critical feedback:
1. *"không có vẽ dự đoán à?"*: The chart lacks forecast prediction paths and target trajectory projections.
2. *"nên tích hợp công nghệ, thuật toán để phân tích chuẩn hơn chứ k phải vẽ bừa"*: Arbitrary diagonal trendlines feel amateurish. The engine must incorporate rigorous quantitative methods: **Smart Money Concepts (SMC Order Blocks, BOS/CHoCH)** and **Statistical Linear Regression Channels ($\pm 2\sigma$)**.
3. *"chart phải realtime như chart gốc luôn"*: The chart must mirror Binance/TradingView's live experience: sub-second price blinking, live candlestick expansion, and a real-time candle countdown timer.

## Architecture & Technical Decisions
### 1. Smart Money Concepts (SMC) & Statistical Engine (`technical_engine.py`):
- **Order Blocks (OB - Supply & Demand Zones)**:
  - `BULLISH_OB`: The last bearish candle before an impulsive bullish displacement that breaks prior swing high. Formatted as an institutional Demand Zone with `[top, bottom]` coordinates.
  - `BEARISH_OB`: The last bullish candle before an impulsive bearish displacement that breaks prior swing low. Formatted as an institutional Supply Zone.
- **Break of Structure (BOS)**:
  - Clean horizontal broken levels indicating structural trend continuation.
- **Statistical Linear Regression Channel ($\pm 2\sigma$)**:
  - Fitted over the last 60 bars using least-squares polynomial regression.
  - Midline ($y = ax + b$).
  - Upper Band ($+2\sigma$): Statistical Overbought / Mean-reversion Resistance.
  - Lower Band ($-2\sigma$): Statistical Oversold / Mean-reversion Support.
- **Forecast Trajectory & Target Projection (Vẽ dự đoán đường đi)**:
  - When a setup occurs, compute the expected path into future bars:
    - Step 0: Current Breakout bar `(time_0, price_0)`.
    - Step 1: Retest Level `(time_0 + 1 * step, retest_price)`.
    - Step 2: Target 1 `(time_0 + 4 * step, tp1_price)`.
    - Step 3: Target 2 `(time_0 + 8 * step, tp2_price)`.
  - Emitted in the structure payload as `forecast_path: [{time, value}, ...]`.

### 2. High-Frequency Realtime Chart Experience (`index.html` & `chart_stream.js`):
- **Live Candle Countdown Timer**:
  - Computes remaining seconds in current candle `(interval_seconds - (now % interval_seconds))`.
  - Renders a clean badge `⏳ 14:23` right beside the price and on the chart axis.
- **Sub-Second Tick Application**:
  - Live bid/ask ticks dynamically adjust `close`, `high`, `low` of the open candle.
  - Price label on right scale and `#chartPrice` flash green/red.
- **TradingView Projection Overlays**:
  - Forecast Path rendered as an arrowed dashed cyan/green trajectory into future bars.
  - Order Blocks rendered as crisp shaded boxes with labels `OB [Demand]` and `OB [Supply]`.
  - Linear Regression Channel rendered as parallel statistical bands.

## Environment Context
- Language: Python 3.13 backend, vanilla JS frontend
- Test commands:
  - Python: `PYTHONPATH=. ./venv/bin/pytest tests/ -q`
  - JavaScript: `node --test tests/chart_stream.test.js`
- Working Branch: `feat/smc-quant-chart` (cut from `feat/signal-win-loss-db`)

## Task 1: Smart Money Concepts (Order Blocks, BOS) & Linear Regression in technical_engine.py
Wave: 1
Status: pending
Risk: medium
Dependencies: none
Model: inherit

Files:
- Modify: `futures-chart-scanner/technical_engine.py`
- Modify: `futures-chart-scanner/tests/test_technical_engine.py`

Acceptance:
- `detect_order_blocks(klines, swings)` identifies valid Bullish and Bearish Order Blocks.
- `calculate_regression_channel(klines, window=60)` calculates slope, intercept, upper band (+2std), and lower band (-2std).
- `generate_forecast_path(signal, klines)` outputs projected coordinates into future candle intervals.
- Unit tests verify Order Block detection, Linear Regression mathematics, and forecast path generation.

TDD:
- Behavior: technical engine detects institutional order blocks and calculates linear regression channel
- Test file: `tests/test_technical_engine.py`
- Test name: `test_smc_order_blocks_and_regression_channel`
- 🔴 RED command: `PYTHONPATH=. ./venv/bin/pytest tests/test_technical_engine.py::test_smc_order_blocks_and_regression_channel -q`
- Expected 🔴 RED failure: methods `detect_order_blocks` / `calculate_regression_channel` do not exist
- Minimal 🟢 GREEN change: implement SMC and regression methods in `technical_engine.py`

Steps:
1. 🔴 RED: write unit test for order blocks, regression channel, and forecast trajectory
   Command: `PYTHONPATH=. ./venv/bin/pytest tests/test_technical_engine.py::test_smc_order_blocks_and_regression_channel -q`
   Expected: FAIL
2. 🟢 GREEN: implement methods in `technical_engine.py`
   Command: `PYTHONPATH=. ./venv/bin/pytest tests/test_technical_engine.py -q`
   Expected: PASS
3. VERIFY: `PYTHONPATH=. ./venv/bin/pytest tests/test_technical_engine.py -q`

Checkpoint:
- Files: `technical_engine.py` `tests/test_technical_engine.py`
- Commit: `feat(engine): implement smc order blocks, linear regression channel, and forecast trajectory`

## Task 2: Server Payload Integration (Order Blocks, Channel, Forecast) in server.py
Wave: 2
Status: pending
Risk: low
Dependencies: Task 1
Model: inherit

Files:
- Modify: `futures-chart-scanner/server.py`
- Modify: `futures-chart-scanner/tests/test_server.py`

Acceptance:
- `build_structure_payload` includes:
  - `order_blocks`: list of `{type, top, bottom, index, end_index}`
  - `regression_channel`: `{upper: [{time, value}], middle: [{time, value}], lower: [{time, value}]}`
  - `forecast_path`: list of future `{time, value, label}`
- WebSocket `/ws/market` structure event emits these fields.
- REST `/api/chart` returns these fields.

TDD:
- Behavior: server structure payload includes order blocks, regression channel, and forecast path
- Test file: `tests/test_server.py`
- Test name: `test_structure_payload_includes_smc_and_forecast`
- 🔴 RED command: `PYTHONPATH=. ./venv/bin/pytest tests/test_server.py::test_structure_payload_includes_smc_and_forecast -q`
- Expected 🔴 RED failure: keys `order_blocks`, `regression_channel`, `forecast_path` missing
- Minimal 🟢 GREEN change: wire engine methods into `build_structure_payload` in `server.py`

Steps:
1. 🔴 RED: write test asserting presence and structure of SMC/forecast keys
   Command: `PYTHONPATH=. ./venv/bin/pytest tests/test_server.py::test_structure_payload_includes_smc_and_forecast -q`
   Expected: FAIL
2. 🟢 GREEN: wire SMC and forecast into `build_structure_payload`
   Command: `PYTHONPATH=. ./venv/bin/pytest tests/test_server.py -q`
   Expected: PASS
3. VERIFY: `PYTHONPATH=. ./venv/bin/pytest tests/test_server.py -q`

Checkpoint:
- Files: `server.py` `tests/test_server.py`
- Commit: `feat(server): emit smc order blocks, regression channel, and forecast path`

## Task 3: Realtime Candle Countdown Timer & Native TradingView Drawing Overlays
Wave: 3
Status: pending
Risk: medium
Dependencies: Task 2
Model: pro

Files:
- Modify: `futures-chart-scanner/static/index.html`
- Modify: `futures-chart-scanner/static/chart_stream.js`
- Test: `futures-chart-scanner/tests/chart_stream.test.js`

Acceptance:
- **Realtime Countdown Timer**: Shows `⏳ mm:ss` countdown to candle close, synchronized to timeframe interval.
- **Forecast Path**: Rendered as a styled dashed projection line with target arrow pointing into future bars.
- **Order Blocks**: Rendered on canvas as elegant Demand (cyan) and Supply (rose) zones with clean tags.
- **Linear Regression Channel**: Rendered with toggle checkbox `[ ] LinReg Channel`.
- **Overlay Controls**: Toggle checkboxes for `[x] Forecast Path`, `[x] Order Blocks`, `[x] Regression Channel`.

TDD:
- Behavior: chart_stream helper calculates candle countdown and formats forecast points
- Test file: `tests/chart_stream.test.js`
- Test name: `test_candle_countdown_and_forecast_helpers`
- 🔴 RED command: `node --test --test-name-pattern='countdown' tests/chart_stream.test.js`
- Expected 🔴 RED failure: helper `formatCandleCountdown` missing
- Minimal 🟢 GREEN change: implement pure helpers in `chart_stream.js`

Steps:
1. 🔴 RED: write node unit test for countdown and forecast helpers
   Command: `node --test tests/chart_stream.test.js`
   Expected: FAIL
2. 🟢 GREEN: implement helpers in `chart_stream.js`
   Command: `node --test tests/chart_stream.test.js`
   Expected: PASS
3. Wire UI in `index.html` with countdown timer, forecast path series, and Order Block canvas rendering
4. VERIFY: `node --test tests/chart_stream.test.js` and `PYTHONPATH=. ./venv/bin/pytest tests/ -q`

Checkpoint:
- Files: `static/index.html` `static/chart_stream.js` `tests/chart_stream.test.js`
- Commit: `feat(ui): add live candle countdown timer, forecast trajectory path, and order block boxes`

## Task 4: Browser Live Verification & Visual Inspection
Wave: 4
Status: pending
Risk: low
Dependencies: Task 3
Model: pro

Files:
- Test: browser live verification via `agent-browser`

Acceptance:
- Verify countdown timer ticks down second-by-second (e.g. `14:59 -> 14:58`).
- Verify price ticks update candle and price scale instantaneously.
- Verify forecast path projects into future space towards TP1 and TP2.
- Verify Order Blocks render as crisp demand/supply boxes.
- Full screenshot captured as evidence.
