"""Tests for the channel authorization store."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from openhydra.channels.auth.store import _CODE_CHARS, _CODE_LENGTH, AuthStore
from openhydra.db import Database


@pytest.fixture()
async def db(tmp_path: Path):
    database = Database(tmp_path / "test.db")
    await database.connect()
    yield database
    await database.close()


@pytest.fixture()
def store(db) -> AuthStore:
    return AuthStore(db)


class TestAuthorization:
    @pytest.mark.asyncio()
    async def test_authorize_and_check(self, store: AuthStore) -> None:
        await store.authorize("slack", "U123", "alice")
        assert await store.is_authorized("slack", "U123")

    @pytest.mark.asyncio()
    async def test_unauthorized_returns_false(self, store: AuthStore) -> None:
        assert not await store.is_authorized("slack", "U999")

    @pytest.mark.asyncio()
    async def test_revoke(self, store: AuthStore) -> None:
        await store.authorize("slack", "U123")
        assert await store.is_authorized("slack", "U123")

        revoked = await store.revoke("slack", "U123")
        assert revoked
        assert not await store.is_authorized("slack", "U123")

    @pytest.mark.asyncio()
    async def test_revoke_nonexistent_returns_false(self, store: AuthStore) -> None:
        revoked = await store.revoke("slack", "U999")
        assert not revoked

    @pytest.mark.asyncio()
    async def test_list_identities(self, store: AuthStore) -> None:
        await store.authorize("slack", "U1", "alice")
        await store.authorize("slack", "U2", "bob")
        await store.authorize("discord", "D1", "charlie")

        all_ids = await store.list_identities()
        assert len(all_ids) == 3

        slack_ids = await store.list_identities(channel="slack")
        assert len(slack_ids) == 2

    @pytest.mark.asyncio()
    async def test_authorize_updates_existing(self, store: AuthStore) -> None:
        await store.authorize("slack", "U1", "alice", via="auth_code")
        await store.authorize("slack", "U1", "alice_updated", via="manual")

        ids = await store.list_identities()
        assert len(ids) == 1
        assert ids[0].user_name == "alice_updated"
        assert ids[0].authorized_via == "manual"


class TestChallenges:
    @pytest.mark.asyncio()
    async def test_create_and_verify(self, store: AuthStore) -> None:
        challenge = await store.create_challenge("slack", "U123", "alice")
        assert len(challenge.code) == _CODE_LENGTH
        assert challenge.channel == "slack"
        assert challenge.user_id == "U123"

        verified = await store.verify_challenge(challenge.code)
        assert verified is not None
        assert verified.user_id == "U123"
        assert verified.resolved

    @pytest.mark.asyncio()
    async def test_expired_code_rejected(self, store: AuthStore, db: Database) -> None:
        challenge = await store.create_challenge("slack", "U123")

        # Manually expire the challenge
        past = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
        await db.conn.execute(
            "UPDATE auth_challenges SET expires_at = ? WHERE code = ?",
            (past, challenge.code),
        )
        await db.conn.commit()

        verified = await store.verify_challenge(challenge.code)
        assert verified is None

    @pytest.mark.asyncio()
    async def test_already_used_code_rejected(self, store: AuthStore) -> None:
        challenge = await store.create_challenge("slack", "U123")

        # First use — valid
        verified = await store.verify_challenge(challenge.code)
        assert verified is not None

        # Second use — already resolved
        verified2 = await store.verify_challenge(challenge.code)
        assert verified2 is None

    @pytest.mark.asyncio()
    async def test_code_format_valid(self, store: AuthStore) -> None:
        challenge = await store.create_challenge("slack", "U123")
        code = challenge.code
        assert len(code) == _CODE_LENGTH
        assert all(c in _CODE_CHARS for c in code)

    @pytest.mark.asyncio()
    async def test_duplicate_challenge_returns_existing(self, store: AuthStore) -> None:
        c1 = await store.create_challenge("slack", "U123")
        c2 = await store.create_challenge("slack", "U123")
        assert c1.code == c2.code

    @pytest.mark.asyncio()
    async def test_case_insensitive_verify(self, store: AuthStore) -> None:
        challenge = await store.create_challenge("slack", "U123")
        verified = await store.verify_challenge(challenge.code.lower())
        # Code is stored uppercase, verify should handle case
        assert verified is not None
