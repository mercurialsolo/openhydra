"""Tests for ASSISTANT.md loading, interest parsing, and schedule parsing."""

from __future__ import annotations

from pathlib import Path

from openhydra.assistant import (
    DEFAULT_ASSISTANT_MD,
    load_assistant_text,
    parse_interests,
    parse_schedule,
)


class TestLoadAssistantText:
    def test_returns_empty_when_no_files(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path / "fakehome")
        monkeypatch.chdir(tmp_path)
        result = load_assistant_text(tmp_path)
        assert result == ""

    def test_loads_global_file(self, tmp_path, monkeypatch):
        home = tmp_path / "fakehome"
        (home / ".openhydra").mkdir(parents=True)
        (home / ".openhydra" / "ASSISTANT.md").write_text("Global rules")
        monkeypatch.setattr(Path, "home", lambda: home)
        monkeypatch.chdir(tmp_path)

        result = load_assistant_text(tmp_path)
        assert result == "Global rules"

    def test_loads_local_file(self, tmp_path, monkeypatch):
        home = tmp_path / "fakehome"
        home.mkdir()
        monkeypatch.setattr(Path, "home", lambda: home)

        project = tmp_path / "project"
        project.mkdir()
        (project / ".openhydra").mkdir()
        (project / ".openhydra" / "ASSISTANT.md").write_text("Project rules")
        monkeypatch.chdir(project)

        result = load_assistant_text(tmp_path)
        assert result == "Project rules"

    def test_merges_global_and_local(self, tmp_path, monkeypatch):
        home = tmp_path / "fakehome"
        (home / ".openhydra").mkdir(parents=True)
        (home / ".openhydra" / "ASSISTANT.md").write_text("Global first")
        monkeypatch.setattr(Path, "home", lambda: home)

        project = tmp_path / "project"
        project.mkdir()
        (project / ".openhydra").mkdir()
        (project / ".openhydra" / "ASSISTANT.md").write_text("Local second")
        monkeypatch.chdir(project)

        result = load_assistant_text(tmp_path)
        assert "Global first" in result
        assert "Local second" in result
        assert result.index("Global first") < result.index("Local second")

    def test_skips_empty_files(self, tmp_path, monkeypatch):
        home = tmp_path / "fakehome"
        (home / ".openhydra").mkdir(parents=True)
        (home / ".openhydra" / "ASSISTANT.md").write_text("   ")
        monkeypatch.setattr(Path, "home", lambda: home)
        monkeypatch.chdir(tmp_path)

        result = load_assistant_text(tmp_path)
        assert result == ""


class TestParseInterests:
    def test_empty_text(self):
        assert parse_interests("") == []

    def test_no_interests_section(self):
        text = "# Guidelines\n- Be helpful\n"
        assert parse_interests(text) == []

    def test_basic_interests(self):
        text = "## Interests\n- AI safety\n- Python updates\n- Rust ecosystem\n"
        result = parse_interests(text)
        assert result == ["AI safety", "Python updates", "Rust ecosystem"]

    def test_skips_html_comments(self):
        text = (
            "## Interests\n"
            "<!-- Example: -->\n"
            "<!-- - Ignored item -->\n"
            "- Real interest\n"
        )
        result = parse_interests(text)
        assert result == ["Real interest"]

    def test_stops_at_next_section(self):
        text = (
            "## Interests\n"
            "- Topic A\n"
            "## Other Section\n"
            "- Not an interest\n"
        )
        result = parse_interests(text)
        assert result == ["Topic A"]

    def test_skips_empty_items(self):
        text = "## Interests\n- \n- Valid item\n-  \n"
        result = parse_interests(text)
        assert result == ["Valid item"]

    def test_multiline_comment_spanning_items(self):
        text = (
            "## Interests\n"
            "<!-- \n- Hidden item\n-->\n"
            "- Visible item\n"
        )
        result = parse_interests(text)
        assert result == ["Visible item"]

    def test_case_insensitive_heading(self):
        text = "## interests\n- lowercase heading\n"
        result = parse_interests(text)
        assert result == ["lowercase heading"]


class TestParseSchedule:
    def test_empty_text(self):
        assert parse_schedule("") == {}

    def test_no_schedule_section(self):
        text = "# Guidelines\n- Be helpful\n"
        assert parse_schedule(text) == {}

    def test_basic_schedule(self):
        text = (
            "## Schedule\n"
            "- timezone: America/New_York\n"
            "- active_hours: 8:00-22:00\n"
            "- delivery_channel: slack\n"
            "- owner_id: U12345\n"
        )
        result = parse_schedule(text)
        assert result == {
            "timezone": "America/New_York",
            "active_hours": "8:00-22:00",
            "delivery_channel": "slack",
            "owner_id": "U12345",
        }

    def test_stops_at_next_section(self):
        text = (
            "## Schedule\n"
            "- timezone: UTC\n"
            "## Other Section\n"
            "- not_schedule: true\n"
        )
        result = parse_schedule(text)
        assert result == {"timezone": "UTC"}
        assert "not_schedule" not in result

    def test_skips_items_without_colon(self):
        text = (
            "## Schedule\n"
            "- timezone: UTC\n"
            "- just a note\n"
        )
        result = parse_schedule(text)
        assert result == {"timezone": "UTC"}

    def test_skips_empty_values(self):
        text = (
            "## Schedule\n"
            "- timezone:\n"
            "- delivery_channel: slack\n"
        )
        result = parse_schedule(text)
        assert result == {"delivery_channel": "slack"}

    def test_skips_html_comments(self):
        text = (
            "## Schedule\n"
            "<!-- - timezone: commented_out -->\n"
            "- delivery_channel: email\n"
        )
        result = parse_schedule(text)
        assert result == {"delivery_channel": "email"}

    def test_case_insensitive_heading(self):
        text = "## schedule\n- timezone: UTC\n"
        result = parse_schedule(text)
        assert result == {"timezone": "UTC"}

    def test_colon_in_value(self):
        text = "## Schedule\n- active_hours: 8:00-22:00\n"
        result = parse_schedule(text)
        assert result["active_hours"] == "8:00-22:00"

    def test_alongside_interests(self):
        text = (
            "## Schedule\n"
            "- timezone: America/Chicago\n"
            "\n"
            "## Interests\n"
            "- AI safety\n"
        )
        schedule = parse_schedule(text)
        interests = parse_interests(text)
        assert schedule == {"timezone": "America/Chicago"}
        assert interests == ["AI safety"]


class TestDefaultTemplate:
    def test_default_has_interests_section(self):
        assert "## Interests" in DEFAULT_ASSISTANT_MD

    def test_default_has_core_principles(self):
        assert "## Core Principles" in DEFAULT_ASSISTANT_MD

    def test_default_interests_are_commented_out(self):
        interests = parse_interests(DEFAULT_ASSISTANT_MD)
        assert interests == []
