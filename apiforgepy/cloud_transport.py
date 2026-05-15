import json
import time
import threading
import urllib.request
import urllib.error
from datetime import datetime, timezone

_CIRCUIT_OPEN_S   = 60
_FAILURE_THRESHOLD = 5


class CloudTransport:
    """Sends aggregated metrics to the APIForge SaaS ingest endpoint."""

    def __init__(self, cloud_url: str, api_key: str, service: str):
        self._url     = cloud_url.rstrip("/") + "/ingest"
        self._api_key = api_key
        self._service = service
        self._failures  = 0
        self._open_until = 0.0
        self._lock = threading.Lock()

    def write(self, rows: list[dict]) -> None:
        if not rows:
            return
        if time.monotonic() < self._open_until:
            return

        metrics = [
            {
                "route":       r["route"],
                "method":      r["method"],
                "service":     self._service,
                "env":         r["env"],
                "release":     r.get("release_tag"),
                "time":        datetime.fromtimestamp(r["bucket_ts"], tz=timezone.utc).isoformat(),
                "calls_total": r["total_calls"],
                "calls_2xx":   r["status_2xx"],
                "calls_4xx":   r["status_4xx"],
                "calls_5xx":   r["status_5xx"],
                "lat_p50":     r.get("lat_p50"),
                "lat_p90":     r.get("lat_p90"),
                "lat_p99":     r.get("lat_p99"),
                "lat_avg":     r.get("lat_avg"),
                "bytes_avg":   r.get("bytes_avg"),
            }
            for r in rows
        ]

        payload = json.dumps({"metrics": metrics}).encode()
        req = urllib.request.Request(
            self._url,
            data=payload,
            headers={"Content-Type": "application/json", "X-API-Key": self._api_key},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=10):
                with self._lock:
                    self._failures = 0
        except (urllib.error.URLError, OSError) as exc:
            with self._lock:
                self._failures += 1
                if self._failures >= _FAILURE_THRESHOLD:
                    self._open_until = time.monotonic() + _CIRCUIT_OPEN_S
                    self._failures   = 0
                    print(
                        f"[apiforgepy] Cloud flush failures — pausing for {_CIRCUIT_OPEN_S}s. "
                        f"Error: {exc}"
                    )
