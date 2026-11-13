# Fixed Whitelist and Manual Purge Execution Ledger

## Mission
Restrict live tracking to `BTCUSDT`, `ETHUSDT`, `BNBUSDT`, `SOLUSDT`, `XRPUSDT`; keep excluded signal rows/history until separately confirmed manual purge. Purge CLI deletes non-whitelist `signals` rows (including OPEN and embedded snapshots) only after summary preview, verified WAL-safe backup and exact `PURGE` confirmation.

## Pre-dispatch conflict scan
- Task 1: fixed whitelist across config, client, `main.ScannerPipeline`, server and associated tests.
- Task 2: historical/live UI separation, picker and WebSocket reconnect guards.
- Task 3: local purge CLI, tracker helpers and temp-DB tests.
- Task 4: README/security/browser/full verification.
- 12-file blast radius; no charting_library changes and no DB schema migration. `.supergraph-env` remains untracked/excluded.
- Branch `feat/symbol-filtered-history`, base before new work at `3bf7ce8`.
- Execution is sequential because server tests/UI source contract are shared across tasks.

## Destructive-operation invariants
- Whitelist switch and app startup never purge data.
- Excluded OPEN stops TP/SL/PnL tracking immediately, remains visible as NOT MONITORED, and remains in DB/history until operator runs CLI.
- CLI default is read-only preview. `--apply` prints exact candidate summary, prompts exact `PURGE`, then creates SQLite online backup (includes WAL), validates `integrity_check` and pre-purge counts, rechecks candidate summary under transaction, and deletes all non-whitelist signal rows atomically. Any error rolls back; invalid backup/table/whitelist/count drift aborts. Backups retained indefinitely.
- No web purge endpoint. Tests only use `tmp_path`; production `signals.db` must not be accessed by automated tests. No production `--apply` executed.

## Verification evidence
- RED/GREEN recorded for fixed whitelist, standalone scanner, live REST/WebSocket gating, historical/live UI guard, and purge CLI.
- Final full verification: `PYTHONPATH=. ./venv/bin/pytest tests/ -q` → 128 passed; `node --test tests/chart_stream.test.js` → 48 passed; Python compile all affected modules passed; `git diff --check` passed. Includes explicit temp-DB post-backup count-drift/idempotency tests and standalone non-whitelist single-symbol rejection before market-data fetch.
- Browser after authorized app restart: API returns fixed five symbols; DOGE live chart returns HTTP 400 `symbol_not_in_universe`; picker contains five; archived history route remains readable; non-whitelist OPEN shows NOT MONITORED. Live purge preview on temp DB showed one DOGE OPEN, no row changes. Confirmed apply on separate temp DB deleted DOGE OPEN, preserved BTC, produced an integrity-checked pre-purge backup. Production DB was not touched.
- Security review: no destructive HTTP route, fixed whitelist not user-controlled, purge SQL parameterized, exact typed confirmation and validated backup mandatory.
- Existing warnings: aiohttp AppKey and pytest-asyncio fixture-scope warnings; test run reports an unclosed client session warning. Mobile browser viewport/axe audit not available in current tool.
- Pre-existing Serena diagnostic remains: possible unbound `sig_dict` in `server.py::run_scan` when enrichment returns None; outside this task’s requested behavior and unchanged.

## Completion boundary
Review verdict PASS; final verification is green and commit follows. Never run production purge unless user explicitly requests it after inspecting a production preview. If authorized, use exact command from README, review candidate summary and verified backup path, then type PURGE.
