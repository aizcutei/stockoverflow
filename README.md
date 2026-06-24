# StockOverflow

US stock search with daily candlestick / volume charts and technical indicators. Data fetched from Yahoo Finance, cached in a local SQLite database, with locally-computed indicators.

## Quick Start

```bash
uv sync
uv run python main.py
```

Open http://127.0.0.1:8000 in your browser.

> 📋 **[Roadmap](ROADMAP.md)** — 7-phase plan to build a one-stop investment platform for beginners and pros.

## Technical Indicators (16)

Each indicator provides support/resistance levels and a buy/sell/watch/neutral signal:

| # | Indicator | Type | What It Measures |
|---|---|---|---|
| 1 | **MACD** (12/26/9) | Momentum | EMA crossover; histogram support/resistance |
| 2 | **Bollinger Bands** (20/2σ) | Volatility | Squeeze & mean reversion; upper/lower band levels |
| 3 | **Ichimoku** (9/26/52/26) | Trend | Cloud position; cloud top/bottom as S/R |
| 4 | **TD Sequential** (9/13) | Exhaustion | Setup (9-bar) and countdown (13-bar) counting |
| 5 | **RSI** (14) | Momentum | Overbought/oversold; 30/70 levels |
| 6 | **Stochastic** (14/3/3) | Momentum | %K/%D crossover; overbought >80, oversold <20 |
| 7 | **ADX** (14) | Trend Strength | Trend strength + directional index (+DI/-DI) |
| 8 | **VWAP** | Price/Volume | Volume-weighted average price; ±1%/±2% bands |
| 9 | **ATR** (14) | Volatility | Average true range; volatility-based stop levels |
| 10 | **OBV** | Volume | On-balance volume; divergence detection |
| 11 | **CCI** (20) | Momentum | Cyclical turns; overbought >100, oversold <-100 |
| 12 | **Williams %R** (14) | Momentum | Overbought >-20, oversold <-80 |
| 13 | **Parabolic SAR** | Trend Following | Reversal points; SAR as trailing stop |
| 14 | **MFI** (14) | Volume | Money flow index; volume-weighted RSI |
| 15 | **Fibonacci** (120d) | Support/Resistance | Retracement levels from recent swing high/low |
| 16 | **CNN Fear & Greed** | Sentiment | Market-wide sentiment (0–100); 7 sub-indicators |

An **overall aggregated signal** is computed by weighting all 16 indicators.

## Frontend Features

- **Candlestick + volume** chart (TradingView Lightweight Charts)
- **Indicator overlays** — each indicator has a toggle switch to draw its series on the chart:
  - **Price overlays**: Bollinger Bands, Ichimoku, VWAP, Parabolic SAR, Fibonacci, TD Sequential
  - **Sub-charts (synced)**: MACD, RSI, Stochastic, ADX, CCI, Williams %R, MFI, OBV, ATR, CNN Fear & Greed
- **Day/Night theme** — toggle button in header; defaults to system preference (`prefers-color-scheme`)
- **LLM Prediction** — OpenAI-compatible API integration:
  - Sends 30-day OHLCV + all 16 indicators as structured context
  - Returns next-day limit buy/sell/hold with specific price levels
  - Displays: action, buy/sell price, stop loss, take profit, confidence, reasoning, key factors
  - Configurable via ⚙️ settings: base URL, API key, model, temperature, max tokens
  - Works with any OpenAI-compatible API (OpenAI, Ollama, vLLM, LiteLLM, etc.)

## Architecture

```
backend/
  main.py            FastAPI — API + frontend serving
  database.py        SQLAlchemy + SQLite
  models.py          Stock / DailyCandle tables
  schemas.py         Pydantic response models
  stock_service.py   yfinance fetch + DB persistence + indicator calc
  indicators.py      15 local indicators (MACD, BB, Ichimoku, TD, RSI, Stoch, ADX, VWAP, ATR, OBV, CCI, %R, SAR, MFI, Fib)
  fear_greed.py      CNN Fear & Greed fetch + cache (30 min TTL)
  llm_service.py     OpenAI-compatible LLM integration for stock prediction
frontend/
  index.html         SPA — TradingView charts + indicators panel + theme toggle
data/
  stocks.db          SQLite (auto-created, gitignored)
```

## API

| Endpoint | Description |
|---|---|
| `GET /api/search?q=apple` | Search stocks by name or ticker |
| `GET /api/stock/AAPL` | Fetch fresh data, upsert into DB, return candles + indicators |
| `GET /api/stock/AAPL/cached` | Return cached data without network call |
| `GET /api/llm/config` | Get LLM configuration (API key masked) |
| `POST /api/llm/config` | Update LLM configuration |
| `GET /api/llm/predict/AAPL` | Run LLM prediction for a stock |
