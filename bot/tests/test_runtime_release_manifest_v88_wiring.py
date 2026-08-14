from __future__ import annotations

import threading
import types

from bot import production_runtime_convergence_v88_patch as v88
from bot import runtime_release_manifest_patch as manifest


def test_release_manifest_installs_and_requires_v88() -> None:
    assert (
        "bot.production_runtime_convergence_v88_patch",
        "install_import_hook",
    ) in manifest._INSTALLERS
    assert (
        manifest._REQUIRED_FLAGS["production_runtime_convergence_v88"]
        == "NIJA_PRODUCTION_RUNTIME_CONVERGENCE_V88_INSTALLED"
    )


def test_v88_recovers_only_generic_execute_false_under_strict_live_proof(monkeypatch) -> None:
    monkeypatch.setenv("NIJA_RUNTIME_TRADING_STATE", "LIVE_ACTIVE")
    monkeypatch.setenv("LIVE_CAPITAL_VERIFIED", "true")
    monkeypatch.setenv("DRY_RUN_MODE", "false")
    monkeypatch.setenv("PAPER_MODE", "false")

    tsm = types.SimpleNamespace(
        __name__="bot.trading_state_machine",
        _EXECUTION_CIRCUIT_BREAKER_LOCK=threading.Lock(),
        _EXECUTION_CIRCUIT_BREAKER_COUNTS={"execute_action_returned_false": 5},
        _EXECUTION_CIRCUIT_BREAKER_TRIPPED=True,
        _EXECUTION_CIRCUIT_BREAKER_REASON="execute_action_returned_false",
        _kill_switch_is_active=lambda: (False, "clear"),
        _runtime_writer_nonce_ready=lambda: (True, "strict_writer_nonce_ready"),
        _execution_circuit_breaker_status=lambda: (
            False,
            "EXECUTION_CIRCUIT_BREAKER rejected_orders threshold=5 detail=execute_action_returned_false",
        ),
    )

    assert v88._patch_trading_state_machine(tsm) is True
    ok, reason = tsm._execution_circuit_breaker_status()

    assert ok is True
    assert reason == "generic_execute_false_not_exchange_rejection"
    assert tsm._EXECUTION_CIRCUIT_BREAKER_COUNTS == {}
    assert tsm._EXECUTION_CIRCUIT_BREAKER_TRIPPED is False
    assert tsm._EXECUTION_CIRCUIT_BREAKER_REASON == ""
