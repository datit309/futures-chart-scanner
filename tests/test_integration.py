import pytest
from unittest.mock import patch, AsyncMock
from config import ScannerConfig
from technical_engine import MarketSignal, PatternType
from risk_manager import EnrichedSignal
from telegram_notifier import TelegramNotifier
from main import ScannerPipeline
import config as app_config

@pytest.mark.asyncio
async def test_telegram_notifier_send_photo():
    notifier = TelegramNotifier(bot_token="mock_token", chat_id="mock_chat")
    
    with patch("aiohttp.ClientSession.post") as mock_post:
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value={"ok": True})
        mock_post.return_value.__aenter__.return_value = mock_resp

        success = await notifier.send_chart_alert(
            photo_bytes=b"\x89PNG\r\n\x1a\nfakecontent",
            caption="Test Caption"
        )
        assert success is True

@pytest.mark.asyncio
async def test_pipeline_scans_only_trusted_symbols():
    trusted = getattr(app_config, "TRUSTED_SYMBOLS", None)
    assert trusted == ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT")
    pipeline = ScannerPipeline(ScannerConfig())
    visited = []
    async def fail_dynamic_selector(*args, **kwargs):
        raise AssertionError("standalone scanner must not use dynamic quote-volume ranking")
    pipeline.client.get_top_futures_symbols = fail_dynamic_selector
    async def fake_scan(symbol, save_dir=None):
        visited.append(symbol)
        return None
    pipeline.scan_single_symbol = fake_scan
    await pipeline.scan_cycle(save_dir=None)
    assert visited == list(trusted)


@pytest.mark.asyncio
async def test_non_whitelist_open_signals_hidden_from_live_state_but_visible_in_history(tmp_path):
    from signal_tracker import SignalTracker
    from server import create_app, filter_live_signals
    from config import TRUSTED_SYMBOLS, ScannerConfig
    app = await create_app(ScannerConfig())
    state = app["state"]
    tracker = SignalTracker(db_path=str(tmp_path / "legacy_open.db"))
    state.signal_tracker = tracker
    for symbol in [*TRUSTED_SYMBOLS[:1], "DOGEUSDT"]:
        tracker.save_signal({
            "symbol": symbol, "timeframe": "15m", "signal_type": "LONG", "pattern": "BREAKOUT",
            "entry_price": 1.0, "stop_loss": 0.9, "take_profit": 1.2, "risk_reward": 2.0,
            "description": "test", "timestamp": 1700000000,
        })
    state.active_signals = filter_live_signals(tracker.list_signals(status_filter="OPEN", limit=100))
    assert set(state.active_signals) == {TRUSTED_SYMBOLS[0]}
    assert any(s["symbol"] == "DOGEUSDT" for s in tracker.list_signals(status_filter="OPEN"))


@pytest.mark.asyncio
async def test_standalone_single_symbol_scan_rejects_untrusted_coin():
    pipeline = ScannerPipeline(ScannerConfig())
    pipeline.client.get_klines = AsyncMock(side_effect=AssertionError("must reject before market-data fetch"))
    result = await pipeline.scan_single_symbol("DOGEUSDT")
    assert result is None
    pipeline.client.get_klines.assert_not_called()


@pytest.mark.asyncio
async def test_scanner_pipeline_cycle():
    config = ScannerConfig(top_n_coins=2, timeframe="15m")
    pipeline = ScannerPipeline(config)

    # Mock top symbols
    with patch.object(pipeline.client, "get_top_futures_symbols", AsyncMock(return_value=["BTCUSDT", "ETHUSDT"])):
        # Mock klines with a breakout structure
        base_ts = 1700000000000
        mock_klines = []
        for i in range(15):
            mock_klines.append({
                "timestamp": base_ts + i * 900000,
                "open": 60000.0 + i * 10,
                "high": 60050.0 + i * 10,
                "low": 59950.0 + i * 10,
                "close": 60020.0 + i * 10,
                "volume": 200.0,
                "close_time": base_ts + (i + 1) * 900000 - 1
            })

        with patch.object(pipeline.client, "get_klines", AsyncMock(return_value=mock_klines)):
            # Mock technical engine finding a signal
            mock_raw_signal = MarketSignal(
                symbol="BTCUSDT",
                timeframe="15m",
                signal_type="LONG",
                pattern=PatternType.TRENDLINE_BREAKOUT,
                entry_price=60100.0,
                stop_loss=59600.0,
                take_profit=61350.0,
                risk_reward=2.5,
                description="Test Breakout"
            )

            mock_signal = EnrichedSignal(
                symbol="BTCUSDT",
                timeframe="15m",
                signal_type="LONG",
                pattern=PatternType.TRENDLINE_BREAKOUT,
                entry_price=60100.0,
                stop_loss=59600.0,
                take_profit=61350.0,
                risk_reward=2.5,
                description="Test Breakout",
                extra_targets={"tp1": 60850.0, "tp2": 61350.0},
                sl_pct=0.008
            )

            with patch.object(pipeline.technical_engine, "analyze_market", return_value=[mock_raw_signal]):
                with patch.object(pipeline.risk_manager, "validate_and_enrich", return_value=mock_signal):
                    with patch.object(pipeline.notifier, "send_chart_alert", AsyncMock(return_value=True)):
                        alerts = await pipeline.scan_cycle(save_dir=None)
                        assert len(alerts) >= 1
                        assert alerts[0].symbol == "BTCUSDT"
                        assert alerts[0].risk_reward >= 2.0
