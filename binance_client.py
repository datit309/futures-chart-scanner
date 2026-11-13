import aiohttp
import asyncio
import math
import re
import time
from typing import List, Dict, Any, Optional

class BinanceClient:
    def __init__(self, base_url: str = "https://fapi.binance.com"):
        self.base_url = base_url.rstrip("/")
        self._session: Optional[aiohttp.ClientSession] = None
        self.ticker_metrics: Dict[str, Dict[str, float]] = {}
        self._aggtrades_semaphore = asyncio.Semaphore(1)
        self._aggtrades_last_request_at = 0.0

    async def get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=15)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    async def _fetch_json(self, url: str, params: Optional[Dict[str, Any]] = None) -> Any:
        session = await self.get_session()
        async with session.get(url, params=params) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def get_top_futures_symbols(self, limit: int = 30) -> List[str]:
        """Return active USDT perpetual symbols ranked by 24h quote volume.

        The matching 24h ticker metrics are retained in ``ticker_metrics``.
        A contract remains eligible when its ticker is temporarily absent.
        """
        try:
            exchange_info = await self._fetch_json(f"{self.base_url}/fapi/v1/exchangeInfo")
            tickers = await self._fetch_json(f"{self.base_url}/fapi/v1/ticker/24hr")
            ticker_by_symbol = {
                item.get("symbol"): item for item in tickers
                if isinstance(item, dict) and item.get("symbol")
            }
            eligible = []
            self.ticker_metrics = {}
            for contract in exchange_info.get("symbols", []):
                if (
                    contract.get("status") != "TRADING"
                    or contract.get("contractType") != "PERPETUAL"
                    or contract.get("quoteAsset") != "USDT"
                ):
                    continue
                symbol = contract["symbol"]
                ticker = ticker_by_symbol.get(symbol)
                volume = float(ticker.get("quoteVolume", 0)) if ticker else 0.0
                self.ticker_metrics[symbol] = {
                    "lastPrice": float(ticker.get("lastPrice", 0)) if ticker else 0.0,
                    "priceChangePercent": float(ticker.get("priceChangePercent", 0)) if ticker else 0.0,
                    "quoteVolume": volume,
                }
                eligible.append((volume, symbol))
            eligible.sort(key=lambda row: (-row[0], row[1]))
            self.ticker_metrics = {symbol: self.ticker_metrics[symbol] for _, symbol in eligible}
            return [symbol for _, symbol in eligible[:limit]]
        except Exception as e:
            print(f"[BinanceClient] Error fetching top symbols: {e}")
            return []

    async def get_klines(self, symbol: str, interval: str = "15m", limit: int = 500, endTime: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Fetch OHLCV candlesticks for a specific symbol.
        Format:
        [
          [
            1499040000000,      // Open time
            "0.01634790",       // Open
            "0.80000000",       // High
            "0.01575800",       // Low
            "0.01577100",       // Close
            "148976.11427815",  // Volume
            1499644799999,      // Close time
            ...
          ]
        ]
        """
        url = f"{self.base_url}/fapi/v1/klines"
        params: Dict[str, Any] = {
            "symbol": symbol,
            "interval": interval,
            "limit": min(limit, 1500)
        }
        if endTime is not None:
            params["endTime"] = endTime
        try:
            raw_klines = await self._fetch_json(url, params=params)
            formatted = []
            for k in raw_klines:
                formatted.append({
                    "timestamp": int(k[0]),
                    "open": float(k[1]),
                    "high": float(k[2]),
                    "low": float(k[3]),
                    "close": float(k[4]),
                    "volume": float(k[5]),
                    "close_time": int(k[6])
                })
            return formatted
        except Exception as e:
            print(f"[BinanceClient] Error fetching klines for {symbol}: {e}")
            return []

    async def get_aggregate_trades(
        self,
        symbol: str,
        start_time_ms: int,
        end_time_ms: int,
        *,
        page_cap: int = 20,
        page_size: int = 1000,
        start_boundary_tolerance_ms: int = 300_000,
        timeout_seconds: float = 25.0,
        retry_base_seconds: float = 0.15,
        min_request_interval: float = 0.1,
    ) -> Dict[str, Any]:
        """Fetch a bounded rolling window of actual Binance USD-M aggregate trades.

        Page 1 is anchored by startTime/endTime. Subsequent pages MUST use
        fromId only (Binance rejects combining cursor and time filters). Since
        aggTrade ids are not a time index, completeness is claimed only if the
        first returned trade is within start_boundary_tolerance_ms of start.
        """
        symbol = str(symbol or "").upper()
        if not re.fullmatch(r"[A-Z0-9]{2,30}USDT", symbol):
            raise ValueError("invalid_symbol")
        start_ms = int(start_time_ms)
        end_ms = int(end_time_ms)
        page_cap = max(1, min(int(page_cap), 20))
        page_size = max(1, min(int(page_size), 1000))
        if start_ms < 0 or end_ms <= start_ms:
            raise ValueError("invalid_time_window")

        result: Dict[str, Any] = {
            "symbol": symbol,
            "window_start_ms": start_ms,
            "window_end_ms": end_ms,
            "partial": False,
            "partial_reason": None,
            "pages": 0,
            "trade_count": 0,
            "oldest_trade_time": None,
            "newest_trade_time": None,
            "start_covered": False,
            "caught_up": False,
            "trades": [],
        }
        endpoint = f"{self.base_url}/fapi/v1/aggTrades"
        unique: Dict[int, Dict[str, Any]] = {}
        deadline = time.monotonic() + max(0.05, float(timeout_seconds))
        next_from_id: Optional[int] = None
        previous_page_last_id: Optional[int] = None
        first_valid_row = True
        pages_used = 0

        acquired = False
        try:
            await asyncio.wait_for(
                self._aggtrades_semaphore.acquire(),
                timeout=max(0.001, deadline - time.monotonic()),
            )
            acquired = True
            if time.monotonic() >= deadline:
                self._aggtrades_semaphore.release()
                acquired = False
                result["partial"] = True
                result["partial_reason"] = "timeout"
        except asyncio.TimeoutError:
            result["partial"] = True
            result["partial_reason"] = "timeout"

        try:
            while acquired and pages_used < page_cap:
                if time.monotonic() >= deadline:
                    result["partial"] = True
                    result["partial_reason"] = "timeout"
                    break

                delay = float(min_request_interval) - (time.monotonic() - self._aggtrades_last_request_at)
                if delay > 0:
                    if time.monotonic() + delay >= deadline:
                        result["partial"] = True
                        result["partial_reason"] = "timeout"
                        break
                    await asyncio.sleep(delay)
                self._aggtrades_last_request_at = time.monotonic()

                if next_from_id is None:
                    params = {"symbol": symbol, "startTime": start_ms, "endTime": end_ms, "limit": page_size}
                else:
                    params = {"symbol": symbol, "fromId": next_from_id, "limit": page_size}

                page: Any = None
                for attempt in range(3):
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        result["partial"] = True
                        result["partial_reason"] = "timeout"
                        break
                    try:
                        page = await asyncio.wait_for(self._fetch_json(endpoint, params=params), timeout=remaining)
                    except asyncio.TimeoutError:
                        result["partial"] = True
                        result["partial_reason"] = "timeout"
                        break
                    except Exception as exc:
                        # Retry only transient HTTP 429/418/5xx. Other failures are final.
                        status = getattr(getattr(exc, "status", None), "status", None) or getattr(exc, "status", None)
                        if status not in (418, 429, 500, 502, 503, 504) or attempt >= 2:
                            result["partial"] = True
                            result["partial_reason"] = "upstream_error"
                            break
                        retry_after = getattr(exc, "headers", None) or {}
                        try:
                            retry_delay = min(max(float(retry_after.get("Retry-After", 0)), 0.0), 2.0)
                        except (TypeError, ValueError):
                            retry_delay = 0.0
                        backoff = max(retry_delay, min(float(retry_base_seconds) * (2 ** attempt), 2.0))
                        if time.monotonic() + backoff >= deadline:
                            result["partial"] = True
                            result["partial_reason"] = "timeout"
                            break
                        await asyncio.sleep(backoff)
                    else:
                        # Unit fakes may return a status-like object instead of raising aiohttp errors.
                        response_status = getattr(page, "status", 200)
                        if response_status == 200:
                            break
                        if response_status in (418, 429, 500, 502, 503, 504) and attempt < 2:
                            headers = getattr(page, "headers", None) or {}
                            try:
                                retry_delay = min(max(float(headers.get("Retry-After", 0)), 0.0), 2.0)
                            except (TypeError, ValueError):
                                retry_delay = 0.0
                            await asyncio.sleep(max(retry_delay, min(float(retry_base_seconds) * (2 ** attempt), 2.0)))
                            page = None
                            continue
                        result["partial"] = True
                        result["partial_reason"] = "upstream_error"
                        page = None
                        break
                if result["partial_reason"] in ("timeout", "upstream_error"):
                    break

                if not isinstance(page, list):
                    result["partial"] = True
                    result["partial_reason"] = "malformed_rows"
                    break

                # A repeated/backward cursor is not a valid caught-up condition.
                if page and previous_page_last_id is not None:
                    try:
                        returned_ids = [int(row["a"]) for row in page]
                    except (KeyError, TypeError, ValueError, OverflowError):
                        returned_ids = []
                    if returned_ids and max(returned_ids) <= previous_page_last_id:
                        result["partial"] = True
                        result["partial_reason"] = "no_progress"
                        break

                pages_used += 1
                result["pages"] = pages_used
                if not page:
                    if first_valid_row:
                        # Empty time-bound query cannot prove the requested start boundary.
                        result["partial"] = True
                        result["partial_reason"] = "start_uncovered"
                    result["caught_up"] = True
                    break

                page_ids: List[int] = []
                page_times: List[int] = []
                malformed = False
                for row in page:
                    try:
                        trade_id = int(row["a"])
                        price = float(row["p"])
                        quantity = float(row["q"])
                        timestamp = int(row["T"])
                        if trade_id < 0 or not math.isfinite(price) or price <= 0 or not math.isfinite(quantity) or quantity < 0 or timestamp < 0:
                            raise ValueError("invalid trade values")
                    except (KeyError, TypeError, ValueError, OverflowError):
                        malformed = True
                        continue
                    page_ids.append(trade_id)
                    page_times.append(timestamp)
                    if start_ms <= timestamp <= end_ms:
                        unique[trade_id] = {"id": trade_id, "price": price, "quantity": quantity, "timestamp": timestamp}

                if malformed:
                    result["partial"] = True
                    result["partial_reason"] = "malformed_rows"

                if page_ids != sorted(page_ids) or len(set(page_ids)) != len(page_ids):
                    result["partial"] = True
                    result["partial_reason"] = "no_progress"
                    break

                if first_valid_row:
                    if page_times:
                        first_time = min(page_times)
                        result["start_covered"] = (start_ms <= first_time <= start_ms + start_boundary_tolerance_ms)
                        if not result["start_covered"]:
                            result["partial"] = True
                            result["partial_reason"] = "start_uncovered"
                    else:
                        result["partial"] = True
                        result["partial_reason"] = "malformed_rows"
                    first_valid_row = False
                elif previous_page_last_id is not None and next_from_id is not None and page_ids and page_ids[0] < next_from_id:
                    # Inclusive/overlap ids are permitted only as duplicates; new rows must advance.
                    if max(page_ids) <= previous_page_last_id:
                        result["partial"] = True
                        result["partial_reason"] = "no_progress"
                        break

                if page_times and max(page_times) >= end_ms:
                    result["caught_up"] = True
                    break

                max_page_id = max(page_ids) if page_ids else None
                if max_page_id is None or (previous_page_last_id is not None and max_page_id <= previous_page_last_id):
                    result["partial"] = True
                    result["partial_reason"] = "no_progress"
                    break

                if len(page) < page_size:
                    result["caught_up"] = True
                    break
                previous_page_last_id = max_page_id
                next_from_id = max_page_id + 1

            if pages_used >= page_cap and not result["caught_up"] and not result["partial_reason"]:
                result["partial"] = True
                result["partial_reason"] = "page_cap"

        finally:
            if acquired:
                self._aggtrades_semaphore.release()
        trades = sorted(unique.values(), key=lambda row: (row["timestamp"], row["id"]))
        result["trades"] = trades
        result["trade_count"] = len(trades)
        result["oldest_trade_time"] = trades[0]["timestamp"] if trades else None
        result["newest_trade_time"] = trades[-1]["timestamp"] if trades else None
        result["complete"] = bool(result["start_covered"] and result["caught_up"] and not result["partial"])
        if not result["complete"]:
            result["partial"] = True
            if not result["partial_reason"]:
                result["partial_reason"] = "start_uncovered" if not result["start_covered"] else "page_cap"
        return result

    async def get_open_interest(self, symbol: str) -> float:
        """Fetch current open interest from Binance Futures public API."""
        url = f"{self.base_url}/fapi/v1/openInterest"
        try:
            data = await self._fetch_json(url, params={"symbol": symbol})
            return float(data.get("openInterest", 0.0))
        except Exception as e:
            print(f"[BinanceClient] Error fetching open interest for {symbol}: {e}")
            return 0.0

    async def get_funding_rate(self, symbol: str) -> float:
        """Fetch latest funding rate from Binance Futures premiumIndex endpoint."""
        url = f"{self.base_url}/fapi/v1/premiumIndex"
        try:
            data = await self._fetch_json(url, params={"symbol": symbol})
            return float(data.get("lastFundingRate", 0.0))
        except Exception as e:
            print(f"[BinanceClient] Error fetching funding rate for {symbol}: {e}")
            return 0.0

