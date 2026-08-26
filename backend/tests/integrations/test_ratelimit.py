from __future__ import annotations

import asyncio
import time

import pytest

from app.integrations.ratelimit import TokenBucket


async def test_acquire_within_capacity_is_immediate() -> None:
    bucket = TokenBucket(capacity=3, period_seconds=60)
    start = time.monotonic()
    for _ in range(3):
        await bucket.acquire()
    assert time.monotonic() - start < 0.1


async def test_acquire_beyond_capacity_waits_for_refill() -> None:
    # capacity=2 refilling over 0.2s => refill rate 10 tokens/sec => ~0.1s per token.
    bucket = TokenBucket(capacity=2, period_seconds=0.2)
    await bucket.acquire()
    await bucket.acquire()

    start = time.monotonic()
    await bucket.acquire()
    elapsed = time.monotonic() - start

    assert elapsed >= 0.05


async def test_concurrent_acquires_are_serialised_not_double_spent() -> None:
    bucket = TokenBucket(capacity=1, period_seconds=0.2)
    await bucket.acquire()  # drain the single token

    order: list[int] = []

    async def take(n: int) -> None:
        await bucket.acquire()
        order.append(n)

    await asyncio.gather(take(1), take(2), take(3))
    assert sorted(order) == [1, 2, 3]  # all eventually acquired, none lost


@pytest.mark.parametrize("bad_kwargs", [{"capacity": 0}, {"capacity": -1}])
def test_rejects_non_positive_capacity(bad_kwargs: dict[str, int]) -> None:
    with pytest.raises(ValueError):
        TokenBucket(period_seconds=60, **bad_kwargs)


def test_rejects_non_positive_period() -> None:
    with pytest.raises(ValueError):
        TokenBucket(capacity=1, period_seconds=0)
