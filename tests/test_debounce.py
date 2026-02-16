"""Tests for message debouncing."""

from __future__ import annotations

import asyncio

import pytest

from openhydra.channels.debounce import DebouncerConfig, MessageDebouncer


@pytest.mark.asyncio
async def test_single_message_returned_after_delay():
    debouncer = MessageDebouncer(DebouncerConfig(delay_ms=50, max_wait_ms=500))
    result = await debouncer.debounce("user1", "hello")
    assert result == "hello"
    await debouncer.stop()


@pytest.mark.asyncio
async def test_rapid_messages_batched():
    debouncer = MessageDebouncer(DebouncerConfig(delay_ms=100, max_wait_ms=2000))

    results = []

    async def send_first():
        r = await debouncer.debounce("user1", "msg1")
        results.append(("first", r))

    async def send_second():
        await asyncio.sleep(0.02)  # 20ms later
        r = await debouncer.debounce("user1", "msg2")
        results.append(("second", r))

    await asyncio.gather(send_first(), send_second())

    # First caller should get combined text, second returns None
    first_results = [r for name, r in results if name == "first"]
    second_results = [r for name, r in results if name == "second"]

    assert len(first_results) == 1
    assert "msg1" in first_results[0]
    assert "msg2" in first_results[0]
    assert second_results == [None]

    await debouncer.stop()


@pytest.mark.asyncio
async def test_different_users_independent():
    debouncer = MessageDebouncer(DebouncerConfig(delay_ms=50, max_wait_ms=500))

    async def user_a():
        return await debouncer.debounce("userA", "a-msg")

    async def user_b():
        return await debouncer.debounce("userB", "b-msg")

    ra, rb = await asyncio.gather(user_a(), user_b())
    assert ra == "a-msg"
    assert rb == "b-msg"

    await debouncer.stop()


@pytest.mark.asyncio
async def test_max_wait_fires():
    debouncer = MessageDebouncer(DebouncerConfig(delay_ms=500, max_wait_ms=100))

    # max_wait < delay, so max_wait should fire first
    result = await debouncer.debounce("user1", "hello")
    assert result == "hello"
    await debouncer.stop()


@pytest.mark.asyncio
async def test_stop_releases_waiters():
    debouncer = MessageDebouncer(DebouncerConfig(delay_ms=10000, max_wait_ms=10000))

    async def slow():
        return await debouncer.debounce("user1", "msg")

    task = asyncio.create_task(slow())
    await asyncio.sleep(0.02)
    await debouncer.stop()
    # Task should complete (event was set)
    result = await asyncio.wait_for(task, timeout=1.0)
    # Result may be None since stop clears buffers before fire
    assert result is None or result == "msg"


@pytest.mark.asyncio
async def test_sequential_batches():
    debouncer = MessageDebouncer(DebouncerConfig(delay_ms=30, max_wait_ms=500))

    # First batch
    r1 = await debouncer.debounce("user1", "batch1")
    assert r1 == "batch1"

    # Second batch (after first completes)
    r2 = await debouncer.debounce("user1", "batch2")
    assert r2 == "batch2"

    await debouncer.stop()
