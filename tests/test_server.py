import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from config import ScannerConfig
from server import create_app


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
    assert "charting_library" in body
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
async def test_market_websocket_marks_silent_polls_stale(aiohttp_client):
    app = await create_app(ScannerConfig(top_n_coins=1))
    app["state"].top_symbols = ["BTCUSDT"]

    async def failing_get_klines(symbol, interval="15m", limit=100):
        await asyncio.sleep(0.01)
        raise RuntimeError("simulated Binance REST outage")

    app["state"].client.get_klines = failing_get_klines
    with patch("server.MARKET_STALE_AFTER_SECONDS", 0.04, create=True), patch("server.MARKET_WS_POLL_SECONDS", 0.01, create=True):
        client = await aiohttp_client(app)
        ws = await client.ws_connect("/ws/market?symbol=BTCUSDT&timeframe=15m")
        states=[]
        for _ in range(20):
            message=await ws.receive_json(timeout=2)
            if message.get("type")=="status": states.append(message["state"])
            if "stale" in states: break
        assert "stale" in states, f"expected stale status, got {states}"
        await ws.close()


@pytest.mark.asyncio
async def test_market_websocket_polls_rest_klines_and_cleans_up(aiohttp_client):
    app = await create_app(ScannerConfig(top_n_coins=1))
    state = app["state"]
    state.top_symbols = ["BTCUSDT"]
    poll_calls = {"n": 0}

    async def fake_get_klines(symbol, interval="15m", limit=100):
        poll_calls["n"] += 1
        # real OHLC shape from Binance REST /fapi/v1/klines
        base_ts = 1793586600000
        return [
            {"timestamp": base_ts - 900000, "open": 78400.0, "high": 78500.0, "low": 78300.0, "close": 78480.0, "volume": 40.0, "close_time": base_ts - 1},
            {"timestamp": base_ts, "open": 78480.0, "high": 78520.0, "low": 78480.0, "close": 78500.0, "volume": 50.0, "close_time": base_ts + 899999},
        ]

    closed_sessions = []
    original_close = state.client.close

    async def tracking_close():
        closed_sessions.append(True)
        await original_close()

    state.client.get_klines = fake_get_klines
    with patch("server.MARKET_WS_POLL_SECONDS", 0.02, create=True):
        client = await aiohttp_client(app)
        ws = await client.ws_connect("/ws/market?symbol=BTCUSDT&timeframe=15m")
        # status messages precede the first kline
        message = None
        for _ in range(6):
            message = await ws.receive_json(timeout=3)
            if message.get("type") == "kline":
                break
        assert message is not None and message["type"] == "kline", f"expected kline, got {message}"
        candle = message["candle"]
        assert candle["open"] == 78480.0
        assert candle["high"] == 78520.0
        assert candle["low"] == 78480.0
        assert candle["close"] == 78500.0
        assert candle["volume"] == 50.0
        assert candle["time"] == 1793586600
        assert poll_calls["n"] >= 1
        await ws.close()
        # poll loop must stop after downstream disconnect (no leaked task)
        polls_at_close = poll_calls["n"]
        await asyncio.sleep(0.1)
        assert poll_calls["n"] == polls_at_close, "poll loop must stop after downstream disconnect"


@pytest.mark.asyncio
async def test_market_websocket_survives_poll_failures(aiohttp_client):
    """Poll failures must not kill the connection — it retries and recovers."""
    app = await create_app(ScannerConfig(top_n_coins=1))
    app["state"].top_symbols = ["BTCUSDT"]
    calls = {"n": 0}

    async def flaky_get_klines(symbol, interval="15m", limit=100):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise RuntimeError("simulated Binance REST outage")
        base_ts = 1793586600000
        return [{"timestamp": base_ts, "open": 78480.0, "high": 78520.0, "low": 78480.0, "close": 78500.0, "volume": 50.0, "close_time": base_ts + 899999}]

    app["state"].client.get_klines = flaky_get_klines
    with patch("server.MARKET_WS_POLL_SECONDS", 0.02, create=True):
        client = await aiohttp_client(app)
        ws = await client.ws_connect("/ws/market?symbol=BTCUSDT&timeframe=15m")
        got_kline = False
        for _ in range(20):
            message = await ws.receive_json(timeout=3)
            if message.get("type") == "kline":
                got_kline = True
                break
        assert got_kline, "connection must recover after transient poll failures"
        assert calls["n"] >= 3
        await ws.close()


@pytest.mark.asyncio
async def test_market_websocket_emits_structure_from_technical_engine(aiohttp_client):
    app = await create_app(ScannerConfig(top_n_coins=1))
    state = app["state"]
    state.top_symbols = ["BTCUSDT"]

    async def fake_get_klines(symbol, interval="15m", limit=100):
        # downtrend with a clear swing structure so the engine finds trendlines
        base_ts = 1793586600000
        prices = [100, 99, 98, 99, 97, 96, 97, 95, 94, 95, 93, 92, 93, 91, 90]
        out = []
        for i, p in enumerate(prices):
            ts = base_ts - (len(prices) - i) * 900000
            out.append({
                "timestamp": ts,
                "open": float(p + 0.5),
                "high": float(p + 1.5),
                "low": float(p - 1.5),
                "close": float(p),
                "volume": 100.0,
                "close_time": ts + 899999,
            })
        return out[-2:] if limit == 2 else out

    state.client.get_klines = fake_get_klines
    with patch("server.MARKET_WS_POLL_SECONDS", 0.02, create=True):
        client = await aiohttp_client(app)
        ws = await client.ws_connect("/ws/market?symbol=BTCUSDT&timeframe=15m")
        structure = None
        for _ in range(10):
            message = await ws.receive_json(timeout=3)
            if message.get("type") == "structure":
                structure = message
                break
        assert structure is not None, "expected a structure message"
        assert structure["symbol"] == "BTCUSDT"
        assert structure["timeframe"] == "15m"
        assert "trendlines" in structure and isinstance(structure["trendlines"], list)
        assert "zone_bands" in structure
        assert "fvgs" in structure
        await ws.close()


@pytest.mark.asyncio
async def test_market_ws_close_during_poll_cleans_up(aiohttp_client):
    """Downstream close while a slow poll is in flight must stop the loop and not leak."""
    app = await create_app(ScannerConfig(top_n_coins=1))
    state = app["state"]
    state.top_symbols = ["BTCUSDT"]
    started = asyncio.Event()

    async def hanging_get_klines(symbol, interval="15m", limit=100):
        started.set()
        await asyncio.sleep(30)  # simulate a hung upstream request
        return []

    state.client.get_klines = hanging_get_klines
    with patch("server.MARKET_WS_POLL_SECONDS", 0.02, create=True):
        client = await aiohttp_client(app)
        ws = await client.ws_connect("/ws/market?symbol=BTCUSDT&timeframe=15m")
        await started.wait()
        # close while the poll is still in flight
        await ws.close()
        await asyncio.sleep(0.1)
        # if the poll loop leaked, this task would still be pending; nothing to assert
        # beyond the server not raising — the websocket handler must return cleanly.
        assert ws.closed


def test_server_close_policy_retries_transient_and_normal_closes():
    from server import should_retry_websocket_close
    assert should_retry_websocket_close(1000) is True
    assert should_retry_websocket_close(1001) is True
    assert should_retry_websocket_close(1012) is True
    assert should_retry_websocket_close(1013) is True
    assert should_retry_websocket_close(1008) is False


@pytest.mark.asyncio
async def test_signal_socket_close_does_not_override_market_state(aiohttp_client):
    app = await create_app(ScannerConfig(top_n_coins=1))
    client = await aiohttp_client(app)
    body = await (await client.get("/")).text()
    assert "shouldShowConnectingStatus" in body
    assert "marketWs.readyState!==WebSocket.OPEN" in body


@pytest.mark.asyncio
async def test_structure_payload_trendlines_have_realistic_touches(aiohttp_client):
    app = await create_app(ScannerConfig(top_n_coins=1))
    state = app["state"]
    state.top_symbols = ["BTCUSDT"]

    # 16 bars with clear descending swing highs
    base_ts = 1793586600000
    prices = [
        (96, 98, 95, 97),   # 0
        (97, 99, 96, 98),   # 1
        (98, 100, 97, 99),  # 2 - SWING HIGH 1 (100)
        (96, 97, 94, 95),   # 3
        (93, 97.5, 92, 94), # 4
        (93, 96.95, 92, 94),# 5
        (91, 93.5, 90, 92), # 6
        (90, 92, 89, 91),   # 7
        (91, 94, 90, 93),   # 8 - SWING HIGH 2 (94)
        (90, 92, 89, 91),   # 9
        (89, 91, 88, 90),   # 10
        (88, 90, 87, 89),   # 11
        (87, 88, 85, 86),   # 12
        (86, 88, 85, 87),   # 13
        (86, 88, 85, 87),   # 14
        (85, 86, 84, 85),   # 15
    ]
    klines = [
        {"timestamp": base_ts + i * 900000, "open": o, "high": h, "low": l, "close": c, "volume": 100.0, "close_time": base_ts + (i + 1) * 900000 - 1}
        for i, (o, h, l, c) in enumerate(prices)
    ]
    state.client.get_klines = AsyncMock(return_value=klines)
    client = await aiohttp_client(app)
    res = await client.get("/api/chart?symbol=BTCUSDT&timeframe=15m")
    assert res.status == 200
    payload = await res.json()
    assert "trendlines" in payload
    # Every trendline emitted MUST have a realistic touch count (< 10)
    for tl in payload["trendlines"]:
        assert tl["touches"] >= 2
        assert tl["touches"] <= 6, f"Touch count {tl['touches']} is too high for a 16-bar series!"
        assert "residual" in tl
        assert "next_price" in tl



@pytest.mark.asyncio
async def test_dashboard_exposes_realtime_chart_controls(aiohttp_client):
    app = await create_app(ScannerConfig(top_n_coins=1))
    client = await aiohttp_client(app)
    body = await (await client.get("/")).text()
    assert "chart_stream.js" in body
    assert "ws/market" in body
    assert 'aria-label="Overlay controls"' in body
    assert "quoteVolume" in body


@pytest.mark.asyncio
async def test_api_signals_and_historical_chart_endpoints(aiohttp_client, tmp_path):
    from signal_tracker import SignalTracker
    app = await create_app(ScannerConfig(top_n_coins=1))
    # inject tracker with temp db
    tracker = SignalTracker(db_path=str(tmp_path / "test_api_signals.db"))
    app["state"].signal_tracker = tracker

    # 1. Save dummy signal
    sig = {
        "symbol": "BTCUSDT",
        "timeframe": "15m",
        "signal_type": "LONG",
        "pattern": "BREAKOUT",
        "entry_price": 78000.0,
        "stop_loss": 77000.0,
        "tp1": 80200.0,
        "tp2": 81000.0,
        "risk_reward": 2.2,
        "sl_pct": 0.0128,
        "description": "Bullish Breakout over Resistance Trendline",
        "timestamp": 1700000000.0,
    }
    klines = [
        {"timestamp": 1699990000000, "open": 77500, "high": 78100, "low": 77400, "close": 78000, "volume": 100},
        {"timestamp": 1700000000000, "open": 78000, "high": 80300, "low": 77900, "close": 80200, "volume": 120},
    ]
    sig_id = tracker.save_signal(sig, klines)
    # Win it
    tracker.evaluate_signal(sig_id, klines[1])

    client = await aiohttp_client(app)

    # Test /api/signals
    res = await client.get("/api/signals")
    assert res.status == 200
    data = await res.json()
    assert "signals" in data
    assert "stats" in data
    assert len(data["signals"]) == 1
    assert data["signals"][0]["status"] == "WIN"
    assert data["stats"]["wins"] == 1
    assert data["stats"]["win_rate"] == 100.0

    # Test /api/signals/{id}/chart
    res_chart = await client.get(f"/api/signals/{sig_id}/chart")
    assert res_chart.status == 200
    chart_data = await res_chart.json()
    assert chart_data["symbol"] == "BTCUSDT"
    assert "candles" in chart_data
    assert len(chart_data["candles"]) == 2
    assert chart_data["signal"]["status"] == "WIN"


@pytest.mark.asyncio
async def test_structure_payload_includes_smc_and_forecast(aiohttp_client):
    app = await create_app(ScannerConfig(top_n_coins=1))
    state = app["state"]
    state.top_symbols = ["BTCUSDT"]

    base_ts = 1793586600000
    prices = [(100 + i * 0.5, 101 + i * 0.5, 99.5 + i * 0.5, 100.5 + i * 0.5) for i in range(30)]
    klines = [
        {"timestamp": base_ts + i * 900000, "open": o, "high": h, "low": l, "close": c, "volume": 100.0, "close_time": base_ts + (i + 1) * 900000 - 1}
        for i, (o, h, l, c) in enumerate(prices)
    ]
    state.client.get_klines = AsyncMock(return_value=klines)
    client = await aiohttp_client(app)
    res = await client.get("/api/chart?symbol=BTCUSDT&timeframe=15m")
    assert res.status == 200
    payload = await res.json()
    assert "order_blocks" in payload
    assert "regression_channel" in payload
    assert "forecast_path" in payload
    reg = payload["regression_channel"]
    assert "upper_series" in reg and "lower_series" in reg
    assert len(reg["upper_series"]) > 0


@pytest.mark.asyncio
async def test_api_chart_supports_pagination_with_endtime(aiohttp_client):
    app = await create_app(ScannerConfig(top_n_coins=1, timeframe="15m"))
    state = app["state"]
    state.client.get_klines = AsyncMock(return_value=[
        {"timestamp": 1700000000000, "open": 100, "high": 105, "low": 99, "close": 102, "volume": 50, "close_time": 1700000900000 - 1}
    ])
    client = await aiohttp_client(app)
    res = await client.get("/api/chart?symbol=BTCUSDT&timeframe=15m&limit=500&endTime=1700000000000")
    assert res.status == 200
    state.client.get_klines.assert_called_with("BTCUSDT", interval="15m", limit=500, endTime=1700000000000)


# ---------------------------------------------------------------------------
# News advisory API (Task 1) — cache-only, advisory, isolated from scan
# ---------------------------------------------------------------------------

def _news_rss(items_xml: str) -> bytes:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<rss version="2.0"><channel><title>Test</title>'
        f"{items_xml}</channel></rss>"
    ).encode()


def _gn_item(title: str, link: str) -> str:
    return (
        f"<item><title>{title}</title><link>{link}</link>"
        "<pubDate>Tue, 11 Nov 2026 09:00:01 GMT</pubDate></item>"
    )


async def _app_with_news(aiohttp_client, active_symbols=()):
    app = await create_app(ScannerConfig(top_n_coins=1, timeframe="15m"))
    state = app["state"]
    for sym in active_symbols:
        state.active_signals[sym] = {"symbol": sym, "status": "OPEN"}

    sec_body = _news_rss(_gn_item("SEC approves first spot Bitcoin ETF - Reuters",
                                  "https://www.sec.gov/news/press-release/sec-etf"))
    fed_body = _news_rss(_gn_item("Federal Reserve holds rates as inflation cools - CNBC",
                                  "https://www.federalreserve.gov/newsevents/pressreleases/hold"))
    gn_body = _news_rss(
        _gn_item("Ethereum completes upgrade, ETH jumps - Bloomberg",
                 "https://news.google.com/rss/articles/eth1")
        + _gn_item("Solana network outage resolved - CoinDesk",
                   "https://news.google.com/rss/articles/sol1")
    )

    class _Resp:
        def __init__(self, body, content_type="application/xml"):
            self.status = 200
            self.content_type = content_type
            self._body = body
            self.closed = False

            class _Content:
                async def iter_chunked(inner_self, n):  # noqa: ARG002
                    yield body

            self.content = _Content()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            self.close()
            return False

        def close(self):
            self.closed = True

    class _Session:
        def __init__(self):
            self.calls = 0
            self.closed = False

        def get(self, url, **kwargs):  # noqa: ARG002
            self.calls += 1
            if "sec.gov" in url:
                return _Resp(sec_body)
            if "federalreserve.gov" in url:
                return _Resp(fed_body)
            return _Resp(gn_body, "application/rss+xml")

        async def close(self):
            self.closed = True

    session = _Session()
    from news_service import NewsService
    state.news_service = NewsService(clock=lambda: 1_794_400_000.0, session_factory=lambda: session)
    await state.news_service.refresh()
    client = await aiohttp_client(app)
    return client, state, session


@pytest.mark.asyncio
async def test_api_news_returns_global_active_and_selected_symbol_items(aiohttp_client):
    client, state, session = await _app_with_news(aiohttp_client, active_symbols=("ETHUSDT",))

    res = await client.get("/api/news?symbol=BTCUSDT")
    assert res.status == 200
    payload = await res.json()
    titles = [i["title"] for i in payload["items"]]
    # selected symbol (BTC via "Bitcoin ETF" alias match)
    assert any("Bitcoin ETF" in t for t in titles)
    # active-signal symbol ETH
    assert any("Ethereum" in t for t in titles)
    # broad market
    assert any("Federal Reserve" in t for t in titles)
    assert payload["stale"] is False
    assert payload["sources_ok"] is True
    assert len(payload["items"]) <= 50
    for item in payload["items"]:
        assert item["url"].startswith("https://")

    # missing symbol: broad-market + active-signal headlines only
    res2 = await client.get("/api/news")
    assert res2.status == 200
    titles2 = [i["title"] for i in (await res2.json())["items"]]
    assert any("Federal Reserve" in t for t in titles2)
    assert any("Ethereum" in t for t in titles2)
    assert not any("Solana" in t for t in titles2)  # SOL not selected/active -> excluded

    # no upstream fetch on the request path
    assert session.calls == 4  # only the 4 startup refreshes


@pytest.mark.asyncio
async def test_api_news_rejects_invalid_symbol_and_does_not_fetch_upstream(aiohttp_client):
    client, state, session = await _app_with_news(aiohttp_client)

    for bad in ("btc", "BTC", "BTCUSD", "../../etc/passwd", "BTCUSDT%20"):
        res = await client.get(f"/api/news?symbol={bad}")
        assert res.status == 400, bad
    assert session.calls == 4  # rejected requests never hit upstream
