# Plan: TradingView-Grade Chart Overlays & High-Frequency Realtime Ticks

## Problem Statement
The current UI/chart fails user expectations in four ways:
1. **"Chưa thấy realtime"**: The price header `#chartPrice` never updates on stream messages, and the 3s REST poll is too slow compared to Binance's live ticking.
2. **"Đường vẽ lỏ" / Line mismatch**: The trendline shown on chart is disconnected from the signal (chart displays an ancient channel from bar 16, while the signal feed alerts a breakdown on a different line at bar 60).
3. **"Tất cả các vẽ đều lỏ, khó hiểu"**:
   - S/R zones are rendered as a massive 800-dollar blurry blue rectangle covering half the screen.
   - Trade levels (Entry, SL, TP) are rendered as floating HTML debug chips in the top-left corner instead of native TradingView horizontal price lines on the price scale.

## Architecture & Technical Decisions
1. **Sub-second Realtime Hybrid Stream (`/ws/market`)**:
   - Upstream Binance WebSocket connects to `@bookTicker` for sub-second live price ticks (100–250ms).
   - Emits `{type: "tick", symbol, price, bid, ask, time}`.
   - Frontend `applyTick` updates:
     - The `#chartPrice` header with green/red flash animation.
     - The right-axis price marker.
     - The currently forming candle's close, high, low in real time.
   - In parallel, background REST kline polling syncs authentic open/high/low/volume/closed boundaries every 5s so no drift occurs.
2. **100% Signal-to-Chart Trendline Alignment**:
   - In `build_structure_payload`:
     - If an active signal exists for the symbol, the EXACT trendline that generated the signal (`signal.trendline`) is given #1 priority in `tv_trendlines`.
     - The second line is the opposing boundary (forming the channel/wedge).
     - When the user selects a coin with a signal, the chart draws the EXACT line that broke out/broke down!
3. **TradingView-Style Position Tool (`createPriceLine`)**:
   - Replace the floating HTML chips `#tradeOverlay` with native Lightweight Charts `series.createPriceLine`:
     - **Entry**: `#65cfff`, Dashed, `ENTRY 78,617.50`
     - **Stop Loss**: `#ff5e6e`, Solid (width 2), `SL 78,959.58 (-0.4%)`
     - **Target 1**: `#00d69a`, Solid (width 2), `TP1 78,104.38 (+0.6%)`
     - **Target 2**: `#00d69a`, Dotted (width 1), `TP2 77,864.92 (+1.0%)`
   - Colored tags appear directly on the right-hand price axis.
4. **Clean Horizontal S/R Levels (No Massive Shading)**:
   - Replace the giant full-screen rectangle with crisp horizontal levels:
     - Key Resistance (recent major swing peak) with thin dashed line + label.
     - Key Support (recent major swing trough) with thin dashed line + label.

## Tasks & Waves
### Task 1: Sub-second bookTicker + kline hybrid relay in server.py
Wave: 1
Status: pending
Risk: medium
Dependencies: none
Files: `server.py`, `tests/test_server.py`
Acceptance: `/ws/market` relays real-time ticks from bookTicker while keeping kline/structure sync. Tests pass.

### Task 2: Signal-aligned trendlines & clean horizontal S/R in technical_engine.py & server.py
Wave: 2
Status: pending
Risk: medium
Dependencies: Task 1
Files: `technical_engine.py`, `server.py`, `tests/test_server.py`
Acceptance: Trendlines prioritize the signal-triggering line; S/R emitted as clean discrete levels.

### Task 3: TradingView-grade Price Lines & Ticking UI in index.html & chart_stream.js
Wave: 3
Status: pending
Risk: low
Dependencies: Task 2
Files: `static/index.html`, `static/chart_stream.js`, `tests/chart_stream.test.js`
Acceptance: `#chartPrice` ticks live with green/red pulse. Entry/SL/TP render as native PriceLines on right axis. Giant blue boxes removed.

### Task 4: Browser Verification & Live Visual Inspection
Wave: 4
Status: pending
Risk: low
Dependencies: Task 3
Acceptance: Screenshots confirm clean professional TradingView-style chart on BTC, ETH, SOL.
