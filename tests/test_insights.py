import math
import time
import pytest
from apiforgepy.insights import get_insights, compute_health_score


def make_db(**overrides):
    """Build a minimal database stub."""
    base = dict(
        get_latency_anomaly_data=lambda: {"recent": [], "baseline_rows": []},
        get_dead_candidates=lambda _days=21: [],
        get_release_comparison=lambda: None,
        get_untracked_routes=lambda: [],
        get_drift_data=lambda: [],
        get_summary=lambda: {
            "recent": {"calls_total": 0},
            "baseline": {},
            "active_routes": 0,
            "total_routes": 0,
        },
    )

    class Stub:
        pass

    stub = Stub()
    merged = {**base, **overrides}
    for name, fn in merged.items():
        setattr(stub, name, fn)
    return stub


class TestGetInsights:
    def test_empty_when_no_data(self):
        assert get_insights(make_db()) == []

    def test_emits_anomaly_on_high_zscore(self):
        baseline_rows = [
            {"method": "GET", "route": "/slow", "lat_p99": float(v)}
            for v in [50, 60, 70, 80, 90, 100, 110, 120, 130, 140]
        ]
        db = make_db(
            get_latency_anomaly_data=lambda: {
                "recent": [{"method": "GET", "route": "/slow", "avg_p99": 500.0}],
                "baseline_rows": baseline_rows,
            }
        )
        insights = get_insights(db)
        anomaly = next((i for i in insights if i["type"] == "ANOMALY"), None)
        assert anomaly is not None
        assert "abnormally high" in anomaly["message"]

    def test_no_anomaly_when_few_samples(self):
        db = make_db(
            get_latency_anomaly_data=lambda: {
                "recent": [{"method": "GET", "route": "/r", "avg_p99": 999.0}],
                "baseline_rows": [{"method": "GET", "route": "/r", "lat_p99": 50.0}],
            }
        )
        insights = get_insights(db)
        assert not any(i["type"] == "ANOMALY" for i in insights)

    def test_emits_dead_for_inactive_endpoint(self):
        old_ts = int(time.time()) - 30 * 86_400
        db = make_db(
            get_dead_candidates=lambda _days=21: [
                {"route": "/old", "method": "DELETE", "last_seen": old_ts}
            ]
        )
        insights = get_insights(db)
        dead = next((i for i in insights if i["type"] == "DEAD"), None)
        assert dead is not None
        assert "no requests" in dead["message"]

    def test_emits_perf_on_regression(self):
        db = make_db(
            get_release_comparison=lambda: {
                "release_tag": "v2.0",
                "before": [{"method": "GET", "route": "/pay", "avg_p90": 100.0, "calls": 10}],
                "after":  [{"method": "GET", "route": "/pay", "avg_p90": 200.0, "calls": 10}],
            }
        )
        insights = get_insights(db)
        perf = next((i for i in insights if i["type"] == "PERF"), None)
        assert perf is not None
        assert "v2.0" in perf["message"]
        assert "Before:" in perf["message"]

    def test_emits_ok_on_improvement(self):
        db = make_db(
            get_release_comparison=lambda: {
                "release_tag": "v3.0",
                "before": [{"method": "GET", "route": "/fast", "avg_p90": 200.0, "calls": 10}],
                "after":  [{"method": "GET", "route": "/fast", "avg_p90": 80.0, "calls": 10}],
            }
        )
        insights = get_insights(db)
        ok = next((i for i in insights if i["type"] == "OK"), None)
        assert ok is not None
        assert "improved" in ok["message"]

    def test_emits_untracked_for_declared_silent_routes(self):
        now = int(time.time())
        db = make_db(
            get_untracked_routes=lambda: [
                {"route": "/ghost", "method": "GET", "first_seen": now}
            ]
        )
        insights = get_insights(db)
        untracked = next((i for i in insights if i["type"] == "UNTRACKED"), None)
        assert untracked is not None
        assert "no requests since monitoring started" in untracked["message"]

    def test_emits_drift_on_steep_upward_slope(self):
        today = int(time.time() // 86_400)
        rows = [
            {"route": "/slow", "method": "GET", "day_bucket": today - 9 + i, "p90": 100.0 + i * 20}
            for i in range(10)
        ]
        db = make_db(get_drift_data=lambda: rows)
        insights = get_insights(db)
        drift = next((i for i in insights if i["type"] == "DRIFT"), None)
        assert drift is not None
        assert "ms/day" in drift["message"]
        assert "30-day projection" in drift["message"]

    def test_no_drift_with_fewer_than_7_days(self):
        today = int(time.time() // 86_400)
        rows = [
            {"route": "/r", "method": "GET", "day_bucket": today - 4 + i, "p90": 100.0 + i * 30}
            for i in range(5)
        ]
        db = make_db(get_drift_data=lambda: rows)
        insights = get_insights(db)
        assert not any(i["type"] == "DRIFT" for i in insights)

    def test_no_drift_when_slope_below_threshold(self):
        today = int(time.time() // 86_400)
        rows = [
            {"route": "/flat", "method": "GET", "day_bucket": today - 9 + i, "p90": 100.0}
            for i in range(10)
        ]
        db = make_db(get_drift_data=lambda: rows)
        insights = get_insights(db)
        assert not any(i["type"] == "DRIFT" for i in insights)

    def test_never_raises_even_when_all_db_methods_raise(self):
        def boom(*_args, **_kwargs):
            raise RuntimeError("db error")

        db = make_db(
            get_latency_anomaly_data=boom,
            get_dead_candidates=boom,
            get_release_comparison=boom,
            get_untracked_routes=boom,
            get_drift_data=boom,
        )
        result = get_insights(db)
        assert result == []


class TestComputeHealthScore:
    def test_returns_none_when_no_traffic(self):
        assert compute_health_score(make_db()) is None

    def test_returns_number_between_0_and_100(self):
        db = make_db(
            get_summary=lambda: {
                "recent": {
                    "calls_total": 100, "calls_2xx": 95,
                    "calls_4xx": 3, "calls_5xx": 2,
                    "avg_p90": 80.0, "avg_p99": 150.0,
                },
                "baseline": {"baseline_p90": 70.0},
                "active_routes": 4,
                "total_routes": 5,
            }
        )
        score = compute_health_score(db)
        assert isinstance(score, int)
        assert 0 <= score <= 100

    def test_high_score_when_api_is_healthy(self):
        db = make_db(
            get_summary=lambda: {
                "recent": {
                    "calls_total": 200, "calls_2xx": 200,
                    "calls_4xx": 0, "calls_5xx": 0,
                    "avg_p90": 50.0, "avg_p99": 80.0,
                },
                "baseline": {"baseline_p90": 60.0},
                "active_routes": 5,
                "total_routes": 5,
            }
        )
        score = compute_health_score(db)
        assert score >= 80

    def test_returns_none_when_get_summary_raises(self):
        db = make_db(get_summary=lambda: (_ for _ in ()).throw(RuntimeError("db error")))
        # Python workaround: use a proper raising function
        class BadDb:
            def get_summary(self):
                raise RuntimeError("db error")
        assert compute_health_score(BadDb()) is None
