import json
import sqlite3
import time
from typing import Any, Dict, List, Optional


class SignalTracker:
    def __init__(self, db_path: str = "signals.db"):
        self.db_path = db_path
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def _init_db(self):
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    signal_type TEXT NOT NULL,
                    pattern TEXT NOT NULL,
                    entry_price REAL NOT NULL,
                    stop_loss REAL NOT NULL,
                    tp1 REAL NOT NULL,
                    tp2 REAL NOT NULL,
                    risk_reward REAL NOT NULL,
                    sl_pct REAL NOT NULL,
                    description TEXT,
                    status TEXT NOT NULL DEFAULT 'OPEN',
                    exit_price REAL,
                    exit_time REAL,
                    pnl_r REAL DEFAULT 0.0,
                    pnl_pct REAL DEFAULT 0.0,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    kline_snapshot TEXT,
                    breakeven_reached INTEGER DEFAULT 0,
                    tp1_hit INTEGER DEFAULT 0
                );
            """)
            try:
                conn.execute("ALTER TABLE signals ADD COLUMN breakeven_reached INTEGER DEFAULT 0;")
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute("ALTER TABLE signals ADD COLUMN tp1_hit INTEGER DEFAULT 0;")
            except sqlite3.OperationalError:
                pass
            conn.execute("CREATE INDEX IF NOT EXISTS idx_signals_symbol ON signals(symbol);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_signals_status ON signals(status);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_signals_created ON signals(created_at);")

    def save_signal(
        self,
        sig: Dict[str, Any],
        klines: Optional[List[Dict[str, Any]]] = None,
        cooldown_seconds: float = 3600.0,
    ) -> int:
        now = time.time()
        created_at = float(sig.get("timestamp") or now)
        symbol = str(sig.get("symbol", "")).upper()
        signal_type = str(sig.get("signal_type", "LONG")).upper()
        pattern = str(sig.get("pattern", "BREAKOUT"))

        with self._get_connection() as conn:
            # Check for existing open signal for same symbol & type within cooldown
            cursor = conn.execute(
                """
                SELECT id FROM signals
                WHERE symbol = ? AND signal_type = ? AND status = 'OPEN' AND created_at >= ?
                ORDER BY created_at DESC LIMIT 1
                """,
                (symbol, signal_type, created_at - cooldown_seconds),
            )
            row = cursor.fetchone()
            if row:
                return row["id"]

            kline_json = json.dumps(klines) if klines else None
            cursor = conn.execute(
                """
                INSERT INTO signals (
                    symbol, timeframe, signal_type, pattern,
                    entry_price, stop_loss, tp1, tp2, risk_reward, sl_pct,
                    description, status, created_at, updated_at, kline_snapshot
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'OPEN', ?, ?, ?)
                """,
                (
                    symbol,
                    str(sig.get("timeframe", "15m")),
                    signal_type,
                    pattern,
                    float(sig.get("entry_price", 0.0)),
                    float(sig.get("stop_loss", 0.0)),
                    float(sig.get("tp1") or sig.get("take_profit", 0.0)),
                    float(sig.get("tp2") or sig.get("take_profit", 0.0)),
                    float(sig.get("risk_reward", 2.0)),
                    float(sig.get("sl_pct", 0.0)),
                    str(sig.get("description", "")),
                    created_at,
                    now,
                    kline_json,
                ),
            )
            return cursor.lastrowid

    def get_signal(self, signal_id: int) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT * FROM signals WHERE id = ?", (signal_id,))
            row = cursor.fetchone()
            if not row:
                return None
            return self._row_to_dict(row)

    def evaluate_signal(self, signal_id: int, candle: Dict[str, Any]) -> Dict[str, Any]:
        sig = self.get_signal(signal_id)
        if not sig or sig["status"] != "OPEN":
            return sig or {}

        entry = float(sig["entry_price"])
        sl = float(sig["stop_loss"])
        tp1 = float(sig["tp1"])
        tp2 = float(sig.get("tp2") or 0.0)
        is_long = sig["signal_type"] == "LONG"
        risk = abs(entry - sl) or (entry * 0.01)

        high = float(candle.get("high", candle.get("close", 0.0)))
        low = float(candle.get("low", candle.get("close", 0.0)))
        close = float(candle.get("close", 0.0))
        ts_raw = candle.get("timestamp", candle.get("time", time.time() * 1000))
        ts_sec = float(ts_raw) / 1000.0 if float(ts_raw) > 1e11 else float(ts_raw)

        has_tp2 = (tp2 > tp1 if is_long else (0 < tp2 < tp1))
        use_be_runner = has_tp2 and sig.get("pattern") in ("SMC_ORDER_BLOCK_RETEST", "TREND_PULLBACK")
        tp1_already_hit = bool(sig.get("tp1_hit") or sig.get("breakeven_reached"))

        status = "OPEN"
        exit_price = None
        pnl_r = 0.0
        pnl_pct = 0.0

        if is_long:
            if not tp1_already_hit and high >= tp1:
                if use_be_runner and high < tp2:
                    with self._get_connection() as conn:
                        conn.execute(
                            "UPDATE signals SET tp1_hit = 1, breakeven_reached = 1, stop_loss = ?, updated_at = ? WHERE id = ?",
                            (entry, time.time(), signal_id)
                        )
                    sig["tp1_hit"] = 1
                    sig["breakeven_reached"] = 1
                    sig["stop_loss"] = entry
                    floating_r = round((close - entry) / risk, 2)
                    return {**sig, "floating_r": floating_r}
                else:
                    status = "WIN"
                    exit_price = tp2 if (use_be_runner and high >= tp2) else tp1
                    pnl_r = float(sig["risk_reward"])
                    pnl_pct = (exit_price - entry) / entry
            elif tp1_already_hit and use_be_runner and high >= tp2:
                status = "WIN"
                exit_price = tp2
                pnl_r = float(sig["risk_reward"])
                pnl_pct = (tp2 - entry) / entry
            elif low <= sl:
                if tp1_already_hit:
                    status = "WIN"
                    exit_price = entry
                    pnl_r = round(0.5 * ((tp1 - entry) / risk), 2)
                    pnl_pct = round(0.5 * (tp1 - entry) / entry, 4)
                else:
                    status = "LOSS"
                    exit_price = sl
                    pnl_r = -1.0
                    pnl_pct = (sl - entry) / entry
            else:
                floating_r = round((close - entry) / risk, 2) if risk > 0 else 0.0
                return {**sig, "floating_r": floating_r}
        else:  # SHORT
            if not tp1_already_hit and low <= tp1:
                if use_be_runner and low > tp2:
                    with self._get_connection() as conn:
                        conn.execute(
                            "UPDATE signals SET tp1_hit = 1, breakeven_reached = 1, stop_loss = ?, updated_at = ? WHERE id = ?",
                            (entry, time.time(), signal_id)
                        )
                    sig["tp1_hit"] = 1
                    sig["breakeven_reached"] = 1
                    sig["stop_loss"] = entry
                    floating_r = round((entry - close) / risk, 2)
                    return {**sig, "floating_r": floating_r}
                else:
                    status = "WIN"
                    exit_price = tp2 if (use_be_runner and low <= tp2) else tp1
                    pnl_r = float(sig["risk_reward"])
                    pnl_pct = (entry - exit_price) / entry
            elif tp1_already_hit and use_be_runner and low <= tp2:
                status = "WIN"
                exit_price = tp2
                pnl_r = float(sig["risk_reward"])
                pnl_pct = (entry - tp2) / entry
            elif high >= sl:
                if tp1_already_hit:
                    status = "WIN"
                    exit_price = entry
                    pnl_r = round(0.5 * ((entry - tp1) / risk), 2)
                    pnl_pct = round(0.5 * (entry - tp1) / entry, 4)
                else:
                    status = "LOSS"
                    exit_price = sl
                    pnl_r = -1.0
                    pnl_pct = (entry - sl) / entry
            else:
                floating_r = round((entry - close) / risk, 2) if risk > 0 else 0.0
                return {**sig, "floating_r": floating_r}

        # Update DB if trade resolved
        now = time.time()
        kline_snapshot = sig.get("kline_snapshot", [])
        candle_ts = candle.get("timestamp") or candle.get("time")
        if kline_snapshot and candle_ts:
            last_ts = kline_snapshot[-1].get("timestamp") or kline_snapshot[-1].get("time")
            if last_ts == candle_ts:
                kline_snapshot[-1] = candle
            else:
                kline_snapshot.append(candle)
        else:
            kline_snapshot.append(candle)

        with self._get_connection() as conn:
            conn.execute(
                """
                UPDATE signals
                SET status = ?, exit_price = ?, exit_time = ?, pnl_r = ?, pnl_pct = ?,
                    updated_at = ?, kline_snapshot = ?
                WHERE id = ?
                """,
                (
                    status,
                    exit_price,
                    ts_sec,
                    pnl_r,
                    pnl_pct,
                    now,
                    json.dumps(kline_snapshot),
                    signal_id,
                ),
            )

        updated_sig = self.get_signal(signal_id)
        return updated_sig or {}

    def evaluate_open_signals(self, symbol: str, candle: Dict[str, Any]) -> List[Dict[str, Any]]:
        open_signals = self.list_signals(status_filter="OPEN", symbol_filter=symbol, limit=20)
        results = []
        for s in open_signals:
            res = self.evaluate_signal(s["id"], candle)
            results.append(res)
        return results

    def list_signals(
        self,
        status_filter: Optional[str] = None,
        symbol_filter: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        query = "SELECT * FROM signals WHERE 1=1"
        params: List[Any] = []

        if status_filter:
            normalized = status_filter.upper()
            if normalized == "HISTORY":
                query += " AND status IN (?, ?, ?)"
                params.extend(["WIN", "LOSS", "EXPIRED"])
            else:
                query += " AND status = ?"
                params.append(normalized)
        if symbol_filter:
            query += " AND symbol = ?"
            params.append(symbol_filter.upper())

        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        with self._get_connection() as conn:
            cursor = conn.execute(query, params)
            return [self._row_to_dict(row) for row in cursor.fetchall()]

    def get_stats(self) -> Dict[str, Any]:
        with self._get_connection() as conn:
            cursor = conn.execute("""
                SELECT
                    COUNT(*) as total_trades,
                    SUM(CASE WHEN status = 'WIN' THEN 1 ELSE 0 END) as wins,
                    SUM(CASE WHEN status = 'LOSS' THEN 1 ELSE 0 END) as losses,
                    SUM(CASE WHEN status = 'OPEN' THEN 1 ELSE 0 END) as open_trades,
                    SUM(pnl_r) as net_pnl_r
                FROM signals
            """)
            row = cursor.fetchone()
            total = row["total_trades"] or 0
            wins = row["wins"] or 0
            losses = row["losses"] or 0
            open_trades = row["open_trades"] or 0
            net_pnl = round(float(row["net_pnl_r"] or 0.0), 2)

            closed = wins + losses
            win_rate = round((wins / closed * 100.0), 1) if closed > 0 else 0.0

            return {
                "total_trades": total,
                "wins": wins,
                "losses": losses,
                "open_trades": open_trades,
                "win_rate": win_rate,
                "net_pnl_r": net_pnl,
            }

    def _row_to_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        d = dict(row)
        if d.get("kline_snapshot"):
            try:
                d["kline_snapshot"] = json.loads(d["kline_snapshot"])
            except Exception:
                d["kline_snapshot"] = []
        else:
            d["kline_snapshot"] = []
        return d
