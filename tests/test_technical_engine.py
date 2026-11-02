from technical_engine import PatternType, SwingPoint, TechnicalEngine, Trendline


def create_synthetic_klines(prices: list[tuple[float, float, float, float]]):
    """Build kline dictionaries from (open, high, low, close) tuples."""
    base_ts = 1700000000000
    return [
        {
            "timestamp": base_ts + idx * 900000,
            "open": o,
            "high": h,
            "low": low,
            "close": close,
            "volume": 100.0,
            "close_time": base_ts + (idx + 1) * 900000 - 1,
        }
        for idx, (o, h, low, close) in enumerate(prices)
    ]


def test_find_swing_points():
    engine = TechnicalEngine()
    prices = [
        (100, 102, 99, 101),
        (101, 105, 100, 104),
        (104, 110, 103, 108),
        (108, 107, 102, 103),
        (103, 104, 98, 99),
        (99, 101, 95, 96),
        (96, 102, 96, 101),
        (101, 103, 100, 102),
    ]
    swings = engine.find_swing_points(create_synthetic_klines(prices), window=2)
    highs = [point for point in swings if point.is_high]
    lows = [point for point in swings if not point.is_high]
    assert any(point.index == 2 and point.price == 110 for point in highs)
    assert any(point.index == 5 and point.price == 95 for point in lows)


def test_detect_downtrend_line_and_breakout():
    engine = TechnicalEngine()
    prices = [
        (95, 96, 94, 95), (95, 98, 95, 97), (97, 100, 96, 98),
        (98, 98, 93, 94), (94, 95, 92, 93), (93, 94, 91, 92),
        (92, 95, 91, 94), (94, 94, 89, 90), (90, 91, 88, 89),
        (89, 90, 87, 88), (88, 90, 87, 89), (89, 89, 86, 87),
        (87, 93, 87, 92),
    ]
    klines = create_synthetic_klines(prices)
    swings = engine.find_swing_points(klines, window=2)
    trendlines = engine.detect_trendlines(klines, swings, min_touches=3, tolerance_pct=0.01)
    assert trendlines
    assert trendlines[0].is_resistance is True
    assert trendlines[0].touches >= 3
    signals = engine.analyze_market(klines, symbol="BTCUSDT", timeframe="15m")
    assert signals
    assert signals[0].signal_type == "LONG"
    assert signals[0].pattern == PatternType.TRENDLINE_BREAKOUT


def test_detect_fvg():
    engine = TechnicalEngine()
    prices = [(98, 100, 97, 99), (99, 110, 99, 109), (109, 112, 104, 111)]
    fvgs = engine.detect_fvg(create_synthetic_klines(prices))
    assert len(fvgs) == 1
    assert fvgs[0]["type"] == "BULLISH"
    assert fvgs[0]["bottom"] == 100
    assert fvgs[0]["top"] == 104


def test_select_strongest_trendlines_is_deterministic():
    engine = TechnicalEngine()
    lines = [
        Trendline((1, 100), (4, 97), -1, 101, 4, True, 90, [1, 4, 6, 8]),
        Trendline((2, 99), (7, 94), -1, 101, 5, True, 89, [2, 5, 7, 9, 11]),
        Trendline((3, 98), (8, 93), -1, 101, 5, True, 88, [3, 6, 8, 10, 12]),
        Trendline((1, 80), (5, 84), 1, 79, 3, False, 90, [1, 5, 8]),
        Trendline((2, 81), (8, 87), 1, 79, 4, False, 90, [2, 4, 6, 8]),
    ]
    selected = engine.select_strongest_trendlines(lines)
    assert len(selected) == 2
    assert selected[0].is_resistance is True
    assert selected[0].touches == 5
    assert selected[0].point2[0] == 8
    assert selected[1].is_resistance is False
    assert selected[1].touches == 4
    assert engine.select_strongest_trendlines(lines) == selected


def test_select_strongest_trendlines_breaks_ties_by_residual():
    engine = TechnicalEngine()
    better = Trendline((2, 99), (8, 93), -1, 101, 5, True, 88, [2, 4, 6, 8, 10])
    worse = Trendline((2, 99), (8, 93), -1, 101, 5, True, 88, [2, 4, 6, 8, 10])
    better.residual = 0.001
    worse.residual = 0.004
    selected = engine.select_strongest_trendlines([worse, better])
    assert len(selected) == 1
    assert selected[0].residual == 0.001


def test_detect_sr_zones_clusters_nearby_swings():
    engine = TechnicalEngine()
    # Cluster A: 100.0, 100.3, 100.6 (within 0.6% of the running mean) -> one zone.
    # Cluster B: 80.0, 80.2 -> separate zone. Distant swings stay separate.
    swings = [
        SwingPoint(index=2, price=100.0, is_high=True, timestamp=1),
        SwingPoint(index=5, price=100.3, is_high=True, timestamp=2),
        SwingPoint(index=8, price=100.6, is_high=True, timestamp=3),
        SwingPoint(index=12, price=80.0, is_high=False, timestamp=4),
        SwingPoint(index=15, price=80.2, is_high=False, timestamp=5),
    ]
    zones = engine.detect_sr_zones([], swings)
    assert len(zones) == 2, f"expected 2 clustered zones, got {zones}"
    lows = [min(z) for z in zones]
    highs = [max(z) for z in zones]
    assert any(abs(lo - 80.0) < 0.01 for lo in lows)
    assert any(abs(hi - 100.6) < 0.01 for hi in highs)
