from __future__ import annotations

import threading
from types import SimpleNamespace

from bot import runtime_kraken_capital_observation_admission_v174_patch as patch


def _guard_with_observation(*, value: float, observed_mono: float, sequence: int = 7):
    observation = SimpleNamespace(
        value=value,
        observed_monotonic=observed_mono,
        observed_epoch=1_787_278_000.0,
        sequence=sequence,
    )
    return SimpleNamespace(
        _OBSERVATIONS={"kraken": observation},
        _OBSERVATION_LOCK=threading.Lock(),
        _freshness_ttl_seconds=lambda: 90.0,
    )


def test_fresh_positive_kraken_observation_is_fastpath_eligible(monkeypatch) -> None:
    guard = _guard_with_observation(value=245.93, observed_mono=990.0)
    monkeypatch.setattr(patch, "_max_admission_age_seconds", lambda guard=None: 30.0)

    observation, age_s = patch._read_fresh_observation(
        guard,
        "kraken",
        now_mono=1000.0,
    )

    assert observation is guard._OBSERVATIONS["kraken"]
    assert age_s == 10.0


def test_stale_or_nonpositive_observation_is_not_fastpathed(monkeypatch) -> None:
    monkeypatch.setattr(patch, "_max_admission_age_seconds", lambda guard=None: 30.0)

    stale = _guard_with_observation(value=245.93, observed_mono=900.0)
    observation, age_s = patch._read_fresh_observation(stale, "kraken", now_mono=1000.0)
    assert observation is None
    assert age_s == 100.0

    zero = _guard_with_observation(value=0.0, observed_mono=999.0)
    observation, _ = patch._read_fresh_observation(zero, "kraken", now_mono=1000.0)
    assert observation is None


def test_fastpath_uses_existing_v37_failure_handler_and_skips_wait(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []

    class FakeBatch:
        def __init__(self):
            self._nija_v37_resolved = {}

        def _handle_failure(self, broker_id: str, reason: str) -> float:
            calls.append((broker_id, reason))
            self._nija_v37_resolved[broker_id] = 245.93
            return 245.93

        def result_for(self, broker_id: str, broker):
            raise AssertionError("synchronous wait path must be bypassed")

    guard = _guard_with_observation(value=245.93, observed_mono=999.0)
    guard._BalanceFetchBatch = FakeBatch
    monkeypatch.setattr(patch, "_guard", lambda: guard)
    monkeypatch.setattr(patch, "_is_proactive_trigger", lambda: True)
    monkeypatch.setattr(patch, "_max_admission_age_seconds", lambda guard=None: 30.0)
    monkeypatch.setattr(patch.time, "monotonic", lambda: 1000.0)

    assert patch._patch_batch_result() is True
    batch = FakeBatch()
    assert batch.result_for("kraken", object()) == 245.93
    assert calls == [("kraken", "v174_proactive_fresh_observation")]


def test_nonproactive_refresh_keeps_original_wait_path(monkeypatch) -> None:
    class FakeBatch:
        def _handle_failure(self, broker_id: str, reason: str) -> float:
            return 245.93

        def result_for(self, broker_id: str, broker):
            return "original"

    guard = _guard_with_observation(value=245.93, observed_mono=999.0)
    guard._BalanceFetchBatch = FakeBatch
    monkeypatch.setattr(patch, "_guard", lambda: guard)
    monkeypatch.setattr(patch, "_is_proactive_trigger", lambda: False)

    assert patch._patch_batch_result() is True
    assert FakeBatch().result_for("kraken", object()) == "original"


def test_fastpath_age_is_never_longer_than_proactive_budget_or_ttl(monkeypatch) -> None:
    guard = SimpleNamespace(_freshness_ttl_seconds=lambda: 90.0)
    fake_v166 = SimpleNamespace(_proactive_fetch_budget_seconds=lambda: 30.0)
    monkeypatch.setattr(patch, "_v166", lambda: fake_v166)
    monkeypatch.setenv("NIJA_KRAKEN_CAPITAL_OBSERVATION_FASTPATH_MAX_AGE_S", "300")
    assert patch._max_admission_age_seconds(guard) == 30.0


def test_patch_exposes_no_freshness_or_execution_bypass_api() -> None:
    assert not hasattr(patch, "extend_freshness")
    assert not hasattr(patch, "accept_partial_snapshot")
    assert not hasattr(patch, "force_activation")
    assert not hasattr(patch, "grant_execution_authority")
