"""The local dashboard serves React/Babel from vendored files — never from a CDN."""

import http.client
import os

from apiforgepy import dashboard
from apiforgepy.database import ApiForgeDatabase


def test_no_cdn_reference_in_dashboard_html():
    # Regression guard for the privacy fix: the served HTML must reference the
    # local /assets/* paths, never a third-party CDN.
    assert "jsdelivr" not in dashboard._HTML
    assert "cdn." not in dashboard._HTML


def test_vendored_assets_are_present_on_disk():
    for name in dashboard._ASSET_NAMES:
        path = os.path.join(dashboard._ASSET_DIR, name)
        assert os.path.exists(path), f"missing vendored asset: {name}"
        assert os.path.getsize(path) > 0


def test_dashboard_serves_vendored_asset_over_http():
    db = ApiForgeDatabase(":memory:")
    server = dashboard.start_dashboard(db, 0)  # port 0 → ephemeral
    try:
        port = server.server_address[1]
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request("GET", "/assets/react.js")
        resp = conn.getresponse()
        body = resp.read()
        conn.close()

        assert resp.status == 200
        assert resp.getheader("Content-Type") == "application/javascript"
        assert len(body) > 0
    finally:
        server.shutdown()
        server.server_close()
        db.close()


def test_dashboard_returns_404_for_unknown_asset():
    db = ApiForgeDatabase(":memory:")
    server = dashboard.start_dashboard(db, 0)
    try:
        port = server.server_address[1]
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request("GET", "/assets/evil.js")
        resp = conn.getresponse()
        resp.read()
        conn.close()

        assert resp.status == 404
    finally:
        server.shutdown()
        server.server_close()
        db.close()
