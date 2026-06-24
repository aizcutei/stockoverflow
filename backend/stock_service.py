"""Stock data service — yfinance fetching + SQLite persistence."""

import math
from datetime import date, datetime, timedelta

import yfinance as yf
from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_upsert
from sqlalchemy.orm import Session

from backend.config import settings
from backend.fear_greed import fetch_fear_greed
from backend.indicators import calc_all_indicators, calc_overall_signal
from backend.models import DailyCandle, DataFetchLog, Stock
from backend.schemas import Candle, StockDetail, StockInfo, StockSearchResult


def search_stocks(query: str, limit: int = 10) -> list[StockSearchResult]:
    """Search US stocks by ticker or company name via yfinance Search."""
    try:
        s = yf.Search(query, max_results=limit)
        quotes = s.quotes or []
    except Exception:
        return []

    out: list[StockSearchResult] = []
    for q in quotes[:limit]:
        out.append(
            StockSearchResult(
                ticker=q.get("symbol", ""),
                name=q.get("shortname") or q.get("longname") or "",
                exchange=q.get("exchDisp") or q.get("exchange", ""),
                type=q.get("typeDisp") or q.get("quoteType", ""),
            )
        )
    return out


def _upsert_stock_info(db: Session, info: dict) -> None:
    """Insert or update stock metadata."""
    stmt = (
        sqlite_upsert(Stock)
        .values(
            ticker=info["ticker"],
            name=info["name"],
            exchange=info.get("exchange"),
            sector=info.get("sector"),
            industry=info.get("industry"),
            market_cap=info.get("market_cap"),
            currency=info.get("currency"),
        )
        .on_conflict_do_update(
            index_elements=["ticker"],
            set_={
                "name": info["name"],
                "exchange": info.get("exchange"),
                "sector": info.get("sector"),
                "industry": info.get("industry"),
                "market_cap": info.get("market_cap"),
                "currency": info.get("currency"),
            },
        )
    )
    db.execute(stmt)
    db.commit()


def _upsert_candles(db: Session, ticker: str, rows: list[dict]) -> int:
    """Bulk insert daily candles, skipping duplicates."""
    count = 0
    for row in rows:
        stmt = (
            sqlite_upsert(DailyCandle)
            .values(
                ticker=ticker,
                date=row["date"],
                open=row["open"],
                high=row["high"],
                low=row["low"],
                close=row["close"],
                volume=row["volume"],
            )
            .on_conflict_do_update(
                index_elements=["ticker", "date"],
                set_={
                    "open": row["open"],
                    "high": row["high"],
                    "low": row["low"],
                    "close": row["close"],
                    "volume": row["volume"],
                },
            )
        )
        db.execute(stmt)
        count += 1
    db.commit()
    return count


def _get_latest_date(db: Session, ticker: str) -> date | None:
    """Return the most recent candle date for a ticker, or None."""
    result = db.execute(
        select(func.max(DailyCandle.date)).where(DailyCandle.ticker == ticker)
    ).scalar()
    return result


def _get_earliest_date(db: Session, ticker: str) -> date | None:
    """Return the earliest candle date for a ticker, or None."""
    result = db.execute(
        select(func.min(DailyCandle.date)).where(DailyCandle.ticker == ticker)
    ).scalar()
    return result


def _save_candles(db: Session, ticker: str, hist) -> int:
    """Save yfinance history DataFrame to DB. Returns count of rows saved."""
    candle_rows = []
    for dt, row in hist.iterrows():
        o, h, l, c = float(row["Open"]), float(row["High"]), float(row["Low"]), float(row["Close"])
        v = float(row["Volume"])
        if any(math.isnan(x) for x in (o, h, l, c, v)):
            continue
        candle_rows.append({
            "date": dt.date() if hasattr(dt, "date") else dt,
            "open": round(o, 4),
            "high": round(h, 4),
            "low": round(l, 4),
            "close": round(c, 4),
            "volume": int(v),
        })
    if candle_rows:
        _upsert_candles(db, ticker, candle_rows)
    return len(candle_rows)


def fetch_and_save(ticker: str, db: Session, period: str | None = None) -> StockDetail:
    """Fetch stock data from yfinance, persist to DB, return full detail.

    Supports incremental updates: only fetches data newer than what's in DB.
    """
    ticker = ticker.upper().strip()
    tk = yf.Ticker(ticker)

    # --- stock info ---
    raw_info = tk.info or {}
    info_dict = {
        "ticker": ticker,
        "name": raw_info.get("shortName") or raw_info.get("longName") or ticker,
        "exchange": raw_info.get("exchange"),
        "sector": raw_info.get("sector"),
        "industry": raw_info.get("industry"),
        "market_cap": raw_info.get("marketCap"),
        "currency": raw_info.get("currency"),
    }
    _upsert_stock_info(db, info_dict)

    # --- incremental update: check latest date in DB ---
    hist_period = period or settings.default_history_period
    latest_in_db = _get_latest_date(db, ticker)
    earliest_in_db = _get_earliest_date(db, ticker)

    # period to days mapping for backfill check
    period_days = {"1y": 252, "2y": 504, "5y": 1260, "max": 9999}
    desired_days = period_days.get(hist_period, 1260)

    if latest_in_db is not None and earliest_in_db is not None:
        days_gap = (date.today() - latest_in_db).days
        have_days = (latest_in_db - earliest_in_db).days

        if days_gap <= 1 and have_days >= desired_days * 0.8:
            # data is fresh and sufficient, just read from DB
            return _read_detail(db, ticker, info_dict)

        if days_gap > 1:
            # fetch newer data (incremental)
            start_date = latest_in_db + timedelta(days=1)
            hist_new = tk.history(start=start_date, interval="1d")
            if not hist_new.empty:
                _save_candles(db, ticker, hist_new)

        # backfill older data if we don't have enough
        if have_days < desired_days * 0.8 and earliest_in_db is not None:
            hist_old = tk.history(period=hist_period, interval="1d")
            if not hist_old.empty:
                _save_candles(db, ticker, hist_old)

        return _read_detail(db, ticker, info_dict)
    else:
        # first time: fetch full history
        hist = tk.history(period=hist_period, interval="1d")
        if hist.empty:
            raise ValueError(f"No price data found for '{ticker}'")
        count = _save_candles(db, ticker, hist)
        if count == 0:
            raise ValueError(f"All candle data for '{ticker}' contained NaN values")
        db.add(DataFetchLog(ticker=ticker, period=hist_period, candles_added=count))
        db.commit()

    # --- read back from DB ---
    from backend.cache import stock_cache
    stock_cache.invalidate(ticker)  # invalidate stale cache
    result = _read_detail(db, ticker, info_dict)
    stock_cache.set(ticker, result)  # cache fresh data
    return result


def _read_detail(
    db: Session, ticker: str, info_dict: dict
) -> StockDetail:
    """Build StockDetail from what's in the DB, including indicators."""
    stmt = (
        select(DailyCandle)
        .where(DailyCandle.ticker == ticker)
        .order_by(DailyCandle.date)
    )
    candles = db.execute(stmt).scalars().all()
    candle_models = [Candle.model_validate(c) for c in candles]

    # calculate indicators from raw candle dicts
    candle_dicts = [
        {
            "date": str(c.date),
            "open": c.open,
            "high": c.high,
            "low": c.low,
            "close": c.close,
            "volume": c.volume,
        }
        for c in candles
    ]
    indicators = calc_all_indicators(candle_dicts)

    # append CNN Fear & Greed (market-wide, fetched from CNN)
    try:
        fg = fetch_fear_greed()
        indicators.append(fg)
    except Exception:
        pass  # don't fail the whole request if CNN is unreachable

    overall = calc_overall_signal(indicators)

    return StockDetail(
        info=StockInfo(**info_dict),
        candles=candle_models,
        indicators=indicators,
        overall=overall,
    )


def check_data_integrity(db: Session, ticker: str) -> dict:
    """Check for missing trading dates in the database."""
    ticker = ticker.upper().strip()

    candles = db.execute(
        select(DailyCandle.date)
        .where(DailyCandle.ticker == ticker)
        .order_by(DailyCandle.date)
    ).scalars().all()

    if not candles:
        return {"ticker": ticker, "status": "no_data", "total_candles": 0, "missing_dates": []}

    # find missing weekdays (skip weekends and known US holidays)
    from datetime import timedelta
    import pandas as pd

    all_dates = set(candles)
    first = min(candles)
    last = max(candles)

    # generate all weekdays in range
    expected = set()
    current = first
    while current <= last:
        if current.weekday() < 5:  # Mon-Fri
            expected.add(current)
        current += timedelta(days=1)

    # US market holidays (approximate — major ones)
    us_holidays = set()
    for year in range(first.year, last.year + 1):
        us_holidays.update([
            date(year, 1, 1),   # New Year
            date(year, 7, 4),   # Independence Day (approx)
            date(year, 12, 25), # Christmas
        ])

    expected -= us_holidays
    missing = sorted(expected - all_dates)

    return {
        "ticker": ticker,
        "status": "ok" if len(missing) < 10 else "gaps_found",
        "total_candles": len(candles),
        "first_date": str(first),
        "last_date": str(last),
        "expected_trading_days": len(expected),
        "missing_count": len(missing),
        "missing_dates": [str(d) for d in missing[:20]],  # show first 20
        "completeness_pct": round((1 - len(missing) / max(len(expected), 1)) * 100, 1),
    }


def fetch_intraday(ticker: str, period: str = "5d", interval: str = "5m") -> list[dict]:
    """Fetch intraday (minute) data from yfinance. Not persisted to DB."""
    from backend.cache import stock_cache

    cache_key = f"intraday:{ticker}:{period}:{interval}"
    cached = stock_cache.get(cache_key)
    if cached is not None:
        return cached

    ticker = ticker.upper().strip()
    tk = yf.Ticker(ticker)
    hist = tk.history(period=period, interval=interval, prepost=True)

    if hist.empty:
        return []

    candles = _hist_to_candles(hist)
    stock_cache.set(cache_key, candles)
    return candles


def fetch_candles(ticker: str, timeframe: str = "daily") -> list[dict]:
    """Fetch candles for various timeframes.

    timeframes: 1d (today intraday), daily, weekly, monthly, quarterly, yearly
    """
    from backend.cache import stock_cache

    cache_key = f"candles:{ticker}:{timeframe}"
    cached = stock_cache.get(cache_key)
    if cached is not None:
        return cached

    ticker = ticker.upper().strip()
    tk = yf.Ticker(ticker)

    if timeframe == "1d":
        # today's intraday (1-minute candles) with pre/post market
        hist = tk.history(period="1d", interval="1m", prepost=True)
    elif timeframe == "daily":
        hist = tk.history(period="5y", interval="1d")
    elif timeframe == "weekly":
        hist = tk.history(period="max", interval="1wk")
    elif timeframe == "monthly":
        hist = tk.history(period="max", interval="1mo")
    elif timeframe == "quarterly":
        # yfinance doesn't have quarterly candles, so resample from monthly
        hist = tk.history(period="max", interval="1mo")
        if not hist.empty:
            hist = hist.resample("QS").agg({
                "Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"
            }).dropna()
    elif timeframe == "yearly":
        hist = tk.history(period="max", interval="1mo")
        if not hist.empty:
            hist = hist.resample("YS").agg({
                "Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"
            }).dropna()
    else:
        hist = tk.history(period="5y", interval="1d")

    if hist.empty:
        return []

    candles = _hist_to_candles(hist)
    stock_cache.set(cache_key, candles)
    return candles


def _hist_to_candles(hist) -> list[dict]:
    """Convert yfinance DataFrame to candle dicts."""
    import math
    candles = []
    for dt, row in hist.iterrows():
        o, h, l, c = float(row["Open"]), float(row["High"]), float(row["Low"]), float(row["Close"])
        v = float(row["Volume"])
        if any(math.isnan(x) for x in (o, h, l, c, v)):
            continue
        # convert to Unix timestamp (seconds) for lightweight-charts compatibility
        if hasattr(dt, "timestamp"):
            ts = int(dt.timestamp())
        elif hasattr(dt, "strftime"):
            ts = dt.strftime("%Y-%m-%d")
        else:
            ts = str(dt)
        candles.append({
            "time": ts,
            "open": round(o, 4),
            "high": round(h, 4),
            "low": round(l, 4),
            "close": round(c, 4),
            "volume": int(v),
        })
    return candles


def compare_stocks(tickers: list[str], db: Session) -> dict:
    """Compare multiple stocks side by side on key metrics."""
    results = []
    for ticker in tickers:
        ticker = ticker.upper().strip()
        stock = db.execute(
            select(Stock).where(Stock.ticker == ticker)
        ).scalar_one_or_none()
        if stock is None:
            continue

        # get latest candle
        latest = db.execute(
            select(DailyCandle)
            .where(DailyCandle.ticker == ticker)
            .order_by(DailyCandle.date.desc())
            .limit(2)
        ).scalars().all()

        if not latest:
            continue

        price = latest[0].close
        prev_price = latest[1].close if len(latest) >= 2 else price
        change_pct = round((price - prev_price) / prev_price * 100, 2) if prev_price else 0

        # get 52-week high/low
        year_ago = latest[0].date - __import__("datetime").timedelta(days=365)
        year_data = db.execute(
            select(DailyCandle.high, DailyCandle.low)
            .where(DailyCandle.ticker == ticker, DailyCandle.date >= year_ago)
        ).all()

        high_52w = max(r[0] for r in year_data) if year_data else price
        low_52w = min(r[1] for r in year_data) if year_data else price

        results.append({
            "ticker": stock.ticker,
            "name": stock.name,
            "price": round(price, 2),
            "change_pct": change_pct,
            "market_cap": stock.market_cap,
            "sector": stock.sector,
            "high_52w": round(high_52w, 2),
            "low_52w": round(low_52w, 2),
            "from_52w_high": round((price - high_52w) / high_52w * 100, 2),
            "from_52w_low": round((price - low_52w) / low_52w * 100, 2),
        })

    return {"stocks": results}


def get_cached(ticker: str, db: Session) -> "StockDetail | None":
    """Return cached data if the ticker exists in DB, else None. Uses LRU cache."""
    from backend.cache import stock_cache

    ticker = ticker.upper().strip()

    # check LRU cache first
    cached = stock_cache.get(ticker)
    if cached is not None:
        return cached

    stock = db.execute(
        select(Stock).where(Stock.ticker == ticker)
    ).scalar_one_or_none()
    if stock is None:
        return None
    info_dict = {
        "ticker": stock.ticker,
        "name": stock.name,
        "exchange": stock.exchange,
        "sector": stock.sector,
        "industry": stock.industry,
        "market_cap": stock.market_cap,
        "currency": stock.currency,
    }
    result = _read_detail(db, ticker, info_dict)
    if result is not None:
        stock_cache.set(ticker, result)
    return result
