"""Tests for CLI commands."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import yaml
from typer.testing import CliRunner

from openhydra.cli.main import _configure_serve_for_web_clients, app

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


def test_agent_scaffold_command_help() -> None:
    result = runner.invoke(app, ["agent", "scaffold", "--help"])
    assert result.exit_code == 0
    assert "roles.yaml" in result.output


def test_agent_scaffold_requires_role_id_when_not_interactive(tmp_path) -> None:
    roles_file = tmp_path / "roles.yaml"
    result = runner.invoke(
        app,
        ["agent", "scaffold", "--roles-file", str(roles_file)],
    )
    assert result.exit_code == 1
    assert "Role ID is required" in result.output


def test_configure_serve_for_web_clients_forces_web_enabled() -> None:
    from openhydra.config import OpenHydraConfig

    cfg = OpenHydraConfig()
    cfg.web.enabled = False

    was_enabled = _configure_serve_for_web_clients(cfg, host="0.0.0.0", port=9090)

    assert was_enabled is False
    assert cfg.web.enabled is True
    assert cfg.web.host == "0.0.0.0"
    assert cfg.web.port == 9090


def test_agent_scaffold_creates_role_entry(tmp_path) -> None:
    roles_file = tmp_path / "roles.yaml"
    roles_file.write_text("roles:\n  existing:\n    name: Existing\n")

    result = runner.invoke(
        app,
        [
            "agent",
            "scaffold",
            "eng.docs",
            "--roles-file",
            str(roles_file),
            "--tool",
            "Read",
            "--tool",
            "Write",
            "--skill-pack",
            "coding_principles",
            "--quality-threshold",
            "24",
            "--tests-gate",
        ],
    )

    assert result.exit_code == 0
    document = yaml.safe_load(roles_file.read_text())
    assert "roles" in document
    assert "existing" in document["roles"]
    assert "eng.docs" in document["roles"]

    role = document["roles"]["eng.docs"]
    assert role["name"] == "Eng Docs"
    assert role["model"] == "claude-sonnet-4-5-20250929"
    assert role["skill_packs"] == ["coding_principles"]
    assert role["allowed_tools"] == ["Read", "Write"]
    assert role["budget"]["max_tokens"] == 100000
    assert role["context_budget"]["reasoning_pct"] == 55
    assert role["gates"] == [{"type": "quality", "threshold": 24}, {"type": "tests_pass"}]


def test_agent_scaffold_interactive_collects_objectives_and_context(tmp_path) -> None:
    roles_file = tmp_path / "roles.yaml"

    result = runner.invoke(
        app,
        [
            "agent",
            "scaffold",
            "--roles-file",
            str(roles_file),
            "--interactive",
        ],
        input=(
            "eng.research\n"
            "Research Agent\n"
            "Investigates implementation options\n"
            "identify risks, compare approaches\n"
            "coding_principles, eng_harness\n"
            "Read, Write, Grep\n"
            "design docs, /docs/adr\n"
        ),
    )

    assert result.exit_code == 0
    document = yaml.safe_load(roles_file.read_text())
    role = document["roles"]["eng.research"]
    assert role["name"] == "Research Agent"
    assert role["description"] == "Investigates implementation options"
    assert role["objectives"] == ["identify risks", "compare approaches"]
    assert role["skill_packs"] == ["coding_principles", "eng_harness"]
    assert role["allowed_tools"] == ["Read", "Write", "Grep"]
    assert role["context_reads"] == ["design docs", "/docs/adr"]


def test_agent_scaffold_duplicate_without_force_fails(tmp_path) -> None:
    roles_file = tmp_path / "roles.yaml"
    roles_file.write_text("roles:\n  eng.docs:\n    name: Existing\n")

    result = runner.invoke(
        app,
        ["agent", "scaffold", "eng.docs", "--roles-file", str(roles_file)],
    )

    assert result.exit_code == 1
    assert "already exists" in result.output


def test_agent_scaffold_force_overwrites_existing_role(tmp_path) -> None:
    roles_file = tmp_path / "roles.yaml"
    roles_file.write_text(
        "roles:\n"
        "  eng.docs:\n"
        "    name: Existing\n"
        "    description: Keep me\n"
        "    model: old-model\n"
        "    skill_packs: []\n"
        "    allowed_tools: [Read]\n"
    )

    result = runner.invoke(
        app,
        [
            "agent",
            "scaffold",
            "eng.docs",
            "--roles-file",
            str(roles_file),
            "--force",
            "--description",
            "New description",
        ],
    )

    assert result.exit_code == 0
    document = yaml.safe_load(roles_file.read_text())
    role = document["roles"]["eng.docs"]
    assert role["name"] == "Eng Docs"
    assert role["description"] == "New description"
    assert role["model"] == "claude-sonnet-4-5-20250929"


def test_agent_scaffold_dry_run_does_not_write_file(tmp_path) -> None:
    roles_file = tmp_path / "roles.yaml"
    assert not roles_file.exists()

    result = runner.invoke(
        app,
        ["agent", "scaffold", "qa.reviewer", "--roles-file", str(roles_file), "--dry-run"],
    )

    assert result.exit_code == 0
    assert "qa.reviewer" in result.output
    assert not roles_file.exists()
