"""Post-connection broker execution preflight.

This check runs after authenticated broker connection and balance hydration but
before activation.  It does not submit an order.  Instead it proves that the
live registry contains an authenticated platform path, observed capital, a
terminal order method, and a known venue minimum notional.  The result carries
one stable first-blocker code for operators and automated readiness consumers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Tuple

from bot.account_registry_snapshot import (
    AccountRegistrySnapshot,
    build_account_registry_snapshot,
)
from bot.execution_contract_primitives import minimum_notional
from bot.execution_lifecycle_canary import run_builtin_execution_lifecycle_canary


@dataclass(frozen=True)
class BrokerRuntimePreflight:
    """Immutable broker execution-path preflight result."""

    passed: bool
    first_blocker: str
    checks: Dict[str, bool]
    connected_venues: Tuple[str, ...]
    minimum_notionals: Dict[str, float]
    accounts: AccountRegistrySnapshot


def _venue_name(value: Any) -> str:
    return str(getattr(value, "value", value) or "").strip().lower()


def evaluate_broker_runtime_preflight(
    manager: Any,
    *,
    total_balance_usd: float,
) -> BrokerRuntimePreflight:
    """Evaluate the authenticated broker execution path without placing orders."""

    accounts = build_account_registry_snapshot(manager)
    connected: Dict[str, Any] = {}
    for broker_type, broker in getattr(manager, "_platform_brokers", {}).items():
        venue = _venue_name(broker_type)
        if venue and bool(getattr(broker, "connected", False)):
            connected[venue] = broker

    route_ready = bool(connected) and all(
        callable(getattr(broker, "place_market_order", None))
        or callable(getattr(broker, "execute_order", None))
        for broker in connected.values()
    )
    authenticated = bool(connected) and all(
        not bool(getattr(broker, "_auth_failed", False))
        and not bool(getattr(broker, "_nija_credentials_quarantined", False))
        and not bool(getattr(broker, "exit_only_mode", False))
        for broker in connected.values()
    )
    notionals = {venue: float(minimum_notional(venue)) for venue in connected}
    notional_ready = bool(notionals) and all(value > 0.0 for value in notionals.values())
    lifecycle_canary = run_builtin_execution_lifecycle_canary()
    registry_consistent = bool(
        accounts.platform_connected <= accounts.platform_registered
        and accounts.user_connected <= accounts.user_registered
        and accounts.user_trading_eligible <= accounts.user_registered
    )
    checks = {
        "platform.registered": accounts.platform_registered > 0,
        "platform.connected": bool(connected),
        "private_api.authenticated": authenticated,
        "capital.balance_observed": float(total_balance_usd or 0.0) > 0.0,
        "order.route_callable": route_ready,
        "minimum_notional.known": notional_ready,
        "lifecycle.canary_passed": lifecycle_canary.passed,
        "account_registry.consistent": registry_consistent,
    }
    blocker_codes = {
        "platform.registered": "platform_registry_empty",
        "platform.connected": "no_platform_connected",
        "private_api.authenticated": "private_api_not_authenticated",
        "capital.balance_observed": "balance_not_hydrated",
        "order.route_callable": "terminal_order_route_missing",
        "minimum_notional.known": "minimum_notional_unknown",
        "lifecycle.canary_passed": lifecycle_canary.first_blocker,
        "account_registry.consistent": "account_registry_inconsistent",
    }
    first_failed = next((name for name, ready in checks.items() if not ready), "")
    return BrokerRuntimePreflight(
        passed=not first_failed,
        first_blocker=blocker_codes.get(first_failed, "none"),
        checks=checks,
        connected_venues=tuple(sorted(connected)),
        minimum_notionals=notionals,
        accounts=accounts,
    )


__all__ = ["BrokerRuntimePreflight", "evaluate_broker_runtime_preflight"]
