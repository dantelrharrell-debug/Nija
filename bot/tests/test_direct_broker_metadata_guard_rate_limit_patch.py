from __future__ import annotations

from bot import direct_broker_metadata_guard_patch as patch


def test_unavailable_log_is_rate_limited(monkeypatch):
    calls = []
    monkeypatch.setenv("NIJA_DIRECT_BROKER_METADATA_UNAVAILABLE_LOG_WINDOW_S", "30")
    monkeypatch.setattr(patch.logger, "warning", lambda *args, **kwargs: calls.append(args))
    monkeypatch.setattr(patch.logger, "debug", lambda *args, **kwargs: None)
    patch._UNAVAILABLE_LOG_TS.clear()

    patch._log_unavailable_rate_limited("coinbase", symbol="AI16Z-USD")
    patch._log_unavailable_rate_limited("coinbase", symbol="AI16Z-USD")

    assert len(calls) == 1
    assert "DIRECT_BROKER_METADATA_RESOLVE_UNAVAILABLE" in calls[0][0]


def test_resolve_live_client_short_circuits_recent_miss(monkeypatch):
    class Router:
        pass

    resolver_calls = {"count": 0}

    def fake_scan(seed, target):
        resolver_calls["count"] += 1
        return None

    monkeypatch.setenv("NIJA_DIRECT_BROKER_METADATA_MISS_CACHE_S", "60")
    monkeypatch.setattr(patch, "_scan_for_client", fake_scan)
    monkeypatch.setattr(patch, "_module_candidates", lambda target: [])
    monkeypatch.setattr(patch, "_log_unavailable_rate_limited", lambda *args, **kwargs: None)
    patch._UNAVAILABLE_CACHE.clear()
    patch._RESOLVED_CACHE.clear()

    assert patch._resolve_live_client(Router(), "coinbase", symbol="AI16Z-USD") is None
    assert patch._resolve_live_client(Router(), "coinbase", symbol="AI16Z-USD") is None

    assert resolver_calls["count"] == 1
