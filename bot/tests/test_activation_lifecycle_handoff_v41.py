from __future__ import annotations

import builtins
import importlib
import os
from types import ModuleType, SimpleNamespace

import pytest


MODULE = "bot.activation_lifecycle_handoff_v41_patch"


def _load():
    return importlib.import_module(MODULE)


class _Coordinator:
    def __init__(self, threads=0, confirmed=True):
        self.snapshot = SimpleNamespace(
            threads_launched=threads,
            threads_confirmed_running=confirmed,
        )
        self.supervised_calls = []

    def build_snapshot(self, **_kwargs):
        return self.snapshot

    def record_threads_supervised(self, count, *, bootstrap_state):
        self.supervised_calls.append((count, bootstrap_state))
        self.snapshot = SimpleNamespace(
            threads_launched=count,
            threads_confirmed_running=True,
        )


def _base_kwargs(**updates):
    data = {
        "bootstrap_state": "RUNNING_SUPERVISED",
        "capital_state": "BOOT_IDLE",
        "capital_hydrated": True,
        "capital_balance": 468.26,
        "capital_stale": False,
        "readiness_key": "strategy_ready",
        "readiness_value": True,
        "readiness_version": 7,
        "readiness_table": {"strategy_ready": True},
        "authority_ready": True,
        "authority_status": {"ok": True},
        "nonce_ready": True,
        "nonce_detail": "ok",
        "dispatch_health_ready": False,
        "dispatch_health_detail": "existing_value_must_be_preserved",
        "global_gate_ready": True,
        "global_gate_detail": "ready",
        "activation_requested": True,
        "activation_source": "test",
        "kill_switch_active": False,
        "trading_state": "OFF",
        "activation_intent": True,
    }
    data.update(updates)
    return data


def test_verified_capital_promotes_boot_idle_without_touching_dispatch(monkeypatch):
    mod = _load()
    coordinator = _Coordinator(threads=2, confirmed=True)
    monkeypatch.setattr(
        mod,
        "_verified_capital_evidence",
        lambda: (
            True,
            "canonical_capital_verified",
            {
                "hydrated": True,
                "real": 468.26,
                "usable": 458.89,
                "broker_count": 2,
                "fresh": True,
            },
        ),
    )

    normalized, audit = mod._normalize_transaction_kwargs(
        coordinator,
        _base_kwargs(dispatch_health_ready=False),
    )

    assert normalized["capital_state"] == "RUNNING"
    assert normalized["capital_hydrated"] is True
    assert normalized["capital_balance"] == pytest.approx(468.26)
    assert normalized["capital_stale"] is False
    assert normalized["dispatch_health_ready"] is False
    assert audit["capital_promoted"] is True


def test_unverified_capital_remains_boot_idle(monkeypatch):
    mod = _load()
    coordinator = _Coordinator(threads=2, confirmed=True)
    monkeypatch.setattr(
        mod,
        "_verified_capital_evidence",
        lambda: (
            False,
            "capital_not_verified",
            {
                "hydrated": True,
                "real": 0.0,
                "usable": 0.0,
                "broker_count": 0,
                "fresh": False,
            },
        ),
    )

    normalized, audit = mod._normalize_transaction_kwargs(coordinator, _base_kwargs())

    assert normalized["capital_state"] == "BOOT_IDLE"
    assert audit["capital_promoted"] is False


def test_missing_thread_count_repaired_only_from_verified_core(monkeypatch):
    mod = _load()
    coordinator = _Coordinator(threads=0, confirmed=True)
    monkeypatch.setattr(
        mod,
        "_verified_capital_evidence",
        lambda: (False, "not_needed_for_thread_test", {}),
    )
    monkeypatch.setattr(
        mod,
        "_verified_supervised_thread_count",
        lambda: (1, "core_loop_supervised"),
    )

    _normalized, audit = mod._normalize_transaction_kwargs(
        coordinator,
        _base_kwargs(capital_state="RUNNING"),
    )

    assert coordinator.supervised_calls == [(1, "RUNNING_SUPERVISED")]
    assert audit["threads_repaired"] is True
    assert audit["thread_count"] == 1


def test_missing_thread_count_stays_blocked_without_live_core(monkeypatch):
    mod = _load()
    coordinator = _Coordinator(threads=0, confirmed=True)
    monkeypatch.setattr(
        mod,
        "_verified_capital_evidence",
        lambda: (False, "not_needed_for_thread_test", {}),
    )
    monkeypatch.setattr(
        mod,
        "_verified_supervised_thread_count",
        lambda: (0, "core_loop_thread_not_alive"),
    )

    _normalized, audit = mod._normalize_transaction_kwargs(
        coordinator,
        _base_kwargs(capital_state="RUNNING"),
    )

    assert coordinator.supervised_calls == []
    assert audit["threads_repaired"] is False
    assert audit["thread_reason"] == "core_loop_thread_not_alive"


def test_existing_positive_thread_proof_is_not_republished(monkeypatch):
    mod = _load()
    coordinator = _Coordinator(threads=3, confirmed=True)
    called = {"threads": 0}

    monkeypatch.setattr(
        mod,
        "_verified_capital_evidence",
        lambda: (False, "not_needed", {}),
    )

    def _thread_probe():
        called["threads"] += 1
        return 1, "core_loop_supervised"

    monkeypatch.setattr(mod, "_verified_supervised_thread_count", _thread_probe)
    mod._normalize_transaction_kwargs(
        coordinator,
        _base_kwargs(capital_state="RUNNING"),
    )

    assert called["threads"] == 0
    assert coordinator.supervised_calls == []


def test_simulation_mode_never_verifies_live_capital(monkeypatch):
    mod = _load()
    monkeypatch.setenv("DRY_RUN_MODE", "true")
    monkeypatch.setenv("LIVE_CAPITAL_VERIFIED", "true")

    ok, reason, _detail = mod._verified_capital_evidence()

    assert ok is False
    assert reason == "simulation_mode"


def test_live_capital_flag_required(monkeypatch):
    mod = _load()
    monkeypatch.delenv("DRY_RUN_MODE", raising=False)
    monkeypatch.delenv("PAPER_MODE", raising=False)
    monkeypatch.delenv("LIVE_CAPITAL_VERIFIED", raising=False)

    ok, reason, _detail = mod._verified_capital_evidence()

    assert ok is False
    assert reason == "live_capital_not_verified"


def test_core_thread_proof_requires_writer_renewal_and_heartbeat(monkeypatch):
    mod = _load()

    class _Alive:
        def is_alive(self):
            return True

    runtime = SimpleNamespace(
        acquired=True,
        lost=False,
        _heartbeat_thread=_Alive(),
        _nija_lease_renewal_health=lambda: (True, "renewal_healthy", 1.0, 15.0),
    )
    monkeypatch.setattr(mod, "_writer_runtime", lambda: runtime)
    monkeypatch.setattr(mod, "_core_thread", lambda: _Alive())

    count, reason = mod._verified_supervised_thread_count()

    assert count == 1
    assert reason == "core_loop_supervised"


def test_core_thread_proof_fails_when_renewal_unhealthy(monkeypatch):
    mod = _load()

    class _Alive:
        def is_alive(self):
            return True

    runtime = SimpleNamespace(
        acquired=True,
        lost=False,
        _heartbeat_thread=_Alive(),
        _nija_lease_renewal_health=lambda: (
            False,
            "renewal_success_stale",
            30.0,
            15.0,
        ),
    )
    monkeypatch.setattr(mod, "_writer_runtime", lambda: runtime)
    monkeypatch.setattr(mod, "_core_thread", lambda: _Alive())

    count, reason = mod._verified_supervised_thread_count()

    assert count == 0
    assert "renewal_success_stale" in reason


def test_startup_coordinator_aliases_share_canonical_getter(monkeypatch):
    mod = _load()
    canonical_key = mod._CANONICAL_KEY
    old = getattr(builtins, canonical_key, None)
    had_old = hasattr(builtins, canonical_key)

    canonical = ModuleType("bot.startup_coordinator")
    singleton = object()
    canonical.get_startup_coordinator = lambda: singleton
    duplicate = ModuleType("startup_coordinator")
    duplicate.get_startup_coordinator = lambda: object()

    try:
        if hasattr(builtins, canonical_key):
            delattr(builtins, canonical_key)
        mod._canonicalize_startup_coordinator(canonical)
        rebound = mod._canonicalize_startup_coordinator(duplicate)

        assert rebound is canonical
        assert duplicate.get_startup_coordinator() is singleton
        assert mod.sys.modules["bot.startup_coordinator"] is canonical
        assert mod.sys.modules["startup_coordinator"] is canonical
    finally:
        if had_old:
            setattr(builtins, canonical_key, old)
        elif hasattr(builtins, canonical_key):
            delattr(builtins, canonical_key)
