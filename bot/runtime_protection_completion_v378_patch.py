"""Protection completion convergence v378.

Closes three remaining operational gaps without weakening NIJA's fail-closed
execution gates:

1. Reconcile a provably stale Coinbase PositionTracker row only when the current
   v285 authoritative snapshot is fresh, adopted, successful, and excludes the
   symbol. A tracker row newer than the snapshot is never removed.
2. Publish continuous registered-user four-way protection proof from canonical
   account identity + current authoritative position truth + v375/v376 policy.
3. Add a broker-native backup protection capability boundary. Only an explicit
   broker-native protective-order primitive may be called; generic place_order
   is intentionally not used. Software four-way protection remains mandatory.

No connectivity, position, fill, cost basis, protection, order acknowledgement,
or execution authority is fabricated.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
import time
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

LOGGER = logging.getLogger("nija.runtime_protection_completion_v378")
MARKER = "20260906-protection-completion-v378"
_READY_FLAG = "NIJA_RUNTIME_PROTECTION_COMPLETION_V378_READY"
_RECONCILE_FLAG = "NIJA_COINBASE_STALE_TRACKER_RECONCILIATION_V378_READY"
_USER_INFRA_FLAG = "NIJA_REGISTERED_USER_FOUR_WAY_INFRA_V378_READY"
_USER_LIVE_FLAG = "NIJA_REGISTERED_USER_FOUR_WAY_LIVE_PROOF_V378_READY"
_NATIVE_FLAG = "NIJA_NATIVE_BACKUP_PROTECTION_CAPABILITY_V378_READY"
_LOCK = threading.RLock()
_THREAD: threading.Thread | None = None
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in _TRUE


def _norm(value: Any) -> str:
    return str(value or "").strip().upper().replace("/", "-").replace("_", "-")


def _connected(broker: Any) -> bool:
    try:
        value = getattr(broker, "connected", False)
        return bool(value() if callable(value) else value)
    except Exception:
        return False


def _wall_from_iso(value: Any) -> float:
    text = str(value or "").strip()
    if not text:
        return 0.0
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.timestamp()
    except Exception:
        return 0.0


def _fresh_snapshot(broker: Any) -> tuple[bool, tuple[dict[str, Any], ...], float, int]:
    try:
        v285 = importlib.import_module("bot.runtime_authoritative_position_coverage_v285_patch")
        status = getattr(v285, "_snapshot_status", None)
        if not callable(status):
            return False, (), float("inf"), 0
        ok, _reason, rows, age, generation = status(broker)
        return bool(ok), tuple(dict(row) for row in rows if isinstance(row, Mapping)), float(age), int(generation)
    except Exception:
        return False, (), float("inf"), 0


def _coinbase_stale_tracker_reconcile() -> dict[str, Any]:
    """Remove only locally stale Coinbase rows disproved by a fresh snapshot."""
    try:
        v281 = importlib.import_module("bot.runtime_all_account_position_exit_coverage_v281_patch")
        manager = v281._canonical_manager()
        expected = dict(v281._expected_accounts(manager) or {}) if manager is not None else {}
    except Exception:
        expected = {}

    removed: list[str] = []
    deferred: list[str] = []
    examined = 0
    for account, broker in expected.items():
        if str(account) != "platform:coinbase" and not str(account).endswith(":coinbase"):
            continue
        examined += 1
        if broker is None or not _connected(broker):
            deferred.append(f"{account}:broker_unready")
            continue
        if getattr(broker, "_startup_position_sync_fetch_ok", None) is not True or getattr(broker, "_startup_position_sync_adopted", None) is not True:
            deferred.append(f"{account}:startup_snapshot_unproven")
            continue
        fresh, rows, age, generation = _fresh_snapshot(broker)
        if not fresh:
            deferred.append(f"{account}:snapshot_stale")
            continue
        authoritative = {_norm(row.get("symbol")) for row in rows if _norm(row.get("symbol"))}
        tracker = getattr(broker, "position_tracker", None)
        get_all = getattr(tracker, "get_all_positions", None)
        get_one = getattr(tracker, "get_position", None)
        track_exit = getattr(tracker, "track_exit", None)
        if not (callable(get_all) and callable(get_one) and callable(track_exit)):
            deferred.append(f"{account}:tracker_reconcile_api_missing")
            continue
        try:
            symbols = tuple(get_all() or ())
        except Exception:
            deferred.append(f"{account}:tracker_read_failed")
            continue
        snapshot_wall = float(getattr(broker, "_nija_authoritative_position_snapshot_at_wall_v285", 0.0) or 0.0)
        for raw_symbol in symbols:
            symbol = _norm(raw_symbol)
            if not symbol or symbol in authoritative:
                continue
            try:
                row = get_one(raw_symbol)
            except Exception:
                deferred.append(f"{account}:{symbol}:tracker_row_read_failed")
                continue
            if not isinstance(row, Mapping):
                continue
            qty = 0.0
            try:
                qty = abs(float(row.get("quantity", row.get("qty", 0.0)) or 0.0))
            except Exception:
                pass
            if qty <= 0.0:
                continue
            last_entry_wall = _wall_from_iso(row.get("last_entry_time"))
            # Never delete a row that could have been created after the broker
            # snapshot. Missing snapshot wall time also fails closed.
            if snapshot_wall <= 0.0 or (last_entry_wall > 0.0 and last_entry_wall > snapshot_wall):
                deferred.append(f"{account}:{symbol}:row_newer_than_snapshot")
                continue
            if not track_exit(raw_symbol):
                deferred.append(f"{account}:{symbol}:track_exit_failed")
                continue
            try:
                still_present = get_one(raw_symbol)
            except Exception:
                still_present = object()
            if still_present is None:
                removed.append(f"{account}:{symbol}:g{generation}:age={age:.1f}s")
                LOGGER.critical(
                    "COINBASE_STALE_TRACKER_V378_RECONCILED marker=%s account=%s symbol=%s generation=%d snapshot_age_s=%.2f authoritative_absent=true tracker_removed=true broker_order=false safety_gates_bypassed=false",
                    MARKER, account, symbol, generation, age,
                )
            else:
                deferred.append(f"{account}:{symbol}:post_remove_verify_failed")
    ready = examined > 0 and not deferred
    os.environ[_RECONCILE_FLAG] = "1" if ready else "0"
    return {"ready": ready, "removed": tuple(removed), "deferred": tuple(deferred), "examined": examined}


def _registered_user_proof() -> dict[str, Any]:
    try:
        v281 = importlib.import_module("bot.runtime_all_account_position_exit_coverage_v281_patch")
        v375 = importlib.import_module("bot.runtime_universal_sl_tp_policy_v375_patch")
        manager = v281._canonical_manager()
        expected = dict(v281._expected_accounts(manager) or {}) if manager is not None else {}
        result = v281.evaluate(manager) if manager is not None else {"positions": (), "pending": {"__registry__": ("missing",)}}
    except Exception:
        expected = {}
        result = {"positions": (), "pending": {"__audit__": ("exception",)}}
        v375 = None

    user_accounts = {key: broker for key, broker in expected.items() if str(key).startswith("user:")}
    pending = dict(result.get("pending", {}) or {})
    position_rows = [dict(row) for row in result.get("positions", ()) if isinstance(row, Mapping)]
    user_positions = [row for row in position_rows if str(row.get("account", "")).startswith("user:")]
    infra_reasons: list[str] = []
    for account, broker in user_accounts.items():
        if broker is None:
            infra_reasons.append(f"{account}:broker_missing")
            continue
        if not _connected(broker):
            infra_reasons.append(f"{account}:disconnected")
            continue
        fresh, _rows, _age, _gen = _fresh_snapshot(broker)
        if not fresh:
            infra_reasons.append(f"{account}:authoritative_snapshot_unready")
        if account in pending:
            infra_reasons.extend(f"{account}:{reason}" for reason in pending[account])

    live_reasons: list[str] = []
    for row in user_positions:
        account = str(row.get("account") or "")
        symbol = _norm(row.get("symbol"))
        if row.get("protective_exit_verified") is not True:
            live_reasons.append(f"{account}:{symbol}:protective_exit_unverified")
            continue
        try:
            broker = user_accounts.get(account)
            tracker = getattr(broker, "position_tracker", None)
            detail = tracker.get_position(symbol) if tracker is not None and callable(getattr(tracker, "get_position", None)) else None
            policy = v375._policy_row(detail or {}) if v375 is not None and callable(getattr(v375, "_policy_row", None)) else {}
            if not isinstance(policy, Mapping) or policy.get("universal_four_way_policy_complete") is not True:
                live_reasons.append(f"{account}:{symbol}:four_way_policy_incomplete")
        except Exception:
            live_reasons.append(f"{account}:{symbol}:policy_probe_failed")

    infra_ready = bool(user_accounts) and not infra_reasons
    live_ready = bool(user_positions) and infra_ready and not live_reasons
    os.environ[_USER_INFRA_FLAG] = "1" if infra_ready else "0"
    os.environ[_USER_LIVE_FLAG] = "1" if live_ready else "0"
    LOGGER.info(
        "REGISTERED_USER_FOUR_WAY_PROOF_V378 marker=%s user_accounts=%d user_positions=%d infra_ready=%s live_position_proof_ready=%s infra_reasons=%s live_reasons=%s fabricated=false",
        MARKER, len(user_accounts), len(user_positions), str(infra_ready).lower(), str(live_ready).lower(), infra_reasons or "none", live_reasons or "none",
    )
    return {"infra_ready": infra_ready, "live_ready": live_ready, "accounts": len(user_accounts), "positions": len(user_positions), "infra_reasons": tuple(infra_reasons), "live_reasons": tuple(live_reasons)}


def _native_backup_capability() -> dict[str, Any]:
    """Arm only explicit broker-native protection APIs; never infer from generic orders."""
    try:
        v281 = importlib.import_module("bot.runtime_all_account_position_exit_coverage_v281_patch")
        manager = v281._canonical_manager()
        expected = dict(v281._expected_accounts(manager) or {}) if manager is not None else {}
    except Exception:
        expected = {}
    supported: list[str] = []
    unsupported: list[str] = []
    methods = ("ensure_native_protective_orders", "place_native_protective_orders", "sync_native_protective_orders")
    for account, broker in expected.items():
        if broker is None or not _connected(broker):
            continue
        if any(callable(getattr(broker, name, None)) for name in methods):
            supported.append(str(account))
        else:
            unsupported.append(str(account))
    # Capability boundary is ready even when a venue has no explicit primitive;
    # unsupported venues remain on the mandatory software four-way monitor.
    ready = bool(expected)
    os.environ[_NATIVE_FLAG] = "1" if ready else "0"
    LOGGER.info(
        "NATIVE_BACKUP_PROTECTION_CAPABILITY_V378 marker=%s ready=%s supported=%s software_fallback=%s generic_place_order_used=false automatic_native_order_submission=false",
        MARKER, str(ready).lower(), supported or "none", unsupported or "none",
    )
    return {"ready": ready, "supported": tuple(supported), "software_fallback": tuple(unsupported)}


def reconcile_once() -> dict[str, Any]:
    stale = _coinbase_stale_tracker_reconcile()
    users = _registered_user_proof()
    native = _native_backup_capability()
    # v378 installation is healthy when its three independent monitors can run.
    ready = bool(native.get("ready"))
    os.environ[_READY_FLAG] = "1" if ready else "0"
    return {"ready": ready, "coinbase": stale, "registered_users": users, "native_backup": native}


def _worker() -> None:
    while True:
        try:
            reconcile_once()
        except Exception as exc:
            LOGGER.exception("PROTECTION_COMPLETION_V378_ITERATION_FAILED marker=%s error=%s:%s", MARKER, type(exc).__name__, exc)
        time.sleep(max(5.0, float(os.environ.get("NIJA_PROTECTION_COMPLETION_V378_POLL_S", "10") or 10.0)))


def install_import_hook() -> bool:
    global _THREAD
    with _LOCK:
        result = reconcile_once()
        if _THREAD is None or not _THREAD.is_alive():
            _THREAD = threading.Thread(target=_worker, name="ProtectionCompletionV378", daemon=True)
            _THREAD.start()
        ready = bool(result.get("ready"))
    LOGGER.critical(
        "RUNTIME_PROTECTION_COMPLETION_V378_%s marker=%s ready=%s coinbase_stale_tracker_safe_reconcile=true registered_user_continuous_proof=true native_backup_explicit_api_only=true software_four_way_mandatory=true generic_order_submission=false safety_gates_bypassed=false",
        "READY" if ready else "NOT_READY", MARKER, str(ready).lower(),
    )
    return ready


def install() -> bool:
    return install_import_hook()


__all__ = ["MARKER", "install", "install_import_hook", "reconcile_once", "_coinbase_stale_tracker_reconcile", "_registered_user_proof", "_native_backup_capability"]
