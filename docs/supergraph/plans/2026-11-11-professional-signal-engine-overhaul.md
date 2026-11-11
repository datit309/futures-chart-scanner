# Professional Signal Engine & Anti-Spam Overhaul — Implementation Plan

## Goal
Overhaul the quantitative signal generation and tracking engines to eliminate noisy spam, whipsaws, and low-winrate setups. Specifically: enforce confirmed candle close validation, volume surge confirmation, single-active-position per coin (ban simultaneous LONG/SHORT), kill naive mean reversion trap (31.5% winrate) in favor of high-quality divergence/reversal, enforce trade timeout/expiration (anti-zombie), and declutter chart visualization.

## Analysis Decisions
- **Issue Diagnosis:** Database analysis of 2,587 signals revealed: (1) 31.5% winrate on `MEAN_REVERSION_TRAP` (340 losses, required R:R only 1.2), (2) 189 signals stuck in OPEN state for days/weeks, (3) opposing LONG and SHORT signals created on the same symbol at the exact same second, (4) breakouts evaluated on live unclosed forming candle `klines[-1]` causing instant trap losses, (5) no volume confirmation on breakouts, (6) 60 arrows clustered on chart obliterating candlestick view.
- **Decision 1 (Confirmed Candle Close):** Signal evaluation must check the completed candle `klines[-2]` for trendline piercing and close confirmation, using `klines[-1]["close"]` only as live entry execution reference.
- **Decision 2 (Volume Surge Filter):** A breakout must have `volume[-2] >= 1.25 * SMA(volume, 20)`. Breakouts on below-average volume are discarded as fakeouts.
- **Decision 3 (Mean Reversion Overhaul & R:R Protection):** Kill naive `low <= lower_bb and RSI <= 45` rule. Replace with strict exhaustion (`RSI <= 30` or `RSI >= 70`) AND reversal candlestick pattern (rejection wick >= 1.5x body) AND mandatory `min_rr >= 2.0` (eliminate 1.2 R:R dilution in `risk_manager.py`).
- **Decision 4 (Single Active Position Policy):** Enforce strict 1-position-per-symbol in `server.py`. If a symbol has an active `OPEN` trade, no new signal may be generated or saved for that symbol. Ban simultaneous opposing positions.
- **Decision 5 (Holding Timeout / Expiration):** In `signal_tracker.py`, if a trade is held for > 32 candles (8 hours on 15m) without reaching TP or SL, mark it as `EXPIRED` with real PnL calculated at current market close.
- **Decision 6 (Chart Decluttering & DB Maintenance):** Cap chart history arrows to the 15 most recent trades (or trades within the last 48 hours) with an active visual toggle, and provide a database cleanup routine to archive legacy noisy signals.

## Environment Context
- Language: Python 3.13 + vanilla JavaScript/HTML.
- TEST_CMD: `PYTHONPATH=. ./venv/bin/pytest tests/ -q`
- NODE_TEST_CMD: `node --test tests/chart_stream.test.js`
- LINT_CMD: `python3 -m py_compile server.py binance_client.py technical_engine.py risk_manager.py config.py chart_renderer.py telegram_notifier.py news_service.py`
- Branch: `feat/symbol-filtered-history`
- Conventions: aiohttp handlers, pytest-asyncio, pure math/geometry in TechnicalEngine, SQLite WAL in SignalTracker.

## Architecture & Contracts
- `TechnicalEngine.analyze_market(klines, symbol, timeframe)`:
  - Validates `len(klines) >= 25`.
  - Calculates 20-period volume SMA: `vol_sma = sum(v[-21:-1]) / 20`.
  - Breakout requires: `klines[-2]["volume"] >= vol_sma * 1.25` AND confirmed close: for resistance, `klines[-2]["close"] > line_val_prev` (not forming bar `klines[-1]`).
  - Mean reversion: requires `curr_rsi <= 30` (Bullish) or `curr_rsi >= 70` (Bearish), plus wick rejection: `lower_wick >= 1.5 * body` for LONG, `upper_wick >= 1.5 * body` for SHORT.
  - Dedup: Returns at most ONE single best signal per symbol, sorted by R:R.
- `RiskManager.validate_and_enrich(signal)`:
  - Removes the 1.2 R:R exception for mean reversion. Strictly requires `rr >= self.min_rr` (>= 2.0).
- `WebServerState.run_scan()`:
  - Single Active Position: if `self.active_signals.get(sym, {}).get("status") == "OPEN"`, skip generating signals for `sym`.
  - Dedup: if `save_signal` detects cooldown or existing open trade, do not broadcast duplicate `NEW_SIGNAL`.
- `SignalTracker.evaluate_signal(signal_id, candle)`:
  - Tracks `bars_held` (or checks `created_at` against candle timestamp). If `bars_held >= 32` (~8h on 15m), transitions trade to `status = "EXPIRED"` with PnL computed against `candle["close"]`.
  - If both TP and SL are pierced in the same candle, evaluate conservative outcome: `status = "LOSS"`.
- `chart_stream.js`:
  - `formatHistoryTrades(signals, limit = 15)`: reduces default limit from 60 to 15 to keep TradingView chart clean and readable.

## Task 1: Overhaul TechnicalEngine & RiskManager with Confirmed Close, Volume Surge, and Strict R:R >= 2.0
Wave: 1
Status: completed
Risk: high
Dependencies: none
Model: pro

Files:
- Modify: `technical_engine.py`
- Modify: `risk_manager.py`
- Test: `tests/test_technical_engine.py`
- Test: `tests/test_risk_manager.py`

Blast radius:
- `technical_engine.py` (core calculation)
- `risk_manager.py` (validation filter)
- `tests/test_technical_engine.py`
- `tests/test_risk_manager.py`

Acceptance:
- `analyze_market` checks confirmed bar `klines[-2]` for breakout rather than forming bar `klines[-1]`.
- Breakouts without volume surge (< 1.25x 20-SMA volume) are rejected.
- Naive mean reversion (RSI 45) is removed; strict exhaustion (RSI <= 30 / >= 70) with wick rejection is required.
- `validate_and_enrich` enforces `min_rr >= 2.0` on all patterns (no 1.2 R:R downgrade).
- Returns at most 1 signal per symbol per scan.

TDD:
- Behavior: confirmed candle close and volume filter prevent false breakout signals; strict R:R >= 2.0 enforced.
- Test file: `tests/test_technical_engine.py`
- Test name: `test_breakout_requires_confirmed_candle_close_and_volume_surge`
- 🔴 RED command: `PYTHONPATH=. ./venv/bin/pytest tests/test_technical_engine.py -k test_breakout_requires_confirmed_candle_close_and_volume_surge -q`
- Expected 🔴 RED failure: Missing volume check or forming candle check in test assertion.
- Minimal 🟢 GREEN change: Implement volume check and closed candle indexing in `technical_engine.py`, remove 1.2 R:R branch in `risk_manager.py`.
- Refactor candidates: Clean helper `_check_volume_surge`.
- Mocking: None (pure numerical klines).

Steps:
1. 🔴 RED: write unit tests asserting breakout requires volume > 1.25x SMA20 and close on bar -2.
   Command: `PYTHONPATH=. ./venv/bin/pytest tests/test_technical_engine.py -k test_breakout_requires_confirmed_candle_close_and_volume_surge -q`
   Expected: FAIL
2. 🟢 GREEN: implement confirmed close, volume surge filter, and strict R:R >= 2.0 in `technical_engine.py` and `risk_manager.py`.
   Command: `PYTHONPATH=. ./venv/bin/pytest tests/test_technical_engine.py tests/test_risk_manager.py -q`
   Expected: PASS
3. REFACTOR: verify all existing tests in `test_technical_engine.py` pass or update synthetic test fixtures.
4. VERIFY:
   - `PYTHONPATH=. ./venv/bin/pytest tests/test_technical_engine.py tests/test_risk_manager.py -q`
   - `python3 -m py_compile technical_engine.py risk_manager.py`

Checkpoint:
- Files: `technical_engine.py risk_manager.py tests/test_technical_engine.py tests/test_risk_manager.py`
- Commit: `fix(engine): enforce confirmed candle close, volume surge and strict R:R on all signals`

## Task 2: Implement Single Active Position Policy and Trade Expiration / Timeout
Wave: 2
Status: completed
Risk: medium
Dependencies: Task 1
Model: pro

Files:
- Modify: `server.py`
- Modify: `signal_tracker.py`
- Test: `tests/test_server.py`
- Test: `tests/test_signal_tracker.py`

Blast radius:
- `server.py` (scan cycle)
- `signal_tracker.py` (evaluation and persistence)
- `tests/test_server.py`
- `tests/test_signal_tracker.py`

Acceptance:
- If a symbol has an active trade (`status == 'OPEN'`), `run_scan` skips generating new signals for that symbol.
- Simultaneous opposing LONG/SHORT positions are strictly forbidden.
- Trades exceeding 32 candles (8h on 15m) without hitting TP/SL transition to `EXPIRED` status with actual PnL recorded.
- Duplicate signal notifications are blocked if `save_signal` hits cooldown or existing position.

TDD:
- Behavior: open trade on a symbol suppresses new signal generation; stale trade expires after timeout.
- Test file: `tests/test_signal_tracker.py`
- Test name: `test_signal_expires_after_max_holding_bars`
- 🔴 RED command: `PYTHONPATH=. ./venv/bin/pytest tests/test_signal_tracker.py -k test_signal_expires_after_max_holding_bars -q`
- Expected 🔴 RED failure: Signal remains OPEN after 35 candles instead of EXPIRED.
- Minimal 🟢 GREEN change: Add `max_holding_bars=32` evaluation in `evaluate_signal`, add symbol active check in `server.py`.
- Refactor candidates: None.
- Mocking: Mock Binance client for server test.

Steps:
1. 🔴 RED: write tests for trade timeout expiration in `test_signal_tracker.py` and single-position suppression in `test_server.py`.
   Command: `PYTHONPATH=. ./venv/bin/pytest tests/test_signal_tracker.py -k test_signal_expires_after_max_holding_bars -q`
   Expected: FAIL
2. 🟢 GREEN: implement expiration in `signal_tracker.py` and active position guard in `server.py`.
   Command: `PYTHONPATH=. ./venv/bin/pytest tests/test_signal_tracker.py tests/test_server.py -k "expires or single_position" -q`
   Expected: PASS
3. REFACTOR: ensure clean database transaction handling.
4. VERIFY:
   - `PYTHONPATH=. ./venv/bin/pytest tests/test_signal_tracker.py tests/test_server.py -q`
   - `python3 -m py_compile server.py signal_tracker.py`

Checkpoint:
- Files: `server.py signal_tracker.py tests/test_server.py tests/test_signal_tracker.py`
- Commit: `feat(tracker): enforce single active position policy and trade expiration timeout`

## Task 3: Declutter TradingView Chart History & Clean Stale Database Records
Wave: 3
Status: completed
Risk: low
Dependencies: Task 2
Model: inherit

Files:
- Modify: `static/chart_stream.js`
- Create: `clean_signals_db.py`
- Test: `tests/chart_stream.test.js`

Blast radius:
- `static/chart_stream.js` (chart visual rendering)
- `tests/chart_stream.test.js` (frontend tests)
- `clean_signals_db.py` (utility script)

Acceptance:
- `formatHistoryTrades` limits rendered closed trades to 15 (down from 60) and filters out trades older than 48 hours to prevent chart arrow clustering.
- `clean_signals_db.py` script prunes or archives duplicate/corrupted legacy signals in `signals.db` and expires zombie open trades older than 24 hours.
- Front-end tests pass cleanly.

TDD:
- Behavior: `formatHistoryTrades` caps history shapes to 15 and ignores ancient trades.
- Test file: `tests/chart_stream.test.js`
- Test name: `formatHistoryTrades caps output to 15 trades and filters ancient trades`
- 🔴 RED command: `node --test --test-name-pattern='formatHistoryTrades caps output' tests/chart_stream.test.js`
- Expected 🔴 RED failure: Returns 60 items instead of capped 15.
- Minimal 🟢 GREEN change: Update default limit to 15 and add timestamp window filter in `static/chart_stream.js`.
- Refactor candidates: None.
- Mocking: None.

Steps:
1. 🔴 RED: write test for 15-trade cap and 48-hour window in `tests/chart_stream.test.js`.
   Command: `node --test --test-name-pattern='formatHistoryTrades caps output' tests/chart_stream.test.js`
   Expected: FAIL
2. 🟢 GREEN: implement cap and window in `formatHistoryTrades`, create `clean_signals_db.py`.
   Command: `node --test tests/chart_stream.test.js`
   Expected: PASS
3. VERIFY:
   - `node --test tests/chart_stream.test.js`
   - `PYTHONPATH=. ./venv/bin/pytest tests/ -q`
   - `python3 -m py_compile clean_signals_db.py`

Checkpoint:
- Files: `static/chart_stream.js tests/chart_stream.test.js clean_signals_db.py`
- Commit: `fix(chart): declutter history trade markers and provide db cleanup utility`

## Task DAG
- Wave 1: Task 1 (Core Engine & Risk Filters)
- Wave 2: Task 2 (Single Position & Expiration Timeout) -> depends on Task 1
- Wave 3: Task 3 (Chart History Declutter & Database Cleanup) -> depends on Task 2

## Plan Review
- Initial self-review: All 3 tasks have exact file paths, explicit TDD commands, RED failure expectations, and focused acceptance criteria.
- Invariants checked: No dilution of R:R below 2.0; scan does not emit signals for coins already in active trade; signals strictly use closed bar confirmation.
- User approval: Pending.

## User Gate
- Approval required before implementation.
- Choices: `yes`, `modify`, `reject`.
