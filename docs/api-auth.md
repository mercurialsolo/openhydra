# OpenHydra API and Auth Guide

Use this guide when you want to run OpenHydra as a backend service and connect to it from your own
product.

## Run OpenHydra as an API service

### Option A: local process

```bash
# Set OPENHYDRA_WEB_API_KEY in your shell/CI secret manager first.
openhydra serve --host 0.0.0.0 --port 7070
```

### Option B: Docker (GHCR image)

```bash
# Set OPENHYDRA_WEB_API_KEY in your shell/CI secret manager first.
docker run --rm \
  -p 7070:7070 \
  --env OPENHYDRA_WEB_API_KEY \
  ghcr.io/mercurialsolo/openhydra:latest
```

Container behavior:

- API server listens on `0.0.0.0:7070` by default.
- Port can be overridden with `PORT` or `OPENHYDRA_WEB_PORT`.
- If `OPENHYDRA_WEB_API_KEY` is not set, `openhydra serve` auto-generates a key.
  For app integrations, set your own key explicitly.

## Auth modes

OpenHydra web middleware accepts either:

1. API key header:
- `X-API-Key: <OPENHYDRA_WEB_API_KEY>`

2. Bearer token (Hydra-compatible auth routes):
- `Authorization: Bearer <access_token>`

Routes exempt from API-key auth:

- `GET /`
- `GET /api/v1/health`
- `POST /api/v1/auth/login`
- `POST /api/v1/auth/refresh`
- `POST /api/v1/auth/logout`

WebSocket auth:

- Connect with `?api_key=<OPENHYDRA_WEB_API_KEY>` on `/api/v1/ws`.

## Minimal API flow

### 1) Health check

```bash
curl http://localhost:7070/api/v1/health
```

### 2) Start a workflow (API key)

```bash
curl -X POST http://localhost:7070/api/v1/workflows \
  -H "Content-Type: application/json" \
  -H "X-API-Key: replace-with-your-key" \
  -d '{"task":"Build a Python CLI that converts CSV to JSON"}'
```

### 3) Read workflow status

```bash
curl http://localhost:7070/api/v1/workflows/<workflow_id> \
  -H "X-API-Key: replace-with-your-key"
```

### 4) Optional login for bearer token

```bash
curl -X POST http://localhost:7070/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"you@example.com","password":"dev-only","workspace_id":"ws_default"}'
```

Then use returned `access_token`:

```bash
curl http://localhost:7070/api/v1/auth/me \
  -H "Authorization: Bearer <access_token>"
```

### 5) Optional WebSocket events

```text
ws://localhost:7070/api/v1/ws?api_key=replace-with-your-key
```

After connect, send:

```json
{"subscribe":"*"}
```

Or subscribe to one workflow:

```json
{"subscribe":"<workflow_id>"}
```

## API endpoints

Primary integration endpoints:

- `GET /api/v1/health`
- `POST /api/v1/workflows`
- `GET /api/v1/workflows`
- `GET /api/v1/workflows/{workflow_id}`
- `POST /api/v1/workflows/{workflow_id}/pause`
- `POST /api/v1/workflows/{workflow_id}/resume`
- `POST /api/v1/workflows/{workflow_id}/cancel`
- `WS /api/v1/ws`
- `POST /api/v1/auth/login`
- `POST /api/v1/auth/refresh`
- `POST /api/v1/auth/logout`
- `GET /api/v1/auth/me`

For broader compatibility APIs and SSE streams, see route definitions in
`src/openhydra/channels/web/routes.py`.
