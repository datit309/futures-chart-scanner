# Plan: TradingView Advanced Real-Time Chart Integration

## Problem Statement
The user requested Option 2: embed the official, full-featured TradingView Advanced Charting widget directly into the scanner workspace.
Traders require:
1. **100% Authentic Real-Time Binance Data**: Sub-second tick accuracy, candle countdown, and zero time-offset issues directly provided by TradingView's Binance Futures datafeed (`BINANCE:BTCUSDT.P`).
2. **Complete Pro Trading Toolkit**: Built-in interactive drawing tools (trendlines, rays, pitchforks, fibonacci, brush, text) and indicators (RSI, MACD, EMA, Volume Profile, Bollinger Bands).
3. **Seamless Scanner Synergy**: Keep our signal feed, automated win/loss tracking, and Watchlist active. Selecting any pair or signal immediately switches the TradingView chart to that contract.
4. **Dual Chart Mode**: Provide a clean toggle `[TradingView Pro]` (official interactive widget) and `[SMC Structure]` (Lightweight Charts with automated Order Blocks, SL/TP levels, and forecast path), giving the user maximum flexibility.

## Analysis Decisions
- **TradingView Widget Engine**: Use official TradingView Advanced Real-Time Charting library (`https://s3.tradingview.com/tv.js`).
- **Symbol Mapping**: Map Binance USDⓈ-M Futures ticker (e.g. `BTCUSDT`, `ETHUSDT`) to TradingView symbol `BINANCE:{symbol}.P`.
- **Interval Mapping**: Map timeframe `15m` -> `"15"`, `1h` -> `"60"`, `4h` -> `"240"`.
- **Timezone**: Explicitly configure `timezone: "Asia/Ho_Chi_Minh"` so timestamps match local ICT time.
- **Persistence & Selection**: Both chart containers reside in `.chart-wrap`. Selecting a coin or timeframe updates both widgets without full page reloads.

## Environment Context
- Language: Python 3.13 backend, vanilla JS frontend
- Test commands:
  - Python: `PYTHONPATH=. ./venv/bin/pytest tests/ -q`
  - JavaScript: `node --test tests/chart_stream.test.js`
- Working Branch: `feat/tradingview-advanced-widget` (cut from `feat/smc-quant-chart`)

## Task 1: TradingView Symbol & Interval Mapping Helper in chart_stream.js
Wave: 1
Status: pending
Risk: low
Dependencies: none
Model: inherit

Files:
- Modify: `futures-chart-scanner/static/chart_stream.js`
- Modify: `futures-chart-scanner/tests/chart_stream.test.js`

Blast radius:
- `static/chart_stream.js`
- `tests/chart_stream.test.js`

Acceptance:
- `symbolToTradingView("BTCUSDT")` returns `"BINANCE:BTCUSDT.P"`.
- `timeframeToTradingView("15m")` returns `"15"`, `"1h"` returns `"60"`, `"4h"` returns `"240"`.
- Unit tests verify conversion and fallback behavior.

TDD:
- Behavior: pure helpers correctly translate internal symbols and intervals to TradingView widget format
- Test file: `tests/chart_stream.test.js`
- Test name: `test_tradingview_symbol_and_interval_mappings`
- 🔴 RED command: `node --test --test-name-pattern='tradingview' tests/chart_stream.test.js`
- Expected 🔴 RED failure: `symbolToTradingView` is not exported
- Minimal 🟢 GREEN change: implement `symbolToTradingView` and `timeframeToTradingView` in `chart_stream.js`

Steps:
1. 🔴 RED: write unit test in `tests/chart_stream.test.js`
   Command: `node --test tests/chart_stream.test.js`
   Expected: FAIL
2. 🟢 GREEN: implement mapping functions in `static/chart_stream.js`
   Command: `node --test tests/chart_stream.test.js`
   Expected: PASS
3. VERIFY: `node --test tests/chart_stream.test.js`

Checkpoint:
- Files: `static/chart_stream.js` `tests/chart_stream.test.js`
- Commit: `feat(chart): add tradingview symbol and interval formatters`

## Task 2: TradingView Advanced Widget & Dual Mode Switcher in index.html
Wave: 2
Status: pending
Risk: medium
Dependencies: Task 1
Model: pro

Files:
- Modify: `futures-chart-scanner/static/index.html`

Blast radius:
- `static/index.html`

Acceptance:
- Add Mode Switcher tabs on chart toolbar: `[TradingView Pro]` (default) and `[SMC Structure]`.
- Load `https://s3.tradingview.com/tv.js` script asynchronously.
- Initialize `TradingView.widget` inside `#tvChartContainer` with:
  - Symbol: `BINANCE:BTCUSDT.P`
  - Interval: `"15"`
  - Timezone: `"Asia/Ho_Chi_Minh"`
  - Theme: `"dark"`
  - Language: `"vi_VN"`
  - Full drawing toolbar enabled (`hide_side_toolbar: false`)
  - Volume indicator enabled
- When user clicks a coin in Watchlist or Signal Feed:
  - Updates TradingView chart symbol seamlessly via widget iframe or reload.
  - Updates SMC structure chart in background.
- When user clicks a timeframe button (`15m`, `1h`, `4h`), both charts synchronize.
- All existing tests pass.

Steps:
1. Add `#tvChartContainer` div and mode tabs `[TradingView Pro] | [SMC Structure]` in `static/index.html`
2. Add TradingView widget loader and state synchronization functions
3. Wire mode switcher to toggle between `#tvChartContainer` and `#chart`
4. VERIFY: `PYTHONPATH=. ./venv/bin/pytest tests/ -q` and `node --test tests/chart_stream.test.js`

Checkpoint:
- Files: `static/index.html`
- Commit: `feat(ui): embed official tradingview advanced real-time chart with dual mode switcher`

## Task 3: Browser Verification & Interactive QA
Wave: 3
Status: pending
Risk: low
Dependencies: Task 2
Model: pro

Files:
- Test: browser live verification via `agent-browser`

Acceptance:
- Verify TradingView widget loads cleanly with complete drawing toolbar and volume.
- Verify switching symbols (BTC -> ETH -> SOL) switches the TradingView widget symbol.
- Verify switching mode to `[SMC Structure]` shows the automated Order Blocks and forecast path.
- Verify switching back to `[TradingView Pro]` maintains active charting session.
- Capture screenshots as evidence.
