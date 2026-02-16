"""Main engine — ties together all components."""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any

from .agents.registry import AgentRegistry
from .config import OpenHydraConfig, load_config
from .db import Database
from .events import EventBus
from .gates.base import Gate
from .memory.base import MemoryStore
from .roles.catalog import RoleCatalog
from .roles.executor import RoleExecutor
from .skills.registry import SkillRegistry
from .tools.executor import ToolExecutor
from .workflow.engine import WorkflowEngine
from .workflow.mailbox import Mailbox
from .workflow.planner import Planner

logger = logging.getLogger(__name__)


class Engine:
    """OpenHydra engine — single entry point for all operations."""

    def __init__(self, config: OpenHydraConfig | None = None) -> None:
        self.config = config or load_config()
        self.events = EventBus()
        self.agents = AgentRegistry()
        self.skills = SkillRegistry()
        self.memory: MemoryStore | None = None
        self.db = Database(self.config.engine.state_dir / "openhydra.db")
        self.roles = RoleCatalog()
        self.tool_executor = ToolExecutor()
        self.role_executor: RoleExecutor | None = None
        self.workflow_engine: WorkflowEngine | None = None
        self.planner: Planner | None = None
        self._tasks: dict[str, asyncio.Task] = {}

    async def start(self) -> None:
        """Initialize all components and start the engine."""
        # Ensure state directory exists
        self.config.engine.state_dir.mkdir(parents=True, exist_ok=True)

        # Connect database
        await self.db.connect()

        # Load roles from config/roles.yaml
        self._load_roles()

        # Initialize memory backend
        self._init_memory()

        # Connect memory store if it requires async init (e.g. SQLite)
        if self.memory and hasattr(self.memory, "connect"):
            await self.memory.connect()

        # Initialize skill sources
        self._init_skills()

        # Resolve MCP templates into concrete server configs
        self._resolve_mcp_templates()

        # Initialize agent providers (lazy imports — missing deps don't crash)
        self._init_providers()

        # Initialize filesystem tools for Anthropic API fallback
        self._init_filesystem_tools()

        # Initialize MCP clients
        await self._init_mcp_clients()

        # Build gate registry
        gates = self._build_gates()

        # Build RoleExecutor
        self.role_executor = RoleExecutor(
            roles=self.roles,
            agents=self.agents,
            skills=self.skills,
            memory=self.memory,
            tool_executor=self.tool_executor,
        )

        # Build Mailbox
        mailbox = Mailbox(self.db, self.events)

        # Build WorkflowEngine
        self.workflow_engine = WorkflowEngine(
            db=self.db,
            events=self.events,
            role_executor=self.role_executor,
            roles=self.roles,
            gates=gates,
            max_retries=self.config.engine.max_retries_per_step,
            max_concurrent=self.config.engine.max_concurrent_sessions,
            mailbox=mailbox,
            base_dir=self.config.engine.state_dir,
        )

        # Build Planner
        self.planner = Planner(
            role_executor=self.role_executor,
            roles=self.roles,
        )

    async def stop(self) -> None:
        """Shut down the engine gracefully."""
        # Cancel background tasks
        for task in self._tasks.values():
            task.cancel()

        # Close memory store if it has a close method
        if self.memory and hasattr(self.memory, "close"):
            await self.memory.close()

        await self.db.close()

    async def submit(self, task: str) -> str:
        """Submit a task for execution. Returns workflow ID."""
        if not self.workflow_engine or not self.planner:
            raise RuntimeError("Engine not started. Call start() first.")

        # Plan the task
        steps = await self.planner.plan(task)

        # Create workflow
        workflow_id = await self.workflow_engine.create_workflow(task, steps)

        # Execute in background
        bg_task = asyncio.create_task(self.workflow_engine.execute_workflow(workflow_id))
        self._tasks[workflow_id] = bg_task

        return workflow_id

    async def get_status(self, workflow_id: str) -> dict[str, Any]:
        """Get current status of a workflow."""
        if not self.workflow_engine:
            raise RuntimeError("Engine not started. Call start() first.")
        return await self.workflow_engine.get_workflow(workflow_id)

    async def list_workflows(self) -> list[dict[str, Any]]:
        """List all workflows."""
        if not self.workflow_engine:
            raise RuntimeError("Engine not started. Call start() first.")
        return await self.workflow_engine.list_workflows()

    async def approve(self, approval_id: str) -> None:
        """Approve a pending request."""
        if not self.workflow_engine:
            raise RuntimeError("Engine not started. Call start() first.")
        await self.workflow_engine.resolve_approval(approval_id, approved=True)

    async def reject(self, approval_id: str, reason: str = "") -> None:
        """Reject a pending request."""
        if not self.workflow_engine:
            raise RuntimeError("Engine not started. Call start() first.")
        await self.workflow_engine.resolve_approval(approval_id, approved=False, reason=reason)

    def _load_roles(self) -> None:
        """Load role definitions from config directory."""
        roles_path = Path("config") / "roles.yaml"
        if roles_path.exists():
            self.roles.load(roles_path)
        else:
            # Try relative to package
            pkg_roles = Path(__file__).parent.parent.parent / "config" / "roles.yaml"
            if pkg_roles.exists():
                self.roles.load(pkg_roles)

    def _init_memory(self) -> None:
        """Initialize memory backend based on config."""
        backend = self.config.memory.backend

        if backend == "in-memory":
            from .memory.backends.in_memory import InMemoryStore
            from .memory.embeddings import TfidfEmbeddingProvider

            self.memory = InMemoryStore(TfidfEmbeddingProvider())
        elif backend == "sqlite":
            # SQLite memory needs async connect — defer to start
            self._init_sqlite_memory()
        # Other backends can be added here

    def _init_sqlite_memory(self) -> None:
        """Initialize SQLite memory store (sync setup, async connect later)."""
        try:
            from .memory.backends.sqlite import SqliteMemoryStore
            from .memory.embeddings import TfidfEmbeddingProvider

            store = SqliteMemoryStore(
                path=self.config.memory.sqlite_path,
                embedding_provider=TfidfEmbeddingProvider(),
            )
            self.memory = store
            # Note: connect() must be called separately — but our memory protocol
            # doesn't require it. The first store/search call will fail if not connected.
            # We'll connect it during start() via a separate async step.
        except ImportError:
            logger.warning("scikit-learn not installed, memory disabled")

    def _init_skills(self) -> None:
        """Initialize skill sources based on config."""
        from .skills.sources.filesystem import FilesystemSkillSource

        for source_config in self.config.skills.sources:
            if source_config.type == "filesystem":
                path = Path(source_config.path) if source_config.path else Path("skills")
                self.skills.add_source(FilesystemSkillSource(path))

    def _init_providers(self) -> None:
        """Register agent providers (lazy imports)."""
        default_provider = self.config.agents.default_provider

        # Anthropic API
        try:
            from .agents.providers.anthropic_api import AnthropicApiProvider

            prov_config = self.config.agents.providers.get("anthropic-api")
            api_key = prov_config.api_key if prov_config else None
            model = prov_config.model if prov_config else None

            provider = AnthropicApiProvider(
                api_key=api_key,
                default_model=model or "claude-sonnet-4-5-20250929",
                tool_executor=self.tool_executor.execute if self.tool_executor else None,
            )
            self.agents.register(provider, default=(default_provider == "anthropic-api"))
        except ImportError:
            logger.debug("anthropic package not installed, skipping anthropic-api provider")

        # Claude SDK (subprocess)
        try:
            from .agents.providers.claude_sdk import ClaudeSdkProvider

            prov_config = self.config.agents.providers.get("claude-sdk")
            model = prov_config.model if prov_config else None

            # Build MCP config dict for Claude CLI --mcp-config flag
            mcp_config = self._build_mcp_config() or None

            provider = ClaudeSdkProvider(
                default_model=model or "claude-sonnet-4-5-20250929",
                mcp_config=mcp_config,
            )
            self.agents.register(provider, default=(default_provider == "claude-sdk"))
        except Exception:
            logger.debug("claude-sdk provider init failed, skipping")

        # Claude Agent SDK (in-process)
        try:
            from .agents.providers.agent_sdk import AgentSdkProvider

            prov_config = self.config.agents.providers.get("agent-sdk")
            model = prov_config.model if prov_config else None
            mcp_config = self._build_mcp_config() or None

            provider = AgentSdkProvider(
                default_model=model or "claude-sonnet-4-5-20250929",
                mcp_config=mcp_config,
            )
            self.agents.register(provider, default=(default_provider == "agent-sdk"))
        except Exception:
            logger.debug("agent-sdk provider init failed, skipping")

        # Codex CLI (subprocess)
        try:
            from .agents.providers.codex_cli import CodexCliProvider

            provider = CodexCliProvider()
            self.agents.register(provider, default=(default_provider == "codex-cli"))
        except Exception:
            logger.debug("codex-cli provider init failed, skipping")

    def _init_filesystem_tools(self) -> None:
        """Set up filesystem tools (Read, Write, Bash, etc.) for API providers."""
        from .tools.filesystem import FilesystemToolRouter

        router = FilesystemToolRouter(
            cwd=self.config.engine.state_dir, restrict_to_cwd=True,
        )
        self.tool_executor.set_filesystem_router(router)

    async def _init_mcp_clients(self) -> None:
        """Initialize MCP clients based on config."""
        from .tools.mcp_client import McpClient
        from .tools.transport import SseTransport, StdioTransport

        for server_config in self.config.tools.mcp_servers:
            try:
                if server_config.transport == "stdio" and server_config.command:
                    transport = StdioTransport(
                        command=server_config.command,
                        args=server_config.args,
                        env=server_config.env,
                    )
                elif server_config.transport == "sse" and server_config.url:
                    transport = SseTransport(url=server_config.url)
                else:
                    logger.warning(f"Invalid MCP server config: {server_config.name}")
                    continue

                client = McpClient(server_config.name, transport)
                await client.connect()
                self.tool_executor.register_mcp_client(server_config.name, client)
                tool_count = len(client.tools)
                logger.info(f"MCP server '{server_config.name}' connected: {tool_count} tools")
            except Exception as e:
                logger.warning(f"Failed to connect MCP server '{server_config.name}': {e}")

    def _resolve_mcp_templates(self) -> None:
        """Resolve MCP templates into concrete McpServerConfig entries.

        Reads ``config.tools.templates.browser`` and ``.search``, looks up
        the template from the registry, checks required env vars, and
        appends to ``config.tools.mcp_servers`` (skipping if the user
        already explicitly configured a server with the same name).
        """
        from .config import McpServerConfig
        from .tools.mcp_templates import get_template

        existing_names = {s.name for s in self.config.tools.mcp_servers}
        templates_config = self.config.tools.templates

        for choice in (templates_config.browser, templates_config.search):
            if not choice or choice == "none":
                continue

            template = get_template(choice)
            if not template:
                logger.warning("Unknown MCP template: %s", choice)
                continue

            if template.name in existing_names:
                logger.debug(
                    "MCP server '%s' already configured, skipping template",
                    template.name,
                )
                continue

            # Check required env vars
            missing = [k for k in template.env_keys if not os.environ.get(k)]
            if missing:
                logger.warning(
                    "MCP template '%s' requires env vars %s — skipping",
                    template.name, ", ".join(missing),
                )
                continue

            # Build env dict from required keys
            env = {k: os.environ[k] for k in template.env_keys}

            self.config.tools.mcp_servers.append(McpServerConfig(
                name=template.name,
                transport="stdio",
                command=template.command,
                args=list(template.args),
                env=env,
            ))
            logger.info("Resolved MCP template: %s", template.name)

    def _build_mcp_config(self) -> dict[str, Any] | None:
        """Build MCP config dict from configured servers for Claude CLI."""
        if not self.config.tools.mcp_servers:
            return None
        servers: dict[str, Any] = {}
        for srv in self.config.tools.mcp_servers:
            entry: dict[str, Any] = {}
            if srv.transport == "stdio" and srv.command:
                entry["command"] = srv.command
                if srv.args:
                    entry["args"] = srv.args
                if srv.env:
                    entry["env"] = srv.env
            elif srv.transport == "sse" and srv.url:
                entry["url"] = srv.url
                entry["transport"] = "sse"
            else:
                continue
            servers[srv.name] = entry
        return {"mcpServers": servers} if servers else None

    def _build_gates(self) -> dict[str, Gate]:
        """Build the gate registry."""
        from .gates.approval import ApprovalGate
        from .gates.quality import QualityGate
        from .gates.tests_gate import TestsGate

        return {
            "quality": QualityGate(),
            "tests_pass": TestsGate(),
            "approval": ApprovalGate(),
        }
