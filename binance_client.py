import aiohttp
import asyncio
from typing import List, Dict, Any, Optional

class BinanceClient:
    def __init__(self, base_url: str = "https://fapi.binance.com"):
        self.base_url = base_url.rstrip("/")
        self._session: Optional[aiohttp.ClientSession] = None

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
        """
        Fetch all 24hr tickers from Binance USDT-M Futures,
        filter only USDT quote asset, and return top symbols sorted by quoteVolume descending.
        """
        url = f"{self.base_url}/fapi/v1/ticker/24hr"
        try:
            data = await self._fetch_json(url)
            usdt_tickers = [
                item for item in data 
                if item.get("symbol", "").endswith("USDT")
            ]
            usdt_tickers.sort(
                key=lambda x: float(x.get("quoteVolume", 0)), 
                reverse=True
            )
            return [item["symbol"] for item in usdt_tickers[:limit]]
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
