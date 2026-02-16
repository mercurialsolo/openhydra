"""Tests for reconnection with exponential backoff."""

from __future__ import annotations

import asyncio
import time

import pytest

from openhydra.channels.reconnect import ReconnectConfig, run_with_reconnect


@pytest.mark.asyncio
async def test_success_first_try():
    """connect_fn runs once; after it returns, loop continues (reconnect behavior)."""
    calls = []

    async def connect():
        calls.append(1)
        if len(calls) >= 2:
            raise asyncio.CancelledError  # Exit loop on second try

    task = asyncio.create_task(
        run_with_reconnect(connect, ReconnectConfig(max_retries=0), name="test")
    )
    with pytest.raises(asyncio.CancelledError):
        await task
    # First call succeeded, second call exited
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_retries_on_failure():
    attempt = 0

    async def connect():
        nonlocal attempt
        attempt += 1
        if attempt < 3:
            raise ConnectionError("fail")
        # Success on third attempt, then exit
        raise asyncio.CancelledError

    task = asyncio.create_task(
        run_with_reconnect(
            connect,
            ReconnectConfig(max_retries=5, base_delay_seconds=0.01, jitter=0),
            name="test",
        )
    )
    with pytest.raises(asyncio.CancelledError):
        await task
    assert attempt == 3


@pytest.mark.asyncio
async def test_max_retries_exceeded():
    async def connect():
        raise ConnectionError("always fails")

    with pytest.raises(ConnectionError):
        await run_with_reconnect(
            connect,
            ReconnectConfig(max_retries=3, base_delay_seconds=0.01, jitter=0),
            name="test",
        )


@pytest.mark.asyncio
async def test_cancellation_propagates():
    calls = []

    async def connect():
        calls.append(1)
        await asyncio.sleep(10)  # Simulates long connection

    task = asyncio.create_task(
        run_with_reconnect(connect, ReconnectConfig(max_retries=0), name="test")
    )
    await asyncio.sleep(0.02)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert len(calls) >= 1


@pytest.mark.asyncio
async def test_exponential_backoff_delays():
    """Verify delays increase with each retry."""
    timestamps = []

    async def connect():
        timestamps.append(time.monotonic())
        if len(timestamps) < 4:
            raise ConnectionError("fail")
        raise asyncio.CancelledError  # Exit after success

    task = asyncio.create_task(
        run_with_reconnect(
            connect,
            ReconnectConfig(
                max_retries=5,
                base_delay_seconds=0.05,
                backoff_factor=2.0,
                max_delay_seconds=10.0,
                jitter=0,
            ),
            name="test",
        )
    )
    with pytest.raises(asyncio.CancelledError):
        await task

    assert len(timestamps) == 4
    # Check last delay is at least larger than first
    delays = [timestamps[i + 1] - timestamps[i] for i in range(len(timestamps) - 1)]
    # Third delay (0.05*4=0.2) should be larger than first (0.05)
    assert delays[2] > delays[0]


@pytest.mark.asyncio
async def test_resets_on_success_then_reconnect():
    """Attempt counter resets after a successful connection."""
    calls = []

    async def connect():
        calls.append(len(calls) + 1)
        if len(calls) == 1:
            return  # First run succeeds, then disconnects
        if len(calls) == 2:
            raise ConnectionError("fail after reconnect")
        # Third call: success
        raise asyncio.CancelledError  # Exit loop

    task = asyncio.create_task(
        run_with_reconnect(
            connect,
            ReconnectConfig(max_retries=0, base_delay_seconds=0.01, jitter=0),
            name="test",
        )
    )
    with pytest.raises(asyncio.CancelledError):
        await task

    assert len(calls) == 3


@pytest.mark.asyncio
async def test_default_config():
    cfg = ReconnectConfig()
    assert cfg.max_retries == 0
    assert cfg.base_delay_seconds == 2.0
    assert cfg.max_delay_seconds == 300.0
    assert cfg.backoff_factor == 1.8
    assert cfg.jitter == 0.25
