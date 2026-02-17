"""Auth manager — coordinates the challenge/confirmation flow."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from openhydra.events import (
    AUTH_CHALLENGE_CREATED,
    AUTH_IDENTITY_AUTHORIZED,
    AUTH_IDENTITY_REVOKED,
    Event,
)

if TYPE_CHECKING:
    from openhydra.events import EventBus

    from .store import AuthStore

logger = logging.getLogger(__name__)


class AuthManager:
    """Coordinates challenge flow between channels and the auth store."""

    def __init__(self, auth_store: AuthStore, events: EventBus) -> None:
        self._store = auth_store
        self._events = events

    async def challenge_unknown_user(
        self,
        channel: str,
        user_id: str,
        user_name: str = "",
    ) -> str:
        """Create an auth challenge for an unknown user.

        Returns the challenge code. Emits AUTH_CHALLENGE_CREATED event so
        the console/web can display the code to the owner.
        """
        challenge = await self._store.create_challenge(channel, user_id, user_name)

        await self._events.emit(Event(
            type=AUTH_CHALLENGE_CREATED,
            data={
                "code": challenge.code,
                "channel": channel,
                "user_id": user_id,
                "user_name": user_name,
            },
        ))

        logger.info(
            "AUTH: %s (%s) on %s wants to connect. Code: %s",
            user_name or user_id, user_id, channel, challenge.code,
        )
        return challenge.code

    async def confirm_challenge(self, code: str) -> bool:
        """Confirm an auth challenge code. Returns True if valid and user is now authorized."""
        challenge = await self._store.verify_challenge(code)
        if not challenge:
            return False

        identity = await self._store.authorize(
            channel=challenge.channel,
            user_id=challenge.user_id,
            user_name=challenge.user_name,
            via="auth_code",
        )

        await self._events.emit(Event(
            type=AUTH_IDENTITY_AUTHORIZED,
            data={
                "identity_key": identity.identity_key,
                "channel": challenge.channel,
                "user_id": challenge.user_id,
                "user_name": challenge.user_name,
            },
        ))

        logger.info(
            "AUTH: %s authorized on %s", challenge.user_id, challenge.channel,
        )
        return True

    async def manual_authorize(
        self,
        channel: str,
        user_id: str,
        user_name: str = "",
    ) -> None:
        """Manually authorize a user without a challenge."""
        identity = await self._store.authorize(
            channel=channel, user_id=user_id, user_name=user_name, via="manual",
        )
        await self._events.emit(Event(
            type=AUTH_IDENTITY_AUTHORIZED,
            data={
                "identity_key": identity.identity_key,
                "channel": channel,
                "user_id": user_id,
                "user_name": user_name,
                "via": "manual",
            },
        ))

    async def revoke_identity(self, channel: str, user_id: str) -> bool:
        """Revoke a user's authorization."""
        revoked = await self._store.revoke(channel, user_id)
        if revoked:
            await self._events.emit(Event(
                type=AUTH_IDENTITY_REVOKED,
                data={
                    "channel": channel,
                    "user_id": user_id,
                },
            ))
        return revoked
