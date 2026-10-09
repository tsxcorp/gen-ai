"""Per-model concurrency limiter (semaphore) + optional min-interval rate limit."""
from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager


class Limiter:
    def __init__(self) -> None:
        self._sems: dict[str, asyncio.Semaphore] = {}
        self._next_at: dict[str, float] = {}
        self._lock = asyncio.Lock()
        self.active: dict[str, int] = {}
        self.peak: dict[str, int] = {}

    def _sem(self, model_id: str, max_concurrent: int) -> asyncio.Semaphore:
        if model_id not in self._sems:
            self._sems[model_id] = asyncio.Semaphore(max(1, max_concurrent))
        return self._sems[model_id]

    @asynccontextmanager
    async def slot(self, model_id: str, max_concurrent: int, rpm: int | None = None):
        async with self._sem(model_id, max_concurrent):
            if rpm:
                async with self._lock:
                    wait = self._next_at.get(model_id, 0.0) - time.monotonic()
                    self._next_at[model_id] = max(time.monotonic(), self._next_at.get(model_id, 0.0)) + 60.0 / rpm
                if wait > 0:
                    await asyncio.sleep(wait)
            n = self.active.get(model_id, 0) + 1
            self.active[model_id] = n
            self.peak[model_id] = max(self.peak.get(model_id, 0), n)
            try:
                yield
            finally:
                self.active[model_id] -= 1
