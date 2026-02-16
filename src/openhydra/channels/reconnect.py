"""Reconnection utility — exponential backoff with jitter."""

from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass
from typing import Callable, Coroutine

logger = logging.getLogger(__name__)


@dataclass
class ReconnectConfig:
    max_retries: int = 0           # 0 = infinite
    base_delay_seconds: float = 2.0
    max_delay_seconds: float = 300.0
    backoff_factor: float = 1.8
    jitter: float = 0.25          # ±25% randomness


async def run_with_reconnect(
    connect_fn: Callable[[], Coroutine],
    config: ReconnectConfig | None = None,
    name: str = "connection",
) -> None:
    """Run connect_fn in a loop with exponential backoff.

    Resets attempt counter on success. Respects asyncio.CancelledError.
    """
    cfg = config or ReconnectConfig()
    attempt = 0

    while True:
        try:
            logger.info("Attempting %s (attempt %d)", name, attempt + 1)
            await connect_fn()
            # If connect_fn returns normally, it ran successfully then disconnected
            attempt = 0  # Reset on success
            logger.info("%s disconnected, will reconnect", name)
        except asyncio.CancelledError:
            logger.info("%s cancelled, stopping reconnect loop", name)
            raise
        except Exception as e:
            attempt += 1
            if cfg.max_retries > 0 and attempt >= cfg.max_retries:
                logger.error(
                    "%s failed after %d attempts, giving up: %s", name, attempt, e
                )
                raise

            delay = min(
                cfg.base_delay_seconds * (cfg.backoff_factor ** (attempt - 1)),
                cfg.max_delay_seconds,
            )
            # Add jitter
            jitter_range = delay * cfg.jitter
            delay += random.uniform(-jitter_range, jitter_range)
            delay = max(0.1, delay)

            logger.warning(
                "%s failed (attempt %d), retrying in %.1fs: %s",
                name, attempt, delay, e,
            )
            await asyncio.sleep(delay)
