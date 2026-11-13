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


@pytest.mark.asyncio
async def test_aggregate_trades_page_one_uses_time_boundary():
    client = BinanceClient()
    start_ms, end_ms = 1000, 9000
    page = [{"a": 10, "p": "100.5", "q": "2.0", "T": 1000, "m": False}]
    with patch.object(client, "_fetch_json", return_value=page) as fetch:
        result = await client.get_aggregate_trades("BTCUSDT", start_ms, end_ms)
    assert fetch.call_count == 1
    assert fetch.call_args.args[0].endswith("/fapi/v1/aggTrades")
    assert fetch.call_args.kwargs["params"] == {"symbol": "BTCUSDT", "startTime": start_ms, "endTime": end_ms, "limit": 1000}
    assert result["trades"] == [{"id": 10, "price": 100.5, "quantity": 2.0, "timestamp": 1000}]
    assert result["start_covered"] is True
    assert result["partial"] is False


@pytest.mark.asyncio
async def test_aggregate_trades_start_uncovered_marks_partial():
    client = BinanceClient()
    start_ms, end_ms = 1000, 9000
    page = [{"a": 10, "p": "100.5", "q": "2.0", "T": 2000, "m": False}]
    with patch.object(client, "_fetch_json", return_value=page):
        result = await client.get_aggregate_trades("BTCUSDT", start_ms, end_ms, start_boundary_tolerance_ms=300)
    assert result["partial"] is True
    assert result["partial_reason"] == "start_uncovered"
    assert result["start_covered"] is False


@pytest.mark.asyncio
async def test_aggregate_trades_followup_uses_from_id_only_and_dedupes_boundary():
    client = BinanceClient()
    start_ms, end_ms = 1000, 3000
    pages = [
        [{"a": 10, "p": "100", "q": "1", "T": 1000}, {"a": 11, "p": "101", "q": "2", "T": 1500}, {"a": 12, "p": "102", "q": "3", "T": 2000}],
        [{"a": 12, "p": "102", "q": "3", "T": 2000}, {"a": 13, "p": "103", "q": "4", "T": 2200}, {"a": 14, "p": "104", "q": "5", "T": 2500}],
        [],
    ]
    with patch.object(client, "_fetch_json", side_effect=pages) as fetch:
        result = await client.get_aggregate_trades("BTCUSDT", start_ms, end_ms, page_size=3, min_request_interval=0)
    assert fetch.call_count == 3
    assert fetch.call_args_list[0].kwargs["params"] == {"symbol": "BTCUSDT", "startTime": start_ms, "endTime": end_ms, "limit": 3}
    assert fetch.call_args_list[1].kwargs["params"] == {"symbol": "BTCUSDT", "fromId": 13, "limit": 3}
    assert fetch.call_args_list[2].kwargs["params"] == {"symbol": "BTCUSDT", "fromId": 15, "limit": 3}
    assert [t["id"] for t in result["trades"]] == [10, 11, 12, 13, 14]
    assert result["caught_up"] is True
    assert result["partial"] is False


@pytest.mark.asyncio
async def test_aggregate_trades_short_page_after_start_is_caught_up():
    client = BinanceClient()
    page = [{"a": 2, "p": "101", "q": "1", "T": 2000}]
    with patch.object(client, "_fetch_json", return_value=page):
        result = await client.get_aggregate_trades("BTCUSDT", 2000, 9000)
    assert result["start_covered"] is True
    assert result["caught_up"] is True
    assert result["partial"] is False


@pytest.mark.asyncio
async def test_aggregate_trades_empty_start_window_is_complete_empty():
    client = BinanceClient()
    with patch.object(client, "_fetch_json", return_value=[]):
        result = await client.get_aggregate_trades("BTCUSDT", 1000, 9000)
    assert result["trades"] == []
    assert result["start_covered"] is False
    assert result["caught_up"] is True
    assert result["partial"] is True
    assert result["partial_reason"] == "start_uncovered"


@pytest.mark.asyncio
async def test_aggregate_trades_page_cap_sets_partial_with_coverage():
    client = BinanceClient()
    pages = [
        [{"a": 10, "p": "100", "q": "1", "T": 1000}, {"a": 11, "p": "100", "q": "1", "T": 1001}, {"a": 12, "p": "100", "q": "1", "T": 1002}],
        [{"a": 13, "p": "100", "q": "1", "T": 1003}, {"a": 14, "p": "100", "q": "1", "T": 1004}, {"a": 15, "p": "100", "q": "1", "T": 1005}],
        [{"a": 16, "p": "100", "q": "1", "T": 1006}, {"a": 17, "p": "100", "q": "1", "T": 1007}, {"a": 18, "p": "100", "q": "1", "T": 1008}],
    ]
    with patch.object(client, "_fetch_json", side_effect=pages) as fetch:
        result = await client.get_aggregate_trades("BTCUSDT", 1000, 9000, page_cap=3, page_size=3)
    assert fetch.call_count == 3
    assert result["pages"] == 3
    assert result["partial"] is True
    assert result["partial_reason"] == "page_cap"


@pytest.mark.asyncio
async def test_aggregate_trades_repeated_or_backwards_cursor_sets_no_progress():
    client = BinanceClient()
    first = [{"a": 10, "p": "100", "q": "1", "T": 1000}, {"a": 11, "p": "101", "q": "1", "T": 1100}]
    repeated = [{"a": 10, "p": "100", "q": "1", "T": 1000}, {"a": 11, "p": "101", "q": "1", "T": 1100}]
    with patch.object(client, "_fetch_json", side_effect=[first, repeated]):
        result = await client.get_aggregate_trades("BTCUSDT", 1000, 9000, page_size=2, min_request_interval=0)
    assert result["partial"] is True
    assert result["partial_reason"] == "no_progress"
    assert len(result["trades"]) == 2


@pytest.mark.asyncio
async def test_aggregate_trades_malformed_rows_are_dropped_and_mark_partial():
    client = BinanceClient()
    page = [
        {"a": 10, "p": "100", "q": "1", "T": 1000},
        {"a": 11, "p": "NaN", "q": "2", "T": 1200},
    ]
    with patch.object(client, "_fetch_json", return_value=page):
        result = await client.get_aggregate_trades("BTCUSDT", 1000, 9000)
    assert len(result["trades"]) == 1
    assert result["partial"] is True
    assert result["partial_reason"] == "malformed_rows"


@pytest.mark.asyncio
async def test_aggregate_trades_deadline_marks_timeout_partial():
    client = BinanceClient()
    page = [
        {"a": 10, "p": "100", "q": "1", "T": 1000},
        {"a": 11, "p": "100", "q": "1", "T": 1100},
    ]
    with patch.object(client, "_fetch_json", side_effect=[page, asyncio.TimeoutError()]):
        result = await client.get_aggregate_trades("BTCUSDT", 1000, 9000, page_size=2, min_request_interval=0)
    assert result["partial"] is True
    assert result["partial_reason"] == "timeout"
    assert len(result["trades"]) == 2


@pytest.mark.asyncio
async def test_aggregate_trades_retries_429_twice_then_returns_partial():
    import aiohttp
    client = BinanceClient()
    response = aiohttp.ClientResponseError(request_info=None, history=(), status=429, message="rate limited")
    with patch.object(client, "_fetch_json", side_effect=[response, response, response]) as fetch:
        result = await client.get_aggregate_trades("BTCUSDT", 1000, 9000, retry_base_seconds=0, min_request_interval=0)
    assert fetch.call_count == 3
    assert result["partial"] is True
    assert result["partial_reason"] == "upstream_error"


@pytest.mark.asyncio
async def test_aggregate_trades_honors_retry_after_with_two_second_cap():
    import aiohttp
    from unittest.mock import AsyncMock
    client = BinanceClient()
    first_error = aiohttp.ClientResponseError(request_info=None, history=(), status=429, message="rate limited", headers={"Retry-After": "9"})
    success = [{"a": 10, "p": "100", "q": "1", "T": 1000}]
    with patch.object(client, "_fetch_json", side_effect=[first_error, success]) as fetch, patch("binance_client.asyncio.sleep", new=AsyncMock()) as sleep:
        result = await client.get_aggregate_trades("BTCUSDT", 1000, 9000, min_request_interval=0)
    assert fetch.call_count == 2
    assert sleep.await_args.args[0] == 2.0, "Retry-After must be honored but clamped to 2 seconds"
    assert result["caught_up"] is True


@pytest.mark.asyncio
async def test_aggregate_trades_deadline_includes_semaphore_wait():
    client = BinanceClient()
    page = [{"a": 10, "p": "100", "q": "1", "T": 1000}]
    await client._aggtrades_semaphore.acquire()
    with patch.object(client, "_fetch_json", return_value=page) as fetch:
        task = asyncio.create_task(client.get_aggregate_trades("BTCUSDT", 1000, 9000, timeout_seconds=0.01))
        await asyncio.sleep(0.06)  # implementation enforces a 50ms minimum total deadline
        client._aggtrades_semaphore.release()
        result = await task
    fetch.assert_not_called()
    assert result["partial"] is True
    assert result["partial_reason"] == "timeout"


@pytest.mark.asyncio
async def test_aggregate_trades_400_is_not_retried():
    import aiohttp
    client = BinanceClient()
    response = aiohttp.ClientResponseError(request_info=None, history=(), status=400, message="bad request")
    with patch.object(client, "_fetch_json", side_effect=response) as fetch:
        result = await client.get_aggregate_trades("BTCUSDT", 1000, 9000, min_request_interval=0)
    assert fetch.call_count == 1
    assert result["partial"] is True
    assert result["partial_reason"] == "upstream_error"


@pytest.mark.asyncio
async def test_get_aggregate_trades_rejects_invalid_symbol_without_network():
    client = BinanceClient()
    with patch.object(client, "_fetch_json") as fetch:
        with pytest.raises(ValueError):
            await client.get_aggregate_trades("https://evil.example/", 1000, 9000)
    fetch.assert_not_called()

