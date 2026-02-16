"""Tests for the approval manager."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from openhydra.channels.approval import ApprovalManager
from openhydra.channels.session import ChannelSession
from openhydra.events import Event, EventBus


class FakeEngine:
    def __init__(self):
        self.events = EventBus()
        self.approve = AsyncMock()
        self.reject = AsyncMock()


class FakeSessionStore:
    def __init__(self, sessions=None):
        self._sessions = sessions or {}

    async def get(self, key):
        return self._sessions.get(key)

    async def upsert(self, session):
        self._sessions[session.session_key] = session

    async def find_by_workflow(self, workflow_id):
        for s in self._sessions.values():
            if s.active_workflow_id == workflow_id:
                return s
        return None

    async def clear_workflow(self, workflow_id):
        for s in self._sessions.values():
            if s.active_workflow_id == workflow_id:
                s.active_workflow_id = None


class FakeChannel:
    def __init__(self, name):
        self._name = name
        self.send_message = AsyncMock()

    @property
    def name(self):
        return self._name

    async def start(self):
        pass

    async def stop(self):
        pass


@pytest.mark.asyncio
async def test_sends_to_active_channel():
    engine = FakeEngine()
    session = ChannelSession(
        session_key="slack:U1",
        active_workflow_id="wf-1",
        last_channel="slack",
    )
    sessions = FakeSessionStore({"slack:U1": session})
    slack_ch = FakeChannel("slack")
    channels = {"slack": slack_ch}

    mgr = ApprovalManager(engine, sessions, channels, default_timeout=10.0)
    mgr.start()

    event = Event(
        type="approval.requested",
        data={"workflow_id": "wf-1", "approval_id": "ap-1", "prompt": "Approve this?"},
    )
    await mgr._on_approval_requested(event)

    slack_ch.send_message.assert_called_once()
    args = slack_ch.send_message.call_args
    assert args[0][0] == "U1"  # user_id
    assert "Approve this?" in args[0][1]  # text contains prompt

    mgr.stop()


@pytest.mark.asyncio
async def test_no_session_silent():
    engine = FakeEngine()
    sessions = FakeSessionStore()
    channels = {"slack": FakeChannel("slack")}

    mgr = ApprovalManager(engine, sessions, channels)
    mgr.start()

    event = Event(
        type="approval.requested",
        data={"workflow_id": "wf-unknown", "approval_id": "ap-1"},
    )
    await mgr._on_approval_requested(event)

    channels["slack"].send_message.assert_not_called()
    mgr.stop()


@pytest.mark.asyncio
async def test_timeout_auto_rejects():
    engine = FakeEngine()
    session = ChannelSession(
        session_key="slack:U1",
        active_workflow_id="wf-1",
        last_channel="slack",
    )
    sessions = FakeSessionStore({"slack:U1": session})
    channels = {"slack": FakeChannel("slack")}

    mgr = ApprovalManager(
        engine, sessions, channels,
        default_timeout=0.05,  # 50ms
        timeout_action="reject",
    )
    mgr.start()

    event = Event(
        type="approval.requested",
        data={"workflow_id": "wf-1", "approval_id": "ap-1", "prompt": "Approve?"},
    )
    await mgr._on_approval_requested(event)
    await asyncio.sleep(0.15)

    engine.reject.assert_called_once()
    assert "ap-1" in str(engine.reject.call_args)
    mgr.stop()


@pytest.mark.asyncio
async def test_timeout_auto_approves():
    engine = FakeEngine()
    session = ChannelSession(
        session_key="slack:U1",
        active_workflow_id="wf-1",
        last_channel="slack",
    )
    sessions = FakeSessionStore({"slack:U1": session})
    channels = {"slack": FakeChannel("slack")}

    mgr = ApprovalManager(
        engine, sessions, channels,
        default_timeout=0.05,
        timeout_action="approve",
    )
    mgr.start()

    event = Event(
        type="approval.requested",
        data={"workflow_id": "wf-1", "approval_id": "ap-1", "prompt": "Approve?"},
    )
    await mgr._on_approval_requested(event)
    await asyncio.sleep(0.15)

    engine.approve.assert_called_once_with("ap-1")
    mgr.stop()


@pytest.mark.asyncio
async def test_subscribe_unsubscribe():
    engine = FakeEngine()
    sessions = FakeSessionStore()
    channels = {}

    mgr = ApprovalManager(engine, sessions, channels)
    mgr.start()
    assert len(engine.events._handlers.get("approval.requested", [])) == 1

    mgr.stop()
    assert len(engine.events._handlers.get("approval.requested", [])) == 0


@pytest.mark.asyncio
async def test_missing_channel_does_not_crash():
    engine = FakeEngine()
    session = ChannelSession(
        session_key="telegram:U1",
        active_workflow_id="wf-1",
        last_channel="telegram",  # Not in channels dict
    )
    sessions = FakeSessionStore({"telegram:U1": session})
    channels = {"slack": FakeChannel("slack")}

    mgr = ApprovalManager(engine, sessions, channels)
    mgr.start()

    event = Event(
        type="approval.requested",
        data={"workflow_id": "wf-1", "approval_id": "ap-1", "prompt": "Approve?"},
    )
    # Should not raise
    await mgr._on_approval_requested(event)
    channels["slack"].send_message.assert_not_called()
    mgr.stop()
