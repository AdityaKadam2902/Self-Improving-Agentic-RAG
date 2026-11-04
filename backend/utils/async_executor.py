"""
Async execution utilities for threadpool worker offloading.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from functools import wraps
from typing import Any, Callable, TypeVar

T = TypeVar("T")

# Dedicated worker pool for CPU-bound operations (embeddings, cross-encoders, BM25)
_MODEL_THREAD_POOL = ThreadPoolExecutor(max_workers=6, thread_name_prefix="rag_worker_")


async def run_in_threadpool(func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """
    Execute a synchronous, CPU-intensive function in the dedicated worker threadpool.
    Ensures the FastAPI async event loop is never blocked by model inferences.
    """
    loop = asyncio.get_running_loop()
    if kwargs:
        return await loop.run_in_executor(_MODEL_THREAD_POOL, lambda: func(*args, **kwargs))
    return await loop.run_in_executor(_MODEL_THREAD_POOL, func, *args)


def threadpool_offload(func: Callable[..., T]) -> Callable[..., asyncio.Future[T]]:
    """
    Decorator to automatically run synchronous functions inside the worker threadpool.
    """
    @wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> T:
        return await run_in_threadpool(func, *args, **kwargs)

    return wrapper
