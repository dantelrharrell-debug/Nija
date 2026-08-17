from __future__ import annotations

import sys
import types

from bot import readiness_proof_convergence_v134_patch as v134


def test_current_capital_accepted_requires_all_current_facts() -> None:
    assert v134._current_capital_accepted(
        {"hydrated": True, "stale": False, "real": 100.0, "registered": 1}
    )
    assert not v134._current_capital_accepted(
        {"hydrated": True, "stale": True, "real": 100.0, "registered": 1}
    )
    assert not v134._current_capital_accepted(
        {"hydrated": True, "stale": False, "real": 0.0, "registered": 1}
    )
    assert not v134._current_capital_accepted(
        {"hydrated": True, "stale": False, "real": 100.0, "registered": 0}
    )


def test_capital_authority_no_arg_staleness_uses_canonical_90s_ttl(monkeypatch) -> None:
    calls: list[float] = []

    class FakeCapitalAuthority:
        def is_stale(self, ttl_s: float = 60.0) -> bool:
            calls.append(float(ttl_s))
            return ttl_s < 80.0

    fake = types.ModuleType("bot.capital_authority")
    fake.CapitalAuthority = FakeCapitalAuthority
    fake._DEFAULT_FRESHNESS_TTL_S = 90.0
    monkeypatch.setitem(sys.modules, "bot.capital_authority", fake)

    assert v134._patch_capital_authority_staleness_default()
    authority = FakeCapitalAuthority()

    # No-argument consumers now agree with CapitalAuthority.is_fresh() and
    # snapshot publication, both of which use the canonical 90-second TTL.
    assert authority.is_stale() is False
    assert calls[-1] == 90.0

    # Explicit thresholds remain exact and are not silently broadened.
    assert authority.is_stale(ttl_s=12.0) is True
    assert calls[-1] == 12.0


def _install_fake_current_proof_modules(monkeypatch, proof: dict[str, object]) -> types.ModuleType:
    v16 = types.ModuleType("preactivation_readiness_convergence_v16_patch")
    v16._capital_snapshot = lambda: dict(proof)
    monkeypatch.setitem(sys.modules, "preactivation_readiness_convergence_v16_patch", v16)

    monitor = types.ModuleType("bot.activation_pending_commit_monitor_patch")
    monitor._capital_ready_snapshot = lambda: (
        True,
        {
            "reason": "legacy_sticky_acceptance",
            "accepted_latch": True,
            "stale": True,
        },
    )
    monkeypatch.setitem(sys.modules, "bot.activation_pending_commit_monitor_patch", monitor)
    return monitor


def test_activation_monitor_rejects_stale_current_proof_even_if_legacy_latch_was_true(monkeypatch) -> None:
    monitor = _install_fake_current_proof_modules(
        monkeypatch,
        {
            "hydrated": True,
            "stale": True,
            "real": 468.25,
            "registered": 3,
            "source": "capital_authority",
        },
    )

    assert v134._patch_activation_monitor()
    accepted, meta = monitor._capital_ready_snapshot()

    assert accepted is False
    assert meta["stale"] is True
    assert meta["accepted_latch"] is False
    assert meta["reason"] == "current_snapshot_not_accepted"
    assert meta["current_proof"] is True


def test_activation_monitor_accepts_fresh_funded_registered_current_proof(monkeypatch) -> None:
    monitor = _install_fake_current_proof_modules(
        monkeypatch,
        {
            "hydrated": True,
            "stale": False,
            "real": 468.25,
            "registered": 3,
            "source": "capital_authority",
        },
    )

    assert v134._patch_activation_monitor()
    accepted, meta = monitor._capital_ready_snapshot()

    assert accepted is True
    assert meta["hydrated"] is True
    assert meta["stale"] is False
    assert meta["real_capital"] == 468.25
    assert meta["registered_brokers"] == 3
    assert meta["accepted_latch"] is True
    assert meta["current_proof"] is True


def test_activation_monitor_fails_closed_when_current_proof_reader_errors(monkeypatch) -> None:
    v16 = types.ModuleType("preactivation_readiness_convergence_v16_patch")

    def broken_snapshot():
        raise RuntimeError("boom")

    v16._capital_snapshot = broken_snapshot
    monkeypatch.setitem(sys.modules, "preactivation_readiness_convergence_v16_patch", v16)

    monitor = types.ModuleType("bot.activation_pending_commit_monitor_patch")
    monitor._capital_ready_snapshot = lambda: (True, {"accepted_latch": True})
    monkeypatch.setitem(sys.modules, "bot.activation_pending_commit_monitor_patch", monitor)

    assert v134._patch_activation_monitor()
    accepted, meta = monitor._capital_ready_snapshot()

    assert accepted is False
    assert meta["hydrated"] is False
    assert meta["stale"] is True
    assert meta["registered_brokers"] == 0
    assert meta["accepted_latch"] is False
    assert meta["reason"].startswith("current_proof_error:RuntimeError:boom")
