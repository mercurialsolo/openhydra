# CLAUDE.md

## Project Overview

OpenHydra is a lightweight, local-first multi-agent orchestration system. Single process, single command, no Docker, no external services.

## Architecture

- **Core Engine** (`src/openhydra/`) — Workflow state machine, agent execution, memory, skills
- **Interfaces** — CLI, TUI, Web UI are separate and consume core via events + API
- **Pluggable adapters** — Memory backends, agent providers, skill sources behind protocol interfaces

## Commands

```bash
# Install (minimal)
uv pip install -e .

# Run CLI
uv run openhydra --help

# Recommended first-run setup and validation
uv run openhydra onboard
uv run openhydra doctor

# Optional: full interactive setup and all extras
uv run openhydra init
uv pip install -e ".[all]"

# Run tests
uv run pytest

# Lint
uv run ruff check src/ tests/
```

## Code Conventions

- Python 3.11+, type annotations everywhere
- `Protocol` classes for adapter interfaces (not ABC)
- `dataclass` or Pydantic `BaseModel` for data transfer objects
- `async/await` for all I/O operations
- SQLite for all persistence (no external databases)
- 100 char line length (ruff)

## Key Design Rules

1. **Engine stays decoupled from channels.** Engine/workflow code must not import channel implementations or web frameworks; channels subscribe to events and call engine APIs.
2. **Adapters are protocols.** Memory, agents, skills use `Protocol` classes — swap implementations freely.
3. **State survives crashes.** Every state transition writes to SQLite before execution.
4. **Skills are files.** SKILL.md + metadata.yaml on disk. No database for skill content.
5. **Skills can be generated.** `SkillBuilder` can generate skills on-the-fly via LLM when not found on disk. Disabled by default (`skills.builder_enabled: false`); generated skills are written to `~/.openhydra/generated_skills/` and scored with a heuristic quality gate before acceptance.
6. **Roles are config.** `config/agents.yaml` defines behavior. No role-specific code.
7. **Events decouple.** Core emits events, interfaces subscribe. No callbacks or direct coupling.

## File Layout

```
src/openhydra/
  engine.py          # Main Engine class
  config.py          # YAML + env config loading
  events.py          # EventBus
  db.py              # SQLite schema + connection

  workflow/          # State machine, planner
  agents/            # Agent providers (Claude, Anthropic API, Ollama)
  skills/            # Skill loading, provisioning, and dynamic generation
    builder.py       # LLM-powered skill generation (SkillBuilder)
  memory/            # Vector memory backends
  roles/             # Role catalog + prompt assembly
  gates/             # Quality gates between steps
  channels/          # Web + messaging adapters (Slack/Discord/WhatsApp/email)
  cli/               # typer CLI entrypoints

config/              # Default role catalog + output schemas
skills/              # Bundled starter skills
tests/               # pytest tests
```
