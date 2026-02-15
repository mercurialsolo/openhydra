# OpenHydra Specification

**Version:** 0.1.0
**Status:** Draft

OpenHydra is a lightweight, local-first multi-agent orchestration system. It runs on a single machine with one command, no Docker, no external services. It preserves the core value of multi-agent workflows — role specialization, durable execution, human-in-the-loop, skills, quality gates, and memory — while eliminating infrastructure overhead.

---

## 1. Design Principles

1. **Single process, single command.** `openhydra start` launches everything. No Temporal server, no Qdrant container, no Docker.
2. **Pluggable everything.** Memory backends, agent providers, skill sources — all behind adapter interfaces. Swap SQLite for Qdrant, local Claude for remote API, filesystem skills for a registry server.
3. **Interface-agnostic core.** The workflow engine, agent executor, and memory system know nothing about CLI, TUI, or web. Interfaces are separate packages that consume the core via events and APIs.
4. **Portable state.** All state lives in `~/.openhydra/` (or project-local `.openhydra/`). One directory, copyable, version-controllable.
5. **Zero mandatory network calls at startup.** The system boots and is ready before any LLM API call. Network is only needed when an agent session actually runs.

---

## 2. Architecture Overview

```
┌──────────────────────────────────────────────────────────────┐
│                        Interfaces                            │
│  ┌──────┐  ┌──────────┐  ┌──────────┐  ┌────────────────┐  │
│  │ CLI  │  │   TUI    │  │  Web UI  │  │ Python SDK     │  │
│  │(typer│  │  (Ink)   │  │(FastAPI+ │  │(programmatic   │  │
│  │/click│  │          │  │  static) │  │ import)        │  │
│  └──┬───┘  └────┬─────┘  └────┬─────┘  └──────┬─────────┘  │
│     │           │              │                │            │
│     └───────────┴──────┬───────┴────────────────┘            │
│                        │                                      │
│              ┌─────────▼─────────┐                           │
│              │    Core API       │                           │
│              │  (event bus +     │                           │
│              │   service layer)  │                           │
│              └─────────┬─────────┘                           │
└────────────────────────│─────────────────────────────────────┘
                         │
┌────────────────────────│─────────────────────────────────────┐
│                   Core Engine                                │
│                        │                                      │
│  ┌─────────────────────▼──────────────────────┐              │
│  │           Workflow Engine                   │              │
│  │  (async state machine, SQLite-backed)      │              │
│  │                                             │              │
│  │  Plan → Steps → Execute → Gate → Next      │              │
│  └──────┬──────────────┬──────────────┬───────┘              │
│         │              │              │                       │
│  ┌──────▼──────┐ ┌─────▼──────┐ ┌────▼───────┐              │
│  │   Agent     │ │  Skill     │ │  Memory    │              │
│  │  Registry   │ │  Registry  │ │  Adapter   │              │
│  │             │ │            │ │            │              │
│  │ Pluggable:  │ │ Pluggable: │ │ Pluggable: │              │
│  │ - Claude SDK│ │ - Local FS │ │ - SQLite   │              │
│  │ - Anthropic │ │ - Git repo │ │ - Qdrant   │              │
│  │ - Ollama   │ │ - HTTP     │ │ - Chroma   │              │
│  │ - OpenAI   │ │            │ │ - In-mem   │              │
│  └─────────────┘ └────────────┘ └────────────┘              │
│                                                              │
│  ┌────────────────────────────────────────────┐              │
│  │            State Store (SQLite)             │              │
│  │  workflows, steps, approvals, artifacts     │              │
│  └────────────────────────────────────────────┘              │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

---

## 3. Core Engine

### 3.1 Workflow Engine

The workflow engine replaces Temporal with an in-process async state machine. All state is persisted to SQLite, enabling crash recovery without an external server.

**Workflow lifecycle:**

```
CREATED → PLANNING → EXECUTING → COMPLETED
                  ↕         ↕
            WAITING_INPUT  WAITING_APPROVAL
                           ↕
                      FAILED / CANCELLED
```

**Key concepts:**

- **Workflow** — A named unit of work with an input description, a composed plan, and ordered steps.
- **Step** — A single agent session with a role, instructions, and expected output schema. Steps execute sequentially by default, with optional parallelism for independent steps.
- **Plan** — An ordered list of steps composed by the planner (which is itself an agent call). Plans can be cached and reused.
- **Gate** — A checkpoint between steps. Gates can be automatic (quality score threshold) or manual (human approval).

**State persistence:**

Every state transition is written to SQLite before execution begins. On crash, the engine resumes from the last completed step. This gives step-level durability (not mid-session replay like Temporal, but sufficient for the local use case).

```sql
CREATE TABLE workflows (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL,          -- lifecycle state
    input TEXT NOT NULL,           -- original task description
    plan TEXT,                     -- JSON: composed step sequence
    current_step INTEGER DEFAULT 0,
    config TEXT,                   -- JSON: workflow-level config overrides
    error TEXT,
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);

CREATE TABLE steps (
    id TEXT PRIMARY KEY,
    workflow_id TEXT REFERENCES workflows(id),
    ordinal INTEGER NOT NULL,
    role_id TEXT NOT NULL,
    instructions TEXT NOT NULL,
    status TEXT NOT NULL,          -- pending, running, completed, failed, skipped
    input_data TEXT,               -- JSON: input from previous steps
    output_data TEXT,              -- JSON: structured result
    artifacts TEXT,                -- JSON: list of artifact references
    cost_usd REAL,
    tokens_used INTEGER,
    error TEXT,
    started_at TIMESTAMP,
    completed_at TIMESTAMP
);

CREATE TABLE approvals (
    id TEXT PRIMARY KEY,
    workflow_id TEXT REFERENCES workflows(id),
    step_id TEXT REFERENCES steps(id),
    type TEXT NOT NULL,            -- approval, correction, input, decision
    prompt TEXT NOT NULL,          -- what the human sees
    response TEXT,                 -- human's response
    status TEXT NOT NULL,          -- pending, approved, rejected, provided
    created_at TIMESTAMP,
    resolved_at TIMESTAMP
);
```

**Retry semantics:**
- Configurable per step: max retries, backoff strategy.
- After max retries, step moves to `failed`, workflow enters `WAITING_INPUT` with an escalation prompt.

**Concurrency:**
- Steps within a workflow execute sequentially by default.
- Steps marked `parallel: true` in the plan can execute concurrently (using `asyncio.gather` with a semaphore).
- Cross-workflow: multiple workflows can run concurrently, bounded by a configurable `max_concurrent_sessions` (default: 2).

### 3.2 Agent Registry

The agent registry is the pluggable layer for LLM-powered agent execution. An "agent" in OpenHydra is not a long-running process — it's a configured session that runs a task and returns a structured result.

**Interface:**

```python
class AgentProvider(Protocol):
    """Adapter for running agent sessions."""

    name: str

    async def run_session(
        self,
        instructions: str,
        system_prompt: str,
        tools: list[ToolDefinition],
        output_schema: dict | None = None,
        max_tokens: int = 100_000,
        model: str | None = None,
    ) -> SessionResult:
        """Run a single agent session and return structured output."""
        ...

    async def check_availability(self) -> bool:
        """Return True if this provider is configured and reachable."""
        ...


@dataclass
class SessionResult:
    output: dict                    # structured output (validated against schema)
    raw_text: str                   # full text response
    artifacts: list[ArtifactRef]    # files created/modified
    tokens_used: int
    input_tokens: int
    output_tokens: int
    cost_usd: float
    duration_seconds: float
    model: str
```

**Built-in providers:**

| Provider | Backend | Requirements |
|----------|---------|-------------|
| `claude-sdk` | Claude Agent SDK (subprocess) | Claude CLI installed, `ANTHROPIC_API_KEY` |
| `anthropic-api` | Anthropic Messages API (direct) | `anthropic` package, `ANTHROPIC_API_KEY` |
| `openai` | OpenAI Chat API | `openai` package, `OPENAI_API_KEY` |
| `ollama` | Ollama local models | Ollama running locally |

**Registry:**

```python
class AgentRegistry:
    def register(self, provider: AgentProvider) -> None: ...
    def get(self, name: str) -> AgentProvider: ...
    def list_available(self) -> list[str]: ...
    def default(self) -> AgentProvider: ...
```

Providers are registered at startup via config or programmatically. The default provider is used unless a role specifies `provider: <name>` in its config.

### 3.3 Skill Registry

Skills are modular instruction packages that teach agents procedures, standards, and guardrails. They are files on disk — no database, no service.

**Skill structure:**

```
skills/
  eng_harness/
    SKILL.md              # Full instructions
    SKILL_SUMMARY.md      # Compressed version (optional, for budget constraints)
    metadata.yaml         # Tags, version, priority, token estimate
    templates/            # Optional templates
    scripts/              # Optional scripts
  coding_principles/
    SKILL.md
    metadata.yaml
```

**Registry interface:**

```python
class SkillSource(Protocol):
    """Adapter for discovering and loading skills."""

    async def list_skills(self) -> list[SkillMetadata]: ...
    async def load_skill(self, skill_id: str, summary: bool = False) -> SkillContent: ...
    async def search_skills(self, query: str) -> list[SkillMetadata]: ...


@dataclass
class SkillMetadata:
    id: str
    name: str
    version: str
    tags: list[str]
    priority: int              # 0=core, 1=matched, 2=supplementary
    token_estimate: int        # approximate token count for budget planning
    has_summary: bool


@dataclass
class SkillContent:
    id: str
    text: str                  # SKILL.md content (or SKILL_SUMMARY.md if summary=True)
    templates: dict[str, str]  # filename -> content
    scripts: dict[str, str]    # filename -> content
```

**Built-in sources:**

| Source | Description |
|--------|-------------|
| `filesystem` | Loads from local `skills/` directory (default) |
| `git` | Loads from a git repository (cloned/pulled at startup) |
| `http` | Fetches from an HTTP skill registry endpoint |

**Skill provisioning per role:**

Each role config specifies `skill_packs: [skill_id, ...]`. The skill provisioner:
1. Loads skills in priority order (core > matched > supplementary).
2. Estimates token cost per skill.
3. Drops or summarizes skills that exceed the role's context budget.
4. Returns the final skill context string to inject into the agent's system prompt.

### 3.4 Memory Adapter

Memory provides persistent vector-searchable storage for facts, decisions, artifacts, and conversation history. The adapter pattern allows swapping backends without changing application code.

**Interface:**

```python
class MemoryStore(Protocol):
    """Adapter for vector-searchable persistent memory."""

    async def store(
        self,
        collection: str,
        content: str,
        metadata: dict,
        embedding: list[float] | None = None,
    ) -> str:
        """Store a memory entry. Returns the entry ID."""
        ...

    async def search(
        self,
        collection: str,
        query: str,
        limit: int = 10,
        filters: dict | None = None,
    ) -> list[MemoryEntry]:
        """Search for relevant memories by semantic similarity."""
        ...

    async def get(self, collection: str, entry_id: str) -> MemoryEntry | None: ...
    async def delete(self, collection: str, entry_id: str) -> bool: ...
    async def list_collections(self) -> list[str]: ...


@dataclass
class MemoryEntry:
    id: str
    content: str
    metadata: dict
    score: float              # similarity score (0-1)
    created_at: datetime
```

**Built-in backends:**

| Backend | Description | Dependencies |
|---------|-------------|-------------|
| `sqlite` | SQLite + sqlite-vec extension | `sqlite-vec` (C extension, ~2MB) |
| `in-memory` | Dict-based, no persistence | None (useful for testing) |
| `qdrant` | Qdrant vector DB | `qdrant-client`, running Qdrant instance |
| `chroma` | ChromaDB | `chromadb` |

**Embedding strategy:**

The memory adapter needs embeddings for vector search. This is handled by a separate `EmbeddingProvider`:

```python
class EmbeddingProvider(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...
    @property
    def dimensions(self) -> int: ...
```

Built-in embedding providers:
- `anthropic` — Claude API embeddings (network required)
- `openai` — OpenAI embeddings (network required)
- `sentence-transformers` — Local model, ~80MB download on first use
- `tfidf` — Scikit-learn TF-IDF (no download, lower quality, zero-network fallback)

**Collections (same semantics as full Hydra):**

| Collection | Purpose |
|------------|---------|
| `memories` | Durable facts, decisions, constraints |
| `artifacts` | File references with hashes |
| `conversations` | Session summaries for handoff |
| `decisions` | Structured decisions with outcomes |
| `plans` | Cached workflow plans for reuse |

### 3.5 Role Catalog

Roles define how agents behave during a step. A role is a configuration, not a process.

```yaml
# config/roles.yaml
roles:
  pm.prd:
    name: "Product Manager - PRD Writer"
    description: "Writes product requirements documents from task descriptions"
    provider: claude-sdk            # which AgentProvider to use
    model: claude-sonnet-4-5-20250929
    skill_packs:
      - prd_template
      - product_quality
    allowed_tools:
      - Read
      - Write
      - Glob
      - Grep
      - WebSearch
      - WebFetch
    output_schema: prd_output      # references schemas/prd_output.json
    budget:
      max_tokens: 50000
      max_tool_calls: 100
      max_duration_minutes: 15
    context_budget:
      skills_pct: 35
      memory_pct: 10
      reasoning_pct: 55
    gates:
      - type: quality
        threshold: 24              # /40

  eng.implement:
    name: "Engineer - Implementation"
    description: "Implements features based on plans and specs"
    provider: claude-sdk
    model: claude-sonnet-4-5-20250929
    skill_packs:
      - eng_harness
      - coding_principles
      - engineering_excellence
    allowed_tools:
      - Read
      - Write
      - Edit
      - Glob
      - Grep
      - Bash
    output_schema: eng_output
    budget:
      max_tokens: 200000
      max_tool_calls: 500
      max_duration_minutes: 60
    context_budget:
      skills_pct: 30
      memory_pct: 8
      reasoning_pct: 62
    gates:
      - type: quality
        threshold: 28
      - type: tests_pass
```

### 3.6 Quality Gates

Quality gates are checkpoints between workflow steps. They inspect the output of a completed step and decide whether to proceed, retry, or escalate.

**Gate types:**

| Type | Behavior |
|------|----------|
| `quality` | Checks quality score dimensions against threshold. Score is embedded in structured output. |
| `tests_pass` | Runs a test command and checks exit code. |
| `approval` | Pauses workflow and waits for human approval. |
| `schema` | Validates output against JSON schema (always runs, not optional). |

**Quality scoring (same as full Hydra):**
- 8 dimensions, 1-5 scale each, /40 total.
- Context-aware thresholds configurable per role.
- On failure: retry with feedback (up to max retries), then escalate.

### 3.7 Event Bus

The core engine communicates with interfaces through an async event bus. This decouples the engine from any specific UI.

```python
class EventBus:
    async def emit(self, event: Event) -> None: ...
    def on(self, event_type: str, handler: Callable) -> None: ...
    def off(self, event_type: str, handler: Callable) -> None: ...


@dataclass
class Event:
    type: str                  # e.g., "workflow.started", "step.completed"
    data: dict
    timestamp: datetime
```

**Event types:**

| Event | Emitted When |
|-------|-------------|
| `workflow.created` | New workflow registered |
| `workflow.planning` | Plan composition started |
| `workflow.executing` | First step begins |
| `workflow.completed` | All steps done |
| `workflow.failed` | Unrecoverable error |
| `workflow.waiting` | Waiting for human input |
| `step.started` | Agent session begins |
| `step.progress` | Token count / tool call update |
| `step.completed` | Step finished successfully |
| `step.failed` | Step failed (may retry) |
| `approval.requested` | Human approval needed |
| `approval.resolved` | Human responded |
| `memory.stored` | New memory entry created |
| `cost.updated` | Running cost total changed |

---

## 4. Interfaces

Interfaces are separate packages. They import the core engine and subscribe to its events. They do not contain business logic.

### 4.1 CLI (`openhydra-cli`)

Minimal command-line interface using `typer` or `click`.

```bash
# Start everything (engine + optional web server)
openhydra start

# Submit a task
openhydra run "Build a REST API for user management"

# Check status
openhydra status
openhydra status <workflow-id>

# List workflows
openhydra list

# Respond to approval
openhydra approve <approval-id>
openhydra reject <approval-id> --reason "..."
openhydra respond <approval-id> --input "..."

# Memory
openhydra memory search "authentication patterns"
openhydra memory store "Always use bcrypt for passwords"

# Skills
openhydra skills list
openhydra skills add <path-or-url>

# Config
openhydra config show
openhydra config set default_provider anthropic-api
```

### 4.2 TUI (`openhydra-tui`)

Rich terminal UI using Ink (Node.js) or Textual (Python). Shows:
- Active workflows with step progress
- Pending approvals (interactive approve/reject)
- Live token/cost counters
- Agent output streaming
- Memory search

The TUI subscribes to the event bus via SSE or WebSocket from the embedded web server.

### 4.3 Web UI (`openhydra-web`)

Optional lightweight web interface. Served by the embedded FastAPI server.

- Static HTML + minimal JS (no React/Vite build step required)
- Or: prebuilt React SPA served as static files
- SSE endpoint for live updates
- REST endpoints for actions (approve, reject, submit task)

### 4.4 Python SDK (`openhydra` package import)

For programmatic use:

```python
from openhydra import Engine

engine = Engine()
workflow = await engine.submit("Build a REST API for user management")

async for event in engine.stream(workflow.id):
    print(event)

result = await engine.wait(workflow.id)
```

---

## 5. Configuration

### 5.1 Config File (`openhydra.yaml`)

```yaml
# ~/.openhydra/openhydra.yaml (or .openhydra/openhydra.yaml in project root)

engine:
  max_concurrent_sessions: 2
  max_retries_per_step: 3
  state_dir: ~/.openhydra             # where DB + artifacts live

agents:
  default_provider: claude-sdk
  providers:
    claude-sdk:
      model: claude-sonnet-4-5-20250929
    anthropic-api:
      model: claude-sonnet-4-5-20250929
      api_key: ${ANTHROPIC_API_KEY}
    ollama:
      model: llama3.1:70b
      base_url: http://localhost:11434

memory:
  backend: sqlite                      # sqlite | qdrant | chroma | in-memory
  embedding_provider: anthropic        # anthropic | openai | sentence-transformers | tfidf
  sqlite:
    path: ~/.openhydra/memory.db
  qdrant:
    url: http://localhost:6333

skills:
  sources:
    - type: filesystem
      path: ./skills
    - type: git
      url: https://github.com/org/shared-skills.git
      branch: main

web:
  enabled: true
  host: 127.0.0.1
  port: 7070
```

### 5.2 Environment Variables

All config values can be overridden by environment variables:

```
OPENHYDRA_STATE_DIR=~/.openhydra
OPENHYDRA_DEFAULT_PROVIDER=claude-sdk
OPENHYDRA_MEMORY_BACKEND=sqlite
OPENHYDRA_WEB_PORT=7070
ANTHROPIC_API_KEY=sk-...
OPENAI_API_KEY=sk-...
```

---

## 6. State Directory

```
~/.openhydra/
  openhydra.yaml          # config (user can also put in project root)
  openhydra.db            # SQLite: workflows, steps, approvals
  memory.db               # SQLite: vector memory (if using sqlite backend)
  artifacts/              # files created by agents
    <workflow-id>/
      <step-ordinal>/
        output.json
        *.md, *.py, etc.
  logs/
    engine.log
    sessions/
      <workflow-id>-<step-ordinal>.log
  cache/
    plans/                # cached workflow plans
    skills/               # cached skill token counts
```

---

## 7. Workflow Execution Flow

```
1. User submits task description
   │
2. Engine creates Workflow (status: CREATED)
   │
3. Planner step runs (status: PLANNING)
   │  - Uses an agent session to analyze the task
   │  - Checks plan cache for similar past tasks
   │  - Composes ordered step list with roles
   │  - Each step has: role, instructions, dependencies
   │
4. Engine validates plan, saves to DB (status: EXECUTING)
   │
5. For each step in plan:
   │
   ├─ 5a. Load role config (tools, skills, budget, model)
   │
   ├─ 5b. Build system prompt:
   │       - Role description
   │       - Loaded skills (budget-constrained)
   │       - Relevant memories (vector search)
   │       - Previous step outputs (context chain)
   │
   ├─ 5c. Run agent session via AgentProvider
   │       - Agent executes with allowed tools
   │       - Structured output validated against schema
   │
   ├─ 5d. Check gates:
   │       - Quality score >= threshold?
   │       - Tests pass?
   │       - Human approval needed?
   │       │
   │       ├─ Pass → Continue to next step
   │       ├─ Fail (retriable) → Retry with feedback
   │       └─ Fail (final) → Escalate to human
   │
   └─ 5e. Store step result, update workflow state
   │
6. All steps complete → Workflow status: COMPLETED
   │
7. Store plan outcome in memory (for future plan caching)
```

---

## 8. Differences from Full Hydra

| Aspect | Full Hydra | OpenHydra |
|--------|-----------|-----------|
| Orchestration | Temporal (external server) | In-process async state machine |
| Memory | Qdrant (external container) | Pluggable (SQLite default) |
| Workers | 8 Docker containers | Single process, role switching |
| Agent runtime | Claude Agent SDK only | Pluggable (Claude SDK, API, Ollama, OpenAI) |
| Skills | Filesystem only | Pluggable (filesystem, git, HTTP) |
| Durability | Temporal event log (mid-session replay) | SQLite checkpoints (step-level resume) |
| UI | React SPA in Docker | Separate packages (CLI, TUI, Web) |
| Auth | JWT + bcrypt | None (local single-user) |
| Networking | Docker bridge network | localhost only |
| Concurrency | 3+ parallel agent sessions | 1-2 (laptop constraint) |
| Artifact storage | MinIO / S3 | Local filesystem |
| Cost | ~35GB RAM, 18 CPU cores | ~500MB idle, ~2GB active |

---

## 9. Extension Points

### Custom Agent Provider

```python
from openhydra.agents import AgentProvider, SessionResult

class MyCustomProvider(AgentProvider):
    name = "my-provider"

    async def run_session(self, instructions, system_prompt, tools, **kwargs):
        # Call your LLM, return SessionResult
        ...

    async def check_availability(self):
        return True

# Register
engine.agents.register(MyCustomProvider())
```

### Custom Memory Backend

```python
from openhydra.memory import MemoryStore

class RedisMemoryStore(MemoryStore):
    async def store(self, collection, content, metadata, embedding=None):
        ...
    async def search(self, collection, query, limit=10, filters=None):
        ...
    # etc.

engine.memory = RedisMemoryStore(redis_url="redis://localhost:6379")
```

### Custom Skill Source

```python
from openhydra.skills import SkillSource

class S3SkillSource(SkillSource):
    async def list_skills(self):
        # List skills from S3 bucket
        ...
    async def load_skill(self, skill_id, summary=False):
        # Download and return skill content
        ...

engine.skills.add_source(S3SkillSource(bucket="my-skills"))
```

### Custom Gate

```python
from openhydra.gates import Gate, GateResult

class LintGate(Gate):
    async def check(self, step_output, context):
        result = subprocess.run(["ruff", "check", "."], capture_output=True)
        return GateResult(
            passed=result.returncode == 0,
            message=result.stdout.decode(),
        )
```

---

## 10. Non-Goals (v0.1)

- Multi-user / multi-tenant
- Cloud deployment
- Horizontal scaling
- Browser automation (Playwright/VNC)
- Real-time collaborative editing
- Git integration for artifact versioning (future)
- Distributed task queues
- OpenTelemetry / Prometheus metrics export
