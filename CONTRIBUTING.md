# Contributing to StockOverflow

## Development Setup

```bash
# Clone
git clone https://github.com/yourname/stockoverflow.git
cd stockoverflow

# Install dependencies
uv sync

# Run development server
make dev
# or
uv run python main.py

# Run tests
make test
# or
uv run pytest tests/ -v
```

## Project Structure

```
backend/
  main.py            FastAPI application & routes
  config.py          Settings via pydantic-settings / .env
  database.py        SQLAlchemy + SQLite (WAL mode)
  models.py          All database models
  schemas.py         Pydantic response schemas
  stock_service.py   yfinance data fetching + DB persistence
  indicators.py      15 technical indicator calculations
  factor_engine.py   Custom factor expression engine + library
  backtest_engine.py Event-driven backtesting framework
  paper_trading.py   Paper trading account management
  llm_service.py     OpenAI-compatible LLM integration
  conversation_service.py  Multi-turn chat persistence
  news_service.py    Stock news from yfinance
  financials_service.py    Quarterly financials, earnings
  fear_greed.py      CNN Fear & Greed Index
  request_queue.py   Async request queue for LLM calls
  errors.py          Unified error handling
  logging_config.py  Structured logging
frontend/
  index.html         Single-page application (vanilla JS)
tests/
  test_indicators.py Unit tests for indicators
  test_factor_engine.py  Unit tests for factor engine
  test_backtest.py   Unit tests for backtesting
```

## Adding a New Indicator

1. Add calculation function in `backend/indicators.py`
2. Follow the standard return format:
```python
{
    "name": "My Indicator",
    "params": "14",
    "values": {"my_value": 42},
    "levels": {"support": 30, "resistance": 70},
    "signal": "BUY" | "SELL" | "NEUTRAL",
    "strength": 0-100,
    "reason": "Human-readable explanation",
    "series": {"my_series": [...], "dates": [...]},
}
```
3. Add to `calc_all_indicators()` list
4. Add weight in `calc_overall_signal()`
5. Add overlay toggle in `frontend/index.html` if it has series data

## Adding a Factor Function

1. Add method to `FactorFunctions` class in `backend/factor_engine.py`
2. Register in the `namespace` dict in `evaluate_expression()`
3. Add a built-in factor template to `BUILTIN_FACTORS`

## Code Style

- Python: follow existing patterns, type hints preferred
- Frontend: vanilla JS, no frameworks
- Tests: pytest, one file per module

## API Design

- All endpoints return JSON
- Errors use `{"error": "...", "code": "...", "detail": "..."}`
- Rate limits: 60/min default, 5/min for LLM predictions
