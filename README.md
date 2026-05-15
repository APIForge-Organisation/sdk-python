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

app.add_middleware(
    ApiForgeMiddleware,
    mode="local",
)

@app.get("/users/{user_id}")
def get_user(user_id: int):
    return {"id": user_id}

# Dashboard → http://localhost:4242
```

## Configuration

```python
app.add_middleware(
    ApiForgeMiddleware,
    mode="local",
    db_path=".apiforge.db",
    dashboard_port=4242,       # set to 0 to disable
    flush_interval=60_000,     # ms
    env="production",
    release="v1.4.0",          # enables release regression detection
    service="user-service",
    sampling=1.0,              # 0.0–1.0
    ignore_paths=["/health", "/favicon.ico"],
)
```

## What you get

- **Latency percentiles** — P50 / P90 / P99 per endpoint, updated every 60s
- **Error rate by route** — 2xx / 4xx / 5xx breakdown in real time
- **API Health Score** — a single 0–100 score summarizing your API's health
- **Automatic insights** — plain-language alerts with no configuration
- **Dead endpoint detection** — routes with no traffic in 21+ days
- **Release impact tracking** — before/after comparison on every deploy

## Graceful shutdown

```python
import signal

mw = None

@asynccontextmanager
async def lifespan(app):
    yield
    if mw:
        mw.shutdown()

app = FastAPI(lifespan=lifespan)
mw = ApiForgeMiddleware.__new__(ApiForgeMiddleware)
app.add_middleware(ApiForgeMiddleware, mode="local")
```

## Privacy by design

The middleware **never** reads request or response bodies, headers, cookies, or tokens. Route parameters are captured as patterns only (`/users/{user_id}` — never `/users/42`). In local mode, zero data leaves your machine.

## Requirements

- Python ≥ 3.11
- Starlette ≥ 0.27 (FastAPI ≥ 0.110 includes this)

## License

MIT — [APIForge Organisation](https://github.com/APIForge-Organisation)
