# Institutional Quant Upgrade — Implementation Plan

## Goal
Elevate the trading scanner from basic 15m retail price action to an institutional-grade quantitative system with:
1. Multi-Timeframe (MTF) 1H trend alignment and BTC volatility circuit breaker.
2. Derivatives order-flow confirmation via Binance Open Interest (OI delta) and Funding Rate guard.
3. Universal dynamic trade management: automatic 1.5R partial profit lock + breakeven stop loss + runner trailing.
4. Real-time TradingView HUD displaying MTF trend, OI confirmation status, and breakeven milestones.

## Analysis Decisions
- **Issue Diagnosis:** Pure 15m technical signals frequently hit false breakout traps when opposing higher-timeframe (1H/4H) momentum or during sudden Bitcoin flash moves that liquidate the broader market. Furthermore, breakout validation without derivatives order flow ($\Delta OI$) cannot distinguish between fresh institutional accumulation and short-squeeze exhaustion.
- **Decision 1 (MTF 1H Alignment):** Evaluate 1H market structure alongside 15m. LONG setups require 1H close > 1H EMA50 and bullish structure; SHORT setups require 1H close < 1H EMA50 and bearish structure. Counter-trend setups are strictly filtered.
- **Decision 2 (BTC Volatility Circuit Breaker):** When BTC 15m volatility exceeds 1.2% or ATR ratio spikes > 2.0x, pause signal generation across all altcoins until Bitcoin market stabilizes.
- **Decision 3 (Open Interest & Funding Rate Filter):** Query Binance public endpoints `/fapi/v1/openInterest` and `/fapi/v1/premiumIndex`. Require positive or neutral OI delta for breakouts. Veto LONG when funding rate > +0.04% (extreme long crowd) and veto SHORT when funding rate < -0.04%.
- **Decision 4 (Universal Breakeven + Runner):** Expand breakeven protection across ALL patterns in `signal_tracker.py`. When high >= TP1 (LONG) or low <= TP1 (SHORT), lock 50% profit, move SL to entry (Risk-Free), and let the remaining position target TP2.
- **Decision 5 (HUD & Metrics Display):** Add badges to the UI for MTF status ("1H BULL / 1H BEAR"), OI Delta ("+OI CONFIRMED"), and Funding Rate ("FR 0.01%").

## Environment Context
- Language: Python 3.13 + vanilla JavaScript/HTML.
- TEST_CMD: `PYTHONPATH=. ./venv/bin/pytest tests/ -q`
- NODE_TEST_CMD: `node --test tests/chart_stream.test.js`
- LINT_CMD: `python3 -m py_compile server.py binance_client.py technical_engine.py risk_manager.py config.py chart_renderer.py telegram_notifier.py news_service.py`
- Branch: `feat/symbol-filtered-history`
- Base Conventions: async BinanceClient, dataclass signals, SQLite WAL persistence, clean vanilla JS modules without external npm runtime dependencies.

## Architecture & Contracts
- `BinanceClient`:
  - `get_open_interest(symbol: str) -> float`: fetches current open interest from `/fapi/v1/openInterest`.
  - `get_funding_rate(symbol: str) -> float`: fetches latest funding rate from `/fapi/v1/premiumIndex`.
- `TechnicalEngine`:
  - `detect_htf_bias(klines_1h: List[Dict[str, Any]]) -> str`: returns `"BULLISH"`, `"BEARISH"`, or `"NEUTRAL"`.
  - `is_btc_circuit_breaker_active(btc_klines_15m: List[Dict[str, Any]], threshold_pct: float = 0.012) -> bool`: returns `True` if recent BTC bar volatility exceeds threshold.
  - `analyze_market(...)`: receives optional `htf_bias` parameter. If `htf_bias == "BULLISH"`, rejects SHORT signals; if `htf_bias == "BEARISH"`, rejects LONG signals.
- `RiskManager`:
  - `validate_and_enrich(signal, open_interest=None, funding_rate=None)`: rejects signals with extreme opposing funding rates (> 0.04% for LONG, < -0.04% for SHORT).
- `SignalTracker`:
  - `evaluate_signal(...)`: sets `use_be_runner = True` for all trades where `tp2 > tp1` (or `tp2 < tp1` for short). When TP1 is pierced, updates stop loss to entry and records `breakeven_reached = 1`.
- `static/chart_stream.js`:
  - `formatSignalTooltipData(signal)`: renders MTF alignment badge, OI status, and BE status in HUD tooltip.

---

## Task 1: MTF 1H Alignment & BTC Volatility Circuit Breaker
Wave: 1
Status: completed
Risk: medium
Dependencies: none
Model: pro

Files:
- Modify: `technical_engine.py`
- Modify: `server.py`
- Test: `tests/test_technical_engine.py`
- Test: `tests/test_server.py`

Blast radius:
- `technical_engine.py` (trend filtering)
- `server.py` (scan cycle orchestration)
- `tests/test_technical_engine.py`
- `tests/test_server.py`

Acceptance:
- `TechnicalEngine.detect_htf_bias(klines_1h)` correctly classifies market as `"BULLISH"`, `"BEARISH"`, or `"NEUTRAL"`.
- `TechnicalEngine.is_btc_circuit_breaker_active(btc_klines)` flags violent BTC volatility (> 1.2% move in 15m).
- `analyze_market` rejects 15m counter-trend setups when `htf_bias` is provided.
- `server.py.run_scan()` skips altcoin signals when BTC circuit breaker is tripped.

TDD:
- Behavior: 1H trend alignment filters counter-trend breakouts; BTC volatility spike pauses altcoin scanning.
- Test file: `tests/test_technical_engine.py`
- Test name: `test_mtf_htf_bias_and_btc_circuit_breaker`
- 🔴 RED command: `PYTHONPATH=. ./venv/bin/pytest tests/test_technical_engine.py -k test_mtf_htf_bias_and_btc_circuit_breaker -q`
- Expected 🔴 RED failure: Missing `detect_htf_bias` or `is_btc_circuit_breaker_active`.
- Minimal 🟢 GREEN change: Implement `detect_htf_bias` and `is_btc_circuit_breaker_active` in `technical_engine.py`, integrate in `server.py`.
- Refactor candidates: None.
- Mocking: Mocked 1H and 15m klines.

Steps:
1. 🔴 RED: write unit tests asserting HTF trend alignment and BTC circuit breaker detection.
   Command: `PYTHONPATH=. ./venv/bin/pytest tests/test_technical_engine.py -k test_mtf_htf_bias_and_btc_circuit_breaker -q`
   Expected: FAIL
2. 🟢 GREEN: implement methods in `technical_engine.py` and hook into `server.py.run_scan()`.
   Command: `PYTHONPATH=. ./venv/bin/pytest tests/test_technical_engine.py tests/test_server.py -q`
   Expected: PASS
3. REFACTOR: verify clean execution without unhandled exceptions.
4. VERIFY:
   - `PYTHONPATH=. ./venv/bin/pytest tests/test_technical_engine.py tests/test_server.py -q`
   - `python3 -m py_compile technical_engine.py server.py`

Checkpoint:
- Files: `technical_engine.py server.py tests/test_technical_engine.py tests/test_server.py`
- Commit: `feat(engine): add 1H MTF trend alignment and BTC volatility circuit breaker`

---

## Task 2: Derivatives Order Flow Confirmation (Open Interest & Funding Rate Filter)
Wave: 2
Status: completed
Risk: medium
Dependencies: Task 1
Model: pro

Files:
- Modify: `binance_client.py`
- Modify: `risk_manager.py`
- Modify: `server.py`
- Test: `tests/test_binance_client.py`
- Test: `tests/test_risk_manager.py`

Blast radius:
- `binance_client.py` (new API endpoints)
- `risk_manager.py` (order flow validation)
- `server.py` (passing metrics into risk manager)
- `tests/test_binance_client.py`
- `tests/test_risk_manager.py`

Acceptance:
- `BinanceClient.get_open_interest(symbol)` fetches open interest amount.
- `BinanceClient.get_funding_rate(symbol)` fetches current funding rate.
- `RiskManager.validate_and_enrich` rejects LONG when funding rate > 0.04% and rejects SHORT when funding rate < -0.04%.
- Signal dictionary contains `funding_rate` and `open_interest` metadata.

TDD:
- Behavior: extreme funding rate crowds are rejected; open interest and funding rate are fetched and parsed safely.
- Test file: `tests/test_risk_manager.py`
- Test name: `test_risk_manager_funding_rate_crowd_filter`
- 🔴 RED command: `PYTHONPATH=. ./venv/bin/pytest tests/test_risk_manager.py -k test_risk_manager_funding_rate_crowd_filter -q`
- Expected 🔴 RED failure: Function does not reject extreme funding rates or missing parameter.
- Minimal 🟢 GREEN change: Add endpoints to `binance_client.py`, add funding rate check to `risk_manager.py`.
- Refactor candidates: None.
- Mocking: Mock Binance responses for `/fapi/v1/openInterest` and `/fapi/v1/premiumIndex`.

Steps:
1. 🔴 RED: write unit test verifying funding rate guard and client methods.
   Command: `PYTHONPATH=. ./venv/bin/pytest tests/test_risk_manager.py -k test_risk_manager_funding_rate_crowd_filter -q`
   Expected: FAIL
2. 🟢 GREEN: implement client methods and funding rate validation rule.
   Command: `PYTHONPATH=. ./venv/bin/pytest tests/test_binance_client.py tests/test_risk_manager.py -q`
   Expected: PASS
3. REFACTOR: ensure timeouts and failure safety if Binance funding rate endpoint is unreachable.
4. VERIFY:
   - `PYTHONPATH=. ./venv/bin/pytest tests/test_binance_client.py tests/test_risk_manager.py -q`
   - `python3 -m py_compile binance_client.py risk_manager.py`

Checkpoint:
- Files: `binance_client.py risk_manager.py server.py tests/test_binance_client.py tests/test_risk_manager.py`
- Commit: `feat(quant): integrate open interest and funding rate order flow filter`

---

## Task 3: Universal Dynamic Trade Management (1.5R Breakeven + Runner Trailing Stop)
Wave: 3
Status: completed
Risk: medium
Dependencies: Task 2
Model: pro

Files:
- Modify: `signal_tracker.py`
- Test: `tests/test_signal_tracker.py`

Blast radius:
- `signal_tracker.py` (trade outcome evaluation)
- `tests/test_signal_tracker.py`

Acceptance:
- Breakeven runner behavior applies universally to all patterns: when TP1 (1.5R) is reached, 50% profit is secured, Stop Loss is moved to Entry (0 risk), and remaining trade runs towards TP2.
- If price reverses after TP1 and hits entry, trade closes as a partial WIN (not a loss).
- If price hits TP2, trade closes as a full WIN (+2.5R).

TDD:
- Behavior: any breakout or mean reversion hitting TP1 transitions to breakeven protection.
- Test file: `tests/test_signal_tracker.py`
- Test name: `test_universal_breakeven_protection_on_all_patterns`
- 🔴 RED command: `PYTHONPATH=. ./venv/bin/pytest tests/test_signal_tracker.py -k test_universal_breakeven_protection_on_all_patterns -q`
- Expected 🔴 RED failure: Non-SMC pattern does not trigger breakeven runner.
- Minimal 🟢 GREEN change: Enable `use_be_runner` whenever `tp2` exists.
- Refactor candidates: None.
- Mocking: None.

Steps:
1. 🔴 RED: write unit test checking that TRENDLINE_BREAKOUT and MEAN_REVERSION_TRAP trades lock in breakeven on TP1.
   Command: `PYTHONPATH=. ./venv/bin/pytest tests/test_signal_tracker.py -k test_universal_breakeven_protection_on_all_patterns -q`
   Expected: FAIL
2. 🟢 GREEN: update `signal_tracker.py` to activate breakeven runner universally.
   Command: `PYTHONPATH=. ./venv/bin/pytest tests/test_signal_tracker.py -q`
   Expected: PASS
3. REFACTOR: clean calculation of partial PnL.
4. VERIFY:
   - `PYTHONPATH=. ./venv/bin/pytest tests/test_signal_tracker.py -q`
   - `python3 -m py_compile signal_tracker.py`

Checkpoint:
- Files: `signal_tracker.py tests/test_signal_tracker.py`
- Commit: `feat(tracker): enable universal 1.5R breakeven protection and partial profit lock`

---

## Task 4: UI TradingView HUD & Metrics (HTF Trend, Funding, and Breakeven Badges)
Wave: 4
Status: completed
Risk: low
Dependencies: Task 3
Model: inherit

Files:
- Modify: `static/chart_stream.js`
- Modify: `static/index.html`
- Test: `tests/chart_stream.test.js`

Blast radius:
- `static/chart_stream.js` (tooltip & overlays)
- `static/index.html` (DOM elements)
- `tests/chart_stream.test.js`

Acceptance:
- Tooltip HUD on chart hover displays HTF Trend ("1H BULL" or "1H BEAR"), Funding Rate, and Breakeven status.
- Signal cards in sidebar show small indicator chips for Breakeven (`BE ACTIVE`) and HTF Trend.
- All frontend tests pass cleanly.

TDD:
- Behavior: `formatSignalTooltipData` includes `htfBias`, `fundingRate`, and `beStatus`.
- Test file: `tests/chart_stream.test.js`
- Test name: `formatSignalTooltipData includes HTF trend and order flow metrics`
- 🔴 RED command: `node --test --test-name-pattern='formatSignalTooltipData includes HTF trend' tests/chart_stream.test.js`
- Expected 🔴 RED failure: Missing `htfBias` or `fundingRate` in tooltip output.
- Minimal 🟢 GREEN change: Add fields to `formatSignalTooltipData` and update `static/index.html`.
- Refactor candidates: None.
- Mocking: None.

Steps:
1. 🔴 RED: write unit test in `tests/chart_stream.test.js`.
   Command: `node --test --test-name-pattern='formatSignalTooltipData includes HTF trend' tests/chart_stream.test.js`
   Expected: FAIL
2. 🟢 GREEN: implement formatting in `static/chart_stream.js` and HUD update in `static/index.html`.
   Command: `node --test tests/chart_stream.test.js`
   Expected: PASS
3. REFACTOR: polish CSS styling and layout.
4. VERIFY:
   - `node --test tests/chart_stream.test.js`
   - `PYTHONPATH=. ./venv/bin/pytest tests/ -q`

Checkpoint:
- Files: `static/chart_stream.js static/index.html tests/chart_stream.test.js`
- Commit: `feat(ui): display HTF trend alignment, funding rate and breakeven status on chart HUD`

---

## Task DAG
- Wave 1: Task 1 (MTF 1H Alignment & BTC Circuit Breaker)
- Wave 2: Task 2 (Derivatives Order Flow: OI & Funding Rate) -> depends on Task 1
- Wave 3: Task 3 (Universal 1.5R Breakeven + Runner) -> depends on Task 2
- Wave 4: Task 4 (UI HUD & Order Flow Indicators) -> depends on Task 3

## User Gate
- Approval required before implementation.
- Choices: `yes`, `modify`, `reject`.
