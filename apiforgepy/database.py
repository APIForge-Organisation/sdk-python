import sqlite3
import threading
import time


def _now_sec() -> int:
    return int(time.time())


class ApiForgeDatabase:
    def __init__(self, db_path: str):
        self._path = db_path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init()

    def _init(self):
        c = self._conn
        c.execute("PRAGMA journal_mode = WAL")
        c.execute("PRAGMA synchronous = NORMAL")
        c.executescript("""
            CREATE TABLE IF NOT EXISTS known_routes (
                route      TEXT NOT NULL,
                method     TEXT NOT NULL,
                first_seen INTEGER NOT NULL DEFAULT (strftime('%s','now')),
                PRIMARY KEY (route, method)
            );

            CREATE TABLE IF NOT EXISTS api_metrics (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                bucket_ts   INTEGER NOT NULL,
                route       TEXT NOT NULL,
                method      TEXT NOT NULL,
                env         TEXT NOT NULL DEFAULT 'production',
                release_tag TEXT,
                status_2xx  INTEGER NOT NULL DEFAULT 0,
                status_4xx  INTEGER NOT NULL DEFAULT 0,
                status_5xx  INTEGER NOT NULL DEFAULT 0,
                total_calls INTEGER NOT NULL DEFAULT 0,
                lat_p50     REAL,
                lat_p90     REAL,
                lat_p99     REAL,
                lat_min     REAL,
                lat_max     REAL,
                bytes_avg   REAL
            );

            CREATE INDEX IF NOT EXISTS idx_route_ts  ON api_metrics (route, method, bucket_ts);
            CREATE INDEX IF NOT EXISTS idx_bucket_ts ON api_metrics (bucket_ts);
            CREATE INDEX IF NOT EXISTS idx_release   ON api_metrics (release_tag)
                WHERE release_tag IS NOT NULL;
        """)
        # Migration for databases created before bytes_avg was introduced
        try:
            c.execute("ALTER TABLE api_metrics ADD COLUMN bytes_avg REAL")
        except Exception:
            pass  # column already exists
        c.commit()

    def insert_batch(self, rows: list[dict]):
        if not rows:
            return
        with self._lock:
            self._conn.executemany("""
                INSERT INTO api_metrics
                    (bucket_ts, route, method, env, release_tag,
                     status_2xx, status_4xx, status_5xx, total_calls,
                     lat_p50, lat_p90, lat_p99, lat_min, lat_max, bytes_avg)
                VALUES (
                    :bucket_ts, :route, :method, :env, :release_tag,
                    :status_2xx, :status_4xx, :status_5xx, :total_calls,
                    :lat_p50, :lat_p90, :lat_p99, :lat_min, :lat_max, :bytes_avg
                )
            """, rows)
            self._conn.commit()

    def upsert_known_routes(self, routes: list[dict]):
        with self._lock:
            self._conn.executemany("""
                INSERT INTO known_routes (route, method) VALUES (?, ?)
                ON CONFLICT (route, method) DO NOTHING
            """, [(r["route"], r["method"]) for r in routes])
            if routes:
                keys = [f"{r['route']}|{r['method']}" for r in routes]
                ph   = ",".join("?" * len(keys))
                self._conn.execute(f"""
                    DELETE FROM known_routes
                    WHERE route || '|' || method NOT IN ({ph})
                      AND NOT EXISTS (
                        SELECT 1 FROM api_metrics m
                        WHERE m.route = known_routes.route AND m.method = known_routes.method
                      )
                """, keys)
            self._conn.commit()

    def get_summary(self) -> dict:
        since_24h = _now_sec() - 86_400
        since_7d  = _now_sec() - 604_800
        c = self._conn

        recent = c.execute("""
            SELECT
                SUM(total_calls) as calls_total,
                SUM(status_2xx)  as calls_2xx,
                SUM(status_4xx)  as calls_4xx,
                SUM(status_5xx)  as calls_5xx,
                AVG(lat_p90)     as avg_p90,
                AVG(lat_p99)     as avg_p99
            FROM api_metrics WHERE bucket_ts >= ?
        """, (since_24h,)).fetchone()

        baseline = c.execute("""
            SELECT AVG(lat_p90) as baseline_p90
            FROM api_metrics WHERE bucket_ts >= ? AND bucket_ts < ?
        """, (since_7d, since_24h)).fetchone()

        active = c.execute("""
            SELECT COUNT(DISTINCT route || '|' || method) as n
            FROM api_metrics WHERE bucket_ts >= ?
        """, (since_24h,)).fetchone()

        total = c.execute("""
            SELECT COUNT(DISTINCT route || '|' || method) as n
            FROM api_metrics
        """).fetchone()

        return {
            "recent": dict(recent) if recent else {},
            "baseline": dict(baseline) if baseline else {},
            "active_routes": active["n"] if active else 0,
            "total_routes": total["n"] if total else 0,
        }

    def get_routes(self, hours: int = 24) -> list[dict]:
        since = _now_sec() - hours * 3600
        rows = self._conn.execute("""
            SELECT
                route, method,
                SUM(total_calls) as calls,
                SUM(status_2xx)  as calls_2xx,
                SUM(status_4xx)  as calls_4xx,
                SUM(status_5xx)  as calls_5xx,
                AVG(lat_p50)     as p50,
                AVG(lat_p90)     as p90,
                AVG(lat_p99)     as p99,
                MAX(lat_max)     as lat_max,
                AVG(bytes_avg)   as bytes_avg
            FROM api_metrics
            WHERE bucket_ts >= ?
            GROUP BY route, method
            ORDER BY calls DESC
            LIMIT 50
        """, (since,)).fetchall()
        return [dict(r) for r in rows]

    def get_time_series(self, route: str, method: str, hours: int = 24) -> list[dict]:
        since = _now_sec() - hours * 3600
        rows = self._conn.execute("""
            SELECT bucket_ts, SUM(total_calls) as calls,
                   AVG(lat_p50) as p50, AVG(lat_p90) as p90,
                   AVG(lat_p99) as p99, SUM(status_5xx) as errors
            FROM api_metrics
            WHERE route = ? AND method = ? AND bucket_ts >= ?
            GROUP BY bucket_ts ORDER BY bucket_ts ASC
        """, (route, method, since)).fetchall()
        return [dict(r) for r in rows]

    def get_dead_candidates(self, inactive_days: int = 21) -> list[dict]:
        cutoff = _now_sec() - inactive_days * 86_400
        rows = self._conn.execute("""
            SELECT route, method, MAX(bucket_ts) as last_seen
            FROM api_metrics
            GROUP BY route, method
            HAVING last_seen < ?
            ORDER BY last_seen ASC
        """, (cutoff,)).fetchall()
        return [dict(r) for r in rows]

    def get_release_comparison(self) -> dict | None:
        latest = self._conn.execute("""
            SELECT release_tag, MIN(bucket_ts) as release_ts
            FROM api_metrics
            WHERE release_tag IS NOT NULL AND release_tag != ''
            GROUP BY release_tag ORDER BY release_ts DESC LIMIT 1
        """).fetchone()

        if not latest:
            return None

        release_tag = latest["release_tag"]
        release_ts  = latest["release_ts"]
        window_before = release_ts - 86_400

        before = self._conn.execute("""
            SELECT route, method, AVG(lat_p90) as avg_p90, SUM(total_calls) as calls
            FROM api_metrics WHERE bucket_ts >= ? AND bucket_ts < ?
            GROUP BY route, method
        """, (window_before, release_ts)).fetchall()

        after = self._conn.execute("""
            SELECT route, method, AVG(lat_p90) as avg_p90, SUM(total_calls) as calls
            FROM api_metrics WHERE bucket_ts >= ? AND release_tag = ?
            GROUP BY route, method
        """, (release_ts, release_tag)).fetchall()

        return {
            "release_tag": release_tag,
            "release_ts": release_ts,
            "before": [dict(r) for r in before],
            "after":  [dict(r) for r in after],
        }

    def get_latency_anomaly_data(self) -> dict:
        since_1h = _now_sec() - 3_600
        since_7d = _now_sec() - 604_800

        recent = self._conn.execute("""
            SELECT route, method, AVG(lat_p99) as avg_p99
            FROM api_metrics WHERE bucket_ts >= ?
            GROUP BY route, method
        """, (since_1h,)).fetchall()

        baseline = self._conn.execute("""
            SELECT route, method, lat_p99
            FROM api_metrics
            WHERE bucket_ts >= ? AND bucket_ts < ? AND lat_p99 IS NOT NULL
        """, (since_7d, since_1h)).fetchall()

        return {
            "recent": [dict(r) for r in recent],
            "baseline_rows": [dict(r) for r in baseline],
        }

    def get_untracked_routes(self) -> list[dict]:
        rows = self._conn.execute("""
            SELECT k.route, k.method, k.first_seen
            FROM known_routes k
            WHERE NOT EXISTS (
                SELECT 1 FROM api_metrics m
                WHERE m.route = k.route AND m.method = k.method
            )
            ORDER BY k.method, k.route
        """).fetchall()
        return [dict(r) for r in rows]

    def get_releases(self) -> list[dict]:
        rows = self._conn.execute("""
            WITH release_times AS (
                SELECT release_tag, MIN(bucket_ts) AS release_ts
                FROM api_metrics
                WHERE release_tag IS NOT NULL AND release_tag != ''
                GROUP BY release_tag
            )
            SELECT rt.release_tag,
                   rt.release_ts,
                   (SELECT COUNT(*) FROM known_routes WHERE first_seen <= rt.release_ts + 60) AS routes_affected
            FROM release_times rt
            ORDER BY rt.release_ts DESC
            LIMIT 20
        """).fetchall()
        return [dict(r) for r in rows]

    def get_drift_data(self) -> list[dict]:
        """Returns one row per (route, method, day) over the last 30 days for drift detection."""
        since_30d = _now_sec() - 30 * 86_400
        rows = self._conn.execute("""
            SELECT
                route, method,
                CAST(bucket_ts / 86400 AS INTEGER) as day_bucket,
                AVG(lat_p90) as p90
            FROM api_metrics
            WHERE bucket_ts >= ? AND lat_p90 IS NOT NULL
            GROUP BY route, method, day_bucket
            ORDER BY route, method, day_bucket
        """, (since_30d,)).fetchall()
        return [dict(r) for r in rows]

    def get_global_time_series(self, hours: int = 24) -> list[dict]:
        since = _now_sec() - hours * 3600
        rows = self._conn.execute("""
            SELECT bucket_ts, SUM(total_calls) as calls,
                   AVG(lat_p50) as p50, AVG(lat_p90) as p90,
                   AVG(lat_p99) as p99, SUM(status_5xx) as errors
            FROM api_metrics WHERE bucket_ts >= ?
            GROUP BY bucket_ts ORDER BY bucket_ts ASC
        """, (since,)).fetchall()
        return [dict(r) for r in rows]

    def close(self):
        self._conn.close()
