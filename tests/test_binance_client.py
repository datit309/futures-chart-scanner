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
    exchange_info = {"symbols": [
        {"symbol": "BTCUSDT", "quoteAsset": "USDT", "status": "TRADING", "contractType": "PERPETUAL"},
        {"symbol": "ETHUSDT", "quoteAsset": "USDT", "status": "TRADING", "contractType": "PERPETUAL"},
        {"symbol": "SOLUSDT", "quoteAsset": "USDT", "status": "TRADING", "contractType": "PERPETUAL"},
        {"symbol": "1000PEPEUSDT", "quoteAsset": "USDT", "status": "TRADING", "contractType": "PERPETUAL"},
        {"symbol": "BTCBUSD", "quoteAsset": "BUSD", "status": "TRADING", "contractType": "PERPETUAL"},
    ]}
    mock_tickers = [
        {"symbol": "BTCUSDT", "quoteVolume": "1000000000.0"},
        {"symbol": "ETHUSDT", "quoteVolume": "500000000.0"},
        {"symbol": "SOLUSDT", "quoteVolume": "300000000.0"},
        {"symbol": "1000PEPEUSDT", "quoteVolume": "200000000.0"},
        {"symbol": "BTCBUSD", "quoteVolume": "999999999.0"},
    ]
    with patch.object(client, "_fetch_json", side_effect=[exchange_info, mock_tickers]):
        top_symbols = await client.get_top_futures_symbols(limit=3)
        assert top_symbols == ["BTCUSDT", "ETHUSDT", "SOLUSDT"]

@pytest.mark.asyncio
async def test_top_symbols_filters_contracts_and_merges_tickers():
    client = BinanceClient()
    exchange_info = {
        "symbols": [
            {"symbol": "BTCUSDT", "status": "TRADING", "contractType": "PERPETUAL", "quoteAsset": "USDT"},
            {"symbol": "OLDUSDT", "status": "BREAK", "contractType": "PERPETUAL", "quoteAsset": "USDT"},
            {"symbol": "BTCUSDT_260101", "status": "TRADING", "contractType": "CURRENT_QUARTER", "quoteAsset": "USDT"},
            {"symbol": "ETHBUSD", "status": "TRADING", "contractType": "PERPETUAL", "quoteAsset": "BUSD"},
            {"symbol": "ETHUSDT", "status": "TRADING", "contractType": "PERPETUAL", "quoteAsset": "USDT"},
        ]
    }
    tickers = [
        {"symbol": "BTCUSDT", "lastPrice": "60000", "priceChangePercent": "1.25", "quoteVolume": "1000"},
        # ETHUSDT deliberately has no ticker row: it stays in universe with safe empty metrics.
        {"symbol": "OLDUSDT", "lastPrice": "1", "priceChangePercent": "0", "quoteVolume": "9999"},
    ]
    responses = [exchange_info, tickers]
    async def fake_fetch(url, params=None):
        return responses.pop(0)
    with patch.object(client, "_fetch_json", side_effect=fake_fetch):
        result = await client.get_top_futures_symbols(limit=10)
    assert result == ["BTCUSDT", "ETHUSDT"]
    assert client.ticker_metrics["BTCUSDT"] == {
        "lastPrice": 60000.0,
        "priceChangePercent": 1.25,
        "quoteVolume": 1000.0,
    }
    assert client.ticker_metrics["ETHUSDT"] == {
        "lastPrice": 0.0,
        "priceChangePercent": 0.0,
        "quoteVolume": 0.0,
    }

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


@pytest.mark.asyncio
async def test_get_open_interest_and_funding_rate():
    client = BinanceClient()
    with patch.object(client, "_fetch_json", return_value={"symbol": "BTCUSDT", "openInterest": "54231.543"}):
        oi = await client.get_open_interest("BTCUSDT")
        assert oi == 54231.543

    with patch.object(client, "_fetch_json", return_value={"symbol": "BTCUSDT", "lastFundingRate": "0.00010000"}):
        fr = await client.get_funding_rate("BTCUSDT")
        assert fr == 0.0001

