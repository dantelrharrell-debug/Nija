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
