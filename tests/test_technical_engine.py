from technical_engine import PatternType, SwingPoint, TechnicalEngine, Trendline


def create_synthetic_klines(prices: list[tuple[float, float, float, float]], start_time: int = 1700000000000):
    """Build kline dictionaries from (open, high, low, close) tuples."""
    base_ts = start_time
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


def test_smc_order_blocks_and_regression_channel():
    engine = TechnicalEngine()
    # 20 bars:
    # Bars 0-5: consolidation around 100. Bar 3 is a swing high (high 102).
    # Bar 6: bearish down candle (open 99.5, close 98, low 97.5) -> candidate Order Block!
    # Bars 7-10: strong bullish displacement breaking structure above 102 (BOS). Bar 7 closes at 102.5.
    prices = [
        (98, 100, 97, 99),    # 0
        (99, 101, 98, 100),   # 1
        (100, 101, 99, 100),  # 2
        (100, 102, 99, 101),  # 3 - Swing High (102)
        (101, 101.5, 99.5, 100), # 4
        (100, 100.5, 98.5, 99),  # 5
        (99.5, 100, 97.5, 98),   # 6 - Bearish candle before expansion (OB!)
        (98.5, 103, 98, 102.5),  # 7 - Breakout bar closes above 102 (BOS!)
        (102.5, 105, 102, 104.5),# 8
        (104.5, 107, 104, 106.5),# 9
        (106, 108, 105, 107),    # 10
        (107, 109, 106, 108),    # 11
        (108, 110, 107, 109),    # 12
        (109, 111, 108, 110),    # 13
        (110, 112, 109, 111),    # 14
        (111, 113, 110, 112),    # 15
        (112, 114, 111, 113),    # 16
        (113, 115, 112, 114),    # 17
        (114, 116, 113, 115),    # 18
        (115, 117, 114, 116),    # 19
    ]
    klines = create_synthetic_klines(prices)
    swings = engine.find_swing_points(klines, window=2)

    # 1. Test Order Blocks
    order_blocks = engine.detect_order_blocks(klines, swings)
    assert len(order_blocks) > 0
    bullish_obs = [ob for ob in order_blocks if ob["type"] == "BULLISH_OB"]
    assert len(bullish_obs) > 0
    latest_ob = bullish_obs[-1]
    assert latest_ob["index"] == 6
    assert latest_ob["bottom"] == 97.5
    assert latest_ob["top"] == 99.5

    # 2. Test Linear Regression Channel
    channel = engine.calculate_regression_channel(klines, window=15)
    assert channel is not None
    assert channel["slope"] > 0, "Steadily rising price must produce positive slope"
    assert channel["upper"] > channel["middle"] > channel["lower"]
    assert channel["std_dev"] > 0

    # 3. Test Forecast Trajectory
    dummy_signal = type("DummySignal", (), {
        "signal_type": "LONG",
        "entry_price": 116.0,
        "stop_loss": 113.0,
        "take_profit": 122.0,
        "extra_targets": {"tp1": 120.5, "tp2": 122.0}
    })()
    forecast = engine.generate_forecast_path(dummy_signal, klines)
    assert len(forecast) >= 3
    # Step 0: current bar
    assert forecast[0]["value"] == 116.0
    # Last step: target
    assert forecast[-1]["value"] >= 120.0
    assert forecast[-1]["time"] > forecast[0]["time"]

    # Test SHORT forecast path with dict signal (ensuring dicts are parsed correctly)
    short_dict_signal = {
        "signal_type": "SHORT",
        "entry_price": 100.0,
        "stop_loss": 103.0,
        "tp1": 95.0,
        "tp2": 93.0
    }
    short_forecast = engine.generate_forecast_path(short_dict_signal, klines)
    assert len(short_forecast) >= 3
    assert short_forecast[-1]["value"] <= 95.0, f"Expected SHORT target <= 95.0, got {short_forecast[-1]['value']}"


def test_quant_indicators_and_regime_classification():
    engine = TechnicalEngine()
    # Create 35 synthetic bars with alternating fluctuations to simulate ranging
    ranging_prices = [(100 + (i % 2) * 2, 103, 99, 100 + ((i + 1) % 2) * 2) for i in range(40)]
    ranging_klines = create_synthetic_klines(ranging_prices)

    # 1. ATR test
    atr = engine.calc_atr(ranging_klines, period=14)
    assert len(atr) == len(ranging_klines)
    assert atr[-1] > 0

    # 2. RSI test
    rsi = engine.calc_rsi(ranging_klines, period=14)
    assert len(rsi) == len(ranging_klines)
    assert 0 <= rsi[-1] <= 100

    # 3. Bollinger Bands test
    upper, middle, lower = engine.calc_bollinger_bands(ranging_klines, period=20, num_std=2.0)
    assert len(upper) == len(ranging_klines)
    assert upper[-1] >= middle[-1] >= lower[-1]

    # 4. ADX test
    adx = engine.calc_adx(ranging_klines, period=14)
    assert len(adx) == len(ranging_klines)
    assert adx[-1] >= 0

    # 5. Market Regime test
    # In tight alternating range, regime should be RANGING
    regime = engine.detect_market_regime(ranging_klines)
    assert regime["regime"] == "RANGING"

    # Strongly trending prices
    trending_prices = [(100 + i * 2, 102 + i * 2, 99 + i * 2, 101.5 + i * 2) for i in range(50)]
    trending_klines = create_synthetic_klines(trending_prices)
    trend_regime = engine.detect_market_regime(trending_klines)
    assert trend_regime["regime"] in ("TRENDING_BULL", "TRENDING_BEAR")
    assert trend_regime["adx"] > 25


def test_regime_adaptive_signals_generation():
    engine = TechnicalEngine()
    # 1. Simulate Mean Reversion Oversold Trap in Ranging Market:
    prices = []
    for i in range(20):
        val = 100 + 3 * (1 if i % 2 == 0 else -1)
        prices.append((val - 1, val + 2, val - 2, val + 1))
    prices.append((102.0, 102.5, 98.0, 98.5))
    prices.append((98.5, 99.0, 95.0, 95.5))
    prices.append((95.5, 96.0, 91.0, 94.5))
    klines = create_synthetic_klines(prices)

    signals = engine.analyze_market(klines, symbol="BTCUSDT", timeframe="15m")
    mr_signals = [s for s in signals if s.pattern == PatternType.MEAN_REVERSION_TRAP]
    assert len(mr_signals) > 0
    sig = mr_signals[0]
    assert sig.signal_type == "LONG"
    assert sig.regime == "RANGING"
    assert sig.take_profit > sig.entry_price
    assert sig.stop_loss < sig.entry_price
    assert sig.tp1 > 0


def test_unmitigated_order_blocks_and_bos_choch_shifts():
    engine = TechnicalEngine()
    # Construct market structure:
    # Bar 0-4: Swing High at Bar 2 (high=105)
    # Bar 5-8: Down candle at Bar 6 (open=100, close=98, low=97), then Bar 8 breaks above 105 (BOS Bullish!)
    # Bar 9-12: Swing High at Bar 10 (high=115), Swing Low at Bar 12 (low=106)
    # Bar 13-16: Bar 14 breaks 115 (BOS Bullish!), Bar 16 breaks below 106 (CHoCH Bearish reversal!)
    prices = [
        (100, 102, 99, 101),   # 0
        (101, 103, 100, 102),  # 1
        (102, 105, 101, 104),  # 2 - Swing High (105)
        (103, 103.5, 99, 100), # 3
        (100, 101, 99, 100),   # 4
        (100, 101, 98, 99),    # 5
        (99, 100, 97, 98),     # 6 - OB candle (low=97, top=99)
        (98, 104, 98, 103),    # 7
        (103, 108, 102, 107),  # 8 - Breaks 105 (BOS Bullish!)
        (107, 112, 106, 111),  # 9
        (111, 115, 110, 114),  # 10 - Swing High (115)
        (114, 114, 107, 108),  # 11
        (108, 109, 106, 107),  # 12 - Swing Low (106)
        (107, 112, 106, 111),  # 13
        (111, 118, 110, 117),  # 14 - Breaks 115 (BOS Bullish!)
        (116, 116, 105, 106),  # 15
        (106, 106, 101, 102),  # 16 - Breaks below 106 (CHoCH Bearish!)
    ]
    klines = create_synthetic_klines(prices)
    swings = engine.find_swing_points(klines, window=2)

    # 1. Test BOS & CHoCH structure shifts
    shifts = engine.detect_market_structure_shifts(klines, swings)
    assert len(shifts) >= 2
    types = [s["type"] for s in shifts]
    assert "BOS" in types
    assert "CHOCH" in types

    # 2. Test Unmitigated Order Blocks
    # Bar 6 OB has top=99, bottom=97.
    # At Bar 16, price dropped to 101, so Bar 6 OB is still UNMITIGATED!
    unmitigated_obs = engine.detect_order_blocks(klines, swings, unmitigated_only=True)
    assert any(ob["index"] == 6 and not ob.get("mitigated", False) for ob in unmitigated_obs)

    # Now add Bar 17 where price drops to 95 (penetrates through 97)
    klines_breached = klines + create_synthetic_klines([(102, 102, 95, 96)], start_time=klines[-1]["timestamp"] + 900000)
    swings_breached = engine.find_swing_points(klines_breached, window=2)
    obs_after_breach = engine.detect_order_blocks(klines_breached, swings_breached, unmitigated_only=True)
    assert not any(ob["index"] == 6 for ob in obs_after_breach), "Breached Order Block must be filtered out when unmitigated_only=True"


def test_lina_rsi_wave_and_pullback_detection():
    engine = TechnicalEngine()
    # 60 synthetic bars
    prices = [(100 + i * 0.5, 101 + i * 0.5, 99.5 + i * 0.5, 100.8 + i * 0.5) for i in range(60)]
    klines = create_synthetic_klines(prices)

    # 1. Test WMA
    data = [float(x) for x in range(1, 11)]
    wma = engine.calc_wma(data, period=5)
    assert len(wma) == len(data)
    assert wma[-1] > data[len(data) - 5]

    # 2. Test calc_lina_rsi
    lina_res = engine.calc_lina_rsi(klines)
    assert "rsi" in lina_res
    assert "rsi_ema" in lina_res
    assert "rsi_wma" in lina_res
    assert len(lina_res["rsi"]) == len(klines)
    assert len(lina_res["rsi_ema"]) == len(klines)
    assert len(lina_res["rsi_wma"]) == len(klines)

    # 3. Test PatternType.LINA_RSI_PULLBACK presence
    assert hasattr(PatternType, "LINA_RSI_PULLBACK")
