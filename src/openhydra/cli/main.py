"""OpenHydra CLI — lightweight multi-agent orchestration."""

from __future__ import annotations

import asyncio

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(
    name="openhydra",
    help="Lightweight local-first multi-agent orchestration.",
    no_args_is_help=True,
)
console = Console()


def _run_async(coro):
    """Bridge sync typer with async engine."""
    return asyncio.run(coro)


async def _create_engine():
    """Create and start an Engine instance."""
    from openhydra.engine import Engine

    engine = Engine()
    await engine.start()
    return engine


@app.command()
def run(
    task: str = typer.Argument(help="Task description"),
    watch: bool = typer.Option(False, "--watch", "-w", help="Stream progress events"),
) -> None:
    """Submit a task for multi-agent execution."""

    async def _run():
        engine = await _create_engine()
        try:
            if watch:
                from openhydra.events import Event

                async def on_event(event: Event) -> None:
                    console.print(f"  [{event.type}] {event.data}")

                engine.events.on_all(on_event)

            console.print(f"[bold]Submitting:[/bold] {task}")
            workflow_id = await engine.submit(task)
            console.print(f"[bold green]Workflow created:[/bold green] {workflow_id}")

            if watch:
                # Wait for workflow to complete
                bg_task = engine._tasks.get(workflow_id)
                if bg_task:
                    await bg_task
                    wf = await engine.get_status(workflow_id)
                    console.print(f"\n[bold]Status:[/bold] {wf['status']}")
                    console.print(f"[bold]Cost:[/bold] ${wf['total_cost_usd']:.4f}")
                    console.print(f"[bold]Tokens:[/bold] {wf['total_tokens']}")
        finally:
            await engine.stop()

    _run_async(_run())


@app.command()
def status(
    workflow_id: str = typer.Argument(None, help="Workflow ID (optional)"),
) -> None:
    """Show workflow status."""

    async def _status():
        engine = await _create_engine()
        try:
            if workflow_id:
                wf = await engine.get_status(workflow_id)
                console.print(f"\n[bold]Workflow:[/bold] {wf['id']}")
                console.print(f"[bold]Status:[/bold] {wf['status']}")
                console.print(f"[bold]Task:[/bold] {wf['input']}")
                console.print(f"[bold]Cost:[/bold] ${wf['total_cost_usd']:.4f}")
                console.print(f"[bold]Tokens:[/bold] {wf['total_tokens']}")

                if wf.get("steps"):
                    table = Table(title="Steps")
                    table.add_column("#", style="dim")
                    table.add_column("Role")
                    table.add_column("Status")
                    table.add_column("Cost")

                    for step in wf["steps"]:
                        status_style = {
                            "completed": "green",
                            "running": "yellow",
                            "failed": "red",
                            "pending": "dim",
                        }.get(step["status"], "")
                        table.add_row(
                            str(step["ordinal"]),
                            step["role_id"],
                            f"[{status_style}]{step['status']}[/{status_style}]",
                            f"${step['cost_usd']:.4f}",
                        )
                    console.print(table)
            else:
                workflows = await engine.list_workflows()
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
                    table.add_row(
                        wf["id"],
                        wf["status"],
                        wf["input"][:50],
                        f"${wf['total_cost_usd']:.4f}",
                        str(wf["created_at"]),
                    )
                console.print(table)
        finally:
            await engine.stop()

    _run_async(_status())


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
        engine = await _create_engine()
        try:
            await engine.approve(approval_id)
            console.print(f"[bold green]Approved:[/bold green] {approval_id}")
        finally:
            await engine.stop()

    _run_async(_approve())


@app.command()
def reject(
    approval_id: str = typer.Argument(help="Approval ID"),
    reason: str = typer.Option("", help="Rejection reason"),
) -> None:
    """Reject a pending request."""

    async def _reject():
        engine = await _create_engine()
        try:
            await engine.reject(approval_id, reason)
            console.print(f"[bold red]Rejected:[/bold red] {approval_id}")
        finally:
            await engine.stop()

    _run_async(_reject())


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

    _run_async(_skills())


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

    async def _serve():
        from openhydra.channels.registry import ChannelRegistry
        from openhydra.config import load_config

        cfg = load_config()
        cfg.web.host = host
        cfg.web.port = port

        engine = await _create_engine()
        registry = ChannelRegistry(engine, cfg)
        heartbeat_runner = None

        stop_event = asyncio.Event()

        def _handle_signal(*_):
            stop_event.set()

        loop = asyncio.get_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, _handle_signal)

        try:
            await registry.start_all()
            channels = [ch.name for ch in registry.channels]
            names = ", ".join(channels) or "none"
            console.print(f"[bold green]OpenHydra serving[/bold green] — channels: {names}")

            # Start heartbeat if requested
            if heartbeat or cfg.heartbeat.enabled:
                from openhydra.heartbeat.runner import HeartbeatRunner

                cfg.heartbeat.enabled = True
                heartbeat_runner = HeartbeatRunner(
                    engine=engine,
                    db=engine.db,
                    config=cfg.heartbeat,
                    sessions=registry.session_store,
                    channels={ch.name: ch for ch in registry.channels},
                )
                await heartbeat_runner.start()
                console.print(
                    f"[bold green]Heartbeat enabled[/bold green] "
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
        _run_async(_serve_daemon())
    else:
        _run_async(_serve())


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
    if cfg.tools.mcp_servers:
        console.print("\n[bold]MCP Servers[/bold]")
        for srv in cfg.tools.mcp_servers:
            console.print(f"  {srv.name}: {srv.transport} ({srv.command or srv.url})")


if __name__ == "__main__":
    app()
