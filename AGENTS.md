# Repository Guidelines

## Project Structure
- `src/openhydra/`: core engine + built-in adapters (`workflow/`, `agents/`, `skills/`, `memory/`, `tools/`, `channels/`, `gates/`).
- `src/openhydra/cli/`: Typer CLI entrypoints (`openhydra ...`).
- `config/roles.yaml`: role catalog/config (roles are data, not code).
- `skills/`: bundled starter skills (`SKILL.md` + `metadata.yaml`).
- `tests/`: pytest suite (`test_*.py`).
- `SPEC.md` / `PLAN.md` / `CLAUDE.md`: architecture notes and conventions.

## Build, Test, and Development Commands
```bash
# Install (editable, minimal)
uv pip install -e .

# Recommended first-run setup + diagnostics
uv run openhydra onboard
uv run openhydra doctor

# Optional: full interactive setup + optional providers/channels
uv run openhydra init
uv pip install -e ".[all]"

# CLI help / run a one-off workflow
uv run openhydra --help
uv run openhydra run "Build a Python CLI that converts CSV to JSON"

# Serve engine + enabled channels (web/Slack/Discord/WhatsApp/email if configured)
uv run openhydra serve --host 127.0.0.1 --port 7070

# Tests + lint
uv run pytest
uv run ruff check src/ tests/
```

## Architecture & Coding Conventions
- Keep the engine interface-agnostic: interfaces/channels consume it via events + APIs.
- Adapters use `Protocol` interfaces (not ABCs) and should remain swappable.
- Durability: write workflow state to SQLite before executing steps.
- Skills are files (`SKILL.md` + `metadata.yaml`); optional `SkillBuilder` can generate skills when enabled (`skills.builder_enabled`, default `false`).
- Channels are pluggable: external adapters can be shipped via the `openhydra.channels` entry point group.
- Prefer `async`/`await` for I/O; use `dataclass` or Pydantic `BaseModel` for DTOs.
- Ruff is the linter; 100-char lines (see `pyproject.toml`).

## Testing Guidelines
- Framework: `pytest` (asyncio mode is `auto`).
- Name tests `tests/test_*.py`; add regression coverage for bug fixes.
- Run a focused subset with `uv run pytest tests/test_cli.py -k doctor`.

## WhatsApp Support (Optional)
- This repo includes a WhatsApp channel with two backends:
- `baileys` (default): WhatsApp Web via a Node.js subprocess + QR login. Requires `node` and `npm install @whiskeysockets/baileys` somewhere above `src/` so `bridge.js` can `require()` it.
- `cloud-api`: Meta WhatsApp Cloud API via webhook routes at `/webhooks/whatsapp` on the web channel.
- Access is enforced via allowlist (`channels.whatsapp.allowed_phones`) or auth store (`openhydra auth add whatsapp:<phone>`).

## Commit & Pull Request Guidelines
- Use Conventional Commit-style subjects (seen in history): `feat: ...`, `fix: ...`, `chore: ...`.
- PRs should include: clear description, rationale, test plan/results, and any config/env changes.
- Do not commit secrets; prefer env vars (e.g. `OPENHYDRA_WEB_API_KEY`, `OPENHYDRA_STATE_DIR`) and local config files (`.openhydra/openhydra.yaml`, `~/.openhydra/openhydra.yaml`).
