"""Multi-source data fetcher with automatic failover.

Priority: yfinance → Alpha Vantage (free tier) → Twelve Data (free tier)
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

logger = logging.getLogger("stockoverflow")

# Cache for API keys (loaded from env or config)
_api_keys: dict[str, str] = {}


def _get_api_key(provider: str) -> str:
    """Get API key from environment."""
    import os
    keys = {
        "alphavantage": os.environ.get("ALPHAVANTAGE_API_KEY", ""),
        "twelvedata": os.environ.get("TWELVEDATA_API_KEY", ""),
    }
    return keys.get(provider, "")


def fetch_stock_data_yfinance(ticker: str, period: str = "5y") -> list[dict] | None:
    """Fetch from yfinance (primary source)."""
    try:
        import yfinance as yf
        import math

        tk = yf.Ticker(ticker)
        hist = tk.history(period=period, interval="1d")
        if hist.empty:
            return None

        candles = []
        for dt, row in hist.iterrows():
            o, h, l, c = float(row["Open"]), float(row["High"]), float(row["Low"]), float(row["Close"])
            v = float(row["Volume"])
            if any(math.isnan(x) for x in (o, h, l, c, v)):
                continue
            candles.append({
                "date": dt.strftime("%Y-%m-%d"),
                "open": round(o, 4),
                "high": round(h, 4),
                "low": round(l, 4),
                "close": round(c, 4),
                "volume": int(v),
            })
        return candles if candles else None
    except Exception as e:
        logger.warning("yfinance failed for %s: %s", ticker, e)
        return None


def fetch_stock_data_alphavantage(ticker: str) -> list[dict] | None:
    """Fetch from Alpha Vantage (fallback)."""
    api_key = _get_api_key("alphavantage")
    if not api_key:
        return None

    try:
        url = f"https://www.alphavantage.co/query?function=TIME_SERIES_DAILY&symbol={ticker}&outputsize=full&apikey={api_key}"
        resp = httpx.get(url, timeout=15)
        data = resp.json()

        ts = data.get("Time Series (Daily)")
        if not ts:
            return None

        candles = []
        for date_str, values in sorted(ts.items()):
            try:
                candles.append({
                    "date": date_str,
                    "open": round(float(values["1. open"]), 4),
                    "high": round(float(values["2. high"]), 4),
                    "low": round(float(values["3. low"]), 4),
                    "close": round(float(values["4. close"]), 4),
                    "volume": int(float(values["5. volume"])),
                })
            except (KeyError, ValueError):
                continue
        return candles if candles else None
    except Exception as e:
        logger.warning("Alpha Vantage failed for %s: %s", ticker, e)
        return None


def fetch_stock_data(ticker: str, period: str = "5y") -> tuple[list[dict] | None, str]:
    """Fetch stock data with automatic failover.

    Returns: (candles, source_name) or (None, "none")
    """
    # 1. Try yfinance
    result = fetch_stock_data_yfinance(ticker, period)
    if result:
        return result, "yfinance"

    # 2. Try Alpha Vantage
    result = fetch_stock_data_alphavantage(ticker)
    if result:
        return result, "alphavantage"

    return None, "none"
