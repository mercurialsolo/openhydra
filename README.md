# OpenHydra

Lightweight, local-first multi-agent orchestration. One command, no Docker, no external services.

## Quick Start

```bash
# Install
uv pip install -e ".[all]"

# Optional: interactive setup (writes ~/.openhydra/openhydra.yaml and can enable channels)
uv run openhydra init

# Run a one-off workflow
uv run openhydra run "Build a Python CLI that converts CSV to JSON"

# Or run the server (web API + any enabled channels)
uv run openhydra serve

# Scaffold a new role agent in config/roles.yaml
uv run openhydra agent scaffold eng.docs --description "Writes implementation docs"

# Interactive scaffold (prompts for objectives, skills, tools, and context/data)
uv run openhydra agent scaffold --interactive
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

## Contributing

See `CONTRIBUTING.md` for the contributor workflow, checks, and PR requirements.

## Configuration

OpenHydra loads config in this order:
1. `.openhydra/openhydra.yaml` (project-local)
2. `~/.openhydra/openhydra.yaml` (user-global)
3. Environment variables (override specific fields)

To enable channels, create `.openhydra/openhydra.yaml` like:

```yaml
web:
  host: "127.0.0.1"
  port: 7070

channels:
  slack:
    enabled: false
  discord:
    enabled: false
  whatsapp:
    enabled: false
  email:
    enabled: false
```

Example: enable Slack + WhatsApp (Baileys):
```yaml
channels:
  slack:
    enabled: true
  whatsapp:
    enabled: true
    backend: "baileys"
```

## Channels (Web, Slack, Discord, WhatsApp, Email)

Start all enabled channels with:
```bash
uv run openhydra serve
```

When you submit a task via a channel, progress updates and the final result are delivered back to the same channel thread/DM/conversation by default.

- Web API examples:
```bash
# List workflows (requires API key)
curl -H "X-API-Key: <web.api_key>" http://127.0.0.1:7070/api/v1/workflows

# Stream events (WebSocket)
npx -y wscat -c "ws://127.0.0.1:7070/api/v1/ws?api_key=<web.api_key>"
```

- **Web API (default)**: REST + WebSocket event stream at `/api/v1/ws`. `serve` auto-generates `web.api_key` in `~/.openhydra/openhydra.yaml` if missing. Use `X-API-Key: <key>` for REST, and `?api_key=<key>` for WebSocket.
- **Slack (Socket Mode)**: set `channels.slack.enabled: true`, plus `OPENHYDRA_SLACK_BOT_TOKEN` (`xoxb-...`) and `OPENHYDRA_SLACK_APP_TOKEN` (`xapp-...`). For access control, set `channels.slack.allowed_users` or pre-authorize via `openhydra auth add slack:<U123...>`.
- **Discord**: set `channels.discord.enabled: true` and `OPENHYDRA_DISCORD_BOT_TOKEN`. Use `/hydra run <task>` in a server where the bot is installed. Restrict with `channels.discord.allowed_users` or `openhydra auth add discord:<user_id>`.
- **WhatsApp**
  - **Baileys (QR, local WhatsApp Web)**: set `channels.whatsapp.enabled: true`, `channels.whatsapp.backend: "baileys"`, and install the Node dep: `npm install @whiskeysockets/baileys`. Set `channels.whatsapp.auth_dir` (recommended) to avoid writing WhatsApp auth files into the repo. The QR payload is emitted as an event `whatsapp.qr` with `data.qr_data` on the WebSocket; render it as a QR code and scan in WhatsApp. Restrict with `channels.whatsapp.allowed_phones` or `openhydra auth add whatsapp:<phone>`.
  - **Cloud API (webhook)**: set `channels.whatsapp.backend: "cloud-api"`, configure `channels.whatsapp.phone_number_id` + `channels.whatsapp.verify_token`, and set `OPENHYDRA_WHATSAPP_ACCESS_TOKEN`. Expose the web server publicly and register the webhook at `https://<public-host>/webhooks/whatsapp`.
- **Email (IMAP + SMTP)**: install deps with `uv pip install -e ".[email]"`, set `channels.email.enabled: true`, and configure IMAP/SMTP + credentials (env vars like `OPENHYDRA_EMAIL_IMAP_HOST`, `OPENHYDRA_EMAIL_USERNAME`, `OPENHYDRA_EMAIL_PASSWORD`). Actionable emails are submitted as workflows, and terminal results are emailed back to the sender.

## Custom Channels

You can add channels (e.g. SMS, Teams) as external plugins via the `openhydra.channels` Python entry point group. Config for unknown channel keys under `channels:` is loaded into `channels.extras` and passed to the plugin factory.

Example:
```yaml
channels:
  sms:
    enabled: true
    permissions:
      can_submit: true
      can_read_status: true
```

## Architecture

- **Pluggable agents** — Claude, OpenAI, Ollama, or bring your own
- **Pluggable memory** — SQLite (default), Qdrant, ChromaDB
- **Pluggable skills** — Filesystem, Git repos, HTTP registries
- **Dynamic skill generation (optional)** — When enabled, a missing skill can be generated on-the-fly via LLM, scored with a quality gate, and cached for reuse
- **Separate interfaces** — CLI, TUI, Web UI are independent of the core engine

## Dynamic Skills

OpenHydra can generate skills at runtime when a workflow references a skill ID that doesn't exist on disk. The `SkillBuilder` uses an LLM to create a `SKILL.md` + `metadata.yaml`, scores the output with a heuristic quality rubric, and writes it to `~/.openhydra/generated_skills/` for reuse.

```yaml
# openhydra.yaml — skill builder config
skills:
  builder_enabled: true          # default: false
  generated_dir: ""              # default: ~/.openhydra/generated_skills/
```

Enable with `builder_enabled: true` if you want on-the-fly generation.

## Documentation

- [README.md](README.md) — install, run, core configuration, and channel setup.
- [SPEC.md](SPEC.md) — architecture, protocols, and extension APIs.
- [PLAN.md](PLAN.md) — implementation roadmap and phase status.
- [CLAUDE.md](CLAUDE.md) — maintainer conventions and project notes.
- [AGENTS.md](AGENTS.md) — repository contribution and workflow guidelines.
- [config/roles.yaml](config/roles.yaml) — default role catalog and gate configuration.

## Extension Point Docs

- Channels/plugins: [Custom Channels](README.md#custom-channels), [entry point group](pyproject.toml)
- Agent providers: [Agent Registry](SPEC.md#32-agent-registry), [custom provider example](SPEC.md#9-extension-points)
- Skill sources + builder: [Skill Registry](SPEC.md#33-skill-registry), [Dynamic Skills](README.md#dynamic-skills)
- Memory backends: [Memory Adapter](SPEC.md#34-memory-adapter), [custom memory example](SPEC.md#9-extension-points)
- Roles + gates: [Role Catalog](SPEC.md#35-role-catalog), [Quality Gates](SPEC.md#36-quality-gates), [default roles](config/roles.yaml)
- MCP tool servers/templates: [tools config schema](src/openhydra/config.py), [built-in MCP templates](src/openhydra/tools/mcp_templates.py)

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
