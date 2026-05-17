"""Async helpers for running blocking AKShare calls safely."""

from __future__ import annotations

import asyncio
import os
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import Any, Callable, TypeVar

T = TypeVar("T")

_MAX_WORKERS = int(os.getenv("OPENFR_AKSHARE_MAX_WORKERS", "4"))
_AKSHARE_EXECUTOR = ThreadPoolExecutor(
    max_workers=_MAX_WORKERS,
    thread_name_prefix="openfr-akshare",
)


async def run_blocking(func: Callable[..., T], /, *args: Any, **kwargs: Any) -> T:
    """Run one blocking AKShare-bound function without blocking the event loop."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_AKSHARE_EXECUTOR, partial(func, *args, **kwargs))


async def gather_blocking(
    calls: list[tuple[str, Callable[..., Any], tuple[Any, ...], dict[str, Any]]],
    timeout: float | None = None,
) -> dict[str, Any]:
    """Run multiple blocking data calls concurrently and keep partial failures isolated."""

    async def _run(name: str, func: Callable[..., Any], args: tuple[Any, ...], kwargs: dict[str, Any]):
        try:
            return name, await run_blocking(func, *args, **kwargs), None
        except Exception as exc:
            return name, None, str(exc)

    async def _maybe_cap(name: str, func: Callable[..., Any], args: tuple[Any, ...], kwargs: dict[str, Any]):
        try:
            if timeout is None:
                return await _run(name, func, args, kwargs)
            # builtins.TimeoutError == asyncio.TimeoutError (3.11+)
            return await asyncio.wait_for(_run(name, func, args, kwargs), timeout=timeout)
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            return (
                name,
                None,
                "timed out waiting for akshare call (executor thread may still finish in background)",
            )
        except Exception as exc:
            return (name, None, str(exc))

    capped = [_maybe_cap(name, func, args, kwargs) for name, func, args, kwargs in calls]
    results = await asyncio.gather(*capped, return_exceptions=True)

    payload: dict[str, Any] = {}
    for i, res in enumerate(results):
        name = calls[i][0]
        if isinstance(res, asyncio.CancelledError):
            raise res
        if isinstance(res, BaseException):
            payload[name] = {"value": None, "error": str(res)}
            continue
        entry_name, value, error = res
        payload[entry_name] = {"value": value, "error": error}
    return payload
