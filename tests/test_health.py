"""Health probe tests.

Kept as sync tests that drive the async API through asyncio.run() to avoid
the pytest-asyncio / pytest-playwright event-loop collision that occurs when
both plugins are loaded in the same session.
"""
from __future__ import annotations

import asyncio
import threading
from typing import Any, Callable, Coroutine

from project_wall.health import probe, probe_many


def _run(coro_factory: Callable[[], Coroutine[Any, Any, Any]]) -> Any:
    """Drive a coroutine on a fresh event loop in a side thread.

    The main thread already has a running asyncio loop (installed by
    pytest-asyncio / pytest-playwright for the session). That loop's
    `_check_running` rejects any new `run_until_complete` on the same thread.
    Since the running-loop flag is per-thread, spinning up a worker thread
    with its own loop sidesteps the check cleanly.
    """
    result: list[Any] = []
    error: list[BaseException] = []

    def runner() -> None:
        loop = asyncio.new_event_loop()
        try:
            result.append(loop.run_until_complete(coro_factory()))
        except BaseException as exc:  # pragma: no cover - propagated below
            error.append(exc)
        finally:
            loop.close()

    t = threading.Thread(target=runner)
    t.start()
    t.join()
    if error:
        raise error[0]
    return result[0]


def test_probe_reachable_url(http_server: str) -> None:
    result = _run(lambda: probe(http_server, timeout_s=3.0))
    assert result.ok is True
    assert result.status == 200
    assert result.latency_ms is not None
    assert result.latency_ms >= 0
    assert result.error is None


def test_probe_unreachable_url() -> None:
    # Port 1 is reserved; nothing should bind there.
    result = _run(lambda: probe("http://127.0.0.1:1/", timeout_s=1.0))
    assert result.ok is False
    assert result.error is not None


def test_probe_many_mixed(http_server: str) -> None:
    results = _run(
        lambda: probe_many(
            {"up": http_server, "down": "http://127.0.0.1:1/"},
            timeout_s=1.5,
        )
    )
    assert results["up"].ok is True
    assert results["down"].ok is False


def test_probe_many_empty() -> None:
    assert _run(lambda: probe_many({})) == {}
