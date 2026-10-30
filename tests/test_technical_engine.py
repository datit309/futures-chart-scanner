import pytest
from technical_engine import (
    TechnicalEngine,
    SwingPoint,
    Trendline,
    PatternType
)

def create_synthetic_klines(prices: list[tuple[float, float, float, float]]):
    """Helper to create kline dicts from (open, high, low, close) tuples"""
    klines = []
    base_ts = 1700000000000
    for idx, (o, h, l, c) in enumerate(prices):
        klines.append({
            "timestamp": base_ts + idx * 900000,
            "open": o,
            "high": h,
            "low": l,
            "close": c,
            "volume": 100.0,
            "close_time": base_ts + (idx + 1) * 900000 - 1
        })
    return klines

def test_find_swing_points():
    engine = TechnicalEngine()
    # Sequence with clear swing high at index 2 and swing low at index 5
    prices = [
        (100, 102, 99, 101),
        (101, 105, 100, 104),
        (104, 110, 103, 108),  # Swing High at index 2 (H=110)
        (108, 107, 102, 103),
        (103, 104, 98, 99),
        (99, 101, 95, 96),     # Swing Low at index 5 (L=95)
        (96, 102, 96, 101),
        (101, 103, 100, 102),
    ]
    klines = create_synthetic_klines(prices)
    swings = engine.find_swing_points(klines, window=2)

    highs = [s for s in swings if s.is_high]
    lows = [s for s in swings if not s.is_high]

    assert any(s.index == 2 and s.price == 110.0 for s in highs)
    assert any(s.index == 5 and s.price == 95.0 for s in lows)

def test_detect_downtrend_line_and_breakout():
    engine = TechnicalEngine()
    # Construct a downward channel:
    # Highs at i=2 (100), i=6 (95), i=10 (90) - slope is -1.25 per bar
    # Then at i=12, price breaks out to 92 (above the trendline which is at ~87.5)
    prices = [
        (95, 96, 94, 95),       # 0
        (95, 98, 95, 97),       # 1
        (97, 100, 96, 98),      # 2: Swing High 1 (100)
        (98, 98, 93, 94),       # 3
        (94, 95, 92, 93),       # 4
        (93, 94, 91, 92),       # 5
        (92, 95, 91, 94),       # 6: Swing High 2 (95)
        (94, 94, 89, 90),       # 7
        (90, 91, 88, 89),       # 8
        (89, 90, 87, 88),       # 9
        (88, 90, 87, 89),       # 10: Swing High 3 (90)
        (89, 89, 86, 87),       # 11
        (87, 93, 87, 92),       # 12: Breakout bar! Close=92, way above line
    ]
    klines = create_synthetic_klines(prices)
    swings = engine.find_swing_points(klines, window=2)
    trendlines = engine.detect_trendlines(klines, swings, min_touches=3, tolerance_pct=0.01)

    assert len(trendlines) >= 1
    best_line = trendlines[0]
    assert best_line.is_resistance is True
    assert best_line.touches >= 3

    # Check breakout signal
    signals = engine.analyze_market(klines, symbol="BTCUSDT", timeframe="15m")
    assert len(signals) >= 1
    breakout_signal = signals[0]
    assert breakout_signal.signal_type == "LONG"
    assert breakout_signal.pattern == PatternType.TRENDLINE_BREAKOUT

def test_detect_fvg():
    engine = TechnicalEngine()
    # Bullish FVG: Bar 0 High is 100. Bar 1 goes 100 -> 110. Bar 2 Low is 104.
    # Gap between Bar 0 High (100) and Bar 2 Low (104) is 4.0 points.
    prices = [
        (98, 100, 97, 99),     # Bar 0: High = 100
        (99, 110, 99, 109),    # Bar 1: Big expansion
        (109, 112, 104, 111),  # Bar 2: Low = 104
    ]
    klines = create_synthetic_klines(prices)
    fvgs = engine.detect_fvg(klines)

    assert len(fvgs) == 1
    assert fvgs[0]["type"] == "BULLISH"
    assert fvgs[0]["bottom"] == 100.0
    assert fvgs[0]["top"] == 104.0
