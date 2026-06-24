"""CNN Fear & Greed Index — fetch, cache, and format.

Source: https://production.dataviz.cnn.io/index/fearandgreed/graphdata
Market-wide indicator, not stock-specific. Cached for 30 minutes.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

import httpx

CNN_URL = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
CNN_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Referer": "https://www.cnn.com/markets/fear-and-greed",
    "Origin": "https://www.cnn.com",
}

# in-memory cache: { "data": ..., "ts": epoch }
_cache: dict = {}
CACHE_TTL = 1800  # 30 minutes


def _rating_signal(rating: str) -> str:
    """Map CNN rating to BUY/SELL/WATCH/NEUTRAL."""
    r = rating.lower()
    if "extreme fear" in r:
        return "BUY"       # contrarian: extreme fear → opportunity
    elif "fear" in r:
        return "WATCH"
    elif "extreme greed" in r:
        return "SELL"       # contrarian: extreme greed → caution
    elif "greed" in r:
        return "WATCH"
    return "NEUTRAL"


def _strength_from_score(score: float) -> float:
    """Convert 0-100 score to 0-100 strength (distance from 50)."""
    return round(abs(score - 50) * 2, 1)


def fetch_fear_greed() -> dict:
    """Fetch CNN Fear & Greed data, return formatted indicator dict."""
    global _cache

    # serve from cache if fresh
    if _cache.get("data") and (time.time() - _cache["ts"]) < CACHE_TTL:
        return _cache["data"]

    try:
        resp = httpx.get(CNN_URL, headers=CNN_HEADERS, timeout=10, follow_redirects=True)
        resp.raise_for_status()
        raw = resp.json()
    except Exception as e:
        # if fetch fails but we have stale cache, use it
        if _cache.get("data"):
            return _cache["data"]
        return _error_result(str(e))

    result = _format(raw)
    _cache = {"data": result, "ts": time.time()}
    return result


def _format(raw: dict) -> dict:
    """Format raw CNN data into our standard indicator dict."""
    fg = raw.get("fear_and_greed", {})
    score = fg.get("score", 0)
    rating = fg.get("rating", "neutral")

    # sub-indicators
    sub_keys = [
        ("market_momentum_sp500", "S&P 500 Momentum"),
        ("stock_price_strength", "Stock Price Strength"),
        ("stock_price_breadth", "Stock Price Breadth"),
        ("put_call_options", "Put/Call Options"),
        ("market_volatility_vix", "VIX Volatility"),
        ("junk_bond_demand", "Junk Bond Demand"),
        ("safe_haven_demand", "Safe Haven Demand"),
    ]
    sub_indicators = []
    for key, label in sub_keys:
        sub = raw.get(key, {})
        if sub and "score" in sub:
            sub_indicators.append({
                "name": label,
                "score": round(float(sub["score"]), 1),
                "rating": sub.get("rating", "neutral"),
                "signal": _rating_signal(sub.get("rating", "")),
            })

    # historical series
    hist = raw.get("fear_and_greed_historical", {})
    hist_data = hist.get("data", [])
    dates = []
    values = []
    for pt in hist_data:
        ts = pt.get("x", 0) / 1000  # ms → s
        dt = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
        dates.append(dt)
        values.append(round(float(pt.get("y", 0)), 2))

    signal = _rating_signal(rating)
    strength = _strength_from_score(score)

    # trend: compare current to 1-week and 1-month
    prev_week = fg.get("previous_1_week")
    prev_month = fg.get("previous_1_month")
    trend = "stable"
    if prev_week is not None:
        if score > prev_week + 5:
            trend = "improving"
        elif score < prev_week - 5:
            trend = "deteriorating"

    return {
        "name": "CNN Fear & Greed",
        "params": "Market-wide",
        "values": {
            "score": round(float(score), 1),
            "rating": rating,
            "previous_close": round(float(fg.get("previous_close", 0)), 1),
            "previous_1_week": round(float(prev_week or 0), 1),
            "previous_1_month": round(float(prev_month or 0), 1),
            "trend": trend,
        },
        "levels": {
            "support": 20,    # extreme fear zone
            "resistance": 80, # extreme greed zone
        },
        "signal": signal,
        "strength": strength,
        "reason": f"Score {round(float(score), 1)} — {rating} ({trend})",
        "sub_indicators": sub_indicators,
        "series": {
            "dates": dates,
            "scores": values,
        },
    }


def _error_result(msg: str) -> dict:
    return {
        "name": "CNN Fear & Greed",
        "params": "Market-wide",
        "values": {},
        "levels": {"support": 20, "resistance": 80},
        "signal": "NEUTRAL",
        "strength": 0,
        "reason": f"Unavailable: {msg}",
        "sub_indicators": [],
        "series": {"dates": [], "scores": []},
    }
