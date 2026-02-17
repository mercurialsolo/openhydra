"""Interactive init wizard for OpenHydra configuration."""

from __future__ import annotations

import os
import secrets
import shutil
from pathlib import Path

import yaml
from rich.console import Console

console = Console()


def _detect_providers() -> dict[str, bool]:
    """Detect which agent providers are available."""
    providers: dict[str, bool] = {}

    # Claude CLI
    providers["claude-sdk"] = shutil.which("claude") is not None

    # Codex CLI
    providers["codex-cli"] = shutil.which("codex") is not None

    # Anthropic API (needs key)
    providers["anthropic-api"] = bool(os.environ.get("ANTHROPIC_API_KEY"))

    return providers


def _pick_option(
    prompt_text: str,
    options: list[tuple[str, str]],
    default: str = "",
) -> str:
    """Prompt user to pick from a list of options."""
    for i, (value, label) in enumerate(options, 1):
        marker = " (default)" if value == default else ""
        console.print(f"  [{i}] {label}{marker}")

    while True:
        raw = console.input(f"\n{prompt_text} [{default}]: ").strip()
        if not raw:
            return default
        try:
            idx = int(raw)
            if 1 <= idx <= len(options):
                return options[idx - 1][0]
        except ValueError:
            # Try matching by name
            for value, _label in options:
                if raw.lower() == value.lower():
                    return value
        console.print("[red]Invalid choice, try again.[/red]")


def run_init_wizard() -> None:
    """Run the interactive init wizard."""
    console.print("\n[bold]OpenHydra Setup Wizard[/bold]\n")

    # 1. Detect providers
    providers = _detect_providers()
    console.print("[bold]Detected providers:[/bold]")
    for name, available in providers.items():
        status = "[green]available[/green]" if available else "[dim]not found[/dim]"
        console.print(f"  {name}: {status}")

    available_providers = [
        (name, name) for name, avail in providers.items() if avail
    ]
    if not available_providers:
        console.print(
            "\n[yellow]No providers detected.[/yellow] "
            "Install claude CLI or set ANTHROPIC_API_KEY."
        )
        available_providers = [
            ("claude-sdk", "claude-sdk (not installed)"),
            ("anthropic-api", "anthropic-api (no API key)"),
        ]

    # 2. Pick default provider
    default_provider = next(
        (n for n, a in providers.items() if a), "claude-sdk"
    )
    provider = _pick_option(
        "Default provider",
        available_providers,
        default=default_provider,
    )

    # 3. Pick primary browser tool (fallbacks auto-added)
    console.print("\n[bold]Browser automation (fallback chain):[/bold]")
    console.print("  Primary choice runs first; others are tried if it fails to connect.\n")
    primary_browser = _pick_option(
        "Primary browser",
        [
            ("claude-in-chrome", "Claude in Chrome (requires extension)"),
            ("playwright", "Playwright (headless, auto-installs)"),
            ("puppeteer", "Puppeteer (headless Chrome via npx)"),
            ("browserbase", "Browserbase (cloud, requires API key)"),
        ],
        default="claude-in-chrome",
    )

    # Build ordered fallback list: primary first, then other local options
    _all_browsers = ["claude-in-chrome", "playwright", "puppeteer", "browserbase"]
    browser: list[str] = [primary_browser]
    for b in _all_browsers:
        if b != primary_browser and b != "browserbase":
            browser.append(b)

    # 4. Pick search tool
    console.print("\n[bold]Web search:[/bold]")
    search = _pick_option(
        "Search tool",
        [
            ("tavily", "Tavily (requires TAVILY_API_KEY)"),
            ("duckduckgo", "DuckDuckGo (free, no API key)"),
            ("perplexity", "Perplexity (requires PERPLEXITY_API_KEY)"),
            ("none", "None"),
        ],
        default="tavily",
    )

    # 5. Prompt for missing API keys
    env_hints: list[str] = []
    if "browserbase" in browser:
        if not os.environ.get("BROWSERBASE_API_KEY"):
            console.print(
                "\n[yellow]Browserbase requires BROWSERBASE_API_KEY.[/yellow] "
                "Get one at https://browserbase.com"
            )
            env_hints.append("export BROWSERBASE_API_KEY=<your-key>")
        if not os.environ.get("BROWSERBASE_PROJECT_ID"):
            env_hints.append("export BROWSERBASE_PROJECT_ID=<your-project-id>")
    if search == "tavily" and not os.environ.get("TAVILY_API_KEY"):
        console.print(
            "\n[yellow]Tavily requires TAVILY_API_KEY.[/yellow] "
            "Get one at https://tavily.com"
        )
        env_hints.append("export TAVILY_API_KEY=<your-key>")
    if search == "perplexity" and not os.environ.get("PERPLEXITY_API_KEY"):
        console.print(
            "\n[yellow]Perplexity requires PERPLEXITY_API_KEY.[/yellow] "
            "Get one at https://perplexity.ai"
        )
        env_hints.append("export PERPLEXITY_API_KEY=<your-key>")

    # 6. Generate API key
    api_key = secrets.token_hex(16)

    # 7. Build config
    config_data: dict = {
        "agents": {"default_provider": provider},
        "web": {"api_key": api_key},
        "tools": {
            "templates": {
                "browser": browser,
                "search": search,
            },
        },
    }

    # Write config
    config_dir = Path.home() / ".openhydra"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "openhydra.yaml"

    # Merge with existing if present
    existing: dict = {}
    if config_path.exists():
        with open(config_path) as f:
            existing = yaml.safe_load(f) or {}

    # Deep merge (config_data wins)
    for key, value in config_data.items():
        if isinstance(value, dict) and isinstance(existing.get(key), dict):
            existing[key].update(value)
        else:
            existing[key] = value

    with open(config_path, "w") as f:
        yaml.safe_dump(existing, f, default_flow_style=False)

    # Create default ASSISTANT.md if absent
    assistant_path = config_dir / "ASSISTANT.md"
    if not assistant_path.exists():
        from openhydra.assistant import DEFAULT_ASSISTANT_MD

        assistant_path.write_text(DEFAULT_ASSISTANT_MD, encoding="utf-8")
        console.print(f"[bold green]Created {assistant_path}[/bold green]")

    # Summary
    console.print(f"\n[bold green]Config written to {config_path}[/bold green]")
    console.print(f"  Provider: {provider}")
    console.print(f"  Browser:  {' → '.join(browser)}")
    console.print(f"  Search:   {search}")
    console.print(f"  API key:  {api_key}")

    if env_hints:
        console.print("\n[bold]Set these environment variables:[/bold]")
        for hint in env_hints:
            console.print(f"  {hint}")

    console.print(
        "\n[bold]Start serving:[/bold]\n  openhydra serve\n"
    )
