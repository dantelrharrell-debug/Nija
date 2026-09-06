"""Registered-user four-way protective-exit proof v379.

Publish an observational, account-scoped proof for every registered user broker
without forcing a trade or fabricating a fill.  The proof is built from the
existing authoritative v281 coverage output after v375 has attached the
universal SL/TP/TSL/TTP contract.

A user with an open position is proof-ready only when the authoritative broker
snapshot adopted that position, cost basis is verified, auto-exit is unblocked,
and all four protective legs plus the shared protective-exit authority are
verified for that exact account/symbol.  A user with no open positions may be
reported safe/idle when its account snapshot is current, but that is explicitly
not represented as a live-position lifecycle proof.

Natural exit/fill proof remains event-driven.  This module never opens, closes,
or modifies a position merely to manufacture a test result.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
import time
from collections.abc import Mapping
from typing import Any

LOGGER = logging.getLogger("nija.runtime_registered_user_protection_proof_v379")
MARKER = "20260906-registered-user-four-way-proof-v379"
_READY_FLAG = "NIJA_RUNTIME_REGISTERED_USER_PROTECTION_PROOF_V379_READY"
_INSTALLED_FLAG = "NIJA_RUNTIME_REGISTERED_USER_PROTECTION_PROOF_V379_INSTALLED"
_LOCK = threading.RLock()
_THREAD: threading.Thread | None = None
_STOP = threading.Event()
_LAST_SIGNATURE = ""


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on", "enabled", "y"}


def _poll_s() -> float:
    try:
        return max(5.0, min(60.0, float(os.environ.get("NIJA_REGISTERED_USER_PROOF_POLL_S", "10") or 10.0)))
    except Exception:
        return 10.0


def _coverage() -> dict[str, Any]:
    v281 = importlib.import_module("bot.runtime_all_account_position_exit_coverage_v281_patch")
    audit = getattr(v281, "audit_once", None)
    if not callable(audit):
        return {"ready": False, "expected_accounts": (), "pending": {"__proof__": ("v281_audit_unavailable",)}, "positions": ()}
    result = audit()
    return dict(result or {}) if isinstance(result, Mapping) else {"ready": False, "expected_accounts": (), "pending": {"__proof__": ("v281_invalid_result",)}, "positions": ()}


def _account_rows(result: Mapping[str, Any], account: str) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in tuple(result.get("positions", ()) or ())
        if isinstance(row, Mapping) and str(row.get("account") or "") == account
    ]


def _snapshot_blockers(reasons: tuple[str, ...]) -> tuple[str, ...]:
    prefixes = (
        "broker_missing", "disconnected", "authoritative_position_fetch_unproven",
        "position_snapshot_not_adopted", "authoritative_snapshot_symbols_missing",
        "authoritative_snapshot_symbols_invalid", "tracker_list_", "tracker_position_",
        "stale_tracker_", "authoritative_snapshot_missing_tracker_position",
    )
    return tuple(reason for reason in reasons if str(reason).startswith(prefixes))


def _row_four_way(row: Mapping[str, Any]) -> bool:
    return bool(
        row.get("authoritative_snapshot_adopted") is True
        and row.get("cost_basis_verified") is True
        and not _truthy(row.get("auto_exit_blocked", False))
        and row.get("universal_four_way_policy_complete") is True
        and row.get("protective_stop_verified") is True
        and row.get("protective_take_profit_verified") is True
        and row.get("protective_trailing_stop_verified") is True
        and row.get("protective_trailing_take_profit_verified") is True
        and row.get("protective_exit_verified") is True
    )


def evaluate_once() -> dict[str, Any]:
    result = _coverage()
    expected = tuple(str(account) for account in tuple(result.get("expected_accounts", ()) or ()))
    users = tuple(account for account in expected if account.startswith("user:"))
    pending = dict(result.get("pending", {}) or {})
    accounts: dict[str, dict[str, Any]] = {}

    for account in users:
        rows = _account_rows(result, account)
        reasons = tuple(str(reason) for reason in tuple(pending.get(account, ()) or ()) if str(reason))
        snapshot_blockers = _snapshot_blockers(reasons)
        position_proofs = []
        for row in rows:
            position_proofs.append(
                {
                    "symbol": str(row.get("symbol") or ""),
                    "quantity": row.get("quantity"),
                    "entry_price": row.get("entry_price"),
                    "authoritative_snapshot_adopted": row.get("authoritative_snapshot_adopted") is True,
                    "cost_basis_verified": row.get("cost_basis_verified") is True,
                    "sl": row.get("protective_stop_verified") is True,
                    "tp": row.get("protective_take_profit_verified") is True,
                    "tsl": row.get("protective_trailing_stop_verified") is True,
                    "ttp": row.get("protective_trailing_take_profit_verified") is True,
                    "protective_exit_verified": row.get("protective_exit_verified") is True,
                    "four_way_verified": _row_four_way(row),
                }
            )

        has_open_positions = bool(position_proofs)
        all_positions_four_way = bool(has_open_positions and all(item["four_way_verified"] for item in position_proofs))
        safe_idle = bool(not has_open_positions and not snapshot_blockers)
        protection_ready = bool(all_positions_four_way or safe_idle)
        accounts[account] = {
            "protection_ready": protection_ready,
            "safe_idle_no_open_positions": safe_idle,
            "live_position_proof": all_positions_four_way,
            "natural_exit_fill_proof": False,
            "forced_test_trade": False,
            "positions": tuple(position_proofs),
            "pending": reasons,
            "snapshot_blockers": snapshot_blockers,
        }

    # No registered users is not represented as a completed user proof.
    ready = bool(users) and all(bool(row["protection_ready"]) for row in accounts.values())
    return {
        "ready": ready,
        "registered_users": users,
        "accounts": accounts,
        "natural_exit_fill_proof_event_driven": True,
        "forced_trade": False,
    }


def audit_once() -> dict[str, Any]:
    global _LAST_SIGNATURE
    try:
        result = evaluate_once()
    except Exception as exc:
        result = {
            "ready": False,
            "registered_users": (),
            "accounts": {},
            "error": f"{type(exc).__name__}:{exc}",
            "natural_exit_fill_proof_event_driven": True,
            "forced_trade": False,
        }
    ready = bool(result.get("ready"))
    os.environ[_READY_FLAG] = "1" if ready else "0"
    os.environ["NIJA_REGISTERED_USER_PROOF_ACCOUNT_COUNT"] = str(len(tuple(result.get("registered_users", ()) or ())))
    signature = repr(result)
    with _LOCK:
        changed = signature != _LAST_SIGNATURE
        if changed:
            _LAST_SIGNATURE = signature
    if changed:
        log = LOGGER.critical if ready else LOGGER.warning
        log(
            "REGISTERED_USER_PROTECTION_PROOF_V379_%s marker=%s users=%s accounts=%s "
            "sl_tp_tsl_ttp_required=true authoritative_snapshot_required=true cost_basis_required=true "
            "natural_exit_fill_proof_event_driven=true forced_test_trade=false protection_fabricated=false "
            "writer_nonce_risk_capital_killswitch_order_fill_gates_unchanged=true safety_gates_bypassed=false",
            "READY" if ready else "PENDING", MARKER, result.get("registered_users"), result.get("accounts"),
        )
    return result


def _monitor() -> None:
    while not _STOP.wait(_poll_s()):
        try:
            audit_once()
        except Exception:
            LOGGER.debug("v379 proof pulse failed", exc_info=True)


def install_import_hook() -> bool:
    global _THREAD
    os.environ.setdefault("NIJA_REGISTERED_USER_PROOF_POLL_S", "10")
    os.environ[_INSTALLED_FLAG] = "1"
    audit_once()
    with _LOCK:
        if _THREAD is None or not _THREAD.is_alive():
            _STOP.clear()
            _THREAD = threading.Thread(target=_monitor, name="RegisteredUserProtectionProofV379", daemon=True)
            _THREAD.start()
    LOGGER.critical(
        "RUNTIME_REGISTERED_USER_PROTECTION_PROOF_V379_INSTALLED marker=%s monitor_alive=%s "
        "observational_only=true forced_trade=false safety_gates_bypassed=false",
        MARKER, str(bool(_THREAD and _THREAD.is_alive())).lower(),
    )
    # Installation success is independent from current user proof readiness.
    # Per-account execution already fails closed in v376/v281 while proof is pending.
    return bool(_THREAD and _THREAD.is_alive())


def install() -> bool:
    return install_import_hook()


def stop() -> None:
    _STOP.set()


__all__ = ["MARKER", "install", "install_import_hook", "audit_once", "evaluate_once", "stop"]
