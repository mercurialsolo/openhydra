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

# Optional: strict diagnostics (treat warnings as failures)
uv run openhydra doctor --strict

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

## OpenHydra is best for work that needs:


- planning with dependencies, checks, and retries
- using multiple tools (code, tests, docs, browser/search, channels)
- selection of the right role, tools, and skills instead of one fixed script

Personal planning and assistant tasks:
- `"Plan my Tokyo trip from May 12-20: flights from SFO, vegetarian options near Shinjuku, and a day-by-day itinerary under $3,500"`
- `"Build my next 6-week personal operating plan: gym 4x/week, finish two certifications, and keep Sundays blocked for family"`
- `"Organize my monthly admin stack: rent, taxes, insurance renewals, and reminders with due dates and fallback actions"`

Research for you:
- `"For our seed-stage B2B SaaS (ACV ~$8k), compare 6 competitors' pricing and positioning, then produce a differentiated GTM brief with sources"`
- `"Review our last 120 support tickets and 40 churn notes, cluster root causes, and propose the top 5 retention experiments by expected impact"`
- `"Prepare a launch-readiness compliance brief for our AI meeting assistant (US + EU): likely legal risks, mitigations, and questions for counsel"`
- `"Evaluate expansion options across Texas, Florida, and Ontario using market size, regulatory friction, and hiring costs; recommend one for Q3"`
- `"Compare open-source LLM eval frameworks for our RAG product, rank tradeoffs, and produce a recommendation memo with implementation implications"`
- `"Review open GitHub issues for our checkout service, cluster duplicate themes, and propose a prioritized 2-sprint stabilization plan"`
- `"Screen US large-cap stocks, liquid call options, and top Polymarket contracts for this week; recommend 3 risk-defined opportunities with thesis, catalysts, downside case, and confidence score"`
- `"Find the best recent papers on hierarchical reasoning for agentic products, rank the top 10 by practical relevance, and summarize what we can implement in our roadmap next sprint"`

Build software products:
- `"Define and deliver v1 team invites for our app: PRD, rollout plan, implementation, and validation tests"`
- `"Migrate our Flask billing API to FastAPI without breaking existing /v1 endpoints or auth behavior, then prove parity with tests"`
- `"Add Google and GitHub OAuth to our web app, preserve existing session behavior, and add integration coverage for login + callback flows"`
- `"Find and fix intermittent checkout timeouts seen in production logs, then add a regression test that reproduces the original failure"`
- `"Audit dependencies for known CVEs, patch low-risk updates, and publish a release-risk summary with test results"`
- `"Generate a weekly engineering readiness report for our team covering test health, dependency drift, incident carryover, and release blockers"`

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
