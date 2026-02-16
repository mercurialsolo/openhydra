"""Channel protocol — the interface every messaging channel implements."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol, runtime_checkable


@dataclass
class ChannelMessage:
    """Inbound message from any channel."""

    text: str
    channel_id: str = ""         # Slack channel, Discord guild, WhatsApp phone, etc.
    thread_id: str = ""          # Thread/conversation context
    user_id: str = ""            # Sender identifier
    user_name: str = ""          # Human-readable sender name
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class ChannelResponse:
    """Outbound response to a channel."""

    text: str
    channel_id: str = ""
    thread_id: str = ""
    blocks: list[dict[str, Any]] | None = None   # Rich formatting (Slack blocks, Discord embeds)
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class Channel(Protocol):
    """Protocol for messaging channel adapters.

    Each channel connects to its platform (REST, WebSocket, bot gateway)
    and translates between platform messages and Engine operations.
    """

    @property
    def name(self) -> str:
        """Unique channel name (e.g. 'web', 'slack', 'discord', 'whatsapp')."""
        ...

    async def start(self) -> None:
        """Start the channel (connect to platform, begin listening)."""
        ...

    async def stop(self) -> None:
        """Stop the channel gracefully."""
        ...

    async def send_message(self, user_id: str, text: str) -> None:
        """Send a message to a specific user on this channel."""
        ...
