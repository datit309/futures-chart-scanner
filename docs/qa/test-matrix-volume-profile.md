# QA Matrix — aggTrades Volume Profile

Target: `http://127.0.0.1:8766/`
Feature: opt-in Binance USDⓈ-M aggTrades 24h horizontal Volume Profile
Data contract: `/api/volume-profile?symbol=BTCUSDT`; raw trades + coverage; 20-page/20,000-trade ceiling; browser computes bins/POC/70% VA.

## Environment note
On 2026-11-13 the authorized app restart loaded the route; direct GET returned HTTP 200 JSON. The live browser then fetched 20,000 real BTC aggTrades, got `partial_reason=page_cap`, and rendered a visibly partial profile. The JSON response was about 1.70 MB and took 2.7–3.8 seconds. Binance upstream was reachable from the server. The browser tool does not expose a viewport-resize control; requested 390x844 case could not be exercised (open extraArgs were ignored, viewport stayed 1280x633).

| ID | Dimension | Scenario | Expected | Latest evidence | Status |
|---|---|---|---|---|---|
| VP-01 | Happy path | Enable overlay; live route returns 24h aggTrades | Histogram, POC/VAH/VAL, coverage state | Live response HTTP 200, 20k raw trades (~1.70 MB, 2.7–3.8s), bins/levels rendered; live dataset is partial by cap | PASS (partial live data) |
| VP-02 | Partial | Endpoint returns `page_cap` trades | Available profile remains visible with coverage duration | Browser displayed 20,000 trades and “PHỦ 39–43 PHÚT”; screenshot captured | PASS |
| VP-03 | Empty | Empty response / zero valid trades | “CHƯA CÓ GIAO DỊCH”, no profile bars | Unit coverage only | PASS (unit) |
| VP-04 | Error | Browser offline while enabling overlay | “LỖI TẢI”; canvas clears; app remains usable | Offline browser toggle showed error state and did not break chart | PASS |
| VP-05 | Boundary | `start_uncovered` and 20-page cap | Partial reason displayed, no complete label | Backend fixtures pass; live cap observed | PASS |
| VP-06 | Resilience | Select symbol while prior fetch in flight | Prior AbortController aborts and stale data cannot paint | Controller unit test pass | PASS (unit) |
| VP-07 | Performance | Toggle/timeframe/range changes | 60s client cache; no refetch per tick/interval | Controller cache unit test pass; no per-tick request seen | PASS (unit + spot check) |
| VP-08 | Security | Invalid symbol / hostile URL text | HTTP 400; upstream fixed host not controlled by input | Browser probe `symbol=BAD` => 400 `invalid_symbol`; unit test verifies URL input never reaches upstream | PASS |
| VP-09 | Responsive | Desktop and 390x844 mobile | Profile width capped; no horizontal page overflow | Desktop viewport 1280x633, overflow false; 390 viewport unavailable (tool ignored `--window-size`) | PARTIAL |
| VP-10 | Accessibility | Toggle has accessible name/state; status announced | Checkbox named and `role=status` / `aria-live=polite` | Accessibility tree names checkbox; status role live region present; axe audit not available | PARTIAL |
| VP-11 | Regression | Other volume toggle, signal scan unaffected | Volume surge and signal flow remain unchanged | Full tests 104 Python + 44 Node pass; scan path not changed by feature | PASS (tests) |

## Remaining QA gaps
- Complete-status fixture not run because live BTC reaches the 20,000-trade cap in 24h and is correctly partial.
- 390x844 responsive viewport and axe-core audit remain unverified because the active MCP browser tool did not expose viewport or a11y commands in this runtime.

## Unit verification evidence
- `PYTHONPATH=. ./venv/bin/pytest tests/ -q`: 105 passed at latest verification.
- `node --test tests/chart_stream.test.js`: 46 passed at latest verification (includes browser-cache eviction, partial-duration badge, and 390px renderer width-cap tests).
- `python3 -m py_compile ...`: passed.
- Live mounted route verified HTTP 200 after authorized restart; it returned a correctly partial 20k-trade dataset. Desktop screenshot shows partial badge/profile; mobile viewport and axe audit not run. Largest observed response: ~1.70 MB / 20k trades.
