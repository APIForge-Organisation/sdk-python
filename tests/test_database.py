import json
import time
import pytest
from apiforgepy.database import ApiForgeDatabase


def make_db():
    return ApiForgeDatabase(":memory:")


def insert_row(db, **overrides):
    defaults = dict(
        bucket_ts=int(time.time()),
        route="/test",
        method="GET",
        env="test",
        release_tag=None,
        status_2xx=1,
        status_3xx=0,
        status_4xx=0,
        status_5xx=0,
        status_dist=None,
        total_calls=1,
        lat_p50=50.0,
        lat_p90=90.0,
        lat_p99=99.0,
        lat_avg=70.0,
        lat_min=10.0,
        lat_max=150.0,
        lat_ttfb_p50=None,
        lat_ttfb_p90=None,
        lat_ttfb_p99=None,
        bytes_avg=None,
        request_size_avg=None,
        inflight_avg=None,
        inflight_max=None,
        is_ghost=0,
    )
    db.insert_batch([{**defaults, **overrides}])


class TestInsertBatch:
    def test_row_appears_in_get_routes(self):
        db = make_db()
        insert_row(db, route="/users", method="GET")
        routes = db.get_routes(24)
        assert len(routes) == 1
        assert routes[0]["route"] == "/users"
        db.close()

    def test_accumulates_calls_for_same_route(self):
        db = make_db()
        insert_row(db, route="/items", total_calls=3)
        insert_row(db, route="/items", total_calls=7)
        routes = db.get_routes(24)
        assert routes[0]["calls"] == 10
        db.close()

    def test_empty_batch_is_noop(self):
        db = make_db()
        db.insert_batch([])
        assert db.get_routes(24) == []
        db.close()


class TestGetSummary:
    def test_returns_zero_when_empty(self):
        db = make_db()
        s = db.get_summary()
        assert s["active_routes"] == 0
        assert s["total_routes"] == 0
        db.close()

    def test_counts_distinct_routes(self):
        db = make_db()
        now = int(time.time())
        insert_row(db, route="/a", bucket_ts=now)
        insert_row(db, route="/b", bucket_ts=now)
        s = db.get_summary()
        assert s["active_routes"] == 2
        assert s["total_routes"] == 2
        db.close()

    def test_sums_5xx_errors(self):
        db = make_db()
        now = int(time.time())
        insert_row(db, status_2xx=0, status_5xx=3, total_calls=3, bucket_ts=now)
        s = db.get_summary()
        assert s["recent"]["calls_5xx"] == 3
        db.close()

    def test_exposes_calls_3xx_in_summary(self):
        db = make_db()
        now = int(time.time())
        insert_row(db, status_2xx=0, status_3xx=4, total_calls=4, bucket_ts=now)
        s = db.get_summary()
        assert s["recent"]["calls_3xx"] == 4
        db.close()


class TestGetTimeSeries:
    def test_returns_data_for_matching_route(self):
        db = make_db()
        ts = int(time.time()) - 60
        insert_row(db, route="/ts", method="POST", bucket_ts=ts)
        rows = db.get_time_series("/ts", "POST", 24)
        assert len(rows) == 1
        assert "p90" in rows[0]
        db.close()

    def test_returns_empty_for_missing_route(self):
        db = make_db()
        insert_row(db, route="/other")
        rows = db.get_time_series("/missing", "GET", 24)
        assert rows == []
        db.close()

    def test_includes_redirects_column(self):
        db = make_db()
        ts = int(time.time()) - 60
        insert_row(db, route="/redir", method="GET", bucket_ts=ts, status_3xx=2)
        rows = db.get_time_series("/redir", "GET", 24)
        assert rows[0]["redirects"] == 2
        db.close()


class TestGetDeadCandidates:
    def test_flags_old_routes(self):
        db = make_db()
        old_ts = int(time.time()) - 25 * 86_400
        insert_row(db, route="/dead", bucket_ts=old_ts)
        dead = db.get_dead_candidates(21)
        assert len(dead) == 1
        assert dead[0]["route"] == "/dead"
        db.close()

    def test_does_not_flag_recent_routes(self):
        db = make_db()
        recent_ts = int(time.time()) - 5 * 86_400
        insert_row(db, route="/alive", bucket_ts=recent_ts)
        dead = db.get_dead_candidates(21)
        assert dead == []
        db.close()


class TestGetReleaseComparison:
    def test_returns_none_without_releases(self):
        db = make_db()
        assert db.get_release_comparison() is None
        db.close()

    def test_returns_before_after_with_release(self):
        db = make_db()
        ts = int(time.time()) - 3600
        insert_row(db, release_tag="v1.0", bucket_ts=ts)
        result = db.get_release_comparison()
        assert result is not None
        assert result["release_tag"] == "v1.0"
        assert isinstance(result["before"], list)
        assert isinstance(result["after"], list)
        db.close()


class TestKnownRoutes:
    def test_untracked_route_appears_in_results(self):
        db = make_db()
        db.upsert_known_routes([{"route": "/ghost", "method": "DELETE"}])
        untracked = db.get_untracked_routes()
        assert len(untracked) == 1
        assert untracked[0]["route"] == "/ghost"
        db.close()

    def test_route_with_traffic_is_not_untracked(self):
        db = make_db()
        db.upsert_known_routes([{"route": "/active", "method": "GET"}])
        insert_row(db, route="/active", method="GET")
        assert db.get_untracked_routes() == []
        db.close()


class TestGetDriftData:
    def test_returns_rows_for_recent_data(self):
        db = make_db()
        ts = int(time.time()) - 10 * 86_400
        insert_row(db, route="/slow", bucket_ts=ts, lat_p90=120.0)
        rows = db.get_drift_data()
        assert len(rows) >= 1
        assert "day_bucket" in rows[0]
        assert "p90" in rows[0]
        db.close()

    def test_returns_empty_when_no_data(self):
        db = make_db()
        assert db.get_drift_data() == []
        db.close()


class TestGetGlobalTimeSeries:
    def test_returns_bucketed_data(self):
        db = make_db()
        insert_row(db, bucket_ts=int(time.time()) - 60)
        rows = db.get_global_time_series(24)
        assert len(rows) >= 1
        db.close()


class TestBytesAvg:
    def test_stored_and_returned_in_get_routes(self):
        db = make_db()
        insert_row(db, route="/size", bytes_avg=512.0)
        routes = db.get_routes(24)
        assert routes[0]["bytes_avg"] == pytest.approx(512.0)
        db.close()

    def test_null_bytes_avg_when_not_provided(self):
        db = make_db()
        insert_row(db, route="/nosize", bytes_avg=None)
        routes = db.get_routes(24)
        assert routes[0]["bytes_avg"] is None
        db.close()


class TestNewColumns:
    def test_stores_and_returns_status_3xx(self):
        db = make_db()
        insert_row(db, route="/redir", status_2xx=0, status_3xx=5, total_calls=5)
        routes = db.get_routes(24)
        assert routes[0]["calls_3xx"] == 5
        db.close()

    def test_stores_and_retrieves_status_dist(self):
        db = make_db()
        dist = json.dumps({200: 10, 201: 2})
        insert_row(db, route="/dist", status_dist=dist)
        row = db._conn.execute("SELECT status_dist FROM api_metrics LIMIT 1").fetchone()
        assert json.loads(row["status_dist"]) == json.loads(dist)
        db.close()

    def test_stores_and_returns_lat_avg(self):
        db = make_db()
        insert_row(db, route="/avg", lat_avg=42.5)
        row = db._conn.execute("SELECT lat_avg FROM api_metrics LIMIT 1").fetchone()
        assert row["lat_avg"] == pytest.approx(42.5)
        db.close()

    def test_stores_and_returns_lat_ttfb(self):
        db = make_db()
        insert_row(db, route="/ttfb", lat_ttfb_p50=12.0, lat_ttfb_p90=25.0, lat_ttfb_p99=40.0)
        row = db._conn.execute(
            "SELECT lat_ttfb_p50, lat_ttfb_p90, lat_ttfb_p99 FROM api_metrics LIMIT 1"
        ).fetchone()
        assert row["lat_ttfb_p50"] == pytest.approx(12.0)
        assert row["lat_ttfb_p90"] == pytest.approx(25.0)
        assert row["lat_ttfb_p99"] == pytest.approx(40.0)
        db.close()

    def test_stores_and_returns_request_size_avg(self):
        db = make_db()
        insert_row(db, route="/upload", request_size_avg=1024.0)
        routes = db.get_routes(24)
        assert routes[0]["request_size_avg"] == pytest.approx(1024.0)
        db.close()

    def test_stores_and_returns_inflight(self):
        db = make_db()
        insert_row(db, route="/busy", inflight_avg=4.5, inflight_max=8)
        routes = db.get_routes(24)
        assert routes[0]["inflight_avg"] == pytest.approx(4.5)
        assert routes[0]["inflight_max"] == 8
        db.close()
