import os
import json
import pytest
from signal_tracker import SignalTracker


@pytest.fixture
def tracker(tmp_path):
    db_file = str(tmp_path / "test_signals.db")
    return SignalTracker(db_path=db_file)


def test_signal_tracker_crud_and_stats(tracker):
    # 1. Initially empty stats
    stats = tracker.get_stats()
    assert stats["total_trades"] == 0
    assert stats["wins"] == 0
    assert stats["losses"] == 0
    assert stats["open_trades"] == 0
    assert stats["win_rate"] == 0.0
    assert stats["net_pnl_r"] == 0.0

    # 2. Save a signal with kline snapshot
    sig = {
        "symbol": "BTCUSDT",
        "timeframe": "15m",
        "signal_type": "LONG",
        "pattern": "TRENDLINE_BREAKOUT",
        "entry_price": 78000.0,
        "stop_loss": 77000.0,
        "tp1": 80200.0,
        "tp2": 81000.0,
        "risk_reward": 2.2,
        "sl_pct": 0.0128,
        "description": "Bullish Breakout over Resistance Trendline (3 touches)",
        "timestamp": 1700000000.0,
    }
    klines = [
        {"timestamp": 1699990000000, "open": 77500, "high": 78100, "low": 77400, "close": 78000, "volume": 100},
        {"timestamp": 1700000000000, "open": 78000, "high": 78500, "low": 77900, "close": 78200, "volume": 120},
    ]

    sig_id = tracker.save_signal(sig, klines)
    assert sig_id is not None
    assert sig_id > 0

    # 3. Retrieve signal
    retrieved = tracker.get_signal(sig_id)
    assert retrieved is not None
    assert retrieved["id"] == sig_id
    assert retrieved["symbol"] == "BTCUSDT"
    assert retrieved["status"] == "OPEN"
    assert retrieved["entry_price"] == 78000.0
    assert retrieved["stop_loss"] == 77000.0
    assert retrieved["tp1"] == 80200.0
    assert len(retrieved["kline_snapshot"]) == 2
    assert retrieved["kline_snapshot"][0]["open"] == 77500

    # Check stats with 1 open trade
    stats = tracker.get_stats()
    assert stats["total_trades"] == 1
    assert stats["open_trades"] == 1

    # 4. List signals
    all_signals = tracker.list_signals()
    assert len(all_signals) == 1
    assert all_signals[0]["id"] == sig_id

    # Filter by status
    assert len(tracker.list_signals(status_filter="OPEN")) == 1
    assert len(tracker.list_signals(status_filter="WIN")) == 0

    # 5. Prevent duplicate signal insertion for same symbol & pattern within cooldown window
    dup_id = tracker.save_signal(sig, klines, cooldown_seconds=3600)
    assert dup_id == sig_id  # Should return existing ID, not insert duplicate
    assert tracker.get_stats()["total_trades"] == 1


def test_signal_outcome_evaluation_rules(tracker):
    # 1. Test LONG - WIN by hitting TP1
    long_sig = {
        "symbol": "BTCUSDT",
        "timeframe": "15m",
        "signal_type": "LONG",
        "pattern": "BREAKOUT",
        "entry_price": 78000.0,
        "stop_loss": 77000.0,
        "tp1": 80200.0,
        "tp2": 81000.0,
        "risk_reward": 2.2,
        "timestamp": 1700000000.0,
    }
    sig_id_1 = tracker.save_signal(long_sig, [{"timestamp": 1700000000000, "open": 78000, "high": 78100, "low": 77900, "close": 78000}])

    # Candle 1: still open (price oscillating between 77500 and 79500)
    candle_1 = {"timestamp": 1700000900000, "open": 78000, "high": 79500, "low": 77500, "close": 79000}
    res = tracker.evaluate_signal(sig_id_1, candle_1)
    assert res["status"] == "OPEN"
    assert res["floating_r"] > 0

    # Candle 2: high touches TP1 (80300 >= 80200) -> WIN
    candle_2 = {"timestamp": 1700001800000, "open": 79000, "high": 80300, "low": 78800, "close": 80100}
    res = tracker.evaluate_signal(sig_id_1, candle_2)
    assert res["status"] == "WIN"
    assert res["exit_price"] == 80200.0
    assert res["pnl_r"] == 2.2
    assert res["pnl_pct"] == pytest.approx(0.0282, abs=0.001)

    # 2. Test LONG - LOSS by hitting SL
    long_sig_2 = dict(long_sig, symbol="ETHUSDT")
    sig_id_2 = tracker.save_signal(long_sig_2)
    candle_sl = {"timestamp": 1700000900000, "open": 78000, "high": 78200, "low": 76900, "close": 77100}
    res_sl = tracker.evaluate_signal(sig_id_2, candle_sl)
    assert res_sl["status"] == "LOSS"
    assert res_sl["exit_price"] == 77000.0
    assert res_sl["pnl_r"] == -1.0
    assert res_sl["pnl_pct"] == pytest.approx(-0.0128, abs=0.001)

    # 3. Test SHORT - WIN by hitting TP1
    short_sig = {
        "symbol": "SOLUSDT",
        "timeframe": "15m",
        "signal_type": "SHORT",
        "pattern": "BREAKDOWN",
        "entry_price": 100.0,
        "stop_loss": 102.0,
        "tp1": 95.6,
        "tp2": 94.0,
        "risk_reward": 2.2,
        "timestamp": 1700000000.0,
    }
    sig_id_3 = tracker.save_signal(short_sig)
    candle_short_win = {"timestamp": 1700000900000, "open": 100.0, "high": 100.5, "low": 95.0, "close": 95.8}
    res_short = tracker.evaluate_signal(sig_id_3, candle_short_win)
    assert res_short["status"] == "WIN"
    assert res_short["exit_price"] == 95.6
    assert res_short["pnl_r"] == 2.2

    # 4. Test SHORT - LOSS by hitting SL
    short_sig_4 = dict(short_sig, symbol="AVAXUSDT")
    sig_id_4 = tracker.save_signal(short_sig_4)
    candle_short_loss = {"timestamp": 1700000900000, "open": 100.0, "high": 102.5, "low": 99.0, "close": 102.0}
    res_short_loss = tracker.evaluate_signal(sig_id_4, candle_short_loss)
    assert res_short_loss["status"] == "LOSS"
    assert res_short_loss["exit_price"] == 102.0
    assert res_short_loss["pnl_r"] == -1.0

    # 5. Check stats after 2 wins and 2 losses
    stats = tracker.get_stats()
    assert stats["total_trades"] == 4
    assert stats["wins"] == 2
    assert stats["losses"] == 2
    assert stats["open_trades"] == 0
    assert stats["win_rate"] == 50.0
    assert stats["net_pnl_r"] == pytest.approx(2.4, abs=0.01)  # (2.2 * 2) - 2.0 = 2.4R


def test_breakeven_protection_on_tp1_hit(tracker):
    # LONG trade with TP1 at 79000, TP2 at 80200, Entry at 78000, SL at 77000
    sig = {
        "symbol": "SOLUSDT",
        "timeframe": "15m",
        "signal_type": "LONG",
        "pattern": "SMC_ORDER_BLOCK_RETEST",
        "entry_price": 78000.0,
        "stop_loss": 77000.0,
        "tp1": 79000.0,
        "tp2": 80200.0,
        "risk_reward": 2.2,
        "timestamp": 1700000000.0,
    }
    sig_id = tracker.save_signal(sig, [{"timestamp": 1700000000000, "open": 78000, "high": 78100, "low": 77900, "close": 78000}])

    # Candle 1: High hits TP1 (79200 >= 79000)
    c1 = {"timestamp": 1700000900000, "open": 78000, "high": 79200, "low": 77900, "close": 78800}
    res1 = tracker.evaluate_signal(sig_id, c1)
    # Trade should remain OPEN with breakeven_reached = 1, stop_loss moved to entry 78000
    assert res1["status"] == "OPEN"
    assert res1.get("breakeven_reached") == 1
    assert res1["stop_loss"] == 78000.0

    # Candle 2: Price drops back down to 77800 (below entry 78000)
    c2 = {"timestamp": 1700001800000, "open": 78500, "high": 78600, "low": 77800, "close": 77900}
    res2 = tracker.evaluate_signal(sig_id, c2)
    # Stopped out at Breakeven with partial win, NOT -1.0R loss!
    assert res2["status"] == "WIN"
    assert res2["exit_price"] == 78000.0
    assert res2["pnl_r"] > 0.0

