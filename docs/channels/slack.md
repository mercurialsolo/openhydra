# Slack Setup (Socket Mode)

Use this guide to connect OpenHydra to Slack with Socket Mode.

## Prerequisites

1. OpenHydra installed locally.
2. Channel dependencies installed:

```bash
uv pip install -e ".[slack]"
```

## Step 1: Create and Configure a Slack App

1. Create a new app in your Slack workspace.
2. Enable **Socket Mode** for the app.
3. Create an app-level token with `connections:write` scope (`xapp-...`).
4. Under **OAuth & Permissions**, add bot token scopes:
   - `app_mentions:read`
   - `channels:history`
   - `groups:history`
   - `im:history`
   - `mpim:history`
   - `chat:write`
5. Install/reinstall the app to workspace and copy the bot token (`xoxb-...`).

## Step 2: Set Required Environment Variables

```bash
export OPENHYDRA_SLACK_BOT_TOKEN=xoxb-...
export OPENHYDRA_SLACK_APP_TOKEN=xapp-...
```

## Step 3: Enable Slack Channel in Config

Edit `.openhydra/openhydra.yaml` or `~/.openhydra/openhydra.yaml`:

```yaml
channels:
  slack:
    enabled: true
    allowed_users: []  # optional allowlist; empty means allow all
```

## Step 4: Validate and Start

```bash
uv run openhydra doctor --strict
uv run openhydra serve
```

## Step 5: Verify in Slack

1. Send a DM to the bot with a task.
2. Or `@mention` the bot in a channel with a task.
3. Confirm progress and completion updates appear in-thread.

## Optional Access Control

1. Restrict by user IDs in config:

```yaml
channels:
  slack:
    enabled: true
    allowed_users: ["U12345678"]
```

2. Or authorize users dynamically:

```bash
uv run openhydra auth add slack:U12345678
```
