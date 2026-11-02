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


def test_trendline_rejects_body_piercing_and_counts_only_swing_touches():
    engine = TechnicalEngine()
    # Verified geometry:
    # Bar 2: high 100 (swing high: bars 0,1 <= 94; bars 3,4 <= 97.5; bar 2 is higher than 0,1,3,4)
    # Bar 8: high 94 (swing high: bars 6,7 <= 93.5; bars 9,10 <= 92; bar 8 is higher than 6,7,9,10)
    # Bar 4 high is 97.5 (not peak because bar 2 is 100 > 97.5)
    # Bar 5 high is 96.95 (not peak because bar 4 is 97.5 > 96.95)
    # Line: line = 100 - 1.0 * (idx - 2) = 102 - idx.
    # At bar 5, line = 97.0. Bar 5 high 96.95 is within 0.001 of line 97.0.
    prices = [
        (90, 92, 89, 91),     # 0
        (91, 94, 90, 93),     # 1
        (95, 100, 94, 98),    # 2 - SWING HIGH 1 (price 100, line 100)
        (91, 93, 90, 92),     # 3 (line 99)
        (93, 97.5, 92, 94),   # 4 - high 97.5 < line 98
        (93, 96.95, 92, 94),  # 5 - NOT SWING HIGH, but high 96.95 tests line 97.0
        (91, 93.5, 90, 92),   # 6 (line 96)
        (90, 92, 89, 91),     # 7 (line 95)
        (91, 94, 90, 93),     # 8 - SWING HIGH 2 (price 94, line 94)
        (90, 92, 89, 91),     # 9
        (89, 91, 88, 90),     # 10
    ]
    klines = create_synthetic_klines(prices)
    swings = engine.find_swing_points(klines, window=2)
    high_swings = [s for s in swings if s.is_high]
    assert [s.index for s in high_swings] == [2, 8], f"Expected only swings 2 and 8, got {[s.index for s in high_swings]}"

    lines = engine.detect_trendlines(klines, swings, min_touches=2, tolerance_pct=0.005)
    res_lines = [l for l in lines if l.is_resistance and l.point1[0] == 2 and l.point2[0] == 8]
    assert len(res_lines) == 1
    res_line = res_lines[0]
    # Under old logic: touches was 3 because bar 5 was falsely counted.
    # Under new swing-touch logic: touches MUST be 2.
    assert res_line.touches == 2, f"Expected 2 touches, got {res_line.touches}"
    assert res_line.touch_indices == [2, 8]

    # Test open-price body piercing:
    # At bar 4, candle opened at 99.0 (> line 98.0) and closed at 94.0 (< line 98.0).
    # The candle body pierced through the resistance line from above.
    pierced_open_prices = list(prices)
    pierced_open_prices[4] = (99.0, 99.2, 93.0, 94.0)  # Open 99.0 pierces above line 98.0
    klines_open_pierced = create_synthetic_klines(pierced_open_prices)
    swings_open_pierced = engine.find_swing_points(klines_open_pierced, window=2)
    lines_open_pierced = engine.detect_trendlines(klines_open_pierced, swings_open_pierced, min_touches=2)
    res_open_pierced = [l for l in lines_open_pierced if l.is_resistance and l.point1[0] == 2 and l.point2[0] == 8]
    assert len(res_open_pierced) == 0, "Line must be rejected when candle open pierces above resistance!"

    klines = create_synthetic_klines(prices)
    swings = engine.find_swing_points(klines, window=2)
    # Confirm bar 5 is NOT in swings
    assert not any(s.index == 5 for s in swings)
    lines = engine.detect_trendlines(klines, swings, min_touches=2)
    res_line = [l for l in lines if l.is_resistance and l.point1[0] == 2 and l.point2[0] == 8][0]
    # Touches must ONLY count actual swing points!
    assert res_line.touches == 2, f"Expected 2 swing touches (bars 2 and 8), but got {res_line.touches} (falsely counted non-swing bar 5)"
    assert res_line.touch_indices == [2, 8]

    # Test open-price body piercing:
    # At bar 5, candle opened at 99.0 (> line 97.0) and closed at 95.0 (< line 97.0).
    # The candle body pierced through the resistance line from above.
    # The old code only checked close > line, so it failed to detect this violation!
    pierced_open_prices = list(prices)
    pierced_open_prices[5] = (99.0, 99.2, 94.0, 95.0)  # Open 99.0 pierces above line 97.0
    klines_open_pierced = create_synthetic_klines(pierced_open_prices)
    swings_open_pierced = engine.find_swing_points(klines_open_pierced, window=2)
    lines_open_pierced = engine.detect_trendlines(klines_open_pierced, swings_open_pierced, min_touches=2)
    res_open_pierced = [l for l in lines_open_pierced if l.is_resistance and l.point1[0] == 2 and l.point2[0] == 8]
    assert len(res_open_pierced) == 0, "Line must be rejected when candle open pierces above resistance!"
