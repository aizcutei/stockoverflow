"""WebSocket manager for real-time stock price streaming."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

import yfinance as yf
from fastapi import WebSocket

logger = logging.getLogger("stockoverflow")


class ConnectionManager:
    """Manages WebSocket connections per ticker."""

    def __init__(self):
        # ticker -> set of websocket connections
        self._connections: dict[str, set[WebSocket]] = {}
        # ticker -> last known price
        self._last_prices: dict[str, dict] = {}
        # ticker -> background task
        self._tasks: dict[str, asyncio.Task] = {}

    async def connect(self, ticker: str, websocket: WebSocket):
        await websocket.accept()
        ticker = ticker.upper().strip()
        if ticker not in self._connections:
            self._connections[ticker] = set()
        self._connections[ticker].add(websocket)

        # start background price stream if not running
        if ticker not in self._tasks or self._tasks[ticker].done():
            self._tasks[ticker] = asyncio.create_task(self._stream_prices(ticker))

        # send last known price immediately
        if ticker in self._last_prices:
            try:
                await websocket.send_json(self._last_prices[ticker])
            except Exception:
                pass

    def disconnect(self, ticker: str, websocket: WebSocket):
        ticker = ticker.upper().strip()
        if ticker in self._connections:
            self._connections[ticker].discard(websocket)
            if not self._connections[ticker]:
                del self._connections[ticker]
                # stop background task
                if ticker in self._tasks:
                    self._tasks[ticker].cancel()
                    del self._tasks[ticker]

    async def broadcast(self, ticker: str, data: dict):
        ticker = ticker.upper().strip()
        if ticker not in self._connections:
            return
        dead = set()
        for ws in self._connections[ticker]:
            try:
                await ws.send_json(data)
            except Exception:
                dead.add(ws)
        for ws in dead:
            self._connections[ticker].discard(ws)

    async def _stream_prices(self, ticker: str):
        """Background task: poll yfinance every 30s and broadcast."""
        try:
            tk = yf.Ticker(ticker)
            while ticker in self._connections:
                try:
                    hist = tk.history(period="1d", interval="1m")
                    if not hist.empty:
                        latest = hist.iloc[-1]
                        data = {
                            "type": "price",
                            "ticker": ticker,
                            "price": round(float(latest["Close"]), 4),
                            "open": round(float(latest["Open"]), 4),
                            "high": round(float(latest["High"]), 4),
                            "low": round(float(latest["Low"]), 4),
                            "volume": int(latest["Volume"]),
                            "time": str(hist.index[-1]),
                            "change_pct": round(
                                (float(latest["Close"]) - float(hist.iloc[0]["Open"]))
                                / float(hist.iloc[0]["Open"]) * 100, 2
                            ),
                        }
                        self._last_prices[ticker] = data
                        await self.broadcast(ticker, data)
                except Exception as e:
                    logger.debug("Price stream error for %s: %s", ticker, e)

                await asyncio.sleep(30)  # poll every 30 seconds
        except asyncio.CancelledError:
            pass

    def get_active_tickers(self) -> list[str]:
        return list(self._connections.keys())


# singleton
manager = ConnectionManager()
