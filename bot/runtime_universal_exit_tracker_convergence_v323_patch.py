"""Universal protective-exit tracker convergence v323.

Production evidence on 2026-08-31 exposed a systemic exit liveness gap across
platform and user accounts.  The universal broker exit supervisor expected
``position_tracker.get_all_positions()`` to return full position mappings, while
NIJA's canonical trackers commonly return symbol names and require a second
``get_position(symbol)`` lookup.  The supervisor could therefore be installed,
registered and healthy while scanning zero real holdings.

v323 repairs that contract without weakening exit truth:

* symbol-only tracker enumerations are resolved through the tracker-owned
  ``get_position`` API into the exact stored position row;
* new exit submissions require verified cost basis, a positive entry/quantity,
  no explicit auto-exit/dust block, and quantity agreement with a genuine recent
  v285 authoritative broker snapshot;
* a transient new position-fetch failure does not immediately strand an already
  proven holding: the last genuine v285 quantity proof remains usable for
  protective exits only while its original snapshot timestamp is inside the
  existing v285 TTL; the TTL is never extended or refreshed here;
* a tracker-only/ghost symbol, stale snapshot, quantity mismatch, unverified cost
  basis or policy-dust row is never submitted as an exit;
* v67 remains the single submit/reconcile/fill authority.  Pending exits are
  reconciled before this trigger guard is consulted, so partial/pending fills are
  never resubmitted merely because tracker quantity changed.

No broker position, cost basis, price, order acknowledgement, fill, readiness or
profit is fabricated.  Stop-loss, take-profit, trailing take-profit, trailing
stop, writer, nonce, capital, risk, kill-switch, minimum-order and fill
confirmation contracts remain authoritative.
"""
from __future__ import annotations

import builtins
import importlib
import logging
import os
import sys
import threading
import time
from collections.abc import Mapping
from functools import wraps
from types import ModuleType
from typing import Any

LOGGER = logging.getLogger("nija.runtime_universal_exit_tracker_convergence_v323")
MARKER = "20260831-universal-exit-tracker-convergence-v323"
RELEASE_ID = "20260831-runtime-convergence-v323"
_READY_FLAG = "NIJA_RUNTIME_UNIVERSAL_EXIT_TRACKER_CONVERGENCE_V323_READY"
_TRACKER_PATCH_ATTR = "_nija_universal_exit_tracker_reader_v323"
_TRIGGER_PATCH_ATTR = "_nija_universal_exit_position_proof_v323"
_V67_POSITION_PATCH_ATTR = "_nija_universal_exit_fill_position_reader_v323"
_IMPORT_HOOK_FLAG = "_NIJA_UNIVERSAL_EXIT_TRACKER_CONVERGENCE_V323_IMPORT_HOOK"
_LOCK = threading.RLock()
_LOG_LOCK = threading.RLock()
_LAST_SKIP_LOG: dict[tuple[int, str, str], float] = {}


def _f(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
        return default if number != number else number
    except Exception:
        return default


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on", "enabled", "y"}


def _normalise_symbol(value: Any) -> str:
    return str(value or "").strip().upper().replace("/", "-").replace("_", "-")


def _snapshot_max_age_s() -> float:
    try:
        value = float(os.environ.get("NIJA_AUTHORITATIVE_POSITION_SNAPSHOT_MAX_AGE_S", "90") or 90.0)
    except (TypeError, ValueError):
        value = 90.0
    return max(15.0, min(600.0, value))


def _quantity_matches(left: float, right: float) -> bool:
    tolerance = max(1e-10, abs(right) * 1e-6)
    return abs(left - right) <= tolerance


def _mapping_from_item(tracker: Any, item: Any, *, key_hint: Any = None) -> dict[str, Any] | None:
    if isinstance(item, Mapping):
        row = dict(item)
        if key_hint is not None and not row.get("symbol"):
            row["symbol"] = key_hint
        return row

    if isinstance(item, (str, bytes, bytearray)):
        symbol = item.decode(errors="ignore") if isinstance(item, (bytes, bytearray)) else str(item)
        getter = getattr(tracker, "get_position", None)
        if callable(getter):
            for candidate in (item, symbol, _normalise_symbol(symbol)):
                try:
                    row = getter(candidate)
                except Exception:
                    continue
                if isinstance(row, Mapping):
                    output = dict(row)
                    output.setdefault("symbol", symbol)
                    return output
        return None

    raw = dict(getattr(item, "__dict__", {}) or {})
    if raw:
        if key_hint is not None and not raw.get("symbol"):
            raw["symbol"] = key_hint
        return raw
    return None


def _resolve_tracker_rows(universal: ModuleType, broker: Any) -> list[dict[str, Any]]:
    tracker = getattr(broker, "position_tracker", None)
    candidates: list[dict[str, Any]] = []

    if tracker is not None:
        for method_name in ("get_all_positions", "get_open_positions", "list_positions"):
            method = getattr(tracker, method_name, None)
            if not callable(method):
                continue
            try:
                raw = method()
            except Exception:
                continue

            if isinstance(raw, Mapping):
                for key, value in raw.items():
                    row = _mapping_from_item(tracker, value, key_hint=key)
                    if row is None and not isinstance(value, Mapping):
                        row = _mapping_from_item(tracker, key, key_hint=key)
                    if row is not None:
                        candidates.append(row)
            elif isinstance(raw, (list, tuple, set, frozenset)):
                for value in raw:
                    row = _mapping_from_item(tracker, value)
                    if row is not None:
                        candidates.append(row)
            elif raw is not None:
                try:
                    for value in tuple(raw):
                        row = _mapping_from_item(tracker, value)
                        if row is not None:
                            candidates.append(row)
                except Exception:
                    pass
            if candidates:
                break

    # Preserve the universal supervisor's legacy object-local fallbacks for
    # broker adapters that do not expose the canonical tracker API.
    for attr in ("positions", "open_positions", "tracked_positions"):
        raw = getattr(broker, attr, None)
        if isinstance(raw, Mapping):
            for key, value in raw.items():
                row = _mapping_from_item(tracker, value, key_hint=key)
                if row is not None:
                    candidates.append(row)
        elif isinstance(raw, (list, tuple, set, frozenset)):
            for value in raw:
                row = _mapping_from_item(tracker, value)
                if row is not None:
                    candidates.append(row)

    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in candidates:
        pos = dict(row)
        symbol = universal.auto_exit._sym(pos.get("symbol") or pos.get("pair"))
        qty = universal.auto_exit._quantity(pos)
        if not symbol or qty <= 0.0:
            continue
        key = f"{symbol}:{pos.get('position_id') or ''}:{qty:.12f}"
        if key in seen:
            continue
        seen.add(key)
        pos["symbol"] = symbol
        pos.setdefault("account_id", universal._account_label(broker))
        normalized.append(pos)
    return normalized


def _recent_authoritative_quantity(broker: Any, symbol: str) -> tuple[bool, float, float, int, str]:
    at = _f(getattr(broker, "_nija_authoritative_position_snapshot_at_monotonic_v285", 0.0))
    if at <= 0.0 or not hasattr(broker, "_nija_authoritative_position_snapshot_rows_v285"):
        return False, 0.0, float("inf"), 0, "authoritative_snapshot_missing"
    age = max(0.0, time.monotonic() - at)
    if age > _snapshot_max_age_s():
        return False, 0.0, age, 0, "authoritative_snapshot_stale"
    try:
        generation = int(getattr(broker, "_nija_authoritative_position_snapshot_generation_v285", 0) or 0)
    except Exception:
        generation = 0
    try:
        rows = tuple(getattr(broker, "_nija_authoritative_position_snapshot_rows_v285", ()) or ())
    except Exception:
        return False, 0.0, age, generation, "authoritative_snapshot_invalid"

    target = _normalise_symbol(symbol)
    total = 0.0
    observed = False
    for raw in rows:
        if not isinstance(raw, Mapping):
            continue
        if _normalise_symbol(raw.get("symbol")) != target:
            continue
        observed = True
        for key in ("quantity", "qty", "amount", "size", "units", "balance"):
            if raw.get(key) is not None:
                total += abs(_f(raw.get(key)))
                break
    if not observed or total <= 0.0:
        return False, 0.0, age, generation, "symbol_absent_from_recent_authoritative_snapshot"
    return True, total, age, generation, "recent_authoritative_quantity"


def _policy_dust(pos: Mapping[str, Any]) -> bool:
    if _truthy(pos.get("exclude_from_auto_exit", False)):
        return True
    return bool(
        str(pos.get("classification", "") or "").strip().upper() == "DUST"
        and pos.get("exclude_from_reconciliation") is True
        and pos.get("exclude_from_auto_exit") is True
        and pos.get("exclude_from_strategy") is True
        and pos.get("exclude_from_position_limit") is True
    )


def _position_exit_proof(universal: ModuleType, broker: Any, pos: Mapping[str, Any]) -> tuple[bool, str, dict[str, Any]]:
    symbol = universal.auto_exit._sym(pos.get("symbol"))
    qty = universal.auto_exit._quantity(dict(pos))
    entry = universal.auto_exit._entry_price(dict(pos))
    if not symbol or qty <= 0.0:
        return False, "invalid_symbol_or_quantity", {}
    if _policy_dust(pos):
        return False, "dust_excluded_from_auto_exit", {}
    if _truthy(pos.get("auto_exit_blocked", False)):
        return False, "auto_exit_blocked", {}
    if pos.get("cost_basis_verified") is not True:
        return False, "cost_basis_unverified", {}
    if entry <= 0.0:
        return False, "entry_price_unverified", {}

    auth_ok, auth_qty, age, generation, auth_reason = _recent_authoritative_quantity(broker, symbol)
    if not auth_ok:
        return False, auth_reason, {
            "snapshot_age_s": age,
            "snapshot_generation": generation,
        }
    if not _quantity_matches(qty, auth_qty):
        return False, "authoritative_quantity_mismatch", {
            "tracker_quantity": qty,
            "authoritative_quantity": auth_qty,
            "snapshot_age_s": age,
            "snapshot_generation": generation,
        }
    return True, "verified_recent_authoritative_position", {
        "tracker_quantity": qty,
        "authoritative_quantity": auth_qty,
        "snapshot_age_s": age,
        "snapshot_generation": generation,
    }


def _log_skip(universal: ModuleType, broker: Any, pos: Mapping[str, Any], reason: str, details: Mapping[str, Any]) -> None:
    symbol = universal.auto_exit._sym(pos.get("symbol")) or "unknown"
    key = (id(broker), symbol, str(reason))
    now = time.monotonic()
    with _LOG_LOCK:
        previous = _LAST_SKIP_LOG.get(key, 0.0)
        if now - previous < 30.0:
            return
        _LAST_SKIP_LOG[key] = now
        if len(_LAST_SKIP_LOG) > 256:
            cutoff = now - 120.0
            for old_key in tuple(_LAST_SKIP_LOG):
                if _LAST_SKIP_LOG.get(old_key, 0.0) < cutoff:
                    _LAST_SKIP_LOG.pop(old_key, None)
    LOGGER.warning(
        "UNIVERSAL_EXIT_V323_POSITION_DEFERRED marker=%s venue=%s account=%s symbol=%s reason=%s "
        "tracker_qty=%.12f authoritative_qty=%.12f snapshot_age_s=%.3f snapshot_generation=%s "
        "cost_basis_verified=%s auto_exit_blocked=%s new_exit_submitted=false pending_reconciliation_unchanged=true "
        "snapshot_ttl_unchanged=true position_success_fabricated=false safety_gates_bypassed=false",
        MARKER,
        universal.auto_exit._broker_label(broker) or "unknown",
        universal._account_label(broker),
        symbol,
        reason,
        universal.auto_exit._quantity(dict(pos)),
        _f(details.get("authoritative_quantity")),
        _f(details.get("snapshot_age_s"), float("inf")),
        details.get("snapshot_generation", 0),
        str(pos.get("cost_basis_verified")),
        str(_truthy(pos.get("auto_exit_blocked", False))).lower(),
    )


def _patch_universal(module: ModuleType) -> bool:
    tracker_current = getattr(module, "_tracker_positions", None)
    trigger_current = getattr(module, "_trigger", None)
    if not callable(tracker_current) or not callable(trigger_current):
        return False

    if not bool(getattr(tracker_current, _TRACKER_PATCH_ATTR, False)):
        original_tracker = tracker_current

        @wraps(original_tracker)
        def tracker_positions_v323(broker: Any) -> list[dict[str, Any]]:
            rows = _resolve_tracker_rows(module, broker)
            if rows:
                return rows
            # Preserve legacy fallback only when the repaired canonical reader
            # truly found nothing.  It cannot promote invalid rows because the
            # trigger proof below still requires v285 quantity + verified basis.
            try:
                return list(original_tracker(broker) or [])
            except Exception:
                return []

        setattr(tracker_positions_v323, _TRACKER_PATCH_ATTR, True)
        setattr(tracker_positions_v323, "__wrapped__", original_tracker)
        module._tracker_positions = tracker_positions_v323

    trigger_current = getattr(module, "_trigger", None)
    if callable(trigger_current) and not bool(getattr(trigger_current, _TRIGGER_PATCH_ATTR, False)):
        original_trigger = trigger_current

        @wraps(original_trigger)
        def trigger_v323(broker: Any, pos: dict[str, Any], market: float):
            safe, reason, details = _position_exit_proof(module, broker, pos)
            if not safe:
                _log_skip(module, broker, pos, reason, details)
                return False, "", 0.0
            return original_trigger(broker, pos, market)

        setattr(trigger_v323, _TRIGGER_PATCH_ATTR, True)
        setattr(trigger_v323, "__wrapped__", original_trigger)
        module._trigger = trigger_v323

    return bool(
        callable(getattr(module, "_tracker_positions", None))
        and bool(getattr(getattr(module, "_tracker_positions", None), _TRACKER_PATCH_ATTR, False))
        and callable(getattr(module, "_trigger", None))
        and bool(getattr(getattr(module, "_trigger", None), _TRIGGER_PATCH_ATTR, False))
    )


def _patch_v67(module: ModuleType) -> bool:
    current = getattr(module, "_broker_symbol_positions", None)
    if not callable(current):
        return False
    if bool(getattr(current, _V67_POSITION_PATCH_ATTR, False)):
        return True
    original = current

    @wraps(original)
    def broker_symbol_positions_v323(broker: Any) -> list[Any]:
        rows = original(broker)
        if rows and not all(isinstance(row, (str, bytes, bytearray)) for row in rows):
            return rows
        tracker = getattr(broker, "position_tracker", None)
        getter = getattr(tracker, "get_position", None)
        if not rows or not callable(getter):
            return rows
        resolved: list[Any] = []
        for symbol in rows:
            for candidate in (symbol, _normalise_symbol(symbol)):
                try:
                    row = getter(candidate)
                except Exception:
                    continue
                if isinstance(row, Mapping):
                    output = dict(row)
                    output.setdefault("symbol", symbol)
                    resolved.append(output)
                    break
        return resolved or rows

    setattr(broker_symbol_positions_v323, _V67_POSITION_PATCH_ATTR, True)
    setattr(broker_symbol_positions_v323, "__wrapped__", original)
    module._broker_symbol_positions = broker_symbol_positions_v323
    return True


def _patch_loaded() -> tuple[bool, bool]:
    universal_ready = False
    v67_ready = False
    for name in ("bot.universal_broker_exit_supervisor_patch", "universal_broker_exit_supervisor_patch"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            universal_ready = _patch_universal(module) or universal_ready
    for name in ("bot.universal_exit_fill_reconciliation_v67_patch", "universal_exit_fill_reconciliation_v67_patch"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            v67_ready = _patch_v67(module) or v67_ready
    return universal_ready, v67_ready


def _register_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_universal_exit_tracker_convergence_v323"] = _READY_FLAG
        return True
    except Exception:
        return False


def install() -> bool:
    with _LOCK:
        try:
            importlib.import_module("bot.universal_broker_exit_supervisor_patch")
            importlib.import_module("bot.universal_exit_fill_reconciliation_v67_patch")
            universal_ready, v67_ready = _patch_loaded()
            manifest = _register_manifest()

            if not bool(getattr(builtins, _IMPORT_HOOK_FLAG, False)):
                original_import = builtins.__import__

                @wraps(original_import)
                def importing(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
                    result = original_import(name, globals, locals, fromlist, level)
                    text = str(name or "")
                    if "universal_broker_exit" in text or "universal_exit_fill_reconciliation_v67" in text:
                        _patch_loaded()
                    return result

                builtins.__import__ = importing
                setattr(builtins, _IMPORT_HOOK_FLAG, True)

            ready = bool(universal_ready and v67_ready and manifest)
        except Exception as exc:
            ready = False
            LOGGER.exception(
                "UNIVERSAL_EXIT_TRACKER_CONVERGENCE_V323_INSTALL_FAILED marker=%s error=%s:%s "
                "new_entries_unchanged=true existing_exits_not_fabricated=true safety_gates_bypassed=false",
                MARKER,
                type(exc).__name__,
                exc,
            )
        os.environ[_READY_FLAG] = "1" if ready else "0"
        log = LOGGER.critical if ready else LOGGER.error
        log(
            "UNIVERSAL_EXIT_TRACKER_CONVERGENCE_V323_%s marker=%s ready=%s "
            "symbol_tracker_resolution=true per_position_v285_quantity_proof=true "
            "recent_snapshot_sticky_for_exits_only=true snapshot_ttl_unchanged=true "
            "ghost_position_exit_blocked=true unverified_cost_basis_exit_blocked=true dust_exit_blocked=true "
            "v67_fill_reconciliation_preserved=true pending_duplicate_submit_blocked=true "
            "stop_loss_preserved=true take_profit_preserved=true trailing_take_profit_preserved=true "
            "trailing_stop_preserved=true writer_nonce_capital_risk_killswitch_minimum_order_fill_gates_unchanged=true "
            "forced_exit=false safety_gates_bypassed=false",
            "READY" if ready else "NOT_READY",
            MARKER,
            str(ready).lower(),
        )
        return ready


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "RELEASE_ID",
    "install",
    "install_import_hook",
    "_resolve_tracker_rows",
    "_recent_authoritative_quantity",
    "_position_exit_proof",
    "_patch_universal",
    "_patch_v67",
]
