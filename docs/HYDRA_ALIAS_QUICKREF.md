# OpenHydra `hydra` Alias - Quick Reference

## Installation Status

✅ **Already installed and configured!**

- Aliases: `~/.openhydra/aliases.sh`
- Shell: `~/.zshrc` (auto-loads aliases)
- Docs: `~/.openhydra/README.md`

## Quick Start

```bash
# Start server + open browser
hydra

# That's it! Server runs in background.
```

## All Commands

| Command | What It Does |
|---------|--------------|
| `hydra` | Start server (if needed) & open browser |
| `hydra-status` | Check if server is running |
| `hydra-stop` | Stop the server |
| `hydra-restart` | Restart the server |
| `hydra-logs` | Show last 50 log lines |
| `hydra-logs -f` | Follow logs in real-time |

## Common Tasks

### Daily Usage
```bash
# Morning: start server
hydra

# ... work in browser ...

# Evening: stop server (optional - runs in background)
hydra-stop
```

### Troubleshooting
```bash
# Check if running
hydra-status

# View logs
hydra-logs

# Full restart
hydra-restart

# Manual health check
curl http://127.0.0.1:7070/api/v1/health
```

### Development Workflow
```bash
# Start server
hydra

# Make code changes...

# Restart to apply
hydra-restart

# Watch logs
hydra-logs -f
```

## Configuration

### Custom Port
```bash
# One-time
OPENHYDRA_WEB_PORT=8080 hydra

# Permanent
export OPENHYDRA_WEB_PORT=8080
hydra
```

### Custom Host
```bash
# Bind to all interfaces
OPENHYDRA_WEB_HOST=0.0.0.0 hydra
```

## Files

- **Aliases:** `~/.openhydra/aliases.sh`
- **Logs:** `~/.openhydra/server.log`
- **PID:** `~/.openhydra/server.pid`
- **Config:** `~/.openhydra/openhydra.yaml`
- **Docs:** `~/.openhydra/README.md`

## How It Works

1. Checks if server already running (`curl` health check)
2. If not running, starts in background (`nohup`)
3. Waits for health endpoint to respond (up to 60s)
4. Opens browser to http://127.0.0.1:7070
5. Returns (server keeps running in background)

## Idempotent

Running `hydra` multiple times is safe:
- If server running → Opens browser, exits
- If server stopped → Starts server, opens browser

**No duplicate processes created.**

## Verified

✅ Fully tested end-to-end  
✅ Production-ready  
✅ See: `docs/HYDRA_ALIAS_VERIFICATION.md`

## Pro Tips

💡 **Keep it running:** Server runs in background, no need to start/stop constantly  
💡 **Multiple terminals:** All share the same server instance  
💡 **Quick access:** Type `hydra` anytime to open UI  
💡 **Check logs:** Use `hydra-logs` if something seems wrong  
💡 **Clean shutdown:** Use `hydra-stop` instead of killing processes

---

**Need detailed help?** See `~/.openhydra/README.md`
