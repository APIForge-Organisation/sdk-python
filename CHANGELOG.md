# Changelog

All notable changes to `apiforgepy` are documented here.

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) — versioning follows [Semantic Versioning](https://semver.org/).

---

## [1.0.3] — 2026-05-15

### Added

- `DRIFT` insight type: detects progressive latency degradation using ordinary least squares over the last 30 days — emitted when slope ≥ 5ms/day over 7+ data points, with a 30-day projection
- `DRIFT` filter chip added to the dashboard Insights view
- 60 unit tests covering `aggregator`, `database`, `insights` and `middleware`

### Fixed

- CI badge was pointing to `main` with no workflow run — CI now triggers on both `main` and `dev`

---

## [1.0.0] — 2026-05-15

### Fixed

- `/api/summary` now returns a flat response structure (`calls_24h`, `error_rate_24h`, `avg_p90_24h`, `active_routes`) matching the React dashboard frontend — fixes "0 requests" display

### Added

- `/api/global-timeseries` endpoint consumed by the dashboard overview chart
- `/api/releases` endpoint (returns `[]` for now — release tracking planned)

### Changed

- Dashboard UI now loads React and Babel from jsDelivr CDN instead of local assets, making `ui.html` SDK-agnostic

---

## [0.1.0] — 2026-05-15

### Added

- Starlette/FastAPI middleware `ApiForgeMiddleware` — drop-in observability with zero mandatory configuration
- Local-first mode with SQLite storage via Python's built-in `sqlite3` module (requires Python ≥ 3.11)
- Per-endpoint metrics: P50 / P90 / P99 latency, request count, 2xx / 4xx / 5xx breakdown
- In-memory aggregation with configurable flush interval (default: 60s), thread-safe
- Circuit breaker on the transport layer — middleware never crashes the host application
- Built-in dashboard on port 4242 with dark theme, Chart.js time series, routes table and insights panel
- REST API: `/api/summary`, `/api/routes`, `/api/timeseries`, `/api/insights`
- Three automatic insight types: `ANOMALY` (Z-score P99), `DEAD` (endpoint inactive 21+ days), `PERF`/`OK` (regression or improvement after a release)
- API Health Score (0–100) combining availability, performance, stability and quality
- Configurable sampling rate, ignored paths, environment label, release tag and service name
- `middleware.shutdown()` for graceful teardown (flushes buffer, closes SQLite)

[1.0.0]: https://github.com/APIForge-Organisation/sdk-python/releases/tag/v1.0.0
[0.1.0]: https://github.com/APIForge-Organisation/sdk-python/releases/tag/v0.1.0
