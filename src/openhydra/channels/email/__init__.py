"""Email channel — IMAP/SMTP adapter."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from openhydra.channels.base import Channel
    from openhydra.channels.context import ChannelContext


def create_channel(config: dict[str, Any], ctx: ChannelContext) -> Channel:
    """Factory for the Email channel."""
    from openhydra.config import EmailConfig

    from .adapter import EmailChannel

    cfg = EmailConfig(
        **{k: v for k, v in config.items() if k in EmailConfig.__dataclass_fields__}
    )
    return EmailChannel(cfg, ctx)
