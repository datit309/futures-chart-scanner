# Plan: Lina RSI Wave Phase & Trend Pullback Integration

## Problem Statement
The user requested integrating the "Lina RSI - Wave Phase RSI with Trend Pullback Zones" concept into the system ("ok dc thì dùng").
Lina RSI combines:
- **Classic RSI (14)**
- **Fast EMA (9)** on RSI
- **Slow WMA (45)** on RSI
- **Momentum Cloud**: EMA(9) vs WMA(45) showing whether bullish or bearish wave momentum is expanding or losing strength.
- **Trend Pullback Zones**:
  - In an Up-Wave: Green pullback band from 55 down to 40.
  - In a Down-Wave: Red pullback band from 45 up to 60.
- **Pullback Completion Signal**:
  - When RSI dips into 40-55 and bounces back above EMA(9) in an uptrend -> Bullish Pullback.
  - When RSI rallies into 45-60 and turns down below EMA(9) in a downtrend -> Bearish Pullback.

## Architecture & Scope
1. **Python Technical Engine (`technical_engine.py`)**:
   - `calc_wma(arr, period)`: Weighted Moving Average.
   - `calc_lina_rsi(klines)`: Computes RSI(14), EMA(9) of RSI, and WMA(45) of RSI.
   - `PatternType.LINA_RSI_PULLBACK`: Signal generation in `analyze_market` when price completes a pullback in the 40-55 or 45-60 zone with favorable R:R.
2. **Signal Translation & Guide (`chart_stream.js` & `index.html`)**:
   - Translate Lina RSI setups into plain Vietnamese in `formatSignalPlainExplanation` and the Beginner Guide Modal.
3. **TradingView Charting Library Custom Indicator (`index.html`)**:
   - Register `custom_indicators_getter` providing `Lina RSI (Wave Momentum & Pullback Zones)` with RSI line, EMA(9), WMA(45), and the 40-55 / 45-60 bands directly in the TradingView chart!

## Tasks
- **Task 1:** Implement WMA & Lina RSI Wave Pullback signal detection in `technical_engine.py` (RED -> GREEN).
- **Task 2:** Unit tests in `tests/test_technical_engine.py` and `tests/chart_stream.test.js` (RED -> GREEN).
- **Task 3:** Register Lina RSI Custom Indicator in TradingView Charting Library (`static/index.html`) and update Guide Modal.
- **Task 4:** Browser live QA verification on running server.
