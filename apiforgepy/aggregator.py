import json
import threading
import time
import math


def _percentile(sorted_vals: list[float], p: float) -> float:
    if not sorted_vals:
        return 0.0
    idx = max(0, min(math.ceil(p * len(sorted_vals)) - 1, len(sorted_vals) - 1))
    return sorted_vals[idx]


class Aggregator:
    def __init__(self, transport, flush_interval_ms: int = 60_000):
        self._transport = transport
        self._flush_interval = flush_interval_ms / 1000.0
        self._buffer: dict = {}
        self._lock = threading.Lock()
        self._timer: threading.Timer | None = None

    def start(self):
        self._schedule()

    def stop(self):
        if self._timer:
            self._timer.cancel()
            self._timer = None
        self._flush()

    def record(self, event: dict):
        is_ghost = event.get("is_ghost", False)
        key = f"{event['method']}|{event['route']}|{event['env']}|{event.get('release') or ''}|{'1' if is_ghost else '0'}"
        with self._lock:
            if key not in self._buffer:
                self._buffer[key] = {
                    "method":           event["method"],
                    "route":            event["route"],
                    "env":              event["env"],
                    "release":          event.get("release"),
                    "is_ghost":         is_ghost,
                    "durations":        [],
                    "ttfb_durations":   [],
                    "response_sizes":   [],
                    "request_sizes":    [],
                    "inflight_samples": [],
                    "status_2xx":       0,
                    "status_3xx":       0,
                    "status_4xx":       0,
                    "status_5xx":       0,
                    "status_map":       {},
                }
            bucket = self._buffer[key]
            bucket["durations"].append(event["duration_ms"])

            if event.get("ttfb_ms") is not None:
                bucket["ttfb_durations"].append(event["ttfb_ms"])
            if event.get("response_size") is not None:
                bucket["response_sizes"].append(event["response_size"])
            if event.get("request_size") is not None:
                bucket["request_sizes"].append(event["request_size"])
            if event.get("inflight") is not None:
                bucket["inflight_samples"].append(event["inflight"])

            s = event["status"]
            if   200 <= s < 300: bucket["status_2xx"] += 1
            elif 300 <= s < 400: bucket["status_3xx"] += 1
            elif 400 <= s < 500: bucket["status_4xx"] += 1
            elif s >= 500:       bucket["status_5xx"] += 1

            bucket["status_map"][s] = bucket["status_map"].get(s, 0) + 1

    def _schedule(self):
        self._timer = threading.Timer(self._flush_interval, self._tick)
        self._timer.daemon = True
        self._timer.start()

    def _tick(self):
        self._flush()
        self._schedule()

    def _flush(self):
        with self._lock:
            if not self._buffer:
                return
            snapshot = self._buffer
            self._buffer = {}

        bucket_ts = int(time.time() // 60) * 60
        rows = []

        for bucket in snapshot.values():
            sorted_d    = sorted(bucket["durations"])
            sorted_ttfb = sorted(bucket["ttfb_durations"])
            n = len(sorted_d)

            sizes     = bucket["response_sizes"]
            req_sizes = bucket["request_sizes"]
            inflight  = bucket["inflight_samples"]

            bytes_avg        = sum(sizes) / len(sizes)         if sizes     else None
            request_size_avg = sum(req_sizes) / len(req_sizes) if req_sizes else None
            lat_avg          = sum(bucket["durations"]) / n    if n > 0     else None
            inflight_avg     = sum(inflight) / len(inflight)   if inflight  else None
            inflight_max     = max(inflight)                   if inflight  else None

            # Granular distribution — sorted by count desc
            status_dist = (
                json.dumps(
                    dict(sorted(bucket["status_map"].items(), key=lambda x: -x[1]))
                )
                if bucket["status_map"] else None
            )

            rows.append({
                "bucket_ts":        bucket_ts,
                "route":            bucket["route"],
                "method":           bucket["method"],
                "env":              bucket["env"],
                "release_tag":      bucket["release"],
                "is_ghost":         1 if bucket["is_ghost"] else 0,
                "status_2xx":       bucket["status_2xx"],
                "status_3xx":       bucket["status_3xx"],
                "status_4xx":       bucket["status_4xx"],
                "status_5xx":       bucket["status_5xx"],
                "status_dist":      status_dist,
                "total_calls":      n,
                "lat_p50":          _percentile(sorted_d, 0.50),
                "lat_p90":          _percentile(sorted_d, 0.90),
                "lat_p99":          _percentile(sorted_d, 0.99),
                "lat_avg":          lat_avg,
                "lat_min":          sorted_d[0]  if sorted_d  else 0,
                "lat_max":          sorted_d[-1] if sorted_d  else 0,
                "lat_ttfb_p50":     _percentile(sorted_ttfb, 0.50) if sorted_ttfb else None,
                "lat_ttfb_p90":     _percentile(sorted_ttfb, 0.90) if sorted_ttfb else None,
                "lat_ttfb_p99":     _percentile(sorted_ttfb, 0.99) if sorted_ttfb else None,
                "bytes_avg":        bytes_avg,
                "request_size_avg": request_size_avg,
                "inflight_avg":     inflight_avg,
                "inflight_max":     inflight_max,
            })

        self._transport.write(rows)
