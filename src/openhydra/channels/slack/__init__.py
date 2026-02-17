"""Slack channel — bot adapter using Socket Mode."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from openhydra.channels.base import Channel
    from openhydra.channels.context import ChannelContext


def create_channel(config: dict[str, Any], ctx: ChannelContext) -> Channel:
    """Factory for the Slack channel."""
    from openhydra.config import SlackConfig

    from .adapter import SlackChannel

    cfg = SlackConfig(**{k: v for k, v in config.items() if k in SlackConfig.__dataclass_fields__})
    return SlackChannel(cfg, ctx)
