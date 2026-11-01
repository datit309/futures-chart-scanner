import os
import json
import time
import asyncio
import re
from typing import Dict, Any, List, Optional
import aiohttp
from aiohttp import WSMsgType, web

from config import ScannerConfig
from binance_client import BinanceClient
from technical_engine import TechnicalEngine
from risk_manager import RiskManager, EnrichedSignal
from chart_renderer import ChartRenderer
from telegram_notifier import TelegramNotifier

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")



MARKET_WS_TIMEFRAMES = {"15m", "1h", "4h"}
MARKET_STALE_AFTER_SECONDS = 15.0
MARKET_WS_POLL_SECONDS = 1.0
MARKET_SYMBOL_RE = re.compile(r"^[A-Z0-9]{2,30}USDT$")


async def connect_binance_ws(session: aiohttp.ClientSession, url: str):
    return await session.ws_connect(url, heartbeat=20.0)


def websocket_backoff_delay(attempt: int) -> int:
    return min(2 ** max(0, attempt - 1), 30)


def should_retry_websocket_close(code: Optional[int]) -> bool:
    return code not in {1000, 1001, 1008, 1012, 1013}


def normalize_binance_book_ticker_event(event: Dict[str, Any], timeframe: str) -> Optional[Dict[str, Any]]:
    """Normalize Binance bookTicker to a midpoint price update."""
    try:
        symbol = str(event["s"]).upper()
        bid = float(event["b"])
        ask = float(event["a"])
        if not MARKET_SYMBOL_RE.fullmatch(symbol) or bid <= 0 or ask < bid:
            return None
        return {
            "type": "price",
            "symbol": symbol,
            "timeframe": timeframe,
            "price": (bid + ask) / 2,
            "bid": bid,
            "ask": ask,
            "event_time": int(event.get("E", 0)),
        }
    except (KeyError, TypeError, ValueError):
        return None

class WebServerState:
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
        self.last_scan_time: float = 0.0
        self.active_signals: Dict[str, Dict[str, Any]] = {}
        self.top_symbols: List[str] = []
        self.ws_clients: set = set()
        self.is_scanning: bool = False

    async def broadcast_ws(self, msg_type: str, data: Any):
        if not self.ws_clients:
            return
        payload = json.dumps({"type": msg_type, "data": data, "timestamp": time.time()})
        disconnected = set()
        for ws in self.ws_clients:
            try:
                await ws.send_str(payload)
            except Exception:
                disconnected.add(ws)
        self.ws_clients -= disconnected

    async def run_scan(self) -> List[Dict[str, Any]]:
        if self.is_scanning:
            return list(self.active_signals.values())
        self.is_scanning = True
        try:
            print("[WebServer] 🔄 Đang chạy chu kỳ quét thị trường...")
            symbols = await self.client.get_top_futures_symbols(limit=self.config.top_n_coins)
            if symbols:
                self.top_symbols = symbols

            found_signals = []
            for sym in self.top_symbols:
                klines = await self.client.get_klines(sym, interval=self.config.timeframe, limit=80)
                if not klines or len(klines) < 15:
                    continue
                raw_signals = self.technical_engine.analyze_market(klines, symbol=sym, timeframe=self.config.timeframe)
                for raw_sig in raw_signals:
                    enriched = self.risk_manager.validate_and_enrich(raw_sig)
                    if enriched:
                        sig_dict = {
                            "symbol": enriched.symbol,
                            "timeframe": enriched.timeframe,
                            "signal_type": enriched.signal_type,
                            "pattern": enriched.pattern.value if hasattr(enriched.pattern, 'value') else str(enriched.pattern),
                            "entry_price": enriched.entry_price,
                            "stop_loss": enriched.stop_loss,
                            "take_profit": enriched.take_profit,
                            "tp1": enriched.extra_targets.get("tp1", enriched.take_profit),
                            "tp2": enriched.extra_targets.get("tp2", enriched.take_profit),
                            "risk_reward": enriched.risk_reward,
                            "sl_pct": enriched.sl_pct,
                            "description": enriched.description,
                            "timestamp": time.time()
                        }
                        self.active_signals[sym] = sig_dict
                        found_signals.append(sig_dict)

                        # Broadcast alert to WS
                        await self.broadcast_ws("NEW_SIGNAL", sig_dict)

            self.last_scan_time = time.time()
            await self.broadcast_ws("SCAN_COMPLETE", {
                "count": len(found_signals),
                "last_scan_time": self.last_scan_time,
                "signals": list(self.active_signals.values())
            })
            return found_signals
        finally:
            self.is_scanning = False

async def handle_index(request: web.Request) -> web.Response:
    index_path = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_path):
        return web.FileResponse(index_path)
    return web.Response(text="<h1>Crypto Futures Chart Scanner API</h1><p>static/index.html not found</p>", content_type="text/html")

async def handle_api_status(request: web.Request) -> web.Response:
    state: WebServerState = request.app["state"]
    if not state.client.ticker_metrics:
        state.top_symbols = await state.client.get_top_futures_symbols(limit=state.config.top_n_coins)
    return web.json_response({
        "status": "online",
        "timeframe": state.config.timeframe,
        "top_n_coins": state.config.top_n_coins,
        "min_rr": state.config.min_rr,
        "last_scan_time": state.last_scan_time,
        "is_scanning": state.is_scanning,
        "scan_interval_seconds": state.config.scan_interval_seconds,
        "active_signals": list(state.active_signals.values()),
        "top_symbols": state.top_symbols[:15]
    })

async def handle_api_symbols(request: web.Request) -> web.Response:
    state: WebServerState = request.app["state"]
    if not state.top_symbols:
        state.top_symbols = await state.client.get_top_futures_symbols(limit=state.config.top_n_coins)
    return web.json_response({
        "symbols": state.top_symbols,
        "count": len(state.top_symbols),
        "tickers": {symbol: state.client.ticker_metrics.get(symbol, {}) for symbol in state.top_symbols},
    })

async def handle_api_chart(request: web.Request) -> web.Response:
    state: WebServerState = request.app["state"]
    symbol = request.query.get("symbol", "BTCUSDT").upper()
    timeframe = request.query.get("timeframe", state.config.timeframe)
    limit = int(request.query.get("limit", "100"))

    klines = await state.client.get_klines(symbol, interval=timeframe, limit=limit)
    if not klines:
        return web.json_response({"error": f"Không lấy được nến cho {symbol}"}, status=404)

    swings = state.technical_engine.find_swing_points(klines)
    trendlines = state.technical_engine.detect_trendlines(klines, swings)
    sr_zones = state.technical_engine.detect_sr_zones(klines, swings)
    fvgs = state.technical_engine.detect_fvg(klines)

    # Format klines for Lightweight Charts: { time: seconds, open, high, low, close, volume }
    tv_candles = []
    tv_volumes = []
    for k in klines:
        t_sec = int(k["timestamp"] / 1000)
        tv_candles.append({
            "time": t_sec,
            "open": k["open"],
            "high": k["high"],
            "low": k["low"],
            "close": k["close"]
        })
        is_bull = k["close"] >= k["open"]
        tv_volumes.append({
            "time": t_sec,
            "value": k["volume"],
            "color": "rgba(14, 203, 129, 0.45)" if is_bull else "rgba(246, 70, 93, 0.45)"
        })

    # Format trendlines with concrete time coordinates for TV chart
    tv_trendlines = []
    n_bars = len(klines)
    time_step = (klines[-1]["timestamp"] - klines[-2]["timestamp"]) // 1000 if n_bars > 1 else 0
    next_time = int(klines[-1]["timestamp"] / 1000) + time_step
    for tl in trendlines:
        idx1, p1 = tl.point1
        idx2, p2 = tl.point2
        if idx1 < n_bars and idx2 < n_bars:
            t1 = int(klines[idx1]["timestamp"] / 1000)
            t2 = int(klines[idx2]["timestamp"] / 1000)
            
            # Project line to the current bar
            curr_idx = n_bars - 1
            curr_time = int(klines[curr_idx]["timestamp"] / 1000)
            curr_val = tl.value_at(curr_idx)

            tv_trendlines.append({
                "time1": t1,
                "price1": p1,
                "time2": t2,
                "price2": p2,
                "anchor_index": idx2,
                "point2": [idx2, p2],
                "next_time": next_time,
                "curr_time": curr_time,
                "curr_price": curr_val,
                "next_price": tl.value_at(n_bars),
                "is_resistance": tl.is_resistance,
                "touches": tl.touches,
                "residual": getattr(tl, "residual", None)
            })

    # Check if there is an active signal for this symbol
    signal_info = state.active_signals.get(symbol)
    if not signal_info:
        raw_signals = state.technical_engine.analyze_market(klines, symbol=symbol, timeframe=timeframe)
        for raw_sig in raw_signals:
            enriched = state.risk_manager.validate_and_enrich(raw_sig)
            if enriched:
                signal_info = {
                    "symbol": enriched.symbol,
                    "timeframe": enriched.timeframe,
                    "signal_type": enriched.signal_type,
                    "pattern": enriched.pattern.value if hasattr(enriched.pattern, 'value') else str(enriched.pattern),
                    "entry_price": enriched.entry_price,
                    "stop_loss": enriched.stop_loss,
                    "take_profit": enriched.take_profit,
                    "tp1": enriched.extra_targets.get("tp1", enriched.take_profit),
                    "tp2": enriched.extra_targets.get("tp2", enriched.take_profit),
                    "risk_reward": enriched.risk_reward,
                    "sl_pct": enriched.sl_pct,
                    "description": enriched.description,
                    "timestamp": time.time()
                }
                break

    zone_bands = [{"bottom": lo, "top": hi, "kind": "SUPPORT_RESISTANCE"} for lo, hi in sr_zones[:4]]
    fvg_bands = [dict(fvg) for fvg in (fvgs[-4:] if fvgs else [])]
    for band in fvg_bands:
        band["end_index"] = n_bars - 1
    return web.json_response({
        "symbol": symbol,
        "timeframe": timeframe,
        "candles": tv_candles,
        "volumes": tv_volumes,
        "trendlines": tv_trendlines,
        "sr_zones": sr_zones[:4],
        "zone_bands": zone_bands,
        "fvgs": fvg_bands,
        "signal": signal_info
    })

async def handle_api_scan(request: web.Request) -> web.Response:
    state: WebServerState = request.app["state"]
    signals = await state.run_scan()
    return web.json_response({
        "success": True,
        "signals_count": len(signals),
        "signals": signals
    })

async def handle_ws(request: web.Request) -> web.WebSocketResponse:
    ws = web.WebSocketResponse(heartbeat=20.0)
    await ws.prepare(request)
    state: WebServerState = request.app["state"]
    state.ws_clients.add(ws)

    # Send initial state
    await ws.send_str(json.dumps({
        "type": "INIT_STATE",
        "data": {
            "active_signals": list(state.active_signals.values()),
            "last_scan_time": state.last_scan_time,
            "top_symbols": state.top_symbols[:20]
        }
    }))

    try:
        async for msg in ws:
            pass
    finally:
        state.ws_clients.discard(ws)
    return ws


async def handle_market_ws(request: web.Request) -> web.StreamResponse:
    state: WebServerState = request.app["state"]
    symbol = request.query.get("symbol", "").upper()
    timeframe = request.query.get("timeframe", "")
    if timeframe not in MARKET_WS_TIMEFRAMES or not MARKET_SYMBOL_RE.fullmatch(symbol) or symbol not in state.top_symbols:
        return web.json_response({"error": "invalid_subscription"}, status=400)

    ws = web.WebSocketResponse(heartbeat=20.0)
    await ws.prepare(request)
    stream_url = f"wss://fstream.binance.com/ws/{symbol.lower()}@bookTicker"
    attempt = 0
    downstream_closed = asyncio.Event()

    async def watch_downstream():
        try:
            async for _ in ws:
                pass
        finally:
            downstream_closed.set()

    downstream_task = asyncio.create_task(watch_downstream())
    try:
        while not ws.closed and not downstream_closed.is_set():
            await ws.send_json({"type": "status", "state": "connecting" if attempt == 0 else "reconnecting"})
            session = aiohttp.ClientSession()
            upstream = None
            try:
                upstream = await connect_binance_ws(session, stream_url)
                attempt = 0
                last_event_at = time.monotonic()
                stale_sent = False
                await ws.send_json({"type": "status", "state": "connected"})
                receive_task = asyncio.create_task(upstream.receive())
                try:
                    while not ws.closed and not downstream_closed.is_set():
                        try:
                            message = await asyncio.wait_for(asyncio.shield(receive_task), timeout=MARKET_WS_POLL_SECONDS)
                            receive_task = asyncio.create_task(upstream.receive())
                        except asyncio.TimeoutError:
                            if not stale_sent and time.monotonic() - last_event_at >= MARKET_STALE_AFTER_SECONDS:
                                await ws.send_json({"type": "status", "state": "stale"})
                                stale_sent = True
                            continue
                        if message.type == WSMsgType.TEXT:
                            try:
                                payload = json.loads(message.data)
                            except (json.JSONDecodeError, TypeError):
                                continue
                            normalized = normalize_binance_book_ticker_event(payload, timeframe)
                            if normalized and normalized["symbol"] == symbol:
                                last_event_at = time.monotonic()
                                stale_sent = False
                                await ws.send_json(normalized)
                        elif message.type in (WSMsgType.CLOSED, WSMsgType.CLOSE, WSMsgType.ERROR):
                            break
                finally:
                    if not receive_task.done():
                        receive_task.cancel()
                    try:
                        await receive_task
                    except (asyncio.CancelledError, Exception):
                        pass
                close_code = getattr(upstream, "close_code", None)
                if not should_retry_websocket_close(close_code):
                    await ws.send_json({"type": "status", "state": "error", "reason": "upstream_closed"})
                    break
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                print(f"[MarketWS] {symbol} stream disconnected: {exc}")
                if ws.closed or downstream_closed.is_set():
                    break
            finally:
                if upstream is not None and not upstream.closed:
                    await upstream.close()
                await session.close()
            if ws.closed or downstream_closed.is_set():
                break
            attempt += 1
            await ws.send_json({"type": "status", "state": "reconnecting"})
            await asyncio.sleep(websocket_backoff_delay(attempt))
    finally:
        downstream_closed.set()
        if not downstream_task.done():
            downstream_task.cancel()
        try:
            await downstream_task
        except asyncio.CancelledError:
            pass
        if not ws.closed:
            await ws.close()
    return ws

async def background_scanner_loop(app: web.Application):
    state: WebServerState = app["state"]
    # Initial scan on startup after 2 seconds
    await asyncio.sleep(2)
    try:
        while True:
            await state.run_scan()
            await asyncio.sleep(state.config.scan_interval_seconds)
    except asyncio.CancelledError:
        pass
    finally:
        await state.client.close()

async def start_background_tasks(app: web.Application):
    app["scanner_task"] = asyncio.create_task(background_scanner_loop(app))

async def cleanup_background_tasks(app: web.Application):
    if "scanner_task" in app:
        app["scanner_task"].cancel()
        try:
            await app["scanner_task"]
        except asyncio.CancelledError:
            pass

async def create_app(config: Optional[ScannerConfig] = None) -> web.Application:
    cfg = config or ScannerConfig.load("config.json")
    app = web.Application()
    state = WebServerState(cfg)
    app["state"] = state

    app.router.add_get("/", handle_index)
    app.router.add_get("/api/status", handle_api_status)
    app.router.add_get("/api/symbols", handle_api_symbols)
    app.router.add_get("/api/chart", handle_api_chart)
    app.router.add_post("/api/scan", handle_api_scan)
    app.router.add_get("/ws/stream", handle_ws)
    app.router.add_get("/ws/market", handle_market_ws)

    os.makedirs(STATIC_DIR, exist_ok=True)
    app.router.add_static("/static", STATIC_DIR)
    return app

def run_server(host: str = "127.0.0.1", port: int = 8766):
    config = ScannerConfig.load("config.json")
    app = asyncio.run(create_app(config))
    app.on_startup.append(start_background_tasks)
    app.on_cleanup.append(cleanup_background_tasks)

    print("\n" + "=" * 65)
    print(f"🚀 BINANCE FUTURES AUTO-CHART SCANNER WEB UI RUNNING")
    print(f"👉 Mở trình duyệt tại: http://{host}:{port}")
    print("=" * 65 + "\n")
    web.run_app(app, host=host, port=port)

if __name__ == "__main__":
    run_server()
