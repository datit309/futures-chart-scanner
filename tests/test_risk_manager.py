import pytest
from technical_engine import MarketSignal, PatternType
from risk_manager import RiskManager

def test_risk_manager_valid_long_setup():
    rm = RiskManager(min_rr=2.0, max_sl_pct=0.035, min_sl_pct=0.003)
    signal = MarketSignal(
        symbol="BTCUSDT",
        timeframe="15m",
        signal_type="LONG",
        pattern=PatternType.TRENDLINE_BREAKOUT,
        entry_price=60000.0,
        stop_loss=59400.0,  # 1% SL = 600 risk
        take_profit=61500.0, # 1500 reward -> R:R = 2.5
        risk_reward=2.5,
        description="Bullish Breakout"
    )

    enriched = rm.validate_and_enrich(signal)
    assert enriched is not None
    assert enriched.risk_reward >= 2.0
    assert enriched.stop_loss == 59400.0
    assert "tp1" in enriched.extra_targets
    assert "tp2" in enriched.extra_targets
    assert enriched.extra_targets["tp2"] >= 61200.0

def test_risk_manager_rejects_poor_rr():
    rm = RiskManager(min_rr=2.0)
    signal = MarketSignal(
        symbol="ETHUSDT",
        timeframe="15m",
        signal_type="LONG",
        pattern=PatternType.TRENDLINE_BREAKOUT,
        entry_price=3000.0,
        stop_loss=2900.0,   # Risk = 100
        take_profit=3100.0, # Reward = 100 -> R:R = 1.0 (fails min_rr 2.0)
        risk_reward=1.0,
        description="Weak R:R"
    )

    enriched = rm.validate_and_enrich(signal)
    assert enriched is None

def test_risk_manager_rejects_extreme_stop_loss():
    rm = RiskManager(min_rr=2.0, max_sl_pct=0.035)
    # SL is 10% below entry (way too wide for 15m futures)
    signal = MarketSignal(
        symbol="SOLUSDT",
        timeframe="15m",
        signal_type="LONG",
        pattern=PatternType.TRENDLINE_BREAKOUT,
        entry_price=100.0,
        stop_loss=90.0,     # 10% SL
        take_profit=130.0,
        risk_reward=3.0,
        description="Stop Loss Too Wide"
    )

    enriched = rm.validate_and_enrich(signal)
    assert enriched is None
