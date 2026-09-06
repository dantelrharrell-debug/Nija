"""Kraken margin full stop-loss/take-profit protection truth v371.

Production evidence on 2026-09-06 showed the authenticated Kraken ETH margin
position was visible and the dedicated software exit monitor had exact-broker hard
exit authority, but v367 still allowed ``protective_exit_verified=true`` when no
native take-profit order existed.  The software margin row also derived only a
stop-loss, so the existing exit scanner had no explicit take-profit price to test.

v371 closes that gap without creating orders or weakening terminal execution gates:

* every authenticated Kraken margin scanner row reuses NIJA's existing hard-loss
  policy for ``stop_loss`` and the existing v239 0.5% / 1% / 2% profit ladder for
  ``take_profit_1`` / ``take_profit_2`` / ``take_profit_3``;
* software protection is accepted only when the dedicated monitor is live, exact
  broker hard-exit authority is already proven by v368, authenticated position ids
  identify the remaining Kraken margin position, and both stop and take-profit
  thresholds are present;
* canonical margin coverage is fail-closed unless a stop path AND a take-profit
  path cover the same authenticated remaining position.  Native and software
  components may be combined, but stop-only or take-profit-only can never certify
  the position as fully protected;
* the patch changes protection truth and scanner inputs only.  v364 remaining
  quantity caps and all writer/nonce/kill-switch/risk/broker-health/terminal submit
  gates remain authoritative.

Profit is not guaranteed.  This patch only makes the configured protective-exit
policy observable, internally consistent, and fail-closed.
"""
from __future__ import annotations

import importlib
import logging
import math
import os
import threading
from collections.abc import Mapping
from functools import wraps
from typing import Any

LOGGER = logging.getLogger("nija.runtime_kraken_margin_full_protection_v371")
MARKER = "20260905-runtime-kraken-margin-full-protection-v371"
RELEASE_ID = "20260905-runtime-convergence-v371"
_READY_FLAG = "NIJA_RUNTIME_KRAKEN_MARGIN_FULL_PROTECTION_V371_READY"
_PATCH_ATTR = "_nija_v371_kraken_margin_full_protection"
_LOCK = threading.RLock()
_EPS = 1e-12


def _f(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
        return parsed if math.isfinite(parsed) else default
    except (TypeError, ValueError, OverflowError):
        return default


def _v239():
    return importlib.import_module("bot.runtime_all_account_profit_targets_v239_patch")


def _v365():
    return importlib.import_module("bot.runtime_kraken_margin_protective_scan_v365_patch")


def _v366():
    return importlib.import_module("bot.runtime_kraken_margin_canonical_coverage_v366_patch")


def _v367():
    return importlib.import_module("bot.runtime_kraken_margin_protection_truth_v367_patch")


def _position_ids(row: Mapping[str, Any]) -> tuple[str, ...]:
    raw = row.get("position_ids")
    values: list[str] = []
    if isinstance(raw, (tuple, list, set)):
        values.extend(str(value).strip() for value in raw if str(value).strip())
    if not values:
        single = str(row.get("position_id") or "").strip()
        if single:
            values.extend(part.strip() for part in single.split(",") if part.strip())
    return tuple(sorted(dict.fromkeys(values)))


def _has_take_profit(row: Mapping[str, Any]) -> bool:
    return any(
        _f(row.get(key)) > _EPS
        for key in ("take_profit_1", "take_profit_2", "take_profit_3", "take_profit")
    )


def _ensure_software_targets(raw: Any) -> Any:
    """Attach NIJA's existing stop and profit ladder to one margin row.

    No target is invented outside existing NIJA policy.  Missing stop values use
    v367's hard-loss calculation; missing profit values use v239's established
    target synthesizer.  Existing explicit values are preserved by both helpers.
    """
    if not isinstance(raw, Mapping):
        return raw
    row = dict(raw)
    if not bool(row.get("kraken_margin_openpositions") is True or row.get("margin_position") is True):
        return row

    entry = max(0.0, _f(row.get("entry_price", row.get("avg_entry_price"))))
    quantity = max(0.0, _f(row.get("quantity", row.get("qty"))))
    ids = _position_ids(row)
    identity_verified = bool(entry > _EPS and quantity > _EPS and ids)
    row["position_ids"] = ids
    if ids:
        row["position_id"] = ",".join(ids)
    row["protection_position_ids"] = ids
    row["software_protection_identity_verified"] = identity_verified

    if entry > _EPS and quantity > _EPS and _f(row.get("stop_loss")) <= _EPS:
        pct_fn = getattr(_v367(), "_effective_stop_loss_pct", None)
        pct = max(0.0, _f(pct_fn(row) if callable(pct_fn) else 0.0))
        if pct > 0.0:
            row["stop_loss"] = entry * (1.0 - pct)
            row["risk_stop_loss_pct"] = pct
            row["risk_stop_loss_source"] = "existing_nija_hard_loss_policy"
            row["software_stop_loss_derived"] = True

    before_tp = _has_take_profit(row)
    target_fn = getattr(_v239(), "_with_profit_targets", None)
    if callable(target_fn) and entry > _EPS and quantity > _EPS:
        targeted = target_fn(row)
        if isinstance(targeted, Mapping):
            row = dict(targeted)
    after_tp = _has_take_profit(row)
    if after_tp and not before_tp:
        row["software_take_profit_derived"] = True
        row["software_take_profit_source"] = "all_account_profit_targets_v239"

    stop_available = _f(row.get("stop_loss")) > _EPS
    tp_available = _has_take_profit(row)
    row["software_stop_loss_available"] = stop_available
    row["software_take_profit_available"] = tp_available
    row["software_protection_targets_complete"] = bool(identity_verified and stop_available and tp_available)
    return row


def _patch_margin_scanner_rows() -> bool:
    v365 = _v365()
    current = getattr(v365, "_openposition_rows", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True

    @wraps(current)
    def rows_v371(broker: Any):
        rows, reason = current(broker)
        if reason != "ok":
            return rows, reason
        hardened = [_ensure_software_targets(row) for row in list(rows or [])]
        for row in hardened:
            if not isinstance(row, Mapping) or row.get("kraken_margin_openpositions") is not True:
                continue
            LOGGER.critical(
                "KRAKEN_MARGIN_SCANNER_PROTECTION_V371 marker=%s symbol=%s quantity=%.12f "
                "position_ids=%s stop_loss=%.8f take_profit_1=%.8f take_profit_2=%.8f "
                "take_profit_3=%.8f identity_verified=%s targets_complete=%s "
                "order_submitted=false safety_gates_bypassed=false",
                MARKER,
                str(row.get("symbol") or "unknown"),
                _f(row.get("quantity")),
                row.get("position_ids", ()),
                _f(row.get("stop_loss")),
                _f(row.get("take_profit_1")),
                _f(row.get("take_profit_2")),
                _f(row.get("take_profit_3")),
                str(bool(row.get("software_protection_identity_verified"))).lower(),
                str(bool(row.get("software_protection_targets_complete"))).lower(),
            )
        return hardened, reason

    setattr(rows_v371, _PATCH_ATTR, True)
    setattr(rows_v371, "__wrapped__", current)
    v365._openposition_rows = rows_v371
    return True


def _patch_margin_coverage_truth() -> bool:
    v366 = _v366()
    current = getattr(v366, "margin_coverage_rows", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True

    @wraps(current)
    def coverage_v371(account: str, broker: Any):
        rows, reasons = current(account, broker)
        reasons = [str(reason) for reason in list(reasons or []) if str(reason)]
        hardened: list[dict[str, Any]] = []

        for raw in list(rows or []):
            row = _ensure_software_targets(raw)
            if not isinstance(row, Mapping):
                continue
            row = dict(row)
            if row.get("margin_position") is not True:
                hardened.append(row)
                continue

            symbol = v366.canonical_symbol(row.get("symbol"))
            identity_verified = bool(row.get("software_protection_identity_verified"))
            native_stop = bool(row.get("native_stop_loss_verified"))
            native_tp = bool(row.get("native_take_profit_verified"))
            software_monitor = bool(row.get("software_exit_monitor_verified"))
            software_stop = bool(
                software_monitor and identity_verified and row.get("software_stop_loss_available")
            )
            software_tp = bool(
                software_monitor and identity_verified and row.get("software_take_profit_available")
            )

            stop_verified = bool(native_stop or software_stop)
            take_profit_verified = bool(native_tp or software_tp)
            verified = bool(identity_verified and stop_verified and take_profit_verified)

            if verified and native_stop and native_tp:
                mode = "native_exchange_stop_take_profit"
            elif verified and software_stop and software_tp and not native_stop and not native_tp:
                mode = "software_margin_monitor_stop_take_profit"
            elif verified:
                mode = "hybrid_native_software_stop_take_profit"
            else:
                mode = "unverified"

            attached: list[str] = []
            if native_stop:
                attached.append("native_stop_loss")
            if native_tp:
                attached.append("native_take_profit")
            if software_stop:
                attached.append("kraken_margin_software_stop_loss")
            if software_tp:
                attached.append("kraken_margin_software_take_profit")
            if software_monitor and identity_verified:
                attached.append("kraken_margin_software_exit_monitor")

            generic_reason = f"kraken_margin_protective_exit_unverified:{symbol}"
            reasons = [reason for reason in reasons if reason != generic_reason]
            if not verified:
                reasons.append(generic_reason)
            if not identity_verified:
                reasons.append(f"kraken_margin_position_identity_unverified:{symbol}")
            if not stop_verified:
                reasons.append(f"kraken_margin_stop_loss_unverified:{symbol}")
            if not take_profit_verified:
                reasons.append(f"kraken_margin_take_profit_unverified:{symbol}")

            row["software_stop_loss_verified"] = software_stop
            row["software_take_profit_verified"] = software_tp
            row["protective_position_identity_verified"] = identity_verified
            row["protective_stop_verified"] = stop_verified
            row["protective_take_profit_verified"] = take_profit_verified
            row["protective_exit_verified"] = verified
            row["protective_exit_mode"] = mode
            row["exit_protections_attached"] = tuple(dict.fromkeys(attached))
            hardened.append(row)

            LOGGER.critical(
                "KRAKEN_MARGIN_FULL_PROTECTION_V371 marker=%s account=%s symbol=%s quantity=%.12f "
                "position_ids=%s identity_verified=%s native_stop=%s native_take_profit=%s "
                "software_monitor=%s software_stop=%s software_take_profit=%s "
                "stop_verified=%s take_profit_verified=%s protective_exit_verified=%s mode=%s "
                "full_remaining_position_required=true terminal_submit_gates_preserved=true "
                "safety_gates_bypassed=false",
                MARKER, account, symbol, _f(row.get("quantity")), row.get("position_ids", ()),
                str(identity_verified).lower(), str(native_stop).lower(), str(native_tp).lower(),
                str(software_monitor).lower(), str(software_stop).lower(), str(software_tp).lower(),
                str(stop_verified).lower(), str(take_profit_verified).lower(), str(verified).lower(), mode,
            )

        deduped = list(dict.fromkeys(reason for reason in reasons if reason))
        return hardened, deduped

    setattr(coverage_v371, _PATCH_ATTR, True)
    setattr(coverage_v371, "__wrapped__", current)
    v366.margin_coverage_rows = coverage_v371
    return True


def _register_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_kraken_margin_full_protection_v371"] = _READY_FLAG
        return True
    except Exception:
        return False


def _wake_coverage() -> None:
    try:
        v281 = importlib.import_module("bot.runtime_all_account_position_exit_coverage_v281_patch")
        audit = getattr(v281, "audit_once", None)
        if callable(audit):
            audit()
    except Exception:
        LOGGER.debug("v371 coverage wake deferred", exc_info=True)


def install_import_hook() -> bool:
    with _LOCK:
        try:
            if os.environ.get("NIJA_RUNTIME_KRAKEN_MARGIN_PROTECTION_TRUTH_V367_READY") != "1":
                raise RuntimeError("v367_not_ready")
            target_fn = getattr(_v239(), "_with_profit_targets", None)
            target_values = getattr(_v239(), "_targets", None)
            if not callable(target_fn) or not callable(target_values):
                raise RuntimeError("v239_profit_target_policy_unavailable")
            scanner = _patch_margin_scanner_rows()
            coverage = _patch_margin_coverage_truth()
            manifest = _register_manifest()
            ready = bool(scanner and coverage and manifest)
        except Exception as exc:
            ready = False
            LOGGER.exception(
                "RUNTIME_KRAKEN_MARGIN_FULL_PROTECTION_V371_INSTALL_FAILED marker=%s error=%s:%s "
                "trading_fail_closed=true existing_exits_preserved=true safety_gates_bypassed=false",
                MARKER, type(exc).__name__, exc,
            )

        os.environ[_READY_FLAG] = "1" if ready else "0"
        log = LOGGER.critical if ready else LOGGER.error
        log(
            "RUNTIME_KRAKEN_MARGIN_FULL_PROTECTION_V371_%s marker=%s ready=%s "
            "stop_and_take_profit_both_required=true exact_openposition_ids_required=true "
            "software_stop_existing_hard_loss_policy=true software_take_profit_existing_v239_policy=true "
            "tp1_default_pct=0.005 tp2_default_pct=0.010 tp3_default_pct=0.020 "
            "stop_only_not_protected=true take_profit_only_not_protected=true "
            "v364_terminal_remaining_quantity_cap_unchanged=true writer_nonce_killswitch_risk_broker_health_terminal_gates_unchanged=true "
            "forced_trade=false forced_exit=false execution_proof_fabricated=false safety_gates_bypassed=false",
            "READY" if ready else "NOT_READY", MARKER, str(ready).lower(),
        )
        if ready:
            _wake_coverage()
        return ready


def install() -> bool:
    return install_import_hook()


__all__ = [
    "MARKER", "RELEASE_ID", "install", "install_import_hook",
    "_ensure_software_targets", "_patch_margin_scanner_rows", "_patch_margin_coverage_truth",
]
