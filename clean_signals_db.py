#!/usr/bin/env python3
"""
Maintenance and cleanup script for signals.db:
1. Marks zombie OPEN trades older than 24 hours as 'EXPIRED'.
2. Resolves duplicate OPEN trades per symbol (Single Active Position enforcement).
3. VACUUMs database to reclaim disk space.
"""
import sqlite3
import time
import os
import sys

def clean_database(db_path: str = "signals.db", dry_run: bool = False):
    if not os.path.exists(db_path):
        print(f"[CleanDB] File not found: {db_path}")
        return

    now = time.time()
    one_day_ago = now - 86400.0

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    try:
        cur = conn.cursor()

        # 1. Count zombie OPEN trades (>24h old)
        zombies = cur.execute(
            "SELECT id, symbol, created_at, entry_price FROM signals WHERE status = 'OPEN' AND created_at < ?",
            (one_day_ago,)
        ).fetchall()
        print(f"[CleanDB] Found {len(zombies)} zombie OPEN signals older than 24 hours.")

        if not dry_run and zombies:
            cur.execute(
                """
                UPDATE signals
                SET status = 'EXPIRED', exit_price = entry_price, exit_time = ?, updated_at = ?
                WHERE status = 'OPEN' AND created_at < ?
                """,
                (now, now, one_day_ago)
            )
            print(f"[CleanDB] Expired {len(zombies)} stale signals.")

        # 2. Count symbols with multiple OPEN trades
        multi_open = cur.execute(
            """
            SELECT symbol, COUNT(*) as cnt
            FROM signals
            WHERE status = 'OPEN'
            GROUP BY symbol
            HAVING cnt > 1
            """
        ).fetchall()
        print(f"[CleanDB] Found {len(multi_open)} symbols with multiple concurrent OPEN trades.")

        for row in multi_open:
            sym = row["symbol"]
            open_sigs = cur.execute(
                "SELECT id, created_at FROM signals WHERE symbol = ? AND status = 'OPEN' ORDER BY created_at DESC",
                (sym,)
            ).fetchall()
            # Keep newest, expire older duplicates
            keep_id = open_sigs[0]["id"]
            expire_ids = [s["id"] for s in open_sigs[1:]]
            if not dry_run and expire_ids:
                placeholders = ",".join("?" for _ in expire_ids)
                cur.execute(
                    f"UPDATE signals SET status = 'EXPIRED', exit_time = ?, updated_at = ? WHERE id IN ({placeholders})",
                    [now, now, *expire_ids]
                )

        if not dry_run:
            conn.commit()
            print("[CleanDB] Changes committed. Running VACUUM...")
            conn.execute("VACUUM;")
            print("[CleanDB] VACUUM complete.")

        # Summary
        stats = cur.execute(
            "SELECT status, COUNT(*) FROM signals GROUP BY status"
        ).fetchall()
        print("[CleanDB] Current status summary:")
        for s in stats:
            print(f"  {s[0]}: {s[1]}")

    finally:
        conn.close()

if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    db = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else "signals.db"
    clean_database(db, dry_run=dry_run)
