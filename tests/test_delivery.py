"""Tests for DeliveryService — queue, active hours, batching, timezone."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openhydra.agenda.delivery import DeliveryService


@pytest.fixture
def mock_db():
    db = MagicMock()
    conn = AsyncMock()
    db.conn = conn
    conn.execute = AsyncMock()
    conn.commit = AsyncMock()
    return db


@pytest.fixture
def mock_channels():
    slack = MagicMock()
    slack.send_message = AsyncMock()
    email = MagicMock()
    email.send_message = AsyncMock()
    return {"slack": slack, "email": email}


class TestQueueResult:
    @pytest.mark.asyncio
    async def test_inserts_into_queue(self, mock_db, mock_channels):
        svc = DeliveryService(mock_db, mock_channels)
        delivery_id = await svc.queue_result(
            workflow_id="wf-123",
            body="Research findings here",
            channel="slack",
            recipient_id="U12345",
            subject="AI Safety Update",
        )
        assert delivery_id  # non-empty UUID
        mock_db.conn.execute.assert_called_once()
        args = mock_db.conn.execute.call_args[0]
        assert "INSERT INTO delivery_queue" in args[0]
        assert mock_db.conn.commit.called

    @pytest.mark.asyncio
    async def test_queue_with_default_subject(self, mock_db, mock_channels):
        svc = DeliveryService(mock_db, mock_channels)
        await svc.queue_result(
            workflow_id="wf-456",
            body="Content",
            channel="email",
            recipient_id="user@example.com",
        )
        args = mock_db.conn.execute.call_args[0][1]
        assert args[4] == ""  # subject defaults to empty


class TestDeliverPending:
    @pytest.mark.asyncio
    async def test_no_pending_is_noop(self, mock_db, mock_channels):
        cursor = AsyncMock()
        cursor.fetchall = AsyncMock(return_value=[])
        mock_db.conn.execute = AsyncMock(return_value=cursor)

        svc = DeliveryService(mock_db, mock_channels, active_start=0, active_end=24)
        count = await svc.deliver_pending()
        assert count == 0

    @pytest.mark.asyncio
    async def test_delivers_single_message(self, mock_db, mock_channels):
        rows = [
            {
                "id": "d-1",
                "workflow_id": "wf-1",
                "recipient_channel": "slack",
                "recipient_id": "U12345",
                "subject": "Update",
                "body": "Research results",
            },
        ]
        cursor = AsyncMock()
        cursor.fetchall = AsyncMock(return_value=rows)
        mock_db.conn.execute = AsyncMock(return_value=cursor)

        svc = DeliveryService(mock_db, mock_channels, active_start=0, active_end=24)
        count = await svc.deliver_pending()

        assert count == 1
        mock_channels["slack"].send_message.assert_called_once_with(
            "U12345", "Research results"
        )

    @pytest.mark.asyncio
    async def test_batches_multiple_messages(self, mock_db, mock_channels):
        rows = [
            {
                "id": "d-1",
                "workflow_id": "wf-1",
                "recipient_channel": "slack",
                "recipient_id": "U12345",
                "subject": "AI Safety",
                "body": "Safety findings",
            },
            {
                "id": "d-2",
                "workflow_id": "wf-2",
                "recipient_channel": "slack",
                "recipient_id": "U12345",
                "subject": "Rust Updates",
                "body": "Rust news",
            },
        ]
        cursor = AsyncMock()
        cursor.fetchall = AsyncMock(return_value=rows)
        mock_db.conn.execute = AsyncMock(return_value=cursor)

        svc = DeliveryService(mock_db, mock_channels, active_start=0, active_end=24)
        count = await svc.deliver_pending()

        assert count == 2
        call_args = mock_channels["slack"].send_message.call_args[0]
        assert "Here are your updates:" in call_args[1]
        assert "AI Safety" in call_args[1]
        assert "Rust Updates" in call_args[1]

    @pytest.mark.asyncio
    async def test_skips_when_outside_active_hours(self, mock_db, mock_channels):
        # Set active hours to an impossible range
        svc = DeliveryService(
            mock_db, mock_channels, active_start=25, active_end=25
        )
        with patch.object(svc, "is_active_hours", return_value=False):
            count = await svc.deliver_pending()
        assert count == 0

    @pytest.mark.asyncio
    async def test_skips_missing_channel(self, mock_db, mock_channels):
        rows = [
            {
                "id": "d-1",
                "workflow_id": "wf-1",
                "recipient_channel": "telegram",  # Not in mock_channels
                "recipient_id": "12345",
                "subject": "",
                "body": "Content",
            },
        ]
        cursor = AsyncMock()
        cursor.fetchall = AsyncMock(return_value=rows)
        mock_db.conn.execute = AsyncMock(return_value=cursor)

        svc = DeliveryService(mock_db, mock_channels, active_start=0, active_end=24)
        count = await svc.deliver_pending()
        assert count == 0


class TestActiveHours:
    def test_utc_within_range(self):
        svc = DeliveryService(MagicMock(), {}, active_start=0, active_end=24)
        assert svc.is_active_hours() is True

    def test_utc_outside_range(self):
        svc = DeliveryService(MagicMock(), {}, active_start=25, active_end=25)
        assert svc.is_active_hours() is False

    def test_timezone_aware(self):
        svc = DeliveryService(
            MagicMock(), {},
            tz_name="America/New_York",
            active_start=0,
            active_end=24,
        )
        # 0-24 covers all hours, so always active
        assert svc.is_active_hours() is True

    def test_invalid_timezone_falls_back_to_utc(self):
        svc = DeliveryService(
            MagicMock(), {},
            tz_name="Invalid/Timezone",
            active_start=0,
            active_end=24,
        )
        assert svc.is_active_hours() is True

    def test_midnight_wrap(self):
        svc = DeliveryService(MagicMock(), {}, active_start=22, active_end=6)
        result = svc.is_active_hours()
        # Just verify it returns a bool without error
        assert isinstance(result, bool)
