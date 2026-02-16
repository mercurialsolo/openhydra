"""Message debouncing — batch rapid messages from the same user."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class DebouncerConfig:
    delay_ms: int = 1500
    max_wait_ms: int = 5000


class MessageDebouncer:
    """Per-user message debouncer with asyncio timers.

    First caller for a key awaits the combined result. Subsequent callers for the
    same batch return None (their text is already buffered). Timer resets on new
    messages; max_wait_ms caps total wait time.
    """

    def __init__(self, config: DebouncerConfig | None = None) -> None:
        self._config = config or DebouncerConfig()
        self._buffers: dict[str, list[str]] = {}
        self._timers: dict[str, asyncio.TimerHandle] = {}
        self._events: dict[str, asyncio.Event] = {}
        self._results: dict[str, str | None] = {}
        self._max_timers: dict[str, asyncio.TimerHandle] = {}

    async def debounce(self, user_key: str, text: str) -> str | None:
        """Returns combined text when window closes, None if still buffering.

        Only the first caller for a given batch awaits and gets the result.
        """
        is_first = user_key not in self._buffers

        if is_first:
            self._buffers[user_key] = [text]
            self._events[user_key] = asyncio.Event()
            self._results[user_key] = None
            self._schedule_timer(user_key)
            self._schedule_max_timer(user_key)
            # First caller waits for the debounce window to close
            await self._events[user_key].wait()
            result = self._results.pop(user_key, None)
            self._events.pop(user_key, None)
            return result
        else:
            self._buffers[user_key].append(text)
            self._schedule_timer(user_key)
            return None

    def _schedule_timer(self, user_key: str) -> None:
        """Schedule or reschedule the debounce delay timer."""
        if user_key in self._timers:
            self._timers[user_key].cancel()
        loop = asyncio.get_event_loop()
        delay = self._config.delay_ms / 1000.0
        self._timers[user_key] = loop.call_later(delay, self._fire, user_key)

    def _schedule_max_timer(self, user_key: str) -> None:
        """Schedule the max wait timer (non-resettable)."""
        loop = asyncio.get_event_loop()
        max_delay = self._config.max_wait_ms / 1000.0
        self._max_timers[user_key] = loop.call_later(max_delay, self._fire, user_key)

    def _fire(self, user_key: str) -> None:
        """Combine buffered messages and release the waiting caller."""
        if user_key not in self._buffers:
            return
        texts = self._buffers.pop(user_key)
        combined = "\n".join(texts)
        self._results[user_key] = combined

        # Cancel timers
        if user_key in self._timers:
            self._timers.pop(user_key).cancel()
        if user_key in self._max_timers:
            self._max_timers.pop(user_key).cancel()

        # Wake up the waiting caller
        event = self._events.get(user_key)
        if event:
            event.set()

    async def stop(self) -> None:
        """Cancel all pending timers."""
        for handle in self._timers.values():
            handle.cancel()
        for handle in self._max_timers.values():
            handle.cancel()
        # Release any waiting callers
        for event in self._events.values():
            event.set()
        self._buffers.clear()
        self._timers.clear()
        self._max_timers.clear()
