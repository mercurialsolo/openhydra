"""OpenHydra CLI — lightweight multi-agent orchestration."""

from __future__ import annotations

import typer
from rich.console import Console

app = typer.Typer(
    name="openhydra",
    help="Lightweight local-first multi-agent orchestration.",
    no_args_is_help=True,
)
console = Console()


@app.command()
def start(
    foreground: bool = typer.Option(True, help="Run in foreground (default)"),
    port: int = typer.Option(7070, help="Web server port"),
) -> None:
    """Start the OpenHydra engine."""
    console.print("[bold]OpenHydra[/bold] starting...", style="green")
    console.print(f"  State dir: ~/.openhydra/")
    console.print(f"  Web UI: http://127.0.0.1:{port}")
    # TODO: Wire up engine startup


@app.command()
def run(
    task: str = typer.Argument(help="Task description"),
    watch: bool = typer.Option(False, "--watch", "-w", help="Stream progress"),
) -> None:
    """Submit a task for multi-agent execution."""
    console.print(f"[bold]Submitting:[/bold] {task}")
    # TODO: Wire up engine.submit()


@app.command()
def status(
    workflow_id: str = typer.Argument(None, help="Workflow ID (optional)"),
) -> None:
    """Show workflow status."""
    if workflow_id:
        console.print(f"Status for workflow: {workflow_id}")
    else:
        console.print("All workflows:")
    # TODO: Wire up engine.status()


@app.command(name="list")
def list_workflows() -> None:
    """List all workflows."""
    console.print("Workflows:")
    # TODO: Wire up engine.list()


@app.command()
def approve(
    approval_id: str = typer.Argument(help="Approval ID"),
) -> None:
    """Approve a pending request."""
    console.print(f"Approved: {approval_id}")
    # TODO: Wire up engine.approve()


@app.command()
def reject(
    approval_id: str = typer.Argument(help="Approval ID"),
    reason: str = typer.Option("", help="Rejection reason"),
) -> None:
    """Reject a pending request."""
    console.print(f"Rejected: {approval_id}")
    # TODO: Wire up engine.reject()


@app.command()
def skills() -> None:
    """List available skills."""
    console.print("Available skills:")
    # TODO: Wire up skill registry


@app.command()
def config() -> None:
    """Show current configuration."""
    console.print("Configuration:")
    # TODO: Wire up config display


if __name__ == "__main__":
    app()
