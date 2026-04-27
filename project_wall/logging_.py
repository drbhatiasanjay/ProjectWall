from __future__ import annotations

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

    def open(self) -> IO[str]:
        if self._fh is None or self._fh.closed:
            self._fh = open(self.path, "a", encoding="utf-8", buffering=1)
        return self._fh

    def write(self, line: str) -> None:
        with self._lock:
            fh = self.open()
            fh.write(line if line.endswith("\n") else line + "\n")
            self._tail.append(line.rstrip("\n"))

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
