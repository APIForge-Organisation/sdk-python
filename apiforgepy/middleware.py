import re
import time
import os

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

_NUMERIC_SEGMENT = re.compile(r"/\d+")
_UUID_SEGMENT    = re.compile(r"/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE)


def _normalize_path(path: str) -> str:
    path = _UUID_SEGMENT.sub("/:uuid", path)
    path = _NUMERIC_SEGMENT.sub("/:id", path)
    return path


class ApiForgeMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, aggregator, config: dict):
        super().__init__(app)
        self._aggregator = aggregator
        self._env        = config["env"]
        self._release    = config.get("release")
        self._service    = config["service"]
        self._sampling   = config["sampling"]
        self._ignore     = set(config["ignore_paths"])

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        if path in self._ignore:
            return await call_next(request)

        if self._sampling < 1.0 and __import__("random").random() > self._sampling:
            return await call_next(request)

        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start) * 1000

        try:
            # FastAPI exposes the matched route pattern via request.scope["route"]
            route_obj = request.scope.get("route")
            if route_obj and hasattr(route_obj, "path"):
                route_pattern = route_obj.path
            else:
                route_pattern = _normalize_path(path)

            content_length = response.headers.get("content-length")

            self._aggregator.record({
                "route":         route_pattern,
                "method":        request.method,
                "status":        response.status_code,
                "duration_ms":   duration_ms,
                "timestamp":     time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "env":           self._env,
                "release":       self._release,
                "service":       self._service,
                "response_size": int(content_length) if content_length else None,
            })
        except Exception:
            pass  # never crash the host application

        return response
