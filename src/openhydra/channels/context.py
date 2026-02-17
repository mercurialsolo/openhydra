"""ChannelContext — bundles shared services every channel needs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .permissions import ChannelPermissions


@dataclass
class ChannelContext:
    """Shared services passed to every channel factory.

    Replaces the 5+ separate constructor parameters that were repeated
    across all channel adapters.
    """

    engine: Any  # Engine or RestrictedEngine (typed as Any to avoid import cycle)
    sessions: Any | None = None  # SessionStore
    debouncer: Any | None = None  # MessageDebouncer
    auth_store: Any | None = None  # AuthStore
    auth_manager: Any | None = None  # AuthManager
    permissions: ChannelPermissions = field(default_factory=ChannelPermissions.full_access)
