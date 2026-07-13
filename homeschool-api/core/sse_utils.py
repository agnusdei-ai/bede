"""
Shared helper for every SSE-streaming router (tutor, sandbox) — guards
against an upstream stall (a hung Anthropic API call, a network
black-hole) leaving a stream open with no more bytes ever coming. Without
this, the browser's own reader.read() on the other end waits forever with
no client-side timeout of its own either, so the UI's send button spins
indefinitely with no way to recover short of reloading the page.
"""

import asyncio
import logging
from typing import AsyncIterator, TypeVar

log = logging.getLogger(__name__)

_T = TypeVar("_T")

# How long a single "step" of a stream (the gap between one SSE chunk and
# the next) may take before this gives up on it. Generous relative to
# these models' normal per-chunk latency, but short enough that a real
# stall surfaces as a recoverable error well within the range of "the
# child gave up waiting."
STREAM_STALL_TIMEOUT_SECONDS = 45.0


async def with_stall_timeout(agen: AsyncIterator[_T], timeout_seconds: float = STREAM_STALL_TIMEOUT_SECONDS) -> AsyncIterator[_T]:
    """Wraps any async generator so that if it doesn't produce its NEXT item
    within timeout_seconds, iteration raises asyncio.TimeoutError instead of
    hanging forever — the timer resets on every item actually produced, so
    this only catches a genuine stall, not a slow-but-steady stream."""
    it = agen.__aiter__()
    while True:
        try:
            item = await asyncio.wait_for(it.__anext__(), timeout=timeout_seconds)
        except StopAsyncIteration:
            return
        yield item
