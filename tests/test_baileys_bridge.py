"""Tests for Baileys WhatsApp bridge (mocked subprocess)."""

from __future__ import annotations

import asyncio
import json
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openhydra.channels.whatsapp.baileys import BaileysBridge


class FakeProcess:
    """Mock asyncio subprocess."""

    def __init__(self):
        self.stdin = MagicMock()
        self.stdin.write = MagicMock()
        self.stdin.drain = AsyncMock()
        self.stdout = None  # Set per-test
        self.stderr = MagicMock()
        self._returncode = None

    def terminate(self):
        pass

    def kill(self):
        pass

    async def wait(self):
        return 0


def make_stdout_reader(lines: list[str]):
    """Create a mock stdout that yields lines."""
    payload = "".join(f"{line}\n" for line in lines).encode()
    chunk_size = 4096

    class FakeStdout:
        def __init__(self) -> None:
            self._offset = 0

        async def read(self, n: int = -1):
            if self._offset >= len(payload):
                return b""
            if n < 0:
                n = len(payload) - self._offset
            end = min(self._offset + min(n, chunk_size), len(payload))
            chunk = payload[self._offset:end]
            self._offset = end
            return chunk

    return FakeStdout()


@pytest.mark.asyncio
async def test_bridge_start_spawns_process():
    on_message = AsyncMock()
    bridge = BaileysBridge("/path/to/bridge.js")

    with patch("asyncio.create_subprocess_exec") as mock_exec:
        proc = FakeProcess()
        proc.stdout = make_stdout_reader([])
        mock_exec.return_value = proc

        await bridge.start(on_message)

        mock_exec.assert_called_once()
        args = mock_exec.call_args[0]
        assert "node" in args[0]
        assert "/path/to/bridge.js" in args[1]

    await bridge.stop()


@pytest.mark.asyncio
async def test_send_writes_json_line():
    on_message = AsyncMock()
    bridge = BaileysBridge("/path/to/bridge.js")

    with patch("asyncio.create_subprocess_exec") as mock_exec:
        proc = FakeProcess()
        proc.stdout = make_stdout_reader([])
        mock_exec.return_value = proc

        await bridge.start(on_message)
        await bridge.send("+1234", "hello")

        written = proc.stdin.write.call_args[0][0].decode()
        msg = json.loads(written.strip())
        assert msg["type"] == "send"
        assert msg["to"] == "+1234"
        assert msg["text"] == "hello"

    await bridge.stop()


@pytest.mark.asyncio
async def test_dispatches_inbound_message():
    on_message = AsyncMock()
    bridge = BaileysBridge("/path/to/bridge.js")

    inbound = json.dumps({"type": "message", "from": "+5555", "text": "hi there"})

    with patch("asyncio.create_subprocess_exec") as mock_exec:
        proc = FakeProcess()
        proc.stdout = make_stdout_reader([inbound])
        mock_exec.return_value = proc

        await bridge.start(on_message)
        await asyncio.sleep(0.05)

    on_message.assert_called_once_with("+5555", "hi there")
    await bridge.stop()


@pytest.mark.asyncio
async def test_dispatches_qr():
    on_message = AsyncMock()
    on_qr = AsyncMock()
    bridge = BaileysBridge("/path/to/bridge.js")

    qr_msg = json.dumps({"type": "qr", "data": "QR-DATA-123"})

    with patch("asyncio.create_subprocess_exec") as mock_exec:
        proc = FakeProcess()
        proc.stdout = make_stdout_reader([qr_msg])
        mock_exec.return_value = proc

        await bridge.start(on_message, on_qr=on_qr)
        await asyncio.sleep(0.05)

    on_qr.assert_called_once_with("QR-DATA-123")
    await bridge.stop()


@pytest.mark.asyncio
async def test_dispatches_connected():
    on_message = AsyncMock()
    bridge = BaileysBridge("/path/to/bridge.js")

    connected_msg = json.dumps({"type": "connected"})

    with patch("asyncio.create_subprocess_exec") as mock_exec:
        proc = FakeProcess()
        proc.stdout = make_stdout_reader([connected_msg])
        mock_exec.return_value = proc

        await bridge.start(on_message)
        await asyncio.sleep(0.05)

    assert bridge.is_connected
    await bridge.stop()


@pytest.mark.asyncio
async def test_stop_terminates_process():
    on_message = AsyncMock()
    bridge = BaileysBridge("/path/to/bridge.js")

    with patch("asyncio.create_subprocess_exec") as mock_exec:
        proc = FakeProcess()
        proc.stdout = make_stdout_reader([])
        proc.terminate = MagicMock()
        mock_exec.return_value = proc

        await bridge.start(on_message)
        await bridge.stop()

    proc.terminate.assert_called_once()


@pytest.mark.asyncio
async def test_handles_invalid_json():
    on_message = AsyncMock()
    bridge = BaileysBridge("/path/to/bridge.js")

    with patch("asyncio.create_subprocess_exec") as mock_exec:
        proc = FakeProcess()
        proc.stdout = make_stdout_reader(["not valid json", "also broken {"])
        mock_exec.return_value = proc

        await bridge.start(on_message)
        await asyncio.sleep(0.05)

    # Should not crash, just log warnings
    on_message.assert_not_called()
    await bridge.stop()


@pytest.mark.asyncio
async def test_handles_oversized_stdout_line_without_crash():
    on_message = AsyncMock()
    bridge = BaileysBridge("/path/to/bridge.js")
    huge_line = "x" * 100_000

    with patch("asyncio.create_subprocess_exec") as mock_exec:
        proc = FakeProcess()
        proc.stdout = make_stdout_reader([huge_line])
        mock_exec.return_value = proc

        await bridge.start(on_message)
        await asyncio.sleep(0.05)

    # Oversized non-JSON output should be ignored safely.
    on_message.assert_not_called()
    await bridge.stop()


@pytest.mark.asyncio
async def test_recoverable_disconnect_logs_info(caplog):
    on_message = AsyncMock()
    bridge = BaileysBridge("/path/to/bridge.js")
    disconnect_msg = json.dumps(
        {
            "type": "disconnected",
            "reason": "Stream Errored (restart required)",
            "statusCode": 515,
            "disconnectReason": "restartRequired",
            "shouldReconnect": True,
        }
    )

    with patch("asyncio.create_subprocess_exec") as mock_exec:
        proc = FakeProcess()
        proc.stdout = make_stdout_reader([disconnect_msg])
        mock_exec.return_value = proc
        with caplog.at_level(logging.INFO):
            await bridge.start(on_message)
            await asyncio.sleep(0.05)

    assert any(
        "recoverable" in record.message
        for record in caplog.records
        if record.levelname == "INFO"
    )
    await bridge.stop()


@pytest.mark.asyncio
async def test_non_recoverable_disconnect_logs_warning(caplog):
    on_message = AsyncMock()
    bridge = BaileysBridge("/path/to/bridge.js")
    disconnect_msg = json.dumps(
        {
            "type": "disconnected",
            "reason": "Logged out",
            "statusCode": 401,
            "disconnectReason": "loggedOut",
            "shouldReconnect": False,
        }
    )

    with patch("asyncio.create_subprocess_exec") as mock_exec:
        proc = FakeProcess()
        proc.stdout = make_stdout_reader([disconnect_msg])
        mock_exec.return_value = proc
        with caplog.at_level(logging.WARNING):
            await bridge.start(on_message)
            await asyncio.sleep(0.05)

    assert any(
        "non-recoverable" in record.message
        for record in caplog.records
        if record.levelname == "WARNING"
    )
    await bridge.stop()


@pytest.mark.asyncio
async def test_send_before_start_raises():
    bridge = BaileysBridge("/path/to/bridge.js")
    with pytest.raises(RuntimeError, match="not started"):
        await bridge.send("+1234", "hello")


@pytest.mark.asyncio
async def test_auth_dir_passed_to_subprocess():
    on_message = AsyncMock()
    bridge = BaileysBridge("/path/to/bridge.js", auth_dir="/tmp/wa_auth")

    with patch("asyncio.create_subprocess_exec") as mock_exec:
        proc = FakeProcess()
        proc.stdout = make_stdout_reader([])
        mock_exec.return_value = proc

        await bridge.start(on_message)

        call_kwargs = mock_exec.call_args[1]
        assert call_kwargs.get("env", {}).get("BAILEYS_AUTH_DIR") == "/tmp/wa_auth"

    await bridge.stop()
