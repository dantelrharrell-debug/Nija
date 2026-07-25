from __future__ import annotations

import importlib


def _module():
    return importlib.import_module("bot.canonical_broker_startup_convergence_v24")


def test_kraken_recovery_accepts_platform_credentials(monkeypatch):
    module = _module()
    monkeypatch.setenv("KRAKEN_PLATFORM_API_KEY", "key")
    monkeypatch.setenv("KRAKEN_PLATFORM_API_SECRET", "secret")
    monkeypatch.delenv("KRAKEN_API_KEY", raising=False)
    monkeypatch.delenv("KRAKEN_API_SECRET", raising=False)
    monkeypatch.delenv("NIJA_DISABLE_KRAKEN", raising=False)
    monkeypatch.delenv("KRAKEN_EXECUTION_DISABLED", raising=False)
    assert module._kraken_credentials_configured() is True


def test_kraken_recovery_accepts_canonical_aliases(monkeypatch):
    module = _module()
    monkeypatch.delenv("KRAKEN_PLATFORM_API_KEY", raising=False)
    monkeypatch.delenv("KRAKEN_PLATFORM_API_SECRET", raising=False)
    monkeypatch.setenv("KRAKEN_API_KEY", "key")
    monkeypatch.setenv("KRAKEN_API_SECRET", "secret")
    monkeypatch.delenv("NIJA_DISABLE_KRAKEN", raising=False)
    monkeypatch.delenv("KRAKEN_EXECUTION_DISABLED", raising=False)
    assert module._kraken_credentials_configured() is True


def test_kraken_recovery_respects_explicit_disable(monkeypatch):
    module = _module()
    monkeypatch.setenv("KRAKEN_PLATFORM_API_KEY", "key")
    monkeypatch.setenv("KRAKEN_PLATFORM_API_SECRET", "secret")
    monkeypatch.setenv("NIJA_DISABLE_KRAKEN", "true")
    assert module._kraken_credentials_configured() is False
