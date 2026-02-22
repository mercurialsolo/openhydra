"""Optional API key authentication middleware."""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from openhydra.hydra_compat import validate_hydra_access_token


class ApiKeyMiddleware(BaseHTTPMiddleware):
    """Check X-API-Key header when api_key is configured.

    Skips auth for health endpoint and WebSocket upgrades.
    """

    def __init__(self, app, api_key: str) -> None:
        super().__init__(app)
        self._api_key = api_key

    async def dispatch(self, request: Request, call_next):
        # Skip auth for health checks
        if request.url.path in {"/api/v1/health", "/"}:
            return await call_next(request)

        # Skip auth for login / refresh endpoints
        if request.url.path in {
            "/api/v1/auth/login",
            "/api/v1/auth/refresh",
            "/api/v1/auth/logout",
        }:
            return await call_next(request)

        # Skip auth for WebSocket upgrades (handled separately)
        if request.headers.get("upgrade", "").lower() == "websocket":
            return await call_next(request)

        # Check API key first (backward-compatible clients).
        provided = request.headers.get("x-api-key", "")
        if provided != self._api_key:
            # Hydra-web compatibility: accept Bearer access token in header
            # or ?token= query parameter for SSE streams.
            auth_header = request.headers.get("authorization", "")
            bearer_token = ""
            if auth_header.lower().startswith("bearer "):
                bearer_token = auth_header[7:].strip()
            query_token = request.query_params.get("token", "").strip()

            token = bearer_token or query_token
            if not token or not validate_hydra_access_token(token):
                return JSONResponse(
                    {"error": "Invalid or missing API key"},
                    status_code=401,
                )

        return await call_next(request)
