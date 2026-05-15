"""
apiforgepy — API observability & intelligence for FastAPI/Starlette.
Local-first, privacy-first. Dashboard on port 4242.

Usage:
    from apiforgepy import ApiForgeMiddleware
    app.add_middleware(ApiForgeMiddleware, mode="local")
"""

import os

from .aggregator  import Aggregator
from .database    import ApiForgeDatabase
from .dashboard   import start_dashboard
from .middleware  import ApiForgeMiddleware as _Base
from .transport   import LocalTransport

__version__ = "0.1.0"
__all__ = ["ApiForgeMiddleware"]


class ApiForgeMiddleware(_Base):
    """
    Starlette/FastAPI middleware for APIForge local-first observability.

    Parameters
    ----------
    app:            The ASGI app to wrap.
    mode:           Storage mode. Only 'local' (SQLite) in v0.x.
    db_path:        SQLite file path. Default: '.apiforge.db'
    dashboard_port: Port for the built-in dashboard. Set 0 to disable. Default: 4242.
    flush_interval: Aggregation flush interval in ms. Default: 60 000.
    env:            Environment label. Default: NODE_ENV or 'production'.
    release:        Release tag for deployment correlation. Default: APP_VERSION env var.
    service:        Service name for multi-service setups. Default: 'default'.
    sampling:       Sample rate 0.0–1.0. Default: 1.0.
    ignore_paths:   Paths to exclude. Default: ['/favicon.ico'].
    """

    _instance_db        = None
    _instance_transport = None
    _instance_aggregator = None
    _instance_dashboard = None

    def __init__(
        self,
        app,
        *,
        mode:           str        = "local",
        db_path:        str        = ".apiforge.db",
        dashboard_port: int        = 4242,
        flush_interval: int        = 60_000,
        env:            str | None = None,
        release:        str | None = None,
        service:        str        = "default",
        sampling:       float      = 1.0,
        ignore_paths:   list[str]  = None,
    ):
        if mode != "local":
            raise ValueError(f"[apiforgepy] mode '{mode}' is not yet supported. Use 'local'.")

        config = {
            "mode":         mode,
            "db_path":      db_path,
            "env":          env or os.environ.get("ENV", "production"),
            "release":      release or os.environ.get("APP_VERSION"),
            "service":      service,
            "sampling":     sampling,
            "ignore_paths": ignore_paths or ["/favicon.ico"],
        }

        db          = ApiForgeDatabase(db_path)
        transport   = LocalTransport(db)
        aggregator  = Aggregator(transport, flush_interval)
        aggregator.start()

        if dashboard_port:
            start_dashboard(db, dashboard_port)

        self._db         = db
        self._transport  = transport
        self._aggregator_ref = aggregator

        super().__init__(app, aggregator=aggregator, config=config)

    def shutdown(self):
        """Flush remaining buffer and close the SQLite connection."""
        self._aggregator_ref.stop()
        self._db.close()
