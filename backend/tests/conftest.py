import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import pytest


@pytest.fixture(autouse=True)
def _reset_perf_caches():
    """Isolate tests from the process-global LLM/search caches and queue.

    The perf layer memoizes reasoning and searches across a run; that's correct
    in production but would leak state between tests (e.g. call-count assertions
    would see cache hits from a prior test). Reset before each test.
    """
    from app.core import throttle
    import asyncio

    async def _clear():
        await throttle.llm_cache.clear()
        await throttle.search_cache.clear()

    asyncio.get_event_loop().run_until_complete(_clear()) if False else None
    # synchronous best-effort clear (caches expose plain dicts under the lock)
    throttle.llm_cache._data.clear()
    throttle.llm_cache.hits = throttle.llm_cache.misses = 0
    throttle.search_cache._data.clear()
    throttle.search_cache.hits = throttle.search_cache.misses = 0
    yield
