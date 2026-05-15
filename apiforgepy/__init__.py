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

import os

from .aggregator       import Aggregator
from .database         import ApiForgeDatabase
from .dashboard        import start_dashboard
from .middleware       import ApiForgeMiddleware as _Base
from .transport        import LocalTransport
from .cloud_transport  import CloudTransport

__version__ = "2.0.0"
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
    flush_interval: Aggregation flush interval in ms. Default: 60 000.
    env:            Environment label. Default: ENV env var or 'production'.
    release:        Release tag. Default: APP_VERSION env var.
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
        flush_interval: int        = 60_000,
        env:            str | None = None,
        release:        str | None = None,
        service:        str        = "default",
        sampling:       float      = 1.0,
        ignore_paths:   list[str]  = None,
    ):
        is_cloud = bool(cloud_url and api_key)

        if (cloud_url and not api_key) or (api_key and not cloud_url):
            raise ValueError("[apiforgepy] Cloud mode requires both cloud_url and api_key.")

        config = {
            "mode":         "cloud" if is_cloud else "local",
            "env":          env or os.environ.get("ENV", "production"),
            "release":      release or os.environ.get("APP_VERSION"),
            "service":      service,
            "sampling":     sampling,
            "ignore_paths": ignore_paths or ["/favicon.ico"],
        }

        self._db = None

        if is_cloud:
            transport = CloudTransport(cloud_url, api_key, service)
        else:
            self._db  = ApiForgeDatabase(db_path)
            transport = LocalTransport(self._db)

        aggregator = Aggregator(transport, flush_interval)
        aggregator.start()

        if not is_cloud and dashboard_port:
            start_dashboard(self._db, dashboard_port)

        self._aggregator_ref = aggregator
        super().__init__(app, aggregator=aggregator, config=config)

    def shutdown(self):
        """Flush remaining buffer and close resources."""
        self._aggregator_ref.stop()
        if self._db:
            self._db.close()
