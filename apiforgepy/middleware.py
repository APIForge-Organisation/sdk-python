import re
import time
import threading

_NUMERIC_SEGMENT = re.compile(r"/\d+")
_UUID_SEGMENT    = re.compile(r"/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE)


def _normalize_path(path: str) -> str:
    path = _UUID_SEGMENT.sub("/:uuid", path)
    path = _NUMERIC_SEGMENT.sub("/:id", path)
    return path


def _extract_routes(app) -> list[dict]:
    """Walk a FastAPI/Starlette app's router and return all declared routes."""
    from starlette.routing import Route, Mount
    routes = []

    def walk(route_list, prefix: str = ""):
        for r in route_list:
            if isinstance(r, Route) and r.methods:
                for method in r.methods:
                    # HEAD is auto-added by Starlette for every GET route — skip it
                    if method != "HEAD":
                        routes.append({"route": prefix + r.path, "method": method})
            elif isinstance(r, Mount) and hasattr(r, "routes"):
                walk(r.routes, prefix + (r.path or ""))

    try:
        walk(getattr(app, "routes", []))
    except Exception:
        pass

    return routes


class ApiForgeMiddleware:
    """
    Raw ASGI middleware for APIForge.

    Captures route, method, status, latency, TTFB, request/response sizes,
    and inflight request count — no body content, no PII.
    """

    def __init__(self, app, *, aggregator, config: dict):
        self._app            = app
        self._aggregator     = aggregator
        self._env            = config["env"]
        self._release        = config.get("release")
        self._service        = config["service"]
        self._sampling       = config["sampling"]
        self._ignore         = set(config["ignore_paths"])
        self._store_routes   = config.get("store_routes")
        self._routes_scanned = False
        self._inflight_count = 0

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        path = scope.get("path", "/")

        # Route scan — executed once on the first request
        if not self._routes_scanned and scope.get("app"):
            self._routes_scanned = True
            app_obj = scope["app"]
            routes = _extract_routes(app_obj)
            if routes and self._store_routes:
                threading.Thread(
                    target=self._store_routes, args=(routes,), daemon=True
                ).start()

        if path in self._ignore:
            await self._app(scope, receive, send)
            return

        import random
        if self._sampling < 1.0 and random.random() > self._sampling:
            await self._app(scope, receive, send)
            return

        start = time.perf_counter()
        self._inflight_count += 1
        inflight_snapshot = self._inflight_count

        # Request body size — size only, never the content
        raw_headers = dict(scope.get("headers", []))
        req_cl = raw_headers.get(b"content-length")
        request_size = int(req_cl.decode()) if req_cl else None

        # Capture TTFB, status code and response size via ASGI send wrapper
        status_code   = None
        response_size = None
        ttfb_ms       = None

        async def send_wrapper(message):
            nonlocal status_code, response_size, ttfb_ms
            if message["type"] == "http.response.start":
                if ttfb_ms is None:
                    ttfb_ms = (time.perf_counter() - start) * 1000
                status_code = message.get("status", 200)
                resp_headers = dict(message.get("headers", []))
                cl = resp_headers.get(b"content-length")
                if cl:
                    response_size = int(cl.decode())
            await send(message)

        try:
            await self._app(scope, receive, send_wrapper)
        finally:
            self._inflight_count -= 1

            if status_code is None:
                return  # no http.response.start was sent — nothing to record

            duration_ms = (time.perf_counter() - start) * 1000
            route_obj = scope.get("route")

            try:
                if route_obj and hasattr(route_obj, "path"):
                    route_pattern = route_obj.path
                else:
                    route_pattern = _normalize_path(path)

                self._aggregator.record({
                    "route":         route_pattern,
                    "method":        scope.get("method", "GET"),
                    "status":        status_code,
                    "duration_ms":   duration_ms,
                    "ttfb_ms":       ttfb_ms if ttfb_ms is not None else duration_ms,
                    "timestamp":     time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "env":           self._env,
                    "release":       self._release,
                    "service":       self._service,
                    "response_size": response_size,
                    "request_size":  request_size,
                    "is_ghost":      route_obj is None,
                    "inflight":      inflight_snapshot,
                })
            except Exception:
                pass  # never crash the host application
