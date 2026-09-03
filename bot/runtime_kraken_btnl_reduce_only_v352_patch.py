"""Kraken U.S. retail reduce-only Bitnomial routing convergence v352.

Fresh Render evidence on 2026-09-03 showed five genuine Kraken rejections for
XETHZUSD SELL with ``EOrder:Reduce only:Non-ECP``. Kraken documents this exact
error for U.S. retail leveraged orders routed through a standard pair instead
of the Bitnomial execution pair, which requires a ``:BTNL`` suffix.

v352 does not assume every Kraken account is U.S. retail. It preserves the
existing first submission. Only when Kraken explicitly returns the exact
Non-ECP reduce-only routing rejection for a leveraged reduce-only AddOrder does
NIJA retry the same rejected order once with the canonical Bitnomial pair.
Because the first order was rejected by Kraken, the retry cannot duplicate a
fill from that first attempt.

No kill switch or rejection window is cleared. No ACK is treated as a fill.
Unknown/existing exchange failures remain unchanged and fail closed. Writer,
nonce, risk, capital, position-sync, ECEL, minimum-order, broker-health,
quantity, ACK and confirmed-fill gates are unchanged.
"""
from __future__ import annotations

import importlib
import logging
import os
import sys
import threading
from functools import wraps
from types import ModuleType
from typing import Any, Mapping, Optional

LOGGER = logging.getLogger("nija.runtime_kraken_btnl_reduce_only_v352")
MARKER = "20260903-runtime-kraken-btnl-reduce-only-v352"
RELEASE_ID = "20260903-runtime-convergence-v352"
_READY_FLAG = "NIJA_RUNTIME_KRAKEN_BTNL_REDUCE_ONLY_V352_READY"
_PATCH_ATTR = "_nija_v352_kraken_btnl_reduce_only_retry"
_LOCK = threading.RLock()
_NON_ECP = "eorder:reduce only:non-ecp"


def _error_text(value: Any) -> str:
    if isinstance(value, Mapping):
        raw = value.get("error")
        if isinstance(raw, (list, tuple, set)):
            return " | ".join(str(item) for item in raw)
        return str(raw or value.get("message") or "")
    if isinstance(value, (list, tuple, set)):
        return " | ".join(str(item) for item in value)
    return str(value or "")


def _is_non_ecp_reduce_only(value: Any) -> bool:
    return _NON_ECP in _error_text(value).strip().lower()


def _margin_scope() -> Mapping[str, Any]:
    try:
        v223 = importlib.import_module("bot.kraken_margin_auto_runtime_patch")
        scoped = getattr(v223, "_MARGIN_ORDER_PARAMS").get()
        return dict(scoped or {}) if isinstance(scoped, Mapping) else {}
    except Exception:
        return {}


def _is_target_addorder(method: Any, payload: Mapping[str, Any]) -> bool:
    if str(method or "").strip().lower() != "addorder":
        return False
    scoped = _margin_scope()
    try:
        leverage = int(float(scoped.get("leverage") or payload.get("leverage") or 1))
    except Exception:
        leverage = 1
    reduce_only = bool(scoped.get("reduce_only")) or payload.get("reduce_only") in (
        True, 1, "1", "true", "True",
    )
    return leverage > 1 and reduce_only


def _canonical_standard_pair(pair: Any) -> str:
    raw = str(pair or "").strip()
    if not raw:
        return ""
    if raw.upper().endswith(":BTNL"):
        return raw[:-5]
    try:
        v261 = importlib.import_module("bot.runtime_kraken_terminal_symbol_canonicalization_v261_patch")
        canonical = str(v261._canonical_terminal_symbol(raw) or "").strip()
    except Exception:
        canonical = raw
    if "/" in canonical:
        return canonical
    if "-" in canonical:
        parts = canonical.split("-")
        if len(parts) == 2 and all(parts):
            return f"{parts[0]}/{parts[1]}"
    # Do not guess unknown compact pair ids. v261 owns the proven legacy-id map.
    return ""


def _btnl_pair(pair: Any) -> str:
    raw = str(pair or "").strip()
    if raw.upper().endswith(":BTNL"):
        return raw
    standard = _canonical_standard_pair(raw)
    return f"{standard}:BTNL" if standard else ""


def _retry_payload(payload: Mapping[str, Any]) -> Optional[dict[str, Any]]:
    routed = _btnl_pair(payload.get("pair"))
    current = str(payload.get("pair") or "").strip()
    if not routed or routed == current:
        return None
    retry = dict(payload)
    retry["pair"] = routed
    return retry


def _patch_kraken_class(cls: type) -> bool:
    current = getattr(cls, "_kraken_private_call", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True
    original = current

    @wraps(original)
    def private_call_v352(
        self: Any,
        method: str,
        params: Optional[dict[str, Any]] = None,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        payload = dict(params or {})
        if not _is_target_addorder(method, payload):
            return original(self, method, payload, *args, **kwargs)

        try:
            first = original(self, method, payload, *args, **kwargs)
        except Exception as exc:
            if not _is_non_ecp_reduce_only(exc):
                raise
            retry = _retry_payload(payload)
            if retry is None:
                raise
            LOGGER.critical(
                "KRAKEN_BTNL_V352_ROUTE_RETRY marker=%s account=%s pair_before=%s pair_after=%s "
                "reason=EOrder:Reduce_only:Non-ECP first_exchange_rejected=true "
                "duplicate_fill_possible=false retry_once=true kill_switch_cleared=false "
                "rejection_window_cleared=false safety_gates_bypassed=false",
                MARKER,
                str(getattr(self, "account_identifier", None) or getattr(self, "account_id", None) or "unknown"),
                str(payload.get("pair") or ""),
                str(retry.get("pair") or ""),
            )
            return original(self, method, retry, *args, **kwargs)

        if not _is_non_ecp_reduce_only(first):
            return first

        retry = _retry_payload(payload)
        if retry is None:
            return first
        LOGGER.critical(
            "KRAKEN_BTNL_V352_ROUTE_RETRY marker=%s account=%s pair_before=%s pair_after=%s "
            "reason=EOrder:Reduce_only:Non-ECP first_exchange_rejected=true "
            "duplicate_fill_possible=false retry_once=true kill_switch_cleared=false "
            "rejection_window_cleared=false safety_gates_bypassed=false",
            MARKER,
            str(getattr(self, "account_identifier", None) or getattr(self, "account_id", None) or "unknown"),
            str(payload.get("pair") or ""),
            str(retry.get("pair") or ""),
        )
        return original(self, method, retry, *args, **kwargs)

    setattr(private_call_v352, _PATCH_ATTR, True)
    setattr(private_call_v352, "__wrapped__", original)
    cls._kraken_private_call = private_call_v352
    return True


def _patch_loaded_kraken_identities() -> bool:
    outcomes: list[bool] = []
    seen: set[int] = set()
    for name in (
        "bot.broker_manager",
        "broker_manager",
        "bot.broker_integration",
        "broker_integration",
    ):
        module = sys.modules.get(name)
        if not isinstance(module, ModuleType):
            try:
                module = importlib.import_module(name)
            except Exception:
                continue
        for attr in dir(module):
            cls = getattr(module, attr, None)
            if not isinstance(cls, type) or "kraken" not in attr.lower():
                continue
            if id(cls) in seen:
                continue
            seen.add(id(cls))
            if callable(getattr(cls, "_kraken_private_call", None)):
                outcomes.append(_patch_kraken_class(cls))
    return bool(outcomes) and all(outcomes)


def _register_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_kraken_btnl_reduce_only_v352"] = _READY_FLAG
        return True
    except Exception:
        return False


def install_import_hook() -> bool:
    with _LOCK:
        identities = manifest = False
        try:
            identities = _patch_loaded_kraken_identities()
            manifest = _register_manifest()
        except Exception as exc:
            LOGGER.exception(
                "RUNTIME_KRAKEN_BTNL_REDUCE_ONLY_V352_INSTALL_ERROR marker=%s error=%s:%s fail_closed=true",
                MARKER, type(exc).__name__, exc,
            )
        ready = bool(identities and manifest)
        os.environ[_READY_FLAG] = "1" if ready else "0"
        log = LOGGER.critical if ready else LOGGER.error
        log(
            "RUNTIME_KRAKEN_BTNL_REDUCE_ONLY_V352_%s marker=%s ready=%s "
            "kraken_private_identities=%s manifest=%s exact_non_ecp_retry_only=true "
            "btnl_pair_not_guessed=true retry_once=true first_order_rejected_required=true "
            "kill_switch_unchanged=true rejection_window_unchanged=true explicit_other_rejections_unchanged=true "
            "ack_not_fill=true confirmed_fill_required=true forced_trade=false forced_activation=false "
            "writer_nonce_risk_capital_position_sync_ecel_minimum_broker_health_quantity_order_ack_fill_gates_unchanged=true "
            "safety_gates_bypassed=false",
            "READY" if ready else "NOT_READY",
            MARKER,
            str(ready).lower(),
            str(identities).lower(),
            str(manifest).lower(),
        )
        return ready


def install() -> bool:
    return install_import_hook()


__all__ = [
    "MARKER",
    "RELEASE_ID",
    "install",
    "install_import_hook",
    "_btnl_pair",
    "_is_non_ecp_reduce_only",
    "_patch_kraken_class",
]
