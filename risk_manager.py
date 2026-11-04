from dataclasses import dataclass, field
from typing import Optional, Dict
from technical_engine import MarketSignal, PatternType

@dataclass
class EnrichedSignal(MarketSignal):
    extra_targets: Dict[str, float] = field(default_factory=dict)
    sl_pct: float = 0.0

class RiskManager:
    def __init__(self, min_rr: float = 2.0, max_sl_pct: float = 0.035, min_sl_pct: float = 0.003):
        self.min_rr = min_rr
        self.max_sl_pct = max_sl_pct
        self.min_sl_pct = min_sl_pct

    def validate_and_enrich(self, signal: MarketSignal) -> Optional[EnrichedSignal]:
        entry = signal.entry_price
        sl = signal.stop_loss
        is_long = signal.signal_type == "LONG"
        required_rr = 1.2 if getattr(signal, "pattern", None) == PatternType.MEAN_REVERSION_TRAP else self.min_rr

        if is_long:
            risk = entry - sl
            if risk <= 0:
                return None
            sl_pct = risk / entry

            # Guard against extreme or too-tight stops
            if sl_pct < self.min_sl_pct or sl_pct > self.max_sl_pct:
                return None

            # If signal already specified a take_profit, check if that TP achieves required_rr
            if signal.take_profit > entry:
                rr = (signal.take_profit - entry) / risk
                if rr < required_rr:
                    return None
                tp1 = getattr(signal, "tp1", 0.0) or (entry + risk * 1.2)
                tp2 = getattr(signal, "tp2", 0.0) or signal.take_profit
            else:
                tp1 = entry + risk * 1.2
                tp2 = entry + risk * 2.2
                rr = (tp2 - entry) / risk
        else:
            risk = sl - entry
            if risk <= 0:
                return None
            sl_pct = risk / entry

            if sl_pct < self.min_sl_pct or sl_pct > self.max_sl_pct:
                return None

            if signal.take_profit > 0 and signal.take_profit < entry:
                rr = (entry - signal.take_profit) / risk
                if rr < required_rr:
                    return None
                tp1 = getattr(signal, "tp1", 0.0) or (entry - risk * 1.2)
                tp2 = getattr(signal, "tp2", 0.0) or signal.take_profit
            else:
                tp1 = entry - risk * 1.2
                tp2 = entry - risk * 2.2
                rr = (entry - tp2) / risk


        if rr < self.min_rr:
            return None

        return EnrichedSignal(
            symbol=signal.symbol,
            timeframe=signal.timeframe,
            signal_type=signal.signal_type,
            pattern=signal.pattern,
            entry_price=entry,
            stop_loss=sl,
            take_profit=tp2,
            risk_reward=rr,
            description=signal.description,
            trendlines=signal.trendlines,
            sr_zones=signal.sr_zones,
            fvgs=signal.fvgs,
            extra_targets={"tp1": tp1, "tp2": tp2},
            sl_pct=sl_pct
        )

    def format_telegram_caption(self, signal: EnrichedSignal) -> str:
        direction_emoji = "🟢 LONG" if signal.signal_type == "LONG" else "🔴 SHORT"
        sl_pct_str = f"{signal.sl_pct * 100:.2f}%"

        tp1 = signal.extra_targets.get("tp1", signal.take_profit)
        tp2 = signal.extra_targets.get("tp2", signal.take_profit)

        return (
            f"🎯 <b>BINANCE FUTURES SIGNAL — {signal.symbol}</b>\n\n"
            f"⚡ <b>Khung:</b> {signal.timeframe}\n"
            f"📈 <b>Vị thế:</b> {direction_emoji}\n"
            f"🔍 <b>Mô hình:</b> {signal.description}\n\n"
            f"📍 <b>Entry:</b> <code>${signal.entry_price:,.4f}</code>\n"
            f"🛑 <b>Stop Loss:</b> <code>${signal.stop_loss:,.4f}</code> (-{sl_pct_str})\n"
            f"🎯 <b>TP1 (1.5R):</b> <code>${tp1:,.4f}</code>\n"
            f"🚀 <b>TP2 (2.5R):</b> <code>${tp2:,.4f}</code>\n"
            f"⚖️ <b>Tỷ lệ R:R:</b> 1:{signal.risk_reward:.1f}\n\n"
            f"⚠️ <i>Lưu ý: Quản trị vốn tối đa 1-2% rủi ro tài khoản cho mỗi lệnh!</i>"
        )
