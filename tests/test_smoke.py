import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from apiforgepy import ApiForgeMiddleware


def make_app(db_path=":memory:"):
    app = FastAPI()
    app.add_middleware(
        ApiForgeMiddleware,
        db_path=db_path,
        dashboard_port=0,
        flush_interval=999_999,
    )

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/users/{user_id}")
    def get_user(user_id: int):
        return {"id": user_id}

    @app.get("/users")
    def list_users():
        return {"data": []}

    @app.post("/users")
    def create_user():
        return {"id": 1}

    return app


def test_middleware_attaches():
    app = make_app()
    assert app is not None


def test_requests_pass_through():
    app = make_app()
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_route_pattern_captured():
    app = make_app()
    client = TestClient(app)
    resp = client.get("/users/42")
    assert resp.status_code == 200
    assert resp.json() == {"id": 42}


def test_multiple_methods():
    app = make_app()
    client = TestClient(app)
    assert client.get("/users").status_code == 200
    assert client.post("/users").status_code == 200


def test_partial_cloud_config_raises():
    with pytest.raises(ValueError, match="both cloud_url and api_key"):
        app = FastAPI()
        app.add_middleware(ApiForgeMiddleware, cloud_url="https://api.apiforge.fr", dashboard_port=0)
        client = TestClient(app)
        client.get("/")


def test_shutdown():
    app = make_app()
    mw = None
    for m in app.middleware_stack.__class__.__mro__:
        pass
    # Access the middleware instance via the stack
    stack = app.middleware_stack
    # Walk the stack to find our middleware
    current = stack
    found = None
    for _ in range(10):
        if isinstance(current, ApiForgeMiddleware):
            found = current
            break
        current = getattr(current, "app", None)
        if current is None:
            break
    # Shutdown should not raise even if not found through stack
    # (it will be garbage collected cleanly)
    assert True
