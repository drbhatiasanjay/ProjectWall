from __future__ import annotations

import asyncio
from dataclasses import dataclass

import httpx


@dataclass
class HealthResult:
    ok: bool
    status: int | None
    latency_ms: int | None
    error: str | None = None


async def probe(url: str, timeout_s: float = 3.0) -> HealthResult:
    try:
        async with httpx.AsyncClient(timeout=timeout_s, follow_redirects=True) as client:
            t0 = asyncio.get_event_loop().time()
            resp = await client.get(url)
            elapsed = int((asyncio.get_event_loop().time() - t0) * 1000)
            return HealthResult(
                ok=resp.status_code < 500,
                status=resp.status_code,
                latency_ms=elapsed,
            )
    except httpx.HTTPError as exc:
        return HealthResult(ok=False, status=None, latency_ms=None, error=str(exc))


async def probe_many(urls: dict[str, str], timeout_s: float = 3.0) -> dict[str, HealthResult]:
    keys = list(urls.keys())
    tasks = [probe(urls[k], timeout_s) for k in keys]
    results = await asyncio.gather(*tasks, return_exceptions=False)
    return dict(zip(keys, results))
