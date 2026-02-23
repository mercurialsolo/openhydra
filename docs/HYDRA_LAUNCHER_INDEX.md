# Hydra Launcher Documentation Index

This directory contains comprehensive documentation for the OpenHydra launcher (`hydra` alias).

## Quick Start

**New users start here:**
- 📘 [HYDRA_QUICK_START.md](HYDRA_QUICK_START.md) - Ultra-concise quick reference

**Just want to use it?**
```bash
hydra              # That's it!
```

---

## Documentation

### User Guides

1. **[HYDRA_QUICK_START.md](HYDRA_QUICK_START.md)** ⭐ Start here!
   - TL;DR usage
   - Quick command reference
   - Common workflows
   - Troubleshooting

2. **[quick-launcher-guide.md](quick-launcher-guide.md)** - Comprehensive guide
   - Detailed installation
   - Configuration options
   - Advanced usage
   - How it works under the hood

3. **[~/.openhydra/README.md](~/.openhydra/README.md)** - User-facing documentation
   - Installed on your system
   - Daily workflow examples
   - File locations
   - Pro tips

### Test Reports

1. **[hydra-alias-verification-summary.md](hydra-alias-verification-summary.md)** ⭐ Latest verification
   - Executive summary
   - End-to-end test results
   - Performance metrics
   - Production readiness assessment

2. **[hydra-alias-test-report.md](hydra-alias-test-report.md)** - Detailed test results
   - Individual test cases
   - Edge cases tested
   - Implementation details
   - Troubleshooting guide

3. **Legacy Test Reports** (archived)
   - HYDRA_ALIAS_TESTING.md
   - HYDRA_ALIAS_TEST_REPORT.md
   - HYDRA_ALIAS_VERIFICATION.md

---

## Quick Command Reference

| Command | Description |
|---------|-------------|
| `hydra` | Start server & open browser |
| `hydra-status` | Check server status |
| `hydra-stop` | Stop server |
| `hydra-restart` | Restart server |
| `hydra-logs` | View last 50 log lines |
| `hydra-logs -f` | Follow logs in real-time |

---

## Files & Locations

### Shell Integration
- `~/.openhydra/aliases.sh` - Alias definitions
- `~/.zshrc` - Sources aliases (auto-configured)

### Runtime Files
- `~/.openhydra/server.log` - Server logs
- `~/.openhydra/server.pid` - Process ID
- `~/.openhydra/openhydra.yaml` - Configuration

### Test Scripts
- `/tmp/test_hydra_alias.sh` - Comprehensive test suite
- `/tmp/test_hydra_final.sh` - Focused verification

---

## Status

✅ **Production Ready**

- All tests passing (10/10)
- Comprehensive documentation
- Fully verified end-to-end
- Ready for daily use

Last Verification: 2026-02-22

---

## Support

**First steps:**
1. Check [HYDRA_QUICK_START.md](HYDRA_QUICK_START.md)
2. Run `hydra-status` to see current state
3. Check logs with `hydra-logs`

**Common issues:**
- Server won't start → Check logs
- Port in use → Change with `OPENHYDRA_WEB_PORT=8080 hydra`
- Browser doesn't open → URL is still printed, open manually

---

## Related Documentation

- [API and Auth Guide](api-auth.md) - Web API and authentication
- [Setup Guide](../SETUP.md) - OpenHydra installation
- [Main README](../README.md) - Project overview
