"""OpenHydra framework adapter: the real implementation under test.

v1.1 (2026-10-28). The v1 adapter's ``kill_workflow`` called
``engine.pause_workflow``: a cooperative, in-process pause that killed nothing,
and the mock executor returned instantly, so every "crash" scenario scored 100
without interrupting anything (see talks/.../RESULTS.md, diagnostic section).

What changed, and what each change is and is not:

* ``kill_workflow`` now cancels the in-flight execution task and **discards the
  engine object**, building a fresh ``WorkflowEngine`` over the same SQLite
  database, event bus and mailbox. Everything the old engine held in memory
  (pause flags, cached configs, workspace handles) is gone; only what was
  written to the database survives. That is what process death does to this
  engine. It is NOT a SIGKILL of a separate process; call it "simulated process
  death, in-memory state discarded, DB kept".
* The mock executor sleeps ``mock_step_seconds`` per step (default 0.1 s) so a
  step is in flight when the kill lands, and charges ``step_cost_usd`` per step
  (default $0.01) so a scenario can set a cost that reaches its cap. Both are
  read from the workflow config the scenario passes to ``create_workflow``.
* ``submit_via_channel`` caches one ``RestrictedEngine`` proxy per channel name,
  so the sliding-window rate limiter is actually exercised (v1 rebuilt the
  proxy, and its window, on every call).
* ``read_artifact`` reads from the workspace directory on disk, rebuilding the
  ``Workspace`` handle if the engine lost it, so hr-2 tests disk durability
  rather than a dict.
* ``get_accumulated_cost`` sums the persisted per-step cost rows. The engine
  only writes ``workflows.total_cost_usd`` at completion, so after a crash the
  per-step rows are the accumulator that survived.

Nothing in the engine was changed for this version. Where the engine cannot
recover (a step left RUNNING is never re-queued; ``resume_workflow`` refuses a
workflow that is not PAUSED), the scenario scores what the engine does.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

from .base import FrameworkAdapter, FrameworkCapabilities

logger = logging.getLogger(__name__)

DEFAULT_STEP_SECONDS = 0.1
DEFAULT_STEP_COST_USD = 0.01


class MockRoleExecutor:
    """Deterministic stand-in for the LLM-backed RoleExecutor.

    Reads two knobs from the workflow config the engine injects into the step
    context: ``mock_step_seconds`` (how long a step takes) and
    ``step_cost_usd`` (what a step costs). No network, no model.
    """

    tool_executor = None
    memory = None

    def __init__(self) -> None:
        self.calls = 0

    async def execute(
        self,
        role_id: str,
        instructions: str,
        context: dict[str, Any] | None = None,
        messages: list[dict[str, str]] | None = None,
        store_memory: bool = False,
        **_: Any,
    ) -> Any:
        from openhydra.agents.base import SessionResult

        cfg = (context or {}).get("workflow_config") or {}
        seconds = float(cfg.get("mock_step_seconds", DEFAULT_STEP_SECONDS))
        cost = float(cfg.get("step_cost_usd", DEFAULT_STEP_COST_USD))
        self.calls += 1
        if seconds > 0:
            await asyncio.sleep(seconds)
        return SessionResult(
            output={"text": "mock output", "quality_score": 30},
            raw_text="mock output",
            tokens_used=100,
            cost_usd=cost,
        )

    async def store_retry_lesson(self, **_: Any) -> None:
        return None


class OpenHydraAdapter(FrameworkAdapter):
    """Adapter that uses real OpenHydra primitives.

    Real SQLite database, event bus, mailbox, workspace, filesystem router and
    channel proxy; a mock in place of the LLM.
    """

    def __init__(self) -> None:
        self._db = None
        self._events = None
        self._engine = None
        self._roles = None
        self._mailbox = None
        self._tmp_dir: Path | None = None
        self._filesystem_router = None
        self._executor: MockRoleExecutor | None = None
        self._exec_tasks: dict[str, asyncio.Task] = {}
        self._proxies: dict[str, Any] = {}
        self.kills = 0
        # When True, a refused resume falls back to the engine's
        # recover_workflow (v1.2). False measures the engine as it was.
        self.use_recovery = os.environ.get("HYDRABENCH_RECOVERY", "1") != "0"

    @property
    def name(self) -> str:
        return "OpenHydra"

    @property
    def capabilities(self) -> FrameworkCapabilities:
        return FrameworkCapabilities(
            crash_recovery=True,
            secret_stripping=True,
            durable_mailbox=True,
            durable_workspace=True,
            channel_permissions=True,
            rate_limiting=True,
            budget_gates=True,
            step_timeout=True,
            cost_attribution=True,
        )

    # -- lifecycle -----------------------------------------------------------

    async def setup(self) -> None:
        import tempfile
        from openhydra.db import Database
        from openhydra.events import EventBus
        from openhydra.roles.catalog import RoleCatalog
        from openhydra.workflow.mailbox import Mailbox
        from openhydra.tools.filesystem import FilesystemToolRouter

        self._tmp_dir = Path(tempfile.mkdtemp(prefix="hydrabench-"))
        self._db = Database(self._tmp_dir / "bench.db")
        await self._db.connect()

        self._events = EventBus()

        config_path = Path(__file__).parent.parent.parent.parent / "config" / "agents.yaml"
        self._roles = RoleCatalog()
        if config_path.exists():
            self._roles.load(config_path)

        self._mailbox = Mailbox(db=self._db, events=self._events)
        self._executor = MockRoleExecutor()
        self._engine = self._new_engine()

        self._filesystem_router = FilesystemToolRouter(
            cwd=self._tmp_dir, restrict_to_cwd=True,
        )

    def _new_engine(self) -> Any:
        """A fresh engine over the same database: what a restarted process gets."""
        from openhydra.workflow.engine import WorkflowEngine

        return WorkflowEngine(
            db=self._db,
            events=self._events,
            role_executor=self._executor,
            roles=self._roles,
            max_retries=2,
            max_concurrent=4,
            mailbox=self._mailbox,
            base_dir=self._tmp_dir,
        )

    async def teardown(self) -> None:
        for task in list(self._exec_tasks.values()):
            task.cancel()
        if self._db:
            await self._db.close()
        if self._tmp_dir and self._tmp_dir.exists():
            import shutil
            shutil.rmtree(self._tmp_dir, ignore_errors=True)

    # -- workflows -----------------------------------------------------------

    async def create_workflow(
        self, steps: list[dict[str, Any]], config: dict[str, Any] | None = None,
    ) -> str:
        from openhydra.workflow.models import Step

        oh_steps = []
        for s in steps:
            oh_steps.append(Step(
                role_id=s.get("role_id", "planner"),
                instructions=s.get("instructions", ""),
                depends_on=s.get("depends_on", []),
            ))

        return await self._engine.create_workflow(
            task="benchmark-task",
            steps=oh_steps,
            config=config,
        )

    async def execute_workflow(self, workflow_id: str) -> dict[str, Any]:
        task = asyncio.create_task(self._engine.execute_workflow(workflow_id))
        self._exec_tasks[workflow_id] = task
        try:
            await task
        finally:
            if self._exec_tasks.get(workflow_id) is task:
                self._exec_tasks.pop(workflow_id, None)
        return await self._engine.get_workflow(workflow_id)

    async def kill_workflow(self, workflow_id: str) -> None:
        """Simulated process death: cancel execution, discard the engine object.

        The database file, the event bus and the mailbox object are kept (they
        are the durable layer). Every piece of engine state held in memory is
        dropped, exactly as it would be if the process had died.
        """
        self.kills += 1
        task = self._exec_tasks.pop(workflow_id, None)
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        self._engine = self._new_engine()

    async def resume_workflow(self, workflow_id: str) -> dict[str, Any]:
        """Resume through the engine's own resume path. If the engine refuses
        (it only resumes PAUSED workflows), that refusal is the measurement."""
        try:
            try:
                task = await self._engine.resume_workflow(workflow_id)
            except ValueError as refused:
                # The engine only resumes PAUSED workflows. A crashed one is
                # still EXECUTING in the database. If the engine has a recovery
                # path (added 2026-10-28), a restarted process would use it;
                # if not, the refusal is the measurement.
                recover = getattr(self._engine, "recover_workflow", None)
                if recover is None or not self.use_recovery:
                    raise refused
                logger.debug("resume refused for %s (%s); recovering", workflow_id, refused)
                task = await recover(workflow_id)
            self._exec_tasks[workflow_id] = task
            await asyncio.wait_for(task, timeout=10.0)
        except ValueError as e:
            logger.debug("resume refused for %s: %s", workflow_id, e)
        except (asyncio.TimeoutError, Exception) as e:  # noqa: BLE001
            logger.debug("resume of %s ended with %s", workflow_id, e)
        finally:
            self._exec_tasks.pop(workflow_id, None)
        return await self._engine.get_workflow(workflow_id)

    async def get_workflow_status(self, workflow_id: str) -> dict[str, Any]:
        return await self._engine.get_workflow(workflow_id)

    # -- tools, mail, artifacts ---------------------------------------------

    async def execute_tool(self, tool_name: str, args: dict[str, Any]) -> str:
        if self._filesystem_router and self._filesystem_router.has_tool(tool_name):
            return await self._filesystem_router.execute(tool_name, args)
        return f"Error: Tool {tool_name} not available"

    async def send_message(
        self, workflow_id: str, from_step: str, to_step: str, body: str,
    ) -> str | None:
        if self._mailbox:
            return await self._mailbox.send(
                workflow_id, from_step, to_step, "bench-msg", body,
            )
        return None

    async def receive_messages(
        self, workflow_id: str, step_id: str,
    ) -> list[dict[str, str]]:
        if not self._mailbox:
            return []
        messages = await self._mailbox.receive(workflow_id, step_id)
        return [
            {"from": m.from_step, "body": m.body, "subject": m.subject}
            for m in messages
        ]

    def _workspace(self, workflow_id: str) -> Any:
        from openhydra.workflow.workspace import Workspace

        ws = self._engine._workspaces.get(workflow_id)
        if not ws:
            ws = Workspace(workflow_id, self._tmp_dir, self._events)
            self._engine._workspaces[workflow_id] = ws
        return ws

    async def register_artifact(
        self, workflow_id: str, name: str, content: bytes,
    ) -> str | None:
        return self._workspace(workflow_id).register_artifact(name, content)

    async def read_artifact(
        self, workflow_id: str, name: str,
    ) -> bytes | None:
        # Read from disk, through a handle rebuilt from base_dir if the engine
        # lost its own: the directory is the durable thing, not the dict.
        artifact_path = self._tmp_dir / "workspaces" / workflow_id / name
        if artifact_path.exists():
            return artifact_path.read_bytes()
        return None

    # -- channels ------------------------------------------------------------

    def _proxy(self, channel_name: str, permissions: dict[str, Any]) -> Any:
        from openhydra.channels.permissions import ChannelPermissions
        from openhydra.channels.restricted_engine import RestrictedEngine

        proxy = self._proxies.get(channel_name)
        if proxy is None:
            mock_engine = AsyncMock()
            mock_engine.submit = AsyncMock(return_value="wf-bench")
            mock_engine.events = self._events
            mock_engine.db = self._db
            mock_engine.config = AsyncMock()
            perms = ChannelPermissions(**{
                k: v for k, v in permissions.items()
                if hasattr(ChannelPermissions, k)
            })
            proxy = RestrictedEngine(mock_engine, perms, channel_name)
            self._proxies[channel_name] = proxy
        return proxy

    async def submit_via_channel(
        self, channel_name: str, task: str, permissions: dict[str, Any],
    ) -> str | dict[str, Any]:
        proxy = self._proxy(channel_name, permissions)
        try:
            if "__access_db__" in task:
                _ = proxy.db
                return "db_accessed"
            elif "__emit_event__" in task:
                from openhydra.events import Event
                await proxy.events.emit(Event(type="test", data={}))
                return "event_emitted"
            elif "__access_" in task:
                attr = task.replace("__access_", "").replace("__", "")
                _ = getattr(proxy, attr)
                return f"{attr}_accessed"
            else:
                return await proxy.submit(task)
        except PermissionError as e:
            return {"error": str(e)}

    # -- cost ----------------------------------------------------------------

    async def get_accumulated_cost(self, workflow_id: str) -> float:
        try:
            wf = await self._engine.get_workflow(workflow_id)
        except Exception:
            return 0.0
        return float(sum((s.get("cost_usd") or 0) for s in wf.get("steps", [])))
