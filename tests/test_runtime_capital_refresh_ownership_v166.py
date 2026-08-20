from datetime import datetime, timezone
from types import SimpleNamespace

import bot.runtime_capital_refresh_ownership_v166_patch as v166


def test_proactive_timing_defaults_preserve_large_expiry_margin(monkeypatch):
    monkeypatch.setattr(v166, "_freshness_ttl_seconds", lambda: 90.0)
    monkeypatch.delenv("NIJA_CAPITAL_PROACTIVE_FETCH_BUDGET_S", raising=False)
    monkeypatch.delenv("NIJA_CAPITAL_PROACTIVE_POST_FETCH_BUDGET_S", raising=False)
    monkeypatch.delenv("NIJA_CAPITAL_PROACTIVE_EXPIRY_MARGIN_S", raising=False)
    manager = SimpleNamespace(capital_watchdog_interval_s=5.0)

    assert v166._proactive_fetch_budget_seconds() == 30.0
    assert v166._proactive_pipeline_deadline_seconds() == 50.0
    assert v166._proactive_headroom_seconds(manager) == 70.0


def test_proactive_bounds_never_extend_canonical_ttl(monkeypatch):
    monkeypatch.setattr(v166, "_freshness_ttl_seconds", lambda: 90.0)
    monkeypatch.setenv("NIJA_CAPITAL_PROACTIVE_FETCH_BUDGET_S", "500")
    monkeypatch.setenv("NIJA_CAPITAL_PROACTIVE_POST_FETCH_BUDGET_S", "500")
    monkeypatch.setenv("NIJA_CAPITAL_PROACTIVE_EXPIRY_MARGIN_S", "500")
    manager = SimpleNamespace(capital_watchdog_interval_s=100.0)

    assert v166._proactive_fetch_budget_seconds() <= 60.0
    assert v166._proactive_pipeline_deadline_seconds() <= 80.0
    assert v166._proactive_headroom_seconds(manager) <= 80.0


def test_writer_ownership_fails_closed_when_authority_unavailable(monkeypatch):
    def broken_import(_name):
        raise ImportError("missing")

    monkeypatch.setattr(v166.importlib, "import_module", broken_import)
    assert v166._writer_lease_owned() is False


def test_oldest_fallback_timestamp_is_preserved():
    observations = {
        "kraken": SimpleNamespace(observed_epoch=100.0),
        "coinbase": SimpleNamespace(observed_epoch=120.0),
    }
    guard = SimpleNamespace(_OBSERVATIONS=observations, _OBSERVATION_LOCK=None)
    status = {
        "used_fallback": True,
        "brokers": {"kraken": {}, "coinbase": {}},
    }
    assert v166._oldest_fallback_observed_epoch(status, guard) == 100.0


def test_cached_fallback_caps_snapshot_computed_at(monkeypatch):
    observed_epoch = 1_700_000_000.0
    guard = SimpleNamespace(
        _OBSERVATIONS={
            "kraken": SimpleNamespace(observed_epoch=observed_epoch),
        },
        _OBSERVATION_LOCK=None,
        current_refresh_fallback_status=lambda _ttl: {
            "used_fallback": True,
            "brokers": {"kraken": {"age_s": 10.0}},
        },
    )
    monkeypatch.setattr(v166, "_freshness_ttl_seconds", lambda: 90.0)
    snapshot = SimpleNamespace(
        computed_at=datetime.fromtimestamp(observed_epoch + 20.0, timezone.utc)
    )

    # SimpleNamespace is not a dataclass, so replacement must fail closed and
    # leave the object unchanged rather than inventing a timestamp.
    candidate, capped, epoch = v166._cap_snapshot_to_fallback_timestamp(snapshot, guard)
    assert candidate is snapshot
    assert capped is False
    assert epoch == observed_epoch


def test_proactive_trigger_matches_rollover_retry():
    assert v166._is_proactive_trigger("publication_deadline_v137") is True
    assert v166._is_proactive_trigger("publication_deadline_v137:v142_rollover_retry") is True
    assert v166._is_proactive_trigger("watchdog") is False
