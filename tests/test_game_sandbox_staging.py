"""Verify Render staging cannot accept Stripe payments before enablement."""
import pytest
from game_sandbox.staging_entrypoint import create_staging_app


def test_disabled_staging_health_is_explicit(monkeypatch):
    monkeypatch.delenv("NIJA_IQ_SANDBOX_ENABLED", raising=False)
    client = create_staging_app().test_client()
    result = client.get("/healthz")
    assert result.status_code == 200
    assert result.json["status"] == "staging_holding"
    assert result.json["checkout_available"] is False
    assert result.json["live_payments"] is False


@pytest.mark.parametrize("path, method", [
    ("/", "GET"),
    ("/sandbox/health", "GET"),
    ("/sandbox/runs", "POST"),
    ("/sandbox/runs/a" + "a" * 47 + "/checkout", "POST"),
    ("/sandbox/runs/a" + "a" * 47 + "/report", "GET"),
    ("/sandbox/stripe/webhook", "POST"),
])
def test_disabled_staging_never_exposes_payment_or_report(monkeypatch, path, method):
    monkeypatch.setenv("NIJA_IQ_SANDBOX_ENABLED", "false")
    result = create_staging_app().test_client().open(path, method=method)
    assert result.status_code == 503
    assert result.json["checkout_available"] is False
    assert result.json["live_payments"] is False
    assert result.headers["Cache-Control"] == "no-store"


def test_enabling_without_isolated_credentials_fails_startup(monkeypatch):
    monkeypatch.setenv("NIJA_IQ_SANDBOX_ENABLED", "true")
    for name in ("NIJA_IQ_SANDBOX_ORIGIN", "NIJA_IQ_SANDBOX_STRIPE_KEY"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises((KeyError, ValueError)):
        create_staging_app()


def test_enabled_health_bypasses_persistent_api_limit(monkeypatch, tmp_path):
    """Healthy enabled staging survives >300 Render probes; APIs retain quota."""
    import sqlite3
    from contextlib import contextmanager
    from types import SimpleNamespace
    from game_sandbox import app as sandbox_http

    monkeypatch.setenv("NIJA_IQ_SANDBOX_INGRESS_MODE", "direct")
    path = tmp_path / "staging_limits.sqlite3"
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE limits (owner_hash TEXT PRIMARY KEY, started INTEGER NOT NULL, count INTEGER NOT NULL)"
        )

    @contextmanager
    def isolated_db():
        conn = sqlite3.connect(path, timeout=5)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    service = SimpleNamespace(
        config=SimpleNamespace(origin="https://stage.example"),
        manifest=SimpleNamespace(digest="test-only"),
        db=isolated_db,
    )
    monkeypatch.setattr(sandbox_http, "from_environment", lambda: sandbox_http.create_app(service))
    monkeypatch.setenv("NIJA_IQ_SANDBOX_ENABLED", "true")
    client = create_staging_app().test_client()

    for _ in range(310):
        response = client.get("/healthz")
        assert response.status_code == 200
        assert response.json["live_payments"] is False

    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM limits").fetchone()[0] == 0

    for _ in range(300):
        assert client.get("/sandbox/health").status_code == 200
    assert client.get("/sandbox/health").status_code == 429
    assert client.get("/healthz").status_code == 200
