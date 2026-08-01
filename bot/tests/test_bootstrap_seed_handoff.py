from __future__ import annotations

import threading
import types

from bot import multi_account_broker_manager as mabm


class FakeCapitalBootstrapFSM:
    def __init__(self) -> None:
        self.state = mabm.CapitalBootstrapState.BOOT_IDLE
        self.transitions = []
        self.claimed = False

    @property
    def is_ready(self) -> bool:
        return self.state in {
            mabm.CapitalBootstrapState.READY,
            mabm.CapitalBootstrapState.RUNNING,
        }

    def claim_bootstrap_ownership(self) -> None:
        self.claimed = True

    def transition(self, target, reason) -> bool:
        self.transitions.append((self.state, target, reason))
        self.state = target
        return True


def test_seed_handoff_walks_capital_fsm_to_ready(monkeypatch) -> None:
    monkeypatch.setattr(mabm, "_CAPITAL_FSM_AVAILABLE", True)
    manager = object.__new__(mabm.MultiAccountBrokerManager)
    manager._capital_bootstrap_fsm = FakeCapitalBootstrapFSM()

    assert manager._advance_seed_capital_bootstrap_ready() is True
    assert manager._capital_bootstrap_fsm.claimed is True
    assert manager._capital_bootstrap_fsm.state == mabm.CapitalBootstrapState.READY
    assert [target for _source, target, _reason in manager._capital_bootstrap_fsm.transitions] == [
        mabm.CapitalBootstrapState.WAIT_PLATFORM,
        mabm.CapitalBootstrapState.INIT_COMPLETE,
        mabm.CapitalBootstrapState.REFRESH_REQUESTED,
        mabm.CapitalBootstrapState.REFRESH_IN_FLIGHT,
        mabm.CapitalBootstrapState.SNAPSHOT_EVALUATING,
        mabm.CapitalBootstrapState.READY,
    ]


def test_startup_lock_release_is_transactional(monkeypatch) -> None:
    startup_lock = threading.Event()
    monkeypatch.setattr(mabm, "STARTUP_LOCK", startup_lock)
    manager = object.__new__(mabm.MultiAccountBrokerManager)
    manager._startup_lock_released = False
    manager._broker_registration_complete = threading.Event()
    manager._broker_registration_complete.set()
    manager._platform_brokers = {}
    manager._get_system_bootstrap_state_name = lambda: "STARTUP_VALIDATED"
    manager._is_system_bootstrap_at_least = lambda _state: True

    failing_authority = types.SimpleNamespace(
        finalize_bootstrap_ready=lambda: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    monkeypatch.setattr(
        mabm.importlib,
        "import_module",
        lambda _name: types.SimpleNamespace(
            get_capital_authority=lambda: failing_authority
        ),
    )

    assert manager.finalize_bootstrap_ready() is False
    assert manager._startup_lock_released is False
    assert startup_lock.is_set() is False

    healthy_authority = types.SimpleNamespace(
        finalize_bootstrap_ready=startup_lock.set
    )
    monkeypatch.setattr(
        mabm.importlib,
        "import_module",
        lambda _name: types.SimpleNamespace(
            get_capital_authority=lambda: healthy_authority
        ),
    )

    assert manager.finalize_bootstrap_ready() is True
    assert manager._startup_lock_released is True
    assert startup_lock.is_set() is True
