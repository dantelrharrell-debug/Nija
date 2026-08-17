from __future__ import annotations

import os
import types
from dataclasses import dataclass

from bot import final_execution_state_router_convergence_patch as v138


def test_execute_action_patch_is_idempotently_converged() -> None:
    def execute_action(self, *args, **kwargs):
        return True

    execute_action._nija_terminal_reason_v1 = True

    class FakeExecutionOwner:
        pass

    FakeExecutionOwner.execute_action = execute_action

    assert v138._patch_execute_action_class(FakeExecutionOwner) is True
    assert getattr(FakeExecutionOwner.execute_action, "_nija_terminal_reason_v1", False) is True


def test_startup_patch_targets_canonical_coordinator_class_and_is_idempotent(monkeypatch) -> None:
    fake_module = types.ModuleType("bot.startup_coordinator")

    class FakeStartupCoordinator:
        def build_snapshot(self, *, trading_state: str, activation_intent: bool):
            return {
                "trading_state": trading_state,
                "activation_intent": activation_intent,
            }

    fake_module.StartupCoordinator = FakeStartupCoordinator

    def fake_import(name: str):
        if name in {"bot.startup_coordinator", "startup_coordinator"}:
            return fake_module
        raise ImportError(name)

    monkeypatch.setattr(v138.importlib, "import_module", fake_import)
    monkeypatch.setattr(v138, "_runtime_live", lambda: False)

    assert v138._patch_startup_state() is True
    assert getattr(FakeStartupCoordinator.build_snapshot, "_nija_live_monotonic_v1", False) is True
    assert v138._patch_startup_state() is True

    result = FakeStartupCoordinator().build_snapshot(
        trading_state="LIVE_PENDING_CONFIRMATION",
        activation_intent=True,
    )
    assert result["trading_state"] == "LIVE_PENDING_CONFIRMATION"
    assert result["activation_intent"] is True


@dataclass(frozen=True)
class FakeSnapshot:
    trading_state: str
    runtime_authority_state: str
    nonce_ready: bool
    dispatch_health_ready: bool


def test_live_monotonic_repair_only_changes_public_trading_state(monkeypatch) -> None:
    monkeypatch.setattr(v138, "_runtime_live", lambda: True)
    monkeypatch.setenv("NIJA_NONCE_READY", "0")
    monkeypatch.setenv("NIJA_RUNTIME_EXECUTION_AUTHORITY", "1")

    original = FakeSnapshot(
        trading_state="LIVE_PENDING_CONFIRMATION",
        runtime_authority_state="EXECUTING",
        nonce_ready=False,
        dispatch_health_ready=False,
    )

    repaired = v138._repair_startup_result(original, "build_snapshot")

    assert repaired.trading_state == "LIVE_ACTIVE"
    assert repaired.runtime_authority_state == "EXECUTING"
    assert repaired.nonce_ready is False
    assert repaired.dispatch_health_ready is False
    assert os.environ["NIJA_NONCE_READY"] == "0"
    assert os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] == "1"


def test_non_live_runtime_never_promotes_pending_state(monkeypatch) -> None:
    monkeypatch.setattr(v138, "_runtime_live", lambda: False)
    original = {
        "trading_state": "LIVE_PENDING_CONFIRMATION",
        "nonce_ready": False,
        "dispatch_health_ready": False,
    }

    repaired = v138._repair_startup_result(original, "build_snapshot")

    assert repaired is original
    assert repaired["trading_state"] == "LIVE_PENDING_CONFIRMATION"
    assert repaired["nonce_ready"] is False
    assert repaired["dispatch_health_ready"] is False


def test_converge_once_reports_current_convergence_and_publishes_ready(monkeypatch) -> None:
    monkeypatch.setattr(v138, "_patch_execution_modules", lambda: True)
    monkeypatch.setattr(v138, "_patch_startup_state", lambda: True)
    monkeypatch.setattr(v138, "_patch_okx_router_identity", lambda: True)
    monkeypatch.delenv("NIJA_FINAL_EXECUTION_STATE_ROUTER_READY", raising=False)

    ready, state = v138._converge_once()

    assert ready is True
    assert state == {"execution": True, "startup": True, "okx": True}
    assert os.environ["NIJA_FINAL_EXECUTION_STATE_ROUTER_READY"] == "1"


def test_converge_once_stays_pending_when_any_component_is_not_converged(monkeypatch) -> None:
    monkeypatch.setattr(v138, "_patch_execution_modules", lambda: True)
    monkeypatch.setattr(v138, "_patch_startup_state", lambda: False)
    monkeypatch.setattr(v138, "_patch_okx_router_identity", lambda: True)

    ready, state = v138._converge_once()

    assert ready is False
    assert state["startup"] is False
    assert os.environ["NIJA_FINAL_EXECUTION_STATE_ROUTER_READY"] == "PENDING"


def test_release_manifest_statically_wires_v138() -> None:
    from bot import runtime_release_manifest_patch as manifest

    assert manifest.RELEASE_ID == "20260817-runtime-convergence-v138"
    assert (
        "bot.final_execution_state_router_convergence_patch",
        "install_import_hook",
    ) in manifest._INSTALLERS
    assert manifest._REQUIRED_FLAGS["final_execution_state_router_v138"] == (
        "NIJA_FINAL_EXECUTION_STATE_ROUTER_READY"
    )
