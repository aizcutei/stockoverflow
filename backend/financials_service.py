"""Financial data service — quarterly financials, institutional holders, dividends."""

from __future__ import annotations

import logging
import time

import yfinance as yf
import pandas as pd

logger = logging.getLogger("stockoverflow")

_cache: dict[str, dict] = {}
CACHE_TTL = 7200  # 2 hours


def _from_cache(ticker: str, key: str) -> dict | None:
    entry = _cache.get(f"{ticker}:{key}")
    if entry and (time.time() - entry["ts"]) < CACHE_TTL:
        return entry["data"]
    return None


def _to_cache(ticker: str, key: str, data: dict) -> None:
    _cache[f"{ticker}:{key}"] = {"data": data, "ts": time.time()}


def _safe_df(df: pd.DataFrame | None, max_rows: int = 8) -> list[dict]:
    """Convert a DataFrame to a list of dicts, handling NaN."""
    if df is None or df.empty:
        return []
    df = df.head(max_rows)
    df = df.where(pd.notnull(df), None)
    result = []
    for idx, row in df.iterrows():
        record = {"index": str(idx)}
        for col in df.columns:
            val = row[col]
            if val is None:
                record[str(col)] = None
            elif isinstance(val, float):
                record[str(col)] = round(val, 4) if not pd.isna(val) else None
            else:
                record[str(col)] = val
        result.append(record)
    return result


def _safe_series(s: pd.Series | None, max_rows: int = 20) -> list[dict]:
    """Convert a Series to a list of dicts."""
    if s is None or s.empty:
        return []
    s = s.head(max_rows)
    result = []
    for idx, val in s.items():
        record = {"date": str(idx)}
        if isinstance(val, float):
            record["value"] = round(val, 4) if not pd.isna(val) else None
        else:
            record["value"] = val
        result.append(record)
    return result


def get_financials(ticker: str) -> dict:
    """Get quarterly financials (revenue, net income, EPS)."""
    cached = _from_cache(ticker, "financials")
    if cached:
        return cached

    try:
        tk = yf.Ticker(ticker)
        qf = tk.quarterly_financials
        if qf is None or qf.empty:
            return {"ticker": ticker, "data": []}

        # Extract key rows
        rows_to_keep = ["Total Revenue", "Net Income", "EBITDA", "Gross Profit", "Operating Income"]
        available = [r for r in rows_to_keep if r in qf.index]
        if not available:
            # try with different names
            rows_to_keep2 = ["Revenue", "NetIncome", "EBITDA"]
            available = [r for r in rows_to_keep2 if r in qf.index]

        filtered = qf.loc[available] if available else qf.head(5)

        result = {
            "ticker": ticker,
            "periods": [str(c) for c in filtered.columns[:8]],
            "data": [],
        }
        for idx in filtered.index:
            row_data = {"metric": str(idx)}
            for i, col in enumerate(filtered.columns[:8]):
                val = filtered.loc[idx, col]
                row_data[str(col)] = round(float(val), 0) if pd.notna(val) else None
            result["data"].append(row_data)

        _to_cache(ticker, "financials", result)
        return result
    except Exception as e:
        logger.warning("Failed to fetch financials for %s: %s", ticker, e)
        return {"ticker": ticker, "data": [], "error": str(e)}


def get_earnings(ticker: str) -> dict:
    """Get earnings history (EPS actual vs estimate)."""
    cached = _from_cache(ticker, "earnings")
    if cached:
        return cached

    try:
        tk = yf.Ticker(ticker)
        eh = tk.earnings_history
        result = _safe_df(eh)
        out = {"ticker": ticker, "data": result}
        _to_cache(ticker, "earnings", out)
        return out
    except Exception as e:
        logger.warning("Failed to fetch earnings for %s: %s", ticker, e)
        return {"ticker": ticker, "data": [], "error": str(e)}


def get_dividends(ticker: str) -> dict:
    """Get dividend history."""
    cached = _from_cache(ticker, "dividends")
    if cached:
        return cached

    try:
        tk = yf.Ticker(ticker)
        div = tk.dividends
        result = _safe_series(div)
        out = {"ticker": ticker, "data": result}
        _to_cache(ticker, "dividends", out)
        return out
    except Exception as e:
        logger.warning("Failed to fetch dividends for %s: %s", ticker, e)
        return {"ticker": ticker, "data": [], "error": str(e)}


def get_institutional_holders(ticker: str) -> dict:
    """Get institutional holders."""
    cached = _from_cache(ticker, "inst_holders")
    if cached:
        return cached

    try:
        tk = yf.Ticker(ticker)
        ih = tk.institutional_holders
        result = _safe_df(ih)
        out = {"ticker": ticker, "data": result}
        _to_cache(ticker, "inst_holders", out)
        return out
    except Exception as e:
        logger.warning("Failed to fetch institutional holders for %s: %s", ticker, e)
        return {"ticker": ticker, "data": [], "error": str(e)}


def get_financial_summary(ticker: str) -> dict:
    """Get all financial data in one call for LLM context."""
    return {
        "financials": get_financials(ticker),
        "earnings": get_earnings(ticker),
        "dividends": get_dividends(ticker),
        "institutional_holders": get_institutional_holders(ticker),
    }


def get_financials_for_llm(ticker: str) -> str:
    """Get financial data as formatted text for LLM context."""
    data = get_financials(ticker)
    if not data.get("data"):
        return ""

    lines = ["--- Quarterly Financials ---"]
    for row in data["data"]:
        metric = row.get("metric", "")
        vals = []
        for period in data.get("periods", [])[:4]:
            v = row.get(period)
            if v is not None:
                if abs(v) >= 1e9:
                    vals.append(f"{period[:7]}: ${v/1e9:.1f}B")
                elif abs(v) >= 1e6:
                    vals.append(f"{period[:7]}: ${v/1e6:.1f}M")
                else:
                    vals.append(f"{period[:7]}: ${v:.0f}")
        if vals:
            lines.append(f"  {metric}: {' | '.join(vals)}")

    # earnings
    earnings = get_earnings(ticker)
    if earnings.get("data"):
        lines.append("\n--- Recent Earnings ---")
        for e in earnings["data"][:4]:
            eps_actual = e.get("epsActual")
            eps_est = e.get("epsEstimate")
            surprise = e.get("surprise")
            q = e.get("index", e.get("quarter", ""))
            parts = []
            if eps_actual is not None:
                parts.append(f"EPS={eps_actual}")
            if eps_est is not None:
                parts.append(f"Est={eps_est}")
            if surprise is not None:
                parts.append(f"Surprise={surprise}")
            if parts:
                lines.append(f"  {q}: {' | '.join(parts)}")

    return "\n".join(lines) if len(lines) > 1 else ""


def get_options(ticker: str) -> dict:
    """Get options chain data (calls/puts for nearest expiry)."""
    cached = _from_cache(ticker, "options")
    if cached:
        return cached

    try:
        tk = yf.Ticker(ticker)
        expirations = tk.options
        if not expirations:
            return {"ticker": ticker, "expirations": [], "data": None}

        nearest = expirations[0]
        chain = tk.option_chain(nearest)

        calls = _safe_df(chain.calls, max_rows=20)
        puts = _safe_df(chain.puts, max_rows=20)

        out = {
            "ticker": ticker,
            "nearest_expiry": nearest,
            "total_expirations": len(expirations),
            "expirations": list(expirations[:10]),
            "calls": calls,
            "puts": puts,
        }
        _to_cache(ticker, "options", out)
        return out
    except Exception as e:
        logger.warning("Failed to fetch options for %s: %s", ticker, e)
        return {"ticker": ticker, "error": str(e)}


def get_peer_comparison(ticker: str) -> dict:
    """Get basic peer comparison using sector/industry."""
    cached = _from_cache(ticker, "peers")
    if cached:
        return cached

    try:
        tk = yf.Ticker(ticker)
        info = tk.info or {}
        sector = info.get("sector", "")
        industry = info.get("industry", "")

        # find peers via yfinance screener
        peers_info = []
        for peer_ticker in info.get("companyOfficers", [])[:0]:  # placeholder
            pass

        # alternative: use sector ETF as benchmark
        sector_etfs = {
            "Technology": "XLK", "Healthcare": "XLV", "Financial Services": "XLF",
            "Consumer Cyclical": "XLY", "Consumer Defensive": "XLP", "Energy": "XLE",
            "Industrials": "XLI", "Basic Materials": "XLB", "Real Estate": "XLRE",
            "Utilities": "XLU", "Communication Services": "XLC",
        }
        etf = sector_etfs.get(sector)

        out = {
            "ticker": ticker,
            "sector": sector,
            "industry": industry,
            "sector_etf": etf,
            "peers": [],  # would need additional API for full peer list
        }
        _to_cache(ticker, "peers", out)
        return out
    except Exception as e:
        logger.warning("Failed to fetch peers for %s: %s", ticker, e)
        return {"ticker": ticker, "error": str(e)}
