import os
import json
import time
import asyncio
import re
from typing import Dict, Any, List, Optional
import aiohttp
from aiohttp import WSMsgType, web
from aiohttp.client_exceptions import ClientConnectionResetError

from config import ScannerConfig
from binance_client import BinanceClient
from technical_engine import TechnicalEngine
from risk_manager import RiskManager, EnrichedSignal
from chart_renderer import ChartRenderer
from telegram_notifier import TelegramNotifier
from signal_tracker import SignalTracker

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")



MARKET_WS_TIMEFRAMES = {"15m", "1h", "4h"}
MARKET_STALE_AFTER_SECONDS = 15.0
MARKET_WS_POLL_SECONDS = 3.0
MARKET_SYMBOL_RE = re.compile(r"^[A-Z0-9]{2,30}USDT$")


def websocket_backoff_delay(attempt: int) -> int:
    return min(2 ** max(0, attempt - 1), 30)


def should_retry_websocket_close(code: Optional[int]) -> bool:
    # Normal closure, going away, service restart and try-again-later are transient for this feed.
    return code not in {1008}


def normalize_kline_dict(kline: Dict[str, Any], symbol: str, timeframe: str) -> Optional[Dict[str, Any]]:
    """Convert an internal OHLCV kline dict into a websocket candle payload."""
    try:
        open_time = int(kline["timestamp"])
        o, h, low, close, volume = (
            float(kline[key]) for key in ("open", "high", "low", "close", "volume")
        )
        if min(o, h, low, close, volume) < 0 or h < max(o, close, low) or low > min(o, close):
            return None
        return {
            "type": "kline",
            "symbol": symbol,
            "timeframe": timeframe,
            "candle": {
                "time": open_time // 1000,
                "open": o,
                "high": h,
                "low": low,
                "close": close,
                "volume": volume,
                "closed": False,
            },
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
        self.signal_tracker = SignalTracker(db_path=os.getenv("SIGNALS_DB_PATH", "signals.db"))
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

                # Evaluate any open signals against the latest forming candle
                try:
                    outcomes = self.signal_tracker.evaluate_open_signals(sym, klines[-1])
                    for outcome in outcomes:
                        if outcome.get("status") in ("WIN", "LOSS"):
                            await self.broadcast_ws("SIGNAL_OUTCOME", outcome)
                            if sym in self.active_signals:
                                self.active_signals[sym]["status"] = outcome["status"]
                except Exception as exc:
                    print(f"[Tracker] Error evaluating signals for {sym}: {exc}")

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
                            "timestamp": time.time(),
                            "status": "OPEN",
                        }

                        # Persist to SQLite database with kline snapshot
                        try:
                            sig_id = self.signal_tracker.save_signal(sig_dict, klines=klines[-50:])
                            sig_dict["id"] = sig_id
                        except Exception as exc:
                            print(f"[Tracker] Error saving signal for {sym}: {exc}")

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
        "top_symbols": state.top_symbols[:15],
        "stats": state.signal_tracker.get_stats(),
    })

async def handle_api_signals(request: web.Request) -> web.Response:
    state: WebServerState = request.app["state"]
    status_filter = request.query.get("status")
    symbol_filter = request.query.get("symbol")
    limit = int(request.query.get("limit", "50"))
    signals = state.signal_tracker.list_signals(
        status_filter=status_filter,
        symbol_filter=symbol_filter,
        limit=limit,
    )
    stats = state.signal_tracker.get_stats()
    return web.json_response({
        "signals": signals,
        "stats": stats,
    })

async def handle_api_signal_chart(request: web.Request) -> web.Response:
    state: WebServerState = request.app["state"]
    try:
        signal_id = int(request.match_info["id"])
    except (KeyError, ValueError):
        return web.json_response({"error": "invalid_id"}, status=400)

    sig = state.signal_tracker.get_signal(signal_id)
    if not sig:
        return web.json_response({"error": "signal_not_found"}, status=404)

    kline_snapshot = sig.get("kline_snapshot", [])
    tv_candles = []
    tv_volumes = []
    for k in kline_snapshot:
        raw_ts = k.get("timestamp", k.get("time", 0))
        t_sec = int(raw_ts / 1000) if raw_ts > 1e11 else int(raw_ts)
        o, h, l, c = float(k["open"]), float(k["high"]), float(k["low"]), float(k["close"])
        vol = float(k.get("volume", 0.0))
        tv_candles.append({
            "time": t_sec,
            "open": o,
            "high": h,
            "low": l,
            "close": c,
        })
        is_bull = c >= o
        tv_volumes.append({
            "time": t_sec,
            "value": vol,
            "color": "rgba(14, 203, 129, 0.45)" if is_bull else "rgba(246, 70, 93, 0.45)",
        })

    return web.json_response({
        "symbol": sig["symbol"],
        "timeframe": sig["timeframe"],
        "signal": sig,
        "candles": tv_candles,
        "volumes": tv_volumes,
        "trendlines": [],
        "sr_zones": [],
        "zone_bands": [],
        "fvgs": [],
    })

async def handle_api_symbols(request: web.Request) -> web.Response:
    state: WebServerState = request.app["state"]
    if not state.top_symbols:
        state.top_symbols = await state.client.get_top_futures_symbols(limit=state.config.top_n_coins)
    tickers = {symbol: state.client.ticker_metrics.get(symbol, {}) for symbol in state.top_symbols}
    resp: Dict[str, Any] = {
        "symbols": state.top_symbols,
        "count": len(state.top_symbols),
        "tickers": tickers,
    }
    if state.client.ticker_metrics:
        resp["all_symbols"] = list(state.client.ticker_metrics.keys())
    return web.json_response(resp)

def build_structure_payload(
    state: "WebServerState",
    klines: List[Dict[str, Any]],
    symbol: str,
    timeframe: str,
) -> Dict[str, Any]:
    """Compute market structure (trendlines, zones, FVGs, signal) from klines."""
    swings = state.technical_engine.find_swing_points(klines)
    trendlines = state.technical_engine.detect_trendlines(klines, swings)
    sr_zones = state.technical_engine.detect_sr_zones(klines, swings)
    fvgs = state.technical_engine.detect_fvg(klines)

    n_bars = len(klines)
    time_step = (klines[-1]["timestamp"] - klines[-2]["timestamp"]) // 1000 if n_bars > 1 else 0
    next_time = int(klines[-1]["timestamp"] / 1000) + time_step

    signal_info = state.active_signals.get(symbol)
    signal_trendline = None
    if not signal_info:
        for raw_sig in state.technical_engine.analyze_market(klines, symbol=symbol, timeframe=timeframe):
            enriched = state.risk_manager.validate_and_enrich(raw_sig)
            if enriched:
                signal_info = {
                    "symbol": enriched.symbol,
                    "timeframe": enriched.timeframe,
                    "signal_type": enriched.signal_type,
                    "pattern": enriched.pattern.value if hasattr(enriched.pattern, "value") else str(enriched.pattern),
                    "entry_price": enriched.entry_price,
                    "stop_loss": enriched.stop_loss,
                    "take_profit": enriched.take_profit,
                    "tp1": enriched.extra_targets.get("tp1", enriched.take_profit),
                    "tp2": enriched.extra_targets.get("tp2", enriched.take_profit),
                    "risk_reward": enriched.risk_reward,
                    "sl_pct": enriched.sl_pct,
                    "description": enriched.description,
                    "timestamp": time.time(),
                }
                if raw_sig.trendlines:
                    signal_trendline = raw_sig.trendlines[0]
                break

    # Select trendlines: if a signal exists, the broken trendline MUST be shown as #1!
    selected_trendlines = []
    if signal_trendline:
        selected_trendlines.append(signal_trendline)
        opposing = [tl for tl in trendlines if tl.is_resistance != signal_trendline.is_resistance]
        opposing_selected = state.technical_engine.select_strongest_trendlines(opposing, n_bars=n_bars)
        if opposing_selected:
            selected_trendlines.append(opposing_selected[0])
    else:
        selected_trendlines = state.technical_engine.select_strongest_trendlines(trendlines, n_bars=n_bars)

    tv_trendlines = []
    for tl in selected_trendlines:
        idx1, p1 = tl.point1
        idx2, p2 = tl.point2
        if idx1 < n_bars and idx2 < n_bars:
            tv_trendlines.append({
                "time1": int(klines[idx1]["timestamp"] / 1000),
                "price1": p1,
                "time2": int(klines[idx2]["timestamp"] / 1000),
                "price2": p2,
                "anchor_index": idx2,
                "point2": [idx2, p2],
                "next_time": next_time,
                "curr_time": int(klines[n_bars - 1]["timestamp"] / 1000),
                "curr_price": tl.value_at(n_bars - 1),
                "next_price": tl.value_at(n_bars),
                "is_resistance": tl.is_resistance,
                "touches": tl.touches,
                "residual": getattr(tl, "residual", None),
            })

    # Crisp, elegant S/R bands (max +-0.15% padding so it never covers the screen)
    zone_bands = []
    for lo, hi in sr_zones[:3]:
        mid = (lo + hi) / 2
        pad = min(max(abs(hi - lo) / 2, mid * 0.0008), mid * 0.0018)
        zone_bands.append({"bottom": mid - pad, "top": mid + pad, "kind": "SUPPORT_RESISTANCE"})
    fvg_bands = [dict(fvg) for fvg in (fvgs[-4:] if fvgs else [])]
    for band in fvg_bands:
        band["end_index"] = n_bars - 1

    order_blocks = state.technical_engine.detect_order_blocks(klines, swings, unmitigated_only=True)
    structure_breaks = state.technical_engine.detect_market_structure_shifts(klines, swings)
    regression_channel = state.technical_engine.calculate_regression_channel(klines, window=60)
    forecast_path = state.technical_engine.generate_forecast_path(signal_info, klines) if signal_info else []
    regime_info = state.technical_engine.detect_market_regime(klines)

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "regime": regime_info["regime"],
        "adx": regime_info["adx"],
        "trendlines": tv_trendlines,
        "sr_zones": sr_zones[:4],
        "zone_bands": zone_bands,
        "fvgs": fvg_bands,
        "order_blocks": order_blocks,
        "structure_breaks": structure_breaks,
        "regression_channel": regression_channel or {},
        "forecast_path": forecast_path,
        "signal": signal_info,
    }


async def handle_api_chart(request: web.Request) -> web.Response:
    state: WebServerState = request.app["state"]
    symbol = request.query.get("symbol", "BTCUSDT").upper()
    timeframe = request.query.get("timeframe", state.config.timeframe)
    limit = int(request.query.get("limit", "1000"))
    end_time_raw = request.query.get("endTime")
    end_time = int(end_time_raw) if end_time_raw and end_time_raw.isdigit() else None

    if end_time is not None:
        klines = await state.client.get_klines(symbol, interval=timeframe, limit=limit, endTime=end_time)
    else:
        klines = await state.client.get_klines(symbol, interval=timeframe, limit=limit)
    if not klines:
        return web.json_response({"error": f"Không lấy được nến cho {symbol}"}, status=404)

    structure = build_structure_payload(state, klines, symbol, timeframe)

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

    return web.json_response({
        "symbol": symbol,
        "timeframe": timeframe,
        "regime": structure["regime"],
        "adx": structure["adx"],
        "candles": tv_candles,
        "volumes": tv_volumes,
        "trendlines": structure["trendlines"],
        "sr_zones": structure["sr_zones"],
        "zone_bands": structure["zone_bands"],
        "fvgs": structure["fvgs"],
        "order_blocks": structure["order_blocks"],
        "structure_breaks": structure["structure_breaks"],
        "regression_channel": structure["regression_channel"],
        "forecast_path": structure["forecast_path"],
        "signal": structure["signal"]
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
    if timeframe not in MARKET_WS_TIMEFRAMES or not MARKET_SYMBOL_RE.fullmatch(symbol):
        return web.json_response({"error": "invalid_subscription"}, status=400)
    if symbol not in state.top_symbols:
        if symbol in state.client.ticker_metrics:
            state.top_symbols.append(symbol)
        else:
            return web.json_response({"error": "invalid_subscription"}, status=400)

    ws = web.WebSocketResponse(heartbeat=20.0)
    await ws.prepare(request)
    attempt = 0
    downstream_closed = asyncio.Event()

    async def send(payload: Dict[str, Any]) -> bool:
        """Send to the browser, swallowing writes on an already-closing socket."""
        if ws.closed:
            return False
        try:
            await ws.send_json(payload)
            return True
        except (ClientConnectionResetError, ConnectionResetError, asyncio.CancelledError):
            downstream_closed.set()
            return False

    async def watch_downstream():
        try:
            async for _ in ws:
                pass
        finally:
            downstream_closed.set()

    downstream_task = asyncio.create_task(watch_downstream())

    async def stream_ticks():
        """Relay sub-second live ticks from Binance bookTicker directly to the browser."""
        while not ws.closed and not downstream_closed.is_set():
            session = None
            try:
                session = aiohttp.ClientSession()
                url = f"wss://fstream.binance.com/ws/{symbol.lower()}@bookTicker"
                async with session.ws_connect(url, heartbeat=20.0) as upstream:
                    async for msg in upstream:
                        if ws.closed or downstream_closed.is_set():
                            break
                        if msg.type == WSMsgType.TEXT:
                            try:
                                d = json.loads(msg.data)
                                bid = float(d["b"])
                                ask = float(d["a"])
                                if bid > 0 and ask >= bid:
                                    mid = (bid + ask) / 2
                                    if not await send({
                                        "type": "tick",
                                        "symbol": symbol,
                                        "price": mid,
                                        "bid": bid,
                                        "ask": ask,
                                        "time": int(d.get("E", 0))
                                    }):
                                        break
                            except Exception:
                                pass
                        elif msg.type in (WSMsgType.CLOSED, WSMsgType.ERROR):
                            break
            except asyncio.CancelledError:
                break
            except Exception:
                await asyncio.sleep(2)
            finally:
                if session and not session.closed:
                    await session.close()

    tick_task = asyncio.create_task(stream_ticks())
    history: List[Dict[str, Any]] = []
    try:
        while not ws.closed and not downstream_closed.is_set():
            await send({"type": "status", "state": "connecting" if attempt == 0 else "reconnecting"})
            last_event_at = time.monotonic()
            stale_sent = False
            await send({"type": "status", "state": "connected"})

            # Load full history once so structure can be computed server-side.
            try:
                history = await state.client.get_klines(symbol, interval=timeframe, limit=100)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                print(f"[MarketWS] {symbol} history fetch failed: {exc}")
                history = []

            if history:
                try:
                    structure = build_structure_payload(state, history, symbol, timeframe)
                    await send({"type": "structure", **structure})
                except Exception as exc:
                    print(f"[MarketWS] {symbol} structure build failed: {exc}")

            polls_since_structure = 0
            # Binance kline WebSocket streams handshake successfully but deliver no
            # frames in this network, so we poll the REST klines endpoint for real OHLC.
            while not ws.closed and not downstream_closed.is_set():
                try:
                    klines = await state.client.get_klines(symbol, interval=timeframe, limit=2)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    print(f"[MarketWS] {symbol} kline poll failed: {exc}")
                    klines = None

                if klines:
                    last = klines[-1]
                    payload = normalize_kline_dict(last, symbol, timeframe)
                    if payload:
                        last_event_at = time.monotonic()
                        stale_sent = False
                        if not await send(payload):
                            break

                        # merge into history and refresh structure when the candle closes
                        if history and last["timestamp"] > history[-1]["timestamp"]:
                            history = (history + [last])[-100:]
                            polls_since_structure += 1
                            closed = last["close_time"] <= int(time.time() * 1000)
                            if closed or polls_since_structure >= 5:
                                polls_since_structure = 0
                                try:
                                    structure = build_structure_payload(state, history, symbol, timeframe)
                                    if not await send({"type": "structure", **structure}):
                                        break
                                except Exception as exc:
                                    print(f"[MarketWS] {symbol} structure build failed: {exc}")
                elif not stale_sent and time.monotonic() - last_event_at >= MARKET_STALE_AFTER_SECONDS:
                    await send({"type": "status", "state": "stale"})
                    stale_sent = True

                if ws.closed or downstream_closed.is_set():
                    break
                await asyncio.sleep(MARKET_WS_POLL_SECONDS)

                if not stale_sent and time.monotonic() - last_event_at >= MARKET_STALE_AFTER_SECONDS:
                    if not await send({"type": "status", "state": "stale"}):
                        break
                    stale_sent = True

            if ws.closed or downstream_closed.is_set():
                break
            attempt += 1
            if not await send({"type": "status", "state": "reconnecting"}):
                break
            await asyncio.sleep(websocket_backoff_delay(attempt))
    finally:
        downstream_closed.set()
        if tick_task and not tick_task.done():
            tick_task.cancel()
            try:
                await tick_task
            except asyncio.CancelledError:
                pass
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
    app.router.add_get("/api/signals", handle_api_signals)
    app.router.add_get("/api/signals/{id}/chart", handle_api_signal_chart)
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
