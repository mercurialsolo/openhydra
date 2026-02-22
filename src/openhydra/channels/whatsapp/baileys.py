"""BaileysBridge — subprocess bridge to Baileys Node.js library.

JSON-L over stdin/stdout, matching the ClaudeSdkProvider subprocess pattern.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)


class BaileysBridge:
    """Subprocess bridge to Baileys Node.js WhatsApp Web library."""

    def __init__(
        self,
        bridge_script: str,
        node_path: str = "node",
        auth_dir: str = "",
    ) -> None:
        self._bridge_script = bridge_script
        self._node_path = node_path
        self._auth_dir = auth_dir
        self._process: asyncio.subprocess.Process | None = None
        self._reader_task: asyncio.Task | None = None
        self._on_message: Callable[[str, str], Coroutine] | None = None
        self._on_qr: Callable[[str], Coroutine] | None = None
        self._connected = asyncio.Event()

    async def start(
        self,
        on_message: Callable[[str, str], Coroutine],
        on_qr: Callable[[str], Coroutine] | None = None,
    ) -> None:
        """Spawn Node.js bridge, begin reading messages."""
        self._on_message = on_message
        self._on_qr = on_qr

        cmd = [self._node_path, self._bridge_script]
        # If we override env at all, we must merge with the parent environment
        # so the subprocess retains PATH, HOME, etc.
        env = None
        if self._auth_dir:
            env = os.environ.copy()
            env["BAILEYS_AUTH_DIR"] = self._auth_dir

        self._process = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        self._reader_task = asyncio.create_task(self._read_loop())

    async def send(self, to: str, text: str) -> None:
        """Send message via Baileys."""
        if not self._process or not self._process.stdin:
            raise RuntimeError("Bridge not started")
        msg = json.dumps({"type": "send", "to": to, "text": text}) + "\n"
        self._process.stdin.write(msg.encode())
        await self._process.stdin.drain()

    async def stop(self) -> None:
        """Terminate bridge subprocess."""
        if self._reader_task:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
            self._reader_task = None

        if self._process:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                self._process.kill()
            self._process = None

    @property
    def is_connected(self) -> bool:
        return self._connected.is_set()

    async def _read_loop(self) -> None:
        """Read JSON-L lines from bridge stdout."""
        if not self._process or not self._process.stdout:
            return
        try:
            while True:
                line = await self._process.stdout.readline()
                if not line:
                    break
                await self._handle_line(line.decode().strip())
        except asyncio.CancelledError:
            return
        except Exception:
            logger.exception("Bridge read loop error")

    async def _handle_line(self, line: str) -> None:
        """Parse and dispatch a JSON-L message from the bridge."""
        if not line:
            return
        try:
            msg: dict[str, Any] = json.loads(line)
        except json.JSONDecodeError:
            logger.warning("Invalid JSON from bridge: %s", line[:100])
            return

        msg_type = msg.get("type", "")

        if msg_type == "message" and self._on_message:
            phone = msg.get("from", "")
            text = msg.get("text", "")
            if phone and text:
                await self._on_message(phone, text)

        elif msg_type == "qr" and self._on_qr:
            await self._on_qr(msg.get("data", ""))

        elif msg_type == "connected":
            self._connected.set()
            logger.info("Baileys bridge connected to WhatsApp")

        elif msg_type == "disconnected":
            self._connected.clear()
            reason = msg.get("reason", "unknown")
            logger.warning("Baileys bridge disconnected: %s", reason)
