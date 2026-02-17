"""Web channel — REST API + WebSocket for OpenHydra."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from openhydra.channels.base import Channel
    from openhydra.channels.context import ChannelContext


def create_channel(config: dict[str, Any], ctx: ChannelContext) -> Channel:
    """Factory for the web channel."""
    from openhydra.config import WebConfig

    from .server import WebChannel

    cfg = WebConfig(**{k: v for k, v in config.items() if k in WebConfig.__dataclass_fields__})
    return WebChannel(cfg, ctx)
