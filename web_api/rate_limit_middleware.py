"""Rate limiting elementare per richieste API (per client IP, finestra fissa)."""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque
from typing import Deque, Dict

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Limita le richieste verso un prefisso URL (default /api/) per indirizzo IP.
    Le richieste OPTIONS (CORS preflight) non contano.
    """

    def __init__(
        self,
        app,
        *,
        calls_per_minute: int = 120,
        enabled: bool = True,
        path_prefix: str = "/api/",
        exempt_paths: frozenset[str] | None = None,
    ) -> None:
        super().__init__(app)
        self.calls_per_minute = max(1, int(calls_per_minute))
        self.enabled = enabled
        self.path_prefix = path_prefix or "/api/"
        self._window_sec = 60.0
        self._buckets: Dict[str, Deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()
        self._exempt = exempt_paths or frozenset(
            {"/docs", "/redoc", "/openapi.json", "/favicon.ico"}
        )

    def _client_key(self, request: Request) -> str:
        xfwd = request.headers.get("x-forwarded-for")
        if xfwd:
            return xfwd.split(",")[0].strip() or "unknown"
        if request.client:
            return request.client.host
        return "unknown"

    async def dispatch(self, request: Request, call_next) -> Response:
        if not self.enabled:
            return await call_next(request)
        path = request.url.path
        if path in self._exempt or not path.startswith(self.path_prefix):
            return await call_next(request)
        if request.method == "OPTIONS":
            return await call_next(request)

        key = self._client_key(request)
        now = time.monotonic()
        async with self._lock:
            dq = self._buckets[key]
            while dq and now - dq[0] > self._window_sec:
                dq.popleft()
            if len(dq) >= self.calls_per_minute:
                return JSONResponse(
                    {"detail": "Too many requests. Try again later."},
                    status_code=429,
                    headers={"Retry-After": "60"},
                )
            dq.append(now)
        return await call_next(request)
