"""Converge startup/exit audits with NIJA's existing dust-position policy (v296).

NIJA already defines a single materiality policy in ``dust_position_filter``:
positions below ``NIJA_DUST_THRESHOLD_USD`` (default $1) remain visible and
auditable, but are excluded from cost-basis reconciliation, automatic exits,
strategy eligibility, and position limits. Production on 2026-08-30 exposed two
consumers that contradicted that policy:

* ``startup_position_sync`` classified an authoritative tracker row as DUST and
  explicitly logged that cost-basis reconciliation was skipped, but then counted
  the same intentionally-unverified cost basis as a fatal startup-adoption error.
* v281 all-account exit coverage still required verified entry price/auto-exit
  eligibility for rows explicitly marked ``exclude_from_auto_exit``.

v296 changes neither the dust threshold nor any position/cost-basis truth. It
only teaches those two consumers to honor the existing classification. A dust
row can satisfy *quantity snapshot adoption* without being represented as having
a verified cost basis, and v281 records that protective exits are not required
for that row instead of claiming protection exists.

The exact authoritative snapshot is captured from the same startup call; no
second broker read is introduced. Non-dust unresolved positions remain fail
closed. Snapshot mismatch, connectivity, broker errors, stale tracker rows,
writer, nonce, capital, risk, kill-switch, order, acknowledgement, and fill gates
remain unchanged.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
from collections.abc import Mapping
from functools import wraps
from typing import Any

LOGGER = logging.getLogger("nija.runtime_dust_position_policy_convergence_v296")
MARKER = "20260830-dust-position-policy-convergence-v296"
RELEASE_ID = "20260830-runtime-convergence-v296"
_READY_FLAG = "NIJA_RUNTIME_DUST_POSITION_POLICY_CONVERGENCE_V296_READY"
_ADOPTER_PATCH_ATTR = "_nija_dust_position_adopter_v296"
_AUDIT_PATCH_ATTR = "_nija_dust_position_audit_v296"
_LOCK = threading.RLock()


def _float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
        return default if number != number else number
    except Exception:
        return default


def _real_broker(broker: Any) -> Any:
    return getattr(broker, "_broker", broker)


def _normalise_symbol(value: Any) -> str:
    return str(value or "").strip().upper().replace("/", "-").replace("_", "-")


def _row_quantity(row: Mapping[str, Any]) -> float:
    for key in ("quantity", "qty", "amount", "size", "units", "balance"):
        if row.get(key) is not None:
            return _float(row.get(key))
    return 0.0


def _tracker_row(broker: Any, symbol: str) -> Mapping[str, Any] | None:
    real = _real_broker(broker)
    tracker = getattr(real, "position_tracker", None)
    getter = getattr(tracker, "get_position", None)
    if not callable(getter):
        return None
    try:
        row = getter(symbol)
    except Exception:
        return None
    return row if isinstance(row, Mapping) else None


def _is_policy_dust(row: Mapping[str, Any] | None) -> bool:
    if not isinstance(row, Mapping):
        return False
    return bool(
        str(row.get("classification", "") or "").strip().upper() == "DUST"
        and row.get("exclude_from_reconciliation") is True
        and row.get("exclude_from_auto_exit") is True
        and row.get("exclude_from_strategy") is True
        and row.get("exclude_from_position_limit") is True
    )


class _CapturePositionsProxy:
    """Capture the exact list returned to startup sync without extra broker I/O."""

    __slots__ = ("_broker", "_captured_rows")

    def __init__(self, broker: Any) -> None:
        object.__setattr__(self, "_broker", broker)
        object.__setattr__(self, "_captured_rows", None)

    def __getattr__(self, name: str) -> Any:
        return getattr(object.__getattribute__(self, "_broker"), name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name in {"_broker", "_captured_rows"}:
            object.__setattr__(self, name, value)
            return
        setattr(object.__getattribute__(self, "_broker"), name, value)

    def get_positions(self, *args: Any, **kwargs: Any) -> Any:
        target = object.__getattribute__(self, "_broker")
        rows = target.get_positions(*args, **kwargs)
        if isinstance(rows, list):
            object.__setattr__(self, "_captured_rows", rows)
        return rows

    def captured_rows(self) -> list[Any] | None:
        rows = object.__getattribute__(self, "_captured_rows")
        return rows if isinstance(rows, list) else None


def _kraken_authoritative_rows(broker: Any) -> list[Any] | None:
    """Use v286's already-captured exact Balance rows when its proxy hid our capture."""
    real = _real_broker(broker)
    try:
        generation = int(getattr(real, "_nija_authoritative_position_snapshot_generation_v285", 0) or 0)
        raw_generation = int(getattr(real, "_nija_authoritative_position_raw_generation_v286", -1) or -1)
        raw = getattr(real, "_nija_authoritative_position_raw_rows_v286", None)
    except Exception:
        return None
    if generation <= 0 or raw_generation != generation or not isinstance(raw, (tuple, list)):
        return None
    return list(raw)


def _apply_dust_adoption(broker: Any, rows: list[Any] | None, broker_name: str = "") -> bool:
    """Complete adoption only when every unresolved authoritative row is policy DUST."""
    real = _real_broker(broker)
    if getattr(real, "_startup_position_sync_adopted", None) is True:
        return True
    if not isinstance(rows, list) or not rows:
        return False

    try:
        already = {
            _normalise_symbol(value)
            for value in tuple(getattr(real, "_startup_position_sync_symbols", ()) or ())
            if _normalise_symbol(value)
        }
    except Exception:
        already = set()

    authoritative: list[str] = []
    dust: list[str] = []
    unresolved: list[str] = []
    invalid = False
    for raw in rows:
        if not isinstance(raw, Mapping):
            invalid = True
            continue
        symbol = _normalise_symbol(raw.get("symbol"))
        quantity = _row_quantity(raw)
        if not symbol or quantity <= 0.0:
            invalid = True
            continue
        authoritative.append(symbol)
        if symbol in already:
            continue
        tracked = _tracker_row(real, symbol)
        if _is_policy_dust(tracked):
            # Deliberately do not alter cost_basis_verified, entry_price, or
            # auto_exit_blocked. Dust is out of scope, not magically verified.
            dust.append(symbol)
            continue
        unresolved.append(symbol)

    if invalid or not authoritative or unresolved:
        return False
    if len(set(authoritative)) != len(authoritative):
        return False

    setattr(real, "_startup_position_sync_adopted", True)
    setattr(real, "_startup_position_sync_symbols", tuple(sorted(authoritative)))
    setattr(real, "_startup_position_sync_dust_symbols_v296", tuple(sorted(dust)))
    LOGGER.critical(
        "POSITION_SYNC_DUST_POLICY_V296_ADOPTED marker=%s broker=%s authoritative=%d verified=%d dust_excluded=%d dust_symbols=%s cost_basis_fabricated=false protective_exit_fabricated=false snapshot_success_fabricated=false dust_threshold_unchanged=true safety_gates_bypassed=false",
        MARKER,
        broker_name or str(getattr(real, "account_identifier", "unknown")),
        len(authoritative),
        len(already.intersection(authoritative)),
        len(dust),
        ",".join(sorted(dust)) or "none",
    )
    return True


def _chain_has_patch(callable_obj: Any, attr: str) -> bool:
    seen: set[int] = set()
    current = callable_obj
    for _ in range(128):
        if not callable(current) or id(current) in seen:
            return False
        seen.add(id(current))
        if bool(getattr(current, attr, False)):
            return True
        current = getattr(current, "__wrapped__", None)
    return False


def _patch_startup_adopter() -> bool:
    try:
        sync = importlib.import_module("bot.startup_position_sync")
    except Exception:
        return False
    current = getattr(sync, "_adopt_broker_positions", None)
    if not callable(current):
        return False
    if _chain_has_patch(current, _ADOPTER_PATCH_ATTR):
        return True
    original = current

    @wraps(original)
    def adopt_v296(broker: Any, broker_name: str, eps: Any) -> int:
        real = _real_broker(broker)
        capture = _CapturePositionsProxy(real)
        result = int(original(capture, broker_name, eps) or 0)
        if getattr(real, "_startup_position_sync_adopted", None) is True:
            return result
        rows = capture.captured_rows()
        if rows is None:
            rows = _kraken_authoritative_rows(real)
        _apply_dust_adoption(real, rows, broker_name)
        return result

    adopt_v296.__name__ = "adopt_v296"
    setattr(adopt_v296, _ADOPTER_PATCH_ATTR, True)
    setattr(adopt_v296, "__wrapped__", original)
    sync._adopt_broker_positions = adopt_v296
    return True


def _strip_dust_protection_reasons(
    broker: Any,
    reasons: list[str],
    positions: list[dict[str, Any]],
) -> tuple[list[str], list[dict[str, Any]], tuple[str, ...]]:
    """Remove only protection requirements the canonical dust policy declares N/A."""
    dust_symbols: set[str] = set()
    for row in positions:
        symbol = _normalise_symbol(row.get("symbol"))
        if not symbol:
            continue
        tracked = _tracker_row(broker, symbol)
        if not _is_policy_dust(tracked):
            continue
        dust_symbols.add(symbol)
        row["dust_excluded"] = True
        row["protective_exit_required"] = False
        row["protective_exit_verified"] = False
        row["coverage_basis"] = "dust_policy_not_actionable"

    if not dust_symbols:
        return list(dict.fromkeys(reasons)), positions, ()

    removable = {
        f"cost_basis_unverified:{symbol}" for symbol in dust_symbols
    } | {
        f"entry_price_unverified:{symbol}" for symbol in dust_symbols
    } | {
        f"auto_exit_blocked:{symbol}" for symbol in dust_symbols
    }
    filtered = [reason for reason in reasons if str(reason) not in removable]
    return list(dict.fromkeys(filtered)), positions, tuple(sorted(dust_symbols))


def _patch_v281_audit() -> bool:
    try:
        v281 = importlib.import_module("bot.runtime_all_account_position_exit_coverage_v281_patch")
    except Exception:
        return False
    current = getattr(v281, "_account_audit", None)
    if not callable(current):
        return False
    if _chain_has_patch(current, _AUDIT_PATCH_ATTR):
        return True
    original = current

    @wraps(original)
    def account_audit_v296(account: str, broker: Any, structural_exit_ready: bool):
        reasons, positions = original(account, broker, structural_exit_ready)
        reason_list = [str(value) for value in list(reasons or [])]
        position_list = [dict(row) for row in list(positions or []) if isinstance(row, Mapping)]
        filtered, enriched, dust = _strip_dust_protection_reasons(
            broker,
            reason_list,
            position_list,
        )
        if dust:
            LOGGER.info(
                "ALL_ACCOUNT_EXIT_DUST_POLICY_V296 marker=%s account=%s dust_symbols=%s protection_required=false cost_basis_verified_unchanged=true protective_exit_fabricated=false reporting_preserved=true",
                MARKER,
                account,
                ",".join(dust),
            )
        return filtered, enriched

    account_audit_v296.__name__ = "account_audit_v296"
    setattr(account_audit_v296, _AUDIT_PATCH_ATTR, True)
    setattr(account_audit_v296, "__wrapped__", original)
    v281._account_audit = account_audit_v296
    return True


def _register_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_dust_position_policy_convergence_v296"] = _READY_FLAG
        return True
    except Exception:
        return False


def reconcile_once() -> dict[str, Any]:
    adopter = _patch_startup_adopter()
    audit = _patch_v281_audit()
    return {
        "ready": bool(adopter and audit),
        "startup_adopter": bool(adopter),
        "exit_audit": bool(audit),
    }


def install() -> bool:
    with _LOCK:
        manifest = _register_manifest()
        adopter = _patch_startup_adopter()
        audit = _patch_v281_audit()
        ready = bool(manifest and adopter and audit)
        os.environ[_READY_FLAG] = "1" if ready else "0"
    log = LOGGER.critical if ready else LOGGER.error
    log(
        "RUNTIME_DUST_POSITION_POLICY_CONVERGENCE_V296_%s marker=%s ready=%s existing_dust_threshold_only=true startup_quantity_adoption_honors_dust=true all_account_exit_audit_honors_dust=true dust_reporting_preserved=true cost_basis_fabricated=false entry_price_fabricated=false protective_exit_fabricated=false dust_position_deleted=false forced_trade=false forced_activation=false writer_nonce_risk_capital_killswitch_order_fill_gates_unchanged=true safety_gates_bypassed=false",
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
    "reconcile_once",
    "_is_policy_dust",
    "_apply_dust_adoption",
    "_strip_dust_protection_reasons",
    "_patch_startup_adopter",
    "_patch_v281_audit",
]
