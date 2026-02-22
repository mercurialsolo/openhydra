# WhatsApp Setup (Baileys or Cloud API)

Use this guide to connect OpenHydra to WhatsApp.

OpenHydra supports two backends:

1. **Baileys**: local WhatsApp Web session via QR login.
2. **Cloud API**: Meta webhook/API integration.

## Option A: Baileys (Local QR Login)

### Prerequisites

1. Node.js and npm installed.
2. OpenHydra installed locally.

### Step 1: Enable WhatsApp Baileys in Config

Edit `.openhydra/openhydra.yaml` or `~/.openhydra/openhydra.yaml`:

```yaml
channels:
  whatsapp:
    enabled: true
    backend: "baileys"
    auth_dir: "~/.openhydra/whatsapp_auth"
    allowed_phones: []  # optional allowlist; empty means allow all
```

Notes:

1. `auth_dir` defaults to `~/.openhydra/whatsapp_auth` if omitted.
2. On first `openhydra serve`, OpenHydra auto-installs `@whiskeysockets/baileys` (requires npm).

### Step 2: Start OpenHydra

```bash
uv run openhydra doctor --strict
uv run openhydra serve
```

### Step 3: Pair WhatsApp

1. Subscribe to the WebSocket stream (`/api/v1/ws`) and watch for event `whatsapp.qr`.
2. Read `data.qr_data` from that event.
3. Render it as a QR code and scan from WhatsApp on your phone.

### Step 4: Verify

1. Send a normal WhatsApp message with task text.
2. Confirm workflow status updates are sent back to the same number.

Supported control commands in chat:

1. `approve`
2. `reject <reason>`
3. `pause`
4. `resume`
5. `cancel`

## Option B: Cloud API (Meta)

### Prerequisites

1. Meta WhatsApp Cloud API setup with phone number.
2. Public HTTPS endpoint for webhooks.
3. OpenHydra web channel enabled.

### Step 1: Set Required Environment Variable

```bash
export OPENHYDRA_WHATSAPP_ACCESS_TOKEN=...
```

### Step 2: Enable Cloud API in Config

```yaml
web:
  enabled: true
  host: "127.0.0.1"
  port: 7070

channels:
  whatsapp:
    enabled: true
    backend: "cloud-api"
    phone_number_id: "1234567890"
    verify_token: "your-verify-token"
    allowed_phones: []  # optional allowlist
```

### Step 3: Start OpenHydra

```bash
uv run openhydra doctor --strict
uv run openhydra serve
```

### Step 4: Register Webhook in Meta

1. Expose your OpenHydra server publicly.
2. Set webhook URL to:

```text
https://<public-host>/webhooks/whatsapp
```

3. Use the same `verify_token` configured above.

### Step 5: Verify

1. Send WhatsApp message to your Cloud API number.
2. Confirm workflow starts and replies return via WhatsApp.

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
