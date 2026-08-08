from __future__ import annotations

import os
import sys
from types import ModuleType

import pytest

from bot import writer_generation_state_gate_v50_patch as v50


_ENV_KEYS = (
    "NIJA_ENFORCE_WRITER_LEASE_GENERATION",
    "NIJA_WRITER_LEASE_GENERATION",
    "NIJA_WRITER_GENERATION",
    "NIJA_WRITER_LEASE_GENERATION_LAST",
    "NIJA_WRITER_LEASE_GENERATION_EXPECTED",
)


@pytest.fixture(autouse=True)
def _clean_generation_env(monkeypatch: pytest.MonkeyPatch):
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("NIJA_ENFORCE_WRITER_LEASE_GENERATION", "true")
    yield


def _fake_v45(
    monkeypatch: pytest.MonkeyPatch,
    *,
    generation: int = 3345,
    token: str = "process-token",
    proof_error: str = "",
) -> ModuleType:
    module = ModuleType("bot.writer_generation_handoff_v45_patch")

    def prove_process_writer():
        if proof_error:
            return None, proof_error
        return {
            "generation": generation,
            "token": token,
            "lock_key": "nija:writer_lock:test",
            "lock_value": f"{token}:owner",
            "pttl_ms": 59000,
            "generation_key": "nija:lease:generation",
        }, ""

    def repair_process_generation(source: str):
        if proof_error:
            return False, 0, proof_error
        value = str(generation)
        os.environ["NIJA_WRITER_LEASE_GENERATION"] = value
        os.environ["NIJA_WRITER_GENERATION"] = value
        os.environ["NIJA_WRITER_LEASE_GENERATION_LAST"] = value
        return True, generation, f"proof_verified:{source}"

    module._prove_process_writer = prove_process_writer
    module.repair_process_generation = repair_process_generation
    monkeypatch.setitem(sys.modules, "bot.writer_generation_handoff_v45_patch", module)
    return module


def test_gate_uses_canonical_process_writer_not_nonce_generation(monkeypatch: pytest.MonkeyPatch):
    _fake_v45(monkeypatch, generation=3345)
    # Production showed a legacy nonce-derived value of 18 against a process
    # writer high-water in the 3300s. v50 must never consume that nonce value.
    monkeypatch.setenv("NIJA_WRITER_LEASE_GENERATION_LAST", "3344")
    monkeypatch.setenv("NIJA_PLATFORM_NONCE_LEASE_GENERATION", "18")

    ok, detail = v50.canonical_writer_generation_gate()

    assert ok is True
    assert "generation=3345" in detail
    assert os.environ["NIJA_WRITER_LEASE_GENERATION"] == "3345"
    assert os.environ["NIJA_WRITER_GENERATION"] == "3345"
    assert os.environ["NIJA_WRITER_LEASE_GENERATION_LAST"] == "3345"
    assert os.environ["NIJA_PLATFORM_NONCE_LEASE_GENERATION"] == "18"


def test_exact_canonical_proof_may_replace_contaminated_local_telemetry(monkeypatch: pytest.MonkeyPatch):
    _fake_v45(monkeypatch, generation=401)
    monkeypatch.setenv("NIJA_WRITER_LEASE_GENERATION", "18")
    monkeypatch.setenv("NIJA_WRITER_GENERATION", "18")
    monkeypatch.setenv("NIJA_WRITER_LEASE_GENERATION_LAST", "3344")
    monkeypatch.setenv("NIJA_WRITER_LEASE_GENERATION_EXPECTED", "3344")

    ok, _detail = v50.canonical_writer_generation_gate()

    assert ok is True
    assert os.environ["NIJA_WRITER_LEASE_GENERATION"] == "401"
    assert os.environ["NIJA_WRITER_GENERATION"] == "401"
    assert os.environ["NIJA_WRITER_LEASE_GENERATION_LAST"] == "401"
    assert os.environ["NIJA_WRITER_LEASE_GENERATION_EXPECTED"] == "401"


def test_missing_process_writer_proof_stays_fail_closed(monkeypatch: pytest.MonkeyPatch):
    _fake_v45(monkeypatch, proof_error="runtime_not_acquired")
    monkeypatch.setenv("NIJA_WRITER_LEASE_GENERATION", "18")
    monkeypatch.setenv("NIJA_WRITER_LEASE_GENERATION_LAST", "3344")

    ok, detail = v50.canonical_writer_generation_gate()

    assert ok is False
    assert detail == "process_writer_generation:runtime_not_acquired"
    assert os.environ["NIJA_WRITER_LEASE_GENERATION"] == "18"
    assert os.environ["NIJA_WRITER_LEASE_GENERATION_LAST"] == "3344"


def test_trading_state_gate_is_replaced_without_calling_legacy_nonce_gate(monkeypatch: pytest.MonkeyPatch):
    _fake_v45(monkeypatch, generation=3350)
    tsm = ModuleType("bot.trading_state_machine")
    calls = {"legacy": 0}

    def legacy_gate():
        calls["legacy"] += 1
        return False, "lease_generation_regression prev=3344 current=18"

    tsm._writer_lease_generation_gate = legacy_gate
    assert v50._patch_trading_state_module(tsm) is True

    ok, detail = tsm._writer_lease_generation_gate()

    assert ok is True
    assert "generation=3350" in detail
    assert calls["legacy"] == 0


def test_dispatch_latch_cannot_rewrap_v50_gate(monkeypatch: pytest.MonkeyPatch):
    _fake_v45(monkeypatch, generation=3351)
    tsm = ModuleType("bot.trading_state_machine")
    tsm._writer_lease_generation_gate = lambda: (False, "legacy")
    assert v50._patch_trading_state_module(tsm) is True

    dispatch = ModuleType("bot.trading_state_dispatch_latch_repair_patch")
    calls = {"legacy_installer": 0}

    def legacy_installer(target):
        calls["legacy_installer"] += 1
        original = target._writer_lease_generation_gate

        def bad_nonce_regression_repair():
            os.environ["NIJA_WRITER_LEASE_GENERATION"] = "18"
            return original()

        target._writer_lease_generation_gate = bad_nonce_regression_repair
        return True

    dispatch._install_lease_generation_patch_on_module = legacy_installer
    dispatch._LEASE_GENERATION_PATCHED = False
    assert v50._patch_dispatch_module(dispatch) is True
    assert dispatch._install_lease_generation_patch_on_module(tsm) is True

    assert calls["legacy_installer"] == 0
    assert getattr(tsm._writer_lease_generation_gate, v50._GATE_PATCH, False) is True
    ok, _detail = tsm._writer_lease_generation_gate()
    assert ok is True
    assert os.environ["NIJA_WRITER_LEASE_GENERATION"] == "3351"


def test_generation_enforcement_can_only_be_disabled_by_existing_policy(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("NIJA_ENFORCE_WRITER_LEASE_GENERATION", "false")
    ok, detail = v50.canonical_writer_generation_gate()
    assert ok is True
    assert detail == ""
