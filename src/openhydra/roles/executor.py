"""Role executor — the critical integration point between roles, agents, skills, and memory."""

from __future__ import annotations

from typing import Any

from ..agents.base import SessionResult, ToolDefinition
from ..agents.registry import AgentRegistry
from ..memory.base import MemoryEntry, MemoryStore
from ..memory.compaction import MemoryCompactor
from ..memory.embeddings import TfidfEmbeddingProvider
from ..roles.catalog import RoleCatalog, RoleDefinition
from ..skills.registry import SkillRegistry
from ..tools.executor import ToolExecutor


class RoleExecutor:
    """Orchestrates a single role execution session.

    1. Load role from RoleCatalog
    2. Provision skills via SkillRegistry (budget-constrained)
    3. Search memory for relevant context
    4. Assemble system prompt
    5. Prepare tool list (builtin + MCP, filtered by role's allowed_tools)
    6. Select provider via AgentRegistry
    7. Call provider.run_session()
    8. Store conversation summary in memory
    """

    def __init__(
        self,
        roles: RoleCatalog,
        agents: AgentRegistry,
        skills: SkillRegistry,
        memory: MemoryStore | None = None,
        tool_executor: ToolExecutor | None = None,
    ) -> None:
        self._roles = roles
        self._agents = agents
        self._skills = skills
        self._memory = memory
        self._tool_executor = tool_executor
        self._store_counts: dict[str, int] = {}
        self._compactor: MemoryCompactor | None = None
        if memory:
            # Try to extract embedding provider for compaction dedup
            embedding_provider = getattr(memory, "_embedding_provider", None)
            self._compactor = MemoryCompactor(
                store=memory,
                embedding_provider=embedding_provider
                if isinstance(embedding_provider, TfidfEmbeddingProvider)
                else None,
            )

    @property
    def memory(self) -> MemoryStore | None:
        return self._memory

    @property
    def tool_executor(self) -> ToolExecutor | None:
        return self._tool_executor

    async def execute(
        self,
        role_id: str,
        instructions: str,
        context: dict[str, Any] | None = None,
        messages: list[dict[str, str]] | None = None,
        store_memory: bool = True,
    ) -> SessionResult:
        """Execute a role with the given instructions."""
        role = self._roles.get(role_id)
        context = context or {}

        # 1. Provision skills
        skill_text = await self._provision_skills(role)

        # 2. Search memory for relevant context
        memory_text = await self._search_memory(role_id, instructions)

        # 3. Assemble system prompt
        system_prompt = self._assemble_prompt(role, skill_text, memory_text, context, messages)

        # 4. Prepare tools
        tools = self._prepare_tools(role)

        # 5. Select provider
        if role.provider:
            provider = self._agents.get(role.provider)
        else:
            provider = self._agents.default()

        # 6. Run session
        result = await provider.run_session(
            instructions=instructions,
            system_prompt=system_prompt,
            tools=tools,
            model=role.model,
            max_tokens=role.budget.max_tokens,
        )

        # 7. Store summary in memory (unless caller will store outcome separately)
        if store_memory:
            await self._store_summary(role_id, instructions, result)

        return result

    async def store_execution_outcome(
        self,
        role_id: str,
        instructions: str,
        result: SessionResult,
        success: bool,
        quality_score: float = 0.0,
        gate_results: list[dict[str, Any]] | None = None,
        was_retry: bool = False,
        retry_attempt: int = 0,
    ) -> None:
        """Store execution result with enriched outcome metadata."""
        if not self._memory:
            return

        collection = f"role:{role_id}"
        summary = (
            f"Task: {instructions[:200]}\n"
            f"Result: {result.raw_text[:500]}\n"
            f"Cost: ${result.cost_usd:.4f}, Tokens: {result.tokens_used}"
        )
        try:
            await self._memory.store(
                collection=collection,
                content=summary,
                metadata={
                    "role_id": role_id,
                    "cost_usd": result.cost_usd,
                    "tokens_used": result.tokens_used,
                    "success": success,
                    "quality_score": quality_score,
                    "gate_results": gate_results or [],
                    "was_retry": was_retry,
                    "retry_attempt": retry_attempt,
                },
            )
            self._store_counts[collection] = self._store_counts.get(collection, 0) + 1
            if self._compactor:
                await self._compactor.maybe_compact(
                    collection, self._store_counts[collection]
                )
        except Exception:
            pass

    async def store_retry_lesson(
        self,
        role_id: str,
        instructions: str,
        failed_result: SessionResult,
        success_result: SessionResult,
        attempt: int,
    ) -> None:
        """Store what failed vs what worked when a retry succeeds."""
        if not self._memory:
            return

        collection = f"role:{role_id}"
        lesson = (
            f"Task: {instructions[:200]}\n"
            f"FAILED (attempt {attempt}): {failed_result.raw_text[:300]}\n"
            f"SUCCEEDED: {success_result.raw_text[:300]}"
        )
        try:
            await self._memory.store(
                collection=collection,
                content=lesson,
                metadata={
                    "role_id": role_id,
                    "type": "retry_lesson",
                    "success": True,
                    "retry_attempt": attempt,
                },
            )
        except Exception:
            pass

    async def _provision_skills(self, role: RoleDefinition) -> str:
        """Load skills for the role, respecting token budget."""
        if not role.skill_packs:
            return ""

        budget = int(role.budget.max_tokens * role.context_budget.skills_pct / 100)
        skills = await self._skills.provision_for_role(role.skill_packs, budget)

        if not skills:
            return ""

        parts = []
        for skill in skills:
            parts.append(f"## Skill: {skill.metadata.name if skill.metadata else skill.id}")
            parts.append(skill.text)
        return "\n\n".join(parts)

    async def _search_memory(self, role_id: str, instructions: str) -> str:
        """Search memory for relevant context with success-weighted re-ranking."""
        if not self._memory:
            return ""

        try:
            # Fetch from own collection
            own_entries = await self._memory.search(
                collection=f"role:{role_id}",
                query=instructions,
                limit=10,
            )

            # Fetch cross-role retry lessons
            cross_entries: list[MemoryEntry] = []
            try:
                collections = await self._memory.list_collections()
                for coll in collections:
                    if coll == f"role:{role_id}":
                        continue
                    lessons = await self._memory.search(
                        collection=coll,
                        query=instructions,
                        limit=3,
                        filters={"type": "retry_lesson"},
                    )
                    cross_entries.extend(lessons)
            except Exception:
                pass

            # Re-rank with success/quality/lesson boosts
            scored: list[tuple[float, MemoryEntry, str]] = []
            for entry in own_entries:
                boosted = self._compute_boosted_score(entry)
                marker = self._get_marker(entry)
                scored.append((boosted, entry, marker))
            for entry in cross_entries:
                boosted = self._compute_boosted_score(entry) * 0.8  # cross-role discount
                scored.append((boosted, entry, "[LESSON]"))

            scored.sort(key=lambda x: x[0], reverse=True)
            top = scored[:5]

            if not top:
                return ""

            parts = ["## Relevant Memory"]
            for _, entry, marker in top:
                prefix = f"{marker} " if marker else ""
                parts.append(f"- {prefix}{entry.content}")
            return "\n".join(parts)
        except Exception:
            return ""

    @staticmethod
    def _compute_boosted_score(entry: MemoryEntry) -> float:
        """Re-rank by: similarity * success_boost * quality_boost * lesson_boost."""
        base = entry.score if entry.score > 0 else 0.5
        meta = entry.metadata

        success_boost = 1.2 if meta.get("success") else 0.8
        quality = meta.get("quality_score", 0)
        quality_boost = 1.0 + (quality / 100.0) * 0.3 if quality else 1.0
        lesson_boost = 1.5 if meta.get("type") == "retry_lesson" else 1.0

        return base * success_boost * quality_boost * lesson_boost

    @staticmethod
    def _get_marker(entry: MemoryEntry) -> str:
        meta = entry.metadata
        if meta.get("type") == "retry_lesson":
            return "[LESSON]"
        if meta.get("success"):
            return "[SUCCESS]"
        return ""

    def _assemble_prompt(
        self,
        role: RoleDefinition,
        skill_text: str,
        memory_text: str,
        context: dict[str, Any],
        messages: list[dict[str, str]] | None,
    ) -> str:
        """Build the full system prompt from all components."""
        sections = [f"# Role: {role.name}", role.description]

        # Previous step outputs
        prev_outputs = context.get("previous_outputs")
        if prev_outputs:
            sections.append("## Previous Step Outputs")
            for i, output in enumerate(prev_outputs):
                sections.append(f"### Step {i}")
                sections.append(str(output))

        # Memory context
        if memory_text:
            sections.append(memory_text)

        # Skills
        if skill_text:
            sections.append("## Skills")
            sections.append(skill_text)

        # Mailbox messages
        if messages:
            sections.append("## Messages from Other Agents")
            for msg in messages:
                sections.append(f"**From {msg.get('from', 'unknown')}**: {msg.get('body', '')}")

        return "\n\n".join(sections)

    def _prepare_tools(self, role: RoleDefinition) -> list[ToolDefinition] | None:
        """Prepare tool list filtered by role's allowed_tools.

        Returns:
            None  — when allowed_tools is None (unrestricted, provider decides)
            []    — when allowed_tools is [] (deny all tools)
            [tools] — filtered list matching allowed_tools names
        """
        if not self._tool_executor:
            return []

        # None = unrestricted (role doesn't specify restrictions)
        if role.allowed_tools is None:
            return None

        # Empty list = deny all tools
        if not role.allowed_tools:
            return []

        all_tools = self._tool_executor.list_all_tools()
        allowed = set(role.allowed_tools)
        return [t for t in all_tools if t.name in allowed]

    async def _store_summary(
        self, role_id: str, instructions: str, result: SessionResult
    ) -> None:
        """Store a summary of the session in memory."""
        if not self._memory:
            return

        collection = f"role:{role_id}"
        summary = (
            f"Task: {instructions[:200]}\n"
            f"Result: {result.raw_text[:500]}\n"
            f"Cost: ${result.cost_usd:.4f}, Tokens: {result.tokens_used}"
        )
        try:
            await self._memory.store(
                collection=collection,
                content=summary,
                metadata={
                    "role_id": role_id,
                    "cost_usd": result.cost_usd,
                    "tokens_used": result.tokens_used,
                },
            )
            # Track store count and trigger compaction at intervals
            self._store_counts[collection] = self._store_counts.get(collection, 0) + 1
            if self._compactor:
                await self._compactor.maybe_compact(
                    collection, self._store_counts[collection]
                )
        except Exception:
            pass
