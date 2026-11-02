import aiohttp
import asyncio
from typing import List, Dict, Any, Optional

class BinanceClient:
    def __init__(self, base_url: str = "https://fapi.binance.com"):
        self.base_url = base_url.rstrip("/")
        self._session: Optional[aiohttp.ClientSession] = None
        self.ticker_metrics: Dict[str, Dict[str, float]] = {}

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

    async def get_klines(self, symbol: str, interval: str = "15m", limit: int = 100) -> List[Dict[str, Any]]:
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
        params = {
            "symbol": symbol,
            "interval": interval,
            "limit": limit
        }
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
