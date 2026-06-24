"""Market-wide data service — indices, movers, active stocks tracking."""

from __future__ import annotations

import logging
import time
from datetime import datetime

import yfinance as yf
from sqlalchemy import select, desc
from sqlalchemy.orm import Session

from backend.models import ActiveStock, DailyCandle, Stock

logger = logging.getLogger("stockoverflow")

# Major indices tickers
INDICES = ["^GSPC", "^IXIC", "^DJI", "^RUT", "^VIX"]
INDEX_NAMES = {
    "^GSPC": "S&P 500",
    "^IXIC": "NASDAQ",
    "^DJI": "Dow Jones",
    "^RUT": "Russell 2000",
    "^VIX": "VIX",
}

# in-memory cache for market data
_market_cache: dict = {}
MARKET_CACHE_TTL = 300  # 5 min


def get_indices(db: Session) -> list[dict]:
    """Get major market indices with current prices."""
    cached = _market_cache.get("indices")
    if cached and (time.time() - cached["ts"]) < MARKET_CACHE_TTL:
        return cached["data"]

    results = []
    for ticker in INDICES:
        try:
            tk = yf.Ticker(ticker)
            hist = tk.history(period="5d")
            if hist.empty:
                continue
            latest = hist.iloc[-1]
            prev = hist.iloc[-2] if len(hist) >= 2 else latest
            price = float(latest["Close"])
            prev_close = float(prev["Close"])
            change_pct = round((price - prev_close) / prev_close * 100, 2) if prev_close else 0

            results.append({
                "ticker": ticker,
                "name": INDEX_NAMES.get(ticker, ticker),
                "price": round(price, 2),
                "change_pct": change_pct,
            })
        except Exception as e:
            logger.warning("Failed to fetch index %s: %s", ticker, e)

    _market_cache["indices"] = {"data": results, "ts": time.time()}
    return results


def get_movers(db: Session, mover_type: str = "gainers", limit: int = 20) -> list[dict]:
    """Get market movers (gainers/losers/hot) and auto-track ranked stocks."""
    cache_key = f"movers_{mover_type}"
    cached = _market_cache.get(cache_key)
    if cached and (time.time() - cached["ts"]) < MARKET_CACHE_TTL:
        return cached["data"][:limit]

    try:
        # use yfinance screener — returns dict with 'quotes' list
        screener_map = {
            "gainers": "day_gainers",
            "losers": "day_losers",
            "hot": "most_actives",
        }
        screen_name = screener_map.get(mover_type)
        if not screen_name:
            return []

        result = yf.screen(screen_name)
        quotes = result.get("quotes", []) if isinstance(result, dict) else []

        results = []
        for row in quotes[:limit]:
            ticker = row.get("symbol", "")
            results.append({
                "ticker": ticker,
                "name": row.get("shortName") or row.get("longName", ""),
                "price": round(float(row.get("regularMarketPrice", 0)), 2),
                "change_pct": round(float(row.get("regularMarketChangePercent", 0)), 2),
                "volume": int(row.get("regularMarketVolume", 0)),
            })

            # auto-track ranked stocks as active (TTL 168h = 7 days)
            if ticker and db:
                try:
                    existing = db.execute(
                        select(ActiveStock).where(ActiveStock.ticker == ticker)
                    ).scalar_one_or_none()
                    if existing:
                        existing.source = "ranking"
                        existing.ttl_hours = 168
                        existing.last_interaction = datetime.now()
                    else:
                        db.add(ActiveStock(
                            ticker=ticker,
                            source="ranking",
                            ttl_hours=168,
                            last_interaction=datetime.now(),
                            interaction_count=1,
                        ))
                except Exception:
                    pass

        if db:
            try:
                db.commit()
            except Exception:
                db.rollback()

        _market_cache[cache_key] = {"data": results, "ts": time.time()}
        return results
    except Exception as e:
        logger.warning("Failed to fetch movers (%s): %s", mover_type, e)
        return []


def record_interaction(db: Session, ticker: str, source: str = "search") -> None:
    """Record a user interaction with a stock (search, view, trade)."""
    ticker = ticker.upper().strip()
    existing = db.execute(
        select(ActiveStock).where(ActiveStock.ticker == ticker)
    ).scalar_one_or_none()

    now = datetime.now()
    if existing:
        existing.last_interaction = now
        existing.interaction_count += 1
        existing.source = source
    else:
        db.add(ActiveStock(
            ticker=ticker,
            source=source,
            ttl_hours=24,
            last_interaction=now,
            interaction_count=1,
        ))
    db.commit()


def get_active_stocks(db: Session) -> list[dict]:
    """Get all active stocks with their status."""
    stocks = db.execute(
        select(ActiveStock).order_by(ActiveStock.last_interaction.desc())
    ).scalars().all()

    now = datetime.now()
    results = []
    for s in stocks:
        hours_since = (now - s.last_interaction).total_seconds() / 3600
        status = "active" if hours_since < s.ttl_hours else "expired"
        results.append({
            "ticker": s.ticker,
            "source": s.source,
            "status": status,
            "hours_since_interaction": round(hours_since, 1),
            "interaction_count": s.interaction_count,
            "last_interaction": str(s.last_interaction),
        })
    return results


def record_prediction(db: Session, ticker: str) -> None:
    """Record that a prediction was made — adds to active set with 72h TTL."""
    record_interaction(db, ticker, "prediction")
    existing = db.execute(
        select(ActiveStock).where(ActiveStock.ticker == ticker.upper())
    ).scalar_one_or_none()
    if existing:
        existing.ttl_hours = 72  # predictions stay active for 3 days


def record_trade(db: Session, ticker: str) -> None:
    """Record that a trade was made — stays active while held."""
    record_interaction(db, ticker, "trade")
    existing = db.execute(
        select(ActiveStock).where(ActiveStock.ticker == ticker.upper())
    ).scalar_one_or_none()
    if existing:
        existing.ttl_hours = 8760  # effectively forever while held


def get_active_stocks_summary(db: Session) -> dict:
    """Get summary of active stocks grouped by source."""
    stocks = db.execute(select(ActiveStock)).scalars().all()
    now = datetime.now()
    by_source = {}
    for s in stocks:
        hours_since = (now - s.last_interaction).total_seconds() / 3600
        if hours_since < s.ttl_hours:
            src = s.source
            if src not in by_source:
                by_source[src] = []
            by_source[src].append(s.ticker)
    return {
        "total": sum(len(v) for v in by_source.values()),
        "by_source": by_source,
    }


def cleanup_expired(db: Session) -> dict:
    """Remove expired active stocks that haven't been interacted with."""
    now = datetime.now()
    stocks = db.execute(select(ActiveStock)).scalars().all()
    removed = 0
    kept = 0
    for s in stocks:
        hours_since = (now - s.last_interaction).total_seconds() / 3600
        if hours_since > s.ttl_hours * 2:  # keep for 2x TTL after expiry
            db.delete(s)
            removed += 1
        else:
            kept += 1
    db.commit()
    return {"removed": removed, "kept": kept, "total": len(stocks)}


def get_watchlist_predictions(db: Session) -> list[dict]:
    """Get LLM predictions for all watchlist stocks."""
    from backend.models import LLMHistory, Watchlist

    watchlist = db.execute(select(Watchlist)).scalars().all()
    if not watchlist:
        return []

    results = []
    for item in watchlist:
        # get latest prediction
        pred = db.execute(
            select(LLMHistory)
            .where(LLMHistory.ticker == item.ticker)
            .order_by(LLMHistory.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()

        # get latest price
        latest = db.execute(
            select(DailyCandle)
            .where(DailyCandle.ticker == item.ticker)
            .order_by(DailyCandle.date.desc())
            .limit(1)
        ).scalar_one_or_none()

        price = round(latest.close, 2) if latest else None

        results.append({
            "ticker": item.ticker,
            "name": item.name or "",
            "price": price,
            "prediction": {
                "action": pred.action if pred else None,
                "buy_price": pred.buy_price if pred else None,
                "sell_price": pred.sell_price if pred else None,
                "stop_loss": pred.stop_loss if pred else None,
                "take_profit": pred.take_profit if pred else None,
                "confidence": pred.confidence if pred else None,
                "reasoning": pred.reasoning if pred else None,
                "created_at": str(pred.created_at) if pred else None,
            } if pred else None,
        })

    return results
