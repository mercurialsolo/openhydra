# Advanced / Learn More

This document holds deeper topics that are intentionally not expanded in `README.md`.

## Configuration

Use [SETUP.md](../SETUP.md) for the full configuration reference.
Use [API and Auth Guide](api-auth.md) when integrating OpenHydra into your own product over
REST/WebSocket.

Key points:

1. Config precedence:
   - `.openhydra/openhydra.yaml` (project-local)
   - `~/.openhydra/openhydra.yaml` (user-global)
   - environment variables (override selected fields)
2. Full categories: engine, agents, memory, skills, tools, web, channels, heartbeat.
3. Validation: run `uv run openhydra doctor` or `uv run openhydra doctor --strict`.

## Architecture

OpenHydra architecture is designed for local-first orchestration:

1. Pluggable agent providers (Claude, OpenAI, etc.)
2. Pluggable memory backends (SQLite by default)
3. Pluggable skill sources (filesystem/git/http)
4. Optional dynamic skill generation
5. Separate interfaces (CLI, TUI, Web, messaging channels) over one engine

For protocol-level details, see [SPEC.md](../SPEC.md).

## Custom Channels

You can add channels (e.g. SMS, Teams) as external plugins via the `openhydra.channels` entry point group.
Unknown channel keys under `channels:` are loaded into `channels.extras` and passed to plugin factories.

Example config:

```yaml
channels:
  sms:
    enabled: true
    permissions:
      can_submit: true
      can_read_status: true
```

Entry point declaration example:

```toml
[project.entry-points."openhydra.channels"]
sms = "yourpkg.channels.sms:create_channel"
```

## Dynamic Skills

OpenHydra can generate a missing skill at runtime using `SkillBuilder`.
Generated skills are scored and saved for reuse.

Example:

```yaml
skills:
  builder_enabled: true
  generated_dir: ""  # defaults to ~/.openhydra/generated_skills/
```

Use this when you want adaptive skill coverage without pre-authoring every skill file.

## OpenClaw Integration

The [OpenClaw](https://github.com/nicepkg/openclaw) plugin can run OpenHydra as a managed child process.

Example:

```yaml
plugins:
  entries:
    openhydra:
      enabled: true
      config:
        managed: true
        pythonPath: "uv"
```

In managed mode, the plugin starts `openhydra serve`, waits for health readiness, reads the API key, and connects to the event stream.

## API Embedding (REST/WebSocket)

Run OpenHydra as a backend service:

```bash
openhydra serve --host 0.0.0.0 --port 7070
```

Or in Docker:

```bash
# Set OPENHYDRA_WEB_API_KEY in your shell/secret manager first.
docker run --rm -p 7070:7070 --env OPENHYDRA_WEB_API_KEY ghcr.io/mercurialsolo/openhydra:latest
```

Auth supports:

1. `X-API-Key` header
2. Bearer token from `/api/v1/auth/login`

For endpoint examples and auth flows, see [API and Auth Guide](api-auth.md).
