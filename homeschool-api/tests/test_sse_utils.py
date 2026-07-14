"""
Real check for core/sse_utils.py's with_stall_timeout — the guard against
an upstream stall (a hung Anthropic API call, a network black-hole)
leaving an SSE stream open with no more bytes ever coming. Without this,
a stuck stream just hangs forever with nothing to time it out — see
routers/tutor.py and routers/sandbox.py's own event_generator functions,
which wrap every LLM stream in this.
"""
import asyncio

import pytest

from core.sse_utils import with_stall_timeout


async def _fast_gen():
    for i in range(3):
        yield i


async def _stalling_gen(stall_at: int, stall_seconds: float):
    for i in range(5):
        if i == stall_at:
            await asyncio.sleep(stall_seconds)
        yield i


@pytest.mark.asyncio
async def test_passes_through_a_normal_generator_unchanged():
    items = [i async for i in with_stall_timeout(_fast_gen(), timeout_seconds=1.0)]
    assert items == [0, 1, 2]


@pytest.mark.asyncio
async def test_raises_timeout_error_when_a_step_stalls_past_the_limit():
    with pytest.raises(asyncio.TimeoutError):
        async for _ in with_stall_timeout(_stalling_gen(stall_at=1, stall_seconds=0.3), timeout_seconds=0.05):
            pass


@pytest.mark.asyncio
async def test_timeout_resets_on_every_item_not_just_the_first():
    """A generator that's merely slow-but-steady (each individual gap under
    the limit) must not be treated as stalled just because its TOTAL
    runtime exceeds one timeout window."""
    async def slow_but_steady():
        for i in range(4):
            await asyncio.sleep(0.03)
            yield i

    items = [i async for i in with_stall_timeout(slow_but_steady(), timeout_seconds=0.1)]
    assert items == [0, 1, 2, 3]


@pytest.mark.asyncio
async def test_items_already_yielded_before_a_stall_are_not_lost():
    seen = []
    with pytest.raises(asyncio.TimeoutError):
        async for item in with_stall_timeout(_stalling_gen(stall_at=2, stall_seconds=0.3), timeout_seconds=0.05):
            seen.append(item)
    assert seen == [0, 1]
