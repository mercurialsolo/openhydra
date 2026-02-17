"""Tests for the skill security sandbox executor."""

from __future__ import annotations

import asyncio
import stat
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from openhydra.skills.security.sandbox import SandboxExecutor


@pytest.fixture()
def executor() -> SandboxExecutor:
    return SandboxExecutor(timeout=5)


class TestSandboxExecutor:
    """Test sandbox script execution with mocked subprocess."""

    @pytest.mark.asyncio()
    async def test_safe_script_exits_zero(self, executor: SandboxExecutor, tmp_path: Path) -> None:
        script = tmp_path / "safe.sh"
        script.write_text("#!/bin/bash\necho hello\n")
        script.chmod(script.stat().st_mode | stat.S_IEXEC)

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_proc:
            mock_proc.return_value.communicate = AsyncMock(
                return_value=(b"hello\n", b""),
            )
            mock_proc.return_value.returncode = 0

            result = await executor.execute_script(script)

        assert result.exit_code == 0
        assert result.stdout == "hello\n"
        assert not result.timed_out

    @pytest.mark.asyncio()
    async def test_timeout_kills_process(self, tmp_path: Path) -> None:
        executor = SandboxExecutor(timeout=1)
        script = tmp_path / "slow.sh"
        script.write_text("#!/bin/bash\nsleep 100\n")
        script.chmod(script.stat().st_mode | stat.S_IEXEC)

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_proc:
            mock_proc.return_value.communicate = AsyncMock(
                side_effect=asyncio.TimeoutError,
            )
            mock_proc.return_value.kill = AsyncMock()
            mock_proc.return_value.wait = AsyncMock()
            mock_proc.return_value.returncode = -9

            result = await executor.execute_script(script)

        assert result.timed_out
        mock_proc.return_value.kill.assert_called_once()

    @pytest.mark.asyncio()
    async def test_nonzero_exit_code(self, executor: SandboxExecutor, tmp_path: Path) -> None:
        script = tmp_path / "fail.sh"
        script.write_text("#!/bin/bash\nexit 1\n")
        script.chmod(script.stat().st_mode | stat.S_IEXEC)

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_proc:
            mock_proc.return_value.communicate = AsyncMock(
                return_value=(b"", b"error\n"),
            )
            mock_proc.return_value.returncode = 1

            result = await executor.execute_script(script)

        assert result.exit_code == 1
        assert "error" in result.stderr

    @pytest.mark.asyncio()
    async def test_nonexistent_script(self, executor: SandboxExecutor) -> None:
        result = await executor.execute_script(Path("/nonexistent/script.sh"))
        assert result.exit_code == -1
        assert "not found" in result.stderr.lower()

    @pytest.mark.asyncio()
    async def test_stripped_env(self, executor: SandboxExecutor) -> None:
        env = executor._build_env()
        # Should not contain any secret-like keys
        assert "ANTHROPIC_API_KEY" not in env
        assert "AWS_SECRET_ACCESS_KEY" not in env
        # Should have basic PATH
        assert "PATH" in env

    @pytest.mark.asyncio()
    async def test_execute_all_empty_dir(
        self, executor: SandboxExecutor, tmp_path: Path,
    ) -> None:
        # No scripts/ subdirectory
        results = await executor.execute_all(tmp_path)
        assert results == []

    @pytest.mark.asyncio()
    async def test_execute_all_runs_scripts(
        self, executor: SandboxExecutor, tmp_path: Path,
    ) -> None:
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        script = scripts_dir / "test.sh"
        script.write_text("#!/bin/bash\necho ok\n")
        script.chmod(script.stat().st_mode | stat.S_IEXEC)

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_proc:
            mock_proc.return_value.communicate = AsyncMock(
                return_value=(b"ok\n", b""),
            )
            mock_proc.return_value.returncode = 0

            results = await executor.execute_all(tmp_path)

        assert len(results) == 1
        assert results[0].exit_code == 0

    def test_build_command_includes_interpreter(
        self, executor: SandboxExecutor, tmp_path: Path,
    ) -> None:
        py_script = tmp_path / "test.py"
        py_script.touch()
        cmd = executor._build_command(py_script)
        # The command should contain python3 somewhere
        assert any("python3" in part for part in cmd)

    def test_build_command_sh_interpreter(self, executor: SandboxExecutor, tmp_path: Path) -> None:
        sh_script = tmp_path / "test.sh"
        sh_script.touch()
        cmd = executor._build_command(sh_script)
        assert any("bash" in part for part in cmd)
