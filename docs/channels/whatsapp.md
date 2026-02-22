# WhatsApp Setup

Use this guide to connect OpenHydra to WhatsApp.
If you only need REST/WebSocket app integration (no WhatsApp), use [API and Auth Guide](../api-auth.md).

### Prerequisites

1. Node.js and npm installed.
2. OpenHydra installed locally.
3. Recommended: install WhatsApp extras for terminal QR rendering:

```bash
uv pip install -e ".[whatsapp]"
```

### Step 1: Enable WhatsApp in Config

Edit `.openhydra/openhydra.yaml` or `~/.openhydra/openhydra.yaml`:

```yaml
channels:
  whatsapp:
    enabled: true
    auth_dir: "~/.openhydra/whatsapp_auth"
    allowed_phones: []  # optional allowlist; empty means allow all
```

Notes:

1. `auth_dir` defaults to `~/.openhydra/whatsapp_auth` if omitted.
2. On first `openhydra serve`, OpenHydra auto-installs the required WhatsApp bridge dependency
   (requires npm).

### Step 2: Validate and Start OpenHydra

```bash
# Optional preflight (recommended): validate config/dependencies first.
uv run openhydra doctor --strict
uv run openhydra serve
```

### Step 3: Pair WhatsApp

1. Keep `uv run openhydra serve` running.
2. OpenHydra prints the pairing QR directly in your terminal.
3. Scan that QR from WhatsApp on your phone.

### Step 4: Verify

1. Send a normal WhatsApp message with task text.
2. Confirm workflow status updates are sent back to the same number.

Supported control commands in chat:

1. `approve`
2. `reject <reason>`
3. `pause`
4. `resume`
5. `cancel`

## Optional Access Control

Restrict by phone number list:

```yaml
channels:
  whatsapp:
    enabled: true
    allowed_phones: ["+15551234567"]
```

Or authorize dynamically:

```bash
uv run openhydra auth add whatsapp:+15551234567
```
