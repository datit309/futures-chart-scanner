import numpy as np
from enum import Enum
from dataclasses import dataclass, field
from typing import List, Dict, Any, Tuple, Optional

class PatternType(str, Enum):
    TRENDLINE_BREAKOUT = "TRENDLINE_BREAKOUT"
    SR_BOUNCE = "SR_BOUNCE"
    FVG_RETEST = "FVG_RETEST"

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
        Analyze candlestick chart data and identify actionable Breakout / Reversal setups.
        """
        if len(klines) < 10:
            return []

        swings = self.find_swing_points(klines)
        trendlines = self.detect_trendlines(klines, swings)
        sr_zones = self.detect_sr_zones(klines, swings)
        fvgs = self.detect_fvg(klines)

        signals: List[MarketSignal] = []
        latest_bar = klines[-1]
        prev_bar = klines[-2]
        curr_price = latest_bar["close"]

        # Check Trendline Breakouts
        for tl in trendlines:
            line_val_latest = tl.value_at(len(klines) - 1)
            line_val_prev = tl.value_at(len(klines) - 2)

            # Bullish Breakout: Resistance line broken to the upside
            if tl.is_resistance:
                if prev_bar["close"] <= line_val_prev * 1.002 and latest_bar["close"] > line_val_latest:
                    # Find recent Swing Low for Stop Loss
                    recent_lows = [s.price for s in swings if not s.is_high and s.index > tl.point1[0]]
                    sl = min(recent_lows) if recent_lows else latest_bar["low"] * 0.992
                    sl = min(sl, latest_bar["low"] * 0.996)  # Ensure SL is below breakout candle

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
                            fvgs=fvgs[-3:] if fvgs else []
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
                            fvgs=fvgs[-3:] if fvgs else []
                        ))

        return signals
