"""Data models for channel authorization."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class AuthChallenge:
    """A pending auth challenge for an unknown user."""

    code: str
    channel: str
    user_id: str
    user_name: str = ""
    created_at: datetime | None = None
    expires_at: datetime | None = None
    resolved: bool = False


@dataclass
class AuthorizedIdentity:
    """A user identity that has been authorized for a channel."""

    identity_key: str  # "channel:user_id"
    channel: str
    user_id: str
    user_name: str = ""
    authorized_at: datetime | None = None
    authorized_via: str = "auth_code"
