"""Optional API key authentication middleware."""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


class ApiKeyMiddleware(BaseHTTPMiddleware):
    """Check X-API-Key header when api_key is configured.

    Skips auth for health endpoint and WebSocket upgrades.
    """

    def __init__(self, app, api_key: str) -> None:
        super().__init__(app)
        self._api_key = api_key

    async def dispatch(self, request: Request, call_next):
        # Skip auth for health checks
        if request.url.path == "/api/v1/health":
            return await call_next(request)

        # Skip auth for WebSocket upgrades (handled separately)
        if request.headers.get("upgrade", "").lower() == "websocket":
            return await call_next(request)

        # Check API key
        provided = request.headers.get("x-api-key", "")
        if provided != self._api_key:
            return JSONResponse(
                {"error": "Invalid or missing API key"}, status_code=401,
            )

        return await call_next(request)
