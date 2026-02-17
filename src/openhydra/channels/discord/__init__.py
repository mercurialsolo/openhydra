"""Discord channel — bot adapter using discord.py Gateway."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from openhydra.channels.base import Channel
    from openhydra.channels.context import ChannelContext


def create_channel(config: dict[str, Any], ctx: ChannelContext) -> Channel:
    """Factory for the Discord channel."""
    from openhydra.config import DiscordConfig

    from .adapter import DiscordChannel

    cfg = DiscordConfig(
        **{k: v for k, v in config.items() if k in DiscordConfig.__dataclass_fields__},
    )
    return DiscordChannel(cfg, ctx)
