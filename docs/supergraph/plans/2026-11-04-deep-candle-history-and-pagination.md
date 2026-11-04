# Plan: Deep Candle History & Seamless Pagination in TradingView Chart

## Problem Statement
The user asked: "sao nen co 1 xiu vay fen" (Why are there so few candles / why is the candle history so short?).
Investigation revealed:
1. On initial load, `/api/chart` was hardcoded to `limit=100`, providing only 100 bars (~25 hours of 15m candles, barely 1 day).
2. On scroll back, `getBars` returned `noData: true` on `!periodParams.firstDataRequest`, permanently blocking TradingView from loading more historical data.
3. Chart container height was only `520px`, which could make vertical candle range feel cramped.

## Goals
1. Increase default candle fetch from 100 to 500 bars on initial load (providing over 5 days of 15m data, 3 weeks of 1h data, 83 days of 4h data).
2. Implement seamless backward pagination: support `endTime` in `binance_client.py` and `server.py`, and pass `endTime` in `chart_stream.js` datafeed when user scrolls left.
3. Increase `.chart-wrap` height to `600px` and add TradingView `time_frames` navigation bar.
4. Verify with automated unit tests and browser live QA.

## Architecture & Contracts
- `binance_client.py`: `get_klines(symbol, interval, limit=500, endTime=None)` passes `endTime` query parameter to Binance Futures API if present.
- `server.py`: `handle_api_chart` extracts `endTime` query param and passes it to `get_klines`.
- `chart_stream.js`: `createTradingViewDatafeed` uses `periodParams.to` on historical requests and calls `fetchChartFn(symbol, tf, endTime)`.
- `static/index.html`: wires `endTime` into URLSearchParams and expands `.chart-wrap` height to `600px`.

## Task 1: Binance Client & Server Pagination Support (RED -> GREEN)
Wave: 1
Status: pending
Risk: low
Dependencies: none
Model: inherit

Files:
- Modify: `binance_client.py`
- Modify: `server.py`
- Modify: `tests/test_server.py`

Acceptance:
- `handle_api_chart` parses `endTime` and passes it to `get_klines`.
- Unit test in `test_server.py` verifies `/api/chart?symbol=BTCUSDT&limit=200&endTime=1700000000000` forwards `endTime`.

## Task 2: Datafeed Continuous Historical Pagination (RED -> GREEN)
Wave: 2
Status: pending
Risk: low
Dependencies: Task 1
Model: inherit

Files:
- Modify: `static/chart_stream.js`
- Modify: `tests/chart_stream.test.js`

Acceptance:
- Unit test verifies `getBars` with `firstDataRequest: false` passes `endTime` in milliseconds.
- Datafeed sorts and returns bars seamlessly.

## Task 3: UI Enhancement & Browser Live QA
Wave: 3
Status: pending
Risk: low
Dependencies: Task 2
Model: pro

Files:
- Modify: `static/index.html`
- Test: browser live verification via `agent-browser`

Acceptance:
- Chart loads 500 candles on initial render.
- User can scroll left to load older history seamlessly.
- Visual inspection confirms deep, spacious candle view.
