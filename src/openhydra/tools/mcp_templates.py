"""MCP server templates — predefined configs for common browser/search tools.

Data-only module. Each template is a dict describing how to launch an MCP
server via stdio transport.  Templates are grouped by *category* so the
engine can auto-wire a default browser and a default search provider.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class McpTemplate:
    """A predefined MCP server configuration."""

    name: str
    category: str  # "browser" | "search"
    command: str
    args: list[str] = field(default_factory=list)
    env_keys: list[str] = field(default_factory=list)  # required env vars
    description: str = ""
    default: bool = False  # is this the default for its category?


ALL_TEMPLATES: list[McpTemplate] = [
    # --- Browser ---
    McpTemplate(
        name="claude-in-chrome",
        category="browser",
        command="npx",
        args=["@anthropic-ai/claude-in-chrome-mcp@latest"],
        description="Chrome browser automation via Claude in Chrome extension",
        default=True,
    ),
    McpTemplate(
        name="playwright",
        category="browser",
        command="npx",
        args=["@playwright/mcp@latest"],
        description="Headless browser automation via Playwright",
    ),
    McpTemplate(
        name="puppeteer",
        category="browser",
        command="npx",
        args=["@modelcontextprotocol/server-puppeteer"],
        description="Browser automation via Puppeteer (headless Chrome)",
    ),
    McpTemplate(
        name="browserbase",
        category="browser",
        command="npx",
        args=["@browserbasehq/mcp-server-browserbase"],
        env_keys=["BROWSERBASE_API_KEY", "BROWSERBASE_PROJECT_ID"],
        description="Cloud browser automation via Browserbase + Stagehand",
    ),
    # --- Search ---
    McpTemplate(
        name="tavily",
        category="search",
        command="npx",
        args=["tavily-mcp@0.1.2"],
        env_keys=["TAVILY_API_KEY"],
        description="Web search via Tavily API (opt-in; Claude CLI has WebSearch built-in)",
    ),
    McpTemplate(
        name="duckduckgo",
        category="search",
        command="npx",
        args=["duckduckgo-mcp-server"],
        description="Web search via DuckDuckGo (no API key needed)",
    ),
    McpTemplate(
        name="perplexity",
        category="search",
        command="npx",
        args=["@perplexity-ai/mcp-server"],
        env_keys=["PERPLEXITY_API_KEY"],
        description="Web search via Perplexity API",
    ),
]

_BY_NAME: dict[str, McpTemplate] = {t.name: t for t in ALL_TEMPLATES}


def get_template(name: str) -> McpTemplate | None:
    """Look up a template by name."""
    return _BY_NAME.get(name)


def get_default_templates() -> list[McpTemplate]:
    """Return the default template for each category."""
    return [t for t in ALL_TEMPLATES if t.default]


def get_templates_by_category(category: str) -> list[McpTemplate]:
    """Return all templates in a category."""
    return [t for t in ALL_TEMPLATES if t.category == category]


def list_categories() -> list[str]:
    """Return unique categories."""
    seen: dict[str, None] = {}
    for t in ALL_TEMPLATES:
        seen.setdefault(t.category)
    return list(seen.keys())
