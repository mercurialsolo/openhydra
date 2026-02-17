# OpenHydra

Lightweight, local-first multi-agent orchestration. One command, no Docker, no external services.

## Quick Start

```bash
# Install
uv pip install -e ".[all]"

# Run
openhydra start
```

## What It Does

OpenHydra takes a task description and executes it through a pipeline of specialized AI agents — each with its own role, tools, skills, and quality gates. Think of it as a lightweight version of a multi-agent system that runs entirely on your laptop.

```bash
openhydra run "Build a Python CLI that converts CSV to JSON"
```

This will:
1. **Plan** — Analyze the task and compose a step-by-step execution plan
2. **Execute** — Run each step with the right agent role (engineer, tester, reviewer)
3. **Gate** — Check quality between steps, ask for human input when needed
4. **Deliver** — Produce the final artifacts in your project directory

## Architecture

- **Pluggable agents** — Claude, OpenAI, Ollama, or bring your own
- **Pluggable memory** — SQLite (default), Qdrant, ChromaDB
- **Pluggable skills** — Filesystem, Git repos, HTTP registries
- **Dynamic skill generation** — When a skill isn't found on disk, the engine generates it on-the-fly via LLM, scores it with a quality gate, and caches it for reuse
- **Separate interfaces** — CLI, TUI, Web UI are independent of the core engine

## Dynamic Skills

OpenHydra can generate skills at runtime when a workflow references a skill ID that doesn't exist on disk. The `SkillBuilder` uses an LLM to create a `SKILL.md` + `metadata.yaml`, scores the output with a heuristic quality rubric, and writes it to `~/.openhydra/generated_skills/` for reuse.

```yaml
# openhydra.yaml — skill builder config
skills:
  builder_enabled: true          # default: true
  generated_dir: ""              # default: ~/.openhydra/generated_skills/
```

Disable with `builder_enabled: false` if you only want hand-authored skills.

## OpenClaw Integration

The [OpenClaw](https://github.com/nicepkg/openclaw) plugin can run OpenHydra as a **managed child process** — one command starts everything:

```yaml
# openclaw.yaml
plugins:
  entries:
    openhydra:
      enabled: true
      config:
        managed: true            # auto-start openhydra serve
        pythonPath: "uv"         # or "python", "openhydra"
```

In managed mode the plugin:
1. Spawns `uv run openhydra serve`
2. Polls the health endpoint until ready
3. Reads the auto-generated API key from `~/.openhydra/openhydra.yaml` (or `OPENHYDRA_WEB_API_KEY` env var)
4. Connects the WebSocket for real-time event streaming

Set `managed: false` (default) to connect to an existing OpenHydra server instead.

See [SPEC.md](SPEC.md) for full architecture and [PLAN.md](PLAN.md) for implementation roadmap.

## Status

Early development. See PLAN.md for current phase.
