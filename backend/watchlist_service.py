"""Watchlist service — manage user's favorite stocks."""

from __future__ import annotations

import logging
from datetime import date

import yfinance as yf
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models import DailyCandle, Watchlist

logger = logging.getLogger("stockoverflow")


def get_watchlist(db: Session) -> list[dict]:
    """Get all watchlist items with latest price data."""
    items = db.execute(
        select(Watchlist).order_by(Watchlist.added_at.desc())
    ).scalars().all()

    result = []
    for item in items:
        # get latest candle for price
        latest = db.execute(
            select(DailyCandle)
            .where(DailyCandle.ticker == item.ticker)
            .order_by(DailyCandle.date.desc())
            .limit(2)
        ).scalars().all()

        price = None
        change_pct = None
        prev_close = None
        if latest:
            price = latest[0].close
            if len(latest) >= 2:
                prev_close = latest[1].close
                change_pct = round((price - prev_close) / prev_close * 100, 2)

        result.append({
            "ticker": item.ticker,
            "name": item.name or "",
            "price": round(price, 2) if price else None,
            "prev_close": round(prev_close, 2) if prev_close else None,
            "change_pct": change_pct,
            "added_at": str(item.added_at),
        })

    return result


def add_to_watchlist(db: Session, ticker: str, name: str = "") -> dict:
    """Add a stock to the watchlist."""
    ticker = ticker.upper().strip()

    existing = db.execute(
        select(Watchlist).where(Watchlist.ticker == ticker)
    ).scalar_one_or_none()

    if existing:
        return {"ticker": ticker, "status": "already_exists"}

    if not name:
        try:
            tk = yf.Ticker(ticker)
            info = tk.info or {}
            name = info.get("shortName") or info.get("longName") or ticker
        except Exception:
            name = ticker

    item = Watchlist(ticker=ticker, name=name)
    db.add(item)
    db.commit()

    return {"ticker": ticker, "name": name, "status": "added"}


def remove_from_watchlist(db: Session, ticker: str) -> dict:
    """Remove a stock from the watchlist."""
    ticker = ticker.upper().strip()
    item = db.execute(
        select(Watchlist).where(Watchlist.ticker == ticker)
    ).scalar_one_or_none()

    if item is None:
        return {"ticker": ticker, "status": "not_found"}

    db.delete(item)
    db.commit()
    return {"ticker": ticker, "status": "removed"}


def is_in_watchlist(db: Session, ticker: str) -> bool:
    """Check if a ticker is in the watchlist."""
    return db.execute(
        select(Watchlist).where(Watchlist.ticker == ticker.upper().strip())
    ).scalar_one_or_none() is not None
