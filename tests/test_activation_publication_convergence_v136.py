from __future__ import annotations

import os
import types
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import wraps

from bot import activation_publication_convergence_v136_patch as v136


@dataclass(frozen=True)
class FakeStatus:
    accepted: bool
    stale: bool
    reason: str
    timestamp: datetime | None
    expiry: datetime | None


class FakeAuthority:
    def __init__(self, status: FakeStatus) -> None:
        self._status = status

    def get_snapshot_publication_status(self) -> FakeStatus:
        return self._status


def test_publication_current_rejects_elapsed_expiry_even_before_v135_wrapper() -> None:
    now = datetime.now(timezone.utc)
    authority = FakeAuthority(
        FakeStatus(
            accepted=True,
            stale=False,
            reason="accepted",
            timestamp=now - timedelta(minutes=3),
            expiry=now - timedelta(seconds=1),
        )
    )

    current, meta = v136._publication_current(authority)

    assert current is False
    assert meta["stale"] is True
    assert meta["reason"] == "expired_after_publish"


def _install_current_meta_fakes(
    monkeypatch,
    *,
    proof: dict[str, object],
    publication: FakeStatus,
) -> None:
    fake_v134 = types.ModuleType("bot.readiness_proof_convergence_v134_patch")
    fake_v134._current_capital_proof = lambda: dict(proof)
    fake_v134._current_capital_accepted = lambda value: bool(
        value.get("hydrated")
        and not value.get("stale")
        and float(value.get("real", 0.0) or 0.0) > 0.0
        and int(value.get("registered", 0) or 0) > 0
    )

    fake_ca = types.ModuleType("bot.capital_authority")
    fake_ca.get_capital_authority = lambda: FakeAuthority(publication)

    fake_bridge = types.ModuleType("bot.activation_snapshot_bridge_patch")
    fake_bridge._mabm_brokers_ready = lambda: True

    def fake_import_first(*names: str):
        if any("readiness_proof_convergence_v134_patch" in name for name in names):
            return fake_v134
        if any(name.endswith("capital_authority") for name in names):
            return fake_ca
        if any("activation_snapshot_bridge_patch" in name for name in names):
            return fake_bridge
        raise ImportError(names)

    monkeypatch.setattr(v136, "_import_first", fake_import_first)


def test_historical_handoff_flags_cannot_turn_stale_current_proof_fresh(monkeypatch) -> None:
    now = datetime.now(timezone.utc)
    monkeypatch.setenv("NIJA_CAPITAL_READINESS_HANDOFF_V34", "1")
    monkeypatch.setenv("NIJA_CAPITAL_READINESS_HANDOFF_V34_READY", "1")
    monkeypatch.setenv("CAPITAL_SYSTEM_READY", "1")
    monkeypatch.setenv("NIJA_CAPITAL_READY", "1")
    _install_current_meta_fakes(
        monkeypatch,
        proof={
            "hydrated": True,
            "stale": True,
            "real": 468.02,
            "registered": 3,
            "source": "capital_authority",
        },
        publication=FakeStatus(
            accepted=True,
            stale=False,
            reason="accepted",
            timestamp=now - timedelta(seconds=10),
            expiry=now + timedelta(seconds=80),
        ),
    )

    accepted, meta = v136._current_capital_meta()

    assert accepted is False
    assert meta["proof_accepted"] is False
    assert meta["stale"] is True
    assert meta["accepted_latch"] is False


def test_expired_publication_blocks_even_when_v134_proof_looks_fresh(monkeypatch) -> None:
    now = datetime.now(timezone.utc)
    _install_current_meta_fakes(
        monkeypatch,
        proof={
            "hydrated": True,
            "stale": False,
            "real": 468.02,
            "registered": 3,
            "source": "capital_authority",
        },
        publication=FakeStatus(
            accepted=True,
            stale=False,
            reason="accepted",
            timestamp=now - timedelta(minutes=2),
            expiry=now - timedelta(seconds=1),
        ),
    )

    accepted, meta = v136._current_capital_meta()

    assert accepted is False
    assert meta["proof_accepted"] is True
    assert meta["publication_current"] is False
    assert meta["stale"] is True


def test_fresh_current_proof_and_publication_can_augment_cycle_snapshot(monkeypatch) -> None:
    now = datetime.now(timezone.utc)
    _install_current_meta_fakes(
        monkeypatch,
        proof={
            "hydrated": True,
            "stale": False,
            "real": 468.02,
            "registered": 3,
            "source": "capital_authority",
        },
        publication=FakeStatus(
            accepted=True,
            stale=False,
            reason="accepted",
            timestamp=now - timedelta(seconds=10),
            expiry=now + timedelta(seconds=80),
        ),
    )

    accepted, meta = v136._current_capital_meta()

    assert accepted is True
    assert meta["publication_current"] is True
    assert meta["stale"] is False
    assert meta["real_capital"] == 468.02
    assert meta["valid_brokers"] == 3
    assert meta["conditions_met"] is True


def test_v136_removes_secondary_bridge_activation_fallback(monkeypatch) -> None:
    canonical_calls: list[dict[str, object]] = []
    legacy_calls: list[str] = []
    force_calls: list[str] = []

    def canonical_commit(self, cycle_capital=None) -> bool:
        canonical_calls.append(dict(cycle_capital or {}))
        return False

    @wraps(canonical_commit)
    def legacy_bridge_commit(self, cycle_capital=None) -> bool:
        legacy_calls.append("legacy_wrapper_called")
        result = canonical_commit(self, cycle_capital=cycle_capital)
        if not result:
            force_calls.append("legacy_force_fallback")
        return result

    legacy_bridge_commit._nija_activation_snapshot_bridge_wrapped = True

    class FakeTradingStateMachine:
        commit_activation = legacy_bridge_commit

    fake_bridge = types.ModuleType("bot.activation_snapshot_bridge_patch")
    fake_bridge._sync_first_snapshot_flag = lambda self, meta: None
    fake_bridge._augment_cycle_capital = lambda cycle, meta: {
        **dict(cycle or {}),
        "snapshot_source": "capital_authority",
        "ca_not_stale": True,
    }

    monkeypatch.setattr(
        v136,
        "_current_capital_meta",
        lambda: (
            True,
            {
                "proof_accepted": True,
                "publication_current": True,
                "stale": False,
                "real_capital": 468.02,
                "valid_brokers": 3,
            },
        ),
    )
    monkeypatch.setattr(v136, "_import_first", lambda *names: fake_bridge)

    assert v136._patch_trading_state_machine_class(FakeTradingStateMachine)
    machine = FakeTradingStateMachine()
    assert machine.commit_activation({"initial": True}) is False

    assert len(canonical_calls) == 1
    assert canonical_calls[0]["snapshot_source"] == "capital_authority"
    assert canonical_calls[0]["ca_not_stale"] is True
    assert legacy_calls == []
    assert force_calls == []
    assert getattr(
        FakeTradingStateMachine.commit_activation,
        "_nija_activation_snapshot_bridge_wrapped",
        False,
    ) is True
    assert getattr(
        FakeTradingStateMachine.commit_activation,
        "_nija_activation_publication_v136",
        False,
    ) is True


def test_v136_does_not_mutate_execution_or_nonce_authority_when_blocked(monkeypatch) -> None:
    monkeypatch.setenv("NIJA_RUNTIME_EXECUTION_AUTHORITY", "0")
    monkeypatch.setenv("NIJA_NONCE_READY", "1")
    monkeypatch.setenv("NIJA_RUNTIME_NONCE_READY", "1")

    monkeypatch.setattr(
        v136,
        "_current_capital_meta",
        lambda: (
            False,
            {
                "proof_accepted": False,
                "publication_current": False,
                "stale": True,
                "source": "capital_authority",
            },
        ),
    )

    canonical_calls: list[int] = []

    class FakeTradingStateMachine:
        def commit_activation(self, cycle_capital=None) -> bool:
            canonical_calls.append(1)
            return False

    assert v136._patch_trading_state_machine_class(FakeTradingStateMachine)
    assert FakeTradingStateMachine().commit_activation({}) is False
    assert canonical_calls == [1]
    assert os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] == "0"
    assert os.environ["NIJA_NONCE_READY"] == "1"
    assert os.environ["NIJA_RUNTIME_NONCE_READY"] == "1"


def test_release_manifest_statically_wires_v136() -> None:
    from bot import runtime_release_manifest_patch as manifest

    assert manifest.RELEASE_ID == "20260817-runtime-convergence-v136"
    assert (
        "bot.activation_publication_convergence_v136_patch",
        "install_import_hook",
    ) in manifest._INSTALLERS
    assert manifest._REQUIRED_FLAGS["activation_publication_convergence_v136"] == (
        "NIJA_ACTIVATION_PUBLICATION_CONVERGENCE_V136_INSTALLED"
    )
