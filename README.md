# OpenHydra

Lightweight, local-first multi-agent orchestration. One command, no Docker, no external services.

## Quick Start

```bash
# Install
uv pip install -e .

# Recommended: quick onboarding (writes ~/.openhydra/openhydra.yaml with safe defaults)
uv run openhydra onboard

# Validate setup and channel/provider prerequisites
uv run openhydra doctor

# Run a one-off workflow
uv run openhydra run "Build a Python CLI that converts CSV to JSON"

# Optional: full interactive setup (providers/tools/channels)
uv run openhydra init

# Optional: install channel/web extras before serving
uv pip install -e ".[all]"

# Run the server (web API + any enabled channels)
uv run openhydra serve

# Scaffold a new role agent in config/roles.yaml
uv run openhydra agent scaffold eng.docs --description "Writes implementation docs"

# Interactive scaffold (prompts for objectives, skills, tools, and context/data)
uv run openhydra agent scaffold --interactive
```

Need full setup and configuration details (all settings, env vars, and customization points)?
See [SETUP.md](SETUP.md).

### Setup Doctor

Validate your local runtime, default provider, and enabled channel prerequisites:

```bash
# normal mode (fails only on hard errors)
uv run openhydra doctor

# strict mode (warnings also fail)
uv run openhydra doctor --strict
```

## OpenHydra is best for work that needs:


- planning with dependencies, checks, and retries
- using multiple tools (code, tests, docs, browser/search, channels)
- selection of the right role, tools, and skills instead of one fixed script

Real tasks by group:

Personal planning and assistant tasks:
- `"Coordinate a multi-city business trip with budget/time constraints and produce a day-by-day itinerary"`
- `"Build a 90-day personal execution plan with weekly goals, risks, and accountability checkpoints"`
- `"Plan a month of travel, health, and admin tasks around fixed calendar constraints and priorities"`

Work tasks: research and decision support first:
- `"Research competitors in the US billing software market, compare pricing/positioning, and produce a GTM brief with sources"`
- `"Analyze customer feedback across support channels, cluster churn drivers, and propose top retention experiments"`
- `"Map legal/compliance considerations for launching an AI feature, summarize risk areas, and draft counsel questions"`
- `"Assess economic and regulatory opportunity across target regions and recommend where to expand next quarter"`
- `"Compare open-source eval frameworks for LLM apps, rank tradeoffs, and produce a recommendation memo with links"`
- `"Review open GitHub issues, cluster duplicates/themes, and propose a prioritized sprint plan"`

Work tasks: product development and coding execution:
- `"Define v1 scope for a customer portal, set success metrics, and sequence a cross-functional launch timeline"`
- `"Draft a PRD for team invites, implement the MVP, and validate with tests"`
- `"Add OAuth login with Google and GitHub, wire session handling, and add tests"`
- `"Migrate this Flask API to FastAPI without breaking existing endpoints"`
- `"Find and fix the intermittent checkout timeout and add regression coverage"`
- `"Audit dependencies for known CVEs, patch low-risk updates, and verify with tests"`
- `"Create a weekly maintenance report covering test health, dependency drift, and release readiness"`

## Talk To OpenHydra Agents From Any Channel

OpenHydra runs one orchestration engine and lets you talk to it from multiple channels.
You can submit work from Web, Slack, WhatsApp, or Discord, and get progress/final updates back in that channel.

Basic flow:

1. Enable the channels you want in `.openhydra/openhydra.yaml`
2. Start the server with `uv run openhydra serve`
3. Send your task from your preferred channel

Step-by-step channel setup guides:

- [Slack setup](docs/channels/slack.md)
- [WhatsApp setup](docs/channels/whatsapp.md)
- [Discord setup](docs/channels/discord.md)

Example channel config:

```yaml
web:
  enabled: true
  host: "127.0.0.1"
  port: 7070

channels:
  slack:
    enabled: true
  whatsapp:
    enabled: true
```

How to talk to agents:

- **Web**: submit tasks via REST (`POST /api/v1/workflows`) and watch events on WebSocket (`/api/v1/ws`)
- **Slack**: send a DM to the bot or `@mention` it in a channel with your task text
- **WhatsApp**: send a normal message as the task text; control commands like `approve`, `reject <reason>`, `pause`, `resume`, `cancel` are supported. On first setup, `openhydra serve` prints the pairing QR in terminal.
- **Discord**: run `/hydra` with `action=run` and your task as `argument`

## Planning On The Fly (No Manual Plan File)

You do not need to write a plan first. Submit the outcome directly:

```bash
uv run openhydra run "Migrate this Flask API to FastAPI without breaking existing endpoints" --watch
```

OpenHydra then:

1. Uses the `planner` role to generate a JSON step graph (`role_id`, `instructions`, `depends_on`)
2. Persists workflow + steps to SQLite before running (for durability/recovery)
3. Executes ready steps based on dependencies (independent branches can run concurrently)
4. Applies role gates (quality/tests/approval) between steps
5. Reports progress/events and final output

For that FastAPI migration prompt, a typical generated plan could look like:

1. `eng.init`: inventory current Flask routes and migration constraints
2. `eng.implement`: port app structure and handlers to FastAPI
3. `test.code`: run/update tests and validate endpoint compatibility
4. `pm.review`: verify scope completion and release readiness

To inspect the generated plan and step-by-step progress:

```bash
uv run openhydra status <workflow_id>
```

## Contributing

See `CONTRIBUTING.md` for the contributor workflow, checks, and PR requirements.

## Learn More

- [SETUP.md](SETUP.md) — complete setup and configuration reference.
- [Advanced / Learn More](docs/learn-more.md) — configuration model, architecture, custom channels, dynamic skills, and OpenClaw integration.
- Channel setup playbooks:
  - [Slack](docs/channels/slack.md)
  - [WhatsApp](docs/channels/whatsapp.md)
  - [Discord](docs/channels/discord.md)
- [SPEC.md](SPEC.md) — architecture, protocols, and extension APIs.
- [PLAN.md](PLAN.md) — implementation roadmap and phase status.
- [CLAUDE.md](CLAUDE.md) — maintainer conventions and project notes.
- [AGENTS.md](AGENTS.md) — repository contribution and workflow guidelines.
- [config/roles.yaml](config/roles.yaml) — default role catalog and gate configuration.

## Status

Early development. See PLAN.md for current phase.
