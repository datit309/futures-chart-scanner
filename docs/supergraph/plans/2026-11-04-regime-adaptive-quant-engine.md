# Plan: Regime-Adaptive Quantitative Trading Engine (SMC Pullback + Mean Reversion Trap)

## Problem Statement
Empirical backtesting on 1,000 real Binance Futures 15m candles revealed:
1. **Naive Breakouts fail 88% of the time (12.2% Win Rate, -37R)** because algorithmic market makers trigger stop hunts (liquidity sweeps) at key highs/lows.
2. **Mean Reversion at Volatility Extremes during Choppy/Ranging Markets achieves 60% - 83% Win Rate** (+2R to +6R profit across BTC, ETH, SOL, BNB, DOGE).
3. **SMC Order Block Retests during Trending Markets achieve high R:R (1:2.5)** when aligned with Higher-Timeframe trend direction and protected by ATR buffers and breakeven stops.

We need to upgrade the technical engine from naive breakout detection to an institutional **Regime-Adaptive Quantitative Engine**:
- **Range-Bound Regime (ADX < 26, ~70% of time)**: Trade **Mean Reversion Traps** (fading Bollinger Band $2\sigma$ piercings with RSI extremes, targeting Middle Band SMA20).
- **Trending Regime (ADX >= 26, ~30% of time)**: Trade **SMC Order Block Retests** (pullbacks into demand/supply zones aligned with EMA200 trend, targeting opposite swing extremes).
- **Dynamic Trade Management**: Move SL to Breakeven once TP1 is achieved.

## Architecture & Contracts
### 1. Market Signals (`technical_engine.py`)
```python
class PatternType(Enum):
    TRENDLINE_BREAKOUT = "TRENDLINE_BREAKOUT"
    MEAN_REVERSION_TRAP = "MEAN_REVERSION_TRAP"
    SMC_ORDER_BLOCK_RETEST = "SMC_ORDER_BLOCK_RETEST"

@dataclass
class MarketSignal:
    symbol: str
    timeframe: str
    signal_type: str  # "LONG" or "SHORT"
    pattern: PatternType
    entry_price: float
    stop_loss: float
    take_profit: float
    risk_reward: float
    description: str
    regime: str  # "RANGING" or "TRENDING"
    tp1: float = 0.0
    tp2: float = 0.0
    ...
```

### 2. Signal Tracker Breakeven Protection (`signal_tracker.py`)
- When candle touches `tp1`, set `tp1_hit = 1` and move active stop loss to `entry_price` (0 risk).
- When candle touches `tp2`, mark trade as `WIN` with realized `+2.2R` or weighted R-multiple.
- If stopped after `tp1_hit`, mark trade as `WIN` (breakeven profit on partial position, e.g. `+0.6R`).

## Wave Assignment & Task DAG
- **Wave 1:** Core Quantitative Indicators & Regime Classifier in `technical_engine.py` (ADX, RSI, Bollinger Bands, ATR, Regime Detection).
- **Wave 2:** Regime-Adaptive Signal Generation in `technical_engine.py` (Mean Reversion Trap & SMC Retest) + Risk Manager adaptation.
- **Wave 3:** Breakeven Stop Management in `signal_tracker.py` & Server Payload Integration.
- **Wave 4:** End-to-End Live Browser QA & Verification.

---

## Task 1: Core Quant Indicators & Regime Classifier (RED -> GREEN)
Wave: 1
Status: pending
Risk: low
Dependencies: none
Model: inherit

Files:
- Modify: `technical_engine.py`
- Modify: `tests/test_technical_engine.py`

Blast radius:
- `technical_engine.py`
- `tests/test_technical_engine.py`

Acceptance:
- `calc_adx(klines, period=14)` correctly computes Average Directional Index.
- `calc_rsi(klines, period=14)` computes Relative Strength Index.
- `calc_bollinger_bands(klines, period=20, num_std=2.0)` computes upper, middle, lower bands.
- `calc_atr(klines, period=14)` computes Average True Range.
- `detect_market_regime(klines)` returns `"RANGING"` when ADX < 26, `"TRENDING_BULL"` or `"TRENDING_BEAR"` when ADX >= 26.

TDD:
- Behavior: technical indicator and regime classification functions produce expected mathematical values
- Test file: `tests/test_technical_engine.py`
- Test name: `test_quant_indicators_and_regime_classification`
- 🔴 RED command: `PYTHONPATH=. ./venv/bin/pytest tests/test_technical_engine.py -k test_quant_indicators_and_regime_classification`
- Expected 🔴 RED failure: `AttributeError: 'TechnicalEngine' object has no attribute 'detect_market_regime'`
- Minimal 🟢 GREEN change: implement `calc_adx`, `calc_rsi`, `calc_bollinger_bands`, `calc_atr`, `detect_market_regime` in `TechnicalEngine`.

Steps:
1. 🔴 RED: write unit test in `tests/test_technical_engine.py`
   Command: `PYTHONPATH=. ./venv/bin/pytest tests/test_technical_engine.py -k test_quant_indicators_and_regime_classification`
   Expected: FAIL
2. 🟢 GREEN: implement indicator methods in `technical_engine.py`
   Command: `PYTHONPATH=. ./venv/bin/pytest tests/test_technical_engine.py -k test_quant_indicators_and_regime_classification`
   Expected: PASS
3. VERIFY: `PYTHONPATH=. ./venv/bin/pytest tests/test_technical_engine.py -q`

---

## Task 2: Regime-Adaptive Signal Generation (Mean Reversion Trap & SMC Retest)
Wave: 2
Status: pending
Risk: medium
Dependencies: Task 1
Model: pro

Files:
- Modify: `technical_engine.py`
- Modify: `risk_manager.py`
- Modify: `tests/test_technical_engine.py`

Blast radius:
- `technical_engine.py`
- `risk_manager.py`

Acceptance:
- In Range regime (ADX < 26): Detects `MEAN_REVERSION_TRAP` on lower/upper BB piercing with RSI divergence/exhaustion and long rejection wicks. TP set to middle band.
- In Trending regime (ADX >= 26): Detects `SMC_ORDER_BLOCK_RETEST` when price pulls back into Demand/Supply zone aligned with EMA200 trend.
- Disables low-probability naive breakout signals that have <15% win rates.
- `analyze_market()` yields high-expectancy setups.

TDD:
- Behavior: `analyze_market` produces `MEAN_REVERSION_TRAP` in ranges and `SMC_ORDER_BLOCK_RETEST` in trends
- Test file: `tests/test_technical_engine.py`
- Test name: `test_regime_adaptive_signals_generation`
- 🔴 RED command: `PYTHONPATH=. ./venv/bin/pytest tests/test_technical_engine.py -k test_regime_adaptive_signals_generation`
- Minimal 🟢 GREEN change: implement signal detection logic and update `analyze_market`.

Steps:
1. 🔴 RED: write unit tests for mean reversion and SMC retest signal generation
2. 🟢 GREEN: implement pattern logic in `technical_engine.py`
3. VERIFY: `PYTHONPATH=. ./venv/bin/pytest tests/ -q`

---

## Task 3: Signal Tracker Breakeven Protection & Trade Evaluation
Wave: 3
Status: pending
Risk: medium
Dependencies: Task 2
Model: inherit

Files:
- Modify: `signal_tracker.py`
- Modify: `tests/test_signal_tracker.py`

Blast radius:
- `signal_tracker.py`

Acceptance:
- Update `signals` table schema to include `breakeven_reached` and `tp1_hit` columns.
- When an open trade's high/low hits `tp1`, move the trade's effective stop loss to `entry_price`.
- If price later reverses, trade exits at Breakeven with positive realized PnL from partial take profit instead of -1.0R loss.
- Unit tests verify breakeven transition on both LONG and SHORT trades.

Steps:
1. 🔴 RED: write test for breakeven stop loss migration upon TP1 hit in `tests/test_signal_tracker.py`.
2. 🟢 GREEN: update `SignalTracker.evaluate_signal` to track `tp1_hit` and adjust stop loss.
3. VERIFY: `PYTHONPATH=. ./venv/bin/pytest tests/ -q`.

---

## Task 4: Server Payload & TradingView UI Integration & Browser QA
Wave: 4
Status: pending
Risk: low
Dependencies: Task 3
Model: pro

Files:
- Modify: `server.py`
- Modify: `static/chart_stream.js`
- Modify: `static/index.html`

Blast radius:
- `server.py`
- `static/chart_stream.js`
- `static/index.html`

Acceptance:
- UI badge reflects pattern: `MEAN REVERSION` or `SMC RETEST`.
- OrderLines for Entry, SL, TP1, TP2 render natively on TradingView chart.
- Browser QA confirms live tick updates, signal selection, and clean shape rendering.
- All 39+ Python tests and 21+ Node tests pass.

Steps:
1. Wire new pattern badges in `formatOutcomeBadge` and `server.py`
2. Run browser live verification via `agent-browser`
3. Commit and open PR.
