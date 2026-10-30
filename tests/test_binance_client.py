import pytest
import asyncio
from unittest.mock import patch, MagicMock
from config import ScannerConfig
from binance_client import BinanceClient

def test_config_defaults():
    config = ScannerConfig()
    assert config.timeframe == "15m"
    assert config.top_n_coins == 30
    assert config.min_rr == 2.0
    assert config.min_trendline_touches == 3

def test_config_from_dict():
    data = {
        "telegram_bot_token": "test_token",
        "telegram_chat_id": "test_chat",
        "timeframe": "1h",
        "top_n_coins": 10,
        "min_rr": 2.5
    }
    config = ScannerConfig.from_dict(data)
    assert config.telegram_bot_token == "test_token"
    assert config.telegram_chat_id == "test_chat"
    assert config.timeframe == "1h"
    assert config.top_n_coins == 10
    assert config.min_rr == 2.5

@pytest.mark.asyncio
async def test_get_top_futures_symbols():
    client = BinanceClient()
    mock_tickers = [
        {"symbol": "BTCUSDT", "quoteVolume": "1000000000.0"},
        {"symbol": "ETHUSDT", "quoteVolume": "500000000.0"},
        {"symbol": "SOLUSDT", "quoteVolume": "300000000.0"},
        {"symbol": "1000PEPEUSDT", "quoteVolume": "200000000.0"},
        {"symbol": "BTCBUSD", "quoteVolume": "999999999.0"},  # Should be filtered out if not USDT
    ]

    with patch.object(client, "_fetch_json", return_value=mock_tickers):
        top_symbols = await client.get_top_futures_symbols(limit=3)
        assert top_symbols == ["BTCUSDT", "ETHUSDT", "SOLUSDT"]

@pytest.mark.asyncio
async def test_get_klines():
    client = BinanceClient()
    # Sample Binance Kline format: [open_time, open, high, low, close, volume, close_time, ...]
    mock_raw_klines = [
        [1700000000000, "65000.0", "65500.0", "64900.0", "65200.0", "120.5", 1700000899999],
        [1700000900000, "65200.0", "65600.0", "65100.0", "65400.0", "150.2", 1700001799999]
    ]

    with patch.object(client, "_fetch_json", return_value=mock_raw_klines):
        klines = await client.get_klines("BTCUSDT", interval="15m", limit=2)
        assert len(klines) == 2
        assert klines[0]["timestamp"] == 1700000000000
        assert klines[0]["open"] == 65000.0
        assert klines[0]["high"] == 65500.0
        assert klines[0]["low"] == 64900.0
        assert klines[0]["close"] == 65200.0
        assert klines[0]["volume"] == 120.5
