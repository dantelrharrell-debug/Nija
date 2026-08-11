"""Focused regression tests for the consolidated production control plane."""

from __future__ import annotations

import os
import sys
import threading
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch

from bot import readiness_table
from bot.account_registry_snapshot import build_account_registry_snapshot
from bot.broker_runtime_preflight import evaluate_broker_runtime_preflight
from bot.execution_lifecycle_canary import (
    run_builtin_execution_lifecycle_canary,
    run_simulated_trade_lifecycle,
)
from bot.live_broker_profit_exit_convergence_v25 import _kraken_user_connectivity
from bot.trading_state_machine import (
    TradingState,
    TradingStateMachine,
    _distributed_writer_authority_gate,
)


class _Broker:
    def __init__(self, *, connected: bool, auth_failed: bool = False) -> None:
        self.connected = connected
        self._auth_failed = auth_failed

    def place_market_order(self, *_args, **_kwargs):
        return {"status": "filled", "order_id": "unused"}


def _manager(**overrides):
    values = {
        "_platform_brokers": {},
        "_platform_failed_types": set(),
        "_all_user_brokers": {},
        "user_brokers": {},
        "_user_metadata": {},
        "_failed_user_connections": {},
        "_users_without_credentials": {},
        "_capital_blocked_users": {},
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_writer_dependent_readiness_is_revoked_in_one_snapshot():
    readiness_table.reset()
    for key in ("authority_ready", "nonce_ready", "execution_ready"):
        readiness_table.mark_ready(key)
    before = readiness_table.get_version()
    coordinator = Mock()

    with patch(
        "bot.startup_coordinator.get_startup_coordinator",
        return_value=coordinator,
    ):
        readiness_table.revoke_many(
            ("authority_ready", "nonce_ready", "execution_ready"),
            reason="writer_lost",
        )

    after, snapshot = readiness_table.snapshot_with_version()
    assert after == before + 1
    assert snapshot["authority_ready"] is False
    assert snapshot["nonce_ready"] is False
    assert snapshot["execution_ready"] is False
    coordinator.record_readiness.assert_called_once()
    published = coordinator.record_readiness.call_args.kwargs["table"]
    assert published["authority_ready"] is False
    assert published["nonce_ready"] is False
    assert published["execution_ready"] is False


def test_account_registry_counts_failures_and_capital_blocks_exactly():
    kraken_platform = _Broker(connected=True)
    coinbase_failed = "coinbase"
    connected_user = _Broker(connected=True)
    disconnected_user = _Broker(connected=False)
    manager = _manager(
        _platform_brokers={"kraken": kraken_platform},
        _platform_failed_types={coinbase_failed},
        _all_user_brokers={
            ("u1", "kraken"): connected_user,
            ("u2", "kraken"): disconnected_user,
        },
        _failed_user_connections={("u3", "kraken"): "auth_failed"},
        _users_without_credentials={("u4", "kraken"): True},
        _capital_blocked_users={"u1": "below_minimum"},
    )

    status = build_account_registry_snapshot(manager)
    kraken = status.venue("kraken")

    assert status.platform_registered == 2
    assert status.platform_connected == 1
    assert status.user_registered == 4
    assert status.user_connected == 1
    assert status.user_trading_eligible == 0
    assert status.all_registered_trading is False
    assert kraken.user_registered == 4
    assert _kraken_user_connectivity(manager) == {
        "registered": 4,
        "connected": 1,
        "disconnected": 3,
        "all_connected": False,
    }


def test_kraken_user_status_does_not_duplicate_platform_status():
    manager = _manager(
        _platform_brokers={"kraken": _Broker(connected=False)},
        _all_user_brokers={("u1", "kraken"): _Broker(connected=True)},
    )

    assert _kraken_user_connectivity(manager)["all_connected"] is True


def test_broker_runtime_preflight_proves_authenticated_route_and_canary():
    manager = _manager(
        _platform_brokers={"kraken": _Broker(connected=True)},
    )

    result = evaluate_broker_runtime_preflight(manager, total_balance_usd=125.0)

    assert result.passed is True
    assert result.first_blocker == "none"
    assert result.connected_venues == ("kraken",)
    assert result.checks["lifecycle.canary_passed"] is True
    assert result.minimum_notionals["kraken"] > 0


def test_broker_runtime_preflight_reports_one_stable_first_blocker():
    result = evaluate_broker_runtime_preflight(_manager(), total_balance_usd=0.0)

    assert result.passed is False
    assert result.first_blocker == "platform_registry_empty"


def test_builtin_execution_lifecycle_canary_round_trips_and_reconciles():
    result = run_builtin_execution_lifecycle_canary()

    assert result.passed is True
    assert result.entry_order_id
    assert result.exit_order_id
    assert result.filled_base_size > 0.0
    assert result.final_position_size == 0.0


def test_execution_lifecycle_canary_refuses_live_broker():
    result = run_simulated_trade_lifecycle(_Broker(connected=True))

    assert result.passed is False
    assert result.first_blocker == "live_broker_canary_forbidden"


def test_execution_lifecycle_canary_detects_reconciliation_failure():
    class _BrokenSimulatedBroker:
        is_simulated = True
        position_size = 0.0

        def place_market_order(self, _symbol, side, quantity, *, size_type):
            filled = quantity / 100.0 if size_type == "quote" else quantity
            if side == "buy":
                self.position_size += filled
            return {
                "status": "filled",
                "order_id": side,
                "filled_base_size": filled,
            }

    result = run_simulated_trade_lifecycle(_BrokenSimulatedBroker())

    assert result.passed is False
    assert result.first_blocker == "position_reconciliation_nonzero"


def test_legacy_force_flags_do_not_manufacture_live_state():
    machine = object.__new__(TradingStateMachine)
    machine.get_current_state = Mock(return_value=TradingState.OFF)

    with patch.dict(
        os.environ,
        {"FORCE_TRADE": "1", "LIVE_CAPITAL_VERIFIED": "true"},
        clear=False,
    ):
        assert machine.is_live_trading_active() is False


def test_local_writer_override_cannot_replace_distributed_fencing():
    lease_manager = SimpleNamespace(lease_version=None)
    authority_module = ModuleType("bot.execution_authority_context")
    authority_module.assert_startup_write_authority = lambda: None
    authority_module.assert_distributed_writer_authority = lambda: None
    nonce_module = ModuleType("bot.distributed_nonce_manager")
    nonce_module.get_distributed_nonce_manager = lambda: lease_manager

    with (
        patch.dict(
            os.environ,
            {
                "NIJA_FORCE_LOCAL_WRITER_LOCK_FALLBACK": "true",
                "NIJA_WRITER_FENCING_TOKEN": "",
            },
            clear=False,
        ),
        patch.dict(
            sys.modules,
            {
                "bot.execution_authority_context": authority_module,
                "bot.distributed_nonce_manager": nonce_module,
            },
        ),
    ):
        allowed, detail = _distributed_writer_authority_gate()

    assert allowed is False
    assert "fencing" in detail.lower()


def test_activate_live_trading_never_uses_force_flag_as_authority():
    machine = object.__new__(TradingStateMachine)
    machine._lock = threading.RLock()
    machine._current_state = TradingState.OFF

    with (
        patch.dict(os.environ, {"FORCE_TRADE": "1"}, clear=False),
        patch(
            "bot.trading_state_machine._live_activation_gate",
            return_value=(False, "writer_authority_missing"),
        ),
        patch.object(
            machine,
            "_force_live_active_transition",
            return_value=True,
        ) as forced_transition,
    ):
        assert machine.activate_live_trading("compatibility request") is False

    forced_transition.assert_not_called()
