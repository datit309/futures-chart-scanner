# Plan: Full Native TradingView Charting Library Integration with Automated Drawings

## Problem Statement
The user explicitly demanded: "Ý TAO LÀ bỏ chart cũ đi, dùng trading view luôn, vẽ trên đó" (Drop the old chart completely, use TradingView directly, and draw the bot's analysis directly on top of it).
Previously, the free TradingView embed widget was in a separate tab without bot drawings because cross-origin iframes prevent programmatic drawing, while the old Lightweight Charts was in another tab.
We now have the official standalone TradingView Charting Library (v27, self-hosted on same-origin `static/charting_library/`), which provides full native APIs (`createMultipointShape`, `createOrderLine`, `createPositionLine`, `createShape`, `removeAllShapes`).

## Goal
1. **Drop Old Chart**: Completely remove Lightweight Charts and custom HTML5 canvas overlays from `static/index.html`.
2. **Single Unified Chart**: The primary, only chart is the real TradingView Advanced Chart.
3. **Automated Bot Drawings on TradingView**:
   - Trendlines drawn via `chart().createMultipointShape(..., { shape: 'trend_line' })`.
   - Order Blocks (SMC Demand/Supply) drawn via `chart().createMultipointShape(..., { shape: 'rectangle' })`.
   - Entry, Stop Loss, Take Profit lines drawn on the TradingView price scale via `chart().createOrderLine()` with color-coded badges and PnL percentages.
   - Breakout markers drawn via `chart().createShape(..., { shape: 'arrow_up' | 'arrow_down' })`.
4. **Interactive Manual Tools**: User can still use all TradingView drawing tools, indicators (RSI, MACD, EMA), and features.
5. **Real-Time Datafeed**: Live Binance USDⓈ-M Futures data fed directly to TradingView via custom UDF-compatible Datafeed connected to our WebSocket stream.

## Architecture & Contracts
- **Library Path**: `/static/charting_library/` (served by `aiohttp.web.static('/static', STATIC_DIR)`).
- **Datafeed Interface**:
  - `onReady`: returns resolutions `['15', '60', '240', 'D']`
  - `resolveSymbol`: resolves `symbol` to Binance perpetual specifications with `pricescale` (100 for high cap, 10000 for low cap), `session: '24x7'`, `timezone: 'Asia/Ho_Chi_Minh'`.
  - `getBars`: queries `/api/chart` or Binance REST; returns bars array `{ time: ms, open, high, low, close, volume }` with `noData: true` on subsequent requests to prevent infinite polling.
  - `subscribeBars`: registers realtime callback invoked on every `tick` or `kline` WebSocket message.
- **Drawings Engine**:
  - `clearTradingViewDrawings(chart)`: calls `chart.removeAllShapes()`.
  - `renderTradingViewStructure(chart, structure, signal)`:
    - Iterates `structure.trendlines` -> creates `'trend_line'` shapes.
    - Iterates `structure.order_blocks` -> creates `'rectangle'` shapes.
    - If `signal` exists -> creates OrderLines for Entry, SL, TP1, TP2 and arrow marker.

## Task 1: Datafeed & Shape Formatting Helpers in chart_stream.js
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
- Unit tests verify `createTradingViewDatafeed` correctly resolves symbols, formats bars, and handles pagination.
- Unit tests verify `formatTrendlineShape` and `formatOrderBlockShape` produce valid TradingView shape descriptor arguments.

Steps:
1. 🔴 RED: write unit tests for datafeed and shape formatting in `tests/chart_stream.test.js`
   Command: `node --test tests/chart_stream.test.js`
   Expected: FAIL
2. 🟢 GREEN: implement datafeed & shape formatting functions in `static/chart_stream.js`
   Command: `node --test tests/chart_stream.test.js`
   Expected: PASS
3. VERIFY: `node --test tests/chart_stream.test.js`

## Task 2: TradingView Charting Library Integration in index.html
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
- Remove Lightweight Charts script tag, old `#chart`, and `#zoneCanvas`.
- Container `#tv_chart_container` loads `new TradingView.widget` using local `/static/charting_library/`.
- On chart ready and on every `structure` / `signal` update, automatically draw:
  - Resistance & Support Trendlines
  - SMC Order Blocks (Demand & Supply rectangles)
  - Native OrderLines for ENTRY, SL, and TP
- Coin switching via select dropdown or Signal Feed updates symbol in TradingView chart.
- Timeframe switching (15m, 1h, 4h) updates chart resolution.
- Live ticks update the current candle in TradingView in sub-second real-time.

Steps:
1. Replace old chart HTML in `static/index.html` with unified TradingView container.
2. Initialize `TradingView.widget` with local datafeed and library path.
3. Hook WebSocket stream events (`tick`, `kline`, `structure`) to update TradingView bars and redraw shapes.
4. VERIFY: `PYTHONPATH=. ./venv/bin/pytest tests/ -q` and `node --test tests/chart_stream.test.js`.

## Task 3: Browser Verification & QA Testing
Wave: 3
Status: pending
Risk: low
Dependencies: Task 2
Model: pro

Files:
- Test: browser live verification via `agent-browser`

Acceptance:
- Open `http://127.0.0.1:8766` in browser.
- Verify real TradingView interface loads with live Binance candles.
- Verify bot-drawn Trendlines, Order Blocks, and Entry/SL/TP order lines appear directly on the TradingView chart.
- Verify switching symbols changes the chart and draws the corresponding symbol's setups.
- Capture screenshot as evidence.
