"""In-process pub/sub for SSE (/api/events) with a small replay buffer (Last-Event-ID)."""
from __future__ import annotations

import asyncio
import json
from collections import deque
from typing import Any

Event = tuple[int, str, dict[str, Any]]  # (id, name, data)


class EventHub:
    def __init__(self, replay: int = 200) -> None:
        self._subs: set[asyncio.Queue[Event]] = set()
        self._buf: deque[Event] = deque(maxlen=replay)
        self._seq = 0

    def subscribe(self) -> asyncio.Queue[Event]:
        q: asyncio.Queue[Event] = asyncio.Queue(maxsize=1000)
        self._subs.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subs.discard(q)

    def since(self, last_id: int = 0) -> list[Event]:
        return [e for e in self._buf if e[0] > last_id]

    def close(self) -> None:
        """Wake every SSE generator with a sentinel so shutdown is not blocked."""
        for q in list(self._subs):
            try:
                q.put_nowait((0, "__close__", {}))
            except asyncio.QueueFull:
                pass

    def publish(self, event: str, data: dict[str, Any]) -> None:
        self._seq += 1
        item: Event = (self._seq, event, data)
        self._buf.append(item)
        for q in list(self._subs):
            try:
                q.put_nowait(item)
            except asyncio.QueueFull:  # slow consumer: drop it rather than block the runner
                self._subs.discard(q)

    @staticmethod
    def format(event: str, data: dict[str, Any], event_id: int | None = None) -> str:
        head = f"id: {event_id}\n" if event_id is not None else ""
        return f"{head}event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
