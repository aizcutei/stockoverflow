"""Simple async request queue for LLM calls — prevents API abuse."""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger("stockoverflow")


@dataclass
class QueuedRequest:
    key: str
    coro_factory: Callable[[], Any]
    future: asyncio.Future = field(default_factory=asyncio.Future)


class RequestQueue:
    """Serializes concurrent requests by key (e.g., ticker symbol)."""

    def __init__(self, max_concurrent: int = 3, max_queue: int = 20):
        self._sem = asyncio.Semaphore(max_concurrent)
        self._queue: deque[QueuedRequest] = deque()
        self._max_queue = max_queue
        self._active: set[str] = set()
        self._task: asyncio.Task | None = None

    async def submit(self, key: str, coro_factory: Callable[[], Any]) -> Any:
        """Submit a coroutine factory. Returns the result when processed."""
        if len(self._queue) >= self._max_queue:
            raise RuntimeError("Request queue is full. Try again later.")

        req = QueuedRequest(key=key, coro_factory=coro_factory)
        self._queue.append(req)

        # start processor if not running
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._process())

        return await req.future

    async def _process(self):
        """Process queued requests respecting concurrency limits."""
        while self._queue:
            req = self._queue.popleft()

            if req.key in self._active:
                # re-queue if same key is still active
                self._queue.append(req)
                await asyncio.sleep(0.1)
                continue

            await self._sem.acquire()
            asyncio.create_task(self._run(req))

    async def _run(self, req: QueuedRequest):
        """Execute a single request."""
        self._active.add(req.key)
        try:
            result = await req.coro_factory()
            req.future.set_result(result)
        except Exception as e:
            req.future.set_exception(e)
        finally:
            self._active.discard(req.key)
            self._sem.release()


# singleton
llm_queue = RequestQueue(max_concurrent=2, max_queue=10)
