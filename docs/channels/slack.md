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
2. Create an app-level token with `connections:write` scope (`xapp-...`).
3. Enable **Socket Mode** for the app.
4. In **App Home**, enable the **Messages Tab** so users can DM the bot.
5. In **Event Subscriptions**, enable events and subscribe to bot events:
   - `app_mention`
   - `message.im`
6. Under **OAuth & Permissions**, add bot token scopes:
   - `app_mentions:read`
   - `im:history`
   - `chat:write`
7. Install/reinstall the app to workspace and copy the bot token (`xoxb-...`).

Notes:

1. The scope/event set above is the minimum for OpenHydra's default Slack behavior
   (DMs + `@mention` tasks).
2. `channels:history`, `groups:history`, and `mpim:history` are not required unless you
   explicitly extend your app to consume those message event types.

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
