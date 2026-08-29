"""All-account authoritative position/protective-exit coverage truth v281.

Platform activation and user-account isolation are intentionally separate NIJA
contracts. v99 keeps a failed user account from unnecessarily revoking safe
platform execution, but operators still need one fail-closed answer to the
stronger question: has every enabled/registered platform and user account been
authoritatively enumerated, and is every currently held position represented in
the local protective-exit tracker with verified cost basis?

v281 is that certification layer. It is observational only:

* the full canonical registry remains the denominator, including disconnected,
  failed, and missing-credential accounts;
* disabled user broker entries are excluded when metadata explicitly says they
  are disabled;
* each connected account must carry current v98/v279 startup-position fetch and
  adoption proof;
* authoritative snapshot symbols must exactly match positive-quantity tracker
  holdings;
* every held tracker row must have verified cost basis, positive entry price,
  and must not be auto-exit blocked;
* the structural v265 protective-exit stack must be ready.

The audit performs no broker I/O, reconnect, position fetch, price lookup, order,
or tracker mutation. In particular, a local tracker symbol that disappeared
from a newer authoritative broker snapshot is reported as a stale mismatch; it
is never deleted or zeroed by this layer without a canonical reconciliation
primitive.

v281 does not change v95/v96/v99/v146 platform activation semantics and never
fabricates connectivity, positions, cost basis, exit protection, nonce,
execution authority, acknowledgements, fills, capital, or kill-switch state.
"""
from __future__ import annotations

import logging
import os
import sys
import threading
from collections.abc import Mapping
from typing import Any

LOGGER = logging.getLogger("nija.runtime_all_account_position_exit_coverage_v281")
MARKER = "20260829-all-account-position-exit-coverage-v281"
_READY_FLAG = "NIJA_ALL_ACCOUNT_POSITION_EXIT_COVERAGE_READY"
_INSTALLED_FLAG = "NIJA_ALL_ACCOUNT_POSITION_EXIT_COVERAGE_V281_INSTALLED"
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}
_LOCK = threading.RLock()
_LAST_SIGNATURE = ""


def _label(value: Any) -> str:
    raw = getattr(value, "value", value)
    text = str(raw or "").strip().lower()
    if "." in text:
        text = text.rsplit(".", 1)[-1]
    return text


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in _TRUE


def _connected(broker: Any) -> bool:
    if broker is None:
        return False
    try:
        value = getattr(broker, "connected", False)
        return bool(value() if callable(value) else value)
    except Exception:
        return False


def _float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
        return default if number != number else number
    except Exception:
        return default


def _normalise_symbol(value: Any) -> str:
    return str(value or "").strip().upper().replace("/", "-").replace("_", "-")


def _iter_items(value: Any) -> tuple[tuple[Any, Any], ...]:
    try:
        return tuple(value.items())
    except Exception:
        return ()


def _explicitly_disabled(value: Any) -> bool:
    """Return true only for an explicit disabled signal; absence means enabled."""
    if isinstance(value, bool):
        return not value
    if isinstance(value, Mapping):
        for key in ("enabled", "is_enabled", "trading_enabled"):
            if key in value:
                return not _truthy(value.get(key))
        return False
    for key in ("enabled", "is_enabled", "trading_enabled"):
        if hasattr(value, key):
            try:
                return not _truthy(getattr(value, key))
            except Exception:
                return True
    return False


def _canonical_manager() -> Any:
    """Resolve the already-loaded canonical manager without importing broker code."""
    for module_name in ("bot.multi_account_broker_manager", "multi_account_broker_manager"):
        module = sys.modules.get(module_name)
        if module is None:
            continue
        getter = getattr(module, "get_broker_manager", None)
        if callable(getter):
            try:
                manager = getter()
            except Exception:
                manager = None
            if manager is not None:
                return manager
        manager = getattr(module, "multi_account_broker_manager", None)
        if manager is not None:
            return manager
    return None


def _user_key(user_id: Any, broker_type: Any) -> str:
    venue = _label(broker_type)
    user = str(user_id or "").strip()
    return f"user:{user}:{venue}" if user and venue else ""


def _platform_key(broker_type: Any) -> str:
    venue = _label(broker_type)
    return f"platform:{venue}" if venue else ""


def _expected_accounts(manager: Any) -> dict[str, Any]:
    """Build the complete enabled registry denominator without broker I/O."""
    if manager is None:
        return {}

    expected: dict[str, Any] = {}
    disabled: set[str] = set()

    # Metadata is populated from enabled user configuration before connection.
    # Honor an explicit disabled value defensively so a disabled venue cannot
    # become a false coverage blocker if it remains in compatibility metadata.
    for user_id, metadata in _iter_items(getattr(manager, "_user_metadata", {})):
        broker_map = metadata.get("brokers", {}) if isinstance(metadata, Mapping) else {}
        for broker_type, config in _iter_items(broker_map):
            key = _user_key(user_id, broker_type)
            if not key:
                continue
            if _explicitly_disabled(config):
                disabled.add(key)
                expected.pop(key, None)
            else:
                expected.setdefault(key, None)

    for broker_type, broker in _iter_items(getattr(manager, "_platform_brokers", {})):
        key = _platform_key(broker_type)
        if key:
            expected[key] = broker
    for broker_type in tuple(getattr(manager, "_platform_failed_types", set()) or ()):
        key = _platform_key(broker_type)
        if key:
            expected.setdefault(key, None)

    for registry_name in ("_all_user_brokers",):
        for raw_key, broker in _iter_items(getattr(manager, registry_name, {})):
            if not isinstance(raw_key, tuple) or len(raw_key) != 2:
                continue
            key = _user_key(raw_key[0], raw_key[1])
            if key and key not in disabled:
                expected[key] = broker

    for user_id, broker_map in _iter_items(getattr(manager, "user_brokers", {})):
        for broker_type, broker in _iter_items(broker_map):
            key = _user_key(user_id, broker_type)
            if key and key not in disabled:
                expected[key] = broker

    for registry_name in ("_failed_user_connections", "_users_without_credentials"):
        registry = getattr(manager, registry_name, {}) or {}
        try:
            keys = tuple(registry)
        except Exception:
            keys = ()
        for raw_key in keys:
            if not isinstance(raw_key, tuple) or len(raw_key) != 2:
                continue
            key = _user_key(raw_key[0], raw_key[1])
            if key and key not in disabled:
                expected.setdefault(key, None)

    for key in disabled:
        expected.pop(key, None)
    return dict(sorted(expected.items()))


def _position_quantity(row: Mapping[str, Any]) -> float:
    for key in ("quantity", "qty", "amount", "size", "units", "balance"):
        if row.get(key) is not None:
            return _float(row.get(key))
    return 0.0


def _entry_price(row: Mapping[str, Any]) -> float:
    for key in (
        "entry_price", "avg_entry_price", "average_price", "cost_basis_price",
        "average_filled_price", "avg_fill_price", "avg_price", "purchase_price",
    ):
        value = _float(row.get(key))
        if value > 0:
            return value
    quantity = abs(_position_quantity(row))
    total_cost = _float(row.get("cost_basis_usd", row.get("total_cost", row.get("size_usd"))))
    return total_cost / quantity if quantity > 0 and total_cost > 0 else 0.0


def _tracker_holdings(broker: Any) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """Read local tracker state only. No broker/private/public API is called."""
    tracker = getattr(broker, "position_tracker", None)
    if tracker is None:
        return {}, []
    list_positions = getattr(tracker, "get_all_positions", None)
    get_position = getattr(tracker, "get_position", None)
    if not callable(list_positions) or not callable(get_position):
        return {}, ["tracker_audit_api_unavailable"]
    try:
        raw_symbols = list_positions() or []
    except Exception as exc:
        return {}, [f"tracker_list_error:{type(exc).__name__}"]
    if isinstance(raw_symbols, Mapping):
        raw_symbols = tuple(raw_symbols.keys())
    elif not isinstance(raw_symbols, (list, tuple, set)):
        try:
            raw_symbols = tuple(raw_symbols)
        except Exception:
            return {}, ["tracker_list_invalid"]

    held: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    for raw_symbol in raw_symbols:
        symbol = _normalise_symbol(raw_symbol)
        if not symbol:
            continue
        try:
            row = get_position(raw_symbol)
        except Exception as exc:
            errors.append(f"tracker_position_error:{symbol}:{type(exc).__name__}")
            continue
        if not isinstance(row, Mapping):
            errors.append(f"tracker_position_missing:{symbol}")
            continue
        quantity = _position_quantity(row)
        if abs(quantity) <= 0.0:
            continue
        held[symbol] = {
            "symbol": symbol,
            "quantity": quantity,
            "entry_price": _entry_price(row),
            "cost_basis_verified": row.get("cost_basis_verified") is True,
            "auto_exit_blocked": _truthy(row.get("auto_exit_blocked", False)),
        }
    return held, errors


def _account_audit(account: str, broker: Any, structural_exit_ready: bool) -> tuple[list[str], list[dict[str, Any]]]:
    reasons: list[str] = []
    positions: list[dict[str, Any]] = []
    if broker is None:
        return ["broker_missing"], positions
    if not _connected(broker):
        return ["disconnected"], positions

    fetch_ok = getattr(broker, "_startup_position_sync_fetch_ok", None)
    if fetch_ok is not True:
        exact = str(getattr(broker, "_startup_position_sync_error", "") or "").strip()
        return [exact or "authoritative_position_fetch_unproven"], positions
    if getattr(broker, "_startup_position_sync_adopted", None) is not True:
        exact = str(getattr(broker, "_startup_position_sync_error", "") or "").strip()
        return [exact or "position_snapshot_not_adopted"], positions
    if not hasattr(broker, "_startup_position_sync_symbols"):
        return ["authoritative_snapshot_symbols_missing"], positions

    raw_snapshot = getattr(broker, "_startup_position_sync_symbols", ())
    try:
        snapshot_symbols = {
            symbol for symbol in (_normalise_symbol(value) for value in tuple(raw_snapshot or ())) if symbol
        }
    except Exception:
        return ["authoritative_snapshot_symbols_invalid"], positions

    held, tracker_errors = _tracker_holdings(broker)
    reasons.extend(tracker_errors)
    held_symbols = set(held)
    stale_local = sorted(held_symbols - snapshot_symbols)
    missing_tracker = sorted(snapshot_symbols - held_symbols)
    if stale_local:
        reasons.append("stale_tracker_not_in_authoritative_snapshot:" + ",".join(stale_local))
    if missing_tracker:
        reasons.append("authoritative_snapshot_missing_tracker_position:" + ",".join(missing_tracker))

    venue = account.rsplit(":", 1)[-1] if ":" in account else "unknown"
    for symbol in sorted(held):
        row = held[symbol]
        verified = bool(row["cost_basis_verified"])
        entry = float(row["entry_price"])
        blocked = bool(row["auto_exit_blocked"])
        in_snapshot = symbol in snapshot_symbols
        if not verified:
            reasons.append(f"cost_basis_unverified:{symbol}")
        if entry <= 0.0:
            reasons.append(f"entry_price_unverified:{symbol}")
        if blocked:
            reasons.append(f"auto_exit_blocked:{symbol}")
        protection_verified = bool(
            structural_exit_ready and in_snapshot and verified and entry > 0.0 and not blocked
        )
        positions.append({
            "account": account,
            "broker": venue,
            "symbol": symbol,
            "quantity": row["quantity"],
            "entry_price": entry,
            "cost_basis_verified": verified,
            "auto_exit_blocked": blocked,
            "authoritative_snapshot_adopted": in_snapshot,
            "protective_exit_verified": protection_verified,
        })
    return reasons, positions


def evaluate(manager: Any, *, structural_exit_ready: Any = None) -> dict[str, Any]:
    """Return deterministic all-account coverage truth without mutating runtime gates."""
    expected = _expected_accounts(manager)
    if structural_exit_ready is None:
        structural_exit_ready = _truthy(os.environ.get("NIJA_PROTECTIVE_EXIT_AUTHORITY_V265_READY", "0"))
    structural = bool(structural_exit_ready)

    pending: dict[str, tuple[str, ...]] = {}
    positions: list[dict[str, Any]] = []
    if not expected:
        pending["__registry__"] = ("registry_empty",)
    if not structural:
        pending["__protective_exit__"] = ("protective_exit_authority_v265_unready",)

    for account, broker in expected.items():
        reasons, account_positions = _account_audit(account, broker, structural)
        positions.extend(account_positions)
        if reasons:
            # Stable de-duplication preserves exact failure provenance without log noise.
            pending[account] = tuple(dict.fromkeys(reasons))

    return {
        "ready": bool(expected) and structural and not pending,
        "expected_accounts": tuple(expected),
        "pending": pending,
        "positions": tuple(positions),
        "structural_exit_ready": structural,
    }


def _state_signature(result: Mapping[str, Any]) -> str:
    pending = result.get("pending", {}) if isinstance(result, Mapping) else {}
    positions = result.get("positions", ()) if isinstance(result, Mapping) else ()
    position_sig = tuple(
        sorted(
            (
                str(row.get("account")), str(row.get("symbol")), str(row.get("quantity")),
                str(row.get("entry_price")), str(row.get("protective_exit_verified")),
            )
            for row in positions if isinstance(row, Mapping)
        )
    )
    return repr((
        bool(result.get("ready")),
        tuple(result.get("expected_accounts", ())),
        tuple(sorted((str(key), tuple(value)) for key, value in pending.items())),
        position_sig,
        bool(result.get("structural_exit_ready")),
    ))


def audit_once(manager: Any = None, *, structural_exit_ready: Any = None) -> dict[str, Any]:
    global _LAST_SIGNATURE
    observed_manager = manager if manager is not None else _canonical_manager()
    result = evaluate(observed_manager, structural_exit_ready=structural_exit_ready)
    ready = bool(result["ready"])
    os.environ[_READY_FLAG] = "1" if ready else "0"
    os.environ["NIJA_ALL_ACCOUNT_POSITION_EXIT_COVERAGE_EXPECTED"] = str(len(result["expected_accounts"]))
    os.environ["NIJA_ALL_ACCOUNT_POSITION_EXIT_COVERAGE_PENDING"] = str(len(result["pending"]))

    signature = _state_signature(result)
    with _LOCK:
        changed = signature != _LAST_SIGNATURE
        if changed:
            _LAST_SIGNATURE = signature
    if changed:
        log = LOGGER.critical if ready else LOGGER.warning
        log(
            "ALL_ACCOUNT_POSITION_EXIT_COVERAGE_V281_%s marker=%s expected=%s pending=%s positions=%s "
            "protective_exit_authority_v265=%s broker_io=false tracker_mutation=false "
            "platform_activation_unchanged=true user_execution_isolation_preserved=true "
            "position_success_fabricated=false cost_basis_fabricated=false exit_protection_fabricated=false "
            "writer_nonce_capital_risk_killswitch_order_fill_gates_unchanged=true safety_gates_bypassed=false",
            "READY" if ready else "PENDING",
            MARKER,
            result["expected_accounts"],
            result["pending"],
            result["positions"],
            str(result["structural_exit_ready"]).lower(),
        )
    return result


def install() -> bool:
    """Install/reassert the audit capability; runtime coverage may remain pending."""
    os.environ[_INSTALLED_FLAG] = "1"
    try:
        audit_once()
    except Exception as exc:
        os.environ[_READY_FLAG] = "0"
        LOGGER.error(
            "ALL_ACCOUNT_POSITION_EXIT_COVERAGE_V281_AUDIT_ERROR marker=%s error=%s:%s "
            "certification_fail_closed=true platform_activation_unchanged=true safety_gates_bypassed=false",
            MARKER, type(exc).__name__, exc,
        )
    return True


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER", "install", "install_import_hook", "audit_once", "evaluate",
    "_expected_accounts", "_account_audit", "_tracker_holdings", "_canonical_manager",
]
