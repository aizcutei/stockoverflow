"""Pydantic response schemas."""

from datetime import date

from pydantic import BaseModel


class StockInfo(BaseModel):
    ticker: str
    name: str
    exchange: str | None = None
    sector: str | None = None
    industry: str | None = None
    market_cap: float | None = None
    currency: str | None = None

    model_config = {"from_attributes": True}


class Candle(BaseModel):
    date: date
    open: float
    high: float
    low: float
    close: float
    volume: int

    model_config = {"from_attributes": True}


class StockSearchResult(BaseModel):
    ticker: str
    name: str
    exchange: str | None = None
    type: str | None = None


class StockDetail(BaseModel):
    info: StockInfo
    candles: list[Candle]
    indicators: list[dict] = []
    overall: dict = {}
