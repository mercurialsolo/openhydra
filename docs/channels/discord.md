# Discord Setup

Use this guide to connect OpenHydra to Discord.
If you only need REST/WebSocket app integration (no Discord), use [API and Auth Guide](../api-auth.md).

## Prerequisites

1. OpenHydra installed locally.
2. Discord dependencies installed:

```bash
uv pip install -e ".[discord]"
```

## Step 1: Create and Configure a Discord Bot

1. Create an application in the Discord Developer Portal.
2. Add a bot user and copy its token.
3. Enable **Message Content Intent** for the bot.
4. Invite the bot to your server with scopes:
   - `bot`
   - `applications.commands`

## Step 2: Set Required Environment Variable

```bash
export OPENHYDRA_DISCORD_BOT_TOKEN=...
```

## Step 3: Enable Discord Channel in Config

Edit `.openhydra/openhydra.yaml` or `~/.openhydra/openhydra.yaml`:

```yaml
channels:
  discord:
    enabled: true
    allowed_users: []  # optional allowlist; empty means allow all
```

## Step 4: Validate and Start

```bash
uv run openhydra doctor --strict
uv run openhydra serve
```

## Step 5: Verify in Discord

1. In a server where the bot is installed, run:

```text
/hydra action:run argument:"Investigate flaky tests and propose fixes"
```

2. Confirm progress and completion messages appear in the same channel/thread context.

Supported slash actions:

1. `run`
2. `status`
3. `approve`
4. `reject`
5. `pause`
6. `resume`
7. `cancel`

## Optional Access Control

Restrict by Discord user IDs:

```yaml
channels:
  discord:
    enabled: true
    allowed_users: ["123456789012345678"]
```

Or authorize dynamically:

```bash
uv run openhydra auth add discord:123456789012345678
```
