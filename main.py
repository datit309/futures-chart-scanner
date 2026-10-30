import os
import time
import asyncio
import argparse
from typing import List, Dict, Optional
from datetime import datetime

from config import ScannerConfig
from binance_client import BinanceClient
from technical_engine import TechnicalEngine
from risk_manager import RiskManager, EnrichedSignal
from chart_renderer import ChartRenderer
from telegram_notifier import TelegramNotifier

class ScannerPipeline:
    def __init__(self, config: ScannerConfig):
        self.config = config
        self.client = BinanceClient(base_url=config.binance_fapi_url)
        self.technical_engine = TechnicalEngine(
            swing_window=2,
            min_touches=config.min_trendline_touches,
            tolerance_pct=0.005
        )
        self.risk_manager = RiskManager(
            min_rr=config.min_rr,
            max_sl_pct=0.035,
            min_sl_pct=0.003
        )
        self.chart_renderer = ChartRenderer()
        self.notifier = TelegramNotifier(
            bot_token=config.telegram_bot_token,
            chat_id=config.telegram_chat_id
        )
        self.cooldown_cache: Dict[str, float] = {}

    def is_in_cooldown(self, symbol: str) -> bool:
        last_time = self.cooldown_cache.get(symbol, 0)
        cooldown_sec = self.config.alert_cooldown_minutes * 60
        return (time.time() - last_time) < cooldown_sec

    def record_alert(self, symbol: str):
        self.cooldown_cache[symbol] = time.time()

    async def scan_single_symbol(
        self, 
        symbol: str, 
        save_dir: Optional[str] = None
    ) -> Optional[EnrichedSignal]:
        klines = await self.client.get_klines(symbol, interval=self.config.timeframe, limit=80)
        if not klines or len(klines) < 15:
            return None

        # Analyze market structure & trendlines
        raw_signals = self.technical_engine.analyze_market(
            klines, symbol=symbol, timeframe=self.config.timeframe
        )
        if not raw_signals:
            return None

        # Evaluate risk management & R:R filters
        for raw_signal in raw_signals:
            enriched = self.risk_manager.validate_and_enrich(raw_signal)
            if not enriched:
                continue

            # Render chart image
            save_path = None
            if save_dir:
                os.makedirs(save_dir, exist_ok=True)
                timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
                save_path = os.path.join(save_dir, f"{symbol}_{self.config.timeframe}_{timestamp_str}.png")

            img_bytes = self.chart_renderer.render_chart_image(klines, enriched, save_path=save_path)

            # Telegram Alert
            if not self.is_in_cooldown(symbol):
                caption = self.risk_manager.format_telegram_caption(enriched)
                await self.notifier.send_chart_alert(
                    photo_bytes=img_bytes,
                    caption=caption,
                    filename=f"{symbol}_{self.config.timeframe}.png"
                )
                self.record_alert(symbol)
            else:
                print(f"[Cooldown] Alert for {symbol} suppressed by cooldown.")

            return enriched

        return None

    async def scan_cycle(self, save_dir: Optional[str] = None) -> List[EnrichedSignal]:
        print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 🚀 Bắt đầu quét Top {self.config.top_n_coins} coin Binance Futures ({self.config.timeframe})...")
        top_symbols = await self.client.get_top_futures_symbols(limit=self.config.top_n_coins)
        if not top_symbols:
            print("[Warning] Không lấy được danh sách symbols từ Binance.")
            return []

        print(f"-> Đã lấy {len(top_symbols)} coin volume lớn nhất: {', '.join(top_symbols[:8])}...")
        
        found_signals: List[EnrichedSignal] = []
        # Concurrently process in batches of 5 to be polite with rate limits
        batch_size = 5
        for i in range(0, len(top_symbols), batch_size):
            batch = top_symbols[i:i + batch_size]
            tasks = [self.scan_single_symbol(sym, save_dir=save_dir) for sym in batch]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for res in results:
                if isinstance(res, EnrichedSignal):
                    found_signals.append(res)
                    print(f"🎯 [KÈO NGON] Phát hiện {res.symbol} ({res.signal_type}) - R:R 1:{res.risk_reward:.1f} | {res.description}")

        print(f"-> Hoàn thành chu kỳ quét. Tìm thấy {len(found_signals)} tín hiệu đạt chuẩn R:R >= 1:{self.config.min_rr}.\n")
        return found_signals

    async def run_loop(self, save_dir: Optional[str] = "saved_charts"):
        print(f"🤖 Bot Chart Scanner đang chạy ngầm 24/7...")
        print(f"-> Chu kỳ quét: mỗi {self.config.scan_interval_seconds}s | Khung: {self.config.timeframe}")
        if self.notifier.is_configured:
            await self.notifier.send_text_message(
                f"🚀 <b>Crypto Futures Chart Scanner Online!</b>\nKhung: {self.config.timeframe} | Top: {self.config.top_n_coins} coins | Min R:R: 1:{self.config.min_rr}"
            )
        try:
            while True:
                await self.scan_cycle(save_dir=save_dir)
                await asyncio.sleep(self.config.scan_interval_seconds)
        except (KeyboardInterrupt, asyncio.CancelledError):
            print("\n[Bot] Đã dừng chu kỳ quét.")
        finally:
            await self.client.close()

async def main_async():
    parser = argparse.ArgumentParser(description="Crypto Futures Chart Scanner & Telegram Alert Bot")
    parser.add_argument("--scan-once", action="store_true", help="Quét 1 vòng duy nhất rồi thoát (thích hợp test)")
    parser.add_argument("--loop", action="store_true", help="Chạy vòng lặp ngầm liên tục 24/7")
    parser.add_argument("--symbol", type=str, default="", help="Quét chỉ 1 coin cụ thể (ví dụ: BTCUSDT)")
    parser.add_argument("--timeframe", type=str, default="", help="Ghi đè khung thời gian (15m, 1h, 4h)")
    parser.add_argument("--top", type=int, default=0, help="Số lượng coin quét (ví dụ: 30)")
    parser.add_argument("--save-charts", type=str, default="saved_charts", help="Thư mục lưu ảnh chart xuất ra")
    args = parser.parse_args()

    config = ScannerConfig.load("config.json")
    if args.timeframe:
        config.timeframe = args.timeframe
    if args.top > 0:
        config.top_n_coins = args.top

    pipeline = ScannerPipeline(config)

    try:
        if args.symbol:
            sym = args.symbol.upper()
            if not sym.endswith("USDT"):
                sym += "USDT"
            print(f"🔍 Đang phân tích kỹ thuật cho cặp: {sym} ({config.timeframe})...")
            res = await pipeline.scan_single_symbol(sym, save_dir=args.save_charts)
            if res:
                print(f"\n✅ PHÁT HIỆN TÍN HIỆU: {res.symbol} ({res.signal_type})")
                print(f"   Entry: ${res.entry_price:,.4f} | SL: ${res.stop_loss:,.4f} | TP: ${res.take_profit:,.4f} | R:R: 1:{res.risk_reward:.1f}")
                print(f"   Ảnh chart đã lưu tại: {args.save_charts}/")
            else:
                print(f"ℹ️ Không có tín hiệu Breakout/Cản nào đạt chuẩn R:R >= {config.min_rr} trên {sym} lúc này.")
        elif args.scan_once or not args.loop:
            # Default to scan-once if not loop specified
            await pipeline.scan_cycle(save_dir=args.save_charts)
        else:
            await pipeline.run_loop(save_dir=args.save_charts)
    finally:
        await pipeline.client.close()

def main():
    asyncio.run(main_async())

if __name__ == "__main__":
    main()
