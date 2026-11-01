import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest
from aiohttp import WSMsgType

from config import ScannerConfig
from server import create_app


def book_ticker_event():
    return {"e": "bookTicker", "E": 123456, "s": "BTCUSDT", "b": "10", "B": "2", "a": "12", "A": "3"}


def test_book_ticker_normalizes_to_live_midprice():
    from server import normalize_binance_book_ticker_event
    assert normalize_binance_book_ticker_event(book_ticker_event(), "15m") == {
        "type": "price", "symbol": "BTCUSDT", "timeframe": "15m",
        "price": 11.0, "bid": 10.0, "ask": 12.0, "event_time": 123456,
    }


@pytest.mark.asyncio
async def test_server_routes():
    app = await create_app(ScannerConfig(top_n_coins=5, timeframe="15m"))
    routes = [r.resource.canonical for r in app.router.routes() if getattr(r, "resource", None)]
    assert "/api/status" in routes
    assert "/api/chart" in routes
    assert "/api/symbols" in routes
    assert "/ws/market" in routes


@pytest.mark.asyncio
async def test_root_serves_dashboard_ui(aiohttp_client):
    app = await create_app(ScannerConfig(top_n_coins=5, timeframe="15m"))
    client = await aiohttp_client(app)
    response = await client.get("/")
    assert response.status == 200
    body = await response.text()
    assert "FUTURES DESK" in body
    assert "SCAN MARKET" in body
    assert "lightweight-charts" in body
    assert "chart_stream.js" in body
    assert "ws/market" in body
    assert 'aria-label="Overlay controls"' in body


@pytest.mark.asyncio
async def test_symbols_endpoint_keeps_symbols_and_adds_metrics(aiohttp_client):
    app = await create_app(ScannerConfig(top_n_coins=2))
    state = app["state"]
    state.client.get_top_futures_symbols = AsyncMock(return_value=["BTCUSDT", "ETHUSDT"])
    state.client.ticker_metrics = {
        "BTCUSDT": {"lastPrice": 60000.0, "priceChangePercent": 1.25, "quoteVolume": 1000.0},
        "ETHUSDT": {"lastPrice": 3000.0, "priceChangePercent": -0.5, "quoteVolume": 500.0},
    }
    client = await aiohttp_client(app)
    payload = await (await client.get("/api/symbols")).json()
    assert payload["symbols"] == ["BTCUSDT", "ETHUSDT"]
    assert payload["count"] == 2
    assert payload["tickers"]["BTCUSDT"]["lastPrice"] == 60000.0
    assert payload["tickers"]["ETHUSDT"]["priceChangePercent"] == -0.5


@pytest.mark.asyncio
async def test_api_symbols_failure_returns_empty_metrics(aiohttp_client):
    app = await create_app(ScannerConfig(top_n_coins=1))
    state = app["state"]
    state.client.get_top_futures_symbols = AsyncMock(return_value=[])
    state.client.ticker_metrics = {}
    client = await aiohttp_client(app)
    payload = await (await client.get("/api/symbols")).json()
    assert payload == {"symbols": [], "count": 0, "tickers": {}}


@pytest.mark.asyncio
async def test_api_status_exposes_configured_scan_interval(aiohttp_client):
    app = await create_app(ScannerConfig(top_n_coins=1, scan_interval_seconds=77))
    state = app["state"]
    state.client.get_top_futures_symbols = AsyncMock(return_value=["BTCUSDT"])
    state.client.ticker_metrics = {"BTCUSDT": {"lastPrice": 1, "priceChangePercent": 0, "quoteVolume": 1}}
    client = await aiohttp_client(app)
    payload = await (await client.get("/api/status")).json()
    assert payload["scan_interval_seconds"] == 77
    assert payload["status"] == "online"

@pytest.mark.asyncio
async def test_signal_stream_close_does_not_override_live_market_status(aiohttp_client):
    app = await create_app(ScannerConfig(top_n_coins=1))
    state = app["state"]
    state.client.get_top_futures_symbols = AsyncMock(return_value=["BTCUSDT"])
    state.client.ticker_metrics = {"BTCUSDT": {"lastPrice": 1, "priceChangePercent": 0, "quoteVolume": 1}}
    client = await aiohttp_client(app)
    payload = await (await client.get("/api/status")).json()
    assert payload["status"] == "online"
    assert payload["scan_interval_seconds"] == 300


@pytest.mark.asyncio
async def test_market_websocket_rejects_bad_timeframe_and_unknown_symbol(aiohttp_client):
    app = await create_app(ScannerConfig(top_n_coins=1))
    app["state"].top_symbols = ["BTCUSDT"]
    client = await aiohttp_client(app)
    for symbol, timeframe in (("BTCUSDT", "2m"), ("NOPEUSDT", "15m")):
        response = await client.get(f"/ws/market?symbol={symbol}&timeframe={timeframe}")
        assert response.status == 400
        assert (await response.json())["error"] == "invalid_subscription"


@pytest.mark.asyncio
async def test_market_websocket_marks_silent_upstream_stale(aiohttp_client):
    app = await create_app(ScannerConfig(top_n_coins=1))
    app["state"].top_symbols = ["BTCUSDT"]
    class SilentUpstream:
        close_code = 1000
        closed = False
        close = AsyncMock()
        async def receive(self):
            await asyncio.sleep(0.08)
            if not hasattr(self, "sent"):
                self.sent = True
                return type("WSMessage", (), {"type": WSMsgType.TEXT, "data": json.dumps(book_ticker_event())})()
            return type("WSMessage", (), {"type": WSMsgType.CLOSED, "data": ""})()
    upstream = SilentUpstream()
    with patch("server.connect_binance_ws", new=AsyncMock(return_value=upstream)), patch("server.MARKET_STALE_AFTER_SECONDS", 0.04, create=True), patch("server.MARKET_WS_POLL_SECONDS", 0.01, create=True):
        client = await aiohttp_client(app)
        ws = await client.ws_connect("/ws/market?symbol=BTCUSDT&timeframe=15m")
        states=[]
        for _ in range(8):
            message=await ws.receive_json(timeout=1)
            if message.get("type")=="status": states.append(message["state"])
            if message.get("type")=="price": break
        assert "stale" in states
        await ws.close()


@pytest.mark.asyncio
async def test_market_websocket_relays_bookticker_and_closes_upstream(aiohttp_client):
    app = await create_app(ScannerConfig(top_n_coins=1))
    state = app["state"]
    state.top_symbols = ["BTCUSDT"]
    class FakeUpstream:
        close_code = 1000
        closed = False
        close = AsyncMock()
        def __init__(self): self.messages = [
            type("WSMessage", (), {"type": WSMsgType.TEXT, "data": json.dumps(book_ticker_event())})(),
            type("WSMessage", (), {"type": WSMsgType.CLOSED, "data": ""})(),
        ]
        async def receive(self):
            await asyncio.sleep(0)
            return self.messages.pop(0) if self.messages else type("WSMessage", (), {"type": WSMsgType.CLOSED, "data": ""})()
    fake_upstream = FakeUpstream()
    with patch("server.connect_binance_ws", new=AsyncMock(return_value=fake_upstream)):
        client = await aiohttp_client(app)
        ws = await client.ws_connect("/ws/market?symbol=BTCUSDT&timeframe=15m")
        while True:
            message = await ws.receive_json(timeout=2)
            if message.get("type") == "price": break
        assert message["price"] == 11.0
        await ws.close()
        await asyncio.sleep(0)
        fake_upstream.close.assert_awaited()


@pytest.mark.asyncio
async def test_market_websocket_status_transitions(aiohttp_client):
    app = await create_app(ScannerConfig(top_n_coins=1))
    app["state"].top_symbols = ["BTCUSDT"]
    class PolicyCloseUpstream:
        close_code = 1008
        closed = False
        close = AsyncMock()
        async def receive(self):
            return type("WSMessage", (), {"type": WSMsgType.CLOSED, "data": ""})()
    fake_upstream = PolicyCloseUpstream()
    with patch("server.connect_binance_ws", new=AsyncMock(return_value=fake_upstream)):
        client = await aiohttp_client(app)
        ws = await client.ws_connect("/ws/market?symbol=BTCUSDT&timeframe=15m")
        states = []
        while True:
            item = await ws.receive_json(timeout=2)
            if item.get("type") == "status": states.append(item["state"])
            if item.get("state") == "error": break
        assert "connecting" in states and "connected" in states
        assert states[-1] == "error"
        await ws.close()


@pytest.mark.asyncio
async def test_dashboard_exposes_realtime_chart_controls(aiohttp_client):
    app = await create_app(ScannerConfig(top_n_coins=1))
    client = await aiohttp_client(app)
    body = await (await client.get("/")).text()
    assert "chart_stream.js" in body
    assert "ws/market" in body
    assert 'aria-label="Overlay controls"' in body
    assert "quoteVolume" in body
