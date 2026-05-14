"""Regression checks for capital flow FSM coercion and terminal-transition guards."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from capital_flow_state_machine import (
    CapitalBootstrapState,
    CapitalEventBus,
    CapitalRefreshCoordinator,
    CapitalRuntimeStateMachine,
    get_capital_bootstrap_fsm,
)


class _StubAuthority:
    """CapitalAuthority stub with configurable previous per-broker value."""

    def __init__(self, previous: float = 0.0) -> None:
        self._previous = previous
        self.reserve_pct = 0.10
        self.expected_brokers = 1
        self.opportunistic = False
        self.last_updated = datetime.now(timezone.utc)
        self.published = []

    def get_raw_per_broker(self, _broker_key: str) -> float:
        return self._previous

    def publish_snapshot(self, snapshot, writer_id: str) -> bool:
        self.published.append((snapshot, writer_id))
        return True


class _ZeroBalanceBroker:
    """Broker stub that returns an explicit zero balance."""

    def get_account_balance(self):
        return 0.0


class _FailingBroker:
    """Broker stub that always raises during balance fetch."""

    def get_account_balance(self):
        raise RuntimeError("balance fetch failed")


class _PositiveBroker:
    """Broker stub that returns a fixed positive balance."""

    def __init__(self, balance: float) -> None:
        self._balance = balance

    def get_account_balance(self):
        return self._balance


def _build_coordinator() -> tuple[CapitalRefreshCoordinator, CapitalRuntimeStateMachine]:
    bootstrap = get_capital_bootstrap_fsm()
    bootstrap.claim_bootstrap_ownership()
    bootstrap.force_transition(CapitalBootstrapState.BOOT_IDLE, "test reset")
    runtime = CapitalRuntimeStateMachine()
    coordinator = CapitalRefreshCoordinator(
        event_bus=CapitalEventBus(),
        bootstrap_fsm=bootstrap,
        runtime_fsm=runtime,
    )
    return coordinator, runtime


def check_zero_or_failed_fetch_never_reuses_stale_positive_balance() -> None:
    coordinator, _runtime = _build_coordinator()
    authority = _StubAuthority(previous=250.0)

    with patch("capital_authority.get_capital_authority", return_value=authority):
        zero_snapshot = coordinator.execute_refresh(
            broker_map={"kraken": _ZeroBalanceBroker()},
            trigger="test_zero",
            open_exposure_usd=0.0,
        )
        failed_snapshot = coordinator.execute_refresh(
            broker_map={"kraken": _FailingBroker()},
            trigger="test_fail",
            open_exposure_usd=0.0,
        )

    assert zero_snapshot is not None
    assert failed_snapshot is not None
    assert zero_snapshot.real_capital == 0.0
    assert failed_snapshot.real_capital == 0.0
    assert zero_snapshot.broker_balances == {}
    assert failed_snapshot.broker_balances == {}


def check_runtime_refresh_does_not_mutate_terminal_bootstrap_state() -> None:
    coordinator, _runtime = _build_coordinator()
    bootstrap = get_capital_bootstrap_fsm()
    bootstrap.force_transition(CapitalBootstrapState.RUNNING, "test terminal")
    authority = _StubAuthority(previous=0.0)

    with patch("capital_authority.get_capital_authority", return_value=authority):
        snapshot = coordinator.execute_refresh(
            broker_map={"kraken": _PositiveBroker(50.0)},
            trigger="test_terminal_skip",
            open_exposure_usd=0.0,
        )

    assert snapshot is not None
    assert bootstrap.state == CapitalBootstrapState.RUNNING


if __name__ == "__main__":
    check_zero_or_failed_fetch_never_reuses_stale_positive_balance()
    check_runtime_refresh_does_not_mutate_terminal_bootstrap_state()
    print("✅ test_capital_flow_state_machine_guards passed")
