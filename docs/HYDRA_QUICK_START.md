# Hydra Launcher - Quick Start

## TL;DR

```bash
hydra              # Start OpenHydra server & open web UI
```

That's it! The command is idempotent — run it anytime to access your OpenHydra instance.

---

## Commands

| Command | What it does |
|---------|-------------|
| `hydra` | Start server (if needed) & open browser |
| `hydra-status` | Check if running |
| `hydra-stop` | Stop server |
| `hydra-restart` | Restart server |
| `hydra-logs` | View last 50 log lines |
| `hydra-logs -f` | Follow logs in real-time |

---

## First Time Setup

The alias is already configured! It was added to your `~/.zshrc`:

```bash
# OpenHydra launcher
[ -f ~/.openhydra/aliases.sh ] && source ~/.openhydra/aliases.sh
```

### For Current Terminal Session

If you just installed, load it now:

```bash
source ~/.openhydra/aliases.sh
```

### For New Terminals

Just type `hydra` — it's ready to go! ✅

---

## How It Works

```bash
$ hydra
⚙ Starting OpenHydra server...
⏳ Waiting for server health check...
.......✓ Server ready!
  Server PID: 12345
  Web UI: http://127.0.0.1:7070
  Logs: ~/.openhydra/server.log
```

Your browser opens automatically to http://127.0.0.1:7070

### Running It Again

```bash
$ hydra
✓ OpenHydra server already running at http://127.0.0.1:7070
```

No duplicate servers! It detects the existing instance and just opens the browser.

---

## Configuration

### Custom Port

```bash
# Temporary
OPENHYDRA_WEB_PORT=8080 hydra

# Permanent
echo 'export OPENHYDRA_WEB_PORT=8080' >> ~/.zshrc
```

### Custom Host (for remote access)

```bash
OPENHYDRA_WEB_HOST=0.0.0.0 hydra
```

---

## Typical Usage

### Daily Workflow

```bash
# Start your work session
hydra

# ... use OpenHydra all day via web UI ...

# Stop when done (optional — runs in background)
hydra-stop
```

### Development

```bash
# Start server
hydra

# Edit code, then restart to apply changes
hydra-restart

# Watch logs while testing
hydra-logs -f
```

### Check What's Running

```bash
hydra-status
```

Output:
```
OpenHydra Server Status:
  URL: http://127.0.0.1:7070
  Status: ✓ Running
  PID: 12345

Recent logs (last 5 lines):
[log output...]
```

---

## Troubleshooting

### Server Won't Start

```bash
# Check logs for errors
hydra-logs

# Check if port is already in use
lsof -ti :7070
```

### Can't Stop Server

```bash
# Force kill by port
lsof -ti :7070 | xargs kill -9

# Clean up PID file
rm ~/.openhydra/server.pid
```

### Health Check Times Out

```bash
# Watch startup logs in real-time
tail -f ~/.openhydra/server.log
```

---

## Files

| Path | Purpose |
|------|---------|
| `~/.openhydra/aliases.sh` | Alias definitions |
| `~/.openhydra/server.log` | Server logs |
| `~/.openhydra/server.pid` | Process ID |
| `~/.openhydra/openhydra.yaml` | Configuration |

---

## More Info

- **Full Guide:** [docs/quick-launcher-guide.md](quick-launcher-guide.md)
- **Test Report:** [docs/hydra-alias-test-report.md](hydra-alias-test-report.md)
- **Verification Summary:** [docs/hydra-alias-verification-summary.md](hydra-alias-verification-summary.md)

---

**Quick Reference Card:**

```bash
hydra              # Start & open
hydra-status       # Check status
hydra-logs         # View logs
hydra-logs -f      # Follow logs
hydra-restart      # Restart
hydra-stop         # Stop
```

Happy coding! 🚀
