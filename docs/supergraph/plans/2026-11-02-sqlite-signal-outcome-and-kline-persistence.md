# Plan: SQLite Signal Outcome (Win/Loss) Tracking & Kline Persistence

## Problem Statement
Currently, signals in `WebServerState` are held exclusively in-memory (`active_signals = {}`). When the server restarts, all signal history is lost. More importantly, there is zero evaluation of whether a signal reached its Take Profit (WIN) or hit Stop Loss (LOSS), leaving traders with no visibility into setup profitability, win rates, or historical performance. Furthermore, klines are not snapshotted when a signal occurs, preventing traders from reviewing past winning or losing trades.

## Analysis Decisions
- **Persistence Storage**: SQLite (`signals.db`) with zero external service dependencies, using Python's built-in `sqlite3` in WAL mode for sub-millisecond concurrent reads/writes.
- **Outcome Evaluation Rules**:
  - **LONG**:
    - If candle `high >= tp1`: **WIN** (`status = 'WIN'`). Realized R:R = `tp1` R-multiple (e.g., +1.5R or +2.2R), exit price = `tp1`.
    - If candle `low <= stop_loss`: **LOSS** (`status = 'LOSS'`). Realized R:R = -1.0R, exit price = `stop_loss`.
    - If both touched in same candle: conservative **LOSS** (risk first principle).
    - Else: **OPEN** (floating PnL calculated based on latest close / tick).
  - **SHORT**:
    - If candle `low <= tp1`: **WIN** (`status = 'WIN'`).
    - If candle `high >= stop_loss`: **LOSS** (`status = 'LOSS'`).
    - If both touched in same candle: conservative **LOSS**.
    - Else: **OPEN**.
- **Kline Snapshot Persistence**:
  - When a signal triggers, snapshot the last 50 historical klines into `kline_snapshot` (stored as compressed JSON in SQLite).
  - As subsequent candles form and until the trade exits, append the outcome candles to the snapshot.
  - Clicking any past trade in the UI instantly loads its exact historical chart with Entry, SL, TP, and Outcome marker!
- **UI Presentation**:
  - Header Metrics: `WIN RATE: 68% · 24 TRADES (16W / 8L) · NET +21.4R`.
  - Signal Feed: Tab filter `[ALL] [ACTIVE] [WON] [LOST]`, badges: `WIN +2.2R` (green), `LOSS -1.0R` (red), `ACTIVE +0.8R` (blue).

## Architecture & Contracts
### SQLite Schema (`signals` table in `signals.db`):
```sql
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    signal_type TEXT NOT NULL, -- LONG | SHORT
    pattern TEXT NOT NULL,
    entry_price REAL NOT NULL,
    stop_loss REAL NOT NULL,
    tp1 REAL NOT NULL,
    tp2 REAL NOT NULL,
    risk_reward REAL NOT NULL,
    sl_pct REAL NOT NULL,
    description TEXT,
    status TEXT NOT NULL DEFAULT 'OPEN', -- OPEN | WIN | LOSS | EXPIRED
    exit_price REAL,
    exit_time REAL,
    pnl_r REAL DEFAULT 0.0,
    pnl_pct REAL DEFAULT 0.0,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    kline_snapshot TEXT -- JSON array of klines
);
CREATE INDEX IF NOT EXISTS idx_signals_symbol ON signals(symbol);
CREATE INDEX IF NOT EXISTS idx_signals_status ON signals(status);
CREATE INDEX IF NOT EXISTS idx_signals_created ON signals(created_at);
```

### REST API Endpoints:
- `GET /api/signals`: returns `{signals: [...], metrics: {win_rate: float, total_trades: int, wins: int, losses: int, open_trades: int, net_pnl_r: float}}`
- `GET /api/signals/{id}/chart`: returns `{symbol, timeframe, signal, candles, volumes, trendlines}` from the stored snapshot.

## Environment Context
- Language: Python 3.13 backend, vanilla JS frontend
- Test commands:
  - Python: `PYTHONPATH=. ./venv/bin/pytest tests/ -q`
  - JavaScript: `node --test tests/chart_stream.test.js`
- Working Branch: `feat/signal-win-loss-db` (cut from `main`)
- Database: `signals.db` (git-ignored)

## Task 1: SQLite Signal & Kline Storage Module (signal_tracker.py)
Wave: 1
Status: pending
Risk: low
Dependencies: none
Model: inherit

Files:
- Create: `futures-chart-scanner/signal_tracker.py`
- Create: `futures-chart-scanner/tests/test_signal_tracker.py`

Blast radius:
- `signal_tracker.py`
- `tests/test_signal_tracker.py`

Acceptance:
- `SignalTracker` manages SQLite database connection with WAL mode.
- `save_signal(sig, klines)` inserts a record with initial status `OPEN` and stores klines JSON.
- `get_signal(id)` retrieves the full signal with parsed kline snapshot.
- `list_signals(status_filter=None, limit=50)` returns signals ordered by `created_at DESC`.
- `get_stats()` calculates total trades, wins, losses, open, win_rate %, and net_pnl_r.

TDD:
- Behavior: SignalTracker persists signals and calculates win/loss statistics
- Test file: `tests/test_signal_tracker.py`
- Test name: `test_signal_tracker_crud_and_stats`
- 🔴 RED command: `PYTHONPATH=. ./venv/bin/pytest tests/test_signal_tracker.py::test_signal_tracker_crud_and_stats -q`
- Expected 🔴 RED failure: `ModuleNotFoundError: No module named 'signal_tracker'`
- Minimal 🟢 GREEN change: Implement `SignalTracker` class using `sqlite3` in `signal_tracker.py`

Steps:
1. 🔴 RED: write unit test covering signal creation, retrieval, and stats computation
   Command: `PYTHONPATH=. ./venv/bin/pytest tests/test_signal_tracker.py -q`
   Expected: FAIL
2. 🟢 GREEN: implement `SignalTracker` with schema creation and queries
   Command: `PYTHONPATH=. ./venv/bin/pytest tests/test_signal_tracker.py -q`
   Expected: PASS
3. VERIFY: `PYTHONPATH=. ./venv/bin/pytest tests/test_signal_tracker.py -q`

Checkpoint:
- Files: `signal_tracker.py` `tests/test_signal_tracker.py`
- Commit: `feat(tracker): create sqlite signal persistence and statistics tracker`

## Task 2: Automated Win / Loss Evaluation Engine
Wave: 2
Status: pending
Risk: medium
Dependencies: Task 1
Model: inherit

Files:
- Modify: `futures-chart-scanner/signal_tracker.py`
- Modify: `futures-chart-scanner/tests/test_signal_tracker.py`

Blast radius:
- `signal_tracker.py`
- `tests/test_signal_tracker.py`

Acceptance:
- `evaluate_signal(signal_record, current_candle)` or `evaluate_against_klines(signal_record, klines)`:
  - For LONG: checks if `high >= tp1` (WIN) or `low <= stop_loss` (LOSS).
  - For SHORT: checks if `low <= tp1` (WIN) or `high >= stop_loss` (LOSS).
  - If resolved, updates `status`, `exit_price`, `exit_time`, `pnl_r`, `pnl_pct` in DB and appends the resolution candle to snapshot.
  - If still OPEN, returns `OPEN` with floating PnL.
- Unit tests verify LONG win, LONG loss, SHORT win, SHORT loss, and conservative tie-break.

TDD:
- Behavior: evaluate_signal accurately classifies LONG/SHORT outcomes against price action
- Test file: `tests/test_signal_tracker.py`
- Test name: `test_signal_outcome_evaluation_rules`
- 🔴 RED command: `PYTHONPATH=. ./venv/bin/pytest tests/test_signal_tracker.py::test_signal_outcome_evaluation_rules -q`
- Expected 🔴 RED failure: method `evaluate_signal` does not exist
- Minimal 🟢 GREEN change: implement evaluation rules in `signal_tracker.py`

Steps:
1. 🔴 RED: write comprehensive rule test for LONG/SHORT wins and losses
   Command: `PYTHONPATH=. ./venv/bin/pytest tests/test_signal_tracker.py::test_signal_outcome_evaluation_rules -q`
   Expected: FAIL
2. 🟢 GREEN: implement outcome evaluation logic and DB update
   Command: `PYTHONPATH=. ./venv/bin/pytest tests/test_signal_tracker.py -q`
   Expected: PASS
3. VERIFY: `PYTHONPATH=. ./venv/bin/pytest tests/test_signal_tracker.py -q`

Checkpoint:
- Files: `signal_tracker.py` `tests/test_signal_tracker.py`
- Commit: `feat(tracker): implement automatic win-loss signal outcome evaluation`

## Task 3: Server Integration & REST Endpoints
Wave: 3
Status: pending
Risk: medium
Dependencies: Task 2
Model: inherit

Files:
- Modify: `futures-chart-scanner/server.py`
- Modify: `futures-chart-scanner/tests/test_server.py`

Blast radius:
- `server.py`
- `tests/test_server.py`

Acceptance:
- `WebServerState` initializes `SignalTracker`.
- In `run_scan()`:
  - Evaluates all `OPEN` signals against fresh klines.
  - Records newly discovered qualified signals into `SignalTracker`.
- New REST endpoints:
  - `GET /api/signals`: returns `{signals: [...], stats: {...}}`
  - `GET /api/signals/{id}/chart`: returns stored snapshot candles and signal overlay for that trade.
- `/api/status` includes current `stats` (`win_rate`, `wins`, `losses`, `net_pnl_r`).

TDD:
- Behavior: server endpoints expose signal performance stats and stored historical chart
- Test file: `tests/test_server.py`
- Test name: `test_api_signals_and_historical_chart_endpoints`
- 🔴 RED command: `PYTHONPATH=. ./venv/bin/pytest tests/test_server.py::test_api_signals_and_historical_chart_endpoints -q`
- Expected 🔴 RED failure: 404 for `/api/signals`
- Minimal 🟢 GREEN change: add `/api/signals` and `/api/signals/{id}/chart` handlers in `server.py`

Steps:
1. 🔴 RED: add test for `/api/signals` and `/api/signals/{id}/chart`
   Command: `PYTHONPATH=. ./venv/bin/pytest tests/test_server.py::test_api_signals_and_historical_chart_endpoints -q`
   Expected: FAIL
2. 🟢 GREEN: integrate `SignalTracker` into `server.py` and register routes
   Command: `PYTHONPATH=. ./venv/bin/pytest tests/test_server.py -q`
   Expected: PASS
3. VERIFY: `PYTHONPATH=. ./venv/bin/pytest tests/ -q`

Checkpoint:
- Files: `server.py` `tests/test_server.py`
- Commit: `feat(api): expose signal win-rate stats and historical trade snapshots`

## Task 4: UI Performance Bar, Outcome Badges, and Historical Inspection
Wave: 4
Status: pending
Risk: low
Dependencies: Task 3
Model: inherit

Files:
- Modify: `futures-chart-scanner/static/index.html`
- Modify: `futures-chart-scanner/static/chart_stream.js`
- Test: `futures-chart-scanner/tests/chart_stream.test.js`

Blast radius:
- `static/index.html`
- `static/chart_stream.js`

Acceptance:
- Top metrics bar shows live win-rate pill: `WIN RATE: 70% (14W / 6L) · NET +16.2R`.
- Signal feed header includes tabs: `[ALL]` `[ACTIVE]` `[HISTORY]`.
- Signal cards display status badges:
  - `WIN +2.2R` in green.
  - `LOSS -1.0R` in red.
  - `ACTIVE` in cyan/amber with floating PnL.
- Clicking any signal (active or history) highlights it, shows the trade levels and entry/exit markers.

Steps:
1. Update `static/chart_stream.js` with pure helper for formatting signal badge/stats
2. Add node test in `tests/chart_stream.test.js`
3. Update `static/index.html` UI components and fetch `/api/signals`
4. VERIFY: `node --test tests/chart_stream.test.js` and `PYTHONPATH=. ./venv/bin/pytest tests/ -q`

Checkpoint:
- Files: `static/index.html` `static/chart_stream.js` `tests/chart_stream.test.js`
- Commit: `feat(ui): display win-rate performance bar and trade outcome badges`

## Task 5: Live Browser Verification & Visual Evidence
Wave: 5
Status: pending
Risk: low
Dependencies: Task 4
Model: pro

Files:
- Test: browser live verification via `agent-browser`

Acceptance:
- Run scanner, verify signals are inserted into `signals.db`.
- Trigger evaluation, verify WIN and LOSS badges render with proper colors.
- Verify clicking past signals loads the historical trade chart.
- Capture screenshots for proof.

Steps:
1. Restart local server with updated logic
2. Trigger scan, verify DB entries
3. Verify UI renders win-rate widget and outcome badges
4. Capture screenshots as evidence
