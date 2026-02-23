# OpenHydra Quick Launcher Guide

The `hydra` alias provides a one-command way to start and manage your OpenHydra server.

## Installation

The launcher was automatically configured during setup. It's sourced in your `~/.zshrc`:

```bash
# OpenHydra launcher
[ -f ~/.openhydra/aliases.sh ] && source ~/.openhydra/aliases.sh
```

For a new terminal session, just type `hydra` — it's ready to go!

For your **current** terminal session:
```bash
source ~/.openhydra/aliases.sh
```

## Commands

### Start Server & Open UI
```bash
hydra
```

This single command:
1. ✅ Checks if server is already running (via health check)
2. 🚀 Starts server in background if needed
3. ⏳ Waits for server to be ready (up to 60s)
4. 🌐 Opens web UI in your default browser

**Idempotent:** Running `hydra` multiple times won't create duplicate servers!

### Check Status
```bash
hydra-status
```

Shows:
- Server running status
- Current URL
- Process ID (if running)
- Recent logs (last 5 lines)

### View Logs
```bash
# Last 50 lines
hydra-logs

# Follow in real-time
hydra-logs -f
```

### Stop Server
```bash
hydra-stop
```

Cleanly stops the OpenHydra server and removes the PID file.

### Restart Server
```bash
hydra-restart
```

Stops and restarts the server in one command.

## Configuration

### Custom Port
```bash
# Temporary
OPENHYDRA_WEB_PORT=8080 hydra

# Permanent (add to ~/.zshrc)
export OPENHYDRA_WEB_PORT=8080
```

### Custom Host
```bash
# Bind to all interfaces (for remote access)
OPENHYDRA_WEB_HOST=0.0.0.0 hydra
```

## Files

| Path | Purpose |
|------|---------|
| `~/.openhydra/aliases.sh` | Shell function definitions |
| `~/.openhydra/server.log` | Server output logs |
| `~/.openhydra/server.pid` | Running server process ID |
| `~/.openhydra/openhydra.yaml` | Main configuration file |

## Typical Workflows

### Daily Use
```bash
# Morning: start server
hydra

# ... work in web UI all day ...

# Evening: stop server (optional - it runs in background)
hydra-stop
```

### Development
```bash
# Start server
hydra

# Make code changes...

# Restart to apply changes
hydra-restart

# Monitor logs
hydra-logs -f
```

### Troubleshooting

**Server won't start:**
```bash
# Check logs for errors
hydra-logs

# Check if port is in use
lsof -ti :7070
```

**Health check times out:**
```bash
# Watch startup in real-time
tail -f ~/.openhydra/server.log
```

**Server won't stop:**
```bash
# Force kill
lsof -ti :7070 | xargs kill -9
rm ~/.openhydra/server.pid
```

## How It Works

### Smart Detection

The `hydra` command checks if a server is already running by calling the health endpoint:

```bash
curl -s -f --max-time 1 http://127.0.0.1:7070/api/v1/health
```

- If it responds → connects to existing server
- If it doesn't respond → starts new server

This approach is:
- ✅ **Reliable** - HTTP health check is authoritative
- ✅ **Fast** - 1-second timeout prevents hang
- ✅ **Safe** - Won't create duplicates

### Browser Opening

Platform-agnostic browser opening:
- **macOS:** `open` command
- **Linux:** `xdg-open` or `sensible-browser`
- **Windows:** `start` command

### Process Management

The stop command has fallback strategies:
1. Try PID file first (fast)
2. Find process by port with `lsof` (reliable)
3. Find by process name with `pkill` (last resort)

## Advanced Usage

### Run on Custom Port Temporarily
```bash
OPENHYDRA_WEB_PORT=9000 hydra
# Server starts on port 9000
# Next 'hydra' call will use default 7070 again
```

### Multiple Instances (Not Recommended)
```bash
# Terminal 1
OPENHYDRA_WEB_PORT=7070 hydra

# Terminal 2
OPENHYDRA_WEB_PORT=8080 hydra
```

Note: The PID file only tracks one instance. Use separate config files for true multi-instance setups.

## Testing

A comprehensive test suite is available at `/tmp/test_hydra_final.sh`:

```bash
/tmp/test_hydra_final.sh
```

This tests:
- Fresh start from stopped state
- Health endpoint response
- Idempotency (no duplicate servers)
- Helper commands (status, logs)
- Clean shutdown

All tests pass ✅

## Related Documentation

- **Full Test Report:** [docs/hydra-alias-test-report.md](hydra-alias-test-report.md)
- **API & Auth Guide:** [docs/api-auth.md](api-auth.md)
- **Setup Guide:** [SETUP.md](../SETUP.md)

---

**Quick Reference:**

```bash
hydra              # Start & open UI
hydra-status       # Check status
hydra-logs         # View logs
hydra-logs -f      # Follow logs
hydra-restart      # Restart
hydra-stop         # Stop
```
