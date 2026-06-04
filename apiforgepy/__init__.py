"""
apiforgepy — API observability & intelligence for FastAPI/Starlette.
Local-first, privacy-first. Dashboard on port 4242.

Usage (local):
    from apiforgepy import ApiForgeMiddleware
    app.add_middleware(ApiForgeMiddleware)

Usage (cloud):
    app.add_middleware(
        ApiForgeMiddleware,
        cloud_url="https://api.apiforge.fr",
        api_key="af_...",
    )
"""

import atexit

from .aggregator       import Aggregator
from .database         import ApiForgeDatabase
from .dashboard        import start_dashboard
from .middleware       import ApiForgeMiddleware as _Base
from .transport        import LocalTransport
from .cloud_transport  import CloudTransport

__version__ = "3.0.0"
__all__ = ["ApiForgeMiddleware"]


class ApiForgeMiddleware(_Base):
    """
    Starlette/FastAPI middleware for APIForge observability.

    Parameters
    ----------
    app:            The ASGI app to wrap.
    cloud_url:      Cloud mode: SaaS API base URL (e.g. 'https://api.apiforge.fr').
    api_key:        Cloud mode: project API key starting with 'af_'.
    db_path:        Local mode: SQLite file path. Default: '.apiforge.db'.
    dashboard_port: Local mode: dashboard port. 0 = disabled. Default: 4242.
    env:            Environment label. Default: 'production'.
    release:        Release tag. Default: None.
    service:        Service name. Default: 'default'.
    sampling:       Sample rate 0.0–1.0. Default: 1.0.
    ignore_paths:   Paths to exclude. Default: ['/favicon.ico'].
    """

    def __init__(
        self,
        app,
        *,
        cloud_url:      str | None = None,
        api_key:        str | None = None,
        db_path:        str        = ".apiforge.db",
        dashboard_port: int        = 4242,
        env:            str | None = None,
        release:        str | None = None,
        service:        str        = "default",
        sampling:       float      = 1.0,
        ignore_paths:   list[str]  = None,
        _flush_interval: int       = 60_000,  # internal — not part of the public API
    ):
        is_cloud = bool(cloud_url and api_key)

        if (cloud_url and not api_key) or (api_key and not cloud_url):
            raise ValueError("[apiforgepy] Cloud mode requires both cloud_url and api_key.")

        config = {
            "mode":         "cloud" if is_cloud else "local",
            "env":          env or "production",
            "release":      release,
            "service":      service,
            "sampling":     sampling,
            "ignore_paths": ignore_paths or ["/favicon.ico"],
        }

        self._db               = None
        self._dashboard_server = None
        self._stopped          = False

        if is_cloud:
            transport = CloudTransport(cloud_url, api_key, service)
            config["store_routes"] = transport.write_routes
        else:
            self._db  = ApiForgeDatabase(db_path)
            transport = LocalTransport(self._db)
            config["store_routes"] = self._db.upsert_known_routes

        aggregator = Aggregator(transport, _flush_interval)
        aggregator.start()

        if not is_cloud and dashboard_port:
            self._dashboard_server = start_dashboard(self._db, dashboard_port)

        self._aggregator_ref = aggregator
        super().__init__(app, aggregator=aggregator, config=config)

        atexit.register(self._cleanup)

    def _cleanup(self) -> None:
        """Flush buffer and close DB — safe to call multiple times (via atexit or shutdown)."""
        if self._stopped:
            return
        self._stopped = True
        try:
            self._aggregator_ref.stop()
        except Exception:
            pass
        if self._db:
            try:
                self._db.close()
            except Exception:
                pass

    def shutdown(self) -> None:
        """Flush remaining buffer, stop dashboard, and release all resources."""
        self._cleanup()
        if self._dashboard_server:
            try:
                self._dashboard_server.shutdown()
                self._dashboard_server.server_close()
            except Exception:
                pass
            self._dashboard_server = None
