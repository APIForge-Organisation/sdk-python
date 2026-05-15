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
        status_4xx=0,
        status_5xx=0,
        total_calls=1,
        lat_p50=50.0,
        lat_p90=90.0,
        lat_p99=99.0,
        lat_min=10.0,
        lat_max=150.0,
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
