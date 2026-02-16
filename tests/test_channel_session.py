"""Tests for session persistence (SQLite-backed)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from openhydra.channels.session import (
    ChannelSession,
    SessionStore,
    SqliteSessionStore,
)
from openhydra.db import Database


@pytest.fixture
async def db(tmp_path):
    database = Database(tmp_path / "test.db")
    await database.connect()
    yield database
    await database.close()


@pytest.fixture
async def store(db):
    return SqliteSessionStore(db)


@pytest.mark.asyncio
async def test_protocol_conformance(store):
    assert isinstance(store, SessionStore)


@pytest.mark.asyncio
async def test_get_nonexistent(store):
    result = await store.get("nonexistent")
    assert result is None


@pytest.mark.asyncio
async def test_upsert_and_get(store):
    session = ChannelSession(
        session_key="slack:U123",
        active_workflow_id="wf-abc",
        last_channel="slack",
        last_message_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        metadata={"thread_ts": "1234.5"},
    )
    await store.upsert(session)

    result = await store.get("slack:U123")
    assert result is not None
    assert result.session_key == "slack:U123"
    assert result.active_workflow_id == "wf-abc"
    assert result.last_channel == "slack"
    assert result.metadata == {"thread_ts": "1234.5"}


@pytest.mark.asyncio
async def test_upsert_overwrites(store):
    session = ChannelSession(
        session_key="slack:U1", active_workflow_id="wf-1", last_channel="slack",
    )
    await store.upsert(session)

    session.active_workflow_id = "wf-2"
    await store.upsert(session)

    result = await store.get("slack:U1")
    assert result.active_workflow_id == "wf-2"


@pytest.mark.asyncio
async def test_find_by_workflow(store):
    session = ChannelSession(
        session_key="discord:D1",
        active_workflow_id="wf-xyz",
        last_channel="discord",
    )
    await store.upsert(session)

    result = await store.find_by_workflow("wf-xyz")
    assert result is not None
    assert result.session_key == "discord:D1"


@pytest.mark.asyncio
async def test_find_by_workflow_no_match(store):
    result = await store.find_by_workflow("nonexistent")
    assert result is None


@pytest.mark.asyncio
async def test_clear_workflow(store):
    session = ChannelSession(
        session_key="slack:U1",
        active_workflow_id="wf-clear",
        last_channel="slack",
    )
    await store.upsert(session)

    await store.clear_workflow("wf-clear")

    result = await store.get("slack:U1")
    assert result is not None
    assert result.active_workflow_id is None


@pytest.mark.asyncio
async def test_clear_workflow_no_match(store):
    # Should not raise
    await store.clear_workflow("nonexistent")


@pytest.mark.asyncio
async def test_metadata_json_roundtrip(store):
    session = ChannelSession(
        session_key="wa:+1234",
        last_channel="whatsapp",
        metadata={"phone": "+1234", "nested": {"key": "val"}},
    )
    await store.upsert(session)

    result = await store.get("wa:+1234")
    assert result.metadata == {"phone": "+1234", "nested": {"key": "val"}}


@pytest.mark.asyncio
async def test_session_without_workflow(store):
    session = ChannelSession(
        session_key="slack:U2",
        last_channel="slack",
    )
    await store.upsert(session)

    result = await store.get("slack:U2")
    assert result is not None
    assert result.active_workflow_id is None


@pytest.mark.asyncio
async def test_multiple_sessions(store):
    for i in range(3):
        session = ChannelSession(
            session_key=f"slack:U{i}",
            active_workflow_id=f"wf-{i}",
            last_channel="slack",
        )
        await store.upsert(session)

    for i in range(3):
        result = await store.get(f"slack:U{i}")
        assert result is not None
        assert result.active_workflow_id == f"wf-{i}"
