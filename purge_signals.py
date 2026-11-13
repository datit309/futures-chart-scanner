"""Preview and explicitly confirmed purge of signals outside TRUSTED_SYMBOLS.

This command is intentionally not called by the app. Default mode is read-only.
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import shutil
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from config import TRUSTED_SYMBOLS


def _validate_whitelist() -> tuple[str, ...]:
    symbols = tuple(TRUSTED_SYMBOLS)
    if not symbols or len(set(symbols)) != len(symbols):
        raise ValueError("trusted whitelist is empty or contains duplicates")
    if any(not isinstance(symbol, str) or not symbol.endswith("USDT") or not symbol.isupper() for symbol in symbols):
        raise ValueError("trusted whitelist contains malformed symbol")
    return symbols


def _open_readonly(db_path: str) -> sqlite3.Connection:
    uri = Path(db_path).resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=10.0)
    conn.row_factory = sqlite3.Row
    return conn


def _candidate_summary(conn: sqlite3.Connection, whitelist: tuple[str, ...]) -> Dict[str, Any]:
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "signals" not in tables:
        raise ValueError("signals table is missing")
    columns = {row[1] for row in conn.execute("PRAGMA table_info(signals)")}
    if "symbol" not in columns or "status" not in columns:
        raise ValueError("signals table schema is invalid")
    placeholders = ",".join("?" for _ in whitelist)
    rows = conn.execute(
        f"SELECT symbol, status, COUNT(*) AS count FROM signals WHERE symbol NOT IN ({placeholders}) GROUP BY symbol,status ORDER BY symbol,status",
        whitelist,
    ).fetchall()
    by_symbol: Dict[str, Dict[str, int]] = defaultdict(dict)
    total = 0
    open_count = 0
    for row in rows:
        count = int(row["count"])
        by_symbol[str(row["symbol"])][str(row["status"])] = count
        total += count
        if str(row["status"]).upper() == "OPEN":
            open_count += count
    protected_count = int(conn.execute(
        f"SELECT COUNT(*) FROM signals WHERE symbol IN ({placeholders})", whitelist
    ).fetchone()[0])
    return {
        "by_symbol": dict(by_symbol),
        "candidate_rows": total,
        "open_rows": open_count,
        "trusted_rows": protected_count,
        "whitelist": list(whitelist),
    }


def preview_non_whitelist_signals(db_path: str = "signals.db") -> Dict[str, Any]:
    """Read-only summary; never creates a backup or modifies the source database."""
    whitelist = _validate_whitelist()
    path = Path(db_path)
    if not path.exists():
        raise FileNotFoundError(f"database does not exist: {path}")
    with _open_readonly(str(path)) as conn:
        summary = _candidate_summary(conn, whitelist)
    summary["db_path"] = str(path.resolve())
    summary["total_rows"] = summary["candidate_rows"] + summary["trusted_rows"]
    return summary


def _create_and_verify_backup(db_path: str, backup_dir: str) -> str:
    source_path = Path(db_path).resolve()
    backup_root = Path(backup_dir).resolve()
    backup_root.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup_path = backup_root / f"{source_path.stem}-pre-purge-{stamp}.sqlite3"
    with sqlite3.connect(str(source_path), timeout=10.0) as src:
        with sqlite3.connect(str(backup_path), timeout=10.0) as dst:
            src.backup(dst)
            integrity = dst.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                raise sqlite3.DatabaseError(f"backup integrity_check failed: {integrity}")
            source_tables = {r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            backup_tables = {r[0] for r in dst.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if source_tables != backup_tables:
                raise sqlite3.DatabaseError("backup schema does not match source database")
            source_count = int(src.execute("SELECT COUNT(*) FROM signals").fetchone()[0])
            backup_count = int(dst.execute("SELECT COUNT(*) FROM signals").fetchone()[0])
            if source_count != backup_count:
                raise sqlite3.DatabaseError("backup row count does not match source database")
    return str(backup_path)


def purge_non_whitelist_signals(
    db_path: str = "signals.db",
    *,
    backup_dir: Optional[str] = None,
    apply: bool = False,
    confirmation: str = "",
    confirm_input: Callable[[str], str] = input,
) -> Dict[str, Any]:
    """Preview by default; `apply=True` requires verified backup and exact PURGE token.

    This function is used by tests on temporary DBs. It is never invoked by web or
    app startup. Callers are responsible for explicit operator intent.
    """
    summary = preview_non_whitelist_signals(db_path)
    if not apply:
        return {**summary, "applied": False, "deleted_rows": 0, "backup_path": None}
    if not confirmation:
        print(f"Database: {summary['db_path']}")
        print(f"Whitelist: {', '.join(summary['whitelist'])}")
        print(f"Rows to delete: {summary['candidate_rows']} (OPEN: {summary['open_rows']})")
        for symbol, statuses in sorted(summary["by_symbol"].items()):
            details = ", ".join(f"{status}={count}" for status, count in sorted(statuses.items()))
            print(f"  {symbol}: {details}")
        confirmation = confirm_input("Type PURGE to permanently delete every listed signal, including OPEN positions (TP/SL tracking ends). A verified backup is mandatory; backup/integrity failure aborts with no override: ")
    if confirmation != "PURGE":
        return {**summary, "applied": False, "aborted": True, "reason": "confirmation_required", "deleted_rows": 0, "backup_path": None}

    whitelist = _validate_whitelist()
    backup_path = _create_and_verify_backup(db_path, backup_dir or str(Path(db_path).resolve().parent / "backups"))
    placeholders = ",".join("?" for _ in whitelist)
    deleted_rows = 0
    with sqlite3.connect(str(Path(db_path).resolve()), timeout=10.0, isolation_level=None) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("BEGIN IMMEDIATE")
        try:
            current = _candidate_summary(conn, whitelist)
            for key in ("candidate_rows", "open_rows", "trusted_rows", "by_symbol"):
                if current[key] != summary[key]:
                    raise RuntimeError("database changed after preview; aborting purge")
            cursor = conn.execute(f"DELETE FROM signals WHERE symbol NOT IN ({placeholders})", whitelist)
            deleted_rows = cursor.rowcount
            if deleted_rows != summary["candidate_rows"]:
                raise RuntimeError("deleted row count changed; rolling back purge")
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return {**summary, "applied": True, "aborted": False, "deleted_rows": deleted_rows, "backup_path": backup_path}


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Preview or explicitly purge non-whitelist signal history.")
    parser.add_argument("--db", default="signals.db", help="SQLite signals DB (default: signals.db)")
    parser.add_argument("--backup-dir", default=None, help="Backup directory (default: <DB parent>/backups)")
    parser.add_argument("--apply", action="store_true", help="Apply purge after creating/verifying backup and typing PURGE")
    args = parser.parse_args(argv)
    try:
        result = purge_non_whitelist_signals(args.db, backup_dir=args.backup_dir, apply=args.apply)
    except Exception as exc:
        print(f"PURGE ABORTED: {exc}", file=sys.stderr)
        return 2
    print(f"Database: {result['db_path']}")
    print(f"Whitelist: {', '.join(result['whitelist'])}")
    print(f"Rows to delete: {result['candidate_rows']} (OPEN: {result['open_rows']})")
    for symbol, statuses in sorted(result["by_symbol"].items()):
        details = ", ".join(f"{status}={count}" for status, count in sorted(statuses.items()))
        print(f"  {symbol}: {details}")
    if not args.apply:
        print("Preview only; no rows changed. Use --apply to create a verified backup and require typed PURGE.")
        return 0
    if result.get("aborted"):
        print("Purge cancelled; no rows changed.")
        return 1
    print(f"Deleted {result['deleted_rows']} rows. Verified backup retained at: {result['backup_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
