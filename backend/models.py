"""SQLAlchemy models for stock data."""

from sqlalchemy import Column, Date, DateTime, Float, Integer, String, Text, UniqueConstraint, func

from backend.database import Base


class Stock(Base):
    """Cached stock metadata."""

    __tablename__ = "stocks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String(10), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=False)
    exchange = Column(String(100))
    sector = Column(String(100))
    industry = Column(String(100))
    market_cap = Column(Float)
    currency = Column(String(10))


class DailyCandle(Base):
    """Daily OHLCV candle data."""

    __tablename__ = "daily_candles"
    __table_args__ = (
        UniqueConstraint("ticker", "date", name="uq_ticker_date"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String(10), nullable=False, index=True)
    date = Column(Date, nullable=False, index=True)
    open = Column(Float, nullable=False)
    high = Column(Float, nullable=False)
    low = Column(Float, nullable=False)
    close = Column(Float, nullable=False)
    volume = Column(Integer, nullable=False)


class DataFetchLog(Base):
    """Tracks when data was last fetched for each ticker."""

    __tablename__ = "data_fetch_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String(10), nullable=False, index=True)
    fetched_at = Column(DateTime, server_default=func.now(), nullable=False)
    period = Column(String(10))
    candles_added = Column(Integer, default=0)
    source = Column(String(50), default="yfinance")


class ActiveStock(Base):
    """Tracks actively-watched stocks with TTL-based lifecycle."""

    __tablename__ = "active_stocks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String(10), unique=True, nullable=False, index=True)
    source = Column(String(50), nullable=False)  # search, watchlist, trade, prediction, ranking
    ttl_hours = Column(Integer, default=24)
    last_interaction = Column(DateTime, server_default=func.now(), nullable=False)
    interaction_count = Column(Integer, default=1)


class Conversation(Base):
    """Persisted LLM conversation history per ticker."""

    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String(10), nullable=False, index=True)
    role = Column(String(20), nullable=False)  # user / assistant / system
    content = Column(Text, nullable=False)
    model = Column(String(100))
    created_at = Column(DateTime, server_default=func.now(), nullable=False)


class LLMHistory(Base):
    """Stores LLM prediction results for history review."""

    __tablename__ = "llm_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String(10), nullable=False, index=True)
    action = Column(String(10))  # BUY / SELL / HOLD
    buy_price = Column(Float)
    sell_price = Column(Float)
    stop_loss = Column(Float)
    take_profit = Column(Float)
    confidence = Column(Integer)
    reasoning = Column(Text)
    model = Column(String(100))
    created_at = Column(DateTime, server_default=func.now(), nullable=False)


class CustomFactor(Base):
    """User-defined custom factor expressions."""

    __tablename__ = "custom_factors"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    expression = Column(String(500), nullable=False)
    description = Column(Text)
    category = Column(String(50), default="Custom")
    created_at = Column(DateTime, server_default=func.now(), nullable=False)


class Watchlist(Base):
    """User's watchlist / favorite stocks."""

    __tablename__ = "watchlist"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String(10), unique=True, nullable=False, index=True)
    name = Column(String(255))
    added_at = Column(DateTime, server_default=func.now(), nullable=False)


class PaperAccount(Base):
    """Paper trading account."""

    __tablename__ = "paper_accounts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(50), unique=True, nullable=False)
    initial_capital = Column(Float, nullable=False)
    cash = Column(Float, nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)


class PaperPosition(Base):
    """Open positions in a paper account."""

    __tablename__ = "paper_positions"
    __table_args__ = (
        UniqueConstraint("account_id", "ticker", name="uq_account_ticker"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(Integer, nullable=False, index=True)
    ticker = Column(String(10), nullable=False)
    quantity = Column(Integer, nullable=False)
    avg_cost = Column(Float, nullable=False)


class PaperTrade(Base):
    """Paper trade log."""

    __tablename__ = "paper_trades"

    id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(Integer, nullable=False, index=True)
    ticker = Column(String(10), nullable=False)
    side = Column(String(4), nullable=False)  # buy / sell
    quantity = Column(Integer, nullable=False)
    price = Column(Float, nullable=False)
    total = Column(Float, nullable=False)
    fee = Column(Float, default=0)
    reason = Column(Text)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)


class PendingOrder(Base):
    """Pending limit/stop orders for paper trading."""

    __tablename__ = "pending_orders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(Integer, nullable=False, index=True)
    ticker = Column(String(10), nullable=False)
    side = Column(String(4), nullable=False)  # buy / sell
    order_type = Column(String(20), nullable=False)  # limit, stop_loss, take_profit
    quantity = Column(Integer, nullable=False)
    trigger_price = Column(Float, nullable=False)
    reason = Column(Text)
    status = Column(String(10), default="pending")  # pending, filled, cancelled
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
