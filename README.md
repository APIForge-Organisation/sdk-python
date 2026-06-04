# apiforgepy

**API observability & intelligence for FastAPI/Starlette — local-first, privacy-first.**

[![PyPI version](https://img.shields.io/pypi/v/apiforgepy?color=0066FF)](https://pypi.org/project/apiforgepy/)
[![CI](https://img.shields.io/github/actions/workflow/status/APIForge-Organisation/sdk-python/ci.yml?branch=main&label=CI)](https://github.com/APIForge-Organisation/sdk-python/actions)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Python](https://img.shields.io/badge/python-%3E%3D3.11-brightgreen)](https://python.org)

> Track latency, error rates, and behavioral trends of your APIs. Everything stays on your machine.

**→ [Full documentation](https://apiforge-organisation.github.io/docs/)**

---

## Install

```bash
pip install apiforgepy
```

## Quick start

```python
from fastapi import FastAPI
from apiforgepy import ApiForgeMiddleware

app = FastAPI()

app.add_middleware(ApiForgeMiddleware)

@app.get("/users/{user_id}")
def get_user(user_id: int):
    return {"id": user_id}

# Dashboard auto-starts at http://localhost:4242
```

## Dashboard

Open **http://localhost:4242** after starting your app. No configuration needed — the dashboard server starts automatically in the background.

- **Health Score** (0–100) — global API health at a glance
- **Latency percentiles** — P50 / P90 / P99 per route
- **Error rates** — 4xx and 5xx breakdown
- **Automatic insights** — latency anomalies, dead endpoints, release regressions
- **Time series chart** — click any route to see its latency over time

Data is stored locally in `.apiforge.db` (SQLite). Nothing leaves your machine.

## Configuration

```python
app.add_middleware(
    ApiForgeMiddleware,
    db_path=".apiforge.db",
    dashboard_port=4242,        # set to 0 to disable
    env="production",
    release="v1.4.0",           # enables release regression detection
    service="user-service",
    sampling=1.0,               # 0.0–1.0 sample rate
    ignore_paths=["/health", "/favicon.ico"],
)
```

## Cloud mode

Send metrics to the APIForge SaaS platform instead of storing them locally:

```python
app.add_middleware(
    ApiForgeMiddleware,
    cloud_url=os.environ["APIFORGE_CLOUD_URL"],
    api_key=os.environ["APIFORGE_API_KEY"],
    service="user-service",
    env="production",
    release=os.environ.get("APP_VERSION"),
)
```

In cloud mode, metrics are aggregated in memory for 60 seconds and sent as a single batch — the local dashboard and SQLite database are not used.

## Release tracking

Pass your release version to enable before/after deployment comparison:

```python
import os
app.add_middleware(ApiForgeMiddleware, release=os.environ.get("APP_VERSION"))
```

When a new release is detected, APIForge compares P90 latency before and after and surfaces regressions automatically.

## What you get

- **Per-route latency** — P50, P90, P99 per endpoint, updated every 60 s
- **Error rate by route** — 2xx / 3xx / 4xx / 5xx breakdown
- **API Health Score** — a single 0–100 score summarising your API's health
- **Ghost route detection** — requests that match no declared Starlette/FastAPI route
- **Latency anomaly alerts** — Z-score detection against a 7-day baseline
- **Dead endpoint detection** — routes with no traffic for 21+ days
- **Release regression analysis** — automatic P90 comparison per deploy
- **Progressive drift detection** — slow latency increases over weeks
- **Untracked route detection** — declared routes that never received traffic
- **Inflight concurrency tracking** — `inflight_avg` and `inflight_max` per route

## Graceful shutdown

Cleanup (flush buffer, close dashboard, close SQLite) happens automatically via `atexit`. For explicit control in long-running processes:

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from apiforgepy import ApiForgeMiddleware

forge = None

@asynccontextmanager
async def lifespan(app):
    yield
    if forge:
        forge.shutdown()

app = FastAPI(lifespan=lifespan)
forge = ApiForgeMiddleware(app)  # store reference before adding
app.add_middleware(ApiForgeMiddleware)
```

## Privacy by design

The middleware **never** reads request or response bodies, headers, cookies, or tokens. Route parameters are captured as patterns only (`/users/{user_id}` — never `/users/42`). In local mode, zero data leaves your machine.

## Requirements

- Python ≥ 3.11
- Starlette ≥ 0.27 (FastAPI ≥ 0.110 includes this)

## License

MIT — [APIForge Organisation](https://github.com/APIForge-Organisation)
