import pytest
from aiohttp import web
from server import create_app
from config import ScannerConfig

@pytest.mark.asyncio
async def test_server_routes():
    config = ScannerConfig(top_n_coins=5, timeframe="15m")
    app = await create_app(config)
    assert app is not None

    # Test route definitions
    routes = [r.resource.canonical for r in app.router.routes() if hasattr(r, 'resource') and r.resource]
    assert "/api/status" in routes
    assert "/api/chart" in routes
    assert "/api/symbols" in routes


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
