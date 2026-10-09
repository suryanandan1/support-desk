"""Bounded retries with exponential backoff for AI provider calls."""

import logging
import random
import time
from collections.abc import Callable
from typing import TypeVar

from app.rag.providers.base import ProviderError

logger = logging.getLogger(__name__)

T = TypeVar("T")


def call_with_retries(
    func: Callable[[], T],
    *,
    retries: int,
    base_delay: float,
    max_delay: float = 8.0,
    description: str = "Provider call",
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """Call ``func``; on a retryable ProviderError try again up to ``retries`` more times.

    Waits base_delay, 2*base_delay, 4*base_delay ... (capped at max_delay, with jitter
    so many clients do not retry in lockstep). Non-retryable errors are raised at once.
    """
    for attempt in range(retries + 1):
        try:
            return func()
        except ProviderError as exc:
            if not exc.retryable or attempt == retries:
                raise
            delay = min(max_delay, base_delay * (2**attempt)) * random.uniform(0.5, 1.0)
            logger.warning(
                "%s failed (attempt %d of %d): %s. Retrying in %.1fs",
                description,
                attempt + 1,
                retries + 1,
                exc,
                delay,
            )
            sleep(delay)
    raise AssertionError("unreachable")  # the loop always returns or raises
