# OpenHydra Setup Guide

This is the complete setup and configuration reference for running OpenHydra locally.

Use this with the quick summary in `README.md`.

## How Users Communicate With OpenHydra

OpenHydra supports two operating modes:

1. **CLI mode** (simplest): submit work with `openhydra run "..."`
2. **Server/channels mode**: run `openhydra serve`, then submit work through:
   - Web API/WebSocket
   - Slack
   - Discord
   - WhatsApp
   - Email

If you are starting from zero, use CLI mode first and add channels later.

## Quick Setup Paths

### Path A: Local CLI Only (recommended first run)

```bash
# Install minimal deps
uv pip install -e .

# Generate defaults
uv run openhydra onboard

# Validate provider/runtime setup
uv run openhydra doctor

# Run a task
uv run openhydra run "Build a Python CLI that converts CSV to JSON"
```

### Path B: Server + Channels

```bash
# Install with optional providers/channels
uv pip install -e ".[all]"

# Full setup wizard (providers/tools/channels prompts)
uv run openhydra init

# Validate strict setup (warnings fail)
uv run openhydra doctor --strict

# Start web server + enabled channels
uv run openhydra serve
```

### Path C: Slack/Email Auto-Response + Browser Research

Use this when you want OpenHydra to ingest inbound Slack/email tasks, do web/browser
research, and post results back to the originating channel.

```yaml
# ~/.openhydra/openhydra.yaml
agents:
  default_provider: "claude-sdk"   # recommended for MCP browser/search orchestration

tools:
  templates:
    browser: ["playwright"]
    search: "duckduckgo"

channels:
  slack:
    enabled: true
  email:
    enabled: true
    imap_host: "imap.example.com"
    smtp_host: "smtp.example.com"
    username: "agent@example.com"
    auth_method: "password"
    poll_interval_seconds: 60
    allowed_senders: ["your-company.com"]
```

```bash
# Required channel credentials
export OPENHYDRA_SLACK_BOT_TOKEN=...
export OPENHYDRA_SLACK_APP_TOKEN=...
export OPENHYDRA_EMAIL_PASSWORD=...

# Optional for provider auth (if needed in your environment)
export ANTHROPIC_API_KEY=...

uv pip install -e ".[all]"
uv run openhydra doctor --strict
uv run openhydra serve
```

Notes:

1. Slack DMs/@mentions are submitted as workflows and replies are posted in thread.
2. Email polls inbox, classifies actionable messages, submits workflows, and emails terminal results.
3. Browser/search templates resolve to MCP tools used by role tool aliases (`WebSearch`, `BrowserNavigate`, etc.).
4. Default role catalog includes `research` for web/browser-heavy tasks.

## What Onboarding Creates

`openhydra onboard` / `openhydra init` creates and/or updates:

- `~/.openhydra/openhydra.yaml` (main config)
- `~/.openhydra/ASSISTANT.md` (default behavior guidance if missing)

At runtime OpenHydra also creates state files under `engine.state_dir` (default `~/.openhydra`), including SQLite DB files.

## Configuration File Locations and Precedence

Config is loaded in this order:

1. `.openhydra/openhydra.yaml` (project-local)
2. `~/.openhydra/openhydra.yaml` (user-global)
3. environment variables (override specific fields)

This allows:

- global defaults in home config
- per-project overrides in repo-local config
- CI/runtime overrides via env vars

## Configuration Categories (High-Level)

These top-level sections come from `OpenHydraConfig` in `src/openhydra/config.py`:

1. `engine` - local runtime behavior and state paths
2. `agents` - model/provider selection and provider-specific settings
3. `memory` - memory backend and embedding settings
4. `skills` - skill sources and dynamic skill builder behavior
5. `tools` - MCP server registrations and templates
6. `web` - host/port/API key for the web interface
7. `channels` - Slack/Discord/WhatsApp/Email + channel runtime controls
8. `heartbeat` - recurring/active-hour automation behavior

## Detailed Settings

### 1) `engine`

Controls runtime concurrency, retries, and where state is stored.

```yaml
engine:
  state_dir: "~/.openhydra"
  max_concurrent_sessions: 2
  max_retries_per_step: 3
```

Notes:

- `max_concurrent_sessions` limits concurrent step execution in workflow DAGs.
- `max_retries_per_step` controls retry attempts for failed steps.

### 2) `agents`

Controls provider/runtime selection. Role behavior is separate (in `config/roles.yaml`).

```yaml
agents:
  default_provider: "claude-sdk"  # claude-sdk | codex-cli | anthropic-api | agent-sdk | custom
  providers:
    anthropic-api:
      model: "claude-sonnet-4-5-20250929"
      api_key: "${ANTHROPIC_API_KEY}"
```

Notes:

- `default_provider` picks the runtime backend used by role executions.
- Provider entries can override model/api/base_url for that provider.
- Built-in providers in this repo are `claude-sdk`, `anthropic-api`, `agent-sdk`, and
  `codex-cli`.

### 3) `memory`

Controls memory backend and embeddings.

```yaml
memory:
  backend: "sqlite"         # sqlite | qdrant | chroma | in-memory
  embedding_provider: "tfidf"
  sqlite_path: "~/.openhydra/memory.db"
  qdrant_url: "http://localhost:6333"
```

### 4) `skills`

Controls where skills come from and whether dynamic skill generation is enabled.

```yaml
skills:
  sources:
    - type: "filesystem"
      path: "./skills"
  builder_enabled: false
  generated_dir: "~/.openhydra/generated_skills"
  max_skills_per_role: 3
  builder_quality_threshold: 6
```

### 5) `tools`

MCP tool server config + defaults for browser/search template resolution.

```yaml
tools:
  templates:
    browser: ["claude-in-chrome", "playwright", "puppeteer"]
    search: "duckduckgo"   # tavily | duckduckgo | perplexity | none
  mcp_servers:
    - name: "playwright"
      transport: "stdio"   # stdio | sse
      command: "npx"
      args: ["-y", "@playwright/mcp@latest"]
```

### 6) `web`

Web API and WebSocket server settings.

```yaml
web:
  enabled: true
  host: "127.0.0.1"
  port: 7070
  api_key: ""  # auto-generated on `openhydra serve` if missing
```

### 7) `channels`

Messaging channel adapters and channel-level runtime controls.

```yaml
channels:
  debounce_delay_ms: 1500
  debounce_max_wait_ms: 5000
  approval_timeout_seconds: 120
  approval_timeout_action: "reject"  # reject | approve | ignore

  slack:
    enabled: false
    allowed_users: []

  discord:
    enabled: false
    allowed_users: []

  whatsapp:
    enabled: false
    backend: "baileys"      # baileys | cloud-api
    node_path: "node"
    auth_dir: "~/.openhydra/whatsapp_auth"
    allowed_phones: []

  email:
    enabled: false
    imap_host: ""
    imap_port: 993
    smtp_host: ""
    smtp_port: 587
    username: ""
    password: ""
    auth_method: "password" # password | oauth2
    mailbox: "INBOX"
    poll_interval_seconds: 60
    allowed_senders: []

  # External plugin channels:
  # sms:
  #   enabled: true
  #   permissions:
  #     can_submit: true
```

Channel-specific minimums:

1. Slack: `enabled=true` + bot/app tokens
2. Discord: `enabled=true` + bot token
3. WhatsApp Baileys: `enabled=true`, `backend=baileys`, Node/npm installed
   (OpenHydra auto-installs `@whiskeysockets/baileys` on first start)
4. WhatsApp Cloud API: web channel enabled + phone/verify/access token configured
5. Email: IMAP/SMTP host + username + auth credentials

### 8) `heartbeat`

Controls periodic autonomous execution and delivery windows.

```yaml
heartbeat:
  enabled: false
  interval_seconds: 300
  timezone: "America/New_York"
  active_hours_start: 8
  active_hours_end: 22
  delivery_channel: "slack"
  owner_id: "U123..."
```

## Environment Variable Reference

These are the main env vars currently supported by `load_config()` and channel/provider flows.

### Core Runtime

- `OPENHYDRA_STATE_DIR`
- `OPENHYDRA_MAX_CONCURRENT_SESSIONS`
- `OPENHYDRA_DEFAULT_PROVIDER`
- `OPENHYDRA_MEMORY_BACKEND`
- `OPENHYDRA_EMBEDDING_PROVIDER`
- `OPENHYDRA_WEB_PORT`
- `OPENHYDRA_WEB_API_KEY`

### Provider/Auth

- `ANTHROPIC_API_KEY` (used by Anthropic SDK/provider flows)
- `OPENAI_API_KEY` (used by OpenAI/Codex auth flows)

### Slack

- `OPENHYDRA_SLACK_BOT_TOKEN`
- `OPENHYDRA_SLACK_APP_TOKEN`

### Discord

- `OPENHYDRA_DISCORD_BOT_TOKEN`

### WhatsApp

- `OPENHYDRA_WHATSAPP_ACCESS_TOKEN` (cloud-api backend)

### Email

- `OPENHYDRA_EMAIL_IMAP_HOST`
- `OPENHYDRA_EMAIL_SMTP_HOST`
- `OPENHYDRA_EMAIL_USERNAME`
- `OPENHYDRA_EMAIL_PASSWORD`
- `OPENHYDRA_EMAIL_AUTH_METHOD`
- `OPENHYDRA_EMAIL_OAUTH_CLIENT_ID`
- `OPENHYDRA_EMAIL_OAUTH_CLIENT_SECRET`
- `OPENHYDRA_EMAIL_OAUTH_REFRESH_TOKEN`
- `OPENHYDRA_EMAIL_OAUTH_TOKEN_URI`

## Customization Points

### 1) Behavior Policy: `ASSISTANT.md`

Files:

1. `~/.openhydra/ASSISTANT.md` (global)
2. `.openhydra/ASSISTANT.md` (project-local)

Both are loaded and concatenated (global first, local second). This content is injected into role system prompts and can also define schedule/interests for agenda automation.

### 2) Base Role Agents: `config/roles.yaml`

This file defines role-level behavior:

- role IDs and descriptions
- model assignment
- allowed tools
- budgets
- gates

Use `openhydra agent scaffold ...` to add custom roles.

Default roles include:

1. `planner` (task decomposition)
2. `eng.init` (initial setup/planning)
3. `research` (web + browser research)
4. `eng.implement` (implementation)
5. `test.code` (validation/testing)
6. `pm.prd` / `pm.review` (product framing/review)

### 3) Skills

Customize via:

- local `skills/` directory
- `skills.sources` entries
- optional dynamic skill builder (`skills.builder_enabled`)

### 4) MCP Tools

Customize via:

- `tools.mcp_servers`
- `tools.templates.browser/search`

### 5) Channels and Auth

Customize:

- enabled channels in `channels.*`
- allowlists (`allowed_users`, `allowed_phones`, `allowed_senders`)
- interactive auth store (`openhydra auth ...`)

## Validation and Operations

Run these after config changes:

```bash
# Validate setup
uv run openhydra doctor
uv run openhydra doctor --strict

# Show merged runtime config summary
uv run openhydra config

# Start runtime
uv run openhydra serve

# Run single-shot CLI workflow
uv run openhydra run "Investigate flaky tests and propose fixes"
```

Workflow controls:

- `openhydra status <workflow_id>`
- `openhydra pause <workflow_id>`
- `openhydra resume <workflow_id>`
- `openhydra cancel <workflow_id>`

## Troubleshooting Quick Checks

1. Provider missing: run `openhydra doctor`, then install/provider-login as suggested.
2. Channel not receiving messages: verify `channels.<name>.enabled` and required tokens.
3. API key missing: `openhydra serve` will generate `web.api_key` if needed.
4. Long tasks stop after restart: ensure state dir persists (default `~/.openhydra`) so workflow auto-resume can recover.
