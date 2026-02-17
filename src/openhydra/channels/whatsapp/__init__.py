"""WhatsApp channel — Baileys or Cloud API adapter."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from openhydra.channels.base import Channel
    from openhydra.channels.context import ChannelContext


def create_channel(config: dict[str, Any], ctx: ChannelContext) -> Channel:
    """Factory for the WhatsApp channel."""
    from openhydra.config import WhatsAppConfig

    from .adapter import WhatsAppChannel

    cfg = WhatsAppConfig(
        **{k: v for k, v in config.items() if k in WhatsAppConfig.__dataclass_fields__},
    )
    return WhatsAppChannel(cfg, ctx)
