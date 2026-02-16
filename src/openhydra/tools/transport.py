"""MCP transport implementations — stdio and SSE."""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any, Protocol


class Transport(Protocol):
    """Protocol for MCP JSON-RPC transport."""

    async def start(self) -> None: ...
    async def send(self, message: dict[str, Any]) -> dict[str, Any]: ...
    async def close(self) -> None: ...


class StdioTransport:
    """Spawn a subprocess and communicate via stdin/stdout JSON-RPC.

    Inherits the user's environment so child processes get API keys,
    SSH_AUTH_SOCK, browser session cookies, etc.
    """

    def __init__(
        self,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        self._command = command
        self._args = args or []
        self._env = {**os.environ, **(env or {})}
        self._process: asyncio.subprocess.Process | None = None
        self._request_id = 0

    async def start(self) -> None:
        self._process = await asyncio.create_subprocess_exec(
            self._command,
            *self._args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=self._env,
        )

    async def send(self, message: dict[str, Any]) -> dict[str, Any]:
        if not self._process or not self._process.stdin or not self._process.stdout:
            raise RuntimeError("Transport not started")

        self._request_id += 1
        request = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            **message,
        }
        payload = json.dumps(request) + "\n"
        self._process.stdin.write(payload.encode())
        await self._process.stdin.drain()

        line = await self._process.stdout.readline()
        if not line:
            raise RuntimeError("MCP server closed connection")
        return json.loads(line)

    async def close(self) -> None:
        if self._process:
            if self._process.stdin:
                self._process.stdin.close()
            self._process.terminate()
            await self._process.wait()
            self._process = None


class SseTransport:
    """HTTP SSE transport for remote MCP servers."""

    def __init__(self, url: str) -> None:
        self._url = url
        self._client: Any = None
        self._request_id = 0

    async def start(self) -> None:
        try:
            import httpx
            self._client = httpx.AsyncClient(base_url=self._url, timeout=30.0)
        except ImportError:
            raise RuntimeError("httpx is required for SSE transport: pip install httpx")

    async def send(self, message: dict[str, Any]) -> dict[str, Any]:
        if not self._client:
            raise RuntimeError("Transport not started")

        self._request_id += 1
        request = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            **message,
        }
        response = await self._client.post("/jsonrpc", json=request)
        response.raise_for_status()
        return response.json()

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None
