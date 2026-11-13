# Fixed Trusted-Coin Whitelist and Manual History Purge — Plan

## Goal
Stop tracking all non-whitelisted coins across the live system. The fixed live whitelist is `BTCUSDT`, `ETHUSDT`, `BNBUSDT`, `SOLUSDT`, `XRPUSDT`. Separately provide a local CLI purge that can permanently delete rows from the existing `signals` table for every other symbol, including OPEN rows; each deleted row's embedded `kline_snapshot` is removed with it. No separate candle-snapshot table is in scope. Purge runs only after displaying the exact candidate summary, explicit typed `PURGE` confirmation, and verified SQLite backup.

## Analysis Decisions
- User clarified the goal is a fixed trusted-coin whitelist, not dynamic top-N by volume.
- User approved whitelist: BTC, ETH, BNB, SOL, XRP.
- User explicitly selected permanent database deletion for other coins, including OPEN signals. Deleting OPEN records ends their TP/SL/PnL tracking. Immediately upon whitelist switch, TP/SL/PnL tracking of excluded OPEN rows stops. These rows remain visible in the OPEN/history UI with a prominent `NOT MONITORED` warning until manual purge, and must not be sent as live active signals or websocket management state. This must be stated in UI/README and CLI preview.
- Operational sequence has two explicit phases: (1) implement/deploy fixed whitelist; (2) operator separately runs CLI preview then optionally `--apply`. Application never invokes purge automatically. No DELETE occurs unless the operator initiates `--apply` and types exact `PURGE` after seeing the candidate summary and after backup verification.
- Purge trigger is **manual only**, never automatic when whitelist changes or at app startup. Web dashboard has no authentication and must not expose a destructive endpoint/button.
- Purge mechanism: local CLI with preview-only default. On `--apply`, first show the complete candidate summary and require one exact `PURGE` confirmation for that summary; cancellation causes no backup or DB changes. After confirmation, create a SQLite-consistent backup (including WAL state), verify backup readability, `integrity_check` and pre-purge row count; any backup/open/integrity failure always aborts, with no override. Recheck candidate counts under one transaction, abort if counts drift, and rollback on any delete/SQL error. On success report deleted count and backup path. Retain every successful backup indefinitely; never auto-delete backups.
- Historical records for whitelisted symbols remain intact. All rows for non-whitelist symbols are removed only by CLI apply; SQLite AUTOINCREMENT metadata is not reset; no VACUUM or unrelated data cleanup.
- **Security:** `TRUSTED_SYMBOLS` is fixed in `config.py`; request input cannot mutate it. Purge accepts DB path from CLI (default `signals.db`), uses SQL placeholders, rejects missing `signals` table and whitelist if empty/duplicate/malformed, allows zero rows for any/all trusted symbols, and never accepts a user-supplied deletion symbol list. Tests use only temporary DB files. No web purge route.
- **Rejected:** dynamic quote-volume ranking (user wants reliable fixed coins), auto-purge on every top membership refresh (can destroy on transient classification changes), unauthenticated web purge endpoint, deleting all history or resetting DB.

## Architecture & Contracts
- `TRUSTED_SYMBOLS = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT")` is the canonical ordered live whitelist. No `top_n_coins`/quote-volume selection.
- `BinanceClient.get_top_futures_symbols` is no longer used to choose live scan universe. Retain exchange metadata validation if useful, but live symbols are exact whitelist only.
- `WebServerState.refresh_universe()` simply publishes the fixed whitelist; it does not rank, discover, or intersect membership by ticker volume/metadata. Ticker metrics may refresh independently for display, but a metrics outage never removes a trusted symbol. The independent `main.ScannerPipeline.scan_cycle()` iterates the same fixed whitelist and does not call the dynamic quote-volume selector.
- `/api/symbols`, `/api/status`, `/ws/stream INIT_STATE`, `run_scan`, live `/api/chart`, `/ws/market`, frontend picker/search/watchlist all use the same fixed list.
- Invalid symbol/valid-format non-member live chart receives HTTP 400 JSON `symbol_not_in_universe`; market WS rejects before upgrade with HTTP 400 JSON. Never use WebSocket close code 400.
- `/api/signals?status=HISTORY`, `/api/signals/{id}/chart`, and history filters remain readable for stored rows before purge. Live OPEN payloads (`/api/signals` without HISTORY, `/api/status.active_signals`, `/ws/stream INIT_STATE.active_signals`, NEW_SIGNAL broadcasts) must be filtered to the fixed whitelist. `active_signals` initialization must not load non-whitelist OPEN rows into live management. A historical non-whitelist symbol may be viewed but cannot enter live picker or market WS and cannot reconnect-loop. Non-whitelist OPEN DB rows remain pending manual purge and are explicitly not auto-managed; README/CLI must warn this monitoring stops immediately when excluded.
- CLI contract: `python3 purge_signals.py --db signals.db` is preview-only (no mutation); prints whitelist, candidate symbol list, row counts by symbol/status, total rows, OPEN count, DB path and backup that WOULD be created. `--apply` performs a SQLite online backup to a unique timestamped file, opens/validates the backup (integrity check and pre-purge row count), asks for exact `PURGE`, then deletes all non-whitelist rows in a single transaction. Re-check candidate counts under the same transaction; abort if universe/count changed since preview. After commit, report deleted rows and surviving rows. Purge must be idempotent.
- Backup source using `sqlite3.Connection.backup()` so WAL content is captured; never copy only the main DB file while WAL is active. Keep all verified backups indefinitely; no automatic retention pruning.
- Purge candidates are rows of the existing `signals` table; `kline_snapshot` is a column in each row, so deleting a non-whitelist row deletes its embedded candle snapshot. No separate candle table exists or is targeted. Use `symbol NOT IN (?,...,?)` with exact whitelist parameters. Abort before backup/delete if the `signals` table is missing or the built-in whitelist is empty, malformed, or has duplicates. Do not require any protected whitelist symbol to have rows: a valid empty database or zero rows for one/more whitelisted coins is allowed. On any exception during deletion, roll back the transaction and retain the pre-purge database state; the backup remains available.
- No foreign-key child table currently owns signal rows; if discovered during implementation, STOP and revise plan before cascade/delete.
- No automatic purge, no schema migration, no signal state rewrite; purge is a separate explicit command.

## Environment Context
- Language: Python 3.13 + vanilla JavaScript/HTML; aiohttp; SQLite WAL.
- TEST_CMD: `PYTHONPATH=. ./venv/bin/pytest tests/ -q`
- NODE_TEST_CMD: `node --test tests/chart_stream.test.js`
- LINT_CMD: `python3 -m py_compile server.py binance_client.py technical_engine.py risk_manager.py config.py chart_renderer.py telegram_notifier.py news_service.py signal_tracker.py purge_signals.py`
- BUILD_CMD: none; server serves static assets.
- Branch: `feat/symbol-filtered-history`; no push unless user asks.
- Graph project: `Users-trantandat-GIC-Freelancer-futures-chart-scanner`, ready. Blast scope crosses server/Binance/UI/SQLite tracker/CLI/tests; no edits to technical signal algorithms, vendor chart library, or schema.
- Blast radius estimate: 14 files: `config.py`, `binance_client.py`, `main.py`, `server.py`, `signal_tracker.py`, `purge_signals.py` (new), `static/index.html`, `static/chart_stream.js`, `README.md`, `tests/test_binance_client.py`, `tests/test_integration.py`, `tests/test_server.py`, `tests/test_signal_tracker.py`, `tests/chart_stream.test.js`.
- Untracked `.supergraph-env` remains excluded from commits.

## Task 1: Define fixed whitelist and use it for all live discovery
Wave: 1
Status: pending
Risk: high
Dependencies: none
Model: inherit

Files:
- Modify: `config.py`
- Modify: `binance_client.py`
- Modify: `server.py`
- Modify: `main.py`
- Test: `tests/test_binance_client.py`
- Test: `tests/test_server.py`
- Test: `tests/test_integration.py`

Blast radius:
- `config.py`, `binance_client.py`, `main.py`, `server.py`
- `tests/test_binance_client.py`, `tests/test_server.py`, `tests/test_integration.py`

Acceptance:
- Fixed exact five-symbol whitelist and order is authoritative; no quote-volume ranking or override can add another symbol.
- Scan, `/api/symbols`, `/api/status`, `/ws/stream INIT_STATE`, live chart and market WS use the whitelist only.
- Exchange metadata outage retains whitelist and marks stale; it never expands the live set.
- Out-of-list valid symbol gets HTTP 400 before live chart data access/WS upgrade. Historical signal APIs remain exempt.
- All existing tests expecting dynamic top-N update to fixed list semantics; chart/WS fixtures explicitly seed whitelist.

TDD:
- Behavior: fixed whitelist becomes canonical server live symbol set.
- Test file: `tests/test_binance_client.py` and `tests/test_server.py`
- Test names: `test_trusted_symbols_is_exact_fixed_whitelist`, `test_scanner_does_not_add_exchange_symbols_outside_whitelist`, `test_pipeline_scans_only_trusted_symbols`, `test_api_symbols_returns_only_trusted_symbols`, `test_live_chart_and_market_ws_reject_non_whitelisted_symbol`, `test_historical_signal_chart_remains_available_for_non_whitelisted_symbol`, `test_non_whitelist_open_signals_hidden_from_live_state_but_visible_in_history`.
- 🔴 RED command: `PYTHONPATH=. ./venv/bin/pytest tests/test_server.py -k test_api_symbols_returns_only_trusted_symbols -q`
- Expected 🔴 RED failure: current source uses dynamic quote-volume-ranked list and exposes all_symbols.
- Minimal 🟢 GREEN change: shared whitelist constant; server refresh, Binance metadata validation, and standalone `ScannerPipeline.scan_cycle()` all use exact list; no DB deletion in this task.
- Refactor candidates: none.
- Mocking: fake exchangeInfo and ticker calls for the external API boundary; aiohttp test client for route behavior.

Steps:
1. 🔴 RED: add exact-list/default and live route membership tests, and update existing chart fixtures.
   Command: `PYTHONPATH=. ./venv/bin/pytest tests/test_binance_client.py tests/test_server.py -k 'trusted_symbols or api_symbols_returns_only_trusted_symbols' -q`
   Expected: FAIL because current system selects dynamically.
2. 🟢 GREEN: switch all live paths to exact whitelist and preserve server snapshot on metadata failure.
   Command: `PYTHONPATH=. ./venv/bin/pytest tests/test_binance_client.py tests/test_server.py -k 'trusted_symbols or api_symbols_returns_only_trusted_symbols or non_whitelisted' -q`
   Expected: PASS.
3. REFACTOR: remove unused dynamic ranking only after caller/reference analysis; maintain ticker metrics for five symbols.
4. VERIFY:
   - `PYTHONPATH=. ./venv/bin/pytest tests/test_binance_client.py tests/test_server.py -q`
   - `python3 -m py_compile config.py binance_client.py server.py`

Checkpoint:
- Files: `config.py binance_client.py main.py server.py tests/test_binance_client.py tests/test_server.py tests/test_integration.py`
- Commit: `feat(symbols): use fixed trusted coin whitelist across scanners`

## Task 2: Keep historical chart separate from live selector and WebSocket
Wave: 2
Status: pending
Risk: medium
Dependencies: Task 1
Model: inherit

Files:
- Modify: `static/index.html`
- Modify: `static/chart_stream.js`
- Test: `tests/chart_stream.test.js`
- Test: `tests/test_server.py`

Blast radius:
- `static/index.html`, `static/chart_stream.js`
- `tests/chart_stream.test.js`, `tests/test_server.py`

Acceptance:
- Live picker/search/watchlist only show the five trusted symbols; no archived symbol insertion/all-symbol fallback.
- Historical signal chart remains readable for a previously stored non-whitelisted symbol without changing live picker universe.
- No market WebSocket connect or reconnect while historical/out-of-whitelist; leaving history returns to selected/first trusted symbol.
- The history feed still displays closed signals from the DB until a manual purge is run.

TDD:
- Behavior: history symbol cannot become a live subscription or picker member.
- Test file: `tests/chart_stream.test.js`
- Test names: `trustedSymbolGuard rejects non-whitelist live symbol`, `historicalChartViewDoesNotSubscribeToMarketWebSocket`, `livePickerNeverInjectsArchivedSymbol`.
- 🔴 RED command: `node --test --test-name-pattern='trustedSymbolGuard rejects non-whitelist live symbol' tests/chart_stream.test.js`
- Expected 🔴 RED failure: helper/guard missing.
- Minimal 🟢 GREEN change: static live membership helper and connect/retry guard; historical rendering continues using archived payload.
- Refactor candidates: none.
- Mocking: pure JS helper fixtures; actual browser route test for historical flow.

Steps:
1. 🔴 RED: add membership and historical/live separation tests.
   Command: `node --test --test-name-pattern='trustedSymbolGuard rejects non-whitelist live symbol' tests/chart_stream.test.js`
   Expected: FAIL because helper is absent.
2. 🟢 GREEN: update selector, history-view transition and reconnect guard.
   Command: `node --test --test-name-pattern='trustedSymbolGuard|historicalChartView|livePickerNever' tests/chart_stream.test.js`
   Expected: PASS.
3. REFACTOR: none.
4. VERIFY:
   - `node --test tests/chart_stream.test.js`
   - `PYTHONPATH=. ./venv/bin/pytest tests/test_server.py -k dashboard -q`

Checkpoint:
- Files: `static/index.html static/chart_stream.js tests/chart_stream.test.js tests/test_server.py`
- Commit: `feat(ui): keep history separate from trusted live symbols`

## Task 3: Add previewable, backed-up manual SQLite purge CLI
Wave: 3
Status: pending
Risk: high
Dependencies: Task 1, Task 2
Model: pro

Files:
- Create: `purge_signals.py`
- Modify: `signal_tracker.py`
- Test: `tests/test_signal_tracker.py`

Blast radius:
- `purge_signals.py`, `signal_tracker.py`, `tests/test_signal_tracker.py`

Acceptance:
- CLI is shipped in the same implementation plan but is not run during deployment or startup. Default invocation is preview-only: candidate non-whitelist rows grouped by symbol/status, total/OPEN counts, DB path; zero DB mutation and no backup required.
- Later, only an explicit operator invocation with `--apply` starts purge: print/reconfirm the exact candidate summary, create unique timestamped backup with SQLite online backup API (includes WAL), verify backup can open and `PRAGMA integrity_check` is `ok`, then require operator to type exact `PURGE` before any DELETE.
- On wrong/missing confirmation, backup failure, integrity failure, invalid/empty whitelist, DB schema mismatch or count drift since preview, abort with no deletion.
- On confirmation, delete every signal row whose symbol is not in fixed whitelist, including OPEN, inside one transaction; use bound SQL placeholders; leave whitelist rows and AUTOINCREMENT sequence untouched; report deleted count.
- CLI has no effect on app startup, HTTP endpoints, or background scan. No automatic purge on whitelist change. Backup retained.
- Test DB is always a temporary file. Production DB is never opened in tests.

TDD:
- Behavior: destructive apply deletes only after preview, validated backup and typed confirmation; all non-whitelist rows including OPEN are deleted.
- Test file: `tests/test_signal_tracker.py`
- Test names: `test_purge_preview_is_read_only_and_lists_open_counts`, `test_purge_apply_requires_exact_confirmation_for_previewed_summary`, `test_purge_apply_creates_integrity_checked_backup_and_deletes_only_non_whitelist`, `test_purge_apply_aborts_if_backup_integrity_check_fails`, `test_purge_apply_aborts_on_count_drift`, `test_purge_aborts_for_missing_table_or_invalid_whitelist`, `test_purge_rolls_back_on_mid_transaction_delete_failure`, `test_purge_backups_are_never_auto_pruned`, `test_purge_is_idempotent`.
- 🔴 RED command: `PYTHONPATH=. ./venv/bin/pytest tests/test_signal_tracker.py -k test_purge_preview_is_read_only_and_lists_open_counts -q`
- Expected 🔴 RED failure: purge preview API/CLI absent.
- Minimal 🟢 GREEN change: add read-only candidate query and CLI backup/confirm/delete flow using temporary DB fixtures.
- Refactor candidates: none.
- Mocking: inject confirmation input and backup target; SQLite test uses temporary DB and real SQLite backup, not mocks for DB semantics.

Steps:
1. 🔴 RED: add preview/apply/abort/backup tests with temp DB.
   Command: `PYTHONPATH=. ./venv/bin/pytest tests/test_signal_tracker.py -k purge -q`
   Expected: FAIL because purge API/CLI absent.
2. 🟢 GREEN: implement preview and explicit protected purge path.
   Command: `PYTHONPATH=. ./venv/bin/pytest tests/test_signal_tracker.py -k purge -q`
   Expected: PASS.
3. REFACTOR: inspect generated backup via SQLite integrity check and ensure `--dry-run` never writes.
4. VERIFY:
   - `PYTHONPATH=. ./venv/bin/pytest tests/test_signal_tracker.py -q`
   - `python3 -m py_compile purge_signals.py signal_tracker.py`

Checkpoint:
- Files: `purge_signals.py signal_tracker.py tests/test_signal_tracker.py`
- Commit: `feat(data): add backed-up confirmed purge for non-whitelist signals`

## Task 4: Document and system-test fixed whitelist and purge workflow
Wave: 4
Status: pending
Risk: high
Dependencies: Task 3
Model: inherit

Files:
- Modify: `README.md`
- Test: `tests/test_server.py`
- Test: `tests/test_signal_tracker.py`

Blast radius:
- `README.md`, test coverage from Tasks 1–3

Acceptance:
- README documents exact five-symbol whitelist, live path enforcement, historical availability until manually purged, purge preview/backup/PURGE confirmation, OPEN tracking impact, and backup location.
- Browser verifies only five live symbols; invalid live chart/WS fails while archived history still renders; frontend does not reconnect.
- CLI preview reports non-whitelist counts and has no write side effects; confirmed test purge creates a valid backup and deletes only non-whitelist rows including OPEN.
- Production `signals.db` is not touched during tests or planning; only operator’s explicit CLI confirmation can purge it.
- Full Python/Node tests, compile, Vibesec and code review pass.

TDD:
- Behavior: CLI and app preserve explicit separation of live whitelist/history/purge; no destructive HTTP route exists.
- Test file: `tests/test_server.py` and `tests/test_signal_tracker.py`
- Test names: `test_no_http_purge_route_is_registered`, `test_purge_preview_and_confirmed_apply_contract`. Re-run the existing Task 1 `test_non_whitelist_open_signals_hidden_from_live_state_but_visible_in_history`; do not define it a second time.
- 🔴 RED command: `PYTHONPATH=. ./venv/bin/pytest tests/test_server.py -k test_no_http_purge_route_is_registered -q`
- Expected 🔴 RED failure: add route-contract test before implementation; purge must only be CLI.
- Minimal 🟢 GREEN change: document operational command and add integration test verifying purge not exposed through server.
- Refactor candidates: none.
- Mocking: aiohttp app route enumeration; CLI test uses temporary SQLite DB only.

Steps:
1. 🔴 RED: add HTTP route absence and test CLI invocation integration.
   Command: `PYTHONPATH=. ./venv/bin/pytest tests/test_server.py tests/test_signal_tracker.py -k 'purge or no_http_purge' -q`
   Expected: FAIL until tests are added and CLI/app boundary is verified.
2. 🟢 GREEN: document exact whitelist and run browser/API/CLI test matrix.
   Command: `PYTHONPATH=. ./venv/bin/pytest tests/test_server.py tests/test_signal_tracker.py -k 'purge or no_http_purge' -q`
   Expected: PASS.
3. REFACTOR: none.
4. VERIFY:
   - `PYTHONPATH=. ./venv/bin/pytest tests/ -q`
   - `node --test tests/chart_stream.test.js`
   - `python3 -m py_compile server.py binance_client.py config.py signal_tracker.py purge_signals.py`

Checkpoint:
- Files: `README.md tests/test_server.py tests/test_signal_tracker.py`
- Commit: `docs(symbols): document fixed trusted universe and manual purge safety`

## Task DAG
- Wave 1: Task 1 fixed whitelist/config/source.
- Wave 2: Task 2 live server/API/WS enforcement; depends on Task 1.
- Wave 3: Task 3 contains the manual purge CLI and depends on fixed whitelist/server contract from Tasks 1–2; UI history/live separation is completed in Task 2 (server/API) and validated in Task 4 browser QA. Task 3 remains local/manual only.
- Wave 4: Task 4 docs and integration verification; depends on Task 3.
- Tasks run sequentially because `tests/test_server.py` and shared UI/browser flows overlap.

## Analysis Decisions
- User explicitly replaced dynamic top-15 ranking with a fixed whitelist: `BTCUSDT`, `ETHUSDT`, `BNBUSDT`, `SOLUSDT`, `XRPUSDT`.
- Non-whitelist signal rows should be permanently deleted only by a manual local CLI after preview, SQLite-consistent backup, integrity verification, and typed `PURGE` confirmation.
- Purge includes OPEN rows; deleting them ends ongoing TP/SL/PnL tracking. This has been explicitly selected by user.
- Changing whitelist does not itself delete data. No unconfirmed purge, no app startup purge, no web purge endpoint, and no DB changes in tests against production file.
- Historical signals stay visible until the user runs the CLI purge. After purge, deleted records are unrecoverable except via retained backup.

## Plan Review
- Review mode: architectural/high-risk because fixed symbol policy spans client/server/API/WebSocket/standalone scanner/UI and destructive CLI targets persistent signal history.
- Graph evidence: `SignalTracker` is SQLite persistence boundary; server and `main.ScannerPipeline` are separate scanner entries; static chart_stream is core UI boundary. No vendor library changes.
- Review findings resolved: fixed whitelist vs dynamic ranking; single CLI purge path; no HTTP deletion; WAL-safe backup before purge; typed confirmation; `OPEN` semantics; test/temporary DB safeguards; scanner/UI path coverage.
- Independent reviewer verdict: **APPROVED** (final review; no blockers).

## User Gate
- Scope decision: all live coin tracking restricted to fixed whitelist, not dynamic top-volume ranking.
- Whitelist approved: BTC, ETH, BNB, SOL, XRP.
- Destructive data scope approved: delete signal rows/snapshots for all other symbols, including OPEN.
- Purge safeguards approved: local CLI preview; one exact `PURGE` confirmation for full candidate summary; abort if backup/integrity fails; keep verified backups indefinitely; no HTTP endpoint.
- Execution approval: user replied “ok” to the revised plan and implementation confirmation. This authorizes implementation only. It does NOT authorize running the production purge CLI; that requires a separate run-specific confirmation after preview.

## Execution Evidence
- TDD RED/GREEN: fixed whitelist constant/pipeline test, out-of-universe API/WebSocket rejection, historical chart exemption, non-whitelist OPEN NOT_MONITORED feed, and purge CLI preview/confirmation/backup/rollback/count-drift/idempotency tests were written before corresponding implementation and passed.
- CLI smoke test used only a temporary `/tmp/whitelist-purge-preview-*.sqlite3`: preview listed one `DOGEUSDT OPEN`, printed Preview only, and both temp rows remained. A separate confirmed-apply smoke test used another temp DB: DOGE OPEN deleted, BTC preserved, SQLite backup integrity passed and original pre-purge rows remained in backup. Production `signals.db` was never opened/purged by these commands.
- Browser: authorized local app restart showed exactly five live picker options; `/api/chart` for DOGE returned HTTP 400 `symbol_not_in_universe`; fixed whitelist metadata verified; NOT MONITORED warning template present. Historical flow source guards/history test pass. Standalone `scan_single_symbol("DOGEUSDT")` now rejects before data fetch (RED/GREEN test).
- Final verification (2026-11-13): Python suite 128 passed; Node suite 48 passed; py_compile and git diff --check pass. Existing warnings: aiohttp AppKey, pytest-asyncio fixture scope, and test client unclosed-session warning.
- Security review: Vibesec pass on fixed whitelist server-side enforcement and local CLI isolation. Purge SQL uses fixed parameterized whitelist; no HTTP destructive route; backup integrity/candidate-count/rollback guards covered by temp DB tests. A concurrent CLI invocation can create redundant backups; single-operator CLI use is expected. No backup auto-pruning.

## Status
Implementation and verification complete; production database untouched. The CLI is available, but `--apply` must only be run after the user explicitly requests a live purge, reviews the candidate summary and types `PURGE`.
