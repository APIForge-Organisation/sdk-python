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
        key = f"{event['method']}|{event['route']}|{event['env']}|{event.get('release') or ''}"
        with self._lock:
            if key not in self._buffer:
                self._buffer[key] = {
                    "method":         event["method"],
                    "route":          event["route"],
                    "env":            event["env"],
                    "release":        event.get("release"),
                    "durations":      [],
                    "response_sizes": [],
                    "status_2xx":     0,
                    "status_4xx":     0,
                    "status_5xx":     0,
                }
            bucket = self._buffer[key]
            bucket["durations"].append(event["duration_ms"])
            if event.get("response_size") is not None:
                bucket["response_sizes"].append(event["response_size"])
            s = event["status"]
            if 200 <= s < 300:
                bucket["status_2xx"] += 1
            elif 400 <= s < 500:
                bucket["status_4xx"] += 1
            elif s >= 500:
                bucket["status_5xx"] += 1

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
            sorted_d = sorted(bucket["durations"])
            n = len(sorted_d)
            sizes = bucket["response_sizes"]
            bytes_avg = sum(sizes) / len(sizes) if sizes else None
            rows.append({
                "bucket_ts":   bucket_ts,
                "route":       bucket["route"],
                "method":      bucket["method"],
                "env":         bucket["env"],
                "release_tag": bucket["release"],
                "status_2xx":  bucket["status_2xx"],
                "status_4xx":  bucket["status_4xx"],
                "status_5xx":  bucket["status_5xx"],
                "total_calls": n,
                "lat_p50":     _percentile(sorted_d, 0.50),
                "lat_p90":     _percentile(sorted_d, 0.90),
                "lat_p99":     _percentile(sorted_d, 0.99),
                "lat_min":     sorted_d[0] if sorted_d else 0,
                "lat_max":     sorted_d[-1] if sorted_d else 0,
                "bytes_avg":   bytes_avg,
            })

        self._transport.write(rows)
