"""Tests for CLI commands."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from typer.testing import CliRunner

from openhydra.cli.main import app

runner = CliRunner()


def test_help() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "openhydra" in result.output.lower() or "multi-agent" in result.output.lower()


def test_config_command() -> None:
    result = runner.invoke(app, ["config"])
    assert result.exit_code == 0
    assert "Engine" in result.output
    assert "Memory" in result.output


def test_skills_command() -> None:
    """Skills command lists available skills."""
    # Patch engine to avoid real initialization
    mock_engine = AsyncMock()
    mock_engine.start = AsyncMock()
    mock_engine.stop = AsyncMock()

    from openhydra.skills.registry import SkillRegistry

    registry = SkillRegistry()
    mock_engine.skills = registry

    with patch("openhydra.cli.main._create_engine", return_value=mock_engine):
        result = runner.invoke(app, ["skills"])
        assert result.exit_code == 0


def test_run_command_help() -> None:
    result = runner.invoke(app, ["run", "--help"])
    assert result.exit_code == 0
    assert "task" in result.output.lower()


def test_status_command_help() -> None:
    result = runner.invoke(app, ["status", "--help"])
    assert result.exit_code == 0


def test_approve_command_help() -> None:
    result = runner.invoke(app, ["approve", "--help"])
    assert result.exit_code == 0


def test_reject_command_help() -> None:
    result = runner.invoke(app, ["reject", "--help"])
    assert result.exit_code == 0
