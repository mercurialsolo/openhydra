"""Main engine — ties together all components."""

from __future__ import annotations

from pathlib import Path

from .agents.registry import AgentRegistry
from .config import OpenHydraConfig, load_config
from .db import Database
from .events import EventBus
from .memory.base import MemoryStore
from .skills.registry import SkillRegistry


class Engine:
    """OpenHydra engine — single entry point for all operations."""

    def __init__(self, config: OpenHydraConfig | None = None) -> None:
        self.config = config or load_config()
        self.events = EventBus()
        self.agents = AgentRegistry()
        self.skills = SkillRegistry()
        self.memory: MemoryStore | None = None
        self.db = Database(self.config.engine.state_dir / "openhydra.db")

    async def start(self) -> None:
        """Initialize all components and start the engine."""
        # Ensure state directory exists
        self.config.engine.state_dir.mkdir(parents=True, exist_ok=True)

        # Connect database
        await self.db.connect()

        # Initialize memory backend
        # TODO: Create memory backend based on config

        # Initialize skill sources
        # TODO: Create skill sources based on config

        # Initialize agent providers
        # TODO: Create providers based on config

    async def stop(self) -> None:
        """Shut down the engine gracefully."""
        await self.db.close()

    async def submit(self, task: str) -> str:
        """Submit a task for execution. Returns workflow ID."""
        # TODO: Create workflow, trigger planning
        raise NotImplementedError

    async def get_status(self, workflow_id: str) -> dict:
        """Get current status of a workflow."""
        # TODO: Query workflow state
        raise NotImplementedError

    async def list_workflows(self) -> list[dict]:
        """List all workflows."""
        # TODO: Query all workflows
        raise NotImplementedError

    async def approve(self, approval_id: str) -> None:
        """Approve a pending request."""
        # TODO: Signal approval
        raise NotImplementedError

    async def reject(self, approval_id: str, reason: str = "") -> None:
        """Reject a pending request."""
        # TODO: Signal rejection
        raise NotImplementedError
