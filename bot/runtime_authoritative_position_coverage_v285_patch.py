"""Authoritative all-account position visibility and protective-exit convergence v285.

Production evidence on 2026-08-29 exposed three remaining truth/liveness gaps:

* v95/v96 could report a broker position-sync ready from the adoption latch even
  when the independent v98 authoritative fetch proof was absent;
* v281 had no explicit current-snapshot age/quantity proof, so an old symbol set
  could outlive the broker snapshot that created it;
* connected user accounts blocked by v282 for missing position proof had no
  dedicated bounded authoritative refresh path to recover that proof.

v285 closes those gaps without weakening any existing execution safety gate.
Every successful broker ``get_positions`` list is fingerprinted as the current
process-local authoritative snapshot (rows, quantity, timestamp and generation).
Readiness requires current fetch proof + adoption + a non-stale v285 snapshot.
Platform retries remain owned by v108/v182. User retries call the existing
startup-position adopter through its bounded v95/v279 path and are serialized
and backoff-limited. Disconnected users remain owned by v86 authenticated
reconnect supervision.

No position, cost basis, connectivity, capital, nonce, writer, execution,
acknowledgement, fill, or protective-exit truth is fabricated. Failed reads,
invalid payloads, stale snapshots, reconciliation discrepancies, and missing
accounts remain fail closed. Existing platform/user execution isolation is
preserved; this module publishes a stronger all-account coverage certificate.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
import time
from collections.abc import Mapping
from functools import wraps
from typing import Any

LOGGER = logging.getLogger("nija.runtime_authoritative_position_coverage_v285")
MARKER = "20260829-authoritative-position-coverage-v285"
RELEASE_ID = "20260829-runtime-convergence-v285"
_READY_FLAG = "NIJA_RUNTIME_AUTHORITATIVE_POSITION_COVERAGE_V285_READY"
_COVERAGE_FLAG = "NIJA_AUTHORITATIVE_POSITION_COVERAGE_CURRENT_READY"
_INSTALLED_FLAG = "NIJA_RUNTIME_AUTHORITATIVE_POSITION_COVERAGE_V285_INSTALLED"
_PATCH_ATTR = "_nija_authoritative_position_coverage_v285"
_LOCK = threading.RLock()
_USER_REFRESH_LOCK = threading.Lock()
_MONITOR_STARTED = False
_MONITOR_STOP = threading.Event()
_USER_NEXT_REFRESH: dict[str, float] = {}
_LAST_SIGNATURE = ""


def _label(value: Any) -> str:
    raw = getattr(value, "value", value)
    text = str(raw or "").strip().lower()
    if "." in text:
        text = text.rsplit(".", 1)[-1]
    return text


def _float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
        return default if number != number else number
    except Exception:
        return default


def _normalise_symbol(value: Any) -> str:
    return str(value or "").strip().upper().replace("/", "-").replace("_", "-")


def _connected(broker: Any) -> bool:
    if broker is None:
        return False
    try:
        value = getattr(broker, "connected", False)
        return bool(value() if callable(value) else value)
    except Exception:
        return False


def _snapshot_max_age_s() -> float:
    try:
        value = float(os.environ.get("NIJA_AUTHORITATIVE_POSITION_SNAPSHOT_MAX_AGE_S", "90") or 90.0)
    except (TypeError, ValueError):
        value = 90.0
    return max(15.0, min(600.0, value))


def _monitor_interval_s() -> float:
    try:
        value = float(os.environ.get("NIJA_AUTHORITATIVE_POSITION_COVERAGE_POLL_S", "5") or 5.0)
    except (TypeError, ValueError):
        value = 5.0
    return max(2.0, min(60.0, value))


def _retry_s() -> float:
    try:
        value = float(os.environ.get("NIJA_AUTHORITATIVE_USER_POSITION_RETRY_S", "15") or 15.0)
    except (TypeError, ValueError):
        value = 15.0
    return max(5.0, min(120.0, value))


def _refresh_interval_s() -> float:
    return max(10.0, _snapshot_max_age_s() * 0.55)


def _quantity(row: Mapping[str, Any]) -> float:
    for key in ("quantity", "qty", "amount", "size", "units", "balance"):
        if row.get(key) is not None:
            return _float(row.get(key))
    return 0.0


def _entry_price(row: Mapping[str, Any]) -> float:
    for key in (
        "entry_price", "average_entry_price", "avg_entry_price", "avg_price",
        "average_price", "cost_basis_price", "average_filled_price",
        "avg_fill_price", "purchase_price",
    ):
        value = _float(row.get(key))
        if value > 0:
            return value
    quantity = abs(_quantity(row))
    for key in ("cost_basis", "cost_basis_usd", "total_cost", "executed_cost", "size_usd"):
        total = _float(row.get(key))
        if total > 0 and quantity > 0:
            return total / quantity
    return 0.0


def _cost_basis(row: Mapping[str, Any], quantity: float, entry_price: float) -> float:
    for key in ("cost_basis", "cost_basis_usd", "total_cost", "executed_cost"):
        total = _float(row.get(key))
        if total > 0:
            return total
    return abs(quantity) * entry_price if abs(quantity) > 0 and entry_price > 0 else 0.0


def _snapshot_rows(raw_positions: list[Any]) -> tuple[tuple[dict[str, Any], ...], str]:
    rows: list[dict[str, Any]] = []
    for raw in raw_positions:
        if not isinstance(raw, Mapping):
            return (), f"invalid_position_payload:{type(raw).__name__}"
        symbol = _normalise_symbol(raw.get("symbol"))
        quantity = _quantity(raw)
        if not symbol or quantity <= 0:
            return (), f"invalid_position_row:symbol={symbol or 'missing'}:quantity={quantity}"
        entry = _entry_price(raw)
        rows.append({
            "symbol": symbol,
            "quantity": quantity,
            "entry_price": entry,
            "cost_basis": _cost_basis(raw, quantity, entry),
        })
    rows.sort(key=lambda row: str(row.get("symbol", "")))
    return tuple(rows), ""


def _record_snapshot_success(broker: Any, raw_positions: list[Any]) -> bool:
    rows, error = _snapshot_rows(raw_positions)
    if error:
        _record_snapshot_failure(broker, error)
        return False
    try:
        generation = int(getattr(broker, "_nija_authoritative_position_snapshot_generation_v285", 0) or 0) + 1
    except Exception:
        generation = 1
    try:
        setattr(broker, "_nija_authoritative_position_snapshot_rows_v285", rows)
        setattr(broker, "_nija_authoritative_position_snapshot_at_monotonic_v285", time.monotonic())
        setattr(broker, "_nija_authoritative_position_snapshot_at_wall_v285", time.time())
        setattr(broker, "_nija_authoritative_position_snapshot_generation_v285", generation)
        setattr(broker, "_nija_authoritative_position_snapshot_fetch_ok_v285", True)
        setattr(broker, "_nija_authoritative_position_snapshot_error_v285", "")
    except Exception:
        return False
    return True


def _record_snapshot_failure(broker: Any, reason: str) -> None:
    try:
        setattr(broker, "_nija_authoritative_position_snapshot_fetch_ok_v285", False)
        setattr(broker, "_nija_authoritative_position_snapshot_error_v285", str(reason or "position_snapshot_failed"))
    except Exception:
        pass


def _snapshot_status(broker: Any) -> tuple[bool, str, tuple[dict[str, Any], ...], float, int]:
    if broker is None:
        return False, "broker_missing", (), float("inf"), 0
    if not _connected(broker):
        return False, "disconnected", (), float("inf"), 0
    if getattr(broker, "_nija_authoritative_position_snapshot_fetch_ok_v285", None) is not True:
        exact = str(getattr(broker, "_nija_authoritative_position_snapshot_error_v285", "") or "").strip()
        return False, exact or "authoritative_position_snapshot_unproven", (), float("inf"), 0
    if not hasattr(broker, "_nija_authoritative_position_snapshot_rows_v285"):
        return False, "authoritative_position_snapshot_rows_missing", (), float("inf"), 0
    at = _float(getattr(broker, "_nija_authoritative_position_snapshot_at_monotonic_v285", 0.0))
    if at <= 0:
        return False, "authoritative_position_snapshot_timestamp_missing", (), float("inf"), 0
    age = max(0.0, time.monotonic() - at)
    try:
        generation = int(getattr(broker, "_nija_authoritative_position_snapshot_generation_v285", 0) or 0)
    except Exception:
        generation = 0
    if age > _snapshot_max_age_s():
        return False, f"stale_position_snapshot:age_s={age:.1f}:max_age_s={_snapshot_max_age_s():.1f}", (), age, generation
    raw_rows = getattr(broker, "_nija_authoritative_position_snapshot_rows_v285", ())
    try:
        rows = tuple(dict(row) for row in tuple(raw_rows or ()) if isinstance(row, Mapping))
    except Exception:
        return False, "authoritative_position_snapshot_rows_invalid", (), age, generation
    return True, "authoritative_position_snapshot_current", rows, age, generation


def _chain_has_exact(callable_obj: Any, expected_name: str | None = None) -> bool:
    seen: set[int] = set()
    current = callable_obj
    for _ in range(48):
        if not callable(current) or id(current) in seen:
            return False
        seen.add(id(current))
        owner = getattr(current, "__globals__", {}) or {}
        if bool(getattr(current, _PATCH_ATTR, False)) and owner.get("MARKER") == MARKER:
            if expected_name is None or str(getattr(current, "__name__", "")) == expected_name:
                return True
        current = getattr(current, "__wrapped__", None)
    return False


def _patch_broker_get_positions() -> bool:
    try:
        module = importlib.import_module("bot.broker_manager")
    except Exception:
        return True
    patched_any = False
    found_any = False
    for class_name in ("CoinbaseBroker", "KrakenBroker", "OKXBroker", "AlpacaBroker"):
        cls = getattr(module, class_name, None)
        if not isinstance(cls, type):
            continue
        current = getattr(cls, "get_positions", None)
        if not callable(current):
            continue
        found_any = True
        if _chain_has_exact(current, "get_positions_v285"):
            patched_any = True
            continue
        original = current

        @wraps(original)
        def get_positions_v285(self: Any, *args: Any, __original=original, **kwargs: Any):
            try:
                result = __original(self, *args, **kwargs)
            except BaseException as exc:
                _record_snapshot_failure(self, f"{type(exc).__name__}:{exc}")
                raise
            if isinstance(result, list):
                _record_snapshot_success(self, list(result))
            else:
                _record_snapshot_failure(self, f"invalid_snapshot_payload:{type(result).__name__}")
            return result

        get_positions_v285.__name__ = "get_positions_v285"
        setattr(get_positions_v285, _PATCH_ATTR, True)
        setattr(get_positions_v285, "__wrapped__", original)
        cls.get_positions = get_positions_v285
        patched_any = True
    return patched_any or not found_any


def _strong_broker_proof(broker: Any) -> tuple[bool, str]:
    if broker is None:
        return False, "broker_missing"
    if not _connected(broker):
        return False, "disconnected"
    if getattr(broker, "_startup_position_sync_fetch_ok", None) is not True:
        exact = str(getattr(broker, "_startup_position_sync_error", "") or "").strip()
        return False, exact or "authoritative_position_fetch_unproven"
    if getattr(broker, "_startup_position_sync_adopted", None) is not True:
        exact = str(getattr(broker, "_startup_position_sync_error", "") or "").strip()
        return False, exact or "position_snapshot_not_adopted"
    if not hasattr(broker, "_startup_position_sync_symbols"):
        return False, "authoritative_snapshot_symbols_missing"
    snapshot_ok, reason, _rows, _age, _generation = _snapshot_status(broker)
    if not snapshot_ok:
        return False, reason
    return True, "authoritative_current_position_snapshot_adopted"


def _patch_v95_status() -> bool:
    try:
        v95 = importlib.import_module("bot.position_sync_core_handoff_v95_patch")
    except Exception:
        return True
    current = getattr(v95, "position_sync_status", None)
    connected = getattr(v95, "_connected_brokers", None)
    if not callable(current) or not callable(connected):
        return False
    if _chain_has_exact(current, "position_sync_status_v285"):
        return True

    @wraps(current)
    def position_sync_status_v285(manager: Any) -> tuple[bool, list[str], dict[str, bool]]:
        brokers = connected(manager)
        status: dict[str, bool] = {}
        for name, broker in brokers.items():
            ready, reason = _strong_broker_proof(broker)
            status[str(name)] = bool(ready)
            try:
                setattr(broker, "_nija_position_sync_status_reason_v285", reason)
            except Exception:
                pass
        pending = sorted(name for name, ready in status.items() if not ready)
        return bool(status) and not pending, pending, status

    position_sync_status_v285.__name__ = "position_sync_status_v285"
    setattr(position_sync_status_v285, _PATCH_ATTR, True)
    setattr(position_sync_status_v285, "__wrapped__", current)
    v95.position_sync_status = position_sync_status_v285
    return True


def _platform_candidates(manager: Any) -> list[tuple[str, Any]]:
    found: list[tuple[str, Any]] = []
    try:
        platform = getattr(manager, "platform_brokers", {}) or {}
        if callable(platform):
            platform = platform()
        for broker_type, broker in dict(platform or {}).items():
            if broker is None or not _connected(broker):
                continue
            ready, _reason = _strong_broker_proof(broker)
            if not ready:
                found.append((_label(broker_type) or "unknown", broker))
    except Exception:
        pass
    return found


def _patch_v182_discovery() -> bool:
    try:
        v182 = importlib.import_module("bot.runtime_position_fetch_proof_v182_patch")
    except Exception:
        return True
    current = getattr(v182, "_connected_platform_brokers_requiring_proof", None)
    if not callable(current):
        return False
    if _chain_has_exact(current, "discovery_v285"):
        return True

    @wraps(current)
    def discovery_v285(manager: Any) -> list[tuple[str, Any]]:
        return _platform_candidates(manager)

    discovery_v285.__name__ = "discovery_v285"
    setattr(discovery_v285, _PATCH_ATTR, True)
    setattr(discovery_v285, "__wrapped__", current)
    v182._connected_platform_brokers_requiring_proof = discovery_v285
    try:
        patch = getattr(v182, "_patch_discovery", None)
        if callable(patch):
            active_v108 = importlib.import_module("bot.platform_position_sync_v108_patch")
            existing = getattr(active_v108, "_connected_unsynced_platform_brokers", None)
            if not (callable(existing) and bool(getattr(existing, "_nija_runtime_position_fetch_proof_v182", False))):
                patch()
    except Exception:
        pass
    return True


def _quantity_matches(left: float, right: float) -> bool:
    tolerance = max(1e-10, abs(right) * 1e-6)
    return abs(left - right) <= tolerance


def _patch_v281_account_audit() -> bool:
    try:
        v281 = importlib.import_module("bot.runtime_all_account_position_exit_coverage_v281_patch")
    except Exception:
        return True
    current = getattr(v281, "_account_audit", None)
    tracker_reader = getattr(v281, "_tracker_holdings", None)
    if not callable(current) or not callable(tracker_reader):
        return False
    if _chain_has_exact(current, "account_audit_v285"):
        return True
    original = current

    @wraps(original)
    def account_audit_v285(account: str, broker: Any, structural_exit_ready: bool):
        reasons, positions = original(account, broker, structural_exit_ready)
        reasons = list(reasons or [])
        positions = [dict(row) for row in tuple(positions or ()) if isinstance(row, Mapping)]
        if broker is None or not _connected(broker):
            return list(dict.fromkeys(reasons)), positions

        snapshot_ok, snapshot_reason, rows, age_s, generation = _snapshot_status(broker)
        if not snapshot_ok:
            reasons.append(snapshot_reason)
            for row in positions:
                row["protective_exit_verified"] = False
                row["snapshot_age_s"] = age_s
                row["snapshot_generation"] = generation
                row["exit_protections_attached"] = ()
            return list(dict.fromkeys(reasons)), positions

        snapshot_map = {
            _normalise_symbol(row.get("symbol")): _float(row.get("quantity"))
            for row in rows
            if _normalise_symbol(row.get("symbol")) and _float(row.get("quantity")) > 0
        }
        snapshot_detail = {
            _normalise_symbol(row.get("symbol")): dict(row)
            for row in rows
            if _normalise_symbol(row.get("symbol"))
        }
        held, tracker_errors = tracker_reader(broker)
        reasons.extend(tracker_errors or [])
        held_symbols = set(held)
        snapshot_symbols = set(snapshot_map)
        for symbol in sorted(snapshot_symbols - held_symbols):
            reasons.append(f"authoritative_snapshot_missing_tracker_position:{symbol}")
        for symbol in sorted(held_symbols - snapshot_symbols):
            reasons.append(f"tracker_position_missing_authoritative_snapshot:{symbol}")
        for symbol in sorted(snapshot_symbols & held_symbols):
            tracked_qty = _float((held.get(symbol) or {}).get("quantity"))
            broker_qty = _float(snapshot_map.get(symbol))
            if not _quantity_matches(tracked_qty, broker_qty):
                reasons.append(f"reconciliation_quantity_mismatch:{symbol}:broker={broker_qty:.12g}:tracker={tracked_qty:.12g}")

        for row in positions:
            symbol = _normalise_symbol(row.get("symbol"))
            detail = snapshot_detail.get(symbol, {})
            broker_qty = _float(detail.get("quantity"))
            tracker_qty = _float(row.get("quantity"))
            qty_ok = symbol in snapshot_map and _quantity_matches(tracker_qty, broker_qty)
            row["snapshot_quantity"] = broker_qty
            row["snapshot_entry_price"] = _float(detail.get("entry_price"))
            row["snapshot_cost_basis"] = _float(detail.get("cost_basis"))
            row["snapshot_age_s"] = age_s
            row["snapshot_generation"] = generation
            row["authoritative_snapshot_current"] = True
            verified = bool(row.get("protective_exit_verified")) and qty_ok
            row["protective_exit_verified"] = verified
            row["exit_protections_attached"] = (
                ("stop_loss", "take_profit", "trailing_take_profit", "trailing_stop", "auto_exit_reconciler")
                if verified else ()
            )
        return list(dict.fromkeys(reasons)), positions

    account_audit_v285.__name__ = "account_audit_v285"
    setattr(account_audit_v285, _PATCH_ATTR, True)
    setattr(account_audit_v285, "__wrapped__", current)
    v281._account_audit = account_audit_v285
    return True


def _patch_v282_position_proof() -> bool:
    try:
        v282 = importlib.import_module("bot.runtime_kraken_user_position_eligibility_v282_patch")
    except Exception:
        return True
    current = getattr(v282, "_position_proof", None)
    if not callable(current):
        return False
    if _chain_has_exact(current, "position_proof_v285"):
        return True
    original = current

    @wraps(original)
    def position_proof_v285(broker: Any) -> tuple[bool, str]:
        ok, reason = original(broker)
        if not ok:
            return False, str(reason or "position_proof_unavailable")
        snapshot_ok, snapshot_reason, _rows, _age, _generation = _snapshot_status(broker)
        if not snapshot_ok:
            return False, snapshot_reason
        return True, "authoritative_current_position_snapshot_adopted"

    position_proof_v285.__name__ = "position_proof_v285"
    setattr(position_proof_v285, _PATCH_ATTR, True)
    setattr(position_proof_v285, "__wrapped__", current)
    v282._position_proof = position_proof_v285
    return True


def _canonical_manager() -> Any:
    try:
        module = importlib.import_module("bot.multi_account_broker_manager")
        getter = getattr(module, "get_broker_manager", None)
        if callable(getter):
            return getter()
        return getattr(module, "multi_account_broker_manager", None)
    except Exception:
        return None


def _expected_accounts(manager: Any) -> dict[str, Any]:
    try:
        v281 = importlib.import_module("bot.runtime_all_account_position_exit_coverage_v281_patch")
        fn = getattr(v281, "_expected_accounts", None)
        result = fn(manager) if callable(fn) else {}
        return dict(result) if isinstance(result, Mapping) else {}
    except Exception:
        return {}


def _refresh_one_user(manager: Any) -> str:
    expected = _expected_accounts(manager)
    now = time.monotonic()
    for account, broker in expected.items():
        if not str(account).startswith("user:"):
            continue
        if broker is None or not _connected(broker):
            continue
        ready, reason = _strong_broker_proof(broker)
        if now < _USER_NEXT_REFRESH.get(str(account), 0.0):
            continue
        if not _USER_REFRESH_LOCK.acquire(blocking=False):
            return "user_refresh_busy"
        try:
            try:
                sync = importlib.import_module("bot.startup_position_sync")
                adopter = getattr(sync, "_adopt_broker_positions", None)
                eps_getter = getattr(sync, "_get_entry_price_store", None)
                if not callable(adopter):
                    _USER_NEXT_REFRESH[str(account)] = now + _retry_s()
                    return f"{account}:adopter_missing"
                eps = eps_getter() if callable(eps_getter) else None
                adopter(broker, str(account), eps)
            except Exception as exc:
                _USER_NEXT_REFRESH[str(account)] = time.monotonic() + _retry_s()
                LOGGER.warning(
                    "AUTHORITATIVE_USER_POSITION_V285_REFRESH_FAILED marker=%s account=%s reason=%s error=%s:%s fail_closed=true synthetic_success=false",
                    MARKER, account, reason, type(exc).__name__, exc,
                )
                return f"{account}:refresh_exception"

            refreshed, refreshed_reason = _strong_broker_proof(broker)
            _USER_NEXT_REFRESH[str(account)] = time.monotonic() + (_refresh_interval_s() if refreshed else _retry_s())
            log = LOGGER.critical if refreshed else LOGGER.warning
            log(
                "AUTHORITATIVE_USER_POSITION_V285_REFRESH marker=%s account=%s ready=%s reason=%s bounded_startup_adopter=true read_only_snapshot=true synthetic_success=false exits_preserved=true user_entries_fail_closed_until_ready=true",
                MARKER, account, str(refreshed).lower(), refreshed_reason,
            )
            return f"{account}:{'ready' if refreshed else refreshed_reason}"
        finally:
            _USER_REFRESH_LOCK.release()
    return "no_user_refresh_needed"


def _kick_user_reconnect(manager: Any) -> dict[str, Any]:
    try:
        v86 = importlib.import_module("bot.kraken_all_account_supervision_v86")
        reconcile = getattr(v86, "reconcile_once", None)
        result = reconcile(manager) if callable(reconcile) else {}
        return dict(result) if isinstance(result, Mapping) else {}
    except Exception as exc:
        return {"ok": False, "reason": f"v86_reconcile_error:{type(exc).__name__}:{exc}"}


def _kick_platform_refresh(manager: Any) -> int:
    try:
        v108 = importlib.import_module("bot.platform_position_sync_v108_patch")
        dispatch = getattr(v108, "dispatch_platform_position_sync", None)
        return int(dispatch(manager, trigger="v285_authoritative_position_coverage") or 0) if callable(dispatch) else 0
    except Exception:
        return 0


def _publish_v96(manager: Any) -> None:
    try:
        v96 = importlib.import_module("bot.position_sync_dispatch_authority_v96_patch")
        publish = getattr(v96, "publish_position_sync_readiness", None)
        if callable(publish):
            publish(manager, source="v285_authoritative_position_coverage")
    except Exception:
        pass


def _audit_v281() -> dict[str, Any]:
    try:
        v281 = importlib.import_module("bot.runtime_all_account_position_exit_coverage_v281_patch")
        audit = getattr(v281, "audit_once", None)
        result = audit() if callable(audit) else {}
        return dict(result) if isinstance(result, Mapping) else {}
    except Exception as exc:
        return {"ready": False, "expected_accounts": (), "pending": {"__audit__": (f"{type(exc).__name__}:{exc}",)}, "positions": ()}


def _emit_state(result: Mapping[str, Any], reconnect_state: Mapping[str, Any], user_refresh: str, platform_workers: int) -> None:
    global _LAST_SIGNATURE
    ready = bool(result.get("ready"))
    os.environ[_COVERAGE_FLAG] = "1" if ready else "0"
    expected = tuple(result.get("expected_accounts", ()) or ())
    pending_raw = result.get("pending", {}) if isinstance(result.get("pending", {}), Mapping) else {}
    pending = {str(account): tuple(str(reason) for reason in tuple(reasons or ())) for account, reasons in pending_raw.items()}
    positions = tuple(row for row in tuple(result.get("positions", ()) or ()) if isinstance(row, Mapping))
    position_sig = tuple(sorted((
        str(row.get("account", "")), str(row.get("symbol", "")), str(row.get("quantity", "")),
        str(row.get("snapshot_quantity", "")), str(row.get("entry_price", "")),
        str(row.get("protective_exit_verified", False)),
    ) for row in positions))
    signature = repr((ready, expected, tuple(sorted(pending.items())), position_sig, user_refresh, platform_workers, reconnect_state.get("connected"), reconnect_state.get("disconnected")))
    with _LOCK:
        if signature == _LAST_SIGNATURE:
            return
        _LAST_SIGNATURE = signature

    LOGGER.critical(
        "AUTHORITATIVE_POSITION_COVERAGE_V285_STATE marker=%s ready=%s expected=%s pending=%s platform_refresh_workers=%d user_refresh=%s kraken_user_reconnect=%s snapshot_max_age_s=%.1f authoritative_fetch_required=true current_snapshot_required=true quantity_reconciliation_required=true protective_exit_adoption_required=true synthetic_success=false safety_gates_bypassed=false",
        MARKER, str(ready).lower(), expected, pending, int(platform_workers), user_refresh,
        dict(reconnect_state), _snapshot_max_age_s(),
    )
    for row in positions:
        LOGGER.critical(
            "AUTHORITATIVE_POSITION_COVERAGE_V285_POSITION marker=%s account=%s broker=%s symbol=%s quantity=%s snapshot_quantity=%s entry_price=%s cost_basis=%s snapshot_cost_basis=%s snapshot_age_s=%s snapshot_generation=%s protections=%s protective_exit_verified=%s",
            MARKER, row.get("account", "unknown"), row.get("broker", "unknown"),
            row.get("symbol", "unknown"), row.get("quantity", "unknown"),
            row.get("snapshot_quantity", "unknown"), row.get("entry_price", "unknown"),
            (abs(_float(row.get("quantity"))) * _float(row.get("entry_price"))) if _float(row.get("entry_price")) > 0 else "unknown",
            row.get("snapshot_cost_basis", "unknown"), row.get("snapshot_age_s", "unknown"),
            row.get("snapshot_generation", "unknown"), row.get("exit_protections_attached", ()),
            str(bool(row.get("protective_exit_verified"))).lower(),
        )


def _patch_loaded() -> bool:
    return all((
        _patch_broker_get_positions(),
        _patch_v95_status(),
        _patch_v182_discovery(),
        _patch_v281_account_audit(),
        _patch_v282_position_proof(),
    ))


def reconcile_once() -> dict[str, Any]:
    _patch_loaded()
    manager = _canonical_manager()
    if manager is None:
        result = {"ready": False, "expected_accounts": (), "pending": {"__registry__": ("canonical_manager_missing",)}, "positions": ()}
        _emit_state(result, {}, "manager_missing", 0)
        return result
    reconnect_state = _kick_user_reconnect(manager)
    platform_workers = _kick_platform_refresh(manager)
    user_refresh = _refresh_one_user(manager)
    _publish_v96(manager)
    result = _audit_v281()
    _emit_state(result, reconnect_state, user_refresh, platform_workers)
    return result


def _register_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_authoritative_position_coverage_v285"] = _READY_FLAG
        return True
    except Exception:
        return False


def _monitor() -> None:
    while not _MONITOR_STOP.wait(_monitor_interval_s()):
        try:
            reconcile_once()
        except Exception as exc:
            os.environ[_COVERAGE_FLAG] = "0"
            LOGGER.error(
                "AUTHORITATIVE_POSITION_COVERAGE_V285_MONITOR_ERROR marker=%s error=%s:%s coverage_fail_closed=true",
                MARKER, type(exc).__name__, exc,
            )


def install() -> bool:
    global _MONITOR_STARTED
    with _LOCK:
        try:
            v282 = importlib.import_module("bot.runtime_kraken_user_position_eligibility_v282_patch")
            installer = getattr(v282, "install_import_hook", None)
            if callable(installer):
                installer()
        except Exception:
            pass
        manifest_ok = _register_manifest()
        patched = _patch_loaded()
        ready = bool(manifest_ok and patched)
        os.environ[_READY_FLAG] = "1" if ready else "0"
        os.environ[_INSTALLED_FLAG] = "1" if ready else "0"
        if not _MONITOR_STARTED:
            _MONITOR_STARTED = True
            threading.Thread(target=_monitor, name="AuthoritativePositionCoverageV285", daemon=True).start()
    try:
        reconcile_once()
    except Exception:
        os.environ[_COVERAGE_FLAG] = "0"
    log = LOGGER.critical if ready else LOGGER.error
    log(
        "RUNTIME_AUTHORITATIVE_POSITION_COVERAGE_V285_%s marker=%s ready=%s snapshot_max_age_s=%.1f platform_v108_retry=true user_bounded_refresh=true v95_fetch_plus_adoption_required=true v281_quantity_reconciliation=true v282_current_snapshot_required=true v86_authenticated_reconnect_preserved=true connectivity_fabricated=false position_fabricated=false cost_basis_fabricated=false execution_proof_fabricated=false forced_trade=false forced_activation=false writer_nonce_risk_capital_killswitch_broker_health_order_fill_gates_unchanged=true safety_gates_bypassed=false",
        "READY" if ready else "NOT_READY", MARKER, str(ready).lower(), _snapshot_max_age_s(),
    )
    return ready


def install_import_hook() -> bool:
    return install()


def stop() -> None:
    _MONITOR_STOP.set()


__all__ = [
    "MARKER", "RELEASE_ID", "install", "install_import_hook", "stop", "reconcile_once",
    "_snapshot_max_age_s", "_snapshot_rows", "_record_snapshot_success", "_record_snapshot_failure",
    "_snapshot_status", "_strong_broker_proof", "_patch_broker_get_positions", "_patch_v95_status",
    "_patch_v182_discovery", "_patch_v281_account_audit", "_patch_v282_position_proof", "_refresh_one_user",
]
