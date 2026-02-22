# OpenHydra Implementation Plan

**Target:** Working MVP that can accept a task, compose a plan, execute multi-step agent workflows, and return results — all from one command.

---

## Phase 0: Project Skeleton

**Goal:** Installable Python package with correct structure and tooling.

**Files:**

```
pyproject.toml
CLAUDE.md
.gitignore
README.md
src/
  openhydra/
    __init__.py
    engine.py                    # Engine class (main entry point)
    config.py                    # Config loading (YAML + env vars)
    events.py                    # EventBus + Event types
    db.py                        # SQLite schema + connection management

    workflow/
      __init__.py
      engine.py                  # WorkflowEngine (state machine)
      models.py                  # Workflow, Step, Approval dataclasses
      planner.py                 # Plan composition (agent-powered)

    agents/
      __init__.py
      registry.py                # AgentRegistry
      base.py                    # AgentProvider protocol + SessionResult
      providers/
        __init__.py
        anthropic_api.py         # Direct Anthropic Messages API
        claude_sdk.py            # Claude Agent SDK subprocess
        ollama.py                # Ollama local models

    skills/
      __init__.py
      registry.py                # SkillRegistry
      base.py                    # SkillSource protocol + SkillContent
      sources/
        __init__.py
        filesystem.py            # Local directory source

    memory/
      __init__.py
      base.py                    # MemoryStore protocol + MemoryEntry
      embeddings.py              # EmbeddingProvider protocol
      backends/
        __init__.py
        sqlite_vec.py            # SQLite + sqlite-vec
        in_memory.py             # Dict-based (testing)

    roles/
      __init__.py
      catalog.py                 # Load and validate agents.yaml
      executor.py                # RoleExecutor: build prompt, run session

    gates/
      __init__.py
      base.py                    # Gate protocol + GateResult
      quality.py                 # Quality score gate
      tests.py                   # Test runner gate
      approval.py                # Human approval gate

    cli/
      __init__.py
      main.py                    # typer CLI app

config/
  agents.yaml                    # Default role catalog
  schemas/                      # JSON schemas for structured outputs
    prd_output.json
    eng_output.json
    plan_output.json

skills/                          # Bundled default skills
  coding_principles/
    SKILL.md
    metadata.yaml
  eng_harness/
    SKILL.md
    metadata.yaml

tests/
  conftest.py
  test_workflow_engine.py
  test_agent_registry.py
  test_memory.py
  test_skill_registry.py
  test_role_executor.py
  test_gates.py
```

**Deliverables:**
- [ ] `pyproject.toml` with dependencies, entry point (`openhydra` CLI)
- [ ] `.gitignore` for Python + SQLite + state dirs
- [ ] `CLAUDE.md` with project conventions
- [ ] All `__init__.py` files
- [ ] SQLite schema in `db.py`
- [ ] Config dataclass + YAML loader in `config.py`
- [ ] Empty protocol classes in all `base.py` files

**Exit criteria:** `uv run openhydra --help` prints usage.

---

## Phase 1: State Machine + SQLite

**Goal:** Workflow engine that can create, persist, and resume workflows without any LLM calls.

**Build:**
1. `db.py` — SQLite connection manager, schema creation, migration support
2. `workflow/models.py` — Pydantic/dataclass models for Workflow, Step, Approval
3. `workflow/engine.py` — WorkflowEngine with create/advance/fail/wait/resume
4. `events.py` — Simple async EventBus (publish/subscribe)

**Test with mock steps:**
```python
engine = WorkflowEngine(db)
wf = await engine.create_workflow("test task")
await engine.set_plan(wf.id, [
    Step(role="mock", instructions="step 1"),
    Step(role="mock", instructions="step 2"),
])
# Manually complete steps, verify state transitions
```

**Exit criteria:**
- Workflows persist to SQLite across process restarts
- State transitions follow lifecycle diagram
- Events emitted for each transition
- Approval workflow blocks and resumes correctly

---

## Phase 2: Agent Registry + First Provider

**Goal:** Run actual LLM agent sessions through a pluggable provider.

**Build:**
1. `agents/base.py` — `AgentProvider` protocol, `SessionResult`
2. `agents/registry.py` — `AgentRegistry` (register, get, default)
3. `agents/providers/anthropic_api.py` — Direct Anthropic Messages API provider (simplest, no subprocess)

**Why Anthropic API first (not Claude SDK):**
- Simpler: just HTTP calls, no subprocess management
- Faster to test: no Claude CLI installation required
- Validates the interface before adding complexity

**Test:**
```python
provider = AnthropicAPIProvider(api_key="...")
result = await provider.run_session(
    instructions="Write a haiku about coding",
    system_prompt="You are a poet.",
    tools=[],
)
assert result.output  # got a response
```

**Exit criteria:**
- AnthropicAPIProvider runs sessions and returns SessionResult
- AgentRegistry manages multiple providers
- Provider check_availability works

---

## Phase 3: Skill Registry + Filesystem Source

**Goal:** Load skills from disk and inject them into agent prompts.

**Build:**
1. `skills/base.py` — `SkillSource` protocol, `SkillMetadata`, `SkillContent`
2. `skills/registry.py` — `SkillRegistry` (multi-source, search, budget-aware loading)
3. `skills/sources/filesystem.py` — Load from `skills/` directory
4. Bundle 2-3 starter skills: `coding_principles`, `eng_harness`

**Token budget logic:**
- Each skill has a `token_estimate` in metadata.yaml
- Provisioner loads skills in priority order until budget exhausted
- Skills with SKILL_SUMMARY.md get summarized version if full doesn't fit

**Exit criteria:**
- Skills load from filesystem
- Token budget correctly limits skill loading
- `openhydra skills list` shows available skills

---

## Phase 4: Memory Adapter + SQLite Backend

**Goal:** Persistent vector-searchable memory using embedded SQLite.

**Build:**
1. `memory/base.py` — `MemoryStore` protocol, `MemoryEntry`
2. `memory/embeddings.py` — `EmbeddingProvider` protocol + TF-IDF fallback
3. `memory/backends/sqlite_vec.py` — SQLite + sqlite-vec implementation
4. `memory/backends/in_memory.py` — Dict-based for testing

**Embedding strategy for MVP:**
- Default: TF-IDF (no downloads, works offline)
- Optional: Anthropic API embeddings (better quality, needs network)
- sqlite-vec for vector operations (if available, fall back to brute-force cosine)

**Exit criteria:**
- Store and search memories by semantic similarity
- Memories persist across restarts
- `openhydra memory search "query"` returns results

---

## Phase 5: Role Executor + Prompt Assembly

**Goal:** Given a role config + skills + memories, assemble a complete system prompt and run an agent session.

**Build:**
1. `roles/catalog.py` — Parse `config/agents.yaml`, validate roles
2. `roles/executor.py` — `RoleExecutor`:
   - Load role config
   - Provision skills (budget-constrained)
   - Retrieve relevant memories
   - Assemble system prompt
   - Run agent session via registry
   - Validate output against schema

**This is the integration layer** — it wires together agents, skills, and memory.

**Exit criteria:**
- `RoleExecutor.execute(role_id, instructions, context)` runs end-to-end
- System prompt includes role description + skills + memories
- Output validated against JSON schema
- Structured result returned

---

## Phase 6: Quality Gates

**Goal:** Checkpoint logic between steps.

**Build:**
1. `gates/base.py` — `Gate` protocol, `GateResult`
2. `gates/quality.py` — Score threshold gate (reads quality dimensions from output)
3. `gates/approval.py` — Pauses workflow, waits for human signal
4. `gates/tests.py` — Runs shell command, checks exit code

**Exit criteria:**
- Quality gate blocks on low score, allows retry
- Approval gate pauses workflow, resumes on signal
- Test gate runs command and gates on exit code

---

## Phase 7: Plan Composition

**Goal:** Given a task description, use an agent to compose a multi-step plan.

**Build:**
1. `workflow/planner.py`:
   - Task analysis (classify type, domain, complexity)
   - Plan composition (generate step sequence with roles)
   - Plan caching (store/retrieve from memory)
2. `config/schemas/plan_output.json` — Schema for composed plans

**The planner is itself an agent session** — it uses the `anthropic-api` provider with a specialized prompt that knows about available roles.

**Exit criteria:**
- Given "Build a REST API for user management", planner produces a multi-step plan with appropriate roles
- Plans cached in memory for reuse
- Cached plan retrieval works on similar future tasks

---

## Phase 8: End-to-End Workflow

**Goal:** Complete workflow from task submission to multi-step execution.

**Integration:**
1. Wire planner into WorkflowEngine (CREATED → PLANNING → EXECUTING)
2. Wire RoleExecutor into step execution
3. Wire gates between steps
4. Wire memory storage for step outputs and plan outcomes
5. Wire event bus for status updates

**Test scenario:**
```
Input: "Write a Python function that calculates fibonacci numbers with tests"

Expected plan:
  Step 1: eng.init (analyze requirements, plan implementation)
  Step 2: eng.implement (write the code + tests)

Expected output:
  - fibonacci.py
  - test_fibonacci.py
  - Quality score >= threshold
```

**Exit criteria:**
- `openhydra run "task description"` executes multi-step workflow end-to-end
- Steps execute sequentially with context passing
- Gates check between steps
- Results stored in artifacts directory
- Workflow recovers from crash (kill mid-workflow, restart, resume)

---

## Phase 9: CLI Polish

**Goal:** Complete CLI for day-to-day use.

**Commands:**
- `openhydra init` — Interactive config wizard (writes `~/.openhydra/openhydra.yaml`)
- `openhydra serve` — Start engine + enabled channels
- `openhydra run <task>` — Submit and optionally watch
- `openhydra status [workflow-id]` — Show status
- `openhydra list` — List all workflows
- `openhydra approve/reject <id>` — Handle approvals
- `openhydra pause/resume/cancel <id>` — Control running workflows
- `openhydra auth add/revoke <channel:user_id>` — Allowlist identities for channel access
- `openhydra skills` — List skills
- `openhydra config` — Show configuration

**Exit criteria:**
- All commands work
- `openhydra run` with `--watch` flag streams events to terminal
- Approval flow works interactively from CLI

---

## Phase 10: Additional Providers

**Goal:** Claude SDK and Ollama providers.

**Build:**
1. `agents/providers/claude_sdk.py` — Subprocess-based Claude Agent SDK
2. `agents/providers/ollama.py` — Ollama HTTP API

**Exit criteria:**
- `openhydra config set default_provider ollama` switches to local models
- Claude SDK provider works with `claude` CLI installed
- Graceful fallback if provider unavailable

---

## Future Phases (post-MVP)

- **Phase 11:** Web UI (FastAPI + SSE + static HTML or prebuilt React)
- **Phase 12:** TUI (Ink or Textual)
- **Phase 13:** Git skill source
- **Phase 14:** Qdrant/Chroma memory backends
- **Phase 15:** Plan caching with vector similarity
- **Phase 16:** Workflow templates (predefined plans for common tasks)
- **Phase 17:** Plugin system (custom gates, providers, skill sources via entry points)

---

## Dependency Budget

### Required (Phase 0)

```
python >= 3.11
pydantic >= 2.0        # Models + validation
pyyaml >= 6.0          # Config
aiosqlite >= 0.19      # Async SQLite
typer >= 0.9           # CLI
rich >= 13.0           # CLI output formatting
```

### Phase 2 (First agent provider)

```
anthropic >= 0.39      # Anthropic API
```

### Phase 4 (Memory)

```
sqlite-vec >= 0.1      # Vector search (optional, falls back to brute-force)
scikit-learn >= 1.3    # TF-IDF embeddings (lightweight fallback)
```

### Phase 10 (Additional providers)

```
openai >= 1.0          # OpenAI provider (optional)
httpx >= 0.25          # Ollama HTTP client (optional)
```

### Total footprint (all phases)

~50MB installed (without sentence-transformers).
~150MB with sentence-transformers local embeddings.

---

## Risk Mitigations

| Risk | Mitigation |
|------|-----------|
| sqlite-vec not available on platform | Fall back to brute-force cosine similarity in pure Python |
| Claude SDK subprocess hangs | Timeout + process kill after max_duration |
| Agent produces invalid structured output | Retry with schema validation error as feedback |
| Plan composition generates nonsensical plans | Validate plan against role catalog (all referenced roles must exist) |
| Memory grows unbounded | Periodic compaction: evict old low-value entries |
| Single-process bottleneck | asyncio + ThreadPoolExecutor for agent sessions (same pattern as Hydra) |
