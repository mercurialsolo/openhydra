"""BaileysBridge — subprocess bridge to Baileys Node.js library.

JSON-L over stdin/stdout, matching the ClaudeSdkProvider subprocess pattern.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
from pathlib import Path
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
        env = os.environ.copy()
        if self._auth_dir:
            auth_dir = os.path.expanduser(self._auth_dir)
            Path(auth_dir).mkdir(parents=True, exist_ok=True)
            env["BAILEYS_AUTH_DIR"] = auth_dir

        # In tests we pass a fake script path; skip runtime bootstrap in that case.
        if Path(self._bridge_script).exists():
            await self._ensure_baileys_dependency(env)

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

    def _node_modules_dir(self) -> Path:
        """Resolve where OpenHydra stores Node dependencies for the bridge."""
        if self._auth_dir:
            state_dir = Path(os.path.expanduser(self._auth_dir)).parent
        else:
            state_dir = Path.home() / ".openhydra"
        return state_dir / "node_deps" / "whatsapp" / "node_modules"

    @staticmethod
    def _with_node_path(env: dict[str, str], node_modules: Path) -> dict[str, str]:
        """Return a copy of env that prepends a Node module path."""
        merged = dict(env)
        existing = merged.get("NODE_PATH", "").strip()
        merged["NODE_PATH"] = (
            f"{node_modules}{os.pathsep}{existing}" if existing else str(node_modules)
        )
        return merged

    async def _node_can_resolve_baileys(self, env: dict[str, str]) -> bool:
        """Check whether Node can resolve @whiskeysockets/baileys with this env."""
        try:
            proc = await asyncio.create_subprocess_exec(
                self._node_path,
                "-e",
                "require.resolve('@whiskeysockets/baileys')",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
                env=env,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(
                f"Node runtime not found: `{self._node_path}`. Install Node.js first."
            ) from exc
        return (await proc.wait()) == 0

    async def _ensure_baileys_dependency(self, env: dict[str, str]) -> None:
        """Ensure @whiskeysockets/baileys is available for the bridge process."""
        node_modules = self._node_modules_dir()
        node_env = self._with_node_path(env, node_modules)

        if await self._node_can_resolve_baileys(node_env):
            env.update(node_env)
            return

        npm_path = shutil.which("npm")
        if not npm_path:
            raise RuntimeError(
                "Missing @whiskeysockets/baileys and `npm` is unavailable for auto-install. "
                "Install npm or preinstall @whiskeysockets/baileys."
            )

        install_root = node_modules.parent
        install_root.mkdir(parents=True, exist_ok=True)
        logger.info(
            "Installing @whiskeysockets/baileys to %s for WhatsApp bridge.",
            install_root,
        )
        proc = await asyncio.create_subprocess_exec(
            npm_path,
            "install",
            "--no-audit",
            "--no-fund",
            "--silent",
            "--prefix",
            str(install_root),
            "@whiskeysockets/baileys",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            err = stderr.decode(errors="ignore").strip()
            out = stdout.decode(errors="ignore").strip()
            detail = err or out or "Unknown npm error."
            raise RuntimeError(
                "Failed to auto-install @whiskeysockets/baileys "
                f"(exit code {proc.returncode}): {detail}"
            )

        if not await self._node_can_resolve_baileys(node_env):
            raise RuntimeError(
                "Installed @whiskeysockets/baileys but Node cannot resolve it."
            )
        env.update(node_env)
