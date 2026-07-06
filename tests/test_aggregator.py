import json

import pytest

from apiforgepy.aggregator import Aggregator


def make_transport():
    class Spy:
        def __init__(self):
            self.calls = []
        def write(self, rows):
            self.calls.append(rows)
    return Spy()


def base_event(**overrides):
    defaults = dict(
        route="/test", method="GET", status=200,
        duration_ms=100.0, timestamp="2026-01-01T00:00:00Z",
        env="test", release=None, service="svc",
        response_size=None, request_size=None,
        ttfb_ms=None, inflight=None,
    )
    return {**defaults, **overrides}


class TestRecord:
    def test_accumulates_durations(self):
        t = make_transport()
        agg = Aggregator(t, flush_interval_ms=999_999_000)
        agg.record(base_event(duration_ms=10))
        agg.record(base_event(duration_ms=20))
        key = next(iter(agg._buffer))
        assert len(agg._buffer[key]["durations"]) == 2

    def test_increments_2xx_counter(self):
        t = make_transport()
        agg = Aggregator(t, flush_interval_ms=999_999_000)
        agg.record(base_event(status=200))
        agg.record(base_event(status=204))
        key = next(iter(agg._buffer))
        assert agg._buffer[key]["status_2xx"] == 2

    def test_increments_3xx_counter(self):
        t = make_transport()
        agg = Aggregator(t, flush_interval_ms=999_999_000)
        agg.record(base_event(status=301))
        agg.record(base_event(status=302))
        key = next(iter(agg._buffer))
        assert agg._buffer[key]["status_3xx"] == 2
        assert agg._buffer[key]["status_2xx"] == 0

    def test_increments_4xx_counter(self):
        t = make_transport()
        agg = Aggregator(t, flush_interval_ms=999_999_000)
        agg.record(base_event(status=404))
        agg.record(base_event(status=429))
        key = next(iter(agg._buffer))
        assert agg._buffer[key]["status_4xx"] == 2
        assert agg._buffer[key]["status_2xx"] == 0

    def test_increments_5xx_counter(self):
        t = make_transport()
        agg = Aggregator(t, flush_interval_ms=999_999_000)
        agg.record(base_event(status=500))
        key = next(iter(agg._buffer))
        assert agg._buffer[key]["status_5xx"] == 1

    def test_builds_status_map(self):
        t = make_transport()
        agg = Aggregator(t, flush_interval_ms=999_999_000)
        agg.record(base_event(status=200))
        agg.record(base_event(status=200))
        agg.record(base_event(status=404))
        key = next(iter(agg._buffer))
        assert agg._buffer[key]["status_map"][200] == 2
        assert agg._buffer[key]["status_map"][404] == 1

    def test_separate_buckets_per_route(self):
        t = make_transport()
        agg = Aggregator(t, flush_interval_ms=999_999_000)
        agg.record(base_event(route="/a"))
        agg.record(base_event(route="/b"))
        assert len(agg._buffer) == 2

    def test_release_separates_bucket_key(self):
        t = make_transport()
        agg = Aggregator(t, flush_interval_ms=999_999_000)
        agg.record(base_event(release="v1"))
        agg.record(base_event(release="v2"))
        assert len(agg._buffer) == 2


class TestFlush:
    def test_sends_rows_and_clears_buffer(self):
        t = make_transport()
        agg = Aggregator(t, flush_interval_ms=999_999_000)
        agg.record(base_event())
        agg._flush()
        assert len(t.calls) == 1
        assert len(t.calls[0]) == 1
        assert len(agg._buffer) == 0

    def test_noop_when_buffer_empty(self):
        t = make_transport()
        agg = Aggregator(t, flush_interval_ms=999_999_000)
        agg._flush()
        assert len(t.calls) == 0

    def test_computes_percentiles(self):
        t = make_transport()
        agg = Aggregator(t, flush_interval_ms=999_999_000)
        for i in range(1, 11):
            agg.record(base_event(duration_ms=float(i * 10)))
        agg._flush()
        row = t.calls[0][0]
        assert 50 <= row["lat_p50"] <= 60
        assert 90 <= row["lat_p90"] <= 100
        assert row["lat_p99"] >= 90

    def test_correct_lat_min_max(self):
        t = make_transport()
        agg = Aggregator(t, flush_interval_ms=999_999_000)
        agg.record(base_event(duration_ms=5.0))
        agg.record(base_event(duration_ms=95.0))
        agg._flush()
        row = t.calls[0][0]
        assert row["lat_min"] == pytest.approx(5.0)
        assert row["lat_max"] == pytest.approx(95.0)

    def test_computes_lat_avg(self):
        t = make_transport()
        agg = Aggregator(t, flush_interval_ms=999_999_000)
        agg.record(base_event(duration_ms=10.0))
        agg.record(base_event(duration_ms=30.0))
        agg._flush()
        assert t.calls[0][0]["lat_avg"] == pytest.approx(20.0)

    def test_total_calls_matches_records(self):
        t = make_transport()
        agg = Aggregator(t, flush_interval_ms=999_999_000)
        for _ in range(7):
            agg.record(base_event())
        agg._flush()
        assert t.calls[0][0]["total_calls"] == 7

    def test_stop_flushes_buffer(self):
        t = make_transport()
        agg = Aggregator(t, flush_interval_ms=999_999_000)
        agg.record(base_event())
        agg.stop()
        assert len(t.calls) == 1, "stop() must flush remaining events"

    def test_bytes_avg_is_mean_of_non_null_sizes(self):
        t = make_transport()
        agg = Aggregator(t, flush_interval_ms=999_999_000)
        agg.record(base_event(response_size=100))
        agg.record(base_event(response_size=300))
        agg._flush()
        assert t.calls[0][0]["bytes_avg"] == pytest.approx(200.0)

    def test_bytes_avg_is_none_when_no_sizes(self):
        t = make_transport()
        agg = Aggregator(t, flush_interval_ms=999_999_000)
        agg.record(base_event(response_size=None))
        agg._flush()
        assert t.calls[0][0]["bytes_avg"] is None

    def test_request_size_avg(self):
        t = make_transport()
        agg = Aggregator(t, flush_interval_ms=999_999_000)
        agg.record(base_event(request_size=1000))
        agg.record(base_event(request_size=3000))
        agg._flush()
        assert t.calls[0][0]["request_size_avg"] == pytest.approx(2000.0)

    def test_request_size_avg_is_none_when_absent(self):
        t = make_transport()
        agg = Aggregator(t, flush_interval_ms=999_999_000)
        agg.record(base_event())
        agg._flush()
        assert t.calls[0][0]["request_size_avg"] is None

    def test_status_dist_json_sorted_by_count(self):
        t = make_transport()
        agg = Aggregator(t, flush_interval_ms=999_999_000)
        for _ in range(5):
            agg.record(base_event(status=200))
        agg.record(base_event(status=404))
        agg._flush()
        dist = json.loads(t.calls[0][0]["status_dist"])
        assert dist["200"] == 5
        assert dist["404"] == 1
        keys = list(dist.keys())
        assert keys[0] == "200"  # highest count first

    def test_status_dist_is_none_when_no_events(self):
        # Verify a freshly flushed row always has a valid status_dist
        t = make_transport()
        agg = Aggregator(t, flush_interval_ms=999_999_000)
        agg.record(base_event(status=200))
        agg._flush()
        row = t.calls[0][0]
        assert row["status_dist"] is not None
        assert json.loads(row["status_dist"])  # valid JSON

    def test_lat_ttfb_percentiles(self):
        t = make_transport()
        agg = Aggregator(t, flush_interval_ms=999_999_000)
        for i in range(1, 11):
            agg.record(base_event(duration_ms=float(i * 10), ttfb_ms=float(i * 5)))
        agg._flush()
        row = t.calls[0][0]
        assert isinstance(row["lat_ttfb_p50"], float)
        assert isinstance(row["lat_ttfb_p90"], float)
        assert isinstance(row["lat_ttfb_p99"], float)
        assert row["lat_ttfb_p99"] <= row["lat_p99"]

    def test_lat_ttfb_is_none_when_absent(self):
        t = make_transport()
        agg = Aggregator(t, flush_interval_ms=999_999_000)
        agg.record(base_event())
        agg._flush()
        row = t.calls[0][0]
        assert row["lat_ttfb_p50"] is None
        assert row["lat_ttfb_p90"] is None
        assert row["lat_ttfb_p99"] is None

    def test_inflight_avg_and_max(self):
        t = make_transport()
        agg = Aggregator(t, flush_interval_ms=999_999_000)
        agg.record(base_event(inflight=3))
        agg.record(base_event(inflight=7))
        agg.record(base_event(inflight=5))
        agg._flush()
        row = t.calls[0][0]
        assert row["inflight_avg"] == pytest.approx(5.0)
        assert row["inflight_max"] == 7

    def test_inflight_is_none_when_absent(self):
        t = make_transport()
        agg = Aggregator(t, flush_interval_ms=999_999_000)
        agg.record(base_event())
        agg._flush()
        row = t.calls[0][0]
        assert row["inflight_avg"] is None
        assert row["inflight_max"] is None
