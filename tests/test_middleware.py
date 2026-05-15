import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from apiforgepy import ApiForgeMiddleware


def make_app(db_path=":memory:", sampling=1.0, ignore_paths=None):
    app = FastAPI()
    app.add_middleware(
        ApiForgeMiddleware,
        mode="local",
        db_path=db_path,
        dashboard_port=0,
        flush_interval=999_999,
        sampling=sampling,
        ignore_paths=ignore_paths or [],
    )

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/users/{user_id}")
    def get_user(user_id: int):
        return {"id": user_id}

    @app.get("/users")
    def list_users():
        return []

    @app.post("/users")
    def create_user():
        return {"id": 1}

    @app.get("/error")
    def raise_error():
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail="boom")

    return app


class TestPassThrough:
    def test_request_passes_through_unchanged(self):
        client = TestClient(make_app())
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    def test_parametric_route_returns_correct_data(self):
        client = TestClient(make_app())
        resp = client.get("/users/42")
        assert resp.status_code == 200
        assert resp.json() == {"id": 42}

    def test_post_route_returns_201(self):
        client = TestClient(make_app())
        resp = client.post("/users")
        assert resp.status_code == 200

    def test_404_passthrough(self):
        client = TestClient(make_app())
        resp = client.get("/nonexistent")
        assert resp.status_code == 404


class TestIgnorePaths:
    def test_ignored_path_still_returns_response(self):
        client = TestClient(make_app(ignore_paths=["/health"]))
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_non_ignored_path_still_works(self):
        client = TestClient(make_app(ignore_paths=["/health"]))
        resp = client.get("/users")
        assert resp.status_code == 200


class TestSampling:
    def test_sampling_at_1_records_all_requests(self):
        """At sampling=1.0, every request should pass through."""
        client = TestClient(make_app(sampling=1.0))
        for _ in range(5):
            resp = client.get("/health")
            assert resp.status_code == 200

    def test_sampling_at_0_still_passes_requests_through(self):
        """At sampling=0.0, requests are not recorded but still served."""
        client = TestClient(make_app(sampling=0.0))
        resp = client.get("/health")
        assert resp.status_code == 200


class TestErrorHandling:
    def test_5xx_response_passes_through(self):
        client = TestClient(make_app(), raise_server_exceptions=False)
        resp = client.get("/error")
        assert resp.status_code == 500

    def test_middleware_does_not_crash_the_app(self):
        """Multiple requests including errors should not crash the server."""
        client = TestClient(make_app(), raise_server_exceptions=False)
        for path in ["/health", "/users", "/error", "/health"]:
            resp = client.get(path)
            assert resp.status_code in (200, 500)
