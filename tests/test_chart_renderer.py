import pytest
from technical_engine import (
    TechnicalEngine,
    PatternType,
    Trendline
)
from risk_manager import EnrichedSignal
from chart_renderer import ChartRenderer

def create_sample_klines():
    klines = []
    base_ts = 1700000000000
    prices = [
        (100, 102, 99, 101),
        (101, 105, 100, 104),
        (104, 108, 103, 106),
        (106, 107, 101, 102),
        (102, 103, 98, 99),
        (99, 101, 97, 100),
        (100, 106, 100, 105),
        (105, 110, 104, 109),
    ]
    for idx, (o, h, l, c) in enumerate(prices):
        klines.append({
            "timestamp": base_ts + idx * 900000,
            "open": float(o),
            "high": float(h),
            "low": float(l),
            "close": float(c),
            "volume": 500.0,
            "close_time": base_ts + (idx + 1) * 900000 - 1
        })
    return klines

def test_chart_renderer_generates_valid_png():
    renderer = ChartRenderer()
    klines = create_sample_klines()

    trendline = Trendline(
        point1=(1, 105.0),
        point2=(3, 107.0),
        slope=1.0,
        intercept=104.0,
        touches=3,
        is_resistance=False,
        current_value=111.0,
        touch_indices=[1, 3]
    )

    signal = EnrichedSignal(
        symbol="BTCUSDT",
        timeframe="15m",
        signal_type="LONG",
        pattern=PatternType.TRENDLINE_BREAKOUT,
        entry_price=105.0,
        stop_loss=98.0,
        take_profit=119.0,
        risk_reward=2.0,
        description="Test Breakout Signal",
        trendlines=[trendline],
        sr_zones=[(97.0, 99.0)],
        fvgs=[],
        extra_targets={"tp1": 112.0, "tp2": 119.0},
        sl_pct=0.066
    )

    png_bytes = renderer.render_chart_image(klines, signal)
    assert isinstance(png_bytes, bytes)
    assert len(png_bytes) > 1000
    # PNG signature check: 89 50 4E 47 0D 0A 1A 0A
    assert png_bytes[:8] == b"\x89PNG\r\n\x1a\n"
