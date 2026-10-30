import io
import os
import tempfile
from datetime import datetime
from typing import List, Dict, Any, Optional

os.environ.setdefault("MPLCONFIGDIR", tempfile.gettempdir())
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from risk_manager import EnrichedSignal

class ChartRenderer:
    def __init__(self):
        # Color palette inspired by Binance Dark Mode
        self.bg_color = "#181a20"
        self.panel_color = "#181a20"
        self.grid_color = "#2b313a"
        self.text_color = "#eaecef"
        self.subtext_color = "#848e9c"
        self.bull_color = "#0ecb81"
        self.bear_color = "#f6465d"
        self.trendline_color = "#f0b90b"
        self.entry_color = "#00f0ff"
        self.sl_color = "#f6465d"
        self.tp_color = "#0ecb81"

    def render_chart_image(
        self, 
        klines: List[Dict[str, Any]], 
        signal: EnrichedSignal, 
        save_path: Optional[str] = None
    ) -> bytes:
        """
        Render a dark-mode candlestick chart with trendlines, zones, and trade levels.
        Returns PNG bytes.
        """
        n = len(klines)
        fig, (ax_main, ax_vol) = plt.subplots(
            2, 1, 
            figsize=(12, 7), 
            gridspec_kw={"height_ratios": [4, 1]},
            facecolor=self.bg_color
        )

        for ax in (ax_main, ax_vol):
            ax.set_facecolor(self.panel_color)
            ax.tick_params(colors=self.subtext_color, labelsize=9)
            ax.grid(True, linestyle="--", linewidth=0.5, color=self.grid_color, alpha=0.7)
            for spine in ax.spines.values():
                spine.set_color(self.grid_color)

        # 1. Plot Candlesticks & Volume
        candle_width = 0.65
        for i, k in enumerate(klines):
            o, h, l, c = k["open"], k["high"], k["low"], k["close"]
            vol = k.get("volume", 0)
            is_bull = c >= o
            color = self.bull_color if is_bull else self.bear_color

            # Wick
            ax_main.vlines(i, l, h, color=color, linewidth=1.1, zorder=2)
            # Body
            body_bottom = min(o, c)
            body_height = max(abs(c - o), 0.000001)
            rect = Rectangle(
                (i - candle_width / 2, body_bottom),
                candle_width,
                body_height,
                facecolor=color,
                edgecolor=color,
                zorder=3
            )
            ax_main.add_patch(rect)

            # Volume Bar
            ax_vol.bar(i, vol, color=color, alpha=0.5, width=candle_width)

        # 2. Plot S/R Zones
        if signal.sr_zones:
            for bottom, top in signal.sr_zones[:3]:
                ax_main.axhspan(bottom, top, color="#3861fb", alpha=0.15, zorder=1)

        # 3. Plot FVGs
        if signal.fvgs:
            for fvg in signal.fvgs:
                fvg_color = "#ff9800" if fvg["type"] == "BULLISH" else "#9c27b0"
                ax_main.axhspan(fvg["bottom"], fvg["top"], color=fvg_color, alpha=0.12, zorder=1)

        # 4. Plot Trendlines
        for tl in signal.trendlines:
            x_start = tl.point1[0]
            x_end = min(n + 3, n + 5)
            y_start = tl.value_at(x_start)
            y_end = tl.value_at(x_end)

            ax_main.plot(
                [x_start, x_end], 
                [y_start, y_end], 
                color=self.trendline_color, 
                linestyle="-", 
                linewidth=1.8, 
                zorder=4,
                label=f"Trendline ({tl.touches} touches)"
            )

            # Highlight touch points
            if tl.touch_indices:
                touch_x = [t for t in tl.touch_indices if t < n]
                touch_y = [tl.value_at(t) for t in touch_x]
                ax_main.scatter(touch_x, touch_y, color=self.trendline_color, s=25, zorder=5)

        # 5. Plot Trade Levels: Entry, SL, TP
        entry = signal.entry_price
        sl = signal.stop_loss
        tp1 = signal.extra_targets.get("tp1", signal.take_profit)
        tp2 = signal.extra_targets.get("tp2", signal.take_profit)

        # Entry Line
        ax_main.axhline(entry, color=self.entry_color, linestyle="--", linewidth=1.2, alpha=0.9)
        ax_main.text(
            n - 1, entry, f" Entry: ${entry:,.2f}", 
            color=self.entry_color, fontsize=9, va="bottom", ha="left", weight="bold"
        )

        # Stop Loss Line
        ax_main.axhline(sl, color=self.sl_color, linestyle="--", linewidth=1.2, alpha=0.9)
        ax_main.text(
            n - 1, sl, f" SL: ${sl:,.2f} (-{signal.sl_pct*100:.1f}%)", 
            color=self.sl_color, fontsize=9, va="top", ha="left", weight="bold"
        )

        # TP1 & TP2 Lines
        ax_main.axhline(tp1, color=self.tp_color, linestyle=":", linewidth=1.0, alpha=0.7)
        ax_main.text(
            n - 1, tp1, f" TP1 (1.5R): ${tp1:,.2f}", 
            color=self.tp_color, fontsize=8, va="bottom", ha="left"
        )

        ax_main.axhline(tp2, color=self.tp_color, linestyle="--", linewidth=1.3, alpha=0.9)
        ax_main.text(
            n - 1, tp2, f" TP2 (2.5R): ${tp2:,.2f}", 
            color=self.tp_color, fontsize=9, va="bottom", ha="left", weight="bold"
        )

        # Formatting axes
        ax_main.set_xlim(-1, n + 8)
        ax_vol.set_xlim(-1, n + 8)

        # Title and Header
        signal_badge = "[LONG]" if signal.signal_type == "LONG" else "[SHORT]"
        ax_main.set_title(
            f"{signal.symbol} [{signal.timeframe}] — {signal_badge} | {signal.description} | R:R 1:{signal.risk_reward:.1f}",
            color=self.text_color,
            fontsize=13,
            pad=12,
            weight="bold"
        )

        # X-Axis Timestamp labels
        step = max(1, n // 6)
        x_ticks = list(range(0, n, step))
        x_labels = [
            datetime.fromtimestamp(klines[idx]["timestamp"] / 1000).strftime("%H:%M")
            for idx in x_ticks
        ]
        ax_vol.set_xticks(x_ticks)
        ax_vol.set_xticklabels(x_labels, color=self.subtext_color)
        ax_main.set_xticks([])

        plt.tight_layout()

        # Save to buffer
        buf = io.BytesIO()
        plt.savefig(buf, format="png", dpi=130, facecolor=self.bg_color, edgecolor="none")
        plt.close(fig)

        img_bytes = buf.getvalue()
        buf.close()

        if save_path:
            with open(save_path, "wb") as f:
                f.write(img_bytes)

        return img_bytes
