from __future__ import annotations

import logging
import time
from typing import Callable, TypeVar

from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)
_T = TypeVar("_T")


def build_or_get_cached(cache_key: str, build_fn: Callable[[], _T]) -> _T:
    cache_family = cache_key.rsplit(":", 1)[0] if ":" in cache_key else cache_key
    cached = cache.get(cache_key)
    if cached is not None:
        logger.debug("stats_bundle hit family=%s key=%s", cache_family, cache_key)
        return cached  # type: ignore[return-value]
    t0 = time.perf_counter()
    result = build_fn()
    elapsed_ms = (time.perf_counter() - t0) * 1000
    logger.debug("stats_bundle miss family=%s key=%s elapsed_ms=%.1f", cache_family, cache_key, elapsed_ms)
    cache.set(cache_key, result, timeout=getattr(settings, "HOMOREPEAT_BROWSER_STATS_CACHE_TTL", 60))
    return result
