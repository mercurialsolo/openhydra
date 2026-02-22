"""OpenHydra CLI — lightweight multi-agent orchestration."""

from __future__ import annotations

import asyncio
import importlib.util
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import typer
import yaml
from rich.console import Console
from rich.markup import escape
from rich.table import Table

if TYPE_CHECKING:
    from openhydra.config import OpenHydraConfig

app = typer.Typer(
    name="openhydra",
    help="Lightweight local-first multi-agent orchestration.",
    no_args_is_help=True,
)
console = Console()


DEFAULT_ROLE_TOOLS = ["Read", "Glob", "Grep"]
DEFAULT_ROLE_DESCRIPTION = "TODO: Describe this role's responsibilities."


@dataclass
class DoctorCheck:
    """Single setup diagnostic check."""

    status: Literal["ok", "warn", "fail"]
    title: str
    detail: str
    hint: str = ""


def _module_available(module_name: str) -> bool:
    """Return True when a Python module can be imported."""
    return importlib.util.find_spec(module_name) is not None


def _command_available(command: str) -> bool:
    """Return True when an executable exists on PATH."""
    return shutil.which(command) is not None


def _value_set(value: str | None) -> bool:
    """Return True when a config/env value is meaningfully set."""
    return bool(value and str(value).strip())


def _doctor_provider_check(cfg: OpenHydraConfig) -> list[DoctorCheck]:
    """Validate default provider prerequisites."""
    provider = (cfg.agents.default_provider or "").strip()
    checks: list[DoctorCheck] = []

    provider_cfg = cfg.agents.providers.get(provider)
    provider_api_key = provider_cfg.api_key if provider_cfg else ""

    if provider == "claude-sdk":
        ok = _command_available("claude")
        checks.append(
            DoctorCheck(
                status="ok" if ok else "fail",
                title="Default provider (claude-sdk)",
                detail="`claude` CLI detected." if ok else "`claude` CLI not found on PATH.",
                hint="Install Claude CLI or switch provider: `openhydra init --quick`.",
            )
        )
        return checks

    if provider == "codex-cli":
        ok = _command_available("codex")
        checks.append(
            DoctorCheck(
                status="ok" if ok else "fail",
                title="Default provider (codex-cli)",
                detail="`codex` CLI detected." if ok else "`codex` CLI not found on PATH.",
                hint="Install Codex CLI or switch provider: `openhydra init --quick`.",
            )
        )
        return checks

    if provider == "anthropic-api":
        api_key = os.environ.get("ANTHROPIC_API_KEY") or provider_api_key
        ok = _value_set(api_key)
        checks.append(
            DoctorCheck(
                status="ok" if ok else "fail",
                title="Default provider (anthropic-api)",
                detail="Anthropic API key configured."
                if ok
                else "Missing ANTHROPIC_API_KEY (or agents.providers.anthropic-api.api_key).",
                hint=(
                    "Set `ANTHROPIC_API_KEY` or configure "
                    "`agents.providers.anthropic-api.api_key`."
                ),
            )
        )
        return checks

    if provider == "openai-api":
        api_key = os.environ.get("OPENAI_API_KEY") or provider_api_key
        ok = _value_set(api_key)
        checks.append(
            DoctorCheck(
                status="ok" if ok else "fail",
                title="Default provider (openai-api)",
                detail="OpenAI API key configured."
                if ok
                else "Missing OPENAI_API_KEY (or agents.providers.openai-api.api_key).",
                hint="Set `OPENAI_API_KEY` or configure `agents.providers.openai-api.api_key`.",
            )
        )
        return checks

    if provider in cfg.agents.providers:
        checks.append(
            DoctorCheck(
                status="warn",
                title=f"Default provider ({provider})",
                detail=(
                    "Custom provider configured; doctor cannot fully validate "
                    "provider-specific auth."
                ),
                hint="Run `openhydra run \"health check\"` to verify this provider end-to-end.",
            )
        )
        return checks

    checks.append(
        DoctorCheck(
            status="warn",
            title=f"Default provider ({provider or 'unset'})",
            detail="Provider is unknown to built-in checks.",
            hint="Set `agents.default_provider` to claude-sdk/codex-cli/anthropic-api/openai-api.",
        )
    )
    return checks


def _doctor_web_check(cfg: OpenHydraConfig) -> list[DoctorCheck]:
    """Validate web/runtime requirements."""
    checks: list[DoctorCheck] = []
    starlette_ok = _module_available("starlette")
    uvicorn_ok = _module_available("uvicorn")
    checks.append(
        DoctorCheck(
            status="ok" if starlette_ok and uvicorn_ok else "fail",
            title="Web runtime dependencies",
            detail="starlette + uvicorn installed."
            if starlette_ok and uvicorn_ok
            else "Missing web runtime deps (starlette and/or uvicorn).",
            hint='Install web extras: `uv pip install -e ".[web]"` or `".[all]"`.',
        )
    )

    if cfg.web.enabled:
        has_key = _value_set(cfg.web.api_key) or _value_set(os.environ.get("OPENHYDRA_WEB_API_KEY"))
        checks.append(
            DoctorCheck(
                status="ok" if has_key else "warn",
                title="Web API key",
                detail="API key configured."
                if has_key
                else "No web.api_key configured yet.",
                hint="`openhydra serve` will auto-generate one, or set OPENHYDRA_WEB_API_KEY.",
            )
        )
    return checks


def _doctor_slack_check(cfg: OpenHydraConfig) -> list[DoctorCheck]:
    """Validate Slack channel prerequisites."""
    if not cfg.channels.slack.enabled:
        return []
    bot_ok = _value_set(cfg.channels.slack.bot_token)
    app_ok = _value_set(cfg.channels.slack.app_token)
    dep_ok = _module_available("slack_bolt")
    return [
        DoctorCheck(
            status="ok" if dep_ok else "fail",
            title="Slack dependency",
            detail="slack_bolt installed." if dep_ok else "slack_bolt is not installed.",
            hint='Install channel deps: `uv pip install -e ".[slack]"` or `".[all]"`.',
        ),
        DoctorCheck(
            status="ok" if bot_ok and app_ok else "fail",
            title="Slack tokens",
            detail="Bot + app tokens configured."
            if bot_ok and app_ok
            else "Missing OPENHYDRA_SLACK_BOT_TOKEN and/or OPENHYDRA_SLACK_APP_TOKEN.",
            hint="Set both token env vars for Socket Mode.",
        ),
    ]


def _doctor_discord_check(cfg: OpenHydraConfig) -> list[DoctorCheck]:
    """Validate Discord channel prerequisites."""
    if not cfg.channels.discord.enabled:
        return []
    token_ok = _value_set(cfg.channels.discord.bot_token)
    dep_ok = _module_available("discord")
    return [
        DoctorCheck(
            status="ok" if dep_ok else "fail",
            title="Discord dependency",
            detail="discord.py installed." if dep_ok else "discord.py is not installed.",
            hint='Install channel deps: `uv pip install -e ".[discord]"` or `".[all]"`.',
        ),
        DoctorCheck(
            status="ok" if token_ok else "fail",
            title="Discord token",
            detail="Bot token configured."
            if token_ok
            else "Missing OPENHYDRA_DISCORD_BOT_TOKEN.",
            hint="Set OPENHYDRA_DISCORD_BOT_TOKEN.",
        ),
    ]


def _doctor_whatsapp_check(cfg: OpenHydraConfig) -> list[DoctorCheck]:
    """Validate WhatsApp channel prerequisites."""
    if not cfg.channels.whatsapp.enabled:
        return []
    checks: list[DoctorCheck] = []
    wa = cfg.channels.whatsapp
    backend = (wa.backend or "baileys").strip().lower()
    if backend == "cloud-api":
        dep_ok = _module_available("httpx")
        token_ok = _value_set(wa.access_token)
        phone_ok = _value_set(wa.phone_number_id)
        verify_ok = _value_set(wa.verify_token)
        checks.extend(
            [
                DoctorCheck(
                    status="ok" if dep_ok else "fail",
                    title="WhatsApp Cloud API dependency",
                    detail="httpx installed." if dep_ok else "httpx is not installed.",
                    hint='Install channel deps: `uv pip install -e ".[web]"` or `".[all]"`.',
                ),
                DoctorCheck(
                    status="ok" if token_ok and phone_ok and verify_ok else "fail",
                    title="WhatsApp Cloud API credentials",
                    detail="Access token, phone_number_id, and verify_token configured."
                    if token_ok and phone_ok and verify_ok
                    else (
                        "Missing one or more of OPENHYDRA_WHATSAPP_ACCESS_TOKEN, "
                        "phone_number_id, verify_token."
                    ),
                    hint=(
                        "Set OPENHYDRA_WHATSAPP_ACCESS_TOKEN and configure "
                        "channels.whatsapp.phone_number_id/verify_token."
                    ),
                ),
            ]
        )
        if not cfg.web.enabled:
            checks.append(
                DoctorCheck(
                    status="fail",
                    title="WhatsApp Cloud API + web channel",
                    detail="Cloud API backend requires the web channel to be enabled.",
                    hint="Set `web.enabled: true` and run `openhydra serve`.",
                )
            )
        return checks

    node_ok = _command_available(wa.node_path or "node")
    checks.append(
        DoctorCheck(
            status="ok" if node_ok else "fail",
            title="WhatsApp Baileys runtime",
            detail=f"`{wa.node_path or 'node'}` executable detected."
            if node_ok
            else f"`{wa.node_path or 'node'}` not found on PATH.",
            hint="Install Node.js or set channels.whatsapp.node_path.",
        )
    )
    return checks


def _doctor_email_check(cfg: OpenHydraConfig) -> list[DoctorCheck]:
    """Validate email channel prerequisites."""
    if not cfg.channels.email.enabled:
        return []
    email_cfg = cfg.channels.email
    dep_imap = _module_available("aioimaplib")
    dep_smtp = _module_available("aiosmtplib")
    imap_ok = _value_set(email_cfg.imap_host)
    smtp_ok = _value_set(email_cfg.smtp_host)
    user_ok = _value_set(email_cfg.username)

    checks = [
        DoctorCheck(
            status="ok" if dep_imap and dep_smtp else "fail",
            title="Email dependencies",
            detail="aioimaplib + aiosmtplib installed."
            if dep_imap and dep_smtp
            else "Missing aioimaplib and/or aiosmtplib.",
            hint='Install email extras: `uv pip install -e ".[email]"`.',
        ),
        DoctorCheck(
            status="ok" if imap_ok and smtp_ok and user_ok else "fail",
            title="Email server config",
            detail="IMAP host, SMTP host, and username configured."
            if imap_ok and smtp_ok and user_ok
            else "Missing one or more of imap_host, smtp_host, username.",
            hint=(
                "Set OPENHYDRA_EMAIL_IMAP_HOST, OPENHYDRA_EMAIL_SMTP_HOST, "
                "OPENHYDRA_EMAIL_USERNAME."
            ),
        ),
    ]

    if (email_cfg.auth_method or "").lower() == "oauth2":
        oauth_ok = all(
            [
                _value_set(email_cfg.oauth_client_id),
                _value_set(email_cfg.oauth_client_secret),
                _value_set(email_cfg.oauth_refresh_token),
            ]
        )
        checks.append(
            DoctorCheck(
                status="ok" if oauth_ok else "fail",
                title="Email OAuth2 credentials",
                detail="OAuth2 client id/secret/refresh token configured."
                if oauth_ok
                else "Missing OAuth2 client id/secret/refresh token.",
                hint=(
                    "Set OPENHYDRA_EMAIL_OAUTH_CLIENT_ID, OPENHYDRA_EMAIL_OAUTH_CLIENT_SECRET, "
                    "OPENHYDRA_EMAIL_OAUTH_REFRESH_TOKEN."
                ),
            )
        )
    else:
        password_ok = _value_set(email_cfg.password)
        checks.append(
            DoctorCheck(
                status="ok" if password_ok else "fail",
                title="Email password auth",
                detail="Email password configured."
                if password_ok
                else "Missing OPENHYDRA_EMAIL_PASSWORD.",
                hint="Set OPENHYDRA_EMAIL_PASSWORD or switch to auth_method: oauth2.",
            )
        )

    return checks


def _run_doctor(cfg: OpenHydraConfig) -> list[DoctorCheck]:
    """Collect all setup checks."""
    checks: list[DoctorCheck] = []
    checks.extend(_doctor_provider_check(cfg))
    checks.extend(_doctor_web_check(cfg))
    checks.extend(_doctor_slack_check(cfg))
    checks.extend(_doctor_discord_check(cfg))
    checks.extend(_doctor_whatsapp_check(cfg))
    checks.extend(_doctor_email_check(cfg))
    if cfg.channels.extras:
        checks.append(
            DoctorCheck(
                status="warn",
                title="External channel plugins",
                detail=(
                    f"Found {len(cfg.channels.extras)} external channel config(s); "
                    "doctor does not validate plugin-specific requirements."
                ),
                hint="Validate custom channels with their plugin docs.",
            )
        )
    return checks


def _humanize_role_id(role_id: str) -> str:
    """Convert a role id like `eng.implement` into `Eng Implement`."""
    cleaned = re.sub(r"[^a-zA-Z0-9]+", " ", role_id).strip()
    return cleaned.title() or role_id


def _split_csv_values(raw: str) -> list[str]:
    """Parse comma-separated values into a clean list."""
    return [value.strip() for value in raw.split(",") if value.strip()]


def _prompt_text(prompt_text: str, *, default: str = "", required: bool = False) -> str:
    """Prompt for a single text value."""
    while True:
        suffix = f" [{default}]" if default else ""
        raw = console.input(f"{prompt_text}{suffix}: ").strip()
        if raw:
            return raw
        if default:
            return default
        if not required:
            return ""
        console.print("[red]This field is required.[/red]")


def _prompt_csv(prompt_text: str, *, default: list[str] | None = None) -> list[str]:
    """Prompt for a comma-separated list."""
    default_values = default or []
    default_text = ", ".join(default_values)
    raw = _prompt_text(prompt_text, default=default_text, required=False)
    if not raw:
        return []
    return _split_csv_values(raw)


def _load_roles_document(path: Path) -> tuple[dict, dict[str, dict]]:
    """Load a roles YAML document and return full doc + roles mapping."""
    if not path.exists():
        return {"roles": {}}, {}

    raw_doc = yaml.safe_load(path.read_text()) or {}
    if not isinstance(raw_doc, dict):
        raise typer.BadParameter(f"{path} must contain a YAML mapping at the root.")

    raw_roles = raw_doc.get("roles")
    if raw_roles is None:
        raw_roles = {}
    if not isinstance(raw_roles, dict):
        raise typer.BadParameter(f"{path} must contain a top-level 'roles' mapping.")

    roles: dict[str, dict] = {}
    for role_key, role_value in raw_roles.items():
        if not isinstance(role_key, str):
            raise typer.BadParameter(f"{path} has a non-string role key: {role_key!r}")
        if not isinstance(role_value, dict):
            raise typer.BadParameter(f"Role '{role_key}' in {path} must be a mapping.")
        roles[role_key] = role_value

    return raw_doc, roles


def _run_async(coro):
    """Bridge sync typer with async engine."""
    return asyncio.run(coro)


def _run_cli(coro) -> None:
    """Run a CLI coroutine and print user-friendly errors."""
    try:
        _run_async(coro)
    except typer.Exit:
        raise
    except Exception as exc:
        from openhydra.hydra_compat import HydraCompatError

        if isinstance(exc, HydraCompatError):
            console.print(f"[bold red]Error ({exc.status_code}):[/bold red] {exc.detail}")
        else:
            console.print(f"[bold red]Error:[/bold red] {exc}")
        raise typer.Exit(code=1) from exc


async def _create_engine():
    """Create and start an Engine instance."""
    from openhydra.engine import Engine

    engine = Engine()
    await engine.start()
    return engine


def _configure_serve_for_web_clients(cfg: OpenHydraConfig, *, host: str, port: int) -> bool:
    """Ensure `openhydra serve` always exposes the web API for local web clients."""
    was_enabled = bool(cfg.web.enabled)
    cfg.web.enabled = True
    cfg.web.host = host
    cfg.web.port = port
    return was_enabled


@app.command()
def run(
    task: str = typer.Argument(help="Task description"),
    watch: bool = typer.Option(False, "--watch", "-w", help="Stream progress events"),
) -> None:
    """Submit a task for multi-agent execution."""

    async def _run():
        from openhydra.hydra_compat import HydraCompatService

        engine = await _create_engine()
        api = HydraCompatService(engine)
        try:
            if watch:
                from openhydra.events import Event

                async def on_event(event: Event) -> None:
                    console.print(f"  [{event.type}] {event.data}")

                engine.events.on_all(on_event)

            console.print(f"[bold]Submitting:[/bold] {task}")
            started = await api.start_workflow(
                {
                    "workflow_type": "DynamicWorkflow",
                    "input": {
                        "task_description": task,
                        "submitter": "cli",
                        "preferred_channel": "hydra_cli",
                    },
                }
            )
            workflow_id = started["workflow_id"]
            console.print(f"[bold green]Workflow created:[/bold green] {workflow_id}")

            if watch:
                # Wait for workflow to complete
                bg_task = engine._tasks.get(workflow_id)
                if bg_task:
                    await bg_task
                    wf = await api.get_workflow(workflow_id)
                    metrics = wf.get("metrics") or {}
                    console.print(f"\n[bold]Status:[/bold] {wf.get('status')}")
                    console.print(
                        f"[bold]Cost:[/bold] ${float(metrics.get('total_cost_usd') or 0):.4f}"
                    )
                    console.print(f"[bold]Tokens:[/bold] {int(metrics.get('total_tokens') or 0)}")
        finally:
            await engine.stop()

    _run_cli(_run())


@app.command()
def status(
    workflow_id: str = typer.Argument(None, help="Workflow ID (optional)"),
) -> None:
    """Show workflow status."""

    async def _status():
        from openhydra.hydra_compat import HydraCompatService

        engine = await _create_engine()
        api = HydraCompatService(engine)
        try:
            if workflow_id:
                wf = await api.get_workflow(workflow_id)
                wf_status = str(wf.get("status") or "")
                wf_status_style = {
                    "COMPLETED": "green",
                    "RUNNING": "yellow",
                    "FAILED": "red",
                    "CANCELLED": "red",
                    "PAUSED": "yellow",
                    "QUEUED": "dim",
                    "WAITING_FOR_APPROVAL": "yellow",
                    "WAITING_FOR_CORRECTION": "yellow",
                }.get(wf_status, "")
                metrics = wf.get("metrics") or {}
                wf_input = wf.get("input") if isinstance(wf.get("input"), dict) else {}
                task_desc = str(
                    wf_input.get("task_description")
                    or wf_input.get("description")
                    or wf_input.get("task")
                    or ""
                )

                console.print(f"\n[bold]Workflow:[/bold] {wf.get('id')}")
                console.print(
                    f"[bold]Status:[/bold] [{wf_status_style}]{wf_status}[/{wf_status_style}]"
                )
                console.print(f"[bold]Task:[/bold] {task_desc}")
                console.print(
                    f"[bold]Cost:[/bold] ${float(metrics.get('total_cost_usd') or 0):.4f}"
                )
                console.print(f"[bold]Tokens:[/bold] {int(metrics.get('total_tokens') or 0)}")

                if wf.get("steps"):
                    table = Table(title="Steps")
                    table.add_column("#", style="dim")
                    table.add_column("Role")
                    table.add_column("Status")
                    table.add_column("Cost")

                    for idx, step in enumerate(wf["steps"], start=1):
                        status_style = {
                            "completed": "green",
                            "running": "yellow",
                            "failed": "red",
                            "pending": "dim",
                            "skipped": "dim",
                            "waiting_approval": "yellow",
                        }.get(step["status"], "")
                        table.add_row(
                            str(idx),
                            str(step.get("agent_role") or step.get("name") or "agent"),
                            f"[{status_style}]{step['status']}[/{status_style}]",
                            f"${float(step.get('cost_usd') or 0):.4f}",
                        )
                    console.print(table)
            else:
                listing = await api.list_workflows()
                workflows = listing.get("workflows", [])
                if not workflows:
                    console.print("[dim]No workflows found.[/dim]")
                    return

                table = Table(title="Workflows")
                table.add_column("ID")
                table.add_column("Status")
                table.add_column("Task")
                table.add_column("Cost")
                table.add_column("Created")

                for wf in workflows:
                    wf_input = wf.get("input") if isinstance(wf.get("input"), dict) else {}
                    task_desc = str(
                        wf_input.get("task_description")
                        or wf_input.get("description")
                        or wf_input.get("task")
                        or ""
                    )
                    metrics = wf.get("metrics") or {}
                    table.add_row(
                        str(wf.get("id")),
                        str(wf.get("status")),
                        task_desc[:50],
                        f"${float(metrics.get('total_cost_usd') or 0):.4f}",
                        str(wf.get("created_at")),
                    )
                console.print(table)
        finally:
            await engine.stop()

    _run_cli(_status())


@app.command(name="list")
def list_workflows() -> None:
    """List all workflows."""
    # Delegate to status without workflow_id
    status(workflow_id=None)


@app.command()
def approve(
    approval_id: str = typer.Argument(help="Approval ID"),
) -> None:
    """Approve a pending request."""

    async def _approve():
        from openhydra.hydra_compat import HydraCompatService

        engine = await _create_engine()
        api = HydraCompatService(engine)
        try:
            await api.approve_inbox_item(approval_id, {"decision": "approved"})
            console.print(f"[bold green]Approved:[/bold green] {approval_id}")
        finally:
            await engine.stop()

    _run_cli(_approve())


@app.command()
def reject(
    approval_id: str = typer.Argument(help="Approval ID"),
    reason: str = typer.Option("", help="Rejection reason"),
) -> None:
    """Reject a pending request."""

    async def _reject():
        from openhydra.hydra_compat import HydraCompatService

        engine = await _create_engine()
        api = HydraCompatService(engine)
        try:
            await api.reject_inbox_item(approval_id, reason)
            console.print(f"[bold red]Rejected:[/bold red] {approval_id}")
        finally:
            await engine.stop()

    _run_cli(_reject())


@app.command(name="pause")
def pause_workflow(
    workflow_id: str = typer.Argument(help="Workflow ID to pause"),
) -> None:
    """Pause a running workflow."""

    async def _pause():
        from openhydra.hydra_compat import HydraCompatService

        engine = await _create_engine()
        api = HydraCompatService(engine)
        try:
            result = await api.control_workflow(workflow_id, "pause")
            console.print(
                f"[bold yellow]Pause:[/bold yellow] {workflow_id} "
                f"({result.get('status', 'unknown')})"
            )
        finally:
            await engine.stop()

    _run_cli(_pause())


@app.command(name="resume")
def resume_workflow(
    workflow_id: str = typer.Argument(help="Workflow ID to resume"),
    watch: bool = typer.Option(False, "--watch", "-w", help="Stream progress events"),
) -> None:
    """Resume a paused workflow."""

    async def _resume():
        from openhydra.hydra_compat import HydraCompatService

        engine = await _create_engine()
        api = HydraCompatService(engine)
        try:
            if watch:
                from openhydra.events import Event

                async def on_event(event: Event) -> None:
                    console.print(f"  [{event.type}] {event.data}")

                engine.events.on_all(on_event)

            result = await api.control_workflow(workflow_id, "resume")
            console.print(
                f"[bold green]Resume:[/bold green] {workflow_id} "
                f"({result.get('status', 'unknown')})"
            )

            if watch:
                bg_task = engine._tasks.get(workflow_id)
                if bg_task:
                    await bg_task
                    wf = await api.get_workflow(workflow_id)
                    metrics = wf.get("metrics") or {}
                    console.print(f"\n[bold]Status:[/bold] {wf.get('status')}")
                    console.print(
                        f"[bold]Cost:[/bold] ${float(metrics.get('total_cost_usd') or 0):.4f}"
                    )
                    console.print(f"[bold]Tokens:[/bold] {int(metrics.get('total_tokens') or 0)}")
        finally:
            await engine.stop()

    _run_cli(_resume())


@app.command(name="cancel")
def cancel_workflow(
    workflow_id: str = typer.Argument(help="Workflow ID to cancel"),
) -> None:
    """Cancel a running or paused workflow."""

    async def _cancel():
        from openhydra.hydra_compat import HydraCompatService

        engine = await _create_engine()
        api = HydraCompatService(engine)
        try:
            result = await api.control_workflow(workflow_id, "cancel")
            console.print(
                f"[bold red]Cancel:[/bold red] {workflow_id} ({result.get('status', 'unknown')})"
            )
        finally:
            await engine.stop()

    _run_cli(_cancel())


@app.command()
def skills() -> None:
    """List available skills."""

    async def _skills():
        engine = await _create_engine()
        try:
            all_skills = await engine.skills.list_all()
            if not all_skills:
                console.print("[dim]No skills found.[/dim]")
                return

            table = Table(title="Available Skills")
            table.add_column("ID")
            table.add_column("Name")
            table.add_column("Tags")
            table.add_column("Priority")
            table.add_column("Tokens")

            for skill in all_skills:
                table.add_row(
                    skill.id,
                    skill.name,
                    ", ".join(skill.tags),
                    str(skill.priority),
                    str(skill.token_estimate),
                )
            console.print(table)
        finally:
            await engine.stop()

    _run_cli(_skills())


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", "--host", "-H", help="Bind host"),
    port: int = typer.Option(7070, "--port", "-p", help="Bind port"),
    heartbeat: bool = typer.Option(False, "--heartbeat", help="Enable heartbeat runner"),
    daemon: bool = typer.Option(False, "--daemon", "-d", help="Daemon mode with auto-restart"),
    max_restarts: int = typer.Option(5, "--max-restarts", help="Max restarts in daemon mode"),
) -> None:
    """Start the engine with all enabled channels (web, Slack, Discord, WhatsApp)."""
    import signal
    import sys

    async def _serve():
        from openhydra.channels.registry import ChannelRegistry
        from openhydra.config import ensure_api_key, load_config

        cfg = load_config()
        was_web_enabled = _configure_serve_for_web_clients(cfg, host=host, port=port)
        ensure_api_key(cfg)

        engine = await _create_engine()
        registry = ChannelRegistry(engine, cfg)
        heartbeat_runner = None

        stop_event = asyncio.Event()

        def _handle_signal(*_):
            stop_event.set()

        if sys.platform != "win32":
            loop = asyncio.get_event_loop()
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(sig, _handle_signal)
        else:
            # Windows: add_signal_handler is not supported; fall back to signal.signal
            signal.signal(signal.SIGINT, _handle_signal)
            signal.signal(signal.SIGBREAK, _handle_signal)

        try:
            await registry.start_all()
            if not was_web_enabled:
                console.print(
                    "[dim]Web channel was disabled in config; enabled for "
                    "`openhydra serve`.[/dim]"
                )
            channels = [ch.name for ch in registry.channels]
            names = ", ".join(channels) or "none"
            console.print(f"[bold green]OpenHydra serving[/bold green] — channels: {names}")

            # Start agenda runner (superset of heartbeat) if requested
            if heartbeat or cfg.heartbeat.enabled:
                from openhydra.agenda.runner import AgendaRunner

                cfg.heartbeat.enabled = True
                heartbeat_runner = AgendaRunner(
                    engine=engine,
                    db=engine.db,
                    config=cfg.heartbeat,
                    sessions=registry.session_store,
                    channels={ch.name: ch for ch in registry.channels},
                )
                await heartbeat_runner.start()
                console.print(
                    f"[bold green]Agenda runner enabled[/bold green] "
                    f"(interval={cfg.heartbeat.interval_seconds}s)"
                )

            console.print("[dim]Press Ctrl+C to stop[/dim]")
            await stop_event.wait()
        finally:
            console.print("\n[bold]Shutting down...[/bold]")
            if heartbeat_runner:
                await heartbeat_runner.stop()
            await registry.stop_all()
            await engine.stop()

    async def _serve_daemon():
        restarts = 0
        base_delay = 2.0
        while restarts < max_restarts:
            try:
                await _serve()
                break  # Clean exit
            except asyncio.CancelledError:
                break
            except Exception as e:
                restarts += 1
                delay = min(base_delay * (1.5 ** (restarts - 1)), 60.0)
                console.print(
                    f"[bold red]Crashed[/bold red] ({e}), "
                    f"restarting in {delay:.0f}s ({restarts}/{max_restarts})"
                )
                await asyncio.sleep(delay)

        if restarts >= max_restarts:
            console.print(f"[bold red]Max restarts ({max_restarts}) reached, exiting[/bold red]")

    if daemon:
        _run_cli(_serve_daemon())
    else:
        _run_cli(_serve())


# --- Skill review commands ---


@app.command(name="skill-review")
def skill_review() -> None:
    """List skills pending security review."""

    async def _review():
        engine = await _create_engine()
        try:
            pending = await engine.list_pending_skills()
            if not pending:
                console.print("[dim]No skills pending review.[/dim]")
                return

            table = Table(title="Pending Skill Reviews")
            table.add_column("Skill ID")
            table.add_column("Status")
            table.add_column("Path")
            table.add_column("Created")

            for skill in pending:
                table.add_row(
                    skill["skill_id"],
                    skill["status"],
                    skill.get("source_path", "")[:50],
                    str(skill.get("created_at", "")),
                )
            console.print(table)
        finally:
            await engine.stop()

    _run_cli(_review())


@app.command(name="skill-approve")
def skill_approve(
    skill_id: str = typer.Argument(help="Skill ID to approve"),
) -> None:
    """Approve a pending skill."""

    async def _approve():
        engine = await _create_engine()
        try:
            ok = await engine.approve_skill(skill_id)
            if ok:
                console.print(f"[bold green]Approved:[/bold green] {skill_id}")
            else:
                console.print(
                    f"[bold red]Failed:[/bold red] Skill '{skill_id}' not found or not pending.",
                )
        finally:
            await engine.stop()

    _run_cli(_approve())


@app.command(name="skill-reject")
def skill_reject(
    skill_id: str = typer.Argument(help="Skill ID to reject"),
) -> None:
    """Reject a pending skill."""

    async def _reject():
        engine = await _create_engine()
        try:
            ok = await engine.reject_skill(skill_id)
            if ok:
                console.print(f"[bold red]Rejected:[/bold red] {skill_id}")
            else:
                console.print(
                    f"[bold red]Failed:[/bold red] Skill '{skill_id}' not found or not pending.",
                )
        finally:
            await engine.stop()

    _run_cli(_reject())


@app.command(name="doctor")
def doctor(
    strict: bool = typer.Option(
        False,
        "--strict",
        help="Treat warnings as failures (exit code 1).",
    ),
) -> None:
    """Validate local setup and channel prerequisites."""
    from openhydra.config import load_config

    cfg = load_config()
    checks = _run_doctor(cfg)
    if not checks:
        console.print("[bold green]Doctor: no checks to run.[/bold green]")
        return

    table = Table(title="OpenHydra Doctor")
    table.add_column("Status")
    table.add_column("Check")
    table.add_column("Detail")
    table.add_column("Hint")

    status_style = {
        "ok": ("OK", "green"),
        "warn": ("WARN", "yellow"),
        "fail": ("FAIL", "red"),
    }
    fail_count = 0
    warn_count = 0
    ok_count = 0

    for check in checks:
        label, style = status_style[check.status]
        table.add_row(
            f"[{style}]{label}[/{style}]",
            escape(check.title),
            escape(check.detail),
            escape(check.hint),
        )
        if check.status == "fail":
            fail_count += 1
        elif check.status == "warn":
            warn_count += 1
        else:
            ok_count += 1

    console.print(table)
    console.print(
        f"[bold]Summary:[/bold] ok={ok_count} warn={warn_count} fail={fail_count} "
        f"(strict={'on' if strict else 'off'})"
    )

    if fail_count > 0 or (strict and warn_count > 0):
        raise typer.Exit(code=1)


# --- Auth commands ---

auth_app = typer.Typer(name="auth", help="Manage channel authorization.")
app.add_typer(auth_app)

agent_app = typer.Typer(name="agent", help="Manage role agents.")
app.add_typer(agent_app)


@auth_app.command(name="confirm")
def auth_confirm(
    code: str = typer.Argument(help="6-character auth code"),
) -> None:
    """Confirm an auth challenge code to authorize a user."""

    async def _confirm():
        engine = await _create_engine()
        try:
            from openhydra.channels.auth.manager import AuthManager
            from openhydra.channels.auth.store import AuthStore

            store = AuthStore(engine.db)
            manager = AuthManager(store, engine.events)
            ok = await manager.confirm_challenge(code)
            if ok:
                console.print(f"[bold green]Authorized![/bold green] Code {code} confirmed.")
            else:
                console.print("[bold red]Failed:[/bold red] Invalid or expired code.")
        finally:
            await engine.stop()

    _run_cli(_confirm())


@auth_app.command(name="list")
def auth_list() -> None:
    """List authorized identities."""

    async def _list():
        engine = await _create_engine()
        try:
            from openhydra.channels.auth.store import AuthStore

            store = AuthStore(engine.db)
            identities = await store.list_identities()
            if not identities:
                console.print("[dim]No authorized identities.[/dim]")
                return

            table = Table(title="Authorized Identities")
            table.add_column("Key")
            table.add_column("Channel")
            table.add_column("User ID")
            table.add_column("Name")
            table.add_column("Via")

            for ident in identities:
                table.add_row(
                    ident.identity_key,
                    ident.channel,
                    ident.user_id,
                    ident.user_name,
                    ident.authorized_via,
                )
            console.print(table)
        finally:
            await engine.stop()

    _run_cli(_list())


@auth_app.command(name="add")
def auth_add(
    identity: str = typer.Argument(help="Identity in channel:user_id format"),
    name: str = typer.Option("", "--name", "-n", help="Display name"),
) -> None:
    """Manually authorize a user (skip challenge)."""

    async def _add():
        parts = identity.split(":", 1)
        if len(parts) != 2:
            console.print("[bold red]Error:[/bold red] Use format channel:user_id")
            raise typer.Exit(1)

        engine = await _create_engine()
        try:
            from openhydra.channels.auth.store import AuthStore

            store = AuthStore(engine.db)
            await store.authorize(parts[0], parts[1], user_name=name, via="manual")
            console.print(f"[bold green]Authorized:[/bold green] {identity}")
        finally:
            await engine.stop()

    _run_cli(_add())


@auth_app.command(name="revoke")
def auth_revoke(
    identity: str = typer.Argument(help="Identity in channel:user_id format"),
) -> None:
    """Revoke a user's authorization."""

    async def _revoke():
        parts = identity.split(":", 1)
        if len(parts) != 2:
            console.print("[bold red]Error:[/bold red] Use format channel:user_id")
            raise typer.Exit(1)

        engine = await _create_engine()
        try:
            from openhydra.channels.auth.store import AuthStore

            store = AuthStore(engine.db)
            revoked = await store.revoke(parts[0], parts[1])
            if revoked:
                console.print(f"[bold red]Revoked:[/bold red] {identity}")
            else:
                console.print(f"[bold red]Not found:[/bold red] {identity}")
        finally:
            await engine.stop()

    _run_cli(_revoke())


@agent_app.command(name="scaffold")
def scaffold_agent(
    role_id: str | None = typer.Argument(None, help="Role ID to create, e.g. eng.docs"),
    roles_file: Path = typer.Option(
        Path("config/roles.yaml"),
        "--roles-file",
        "-f",
        help="Path to roles.yaml.",
    ),
    name: str | None = typer.Option(None, "--name", help="Role display name."),
    description: str = typer.Option(
        DEFAULT_ROLE_DESCRIPTION,
        "--description",
        help="Role description.",
    ),
    objectives: list[str] | None = typer.Option(
        None,
        "--objective",
        "-o",
        help="Role objective. Repeat to add more.",
    ),
    provider: str | None = typer.Option(
        None,
        "--provider",
        help="Agent provider name. Omit to use global default provider.",
    ),
    model: str = typer.Option(
        "claude-sonnet-4-5-20250929",
        "--model",
        help="Model to use for this role.",
    ),
    skill_packs: list[str] | None = typer.Option(
        None,
        "--skill-pack",
        "-s",
        help="Skill pack id. Repeat to add more.",
    ),
    tools: list[str] | None = typer.Option(
        None,
        "--tool",
        "-t",
        help="Allowed tool name. Repeat to add more.",
    ),
    context_reads: list[str] | None = typer.Option(
        None,
        "--context-read",
        "-c",
        help="Context/data source this role can read. Repeat to add more.",
    ),
    output_schema: str | None = typer.Option(
        None,
        "--output-schema",
        help="Optional output schema name from schemas/<name>.json.",
    ),
    quality_threshold: int | None = typer.Option(
        None,
        "--quality-threshold",
        min=1,
        max=40,
        help="If set, adds a quality gate with this threshold.",
    ),
    tests_gate: bool = typer.Option(
        False,
        "--tests-gate",
        help="Add a tests_pass gate.",
    ),
    approval_gate: bool = typer.Option(
        False,
        "--approval-gate",
        help="Add an approval gate.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Overwrite an existing role if the id already exists.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Print generated YAML without writing to disk.",
    ),
    interactive: bool = typer.Option(
        False,
        "--interactive",
        "-i",
        help="Prompt for role fields interactively.",
    ),
) -> None:
    """Scaffold a new role agent entry in roles.yaml."""
    doc, roles = _load_roles_document(roles_file)

    if interactive and not role_id:
        role_id = _prompt_text("Role ID (example: eng.docs)", required=True)
    if not role_id:
        console.print(
            "[bold red]Error:[/bold red] "
            "Role ID is required unless --interactive is set."
        )
        raise typer.Exit(code=1)

    if role_id in roles and not force:
        console.print(
            f"[bold red]Error:[/bold red] Role '{role_id}' already exists in {roles_file}. "
            "Use --force to overwrite."
        )
        raise typer.Exit(code=1)

    generated_name = name or _humanize_role_id(role_id)
    generated_description = description
    generated_objectives = objectives or []
    generated_tools = tools or list(DEFAULT_ROLE_TOOLS)
    generated_skill_packs = skill_packs or []
    generated_context_reads = context_reads or []

    if interactive:
        generated_name = _prompt_text(
            "Agent name",
            default=generated_name,
        )
        description_default = (
            generated_description if generated_description != DEFAULT_ROLE_DESCRIPTION else ""
        )
        generated_description = _prompt_text(
            "Agent description",
            default=description_default,
        ) or DEFAULT_ROLE_DESCRIPTION
        generated_objectives = _prompt_csv(
            "Agent goals/objectives (comma-separated)",
            default=generated_objectives,
        )
        generated_skill_packs = _prompt_csv(
            "Skills / skill packs (comma-separated)",
            default=generated_skill_packs,
        )
        generated_tools = _prompt_csv(
            "Tools this agent can access (comma-separated)",
            default=generated_tools,
        )
        generated_context_reads = _prompt_csv(
            "Context / data this agent can read (comma-separated)",
            default=generated_context_reads,
        )

    gates: list[dict[str, str | int]] = []
    if quality_threshold is not None:
        gates.append({"type": "quality", "threshold": quality_threshold})
    if tests_gate:
        gates.append({"type": "tests_pass"})
    if approval_gate:
        gates.append({"type": "approval"})

    role_payload: dict[str, object] = {
        "name": generated_name,
        "description": generated_description,
        "model": model,
        "skill_packs": generated_skill_packs,
        "allowed_tools": generated_tools,
        "budget": {
            "max_tokens": 100_000,
            "max_tool_calls": 200,
            "max_duration_minutes": 30,
        },
        "context_budget": {
            "skills_pct": 35,
            "memory_pct": 10,
            "reasoning_pct": 55,
        },
    }
    if generated_objectives:
        role_payload["objectives"] = generated_objectives
    if generated_context_reads:
        role_payload["context_reads"] = generated_context_reads
    if provider:
        role_payload["provider"] = provider
    if output_schema:
        role_payload["output_schema"] = output_schema
    if gates:
        role_payload["gates"] = gates

    if dry_run:
        preview = yaml.safe_dump({"roles": {role_id: role_payload}}, sort_keys=False).rstrip()
        console.print(preview)
        return

    roles[role_id] = role_payload
    doc["roles"] = roles
    roles_file.parent.mkdir(parents=True, exist_ok=True)
    roles_file.write_text(yaml.safe_dump(doc, sort_keys=False))
    console.print(f"[bold green]Scaffolded role:[/bold green] {role_id}")
    console.print(f"[dim]Updated {roles_file}[/dim]")


@app.command()
def config() -> None:
    """Show current configuration."""
    from openhydra.config import load_config

    cfg = load_config()
    console.print("[bold]Engine[/bold]")
    console.print(f"  State dir: {cfg.engine.state_dir}")
    console.print(f"  Max concurrent: {cfg.engine.max_concurrent_sessions}")
    console.print(f"  Max retries: {cfg.engine.max_retries_per_step}")
    console.print("\n[bold]Agents[/bold]")
    console.print(f"  Default provider: {cfg.agents.default_provider}")
    console.print("\n[bold]Memory[/bold]")
    console.print(f"  Backend: {cfg.memory.backend}")
    console.print(f"  Embeddings: {cfg.memory.embedding_provider}")
    console.print("\n[bold]Skills[/bold]")
    for src in cfg.skills.sources:
        console.print(f"  Source: {src.type} ({src.path or src.url})")
    console.print(f"  Builder enabled: {cfg.skills.builder_enabled}")
    console.print(f"  Max skills per role: {cfg.skills.max_skills_per_role}")
    console.print(f"  Builder quality threshold: {cfg.skills.builder_quality_threshold}")
    if cfg.tools.mcp_servers:
        console.print("\n[bold]MCP Servers[/bold]")
        for srv in cfg.tools.mcp_servers:
            console.print(f"  {srv.name}: {srv.transport} ({srv.command or srv.url})")


@app.command(name="init")
def init_config(
    quick: bool = typer.Option(
        False,
        "--quick",
        help="Quick setup with detected defaults and fewer prompts.",
    ),
) -> None:
    """Interactive setup wizard — configure providers, tools, and API keys."""
    from openhydra.cli.init_wizard import run_init_wizard

    run_init_wizard(quick=quick)


@app.command(name="onboard")
def onboard_config(
    full: bool = typer.Option(
        False,
        "--full",
        help="Run the full interactive setup instead of quick mode.",
    ),
) -> None:
    """Recommended onboarding flow. Quick mode by default."""
    from openhydra.cli.init_wizard import run_init_wizard

    run_init_wizard(quick=not full)


if __name__ == "__main__":
    app()
