"""Tests for MCP server templates, config parsing, engine resolution, and tool aliases."""

from __future__ import annotations

import yaml

from openhydra.config import (
    McpServerConfig,
    McpTemplatesConfig,
    OpenHydraConfig,
    ToolsConfig,
    load_config,
)
from openhydra.tools.mcp_templates import (
    ALL_TEMPLATES,
    get_default_templates,
    get_template,
    get_templates_by_category,
    list_categories,
)

# ---------------------------------------------------------------------------
# Template registry
# ---------------------------------------------------------------------------


def test_all_templates_not_empty():
    assert len(ALL_TEMPLATES) >= 7


def test_get_template_by_name():
    t = get_template("tavily")
    assert t is not None
    assert t.name == "tavily"
    assert t.category == "search"


def test_get_template_missing():
    assert get_template("nonexistent") is None


def test_get_default_templates():
    defaults = get_default_templates()
    names = {t.name for t in defaults}
    assert "claude-in-chrome" in names
    # tavily is opt-in (Claude CLI has WebSearch built-in)
    assert "tavily" not in names


def test_get_templates_by_category():
    browsers = get_templates_by_category("browser")
    assert len(browsers) >= 4
    for t in browsers:
        assert t.category == "browser"


def test_list_categories():
    cats = list_categories()
    assert "browser" in cats
    assert "search" in cats


def test_each_template_has_command():
    for t in ALL_TEMPLATES:
        assert t.command, f"Template {t.name} missing command"
        assert t.category in ("browser", "search")


def test_env_keys_on_tavily():
    t = get_template("tavily")
    assert "TAVILY_API_KEY" in t.env_keys


def test_no_env_keys_on_duckduckgo():
    t = get_template("duckduckgo")
    assert t.env_keys == []


# ---------------------------------------------------------------------------
# Config parsing
# ---------------------------------------------------------------------------


def test_templates_config_defaults():
    cfg = McpTemplatesConfig()
    assert cfg.browser == ["claude-in-chrome", "playwright"]
    assert cfg.search == "none"  # Claude CLI has WebSearch built-in


def test_tools_config_has_templates():
    cfg = ToolsConfig()
    assert isinstance(cfg.templates, McpTemplatesConfig)


def test_load_config_parses_templates(tmp_path):
    config_file = tmp_path / ".openhydra" / "openhydra.yaml"
    config_file.parent.mkdir(parents=True)
    config_file.write_text(yaml.safe_dump({
        "tools": {
            "templates": {
                "browser": ["playwright", "puppeteer"],
                "search": "duckduckgo",
            }
        }
    }))
    cfg = load_config(config_file)
    assert cfg.tools.templates.browser == ["playwright", "puppeteer"]
    assert cfg.tools.templates.search == "duckduckgo"


# ---------------------------------------------------------------------------
# Engine template resolution
# ---------------------------------------------------------------------------


def test_resolve_mcp_templates_adds_servers(monkeypatch):
    """Templates are resolved into McpServerConfig entries."""
    monkeypatch.setenv("TAVILY_API_KEY", "test-key-123")

    from openhydra.engine import Engine

    config = OpenHydraConfig()
    config.tools.templates = McpTemplatesConfig(
        browser=["playwright"], search="tavily",
    )
    engine = Engine.__new__(Engine)
    engine.config = config

    import logging
    engine._logger = logging.getLogger("test")

    engine._resolve_mcp_templates()

    names = {s.name for s in config.tools.mcp_servers}
    assert "playwright" in names
    assert "tavily" in names

    # Check tavily has env
    tavily_srv = next(s for s in config.tools.mcp_servers if s.name == "tavily")
    assert tavily_srv.env["TAVILY_API_KEY"] == "test-key-123"


def test_resolve_skips_none_template():
    """Empty browser list and 'none' search means no servers."""
    from openhydra.engine import Engine

    config = OpenHydraConfig()
    config.tools.templates = McpTemplatesConfig(
        browser=[], search="none",
    )
    engine = Engine.__new__(Engine)
    engine.config = config

    engine._resolve_mcp_templates()

    assert len(config.tools.mcp_servers) == 0


def test_resolve_skips_missing_env(monkeypatch):
    """Templates with missing env vars are skipped with a warning."""
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)

    from openhydra.engine import Engine

    config = OpenHydraConfig()
    config.tools.templates = McpTemplatesConfig(
        browser=[], search="tavily",
    )
    engine = Engine.__new__(Engine)
    engine.config = config

    engine._resolve_mcp_templates()

    names = {s.name for s in config.tools.mcp_servers}
    assert "tavily" not in names


def test_resolve_skips_duplicate():
    """If user already configured a server by name, template is skipped."""
    from openhydra.engine import Engine

    config = OpenHydraConfig()
    config.tools.templates = McpTemplatesConfig(
        browser=["playwright"], search="none",
    )
    config.tools.mcp_servers = [
        McpServerConfig(name="playwright", command="custom-playwright"),
    ]
    engine = Engine.__new__(Engine)
    engine.config = config

    engine._resolve_mcp_templates()

    # Should still only have the original
    assert len(config.tools.mcp_servers) == 1
    assert config.tools.mcp_servers[0].command == "custom-playwright"


# ---------------------------------------------------------------------------
# Tool alias resolution
# ---------------------------------------------------------------------------


def test_tool_alias_resolves_websearch():
    """WebSearch in allowed_tools resolves to tavily_search if available."""
    from openhydra.agents.base import ToolDefinition
    from openhydra.agents.registry import AgentRegistry
    from openhydra.roles.catalog import RoleCatalog, RoleDefinition
    from openhydra.roles.executor import RoleExecutor
    from openhydra.skills.registry import SkillRegistry
    from openhydra.tools.executor import ToolExecutor

    # Create executor with a tool named tavily_search
    tool_exec = ToolExecutor()

    class FakeRouter:
        def has_tool(self, name):
            return name == "tavily_search"

        def get_definitions(self):
            return [
                ToolDefinition(
                    name="tavily_search",
                    description="Search",
                    source="mcp",
                )
            ]

        async def execute(self, name, args):
            return "ok"

    tool_exec.set_filesystem_router(FakeRouter())

    role = RoleDefinition(
        id="test", name="Test",
        allowed_tools=["WebSearch"],
    )
    executor = RoleExecutor(
        roles=RoleCatalog(), agents=AgentRegistry(),
        skills=SkillRegistry(), tool_executor=tool_exec,
    )
    result = executor._prepare_tools(role)
    assert len(result) == 1
    assert result[0].name == "tavily_search"


def test_tool_alias_keeps_direct_name():
    """Direct tool names are kept even if alias exists."""
    from openhydra.agents.registry import AgentRegistry
    from openhydra.roles.catalog import RoleCatalog, RoleDefinition
    from openhydra.roles.executor import RoleExecutor
    from openhydra.skills.registry import SkillRegistry
    from openhydra.tools.executor import ToolExecutor
    from openhydra.tools.filesystem import FilesystemToolRouter

    tool_exec = ToolExecutor()
    tool_exec.set_filesystem_router(FilesystemToolRouter())

    role = RoleDefinition(
        id="test", name="Test",
        allowed_tools=["Read", "Bash"],
    )
    executor = RoleExecutor(
        roles=RoleCatalog(), agents=AgentRegistry(),
        skills=SkillRegistry(), tool_executor=tool_exec,
    )
    result = executor._prepare_tools(role)
    names = {t.name for t in result}
    assert names == {"Read", "Bash"}


# ---------------------------------------------------------------------------
# Init wizard (non-interactive parts)
# ---------------------------------------------------------------------------


def test_detect_providers():
    from openhydra.cli.init_wizard import _detect_providers

    providers = _detect_providers()
    assert "claude-sdk" in providers
    assert "codex-cli" in providers
    assert "anthropic-api" in providers
    # Values are booleans
    for v in providers.values():
        assert isinstance(v, bool)


# ---------------------------------------------------------------------------
# Browser fallback chain
# ---------------------------------------------------------------------------


def test_puppeteer_template_exists():
    t = get_template("puppeteer")
    assert t is not None
    assert t.category == "browser"
    assert t.env_keys == []


def test_browserbase_template_exists():
    t = get_template("browserbase")
    assert t is not None
    assert t.category == "browser"
    assert "BROWSERBASE_API_KEY" in t.env_keys
    assert "BROWSERBASE_PROJECT_ID" in t.env_keys


def test_load_config_browser_str_backward_compat(tmp_path):
    """A scalar string browser value is coerced to a single-element list."""
    config_file = tmp_path / ".openhydra" / "openhydra.yaml"
    config_file.parent.mkdir(parents=True)
    config_file.write_text(yaml.safe_dump({
        "tools": {
            "templates": {
                "browser": "playwright",
                "search": "none",
            }
        }
    }))
    cfg = load_config(config_file)
    assert cfg.tools.templates.browser == ["playwright"]


def test_load_config_browser_none_str(tmp_path):
    """browser: 'none' is coerced to an empty list."""
    config_file = tmp_path / ".openhydra" / "openhydra.yaml"
    config_file.parent.mkdir(parents=True)
    config_file.write_text(yaml.safe_dump({
        "tools": {
            "templates": {
                "browser": "none",
                "search": "none",
            }
        }
    }))
    cfg = load_config(config_file)
    assert cfg.tools.templates.browser == []


def test_resolve_browser_list_multiple_servers():
    """Browser list with multiple entries resolves all of them."""
    from openhydra.engine import Engine

    config = OpenHydraConfig()
    config.tools.templates = McpTemplatesConfig(
        browser=["claude-in-chrome", "playwright", "puppeteer"],
        search="none",
    )
    engine = Engine.__new__(Engine)
    engine.config = config

    engine._resolve_mcp_templates()

    names = [s.name for s in config.tools.mcp_servers]
    assert "claude-in-chrome" in names
    assert "playwright" in names
    assert "puppeteer" in names
    assert len(names) == 3
