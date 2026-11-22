"""Backend: error responses never leak internals; request IDs; production safety checks."""

from fastapi.testclient import TestClient

from app.config import Settings
from app.db.session import normalize_db_url
from app.main import app


def test_unexpected_errors_are_hidden_and_traceable(client):
    @app.get("/api/_boom")
    def boom():
        raise RuntimeError("database password is hunter2")

    try:
        with TestClient(app, raise_server_exceptions=False) as c:
            r = c.get("/api/_boom", headers={"X-Request-ID": "abc123"})
        assert r.status_code == 500
        assert r.json() == {"detail": "Internal server error", "request_id": "abc123"}
        assert "hunter2" not in r.text and r.headers["X-Request-ID"] == "abc123"
    finally:
        app.router.routes = [rt for rt in app.router.routes if getattr(rt, "path", "") != "/api/_boom"]


def test_every_response_has_a_request_id(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and len(r.headers["X-Request-ID"]) == 16


def test_production_safety_checks():
    unsafe = Settings(_env_file=None, secret_key="dev-only-change-me", database_url="sqlite:///x.db", cors_origins="*")
    assert len(unsafe.production_problems()) == 3
    safe = Settings(_env_file=None, secret_key="k" * 40, database_url="postgresql://u:p@h/db",
                    cors_origins="https://app.example.com")
    assert safe.production_problems() == []


def test_database_url_normalisation():
    assert normalize_db_url("postgres://u:p@h/db") == "postgresql+psycopg://u:p@h/db"
    assert normalize_db_url("postgresql://u:p@h/db") == "postgresql+psycopg://u:p@h/db"
    assert normalize_db_url("sqlite:///x.db") == "sqlite:///x.db"
