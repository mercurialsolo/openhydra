"""Tests for the channel auth manager."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from openhydra.channels.auth.manager import AuthManager
from openhydra.channels.auth.store import AuthStore
from openhydra.db import Database
from openhydra.events import EventBus


@pytest.fixture()
async def db(tmp_path: Path):
    database = Database(tmp_path / "test.db")
    await database.connect()
    yield database
    await database.close()


@pytest.fixture()
def events() -> EventBus:
    return EventBus()


@pytest.fixture()
def store(db) -> AuthStore:
    return AuthStore(db)


@pytest.fixture()
def manager(store, events) -> AuthManager:
    return AuthManager(store, events)


class TestChallengeFlow:
    @pytest.mark.asyncio()
    async def test_challenge_emits_event(
        self, manager: AuthManager, events: EventBus,
    ) -> None:
        emitted = []
        events.on_all(AsyncMock(side_effect=lambda e: emitted.append(e)))

        code = await manager.challenge_unknown_user("slack", "U123", "alice")

        assert len(code) == 6
        assert any(e.type == "auth.challenge_created" for e in emitted)
        challenge_event = next(e for e in emitted if e.type == "auth.challenge_created")
        assert challenge_event.data["user_id"] == "U123"

    @pytest.mark.asyncio()
    async def test_confirm_authorizes_user(
        self, manager: AuthManager, store: AuthStore,
    ) -> None:
        code = await manager.challenge_unknown_user("slack", "U123", "alice")

        ok = await manager.confirm_challenge(code)
        assert ok
        assert await store.is_authorized("slack", "U123")

    @pytest.mark.asyncio()
    async def test_confirm_emits_authorized_event(
        self, manager: AuthManager, events: EventBus,
    ) -> None:
        emitted = []
        events.on_all(AsyncMock(side_effect=lambda e: emitted.append(e)))

        code = await manager.challenge_unknown_user("slack", "U123")
        await manager.confirm_challenge(code)

        assert any(e.type == "auth.identity_authorized" for e in emitted)

    @pytest.mark.asyncio()
    async def test_invalid_code_returns_false(self, manager: AuthManager) -> None:
        ok = await manager.confirm_challenge("XXXXXX")
        assert not ok

    @pytest.mark.asyncio()
    async def test_manual_authorize(
        self, manager: AuthManager, store: AuthStore, events: EventBus,
    ) -> None:
        emitted = []
        events.on_all(AsyncMock(side_effect=lambda e: emitted.append(e)))

        await manager.manual_authorize("discord", "D456", "bob")

        assert await store.is_authorized("discord", "D456")
        assert any(e.type == "auth.identity_authorized" for e in emitted)

    @pytest.mark.asyncio()
    async def test_revoke_identity(
        self, manager: AuthManager, store: AuthStore, events: EventBus,
    ) -> None:
        emitted = []
        events.on_all(AsyncMock(side_effect=lambda e: emitted.append(e)))

        await store.authorize("slack", "U123")
        revoked = await manager.revoke_identity("slack", "U123")

        assert revoked
        assert not await store.is_authorized("slack", "U123")
        assert any(e.type == "auth.identity_revoked" for e in emitted)

    @pytest.mark.asyncio()
    async def test_revoke_nonexistent_returns_false(self, manager: AuthManager) -> None:
        revoked = await manager.revoke_identity("slack", "U999")
        assert not revoked

    @pytest.mark.asyncio()
    async def test_duplicate_challenge_returns_same_code(
        self, manager: AuthManager,
    ) -> None:
        code1 = await manager.challenge_unknown_user("slack", "U123")
        code2 = await manager.challenge_unknown_user("slack", "U123")
        assert code1 == code2
