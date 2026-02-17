"""SQLite-backed identity and challenge store with in-memory cache."""

from __future__ import annotations

import random
import string
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from .models import AuthChallenge, AuthorizedIdentity

if TYPE_CHECKING:
    from openhydra.db import Database

# Characters that avoid confusion (no 0/O, 1/I/L)
_CODE_CHARS = string.ascii_uppercase.replace("O", "").replace("I", "").replace("L", "") + "23456789"
_CODE_LENGTH = 6
_CHALLENGE_TTL_MINUTES = 5


class AuthStore:
    """SQLite-backed identity persistence and challenge management."""

    def __init__(self, db: Database) -> None:
        self._db = db
        self._cache: set[str] = set()  # identity_keys of authorized users
        self._loaded = False

    async def _ensure_cache(self) -> None:
        """Load authorized identities into memory cache on first access."""
        if self._loaded:
            return
        cursor = await self._db.conn.execute(
            "SELECT identity_key FROM authorized_identities",
        )
        rows = await cursor.fetchall()
        self._cache = {row["identity_key"] for row in rows}
        self._loaded = True

    def _make_key(self, channel: str, user_id: str) -> str:
        return f"{channel}:{user_id}"

    async def is_authorized(self, channel: str, user_id: str) -> bool:
        """Check if a user is authorized (fast, cached)."""
        await self._ensure_cache()
        return self._make_key(channel, user_id) in self._cache

    async def authorize(
        self,
        channel: str,
        user_id: str,
        user_name: str = "",
        via: str = "auth_code",
    ) -> AuthorizedIdentity:
        """Authorize a user identity."""
        key = self._make_key(channel, user_id)
        await self._db.conn.execute(
            "INSERT INTO authorized_identities "
            "(identity_key, channel, user_id, user_name, authorized_via) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(identity_key) DO UPDATE SET user_name = ?, authorized_via = ?",
            (key, channel, user_id, user_name, via, user_name, via),
        )
        await self._db.conn.commit()
        self._cache.add(key)
        return AuthorizedIdentity(
            identity_key=key,
            channel=channel,
            user_id=user_id,
            user_name=user_name,
            authorized_via=via,
        )

    async def revoke(self, channel: str, user_id: str) -> bool:
        """Revoke a user's authorization."""
        key = self._make_key(channel, user_id)
        cursor = await self._db.conn.execute(
            "DELETE FROM authorized_identities WHERE identity_key = ?", (key,),
        )
        await self._db.conn.commit()
        self._cache.discard(key)
        return cursor.rowcount > 0

    async def list_identities(self, channel: str | None = None) -> list[AuthorizedIdentity]:
        """List authorized identities, optionally filtered by channel."""
        if channel:
            cursor = await self._db.conn.execute(
                "SELECT * FROM authorized_identities WHERE channel = ? ORDER BY authorized_at",
                (channel,),
            )
        else:
            cursor = await self._db.conn.execute(
                "SELECT * FROM authorized_identities ORDER BY authorized_at",
            )
        rows = await cursor.fetchall()
        return [
            AuthorizedIdentity(
                identity_key=r["identity_key"],
                channel=r["channel"],
                user_id=r["user_id"],
                user_name=r["user_name"],
                authorized_at=r["authorized_at"],
                authorized_via=r["authorized_via"],
            )
            for r in rows
        ]

    # -- Challenge management --

    async def create_challenge(
        self,
        channel: str,
        user_id: str,
        user_name: str = "",
    ) -> AuthChallenge:
        """Create a new auth challenge code."""
        # Check for existing active challenge
        existing = await self._get_active_challenge(channel, user_id)
        if existing:
            return existing

        code = self._generate_code()
        now = datetime.now(timezone.utc)
        expires = now + timedelta(minutes=_CHALLENGE_TTL_MINUTES)

        await self._db.conn.execute(
            "INSERT INTO auth_challenges (code, channel, user_id, user_name, expires_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (code, channel, user_id, user_name, expires.isoformat()),
        )
        await self._db.conn.commit()

        return AuthChallenge(
            code=code,
            channel=channel,
            user_id=user_id,
            user_name=user_name,
            created_at=now,
            expires_at=expires,
        )

    async def verify_challenge(self, code: str) -> AuthChallenge | None:
        """Verify a challenge code. Returns the challenge if valid, None otherwise."""
        cursor = await self._db.conn.execute(
            "SELECT * FROM auth_challenges WHERE code = ? AND resolved = 0",
            (code.upper(),),
        )
        row = await cursor.fetchone()
        if not row:
            return None

        # Check expiry
        expires_at = datetime.fromisoformat(row["expires_at"])
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) > expires_at:
            return None

        # Mark as resolved
        await self._db.conn.execute(
            "UPDATE auth_challenges SET resolved = 1 WHERE code = ?",
            (code.upper(),),
        )
        await self._db.conn.commit()

        return AuthChallenge(
            code=row["code"],
            channel=row["channel"],
            user_id=row["user_id"],
            user_name=row["user_name"],
            expires_at=expires_at,
            resolved=True,
        )

    async def _get_active_challenge(
        self, channel: str, user_id: str,
    ) -> AuthChallenge | None:
        """Get an existing non-expired, non-resolved challenge."""
        cursor = await self._db.conn.execute(
            "SELECT * FROM auth_challenges "
            "WHERE channel = ? AND user_id = ? AND resolved = 0 "
            "ORDER BY created_at DESC LIMIT 1",
            (channel, user_id),
        )
        row = await cursor.fetchone()
        if not row:
            return None

        expires_at = datetime.fromisoformat(row["expires_at"])
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) > expires_at:
            return None

        return AuthChallenge(
            code=row["code"],
            channel=row["channel"],
            user_id=row["user_id"],
            user_name=row["user_name"],
            expires_at=expires_at,
        )

    def _generate_code(self) -> str:
        """Generate a 6-character auth code."""
        return "".join(random.choices(_CODE_CHARS, k=_CODE_LENGTH))
