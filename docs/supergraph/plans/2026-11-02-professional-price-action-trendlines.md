# Plan: Professional Price Action Trendlines & Clean Chart Overlays

## Problem Statement
The current trendline algorithm in `technical_engine.py` generates nonsensical lines on real futures charts:
1. **Fake touch counting**: It iterates every single candle and increments `touches += 1` if the wick is within 0.5% of the line. On a 100-bar chart, sideways consolidation causes 40–93 bars to be flagged as "touches".
2. **Candle body piercing**: The violation check only tests `close > line * (1 + tol)`. Candle bodies pierce right through the line without invalidating it.
3. **Noisy anchors**: Micro swing points (3 bars apart) are extended across 100 bars, creating steep chords cutting across the middle of price action.
4. **Flawed selection**: `select_strongest_trendlines` sorts by `-touches`, meaning lines that slice through the most consolidation bars are chosen as the "best" trendlines.

## Analysis Decisions
- **Swing-based touches**: Touches are ONLY counted when a recognized `SwingPoint` (peak or trough) tests the line within tolerance. Distinct swing touches are typically 2, 3, or 4 — never 40+.
- **Strict no-pierce invariant**:
  - Resistance line: for every bar from anchor 1 to current, `max(open, close) <= line_val * (1 + 0.001)` (candle bodies MUST remain under the line).
  - Support line: for every bar from anchor 1 to current, `min(open, close) >= line_val * (1 - 0.001)` (candle bodies MUST remain above the line).
- **Minimum anchor span**: `p2.index - p1.index >= 5` bars to prevent micro-fluctuation slope exaggeration.
- **Active structural relevance ranking**:
  - Validated touches (3+ confirmed touches).
  - Anchor 2 recency (trendlines anchoring recent waves take precedence over ancient broken lines).
  - Slope sanity (resistance lines slope downward or near-horizontal; support lines slope upward or near-horizontal).
  - Clean fit / minimal residual.
- **Frontend / UI rendering**:
  - Show the primary descending resistance line (in gold `#f5b84b`) and primary ascending support line (in cyan `#65cfff`).
  - Signal descriptions and badges display realistic touch counts (e.g. `3 touches`, `4 touches`).

## Environment Context
- Language: Python 3.13 backend, vanilla JS frontend
- Test commands:
  - Python: `PYTHONPATH=. ./venv/bin/pytest tests/ -q`
  - JavaScript: `node --test tests/chart_stream.test.js`
- Working Branch: `feat/clean-trendlines` (cut from `main`)
- Affected files: `technical_engine.py`, `server.py`, `tests/test_technical_engine.py`, `tests/test_server.py`, `tests/chart_stream.test.js`

## Task 1: Strict Body-Piercing and Swing-Touch Trendline Algorithm
Wave: 1
Status: pending
Risk: medium
Dependencies: none
Model: inherit

Files:
- Modify: `futures-chart-scanner/technical_engine.py`
- Test: `futures-chart-scanner/tests/test_technical_engine.py`

Blast radius:
- `technical_engine.py`
- `tests/test_technical_engine.py`

Acceptance:
- `detect_trendlines` only counts actual `SwingPoint` occurrences as touches.
- Candle bodies (`max(open, close)` for resistance, `min(open, close)` for support) that pierce beyond the line invalidate it.
- Trendlines on real 100-bar charts have realistic touch counts (2 to 6 touches, never > 10).
- `select_strongest_trendlines` ranks by: confirmed touches (>=3 prioritized), anchor 2 recency, span length, and residual.

TDD:
- Behavior: trendlines reject body piercing and only count swing points as touches
- Test file: `tests/test_technical_engine.py`
- Test name: `test_trendline_rejects_body_piercing_and_counts_only_swing_touches`
- 🔴 RED command: `PYTHONPATH=. ./venv/bin/pytest tests/test_technical_engine.py::test_trendline_rejects_body_piercing_and_counts_only_swing_touches -q`
- Expected 🔴 RED failure: current implementation counts all intermediate candle bars and permits body piercing
- Minimal 🟢 GREEN change: rewrite `detect_trendlines` touch counter and violation loop in `technical_engine.py`

Steps:
1. 🔴 RED: write test with a pierced trendline (should be rejected) and a 3-swing test (touches == 3)
   Command: `PYTHONPATH=. ./venv/bin/pytest tests/test_technical_engine.py::test_trendline_rejects_body_piercing_and_counts_only_swing_touches -q`
   Expected: FAIL
2. 🟢 GREEN: implement strict body check and swing-only touch counting in `detect_trendlines`
   Command: `PYTHONPATH=. ./venv/bin/pytest tests/test_technical_engine.py -q`
   Expected: PASS
3. REFACTOR: clean up slope limits and tolerance calculations
4. VERIFY: `PYTHONPATH=. ./venv/bin/pytest tests/test_technical_engine.py -q`

Checkpoint:
- Files: `technical_engine.py` `tests/test_technical_engine.py`
- Commit: `fix(engine): enforce strict body piercing and swing-only trendline touches`

## Task 2: Server & UI Integration with Clean Trendlines
Wave: 2
Status: pending
Risk: low
Dependencies: Task 1
Model: inherit

Files:
- Modify: `futures-chart-scanner/server.py`
- Modify: `futures-chart-scanner/static/chart_stream.js`
- Test: `futures-chart-scanner/tests/test_server.py`
- Test: `futures-chart-scanner/tests/chart_stream.test.js`

Blast radius:
- `server.py`
- `static/chart_stream.js`

Acceptance:
- `build_structure_payload` formats trendlines with correct anchor indices and verified slope coordinates.
- WebSocket stream and REST `/api/chart` emit clean trendlines with realistic touches.
- Signal generator creates realistic descriptions (e.g. `Breakout over Resistance Trendline (3 touches)`).
- Frontend renders the clean resistance (gold) and support (cyan) lines without clutter.

TDD:
- Behavior: structure payload emits valid non-piercing trendlines with clean coordinates
- Test file: `tests/test_server.py`
- Test name: `test_structure_payload_trendlines_have_realistic_touches`
- 🔴 RED command: `PYTHONPATH=. ./venv/bin/pytest tests/test_server.py::test_structure_payload_trendlines_have_realistic_touches -q`
- Expected 🔴 RED failure: assertion on realistic touch count fails or missing test
- Minimal 🟢 GREEN change: ensure `select_strongest_trendlines` is applied in `build_structure_payload`

Steps:
1. 🔴 RED: write test checking structure payload trendlines
   Command: `PYTHONPATH=. ./venv/bin/pytest tests/test_server.py::test_structure_payload_trendlines_have_realistic_touches -q`
   Expected: FAIL
2. 🟢 GREEN: wire cleaned trendlines into `build_structure_payload`
   Command: `PYTHONPATH=. ./venv/bin/pytest tests/test_server.py -q`
   Expected: PASS
3. VERIFY: `PYTHONPATH=. ./venv/bin/pytest tests/ -q` and `node --test tests/chart_stream.test.js`

Checkpoint:
- Files: `server.py` `tests/test_server.py`
- Commit: `feat(scanner): stream clean price-action trendlines to client`

## Task 3: Browser Verification & Visual Quality Check
Wave: 3
Status: pending
Risk: low
Dependencies: Task 2
Model: pro

Files:
- Test: browser live verification via `agent-browser`

Acceptance:
- Live chart on `http://127.0.0.1:8766` shows natural, professional trendlines framing price action.
- No lines cutting through candle bodies.
- Signal cards and chart markers display realistic touch counts (e.g., 3-4 touches).
- Switching coins (BTC, ETH, SOL) produces clean price action lines.
- Full screenshot captured as evidence.

Steps:
1. Restart local server with updated logic
2. Open browser session and inspect BTCUSDT, ETHUSDT, SOLUSDT
3. Capture full screenshot showing clean trendlines
4. Verify all tests pass

Checkpoint:
- Commit: `docs(scanner): capture clean trendline verification evidence`
