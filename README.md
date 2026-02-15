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
- **Separate interfaces** — CLI, TUI, Web UI are independent of the core engine

See [SPEC.md](SPEC.md) for full architecture and [PLAN.md](PLAN.md) for implementation roadmap.

## Status

Early development. See PLAN.md for current phase.
