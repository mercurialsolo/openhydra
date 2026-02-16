"""Tests for WhatsApp webhook handlers and adapter lifecycle."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from openhydra.channels.base import Channel
from openhydra.channels.whatsapp.adapter import WhatsAppChannel
from openhydra.channels.whatsapp.formatters import event_to_text
from openhydra.channels.whatsapp.handlers import WhatsAppHandlers
from openhydra.config import WhatsAppConfig
from openhydra.events import Event, EventBus


class FakeEngine:
    def __init__(self):
        self.events = EventBus()
        self.submit = AsyncMock(return_value="wf-123")
        self.approve = AsyncMock()
        self.reject = AsyncMock()


@pytest.fixture
def engine():
    return FakeEngine()


@pytest.fixture
def wa_config():
    return WhatsAppConfig(
        enabled=True,
        backend="cloud-api",
        access_token="test-token",
        phone_number_id="12345",
        verify_token="verify-me",
    )


@pytest.fixture
def http_client():
    client = MagicMock()
    client.post = AsyncMock(return_value=MagicMock(status_code=200))
    client.aclose = AsyncMock()
    return client


@pytest.fixture
def handlers(engine, wa_config, http_client):
    return WhatsAppHandlers(engine, wa_config, http_client=http_client)


@pytest.fixture
def app(handlers):
    routes = handlers.build_routes()
    return Starlette(routes=routes)


@pytest.fixture
def client(app):
    return TestClient(app)


# --- Webhook verification ---


def test_verify_success(client):
    resp = client.get(
        "/webhooks/whatsapp",
        params={"hub.mode": "subscribe", "hub.verify_token": "verify-me", "hub.challenge": "abc"},
    )
    assert resp.status_code == 200
    assert resp.text == "abc"


def test_verify_wrong_token(client):
    resp = client.get(
        "/webhooks/whatsapp",
        params={"hub.mode": "subscribe", "hub.verify_token": "wrong", "hub.challenge": "abc"},
    )
    assert resp.status_code == 403


def test_verify_wrong_mode(client):
    resp = client.get(
        "/webhooks/whatsapp",
        params={"hub.mode": "unsubscribe", "hub.verify_token": "verify-me", "hub.challenge": "x"},
    )
    assert resp.status_code == 403


# --- Inbound messages ---


def _make_webhook_payload(phone: str, text: str) -> dict:
    return {
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [{
                        "from": phone,
                        "type": "text",
                        "text": {"body": text},
                    }]
                }
            }]
        }]
    }


def test_inbound_message_submits_task(client, engine, http_client):
    resp = client.post(
        "/webhooks/whatsapp",
        json=_make_webhook_payload("+1234567890", "build a thing"),
    )
    assert resp.status_code == 200
    engine.submit.assert_called_once_with("build a thing")
    # Should send confirmation
    http_client.post.assert_called_once()


def test_approve_command(client, engine, handlers, http_client):
    # Set up a tracked conversation
    handlers._conversations["+1234567890"] = "wf-123"

    resp = client.post(
        "/webhooks/whatsapp",
        json=_make_webhook_payload("+1234567890", "approve"),
    )
    assert resp.status_code == 200
    engine.approve.assert_called_once_with("wf-123")


def test_reject_command(client, engine, handlers, http_client):
    handlers._conversations["+1234567890"] = "wf-123"

    resp = client.post(
        "/webhooks/whatsapp",
        json=_make_webhook_payload("+1234567890", "reject bad output"),
    )
    assert resp.status_code == 200
    engine.reject.assert_called_once_with("wf-123", "bad output")


def test_approve_no_active_workflow(client, engine, http_client):
    resp = client.post(
        "/webhooks/whatsapp",
        json=_make_webhook_payload("+1234567890", "approve"),
    )
    assert resp.status_code == 200
    engine.approve.assert_not_called()


def test_empty_payload_ok(client, engine):
    resp = client.post("/webhooks/whatsapp", json={"entry": []})
    assert resp.status_code == 200
    engine.submit.assert_not_called()


# --- Engine event forwarding ---


@pytest.mark.asyncio
async def test_engine_event_forwarded(handlers, http_client):
    handlers._conversations["+1234567890"] = "wf-123"

    event = Event(type="step.completed", data={"workflow_id": "wf-123", "role_id": "eng"})
    await handlers.on_engine_event(event)

    http_client.post.assert_called_once()
    call_kwargs = http_client.post.call_args
    assert "+1234567890" in str(call_kwargs)


@pytest.mark.asyncio
async def test_engine_event_cleanup_on_completion(handlers, http_client):
    handlers._conversations["+1234567890"] = "wf-123"

    event = Event(type="workflow.completed", data={"workflow_id": "wf-123"})
    await handlers.on_engine_event(event)

    assert "+1234567890" not in handlers._conversations


@pytest.mark.asyncio
async def test_engine_event_ignored_for_unknown_workflow(handlers, http_client):
    event = Event(type="step.completed", data={"workflow_id": "wf-unknown"})
    await handlers.on_engine_event(event)

    http_client.post.assert_not_called()


# --- Formatters ---


def test_event_to_text_workflow_created():
    event = Event(type="workflow.created", data={"workflow_id": "wf-abc", "task": "hello"})
    text = event_to_text(event)
    assert "wf-abc" in text
    assert "hello" in text


def test_event_to_text_approval():
    event = Event(
        type="approval.requested",
        data={"workflow_id": "wf-1", "prompt": "Approve?"},
    )
    text = event_to_text(event)
    assert "approve" in text.lower()


def test_event_to_text_unknown():
    event = Event(type="custom.event", data={})
    text = event_to_text(event)
    assert "custom.event" in text


# --- Adapter protocol conformance ---


def test_whatsapp_channel_satisfies_protocol():
    engine = FakeEngine()
    ch = WhatsAppChannel(engine, WhatsAppConfig())
    assert isinstance(ch, Channel)


def test_whatsapp_channel_name():
    engine = FakeEngine()
    ch = WhatsAppChannel(engine, WhatsAppConfig())
    assert ch.name == "whatsapp"


@pytest.mark.asyncio
async def test_stop_without_start():
    engine = FakeEngine()
    ch = WhatsAppChannel(engine, WhatsAppConfig())
    await ch.stop()  # Should not raise


@pytest.mark.asyncio
async def test_start_cloud_api_mounts_routes():
    engine = FakeEngine()
    web_channel = MagicMock()
    web_app = Starlette(routes=[])
    web_channel.app = web_app
    config = WhatsAppConfig(
        enabled=True,
        backend="cloud-api",
        access_token="tok",
        phone_number_id="123",
        verify_token="v",
    )

    ch = WhatsAppChannel(engine, config, web_channel=web_channel)
    await ch.start()

    # Routes should have been added
    paths = [r.path for r in web_app.routes]
    assert "/webhooks/whatsapp" in paths

    await ch.stop()
