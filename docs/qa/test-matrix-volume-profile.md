# QA Matrix — Fixed Trusted-Coin Universe and Purge Safety

Target: `http://127.0.0.1:8766/`
Whitelist: BTCUSDT, ETHUSDT, BNBUSDT, SOLUSDT, XRPUSDT.
Destructive scope: only local manual CLI purge of non-whitelist `signals` rows (including OPEN and embedded kline_snapshot), never automatically and never via HTTP.

## Browser/API evidence
- Authorized app restart loaded current code.
- `/api/symbols`: exactly five selected whitelist symbols; no `all_symbols` field.
- Picker `<select>`: exactly five options; `allSymbols` state removed.
- `/api/chart?symbol=DOGEUSDT&timeframe=15m`: HTTP 400 JSON `{error:"symbol_not_in_universe"}`.
- Historical DOGE/PAXG signal chart remains available by ID; UI source guards `connectMarketWs` and reconnect timer against `viewingHistorical` or non-whitelist membership.
- Production `signals.db` was not touched; manual purge CLI was tested only against `/tmp` temporary test DBs.

| ID | Dimension | Scenario | Expected | Latest evidence | Status |
|---|---|---|---|---|---|
| U-01 | Universe | Refresh live symbols | Exact fixed five; no dynamic ranking | API returned five symbols; client and server tests pass | PASS |
| U-02 | Picker | Search/watchlist | Only fixed five; no legacy all-symbol source | DOM select has five options; snapshot confirms | PASS |
| U-03 | Live chart | Request DOGE chart | HTTP 400 `symbol_not_in_universe`; no candle request | Browser route returned 400 JSON | PASS |
| U-04 | Live WebSocket | Subscribe DOGE | HTTP 400 before WS upgrade; whitelist not mutated | Server aiohttp handshake regression passes | PASS (unit/integration) |
| U-05 | History | View archived DOGE/PAXG chart | Remains viewable; no live socket/reconnect | Historical route test + source guard test pass | PASS (unit/integration) |
| U-06 | Legacy OPEN | Small-coin OPEN | Hidden from live active state; `/api/signals?status=OPEN` shows `NOT_MONITORED`; row remains until manual purge | Server temp-DB test and dashboard badge/source test pass | PASS (unit) |
| P-01 | Purge preview | Temp DB with BTC+DOGE OPEN | Lists DOGE/OPEN; preview only, DB unchanged | CLI preview showed one DOGE OPEN and no mutation | PASS (temp DB) |
| P-02 | Purge confirmation | Wrong token | Abort, no backup/delete | Unit test asserts unchanged rows and no purge backup | PASS (temp DB) |
| P-03 | Purge apply | Typed PURGE on temp DB | Backup integrity validated, DOGE incl OPEN deleted, BTC preserved | Temp-DB tests pass, no production DB involved | PASS (temp DB) |
| P-04 | Failure | Backup/integrity/count drift/transaction exception | Abort/rollback, source rows intact | Temp-DB regression tests pass | PASS (temp DB) |
| P-05 | Exposure | HTTP route enumeration | No purge HTTP route | Server route test passes | PASS |
| P-06 | Retention | Verified backups | Never auto-pruned | CLI has no retention cleanup; temp backup test passes | PASS |
| U-07 | Regression | Whole repository | Tests/compile green; history still readable | Latest full suite 128 Python + 48 Node; py_compile + diff-check pass | PASS |

## Known limitations
- Excluded OPEN signals stop getting TP/SL/PnL tracking immediately when whitelist is applied; they are surfaced as NOT MONITORED until manually purged.
- Production purge has not been run. Future operator must run preview, inspect full candidate summary, then explicitly run `--apply` and type `PURGE`; verified backup is mandatory and retained indefinitely.
- Browser tool cannot change viewport to 390x844 or run axe-core in this environment; unit test covers the 390px histogram width cap, but physical mobile layout/accessibility audit remains unverified.
- Do not use a dynamic top-15/quoteVolume universe. The whitelist is static and exact.
