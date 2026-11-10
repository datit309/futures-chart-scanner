import numpy as np
from enum import Enum
from dataclasses import dataclass, field
from typing import List, Dict, Any, Tuple, Optional

class PatternType(str, Enum):
    TRENDLINE_BREAKOUT = "TRENDLINE_BREAKOUT"
    SR_BOUNCE = "SR_BOUNCE"
    FVG_RETEST = "FVG_RETEST"
    MEAN_REVERSION_TRAP = "MEAN_REVERSION_TRAP"
    SMC_ORDER_BLOCK_RETEST = "SMC_ORDER_BLOCK_RETEST"
    LINA_RSI_PULLBACK = "LINA_RSI_PULLBACK"

@dataclass
class SwingPoint:
    index: int
    price: float
    is_high: bool
    timestamp: int

@dataclass
class Trendline:
    point1: Tuple[int, float]
    point2: Tuple[int, float]
    slope: float
    intercept: float
    touches: int
    is_resistance: bool
    current_value: float
    touch_indices: List[int] = field(default_factory=list)

    def value_at(self, index: int) -> float:
        return self.slope * index + self.intercept

@dataclass
class MarketSignal:
    symbol: str
    timeframe: str
    signal_type: str  # "LONG" | "SHORT"
    pattern: PatternType
    entry_price: float
    stop_loss: float
    take_profit: float
    risk_reward: float
    description: str
    trendlines: List[Trendline] = field(default_factory=list)
    sr_zones: List[Tuple[float, float]] = field(default_factory=list)
    fvgs: List[Dict[str, Any]] = field(default_factory=list)
    regime: str = "RANGING"
    tp1: float = 0.0
    tp2: float = 0.0

class TechnicalEngine:
    def __init__(self, swing_window: int = 2, min_touches: int = 3, tolerance_pct: float = 0.005):
        self.swing_window = swing_window
        self.min_touches = min_touches
        self.tolerance_pct = tolerance_pct

    def find_swing_points(self, klines: List[Dict[str, Any]], window: Optional[int] = None) -> List[SwingPoint]:
        """
        Identify local peaks (Swing High) and troughs (Swing Low) using N-bar fractals.
        """
        w = window or self.swing_window
        n = len(klines)
        swings = []
        if n < 2 * w + 1:
            return swings

        for i in range(w, n - w):
            current_high = klines[i]["high"]
            current_low = klines[i]["low"]
            ts = klines[i]["timestamp"]

            # Check Swing High
            is_peak = True
            for k in range(1, w + 1):
                if klines[i - k]["high"] > current_high or klines[i + k]["high"] > current_high:
                    is_peak = False
                    break
            if is_peak:
                swings.append(SwingPoint(index=i, price=current_high, is_high=True, timestamp=ts))

            # Check Swing Low
            is_trough = True
            for k in range(1, w + 1):
                if klines[i - k]["low"] < current_low or klines[i + k]["low"] < current_low:
                    is_trough = False
                    break
            if is_trough:
                swings.append(SwingPoint(index=i, price=current_low, is_high=False, timestamp=ts))

        return swings

    def detect_trendlines(
        self, 
        klines: List[Dict[str, Any]], 
        swings: List[SwingPoint], 
        min_touches: Optional[int] = None, 
        tolerance_pct: Optional[float] = None
    ) -> List[Trendline]:
        """
        Fit trendlines connecting swing points, rejecting lines pierced by candle bodies.
        """
        req_touches = min_touches or self.min_touches
        tol = tolerance_pct or self.tolerance_pct
        n_bars = len(klines)
        if n_bars < 5 or len(swings) < 2:
            return []

        trendlines: List[Trendline] = []
        high_swings = [s for s in swings if s.is_high]
        low_swings = [s for s in swings if not s.is_high]

        # 1. Resistance lines (connecting Swing Highs)
        for i in range(len(high_swings)):
            for j in range(i + 1, len(high_swings)):
                p1, p2 = high_swings[i], high_swings[j]
                dx = p2.index - p1.index
                if dx < 3:
                    continue
                slope = (p2.price - p1.price) / dx
                intercept = p1.price - slope * p1.index

                # Resistance lines should slope downwards or align with channel
                if slope > 0.05 * (p1.price / n_bars):
                    continue

                # Strict violation check from p1 up to bar before current:
                # Candle body (max(open, close)) must NOT pierce above the line!
                violated = False
                for bar_idx in range(p1.index, n_bars - 1):
                    line_val = slope * bar_idx + intercept
                    body_top = max(klines[bar_idx]["open"], klines[bar_idx]["close"])
                    high_val = klines[bar_idx]["high"]
                    if body_top > line_val * (1 + tol):
                        violated = True
                        break
                    if high_val > line_val * (1 + tol * 1.5):
                        violated = True
                        break
                if violated:
                    continue

                # Count touches: anchors p1 and p2, plus any distinct peak testing the line
                touch_indices = [p1.index, p2.index]
                for b in range(p1.index + 1, n_bars - 1):
                    if b in touch_indices:
                        continue
                    line_val = slope * b + intercept
                    high_val = klines[bar_idx := b]["high"]
                    if abs(high_val - line_val) / line_val <= tol:
                        is_peak = high_val >= klines[b - 1]["high"] and (b == n_bars - 2 or high_val >= klines[b + 1]["high"])
                        if is_peak and all(abs(b - tb) >= 3 for tb in touch_indices):
                            touch_indices.append(b)

                touch_indices = sorted(set(touch_indices))
                touches = len(touch_indices)

                if touches >= req_touches:
                    curr_val = slope * (n_bars - 1) + intercept
                    residuals = [abs(klines[b]["high"] - (slope * b + intercept)) / (slope * b + intercept) for b in touch_indices]
                    avg_residual = sum(residuals) / len(residuals) if residuals else 0.0
                    tl = Trendline(
                        point1=(p1.index, p1.price),
                        point2=(p2.index, p2.price),
                        slope=slope,
                        intercept=intercept,
                        touches=touches,
                        is_resistance=True,
                        current_value=curr_val,
                        touch_indices=touch_indices
                    )
                    tl.residual = avg_residual
                    trendlines.append(tl)

        # 2. Support lines (connecting Swing Lows)
        for i in range(len(low_swings)):
            for j in range(i + 1, len(low_swings)):
                p1, p2 = low_swings[i], low_swings[j]
                dx = p2.index - p1.index
                if dx < 3:
                    continue
                slope = (p2.price - p1.price) / dx
                intercept = p1.price - slope * p1.index

                # Support lines should slope upwards or align with channel
                if slope < -0.05 * (p1.price / n_bars):
                    continue

                # Strict violation check:
                # Candle body (min(open, close)) must NOT pierce below the line!
                violated = False
                for bar_idx in range(p1.index, n_bars - 1):
                    line_val = slope * bar_idx + intercept
                    body_bottom = min(klines[bar_idx]["open"], klines[bar_idx]["close"])
                    low_val = klines[bar_idx]["low"]
                    if body_bottom < line_val * (1 - tol):
                        violated = True
                        break
                    if low_val < line_val * (1 - tol * 1.5):
                        violated = True
                        break
                if violated:
                    continue

                # Count touches: anchors p1 and p2, plus any distinct trough testing the line
                touch_indices = [p1.index, p2.index]
                for b in range(p1.index + 1, n_bars - 1):
                    if b in touch_indices:
                        continue
                    line_val = slope * b + intercept
                    low_val = klines[bar_idx := b]["low"]
                    if abs(low_val - line_val) / line_val <= tol:
                        is_trough = low_val <= klines[b - 1]["low"] and (b == n_bars - 2 or low_val <= klines[b + 1]["low"])
                        if is_trough and all(abs(b - tb) >= 3 for tb in touch_indices):
                            touch_indices.append(b)

                touch_indices = sorted(set(touch_indices))
                touches = len(touch_indices)

                if touches >= req_touches:
                    curr_val = slope * (n_bars - 1) + intercept
                    residuals = [abs(klines[b]["low"] - (slope * b + intercept)) / (slope * b + intercept) for b in touch_indices]
                    avg_residual = sum(residuals) / len(residuals) if residuals else 0.0
                    tl = Trendline(
                        point1=(p1.index, p1.price),
                        point2=(p2.index, p2.price),
                        slope=slope,
                        intercept=intercept,
                        touches=touches,
                        is_resistance=False,
                        current_value=curr_val,
                        touch_indices=touch_indices
                    )
                    tl.residual = avg_residual
                    trendlines.append(tl)

        # Sort by most touches and freshness
        trendlines.sort(key=lambda x: (x.touches, x.point2[0]), reverse=True)
        return trendlines


    def select_strongest_trendlines(self, trendlines: List[Trendline], n_bars: Optional[int] = None) -> List[Trendline]:
        """Choose at most one active support and resistance line deterministically.

        Ranking prioritizes:
        1. Active relevance (anchor 2 in recent price action vs ancient history).
        2. Touch validation (lines with confirmed touches).
        3. Touch count (descending).
        4. Span (longer baseline is more reliable).
        5. Minimal residual error.
        """
        selected = []
        recency_threshold = (n_bars - 40) if n_bars and n_bars > 50 else -1

        for is_resistance in (True, False):
            candidates = [line for line in trendlines if line.is_resistance is is_resistance]
            candidates.sort(key=lambda line: (
                -1 if (recency_threshold > 0 and line.point2[0] >= recency_threshold) else 0,
                -line.touches,
                -line.point2[0],
                -(line.point2[0] - line.point1[0]),
                float(getattr(line, "residual", float("inf"))),
                line.point1[0],
                line.point2[0],
                line.point1[1],
                line.point2[1],
            ))
            if candidates:
                selected.append(candidates[0])
        return selected

    def detect_sr_zones(self, klines: List[Dict[str, Any]], swings: List[SwingPoint]) -> List[Tuple[float, float]]:
        """
        Cluster swing prices to identify significant horizontal Support/Resistance bands.
        """
        if not swings:
            return []
        prices = [s.price for s in swings]
        prices.sort()

        zones = []
        cluster = [prices[0]]
        for p in prices[1:]:
            # If within 0.6% of cluster average, group together
            if (p - np.mean(cluster)) / np.mean(cluster) <= 0.006:
                cluster.append(p)
            else:
                if len(cluster) >= 2:
                    zones.append((min(cluster), max(cluster)))
                cluster = [p]
        if len(cluster) >= 2:
            zones.append((min(cluster), max(cluster)))

        return zones

    def detect_fvg(self, klines: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Detect Fair Value Gaps (FVG):
        - Bullish: Low(i) > High(i-2)
        - Bearish: High(i) < Low(i-2)
        """
        fvgs = []
        for i in range(2, len(klines)):
            c0 = klines[i - 2]
            c2 = klines[i]

            # Bullish FVG
            if c2["low"] > c0["high"]:
                fvgs.append({
                    "index": i - 1,
                    "type": "BULLISH",
                    "bottom": c0["high"],
                    "top": c2["low"],
                    "timestamp": klines[i - 1]["timestamp"]
                })
            # Bearish FVG
            elif c2["high"] < c0["low"]:
                fvgs.append({
                    "index": i - 1,
                    "type": "BEARISH",
                    "bottom": c2["high"],
                    "top": c0["low"],
                    "timestamp": klines[i - 1]["timestamp"]
                })
        return fvgs

    def analyze_market(self, klines: List[Dict[str, Any]], symbol: str = "BTCUSDT", timeframe: str = "15m") -> List[MarketSignal]:
        """
        Analyze candlestick chart data using Regime-Adaptive Quantitative Rules:
        - In RANGING regime (ADX < 26): Generate MEAN_REVERSION_TRAP signals (fade BB piercings with RSI exhaustion).
        - In TRENDING regime (ADX >= 26): Generate SMC_ORDER_BLOCK_RETEST signals (pullbacks into Demand/Supply).
        - Fallback: Trendline Breakouts.
        """
        if len(klines) < 10:
            return []

        swings = self.find_swing_points(klines)
        trendlines = self.detect_trendlines(klines, swings)
        sr_zones = self.detect_sr_zones(klines, swings)
        fvgs = self.detect_fvg(klines)
        order_blocks = self.detect_order_blocks(klines, swings)

        regime_info = self.detect_market_regime(klines)
        regime = regime_info["regime"]
        signals: List[MarketSignal] = []

        latest_bar = klines[-1]
        prev_bar = klines[-2]
        curr_price = float(latest_bar["close"])

        # Compute ATR, RSI, Bollinger Bands
        atr_series = self.calc_atr(klines, 14)
        curr_atr = atr_series[-1] if atr_series else (curr_price * 0.01)
        rsi_series = self.calc_rsi(klines, 14)
        curr_rsi = rsi_series[-1] if rsi_series else 50.0
        upper_bb, mid_bb, lower_bb = self.calc_bollinger_bands(klines, 20, 2.0)
        curr_upper = upper_bb[-1]
        curr_mid = mid_bb[-1]
        curr_lower = lower_bb[-1]

        body = abs(float(latest_bar["close"]) - float(latest_bar["open"]))
        lower_wick = min(float(latest_bar["open"]), float(latest_bar["close"])) - float(latest_bar["low"])
        upper_wick = float(latest_bar["high"]) - max(float(latest_bar["open"]), float(latest_bar["close"]))

        # 1. RANGE-BOUND REGIME: Mean Reversion Trap (Fading Extremes)
        if regime == "RANGING":
            # Bullish Mean Reversion Trap
            if (float(latest_bar["low"]) <= curr_lower or float(prev_bar["low"]) <= curr_lower) and curr_rsi <= 45 and curr_price > float(latest_bar["low"]):
                sl = float(latest_bar["low"]) - curr_atr * 0.2
                risk = curr_price - sl
                if risk > 0 and curr_mid > curr_price:
                    tp1 = curr_mid
                    tp2 = curr_upper
                    rr = (tp2 - curr_price) / risk
                    if rr >= 1.2:
                        signals.append(MarketSignal(
                            symbol=symbol,
                            timeframe=timeframe,
                            signal_type="LONG",
                            pattern=PatternType.MEAN_REVERSION_TRAP,
                            entry_price=curr_price,
                            stop_loss=sl,
                            take_profit=tp1 if ((tp1 - curr_price) / risk >= 1.0) else tp2,
                            risk_reward=round(rr, 2),
                            description=f"Bullish Mean Reversion (Oversold BB Trap + RSI {curr_rsi:.1f})",
                            trendlines=trendlines[:1],
                            sr_zones=sr_zones,
                            fvgs=fvgs[-3:] if fvgs else [],
                            regime="RANGING",
                            tp1=round(tp1, 4),
                            tp2=round(tp2, 4)
                        ))

            # Bearish Mean Reversion Trap
            elif (float(latest_bar["high"]) >= curr_upper or float(prev_bar["high"]) >= curr_upper) and curr_rsi >= 55 and curr_price < float(latest_bar["high"]):
                sl = float(latest_bar["high"]) + curr_atr * 0.2
                risk = sl - curr_price
                if risk > 0 and curr_mid < curr_price:
                    tp1 = curr_mid
                    tp2 = curr_lower
                    rr = (curr_price - tp2) / risk
                    if rr >= 1.2:
                        signals.append(MarketSignal(
                            symbol=symbol,
                            timeframe=timeframe,
                            signal_type="SHORT",
                            pattern=PatternType.MEAN_REVERSION_TRAP,
                            entry_price=curr_price,
                            stop_loss=sl,
                            take_profit=tp1 if ((curr_price - tp1) / risk >= 1.0) else tp2,
                            risk_reward=round(rr, 2),
                            description=f"Bearish Mean Reversion (Overbought BB Trap + RSI {curr_rsi:.1f})",
                            trendlines=trendlines[:1],
                            sr_zones=sr_zones,
                            fvgs=fvgs[-3:] if fvgs else [],
                            regime="RANGING",
                            tp1=round(tp1, 4),
                            tp2=round(tp2, 4)
                        ))

        # 2. TRENDING REGIME: SMC Order Block Retest
        elif regime in ("TRENDING_BULL", "TRENDING_BEAR"):
            is_bull = regime == "TRENDING_BULL"
            if is_bull:
                recent_obs = [ob for ob in order_blocks if ob["type"] == "BULLISH_OB"]
                if recent_obs:
                    ob = recent_obs[-1]
                    if float(latest_bar["low"]) <= ob["top"] * 1.002 and curr_price >= ob["bottom"] * 0.998:
                        sl = ob["bottom"] - curr_atr * 0.3
                        risk = curr_price - sl
                        if risk > 0:
                            tp1 = curr_price + risk * 1.5
                            tp2 = curr_price + risk * 2.5
                            signals.append(MarketSignal(
                                symbol=symbol,
                                timeframe=timeframe,
                                signal_type="LONG",
                                pattern=PatternType.SMC_ORDER_BLOCK_RETEST,
                                entry_price=curr_price,
                                stop_loss=sl,
                                take_profit=tp2,
                                risk_reward=2.5,
                                description=f"Bullish SMC Retest on Demand Block ({ob['label']})",
                                trendlines=trendlines[:1],
                                sr_zones=sr_zones,
                                fvgs=fvgs[-3:] if fvgs else [],
                                regime=regime,
                                tp1=round(tp1, 4),
                                tp2=round(tp2, 4)
                            ))
            else:
                recent_obs = [ob for ob in order_blocks if ob["type"] == "BEARISH_OB"]
                if recent_obs:
                    ob = recent_obs[-1]
                    if float(latest_bar["high"]) >= ob["bottom"] * 0.998 and curr_price <= ob["top"] * 1.002:
                        sl = ob["top"] + curr_atr * 0.3
                        risk = sl - curr_price
                        if risk > 0:
                            tp1 = curr_price - risk * 1.5
                            tp2 = curr_price - risk * 2.5
                            signals.append(MarketSignal(
                                symbol=symbol,
                                timeframe=timeframe,
                                signal_type="SHORT",
                                pattern=PatternType.SMC_ORDER_BLOCK_RETEST,
                                entry_price=curr_price,
                                stop_loss=sl,
                                take_profit=tp2,
                                risk_reward=2.5,
                                description=f"Bearish SMC Retest on Supply Block ({ob['label']})",
                                trendlines=trendlines[:1],
                                sr_zones=sr_zones,
                                fvgs=fvgs[-3:] if fvgs else [],
                                regime=regime,
                                tp1=round(tp1, 4),
                                tp2=round(tp2, 4)
                            ))

        # 3. If no regime signal, check for Trendline Breakout
        if not signals:
            for tl in trendlines:
                line_val_latest = tl.value_at(len(klines) - 1)
                line_val_prev = tl.value_at(len(klines) - 2)

                # Bullish Breakout: Resistance line broken to the upside
                if tl.is_resistance:
                    if prev_bar["close"] <= line_val_prev * 1.002 and latest_bar["close"] > line_val_latest:
                        recent_lows = [s.price for s in swings if not s.is_high and s.index > tl.point1[0]]
                        sl = min(recent_lows) if recent_lows else latest_bar["low"] * 0.992
                        sl = min(sl, latest_bar["low"] * 0.996)

                        risk = curr_price - sl
                        if risk > 0:
                            tp = curr_price + risk * 2.2
                            rr = (tp - curr_price) / risk
                            signals.append(MarketSignal(
                                symbol=symbol,
                                timeframe=timeframe,
                                signal_type="LONG",
                                pattern=PatternType.TRENDLINE_BREAKOUT,
                                entry_price=curr_price,
                                stop_loss=sl,
                                take_profit=tp,
                                risk_reward=rr,
                                description=f"Bullish Breakout over Resistance Trendline ({tl.touches} touches)",
                                trendlines=[tl],
                                sr_zones=sr_zones,
                                fvgs=fvgs[-3:] if fvgs else [],
                                regime=regime,
                                tp1=round(curr_price + risk * 1.2, 4),
                                tp2=round(tp, 4)
                            ))

                # Bearish Breakout: Support line broken to the downside
                elif not tl.is_resistance:
                    if prev_bar["close"] >= line_val_prev * 0.998 and latest_bar["close"] < line_val_latest:
                        recent_highs = [s.price for s in swings if s.is_high and s.index > tl.point1[0]]
                        sl = max(recent_highs) if recent_highs else latest_bar["high"] * 1.008
                        sl = max(sl, latest_bar["high"] * 1.004)

                        risk = sl - curr_price
                        if risk > 0:
                            tp = curr_price - risk * 2.2
                            rr = (curr_price - tp) / risk
                            signals.append(MarketSignal(
                                symbol=symbol,
                                timeframe=timeframe,
                                signal_type="SHORT",
                                pattern=PatternType.TRENDLINE_BREAKOUT,
                                entry_price=curr_price,
                                stop_loss=sl,
                                take_profit=tp,
                                risk_reward=rr,
                                description=f"Bearish Breakdown under Support Trendline ({tl.touches} touches)",
                                trendlines=[tl],
                                sr_zones=sr_zones,
                                fvgs=fvgs[-3:] if fvgs else [],
                                regime=regime,
                                tp1=round(curr_price - risk * 1.2, 4),
                                tp2=round(tp, 4)
                            ))

        return signals

    def detect_market_structure_shifts(self, klines: List[Dict[str, Any]], swings: List[SwingPoint]) -> List[Dict[str, Any]]:
        """
        Detect Institutional Break of Structure (BOS) and Change of Character (CHoCH).
        - BOS: Trend continuation (breaking swing high in uptrend or swing low in downtrend).
        - CHoCH: Trend reversal (first break of swing low in uptrend or swing high in downtrend).
        """
        n = len(klines)
        if n < 6 or not swings:
            return []

        break_events = []
        for s in swings:
            for i in range(s.index + 1, n):
                c = float(klines[i]["close"])
                prev_c = float(klines[i - 1]["close"])
                if s.is_high and prev_c <= s.price and c > s.price:
                    break_events.append({"break_idx": i, "swing": s, "direction": "UP"})
                    break
                elif not s.is_high and prev_c >= s.price and c < s.price:
                    break_events.append({"break_idx": i, "swing": s, "direction": "DOWN"})
                    break

        # Sort strictly chronologically by break candle, closest swing first
        break_events.sort(key=lambda x: (x["break_idx"], -x["swing"].index))

        # Keep primary broken swing per break bar to avoid overlapping lines
        deduped_events = []
        seen_break_bars = set()
        for ev in break_events:
            if ev["break_idx"] not in seen_break_bars:
                seen_break_bars.add(ev["break_idx"])
                deduped_events.append(ev)

        current_trend = None
        shifts = []
        for ev in deduped_events:
            i = ev["break_idx"]
            s = ev["swing"]
            is_bull = ev["direction"] == "UP"

            if is_bull:
                if current_trend == "BULL":
                    shift_type = "BOS"
                else:
                    shift_type = "CHOCH"
                    current_trend = "BULL"
            else:
                if current_trend == "BEAR":
                    shift_type = "BOS"
                else:
                    shift_type = "CHOCH"
                    current_trend = "BEAR"

            t_start = int(klines[s.index]["timestamp"] / 1000)
            t_end = int(klines[i]["timestamp"] / 1000)
            label = f"{shift_type} {'Bullish' if is_bull else 'Bearish'}"
            shifts.append({
                "type": shift_type,
                "price": round(s.price, 4),
                "time_start": t_start,
                "time_end": t_end,
                "label": label,
                "is_bullish": is_bull,
                "swing_index": s.index,
                "break_index": i
            })

        # Return the most recent 6 confirmed structure breaks across the chart
        return shifts[-6:]

    def detect_order_blocks(self, klines: List[Dict[str, Any]], swings: List[SwingPoint], unmitigated_only: bool = True) -> List[Dict[str, Any]]:
        """
        Detect Institutional Order Blocks (SMC):
        - Bullish OB: The last down candle (close < open) prior to an aggressive upward break of structure.
        - Bearish OB: The last up candle (close > open) prior to an aggressive downward break of structure.
        - Unmitigated filter: Removes blocks that have already been completely penetrated or tested.
        """
        n = len(klines)
        if n < 8 or not swings:
            return []

        swing_highs = [s for s in swings if s.is_high]
        swing_lows = [s for s in swings if not s.is_high]
        order_blocks = []

        # Bullish OBs
        for idx in range(3, n):
            c = klines[idx]["close"]
            prev_c = klines[idx - 1]["close"]
            recent_highs = [sh for sh in swing_highs if sh.index < idx and sh.index >= idx - 25]
            if recent_highs:
                last_sh = recent_highs[-1]
                if prev_c <= last_sh.price and c > last_sh.price:
                    candidates = [
                        (k_i, klines[k_i]) for k_i in range(last_sh.index, idx)
                        if klines[k_i]["close"] < klines[k_i]["open"]
                    ]
                    if candidates:
                        ob_idx, ob_candle = min(candidates, key=lambda x: x[1]["low"])
                        ob_top = max(ob_candle["open"], ob_candle["close"])
                        ob_bottom = ob_candle["low"]

                        # Check mitigation by subsequent candles
                        mitigated = False
                        breached = False
                        for later_i in range(idx + 1, n):
                            later_low = float(klines[later_i]["low"])
                            if later_low < ob_bottom:
                                breached = True
                                break
                            elif later_low <= ob_top:
                                mitigated = True

                        if not (unmitigated_only and breached):
                            order_blocks.append({
                                "type": "BULLISH_OB",
                                "index": ob_idx,
                                "top": round(ob_top, 4),
                                "bottom": round(ob_bottom, 4),
                                "timestamp": ob_candle["timestamp"],
                                "label": "OB Demand",
                                "mitigated": mitigated or breached,
                                "breached": breached
                            })

        # Bearish OBs
        for idx in range(3, n):
            c = klines[idx]["close"]
            prev_c = klines[idx - 1]["close"]
            recent_lows = [sl for sl in swing_lows if sl.index < idx and sl.index >= idx - 25]
            if recent_lows:
                last_sl = recent_lows[-1]
                if prev_c >= last_sl.price and c < last_sl.price:
                    candidates = [
                        (k_i, klines[k_i]) for k_i in range(last_sl.index, idx)
                        if klines[k_i]["close"] > klines[k_i]["open"]
                    ]
                    if candidates:
                        ob_idx, ob_candle = max(candidates, key=lambda x: x[1]["high"])
                        ob_top = ob_candle["high"]
                        ob_bottom = min(ob_candle["open"], ob_candle["close"])

                        mitigated = False
                        breached = False
                        for later_i in range(idx + 1, n):
                            later_high = float(klines[later_i]["high"])
                            if later_high > ob_top:
                                breached = True
                                break
                            elif later_high >= ob_bottom:
                                mitigated = True

                        if not (unmitigated_only and breached):
                            order_blocks.append({
                                "type": "BEARISH_OB",
                                "index": ob_idx,
                                "top": round(ob_top, 4),
                                "bottom": round(ob_bottom, 4),
                                "timestamp": ob_candle["timestamp"],
                                "label": "OB Supply",
                                "mitigated": mitigated or breached,
                                "breached": breached
                            })

        seen = set()
        unique_obs = []
        for ob in reversed(order_blocks):
            key = (ob["type"], ob["index"])
            if key not in seen:
                seen.add(key)
                if not unmitigated_only or not ob["breached"]:
                    unique_obs.append(ob)
        unique_obs.reverse()
        return unique_obs[-4:]

    def calculate_regression_channel(self, klines: List[Dict[str, Any]], window: int = 60) -> Optional[Dict[str, Any]]:
        """
        Calculate Statistical Linear Regression Channel (with +-2 standard deviation bands).
        """
        n = len(klines)
        if n < 10:
            return None
        w = min(window, n)
        subset = klines[-w:]
        x = np.arange(w)
        closes = np.array([float(k["close"]) for k in subset])
        slope, intercept = np.polyfit(x, closes, 1)
        fitted = slope * x + intercept
        residuals = closes - fitted
        std_dev = float(np.std(residuals))

        upper_series = []
        middle_series = []
        lower_series = []

        for i, k in enumerate(subset):
            t_sec = int(k["timestamp"] / 1000)
            mid_val = float(fitted[i])
            upper_series.append({"time": t_sec, "value": round(mid_val + 2 * std_dev, 4)})
            middle_series.append({"time": t_sec, "value": round(mid_val, 4)})
            lower_series.append({"time": t_sec, "value": round(mid_val - 2 * std_dev, 4)})

        curr_mid = float(fitted[-1])
        return {
            "slope": float(slope),
            "intercept": float(intercept),
            "std_dev": std_dev,
            "upper": round(curr_mid + 2 * std_dev, 4),
            "middle": round(curr_mid, 4),
            "lower": round(curr_mid - 2 * std_dev, 4),
            "upper_series": upper_series,
            "middle_series": middle_series,
            "lower_series": lower_series,
        }

    def generate_forecast_path(self, signal: Any, klines: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Generate projected price trajectory path into future bars.
        Points: [Current Close -> Retest (+1 bar) -> Target (+3 bars)]
        """
        if not klines or not signal:
            return []
        last_k = klines[-1]
        t_sec = int(last_k["timestamp"] / 1000)
        time_step = (klines[-1]["timestamp"] - klines[-2]["timestamp"]) // 1000 if len(klines) > 1 else 900

        def get_val(key, default=None):
            if isinstance(signal, dict):
                return signal.get(key, default)
            return getattr(signal, key, default)

        sig_type = str(get_val("signal_type", "LONG")).upper()
        is_long = sig_type == "LONG"
        entry = float(get_val("entry_price") or last_k["close"])
        sl = float(get_val("stop_loss") or (entry * (0.99 if is_long else 1.01)))

        extra = get_val("extra_targets") or {}
        tp1_val = extra.get("tp1") if isinstance(extra, dict) else getattr(extra, "tp1", None)
        tp1 = float(tp1_val or get_val("tp1") or get_val("take_profit") or (entry * (1.02 if is_long else 0.98)))

        retest = entry - (entry - sl) * 0.15 if is_long else entry + (sl - entry) * 0.15
        return [
            {"time": t_sec, "value": round(last_k["close"], 4), "stage": "NOW"},
            {"time": t_sec + time_step, "value": round(retest, 4), "stage": "RETEST"},
            {"time": t_sec + time_step * 3, "value": round(tp1, 4), "stage": "TARGET"},
        ]

    def calc_atr(self, klines: List[Dict[str, Any]], period: int = 14) -> List[float]:
        n = len(klines)
        if n == 0:
            return []
        trs = [float(klines[0]["high"] - klines[0]["low"])]
        for i in range(1, n):
            h = float(klines[i]["high"])
            l = float(klines[i]["low"])
            pc = float(klines[i - 1]["close"])
            tr = max(h - l, abs(h - pc), abs(l - pc))
            trs.append(tr)

        if n <= period:
            mean_tr = float(np.mean(trs)) if trs else 0.0
            return [mean_tr] * n

        first_atr = float(np.mean(trs[:period]))
        atr = [first_atr] * period
        curr_atr = first_atr
        for i in range(period, n):
            curr_atr = (curr_atr * (period - 1) + trs[i]) / period
            atr.append(curr_atr)
        return atr

    def calc_rsi(self, klines: List[Dict[str, Any]], period: int = 14) -> List[float]:
        n = len(klines)
        if n == 0:
            return []
        closes = [float(k["close"]) for k in klines]
        if n <= period:
            return [50.0] * n
        deltas = np.diff(closes)
        gains = np.where(deltas > 0, deltas, 0.0)
        losses = np.where(deltas < 0, -deltas, 0.0)

        avg_gain = float(np.mean(gains[:period]))
        avg_loss = float(np.mean(losses[:period]))

        rsi_list = [50.0] * period
        if avg_loss == 0:
            rsi_list.append(100.0)
        else:
            rs = avg_gain / avg_loss
            rsi_list.append(100.0 - (100.0 / (1.0 + rs)))

        for i in range(period, len(deltas)):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period
            if avg_loss == 0:
                rsi_list.append(100.0)
            else:
                rs = avg_gain / avg_loss
                rsi_list.append(100.0 - (100.0 / (1.0 + rs)))
        return rsi_list

    def calc_bollinger_bands(self, klines: List[Dict[str, Any]], period: int = 20, num_std: float = 2.0) -> Tuple[List[float], List[float], List[float]]:
        n = len(klines)
        if n == 0:
            return [], [], []
        closes = [float(k["close"]) for k in klines]
        upper, middle, lower = [], [], []
        for i in range(n):
            if i < period:
                sub = closes[:i + 1]
            else:
                sub = closes[i - period + 1:i + 1]
            m = float(np.mean(sub))
            s = float(np.std(sub))
            middle.append(round(m, 4))
            upper.append(round(m + num_std * s, 4))
            lower.append(round(m - num_std * s, 4))
        return upper, middle, lower

    def calc_adx(self, klines: List[Dict[str, Any]], period: int = 14) -> List[float]:
        n = len(klines)
        if n <= period:
            return [0.0] * n
        tr = []
        dm_plus = []
        dm_minus = []
        for i in range(1, n):
            h, l = float(klines[i]["high"]), float(klines[i]["low"])
            ph, pl, pc = float(klines[i - 1]["high"]), float(klines[i - 1]["low"]), float(klines[i - 1]["close"])
            tr.append(max(h - l, abs(h - pc), abs(l - pc)))
            up = h - ph
            down = pl - l
            dm_plus.append(up if (up > down and up > 0) else 0.0)
            dm_minus.append(down if (down > up and down > 0) else 0.0)

        tr_s = [sum(tr[:period])]
        p_s = [sum(dm_plus[:period])]
        m_s = [sum(dm_minus[:period])]
        for i in range(period, len(tr)):
            tr_s.append(tr_s[-1] - (tr_s[-1] / period) + tr[i])
            p_s.append(p_s[-1] - (p_s[-1] / period) + dm_plus[i])
            m_s.append(m_s[-1] - (m_s[-1] / period) + dm_minus[i])

        pdi = [100.0 * p / (t if t > 0 else 1.0) for p, t in zip(p_s, tr_s)]
        mdi = [100.0 * m / (t if t > 0 else 1.0) for m, t in zip(m_s, tr_s)]
        dx = [100.0 * abs(p - m) / (p + m if (p + m) > 0 else 1.0) for p, m in zip(pdi, mdi)]

        adx = [0.0] * period
        curr = float(np.mean(dx[:period])) if len(dx) >= period else 0.0
        adx.append(curr)
        for d in dx[period:]:
            curr = (curr * (period - 1) + d) / period
            adx.append(curr)
        while len(adx) < n:
            adx.insert(0, 0.0)
        return adx[-n:]

    def calc_ema(self, arr: List[float], period: int) -> List[float]:
        n = len(arr)
        if n == 0:
            return []
        alpha = 2.0 / (period + 1.0)
        res = [arr[0]]
        for x in arr[1:]:
            res.append(alpha * x + (1.0 - alpha) * res[-1])
        return res

    def calc_wma(self, data: List[float], period: int = 45) -> List[float]:
        n = len(data)
        if n == 0:
            return []
        p = min(period, n)
        weights = np.arange(1, p + 1, dtype=float)
        weight_sum = float(weights.sum())
        res: List[float] = []
        for i in range(n):
            if i < p - 1:
                w = np.arange(1, i + 2, dtype=float)
                sub = np.array(data[: i + 1], dtype=float)
                res.append(float(np.dot(sub, w) / w.sum()))
            else:
                sub = np.array(data[i - p + 1 : i + 1], dtype=float)
                res.append(float(np.dot(sub, weights) / weight_sum))
        return res

    def calc_lina_rsi(self, klines: List[Dict[str, Any]], rsi_period: int = 14, ema_period: int = 9, wma_period: int = 45) -> Dict[str, List[float]]:
        rsi = self.calc_rsi(klines, period=rsi_period)
        rsi_ema = self.calc_ema(rsi, period=ema_period)
        rsi_wma = self.calc_wma(rsi, period=wma_period)
        return {
            "rsi": rsi,
            "rsi_ema": rsi_ema,
            "rsi_wma": rsi_wma,
        }

    def detect_market_regime(self, klines: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not klines:
            return {"regime": "RANGING", "adx": 0.0, "ema50": 0.0, "ema200": 0.0}
        adx_series = self.calc_adx(klines, 14)
        curr_adx = adx_series[-1] if adx_series else 0.0
        closes = [float(k["close"]) for k in klines]

        ema50_series = self.calc_ema(closes, min(50, len(closes)))
        ema200_series = self.calc_ema(closes, min(200, len(closes)))
        ema50 = ema50_series[-1] if ema50_series else 0.0
        ema200 = ema200_series[-1] if ema200_series else 0.0
        curr_close = closes[-1]

        if curr_adx >= 26.0:
            regime = "TRENDING_BULL" if curr_close > ema200 else "TRENDING_BEAR"
        else:
            regime = "RANGING"

        return {
            "regime": regime,
            "adx": round(curr_adx, 2),
            "ema50": round(ema50, 4),
            "ema200": round(ema200, 4),
            "close": curr_close
        }
