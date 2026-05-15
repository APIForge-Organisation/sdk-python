import math
import time

DEAD_ENDPOINT_DAYS   = 21
REGRESSION_THRESHOLD = 0.20
ANOMALY_Z_THRESHOLD  = 2.5


def get_insights(db) -> list[dict]:
    insights = []
    for fn in (
        _detect_latency_anomalies,
        _detect_dead_endpoints,
        _detect_release_regressions,
        _detect_untracked_routes,
    ):
        try:
            insights.extend(fn(db))
        except Exception:
            pass
    return insights


def compute_health_score(db) -> int | None:
    try:
        s = db.get_summary()
        total = (s["recent"] or {}).get("calls_total") or 0
        if not total:
            return None

        recent   = s["recent"]
        baseline = s["baseline"]

        availability = min(100.0, ((recent.get("calls_2xx") or 0) / total) * 100)

        performance = 100.0
        b_p90 = (baseline or {}).get("baseline_p90")
        r_p90 = (recent or {}).get("avg_p90")
        if b_p90 and r_p90 and b_p90 > 0:
            ratio = r_p90 / b_p90
            performance = max(0.0, min(100.0, 100 - (ratio - 1) * 100))

        stability = 100.0

        active = s["active_routes"]
        total_r = s["total_routes"]
        quality = min(100.0, (active / total_r) * 100) if total_r > 0 else 100.0

        score = availability * 0.30 + performance * 0.30 + stability * 0.25 + quality * 0.15
        return round(score)
    except Exception:
        return None


def _detect_latency_anomalies(db) -> list[dict]:
    data = db.get_latency_anomaly_data()
    recent       = data["recent"]
    baseline_rows = data["baseline_rows"]

    if not recent or not baseline_rows:
        return []

    baseline_map: dict[str, list[float]] = {}
    for row in baseline_rows:
        key = f"{row['method']}|{row['route']}"
        baseline_map.setdefault(key, []).append(row["lat_p99"])

    insights = []
    for r in recent:
        key = f"{r['method']}|{r['route']}"
        samples = baseline_map.get(key, [])
        if len(samples) < 5:
            continue

        mean = sum(samples) / len(samples)
        variance = sum((v - mean) ** 2 for v in samples) / len(samples)
        stdev = math.sqrt(variance)
        if stdev == 0:
            continue

        z = (r["avg_p99"] - mean) / stdev
        if z >= ANOMALY_Z_THRESHOLD:
            insights.append({
                "type":     "ANOMALY",
                "severity": "warning",
                "route":    r["route"],
                "method":   r["method"],
                "message":  (
                    f"`{r['method']} {r['route']}` P99 latency is abnormally high "
                    f"({_fmt(r['avg_p99'])} vs baseline {_fmt(mean)} — Z-score {z:.1f})."
                ),
                "data": {"current_p99": r["avg_p99"], "baseline_p99": mean, "z_score": z},
            })
    return insights


def _detect_dead_endpoints(db) -> list[dict]:
    candidates = db.get_dead_candidates(DEAD_ENDPOINT_DAYS)
    insights = []
    now = time.time()
    for row in candidates:
        days = int((now - row["last_seen"]) / 86_400)
        insights.append({
            "type":     "DEAD",
            "severity": "info",
            "route":    row["route"],
            "method":   row["method"],
            "message":  (
                f"`{row['method']} {row['route']}` has received no requests "
                f"in {days} days. Consider deprecating this endpoint."
            ),
            "data": {"last_seen_ts": row["last_seen"], "inactive_days": days},
        })
    return insights


def _detect_release_regressions(db) -> list[dict]:
    comparison = db.get_release_comparison()
    if not comparison:
        return []

    release_tag = comparison["release_tag"]
    before_map = {
        f"{r['method']}|{r['route']}": r for r in comparison["before"]
    }

    insights = []
    for a in comparison["after"]:
        key = f"{a['method']}|{a['route']}"
        b = before_map.get(key)
        if not b or not b.get("avg_p90") or not a.get("avg_p90") or b["avg_p90"] == 0:
            continue

        delta = (a["avg_p90"] - b["avg_p90"]) / b["avg_p90"]

        if delta >= REGRESSION_THRESHOLD:
            insights.append({
                "type":     "PERF",
                "severity": "error",
                "route":    a["route"],
                "method":   a["method"],
                "message":  (
                    f"`{a['method']} {a['route']}` P90 increased by {_pct(delta)} "
                    f"after {release_tag}. Before: {_fmt(b['avg_p90'])} — After: {_fmt(a['avg_p90'])}."
                ),
                "data": {"release": release_tag, "before_p90": b["avg_p90"], "after_p90": a["avg_p90"], "delta_pct": delta * 100},
            })
        elif delta <= -REGRESSION_THRESHOLD:
            insights.append({
                "type":     "OK",
                "severity": "success",
                "route":    a["route"],
                "method":   a["method"],
                "message":  (
                    f"{release_tag} improved `{a['method']} {a['route']}` by {_pct(-delta)}. "
                    f"Before: {_fmt(b['avg_p90'])} — After: {_fmt(a['avg_p90'])}."
                ),
                "data": {"release": release_tag, "before_p90": b["avg_p90"], "after_p90": a["avg_p90"], "delta_pct": delta * 100},
            })
    return insights


def _detect_untracked_routes(db) -> list[dict]:
    return [
        {
            "type":     "UNTRACKED",
            "severity": "info",
            "route":    r["route"],
            "method":   r["method"],
            "message":  (
                f"`{r['method']} {r['route']}` is declared but has received "
                "no requests since monitoring started."
            ),
            "data": {"first_seen_ts": r["first_seen"]},
        }
        for r in db.get_untracked_routes()
    ]


def _fmt(ms: float | None) -> str:
    return "N/A" if ms is None else f"{round(ms)}ms"


def _pct(ratio: float) -> str:
    return f"{round(ratio * 100)}%"
