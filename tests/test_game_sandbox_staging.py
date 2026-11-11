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
    # Isolate the credential failure from the independent private-disk gate.
    from game_sandbox import staging_bootstrap
    monkeypatch.setattr(staging_bootstrap, "validate_runtime", lambda: None)
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
    from game_sandbox import staging_bootstrap

    # Simulate an approved disk for the HTTP quota test, not for startup safety.
    monkeypatch.setattr(staging_bootstrap, "validate_runtime", lambda: None)
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

    from game_sandbox import preview_assets
    monkeypatch.setattr(preview_assets, "install_preview_ui", lambda app: SimpleNamespace(manifest_sha256="fixture"))

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


def test_enabled_direct_wsgi_startup_rejects_missing_private_mount_first(monkeypatch):
    """Direct Gunicorn imports must never bypass the private-disk requirement."""
    from game_sandbox import staging_bootstrap
    from game_sandbox import app as sandbox_http

    monkeypatch.setenv("NIJA_IQ_SANDBOX_ENABLED", "true")
    monkeypatch.setenv("NIJA_IQ_SANDBOX_DATABASE", "/var/data/trading_iq_sandbox.sqlite3")
    monkeypatch.setattr(staging_bootstrap.os, "geteuid", lambda: 10001)
    monkeypatch.setattr(staging_bootstrap, "has_dedicated_mount", lambda path: False)
    calls = []

    def no_payment_initialization():
        calls.append("payment")
        raise AssertionError("payment service reached before storage preflight")

    monkeypatch.setattr(sandbox_http, "from_environment", no_payment_initialization)

    with pytest.raises(RuntimeError, match="sandbox_persistent_mount_required"):
        create_staging_app()
    assert calls == []


def test_enabled_direct_wsgi_startup_rejects_root_before_payment(monkeypatch):
    from game_sandbox import staging_bootstrap
    from game_sandbox import app as sandbox_http

    monkeypatch.setenv("NIJA_IQ_SANDBOX_ENABLED", "true")
    monkeypatch.setattr(staging_bootstrap.os, "geteuid", lambda: 0)
    monkeypatch.setattr(sandbox_http, "from_environment",
                        lambda: pytest.fail("payment initialized under root"))
    with pytest.raises(RuntimeError, match="sandbox_non_root_user_required"):
        create_staging_app()


def test_disabled_wsgi_entrypoint_never_needs_or_calls_storage_preflight(monkeypatch):
    from game_sandbox import staging_bootstrap

    monkeypatch.setenv("NIJA_IQ_SANDBOX_ENABLED", "false")
    monkeypatch.setattr(staging_bootstrap, "validate_runtime",
                        lambda: pytest.fail("disabled standby probed payment disk"))
    client = create_staging_app().test_client()
    assert client.get("/healthz").json["status"] == "staging_holding"
    assert client.post("/sandbox/runs").status_code == 503
