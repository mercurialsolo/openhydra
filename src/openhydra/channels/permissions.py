"""Channel permission model — controls what external plugins can access."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ChannelPermissions:
    """Permission flags for a channel's access to Engine internals."""

    can_submit: bool = True
    can_read_status: bool = True
    can_access_sessions: bool = True
    can_emit_events: bool = False
    can_access_db: bool = False
    max_submissions_per_hour: int = 10  # 0 = unlimited

    @classmethod
    def full_access(cls) -> ChannelPermissions:
        """Unrestricted permissions for bundled channels."""
        return cls(
            can_submit=True,
            can_read_status=True,
            can_access_sessions=True,
            can_emit_events=True,
            can_access_db=True,
            max_submissions_per_hour=0,
        )

    @classmethod
    def restricted(cls, overrides: dict | None = None) -> ChannelPermissions:
        """Default restricted permissions for external plugins."""
        perms = cls()  # defaults are already restricted
        if overrides:
            for key, val in overrides.items():
                if hasattr(perms, key):
                    setattr(perms, key, val)
        return perms
