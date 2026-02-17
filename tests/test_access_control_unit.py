"""Unit tests for the shared AccessControl class."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from openhydra.channels.access import AccessControl
from openhydra.channels.auth.manager import AuthManager
from openhydra.channels.auth.store import AuthStore
from openhydra.db import Database
from openhydra.events import EventBus


@pytest.fixture()
async def auth_db(tmp_path: Path):
    database = Database(tmp_path / "test.db")
    await database.connect()
    yield database
    await database.close()


# --- Allowlist priority ---


@pytest.mark.asyncio
async def test_allowlist_allows_listed_user():
    ac = AccessControl(allowed_ids=["alice"])
    assert await ac.check("slack", "alice") is True


@pytest.mark.asyncio
async def test_allowlist_blocks_unlisted_user():
    ac = AccessControl(allowed_ids=["alice"])
    assert await ac.check("slack", "bob") is False


@pytest.mark.asyncio
async def test_empty_allowlist_no_store_allows_all():
    """Backward compat: no allowlist + no auth store → allow everyone."""
    ac = AccessControl()
    assert await ac.check("slack", "anyone") is True


# --- Auth store integration ---


@pytest.mark.asyncio
async def test_auth_store_authorized(auth_db):
    store = AuthStore(auth_db)
    await store.authorize("slack", "U-auth")
    ac = AccessControl(auth_store=store)
    assert await ac.check("slack", "U-auth") is True


@pytest.mark.asyncio
async def test_auth_store_unknown_returns_false(auth_db):
    store = AuthStore(auth_db)
    ac = AccessControl(auth_store=store)
    assert await ac.check("slack", "U-unknown") is False


@pytest.mark.asyncio
async def test_auth_store_unknown_triggers_challenge(auth_db):
    store = AuthStore(auth_db)
    events = EventBus()
    manager = AuthManager(store, events)
    ac = AccessControl(auth_store=store, auth_manager=manager)

    # Should trigger a challenge but return False
    result = await ac.check("slack", "U-new")
    assert result is False


# --- check_and_notify ---


@pytest.mark.asyncio
async def test_check_and_notify_calls_fn_on_challenge(auth_db):
    store = AuthStore(auth_db)
    events = EventBus()
    manager = AuthManager(store, events)
    ac = AccessControl(auth_store=store, auth_manager=manager)

    notify = AsyncMock()
    result = await ac.check_and_notify("slack", "U-new", notify_fn=notify)
    assert result is False
    notify.assert_called_once()


@pytest.mark.asyncio
async def test_check_and_notify_no_fn_still_works(auth_db):
    store = AuthStore(auth_db)
    events = EventBus()
    manager = AuthManager(store, events)
    ac = AccessControl(auth_store=store, auth_manager=manager)

    result = await ac.check_and_notify("slack", "U-new")
    assert result is False


@pytest.mark.asyncio
async def test_check_and_notify_skips_fn_when_allowed():
    ac = AccessControl(allowed_ids=["alice"])
    notify = AsyncMock()
    result = await ac.check_and_notify("slack", "alice", notify_fn=notify)
    assert result is True
    notify.assert_not_called()


# --- Allowlist overrides auth store ---


@pytest.mark.asyncio
async def test_allowlist_takes_priority_over_auth_store(auth_db):
    """Even if auth store has the user, allowlist is definitive."""
    store = AuthStore(auth_db)
    await store.authorize("slack", "U-store-only")

    ac = AccessControl(allowed_ids=["U-config-only"], auth_store=store)
    assert await ac.check("slack", "U-config-only") is True
    assert await ac.check("slack", "U-store-only") is False
