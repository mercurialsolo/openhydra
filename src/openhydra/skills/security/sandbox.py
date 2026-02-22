"""Sandbox executor — runs skill scripts in a restricted subprocess."""

from __future__ import annotations

import asyncio
import inspect
import logging
import platform
import time
from pathlib import Path

from .models import SandboxResult

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 10  # seconds


class SandboxExecutor:
    """Runs scripts in a restricted subprocess with network denied and env stripped."""

    def __init__(self, timeout: int = DEFAULT_TIMEOUT) -> None:
        self.timeout = timeout

    async def execute_script(self, script_path: Path) -> SandboxResult:
        """Execute a single script in a sandboxed subprocess."""
        if not script_path.exists():
            return SandboxResult(
                script_path=str(script_path),
                exit_code=-1,
                stderr=f"Script not found: {script_path}",
            )

        cmd = self._build_command(script_path)
        env = self._build_env()
        start = time.monotonic()

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
                cwd=str(script_path.parent),
            )
            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(), timeout=self.timeout,
                )
                timed_out = False
            except asyncio.TimeoutError:
                kill_result = proc.kill()
                if inspect.isawaitable(kill_result):
                    await kill_result

                wait_result = proc.wait()
                if inspect.isawaitable(wait_result):
                    await wait_result
                stdout_bytes = b""
                stderr_bytes = b"Process killed: timeout exceeded"
                timed_out = True

            duration = time.monotonic() - start
            return SandboxResult(
                script_path=str(script_path),
                exit_code=proc.returncode or 0,
                stdout=stdout_bytes.decode(errors="replace")[:4096],
                stderr=stderr_bytes.decode(errors="replace")[:4096],
                timed_out=timed_out,
                duration_seconds=round(duration, 3),
            )
        except OSError as e:
            duration = time.monotonic() - start
            return SandboxResult(
                script_path=str(script_path),
                exit_code=-1,
                stderr=str(e),
                duration_seconds=round(duration, 3),
            )

    async def execute_all(self, skill_dir: Path) -> list[SandboxResult]:
        """Execute all scripts in a skill's scripts/ subdirectory."""
        scripts_dir = skill_dir / "scripts"
        if not scripts_dir.exists():
            return []

        results: list[SandboxResult] = []
        for script_path in sorted(scripts_dir.iterdir()):
            if not script_path.is_file():
                continue
            if script_path.suffix in {".sh", ".bash", ".py", ".js", ".rb", ".pl"}:
                result = await self.execute_script(script_path)
                results.append(result)
        return results

    def _build_command(self, script_path: Path) -> list[str]:
        """Build the sandboxed command for the current platform."""
        system = platform.system()
        suffix = script_path.suffix

        # Determine the interpreter
        if suffix in {".sh", ".bash"}:
            interpreter = ["bash"]
        elif suffix == ".py":
            interpreter = ["python3"]
        elif suffix == ".js":
            interpreter = ["node"]
        elif suffix == ".rb":
            interpreter = ["ruby"]
        elif suffix == ".pl":
            interpreter = ["perl"]
        else:
            interpreter = ["bash"]

        base_cmd = interpreter + [str(script_path)]

        if system == "Darwin":
            # macOS: use sandbox-exec to deny network
            profile = "(version 1)(allow default)(deny network*)"
            return ["sandbox-exec", "-p", profile] + base_cmd
        elif system == "Linux":
            # Linux: use unshare to isolate network namespace (requires no privileges
            # for user namespaces on most modern kernels)
            return ["unshare", "--net", "--map-root-user"] + base_cmd
        else:
            # Fallback: run without sandbox (Windows, etc.)
            logger.warning("No sandbox available on %s, running script without isolation", system)
            return base_cmd

    def _build_env(self) -> dict[str, str]:
        """Build a minimal, stripped environment for sandboxed execution."""
        return {
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "HOME": "/tmp",
            "LANG": "en_US.UTF-8",
        }
