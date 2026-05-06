from __future__ import annotations

import asyncio
from collections import deque
from pathlib import Path
from threading import Lock
from typing import IO


class ProjectLog:
    def __init__(self, path: Path, tail_size: int = 500):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._tail: deque[str] = deque(maxlen=tail_size)
        self._lock = Lock()
        self._fh: IO[str] | None = None
        self._sub_id = 0
        self._subscribers: dict[int, tuple[asyncio.AbstractEventLoop, asyncio.Queue[str]]] = {}

    def open(self) -> IO[str]:
        if self._fh is None or self._fh.closed:
            self._fh = open(self.path, "a", encoding="utf-8", buffering=1)
        return self._fh

    def subscribe(self, loop: asyncio.AbstractEventLoop) -> tuple[int, asyncio.Queue[str]]:
        """Register a live-tail subscriber. Returns (sid, queue) for the caller to await on."""
        q: asyncio.Queue[str] = asyncio.Queue()
        with self._lock:
            sid = self._sub_id
            self._sub_id += 1
            self._subscribers[sid] = (loop, q)
        return sid, q

    def unsubscribe(self, sid: int) -> None:
        with self._lock:
            self._subscribers.pop(sid, None)

    def write(self, line: str) -> None:
        clean = line.rstrip("\n")
        with self._lock:
            fh = self.open()
            fh.write(line if line.endswith("\n") else line + "\n")
            self._tail.append(clean)
            for loop, q in list(self._subscribers.values()):
                loop.call_soon_threadsafe(q.put_nowait, clean)

    def tail(self, n: int = 100) -> list[str]:
        with self._lock:
            if n >= len(self._tail):
                return list(self._tail)
            return list(self._tail)[-n:]

    def close(self) -> None:
        with self._lock:
            if self._fh and not self._fh.closed:
                self._fh.close()
            self._fh = None
