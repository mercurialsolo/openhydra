"""Shared workspace — per-workflow artifact directory."""

from __future__ import annotations

import hashlib
from pathlib import Path

from ..events import ARTIFACT_CREATED, ARTIFACT_MODIFIED, Event, EventBus


class Workspace:
    """Manages a per-workflow artifact directory.

    All agents in a workflow share the same workspace directory.
    Artifacts are tracked by hash for change detection.
    """

    def __init__(self, workflow_id: str, base_dir: Path, events: EventBus) -> None:
        self.workflow_id = workflow_id
        self.path = base_dir / "workspaces" / workflow_id
        self._events = events
        self._artifacts: dict[str, str] = {}  # relative path -> hash
        self.path.mkdir(parents=True, exist_ok=True)

    def register_artifact(
        self, relative_path: str, content: bytes | None = None
    ) -> str:
        """Register or update an artifact. Returns its hash.

        If content is None, reads from the file on disk.
        """
        full_path = self.path / relative_path
        if content is not None:
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_bytes(content)

        if not full_path.exists():
            raise FileNotFoundError(f"Artifact not found: {relative_path}")

        file_hash = hashlib.sha256(full_path.read_bytes()).hexdigest()[:16]
        self._artifacts[relative_path] = file_hash
        return file_hash

    async def register_artifact_async(
        self, relative_path: str, content: bytes | None = None
    ) -> str:
        """Async version that also emits events."""
        previously_known = relative_path in self._artifacts
        file_hash = self.register_artifact(relative_path, content)

        event_type = ARTIFACT_MODIFIED if previously_known else ARTIFACT_CREATED
        await self._events.emit(Event(
            type=event_type,
            data={
                "workflow_id": self.workflow_id,
                "path": relative_path,
                "hash": file_hash,
            },
        ))
        return file_hash

    def list_artifacts(self) -> dict[str, str]:
        """Return all tracked artifacts and their hashes."""
        return dict(self._artifacts)
