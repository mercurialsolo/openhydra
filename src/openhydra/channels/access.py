"""Shared access control — deduplicated from channel handlers."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Callable, Coroutine

if TYPE_CHECKING:
    from openhydra.channels.auth.manager import AuthManager
    from openhydra.channels.auth.store import AuthStore

logger = logging.getLogger(__name__)

# Type alias for the optional notify callback
NotifyFn = Callable[[str], Coroutine[Any, Any, Any]]


class AccessControl:
    """Centralised access check: config allowlist > auth store > challenge.

    Replaces the identical ``_check_access()`` that was copy-pasted in the
    Slack, Discord and WhatsApp handlers.
    """

    def __init__(
        self,
        allowed_ids: list[str] | None = None,
        auth_store: AuthStore | None = None,
        auth_manager: AuthManager | None = None,
    ) -> None:
        self._allowed_ids = allowed_ids or []
        self._auth_store = auth_store
        self._auth_manager = auth_manager

    async def check(self, channel_name: str, user_id: str) -> bool:
        """Return ``True`` if the user is allowed to interact.

        Priority order:
        1. Config allowlist (if non-empty) — definitive yes/no.
        2. Auth store lookup — previously authorised identities.
        3. No allowlist + no auth store → allow all (backward compat).
        """
        if self._allowed_ids:
            return user_id in self._allowed_ids

        if not self._auth_store:
            return True

        if await self._auth_store.is_authorized(channel_name, user_id):
            return True

        # Trigger challenge for unknown user
        if self._auth_manager:
            await self._auth_manager.challenge_unknown_user(channel_name, user_id)

        return False

    async def check_and_notify(
        self,
        channel_name: str,
        user_id: str,
        notify_fn: NotifyFn | None = None,
    ) -> bool:
        """Like :meth:`check`, but calls *notify_fn* with a message when denied via challenge."""
        if self._allowed_ids:
            return user_id in self._allowed_ids

        if not self._auth_store:
            return True

        if await self._auth_store.is_authorized(channel_name, user_id):
            return True

        if self._auth_manager:
            await self._auth_manager.challenge_unknown_user(channel_name, user_id)
            if notify_fn:
                await notify_fn(
                    "Auth code has been displayed on the owner's machine. "
                    "Please ask the owner to confirm your access."
                )

        return False
