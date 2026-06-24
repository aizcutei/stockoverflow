"""FastAPI application — stock search, fetch, and serve."""

import logging
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, Request, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from sqlalchemy.orm import Session

from backend.config import settings
from backend.database import Base, engine, get_db
from backend.errors import (
    AppError,
    app_error_handler,
    generic_error_handler,
    http_error_handler,
)
from backend.financials_service import get_financial_summary
from backend.llm_service import get_config, predict, save_config
from backend.logging_config import setup_logging
from backend.news_service import fetch_news
from backend.schemas import StockDetail, StockSearchResult
from backend.stock_service import fetch_and_save, get_cached, search_stocks

# --- logging ---
setup_logging("DEBUG" if settings.debug else "INFO")
logger = logging.getLogger("stockoverflow")

# --- rate limiting ---
limiter = Limiter(key_func=get_remote_address, default_limits=["60/minute"])

# --- create tables on startup ---
Base.metadata.create_all(bind=engine)

# --- auto-backup on startup ---
try:
    from backend.backup import create_backup
    _bk = create_backup()
    if _bk.get("status") == "ok":
        logger.info("Auto-backup created: %s (%s MB)", _bk.get("file"), _bk.get("size_mb"))
except Exception as e:
    logger.warning("Auto-backup failed: %s", e)

# --- auto-cleanup expired active stocks on startup ---
try:
    from backend.database import SessionLocal
    from backend.market_service import cleanup_expired
    _db = SessionLocal()
    _cu = cleanup_expired(_db)
    _db.close()
    if _cu.get("removed", 0) > 0:
        logger.info("Cleaned up %d expired active stocks", _cu["removed"])
except Exception as e:
    logger.warning("Auto-cleanup failed: %s", e)

app = FastAPI(
    title="StockOverflow",
    version="0.2.0",
    description="""
# StockOverflow API

一站式智能股票分析平台 — 面向投资小白，赋能进阶用户。

## Features
- **Stock Data**: Search, fetch, and cache US stock OHLCV data
- **Technical Indicators**: 16 indicators with buy/sell signals
- **News & Financials**: Real-time news and quarterly financial data
- **LLM Prediction**: AI-powered next-day trading recommendations
- **Factor Lab**: Custom factor expression evaluation and backtesting
- **Paper Trading**: Virtual trading account with position tracking

## Docs
- Swagger UI: `/docs`
- ReDoc: `/redoc`
""",
    docs_url="/docs",
    redoc_url="/redoc",
)

# --- rate limit error handler ---
@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={"error": "Rate limit exceeded. Try again later.", "code": "RATE_LIMITED"},
    )

# --- unified error handlers ---
app.add_exception_handler(AppError, app_error_handler)
app.add_exception_handler(HTTPException, http_error_handler)
app.add_exception_handler(Exception, generic_error_handler)

# --- performance monitoring ---
from collections import defaultdict
import time as _time

_perf_stats = defaultdict(lambda: {"count": 0, "total_ms": 0, "max_ms": 0})


@app.middleware("http")
async def track_performance(request: Request, call_next):
    start = _time.time()
    response = await call_next(request)
    elapsed = (_time.time() - start) * 1000
    path = request.url.path
    # only track API endpoints
    if path.startswith("/api/"):
        stats = _perf_stats[path]
        stats["count"] += 1
        stats["total_ms"] += elapsed
        stats["max_ms"] = max(stats["max_ms"], elapsed)
    return response


@app.get("/api/perf")
async def api_performance():
    """Get API performance statistics."""
    result = {}
    for path, stats in _perf_stats.items():
        result[path] = {
            "count": stats["count"],
            "avg_ms": round(stats["total_ms"] / stats["count"], 1) if stats["count"] > 0 else 0,
            "max_ms": round(stats["max_ms"], 1),
        }
    return result


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- static / frontend ---
FRONTEND = Path(__file__).resolve().parent.parent / "frontend"
app.mount("/static", StaticFiles(directory=str(FRONTEND)), name="static")
app.mount("/locales", StaticFiles(directory=str(FRONTEND / "locales")), name="locales")


@app.get("/")
async def index():
    return FileResponse(str(FRONTEND / "index.html"))


@app.get("/health")
async def health():
    """Health check endpoint for monitoring."""
    from backend.database import engine
    try:
        with engine.connect() as conn:
            conn.execute(__import__("sqlalchemy").text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False

    return {
        "status": "healthy" if db_ok else "degraded",
        "database": "ok" if db_ok else "error",
        "version": "0.2.0",
    }


@app.get("/stock/{ticker}")
async def stock_page(ticker: str):
    """Serve SPA for direct URL access to /stock/AAPL."""
    return FileResponse(str(FRONTEND / "index.html"))


@app.websocket("/ws/stock/{ticker}")
async def websocket_stock(websocket: WebSocket, ticker: str):
    """WebSocket endpoint for real-time stock price streaming."""
    from backend.websocket_manager import manager
    ticker = ticker.upper().strip()
    await manager.connect(ticker, websocket)
    try:
        while True:
            # keep connection alive, receive pings
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except Exception:
        manager.disconnect(ticker, websocket)


# --- Market routes ---


@app.get("/api/market/indices")
async def api_market_indices(db: Session = Depends(get_db)):
    """Get major market indices (S&P 500, NASDAQ, Dow, Russell, VIX)."""
    from backend.market_service import get_indices
    return get_indices(db)


@app.get("/api/market/movers")
async def api_market_movers(type: str = Query("gainers", pattern="^(gainers|losers|hot)$"), limit: int = Query(20, ge=1, le=50), db: Session = Depends(get_db)):
    """Get market movers (gainers/losers/hot) and auto-track ranked stocks."""
    from backend.market_service import get_movers
    return get_movers(db, type, limit)


@app.get("/api/market/active-stocks")
async def api_active_stocks(db: Session = Depends(get_db)):
    """Get all active stocks being tracked."""
    from backend.market_service import get_active_stocks
    return get_active_stocks(db)


class InteractBody(BaseModel):
    ticker: str
    source: str = "search"


@app.post("/api/market/interact")
async def api_market_interact(body: InteractBody, db: Session = Depends(get_db)):
    """Record user interaction with a stock (search, view, trade)."""
    from backend.market_service import record_interaction
    record_interaction(db, body.ticker, body.source)
    return {"ok": True}


@app.get("/api/watchlist/predictions")
async def api_watchlist_predictions(db: Session = Depends(get_db)):
    """Get LLM predictions for all watchlist stocks."""
    from backend.market_service import get_watchlist_predictions
    return get_watchlist_predictions(db)


@app.post("/api/market/cleanup")
async def api_cleanup(db: Session = Depends(get_db)):
    """Clean up expired active stocks."""
    from backend.market_service import cleanup_expired
    return cleanup_expired(db)


# --- API routes ---


@app.get("/api/search", response_model=list[StockSearchResult])
async def api_search(q: str = Query(..., min_length=1, max_length=50)):
    """Search US stocks by ticker or company name."""
    return search_stocks(q)


@app.get("/api/stock/{ticker}", response_model=StockDetail)
async def api_stock(
    ticker: str,
    period: str | None = Query(None, description="History period: 1y/2y/5y/max"),
    db: Session = Depends(get_db),
):
    """Get stock detail — fetches fresh data from yfinance and upserts into DB.

    Uses incremental updates: only fetches data newer than what's already cached.
    """
    try:
        return fetch_and_save(ticker, db, period=period)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch data: {e}")


@app.get("/api/stock/{ticker}/cached", response_model=StockDetail | None)
async def api_stock_cached(ticker: str, db: Session = Depends(get_db)):
    """Return cached stock data without hitting yfinance."""
    return get_cached(ticker, db)


@app.get("/api/cache/stats")
async def api_cache_stats():
    """Get cache statistics."""
    from backend.cache import stock_cache, news_cache
    return {
        "stock_cache": stock_cache.stats(),
        "news_cache": news_cache.stats(),
    }


@app.post("/api/cache/clear")
async def api_cache_clear():
    """Clear all caches."""
    from backend.cache import stock_cache, news_cache
    stock_cache.clear()
    news_cache.clear()
    return {"status": "cleared"}


@app.post("/api/backup")
async def api_create_backup():
    """Create a database backup."""
    from backend.backup import create_backup
    return create_backup()


@app.get("/api/backup")
async def api_list_backups():
    """List all database backups."""
    from backend.backup import list_backups
    return list_backups()


@app.post("/api/backup/restore/{filename}")
async def api_restore_backup(filename: str):
    """Restore database from a backup."""
    from backend.backup import restore_backup
    return restore_backup(filename)


@app.get("/api/stock/{ticker}/integrity")
async def api_data_integrity(ticker: str, db: Session = Depends(get_db)):
    """Check data integrity — find missing trading dates."""
    from backend.stock_service import check_data_integrity
    return check_data_integrity(db, ticker)


@app.get("/api/stock/{ticker}/intraday")
async def api_stock_intraday(
    ticker: str,
    period: str = Query("5d", description="Data period: 1d/5d/1mo"),
    interval: str = Query("5m", description="Candle interval: 1m/5m/15m/1h"),
):
    """Get intraday (minute) data for zoomed-in views."""
    from backend.stock_service import fetch_intraday
    return fetch_intraday(ticker, period, interval)


@app.get("/api/stock/{ticker}/candles")
async def api_stock_candles(
    ticker: str,
    timeframe: str = Query("daily", description="Timeframe: 1d, daily, weekly, monthly, quarterly, yearly"),
):
    """Get candles for various timeframes (1d intraday, daily, weekly, monthly, quarterly, yearly)."""
    from backend.stock_service import fetch_candles
    return fetch_candles(ticker, timeframe)


@app.get("/api/stock/{ticker}/fetch-history")
async def api_fetch_history(ticker: str, db: Session = Depends(get_db)):
    """Get data fetch history for a ticker."""
    from backend.models import DataFetchLog
    logs = (
        db.query(DataFetchLog)
        .filter(DataFetchLog.ticker == ticker.upper())
        .order_by(DataFetchLog.fetched_at.desc())
        .limit(20)
        .all()
    )
    return [
        {
            "fetched_at": str(log.fetched_at),
            "period": log.period,
            "candles_added": log.candles_added,
            "source": log.source,
        }
        for log in logs
    ]


# --- Watchlist routes ---


@app.get("/api/watchlist")
async def api_get_watchlist(db: Session = Depends(get_db)):
    """Get all watchlist stocks with latest prices."""
    from backend.watchlist_service import get_watchlist
    return get_watchlist(db)


class WatchlistBody(BaseModel):
    ticker: str
    name: str = ""


@app.post("/api/watchlist")
async def api_add_watchlist(body: WatchlistBody, db: Session = Depends(get_db)):
    """Add a stock to the watchlist."""
    from backend.watchlist_service import add_to_watchlist
    return add_to_watchlist(db, body.ticker, body.name)


@app.delete("/api/watchlist/{ticker}")
async def api_remove_watchlist(ticker: str, db: Session = Depends(get_db)):
    """Remove a stock from the watchlist."""
    from backend.watchlist_service import remove_from_watchlist
    return remove_from_watchlist(db, ticker)


@app.get("/api/watchlist/{ticker}/check")
async def api_check_watchlist(ticker: str, db: Session = Depends(get_db)):
    """Check if a ticker is in the watchlist."""
    from backend.watchlist_service import is_in_watchlist
    return {"ticker": ticker.upper(), "in_watchlist": is_in_watchlist(db, ticker)}


@app.get("/api/compare")
async def api_compare_stocks(tickers: str = Query(..., description="Comma-separated tickers"), db: Session = Depends(get_db)):
    """Compare multiple stocks side by side."""
    from backend.stock_service import compare_stocks
    ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()]
    if len(ticker_list) < 2:
        raise HTTPException(status_code=422, detail="Provide at least 2 tickers")
    if len(ticker_list) > 10:
        raise HTTPException(status_code=422, detail="Max 10 tickers")
    return compare_stocks(ticker_list, db)


@app.get("/api/stock/{ticker}/news")
async def api_stock_news(
    ticker: str,
    limit: int = Query(10, ge=1, le=30),
    sentiment: bool = Query(False),
    sources: str = Query("all", description="News sources: all, yfinance, finviz"),
):
    """Fetch recent news for a stock from multiple sources."""
    try:
        if sentiment:
            from backend.news_service import analyze_news_sentiment
            return analyze_news_sentiment(ticker, min(limit, 8))
        return fetch_news(ticker, limit, sources)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch news: {e}")


@app.get("/api/stock/{ticker}/financials")
async def api_stock_financials(ticker: str):
    """Get quarterly financials, earnings, dividends, institutional holders."""
    return get_financial_summary(ticker)


@app.get("/api/stock/{ticker}/news-impact")
async def api_news_impact(ticker: str, db: Session = Depends(get_db)):
    """Deep analysis of news impact on a stock and user's holdings."""
    from backend.llm_service import analyze_news_impact
    from backend.news_service import fetch_news
    from backend.paper_trading import get_account_summary

    ticker = ticker.upper().strip()
    news = fetch_news(ticker, limit=10)
    if not news:
        return {"error": "No news available"}

    # get user's positions
    account = get_account_summary(db)
    holdings = [
        {"ticker": p["ticker"], "quantity": p["quantity"], "avg_cost": p["avg_cost"]}
        for p in account.get("positions", [])
    ]

    return analyze_news_impact(ticker, news, holdings)


class BullBearDebateBody(BaseModel):
    indicators: list[dict]
    overall: dict
    current_price: float | None = None


class OptimizeBody(BaseModel):
    risk_tolerance: str = "moderate"


@app.post("/api/llm/optimize")
async def api_optimize(body: OptimizeBody, db: Session = Depends(get_db)):
    """Portfolio optimization based on risk tolerance."""
    from backend.llm_service import optimize_portfolio
    from backend.paper_trading import get_account_summary

    account = get_account_summary(db)
    positions = account.get("positions", [])
    if not positions:
        return {"error": "No positions to optimize"}
    return optimize_portfolio(positions, body.risk_tolerance)


class FinancialAnalysisBody(BaseModel):
    financials: dict


@app.post("/api/llm/financial-analysis/{ticker}")
async def api_financial_analysis(ticker: str, body: FinancialAnalysisBody):
    """LLM analysis of financial data."""
    from backend.llm_service import analyze_financial_report
    return analyze_financial_report(ticker.upper(), body.financials)


@app.get("/api/llm/portfolio-review")
async def api_portfolio_review(db: Session = Depends(get_db)):
    """Generate daily portfolio review for all held stocks."""
    from backend.llm_service import generate_portfolio_review
    from backend.paper_trading import get_account_summary

    account = get_account_summary(db)
    positions = account.get("positions", [])
    if not positions:
        return {"error": "No positions to review"}

    # get indicators for each held stock
    indicators_map = {}
    for pos in positions:
        detail = get_cached(pos["ticker"], db)
        if detail:
            indicators_map[pos["ticker"]] = detail.indicators

    return generate_portfolio_review(positions, indicators_map)


@app.post("/api/llm/bull-bear-debate/{ticker}")
async def api_bull_bear_debate(ticker: str, body: BullBearDebateBody):
    """Structured bull vs bear debate with arguments on both sides."""
    from backend.llm_service import bull_bear_debate
    return bull_bear_debate(ticker.upper(), body.indicators, body.overall, body.current_price)


@app.get("/api/stock/{ticker}/anomaly")
async def api_stock_anomaly(ticker: str, threshold: float = Query(5.0), db: Session = Depends(get_db)):
    """Detect price anomalies (>threshold% move) and explain with LLM."""
    from backend.llm_service import detect_anomaly, explain_anomaly
    from backend.news_service import get_news_for_llm

    ticker = ticker.upper().strip()
    detail = get_cached(ticker, db)
    if detail is None:
        try:
            detail = fetch_and_save(ticker, db)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))

    candles = [
        {"date": str(c.date), "close": c.close, "volume": c.volume}
        for c in detail.candles
    ]

    anomaly = detect_anomaly(candles, threshold)
    if anomaly is None:
        return {"detected": False, "message": f"No anomaly detected (threshold: {threshold}%)"}

    anomaly["ticker"] = ticker
    news_text = get_news_for_llm(ticker, limit=5)
    explanation = explain_anomaly(ticker, anomaly, news_text)

    return {
        "detected": True,
        "anomaly": anomaly,
        "explanation": explanation,
    }


@app.get("/api/stock/{ticker}/options")
async def api_stock_options(ticker: str):
    """Get options chain data for nearest expiry."""
    from backend.financials_service import get_options
    return get_options(ticker)


@app.get("/api/stock/{ticker}/peers")
async def api_stock_peers(ticker: str):
    """Get sector/industry peer comparison."""
    from backend.financials_service import get_peer_comparison
    return get_peer_comparison(ticker)


@app.get("/api/stock/{ticker}/risk")
async def api_stock_risk(ticker: str, db: Session = Depends(get_db)):
    """Get quantitative risk assessment for a stock."""
    from backend.llm_service import assess_risk

    ticker = ticker.upper().strip()
    detail = get_cached(ticker, db)
    if detail is None:
        try:
            detail = fetch_and_save(ticker, db)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))

    candles = [
        {"date": str(c.date), "open": c.open, "high": c.high, "low": c.low, "close": c.close, "volume": c.volume}
        for c in detail.candles
    ]

    return assess_risk(candles, detail.indicators, {
        "ticker": detail.info.ticker,
        "sector": detail.info.sector,
    })


# --- LLM routes ---


@app.get("/api/llm/config")
async def api_llm_config():
    """Get current LLM configuration (masks API key)."""
    cfg = get_config()
    # mask api_key for frontend display — NEVER return full key
    masked = cfg.copy()
    key = masked.pop("api_key", "")
    if key:
        masked["api_key_masked"] = key[:8] + "..." + key[-4:] if len(key) > 12 else "***"
        masked["api_key_set"] = True
    else:
        masked["api_key_masked"] = ""
        masked["api_key_set"] = False
    return masked


class LLMConfigBody(BaseModel):
    base_url: str | None = None
    api_key: str | None = None
    model: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    enabled: bool | None = None


@app.post("/api/llm/config")
async def api_llm_config_update(body: LLMConfigBody):
    """Update LLM configuration."""
    cfg = get_config()
    update = body.model_dump(exclude_none=True)
    # don't overwrite api_key with masked value
    if "api_key" in update and ("..." in update["api_key"] or update["api_key"] == "***"):
        del update["api_key"]
    cfg.update(update)
    save_config(cfg)
    return {"ok": True}


def _prepare_stock_data(ticker: str, db: Session) -> tuple:
    """Get stock data for LLM prediction, fetching if needed."""
    detail = get_cached(ticker, db)
    if detail is None:
        detail = fetch_and_save(ticker, db)

    info = {
        "ticker": detail.info.ticker,
        "name": detail.info.name,
        "exchange": detail.info.exchange,
        "sector": detail.info.sector,
        "industry": detail.info.industry,
        "market_cap": detail.info.market_cap,
        "currency": detail.info.currency,
    }
    candles = [
        {
            "date": str(c.date),
            "open": c.open, "high": c.high, "low": c.low,
            "close": c.close, "volume": c.volume,
        }
        for c in detail.candles
    ]
    return info, candles, detail.indicators, detail.overall


@app.get("/api/llm/predict/{ticker}")
@limiter.limit("5/minute")
async def api_llm_predict(ticker: str, request: Request, db: Session = Depends(get_db)):
    """Run LLM prediction for a stock. Uses cached data + request queue."""
    from backend.request_queue import llm_queue

    ticker = ticker.upper().strip()
    try:
        info, candles, indicators, overall = _prepare_stock_data(ticker, db)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch data: {e}")

    async def _run_predict():
        import asyncio
        return await asyncio.to_thread(predict, ticker, info, candles, indicators, overall)

    try:
        result = await llm_queue.submit(ticker, _run_predict)
    except RuntimeError as e:
        raise HTTPException(status_code=429, detail=str(e))

    # save prediction to history and track as active
    if not result.get("error"):
        from backend.conversation_service import save_prediction
        from backend.market_service import record_prediction
        save_prediction(db, ticker, result)
        record_prediction(db, ticker)

    return result


class ExplainBody(BaseModel):
    indicator: dict
    current_price: float | None = None


@app.post("/api/llm/explain/{ticker}")
async def api_llm_explain(ticker: str, body: ExplainBody):
    """Explain a technical indicator in plain language using LLM."""
    from backend.llm_service import explain_indicator
    ticker = ticker.upper().strip()
    return explain_indicator(body.indicator, ticker, body.current_price)


@app.get("/api/llm/predict/{ticker}/stream")
@limiter.limit("3/minute")
async def api_llm_predict_stream(ticker: str, request: Request, db: Session = Depends(get_db)):
    """Stream LLM prediction via SSE."""
    from fastapi.responses import StreamingResponse
    import asyncio, json

    ticker = ticker.upper().strip()
    try:
        info, candles, indicators, overall = _prepare_stock_data(ticker, db)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch data: {e}")

    async def event_stream():
        # send progress event
        yield f"data: {json.dumps({'type': 'progress', 'message': 'Analyzing with LLM...'})}\n\n"

        try:
            result = await asyncio.to_thread(predict, ticker, info, candles, indicators, overall)
            yield f"data: {json.dumps({'type': 'result', 'data': result})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/api/llm/prompts")
async def api_get_prompts():
    """Get all prompt versions."""
    from backend.llm_service import get_prompt_versions
    return get_prompt_versions()


class PromptVersionBody(BaseModel):
    name: str
    prompt: str


@app.post("/api/llm/prompts")
async def api_create_prompt(body: PromptVersionBody):
    """Create a new prompt version."""
    from backend.llm_service import save_prompt_version
    return save_prompt_version(body.name, body.prompt)


class SetPromptBody(BaseModel):
    id: int


@app.post("/api/llm/prompts/active")
async def api_set_active_prompt(body: SetPromptBody):
    """Set active prompt version."""
    from backend.llm_service import set_active_prompt
    return set_active_prompt(body.id)


# --- Conversation & History routes ---


@app.get("/api/llm/models")
async def api_llm_models():
    """Get available model presets."""
    from backend.llm_service import get_model_presets
    return get_model_presets()


class ChatBody(BaseModel):
    message: str
    context: dict = {}


@app.post("/api/llm/chat/{ticker}")
async def api_llm_chat(ticker: str, body: ChatBody, db: Session = Depends(get_db)):
    """Multi-turn chat about a stock."""
    from backend.llm_service import chat

    ticker = ticker.upper().strip()
    try:
        result = chat(db, ticker, body.message, body.context)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))
    return result


@app.get("/api/llm/chat/{ticker}/history")
async def api_chat_history(ticker: str, limit: int = Query(20, ge=1, le=100), db: Session = Depends(get_db)):
    """Get conversation history for a ticker."""
    from backend.conversation_service import get_history
    return get_history(db, ticker, limit)


@app.delete("/api/llm/chat/{ticker}/history")
async def api_chat_clear(ticker: str, db: Session = Depends(get_db)):
    """Clear conversation history for a ticker."""
    from backend.conversation_service import clear_history
    count = clear_history(db, ticker)
    return {"cleared": count}


@app.get("/api/llm/history/{ticker}")
async def api_prediction_history(ticker: str, limit: int = Query(10, ge=1, le=50), db: Session = Depends(get_db)):
    """Get LLM prediction history for a ticker."""
    from backend.conversation_service import get_prediction_history
    return get_prediction_history(db, ticker, limit)


@app.get("/api/llm/calibrate/{ticker}")
async def api_calibrate(ticker: str, db: Session = Depends(get_db)):
    """Calibrate LLM confidence based on historical prediction accuracy."""
    from backend.conversation_service import calibrate_confidence

    ticker = ticker.upper().strip()
    detail = get_cached(ticker, db)
    if detail is None:
        try:
            detail = fetch_and_save(ticker, db)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))

    candles = [
        {"date": str(c.date), "close": c.close}
        for c in detail.candles
    ]

    return calibrate_confidence(db, ticker, candles)


class AskBody(BaseModel):
    question: str


@app.post("/api/llm/ask")
async def api_llm_ask(body: AskBody):
    """Ask a general investment question."""
    from backend.llm_service import ask_encyclopedia
    return ask_encyclopedia(body.question)


class LearningPathBody(BaseModel):
    level: str = "beginner"
    interests: list[str] = []


@app.post("/api/llm/learn")
async def api_learning_path(body: LearningPathBody):
    """Get a personalized learning path for investing."""
    from backend.llm_service import get_learning_path
    return get_learning_path(body.level, body.interests)


class BullBearBody(BaseModel):
    indicators: list[dict]
    overall: dict
    current_price: float | None = None


@app.post("/api/llm/bull-bear/{ticker}")
async def api_bull_bear(ticker: str, body: BullBearBody):
    """Generate bull and bear cases for a stock."""
    from backend.llm_service import bull_bear_analysis
    return bull_bear_analysis(ticker.upper(), body.indicators, body.overall, body.current_price)


class DCABody(BaseModel):
    indicators: list[dict]
    overall: dict
    current_price: float | None = None


@app.post("/api/llm/dca/{ticker}")
async def api_dca(ticker: str, body: DCABody):
    """Generate DCA investment advice."""
    from backend.llm_service import get_dca_advice
    return get_dca_advice(ticker.upper(), body.indicators, body.overall, body.current_price)


class ChartAnnotationBody(BaseModel):
    indicators: list[dict]


@app.post("/api/llm/annotate/{ticker}")
async def api_chart_annotation(ticker: str, body: ChartAnnotationBody, db: Session = Depends(get_db)):
    """Generate chart annotations — key support/resistance levels."""
    from backend.llm_service import get_chart_annotations

    ticker = ticker.upper().strip()
    detail = get_cached(ticker, db)
    if detail is None:
        try:
            detail = fetch_and_save(ticker, db)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))

    candles = [
        {"date": str(c.date), "open": c.open, "high": c.high, "low": c.low, "close": c.close, "volume": c.volume}
        for c in detail.candles
    ]

    return get_chart_annotations(ticker, candles, body.indicators)


class ReportBody(BaseModel):
    info: dict
    indicators: list[dict]
    overall: dict
    prediction: dict | None = None


@app.post("/api/llm/report/{ticker}")
async def api_report(ticker: str, body: ReportBody):
    """Generate a Markdown analysis report."""
    from backend.llm_service import generate_report
    return generate_report(ticker.upper(), body.info, body.indicators, body.overall, body.prediction)


# --- Factor Lab routes ---


@app.get("/api/factors/library")
async def api_factor_library(db: Session = Depends(get_db)):
    """Get built-in + custom factor library."""
    from sqlalchemy import select as sa_select
    from backend.factor_engine import BUILTIN_FACTORS
    from backend.models import CustomFactor

    builtins = BUILTIN_FACTORS
    customs = db.execute(sa_select(CustomFactor).order_by(CustomFactor.created_at.desc())).scalars().all()
    custom_list = [
        {"name": f.name, "expression": f.expression, "description": f.description or "", "category": f.category, "custom": True, "id": f.id}
        for f in customs
    ]
    return builtins + custom_list


@app.get("/api/factors/categories")
async def api_factor_categories():
    """Get factor categories with descriptions."""
    from backend.factor_engine import FACTOR_CATEGORIES, BUILTIN_FACTORS
    categories = {}
    for name, desc in FACTOR_CATEGORIES.items():
        factors = [f for f in BUILTIN_FACTORS if f.get("category") == name]
        categories[name] = {
            "description": desc,
            "count": len(factors),
            "factors": factors,
        }
    return categories


class CustomFactorBody(BaseModel):
    name: str
    expression: str
    description: str = ""
    category: str = "Custom"


@app.post("/api/factors/custom")
async def api_create_custom_factor(body: CustomFactorBody, db: Session = Depends(get_db)):
    """Save a custom factor expression."""
    from backend.models import CustomFactor

    # validate expression
    from backend.factor_engine import evaluate_expression
    test_candles = [{"date": f"2025-01-{i+1:02d}", "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1000000} for i in range(30)]
    result = evaluate_expression(body.expression, test_candles)
    if result.get("error"):
        raise HTTPException(status_code=422, detail=f"Invalid expression: {result['error']}")

    factor = CustomFactor(
        name=body.name,
        expression=body.expression,
        description=body.description,
        category=body.category,
    )
    db.add(factor)
    db.commit()
    db.refresh(factor)
    return {"id": factor.id, "name": factor.name, "expression": factor.expression, "status": "created"}


@app.delete("/api/factors/custom/{factor_id}")
async def api_delete_custom_factor(factor_id: int, db: Session = Depends(get_db)):
    """Delete a custom factor."""
    from backend.models import CustomFactor
    factor = db.execute(select(CustomFactor).where(CustomFactor.id == factor_id)).scalar_one_or_none()
    if factor is None:
        raise HTTPException(status_code=404, detail="Factor not found")
    db.delete(factor)
    db.commit()
    return {"id": factor_id, "status": "deleted"}


class FactorEvalBody(BaseModel):
    expression: str


@app.get("/api/factors/correlation/{ticker}")
async def api_factor_correlation(ticker: str, db: Session = Depends(get_db)):
    """Compute correlation matrix between built-in factors for a stock."""
    from backend.factor_engine import compute_factor_correlation

    ticker = ticker.upper().strip()
    detail = get_cached(ticker, db)
    if detail is None:
        try:
            detail = fetch_and_save(ticker, db)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))

    candles = [
        {
            "date": str(c.date),
            "open": c.open, "high": c.high, "low": c.low,
            "close": c.close, "volume": c.volume,
        }
        for c in detail.candles
    ]

    return compute_factor_correlation(candles)


@app.post("/api/factors/eval/{ticker}")
async def api_factor_eval(ticker: str, body: FactorEvalBody, db: Session = Depends(get_db)):
    """Evaluate a factor expression against a stock's data."""
    from backend.factor_engine import evaluate_expression

    ticker = ticker.upper().strip()
    # get candle data
    detail = get_cached(ticker, db)
    if detail is None:
        try:
            detail = fetch_and_save(ticker, db)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))

    candles = [
        {
            "date": str(c.date),
            "open": c.open, "high": c.high, "low": c.low,
            "close": c.close, "volume": c.volume,
        }
        for c in detail.candles
    ]

    result = evaluate_expression(body.expression, candles)
    if result.get("error"):
        raise HTTPException(status_code=422, detail=result["error"])
    return result


@app.post("/api/factors/distribution/{ticker}")
async def api_factor_distribution(ticker: str, body: FactorEvalBody, db: Session = Depends(get_db)):
    """Get distribution histogram of a factor expression."""
    from backend.factor_engine import compute_factor_distribution

    ticker = ticker.upper().strip()
    detail = get_cached(ticker, db)
    if detail is None:
        try:
            detail = fetch_and_save(ticker, db)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))

    candles = [
        {"date": str(c.date), "open": c.open, "high": c.high, "low": c.low, "close": c.close, "volume": c.volume}
        for c in detail.candles
    ]

    result = compute_factor_distribution(candles, body.expression)
    if result.get("error"):
        raise HTTPException(status_code=422, detail=result["error"])
    return result


class QuintileBody(BaseModel):
    expression: str
    holding_days: int = 5


@app.post("/api/factors/quintile/{ticker}")
async def api_factor_quintile(ticker: str, body: QuintileBody, db: Session = Depends(get_db)):
    """Quintile backtest — split factor into 5 groups, compare forward returns."""
    from backend.factor_engine import compute_quintile_backtest

    ticker = ticker.upper().strip()
    detail = get_cached(ticker, db)
    if detail is None:
        try:
            detail = fetch_and_save(ticker, db)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))

    candles = [
        {"date": str(c.date), "open": c.open, "high": c.high, "low": c.low, "close": c.close, "volume": c.volume}
        for c in detail.candles
    ]

    result = compute_quintile_backtest(candles, body.expression, body.holding_days)
    if result.get("error"):
        raise HTTPException(status_code=422, detail=result["error"])
    return result


class ICAnalysisBody(BaseModel):
    expression: str
    max_lag: int = 20


@app.post("/api/factors/ic/{ticker}")
async def api_factor_ic(ticker: str, body: ICAnalysisBody, db: Session = Depends(get_db)):
    """Rank IC analysis — factor predictive power at various lags."""
    from backend.factor_engine import compute_ic_analysis

    ticker = ticker.upper().strip()
    detail = get_cached(ticker, db)
    if detail is None:
        try:
            detail = fetch_and_save(ticker, db)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))

    candles = [
        {"date": str(c.date), "open": c.open, "high": c.high, "low": c.low, "close": c.close, "volume": c.volume}
        for c in detail.candles
    ]

    result = compute_ic_analysis(candles, body.expression, body.max_lag)
    if result.get("error"):
        raise HTTPException(status_code=422, detail=result["error"])
    return result


class DecayBody(BaseModel):
    expression: str
    periods: list[int] | None = None


@app.post("/api/factors/decay/{ticker}")
async def api_factor_decay(ticker: str, body: DecayBody, db: Session = Depends(get_db)):
    """Factor decay analysis — predictive power across holding periods."""
    from backend.factor_engine import compute_factor_decay

    ticker = ticker.upper().strip()
    detail = get_cached(ticker, db)
    if detail is None:
        try:
            detail = fetch_and_save(ticker, db)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))

    candles = [
        {"date": str(c.date), "open": c.open, "high": c.high, "low": c.low, "close": c.close, "volume": c.volume}
        for c in detail.candles
    ]

    result = compute_factor_decay(candles, body.expression, body.periods)
    if result.get("error"):
        raise HTTPException(status_code=422, detail=result["error"])
    return result


class MultiFactorBody(BaseModel):
    expressions: list[str]
    weights: list[float] | None = None


@app.post("/api/factors/multi/{ticker}")
async def api_multi_factor(ticker: str, body: MultiFactorBody, db: Session = Depends(get_db)):
    """Compute weighted multi-factor composite score."""
    from backend.factor_engine import compute_multi_factor_score

    ticker = ticker.upper().strip()
    detail = get_cached(ticker, db)
    if detail is None:
        try:
            detail = fetch_and_save(ticker, db)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))

    candles = [
        {"date": str(c.date), "open": c.open, "high": c.high, "low": c.low, "close": c.close, "volume": c.volume}
        for c in detail.candles
    ]

    result = compute_multi_factor_score(candles, body.expressions, body.weights)
    if result.get("error"):
        raise HTTPException(status_code=422, detail=result["error"])
    return result


class OrthogonalBody(BaseModel):
    expressions: list[str]


@app.post("/api/factors/orthogonal/{ticker}")
async def api_orthogonal(ticker: str, body: OrthogonalBody, db: Session = Depends(get_db)):
    """Orthogonalize factors — remove multicollinearity via Gram-Schmidt."""
    from backend.factor_engine import compute_orthogonalization

    ticker = ticker.upper().strip()
    detail = get_cached(ticker, db)
    if detail is None:
        try:
            detail = fetch_and_save(ticker, db)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))

    candles = [
        {"date": str(c.date), "open": c.open, "high": c.high, "low": c.low, "close": c.close, "volume": c.volume}
        for c in detail.candles
    ]

    result = compute_orthogonalization(candles, body.expressions)
    if result.get("error"):
        raise HTTPException(status_code=422, detail=result["error"])
    return result


class NeutralizeBody(BaseModel):
    expression: str


@app.post("/api/factors/neutralize/{ticker}")
async def api_neutralize(ticker: str, body: NeutralizeBody, db: Session = Depends(get_db)):
    """Neutralize a factor — remove trend and mean exposure."""
    from backend.factor_engine import compute_neutralization

    ticker = ticker.upper().strip()
    detail = get_cached(ticker, db)
    if detail is None:
        try:
            detail = fetch_and_save(ticker, db)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))

    candles = [
        {"date": str(c.date), "open": c.open, "high": c.high, "low": c.low, "close": c.close, "volume": c.volume}
        for c in detail.candles
    ]

    result = compute_neutralization(candles, body.expression)
    if result.get("error"):
        raise HTTPException(status_code=422, detail=result["error"])
    return result


@app.get("/api/backtest/templates")
async def api_backtest_templates():
    """Get pre-built strategy templates."""
    from backend.backtest_engine import STRATEGY_TEMPLATES
    return STRATEGY_TEMPLATES


class BacktestBody(BaseModel):
    buy_expr: str
    sell_expr: str
    initial_capital: float = 100000.0
    fee_rate: float = 0.001
    slippage: float = 0.0005
    stop_loss_pct: float | None = None
    take_profit_pct: float | None = None


@app.post("/api/backtest/{ticker}")
async def api_backtest(ticker: str, body: BacktestBody, db: Session = Depends(get_db)):
    """Run a backtest on a stock with buy/sell factor expressions."""
    from backend.backtest_engine import BacktestConfig, run_backtest

    ticker = ticker.upper().strip()
    detail = get_cached(ticker, db)
    if detail is None:
        try:
            detail = fetch_and_save(ticker, db)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))

    candles = [
        {
            "date": str(c.date),
            "open": c.open, "high": c.high, "low": c.low,
            "close": c.close, "volume": c.volume,
        }
        for c in detail.candles
    ]

    config = BacktestConfig(
        initial_capital=body.initial_capital,
        fee_rate=body.fee_rate,
        slippage=body.slippage,
        stop_loss_pct=body.stop_loss_pct,
        take_profit_pct=body.take_profit_pct,
    )

    try:
        result = run_backtest(candles, body.buy_expr, body.sell_expr, config)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return {
        "total_return": result.total_return,
        "annual_return": result.annual_return,
        "max_drawdown": result.max_drawdown,
        "sharpe_ratio": result.sharpe_ratio,
        "win_rate": result.win_rate,
        "profit_factor": result.profit_factor,
        "avg_trade_pnl": result.avg_trade_pnl,
        "total_trades": result.total_trades,
        "equity_curve": result.equity_curve,
        "trades": result.trades,
        "config": result.config,
    }


class MonteCarloBody(BaseModel):
    buy_expr: str
    sell_expr: str
    n_simulations: int = 1000
    initial_capital: float = 100000.0
    fee_rate: float = 0.001
    stop_loss_pct: float | None = None


@app.post("/api/backtest/{ticker}/montecarlo")
async def api_montecarlo(ticker: str, body: MonteCarloBody, db: Session = Depends(get_db)):
    """Run backtest + Monte Carlo simulation to assess strategy robustness."""
    from backend.backtest_engine import BacktestConfig, run_backtest, run_monte_carlo

    ticker = ticker.upper().strip()
    detail = get_cached(ticker, db)
    if detail is None:
        try:
            detail = fetch_and_save(ticker, db)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))

    candles = [
        {"date": str(c.date), "open": c.open, "high": c.high, "low": c.low, "close": c.close, "volume": c.volume}
        for c in detail.candles
    ]

    config = BacktestConfig(
        initial_capital=body.initial_capital,
        fee_rate=body.fee_rate,
        stop_loss_pct=body.stop_loss_pct,
    )

    try:
        result = run_backtest(candles, body.buy_expr, body.sell_expr, config)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    mc = run_monte_carlo(result.trades, body.n_simulations, body.initial_capital)
    if mc.get("error"):
        raise HTTPException(status_code=422, detail=mc["error"])

    return {
        "backtest": {
            "total_return": result.total_return,
            "sharpe_ratio": result.sharpe_ratio,
            "max_drawdown": result.max_drawdown,
            "total_trades": result.total_trades,
        },
        "monte_carlo": mc,
    }


class WalkForwardBody(BaseModel):
    buy_expr: str
    sell_expr: str
    train_pct: float = 0.7
    n_splits: int = 3
    initial_capital: float = 100000.0
    fee_rate: float = 0.001


@app.post("/api/backtest/{ticker}/walkforward")
async def api_walkforward(ticker: str, body: WalkForwardBody, db: Session = Depends(get_db)):
    """Walk-forward backtest — rolling train/test splits to avoid look-ahead bias."""
    from backend.backtest_engine import BacktestConfig, run_walk_forward

    ticker = ticker.upper().strip()
    detail = get_cached(ticker, db)
    if detail is None:
        try:
            detail = fetch_and_save(ticker, db)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))

    candles = [
        {"date": str(c.date), "open": c.open, "high": c.high, "low": c.low, "close": c.close, "volume": c.volume}
        for c in detail.candles
    ]

    config = BacktestConfig(initial_capital=body.initial_capital, fee_rate=body.fee_rate)
    result = run_walk_forward(candles, body.buy_expr, body.sell_expr, body.train_pct, body.n_splits, config)
    if result.get("error"):
        raise HTTPException(status_code=422, detail=result["error"])
    return result


class OutOfSampleBody(BaseModel):
    buy_expr: str
    sell_expr: str
    train_ratio: float = 0.6
    initial_capital: float = 100000.0
    fee_rate: float = 0.001


@app.post("/api/backtest/{ticker}/oos")
async def api_out_of_sample(ticker: str, body: OutOfSampleBody, db: Session = Depends(get_db)):
    """Out-of-sample validation — train/test split with robustness score."""
    from backend.backtest_engine import BacktestConfig, run_out_of_sample

    ticker = ticker.upper().strip()
    detail = get_cached(ticker, db)
    if detail is None:
        try:
            detail = fetch_and_save(ticker, db)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))

    candles = [
        {"date": str(c.date), "open": c.open, "high": c.high, "low": c.low, "close": c.close, "volume": c.volume}
        for c in detail.candles
    ]

    config = BacktestConfig(initial_capital=body.initial_capital, fee_rate=body.fee_rate)
    result = run_out_of_sample(candles, body.buy_expr, body.sell_expr, body.train_ratio, config)
    if result.get("error"):
        raise HTTPException(status_code=422, detail=result["error"])
    return result


class MultiBacktestBody(BaseModel):
    strategies: list[dict]  # [{"name": "RSI", "buy": "...", "sell": "..."}, ...]
    initial_capital: float = 100000.0
    fee_rate: float = 0.001
    stop_loss_pct: float | None = None


@app.post("/api/backtest/{ticker}/compare")
async def api_backtest_compare(ticker: str, body: MultiBacktestBody, db: Session = Depends(get_db)):
    """Run multiple strategies and compare results."""
    from backend.backtest_engine import BacktestConfig, run_backtest

    ticker = ticker.upper().strip()
    detail = get_cached(ticker, db)
    if detail is None:
        try:
            detail = fetch_and_save(ticker, db)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))

    candles = [
        {
            "date": str(c.date),
            "open": c.open, "high": c.high, "low": c.low,
            "close": c.close, "volume": c.volume,
        }
        for c in detail.candles
    ]

    config = BacktestConfig(
        initial_capital=body.initial_capital,
        fee_rate=body.fee_rate,
        stop_loss_pct=body.stop_loss_pct,
    )

    results = []
    for strat in body.strategies:
        try:
            r = run_backtest(candles, strat["buy"], strat["sell"], config)
            results.append({
                "name": strat.get("name", "Unnamed"),
                "buy_expr": strat["buy"],
                "sell_expr": strat["sell"],
                "total_return": r.total_return,
                "annual_return": r.annual_return,
                "max_drawdown": r.max_drawdown,
                "sharpe_ratio": r.sharpe_ratio,
                "win_rate": r.win_rate,
                "total_trades": r.total_trades,
                "equity_curve": r.equity_curve,
            })
        except Exception as e:
            results.append({
                "name": strat.get("name", "Unnamed"),
                "error": str(e),
            })

    # rank by Sharpe ratio
    valid = [r for r in results if "error" not in r]
    valid.sort(key=lambda x: x.get("sharpe_ratio", -999), reverse=True)

    return {"ticker": ticker, "strategies": results, "best": valid[0] if valid else None}


class SensitivityBody(BaseModel):
    buy_template: str  # e.g., "rsi({period}) < {threshold}"
    sell_template: str  # e.g., "rsi({period}) > {threshold}"
    param_ranges: dict  # {"period": [7, 14, 21], "threshold": [20, 25, 30]}
    initial_capital: float = 100000.0
    fee_rate: float = 0.001


@app.post("/api/backtest/{ticker}/sensitivity")
async def api_sensitivity(ticker: str, body: SensitivityBody, db: Session = Depends(get_db)):
    """Parameter sensitivity analysis — grid search over parameter ranges."""
    import itertools
    from backend.backtest_engine import BacktestConfig, run_backtest

    ticker = ticker.upper().strip()
    detail = get_cached(ticker, db)
    if detail is None:
        try:
            detail = fetch_and_save(ticker, db)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))

    candles = [
        {
            "date": str(c.date),
            "open": c.open, "high": c.high, "low": c.low,
            "close": c.close, "volume": c.volume,
        }
        for c in detail.candles
    ]

    config = BacktestConfig(initial_capital=body.initial_capital, fee_rate=body.fee_rate)

    # generate all parameter combinations
    param_names = list(body.param_ranges.keys())
    param_values = list(body.param_ranges.values())
    combinations = list(itertools.product(*param_values))

    results = []
    for combo in combinations:
        params = dict(zip(param_names, combo))
        buy_expr = body.buy_template.format(**params)
        sell_expr = body.sell_template.format(**params)

        try:
            r = run_backtest(candles, buy_expr, sell_expr, config)
            results.append({
                "params": params,
                "buy_expr": buy_expr,
                "sell_expr": sell_expr,
                "total_return": r.total_return,
                "annual_return": r.annual_return,
                "max_drawdown": r.max_drawdown,
                "sharpe_ratio": r.sharpe_ratio,
                "win_rate": r.win_rate,
                "total_trades": r.total_trades,
            })
        except Exception as e:
            results.append({"params": params, "error": str(e)})

    # sort by Sharpe
    valid = [r for r in results if "error" not in r]
    valid.sort(key=lambda x: x.get("sharpe_ratio", -999), reverse=True)

    return {
        "ticker": ticker,
        "total_combinations": len(combinations),
        "results": results,
        "best": valid[0] if valid else None,
        "worst": valid[-1] if valid else None,
    }


# --- Paper Trading routes ---


class OrderBody(BaseModel):
    ticker: str
    side: str  # buy / sell
    quantity: int
    price: float
    reason: str = ""


@app.post("/api/paper/order")
async def api_paper_order(body: OrderBody, db: Session = Depends(get_db)):
    """Place a paper trade order."""
    from backend.paper_trading import place_order
    result = place_order(db, "default", body.ticker, body.side, body.quantity, body.price, reason=body.reason)
    if result.get("error"):
        raise HTTPException(status_code=422, detail=result["error"])
    return result


@app.get("/api/paper/account")
async def api_paper_account(db: Session = Depends(get_db)):
    """Get paper trading account summary with positions."""
    from backend.paper_trading import get_account_summary
    from backend.models import PaperPosition
    import yfinance as yf

    # get current prices for all positions
    account = get_account_summary(db)
    current_prices = {}
    for pos in account.get("positions", []):
        try:
            tk = yf.Ticker(pos["ticker"])
            hist = tk.history(period="1d")
            if not hist.empty:
                current_prices[pos["ticker"]] = float(hist["Close"].iloc[-1])
        except Exception:
            pass

    return get_account_summary(db, current_prices=current_prices)


@app.get("/api/paper/trades")
async def api_paper_trades(limit: int = Query(50, ge=1, le=200), db: Session = Depends(get_db)):
    """Get paper trade log."""
    from backend.paper_trading import get_trade_log
    return get_trade_log(db, limit=limit)


@app.get("/api/paper/stats")
async def api_paper_stats(db: Session = Depends(get_db)):
    """Get paper trading performance statistics."""
    from backend.paper_trading import get_performance_stats
    return get_performance_stats(db)


@app.get("/api/paper/rebalance")
async def api_rebalance(db: Session = Depends(get_db)):
    """Get portfolio rebalance suggestions."""
    from backend.paper_trading import get_rebalance_suggestion
    return get_rebalance_suggestion(db)


@app.get("/api/paper/tax")
async def api_tax_report(year: int = Query(None), db: Session = Depends(get_db)):
    """Generate tax report of realized capital gains/losses."""
    from backend.paper_trading import get_tax_report
    return get_tax_report(db, year=year)


class PendingOrderBody(BaseModel):
    ticker: str
    side: str  # buy / sell
    order_type: str  # limit, stop_loss, take_profit
    quantity: int
    trigger_price: float
    reason: str = ""


@app.post("/api/paper/pending")
async def api_place_pending(body: PendingOrderBody, db: Session = Depends(get_db)):
    """Place a pending limit/stop order."""
    from backend.paper_trading import place_pending_order
    result = place_pending_order(
        db, "default", body.ticker, body.side, body.order_type,
        body.quantity, body.trigger_price, body.reason,
    )
    if result.get("error"):
        raise HTTPException(status_code=422, detail=result["error"])
    return result


@app.get("/api/paper/pending")
async def api_get_pending(db: Session = Depends(get_db)):
    """Get all pending orders."""
    from backend.paper_trading import get_pending_orders
    return get_pending_orders(db)


@app.delete("/api/paper/pending/{order_id}")
async def api_cancel_pending(order_id: int, db: Session = Depends(get_db)):
    """Cancel a pending order."""
    from backend.paper_trading import cancel_pending_order
    result = cancel_pending_order(db, order_id)
    if result.get("error"):
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@app.get("/api/paper/dashboard")
async def api_paper_dashboard(db: Session = Depends(get_db)):
    """Get dashboard data: recent trades, account summary, top positions."""
    from backend.paper_trading import get_account_summary, get_trade_log
    from backend.models import PaperPosition
    import yfinance as yf

    account = get_account_summary(db)
    trades = get_trade_log(db, limit=10)

    # get current prices
    current_prices = {}
    for pos in account.get("positions", []):
        try:
            tk = yf.Ticker(pos["ticker"])
            hist = tk.history(period="1d")
            if not hist.empty:
                current_prices[pos["ticker"]] = float(hist["Close"].iloc[-1])
        except Exception:
            pass

    account_with_prices = get_account_summary(db, current_prices=current_prices)

    return {
        "account": account_with_prices,
        "recent_trades": trades,
    }


@app.get("/api/dashboard")
async def api_dashboard(db: Session = Depends(get_db)):
    """Get dashboard data: account, recent analyses, trades."""
    from sqlalchemy import func, select
    from backend.models import PaperAccount, PaperTrade, DataFetchLog, LLMHistory
    from backend.paper_trading import get_account_summary, get_trade_log

    # recent analyzed stocks
    recent_stocks = db.execute(
        select(DataFetchLog.ticker, func.max(DataFetchLog.fetched_at).label("last_fetch"))
        .group_by(DataFetchLog.ticker)
        .order_by(func.max(DataFetchLog.fetched_at).desc())
        .limit(10)
    ).all()

    # recent predictions
    recent_preds = db.execute(
        select(LLMHistory)
        .order_by(LLMHistory.created_at.desc())
        .limit(5)
    ).scalars().all()

    # account summary
    account = get_account_summary(db)
    trades = get_trade_log(db, limit=5)

    # active stocks summary
    from backend.market_service import get_active_stocks_summary
    active = get_active_stocks_summary(db)

    return {
        "recent_stocks": [{"ticker": r.ticker, "last_fetch": str(r.last_fetch)} for r in recent_stocks],
        "recent_predictions": [
            {
                "ticker": p.ticker,
                "action": p.action,
                "confidence": p.confidence,
                "created_at": str(p.created_at),
            }
            for p in recent_preds
        ],
        "account": account,
        "recent_trades": trades,
        "active_stocks": active,
    }
