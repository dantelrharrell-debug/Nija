"""Coinbase protective-exit recovery v344.

Production on 2026-09-02 proved two independent exit-path faults after v343:

1. ``CoinbaseBroker.place_market_order`` sets ``base_increment = None`` before
   reading product metadata, then compares ``base_increment <= 0``.  When the
   Coinbase metadata response omits all increment fields this raises the exact
   production exception ``TypeError: '<=' not supported between instances of
   'NoneType' and 'int'`` before a protective BTC/ETH sell can complete.

2. Those deterministic local Python failures, plus a deterministic Kraken
   minimum-volume rejection, were recorded as exchange-health rejections and
   produced a 5/5 EXCHANGE_MONITOR kill-switch latch.  They are order-feasibility
   failures, not evidence that an exchange is unavailable or unhealthy.

v344 repairs both without weakening execution safety:

* Coinbase BTC/ETH product metadata is completed with the *existing* conservative
  fallback increments already encoded in ``CoinbaseBroker.place_market_order``
  (BTC=1e-8, ETH=1e-6) only when Coinbase provides no usable increment.  Real
  exchange metadata always wins.  No quantity is enlarged and all ordinary
  balance/minimum/ACK/fill gates remain in force.
* The exact local ``NoneType <= int`` signature, V341 pre-dispatch
  base/notional mismatch, and Kraken ``volume minimum not met`` feasibility
  response are excluded from the EXCHANGE-HEALTH rejection-rate sample while
  the orders themselves still fail closed.
* A one-time recovery may clear only the exact polluted 5/5 EXCHANGE_MONITOR
  latch observed in production, and only when the latest five provenance rows
  are all from the narrow deterministic allow-list and the existing v219 writer
  + structural readiness proofs are current.  Manual/UI/CLI, drawdown, risk,
  auth, unknown exchange rejects, broker outages and mixed samples are preserved.

No writer, nonce, capital, risk, kill-switch policy threshold, position-sync,
ECEL, broker-health, order ACK, confirmed-fill, or activation proof is fabricated.
"""
from __future__ import annotations

import importlib
import logging
import math
import os
import threading
import time
from collections import deque
from functools import wraps
from typing import Any, Mapping

LOGGER = logging.getLogger("nija.runtime_coinbase_exit_recovery_v344")
MARKER = "20260902-runtime-coinbase-exit-recovery-v344"
RELEASE_ID = "20260902-runtime-convergence-v344"
_READY_FLAG = "NIJA_RUNTIME_COINBASE_EXIT_RECOVERY_V344_READY"
_LOCK = threading.RLock()
_THREAD: threading.Thread | None = None
_RECOVERED = False
_META_PATCH_ATTR = "_nija_coinbase_exit_metadata_v344"
_CLASSIFIER_PATCH_ATTR = "_nija_exit_reject_classifier_v344"

_COINBASE_FALLBACK_INCREMENT = {
    "BTC": 0.00000001,
    "ETH": 0.000001,
}

_DETERMINISTIC_NON_HEALTH_MARKERS = (
    "typeerror: '<=' not supported between instances of 'nonetype' and 'int'",
    "v341 base_notional_mismatch",
    "egeneral:invalid arguments:volume minimum not met",
)


def _finite_positive(value: Any) -> bool:
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return False
    return math.isfinite(parsed) and parsed > 0.0


def _complete_coinbase_increment(symbol: str, metadata: Any) -> Any:
    """Return metadata with a proven BTC/ETH fallback only when API data is absent."""
    base = str(symbol or "").strip().upper().split("-", 1)[0]
    fallback = _COINBASE_FALLBACK_INCREMENT.get(base)
    if fallback is None:
        return metadata

    result = dict(metadata) if isinstance(metadata, Mapping) else {}
    candidates = (
        result.get("base_increment"),
        result.get("base_increment_decimal"),
        result.get("base_increment_value"),
    )
    if any(_finite_positive(value) for value in candidates):
        return metadata

    result["base_increment"] = fallback
    LOGGER.critical(
        "COINBASE_EXIT_V344_INCREMENT_FALLBACK marker=%s symbol=%s base=%s increment=%.12f "
        "api_increment_missing=true quantity_enlarged=false exchange_metadata_overridden=false "
        "minimum_order_gate_unchanged=true safety_gates_bypassed=false",
        MARKER, symbol, base, fallback,
    )
    return result


def _patch_coinbase_product_metadata() -> bool:
    module = importlib.import_module("bot.broker_manager")
    cls = getattr(module, "CoinbaseBroker", None)
    if not isinstance(cls, type):
        return False
    current = getattr(cls, "_get_product_metadata", None)
    if not callable(current):
        return False
    if bool(getattr(current, _META_PATCH_ATTR, False)):
        return True

    @wraps(current)
    def metadata_v344(self: Any, symbol: str, *args: Any, **kwargs: Any):
        value = current(self, symbol, *args, **kwargs)
        return _complete_coinbase_increment(symbol, value)

    setattr(metadata_v344, _META_PATCH_ATTR, True)
    setattr(metadata_v344, "__wrapped__", current)
    cls._get_product_metadata = metadata_v344
    return True


def _deterministic_non_health(reason: Any) -> bool:
    text = str(reason or "").strip().lower()
    return bool(text) and any(marker in text for marker in _DETERMINISTIC_NON_HEALTH_MARKERS)


def _patch_rejection_classifier() -> bool:
    module = importlib.import_module("bot.exchange_reject_dispatch_provenance_v228_patch")
    current = getattr(module, "_is_non_exchange_rejection", None)
    if not callable(current):
        return False
    if bool(getattr(current, _CLASSIFIER_PATCH_ATTR, False)):
        return True

    @wraps(current)
    def classifier_v344(reason: Any) -> bool:
        if _deterministic_non_health(reason):
            return True
        return bool(current(reason))

    setattr(classifier_v344, _CLASSIFIER_PATCH_ATTR, True)
    setattr(classifier_v344, "__wrapped__", current)
    module._is_non_exchange_rejection = classifier_v344
    return True


def _writer_and_structural_ready() -> tuple[bool, str]:
    try:
        v219 = importlib.import_module("bot.kill_switch_false_auth_recovery_v219_patch")
        writer = getattr(v219, "_writer_healthy", None)
        structural = getattr(v219, "_structural_readiness", None)
        if not callable(writer) or not callable(structural):
            return False, "v219_readiness_helpers_missing"
        writer_ok, writer_detail = writer()
        if not writer_ok:
            return False, f"writer:{writer_detail}"
        structural_ok, structural_detail = structural()
        if not structural_ok:
            return False, f"structural:{structural_detail}"
        return True, "writer_and_structural_current"
    except Exception as exc:
        return False, f"readiness_probe_error:{type(exc).__name__}:{exc}"


def _causal_record(status: Mapping[str, Any]) -> dict[str, Any]:
    try:
        v219 = importlib.import_module("bot.kill_switch_false_auth_recovery_v219_patch")
        helper = getattr(v219, "_causal_record", None)
        if callable(helper):
            value = helper(dict(status))
            if isinstance(value, dict):
                return value
    except Exception:
        pass
    history = list(status.get("recent_history") or [])
    for item in reversed(history):
        if not isinstance(item, dict):
            continue
        source = str(item.get("source") or "").strip()
        reason = str(item.get("reason") or "").strip()
        if source:
            return {"source": source, "reason": reason}
    return {}


def _exact_polluted_five_sample_latch(record: Mapping[str, Any]) -> bool:
    source = str(record.get("source") or "").strip().upper()
    reason = str(record.get("reason") or "").strip().lower()
    return bool(
        source == "EXCHANGE_MONITOR"
        and "order rejection rate 100.0%" in reason
        and "(5/5 orders rejected)" in reason
    )


def _latest_five_provenance(protector: Any) -> list[dict[str, Any]]:
    for attr in ("_nija_order_result_provenance_v258", "_nija_order_result_provenance_v256"):
        history = getattr(protector, attr, None)
        if isinstance(history, deque):
            rows = [dict(row) for row in list(history)[-5:] if isinstance(row, Mapping)]
            if len(rows) == 5:
                return rows
    return []


def _provenance_is_exactly_recoverable(rows: list[dict[str, Any]]) -> tuple[bool, str]:
    if len(rows) != 5:
        return False, "latest_five_provenance_missing"
    for index, row in enumerate(rows):
        if bool(row.get("accepted")):
            return False, f"accepted_sample_present:{index}"
        if str(row.get("source") or "").strip() != "execution_pipeline":
            return False, f"non_pipeline_source:{index}"
        reason = str(row.get("reason") or "")
        if not _deterministic_non_health(reason):
            return False, f"unknown_or_genuine_exchange_reject:{index}:{reason[:120]}"
    return True, "exact_deterministic_five_sample_pollution"


def attempt_polluted_latch_recovery_once() -> bool:
    """Clear only the exact known false EXCHANGE_MONITOR latch after hard proof."""
    global _RECOVERED
    if _RECOVERED:
        return False
    try:
        kill_module = importlib.import_module("bot.kill_switch")
        getter = getattr(kill_module, "get_kill_switch", None)
        ks = getter() if callable(getter) else None
        if ks is None or not callable(getattr(ks, "get_status", None)):
            return False
        status = dict(ks.get_status() or {})
        if not bool(status.get("is_active")):
            return False
        record = _causal_record(status)
        if not _exact_polluted_five_sample_latch(record):
            return False

        exchange_module = importlib.import_module("bot.exchange_kill_switch")
        protector_getter = getattr(exchange_module, "get_exchange_kill_switch_protector", None)
        protector = protector_getter() if callable(protector_getter) else None
        if protector is None:
            return False
        rows = _latest_five_provenance(protector)
        safe, detail = _provenance_is_exactly_recoverable(rows)
        if not safe:
            LOGGER.warning(
                "COINBASE_EXIT_V344_LATCH_RECOVERY_INELIGIBLE marker=%s detail=%s active_preserved=true",
                MARKER, detail,
            )
            return False

        ready, ready_detail = _writer_and_structural_ready()
        if not ready:
            LOGGER.warning(
                "COINBASE_EXIT_V344_LATCH_RECOVERY_WAIT marker=%s blocker=%s active_preserved=true",
                MARKER, ready_detail,
            )
            return False

        deactivate = getattr(ks, "deactivate", None)
        reset = getattr(protector, "reset", None)
        if not callable(deactivate) or not callable(reset):
            return False

        result = deactivate(
            "v344 verified recovery from polluted 5/5 deterministic exit-feasibility rejection latch"
        )
        if result is False:
            return False
        reset("v344 removed deterministic non-exchange-health exit rejection sample pollution")

        after = dict(ks.get_status() or {})
        if bool(after.get("is_active")) or bool(after.get("kill_file_exists")):
            LOGGER.critical(
                "COINBASE_EXIT_V344_LATCH_RECOVERY_VERIFY_FAILED marker=%s active=%s marker_exists=%s "
                "trading_fail_closed=true",
                MARKER, str(bool(after.get("is_active"))).lower(),
                str(bool(after.get("kill_file_exists"))).lower(),
            )
            return False

        _RECOVERED = True
        LOGGER.critical(
            "COINBASE_EXIT_V344_LATCH_RECOVERED marker=%s causal_source=EXCHANGE_MONITOR "
            "exact_five_sample_pollution=true writer_proof=exact structural_proofs=current "
            "protector_reset=true authority_nonce_execution_not_fabricated=true "
            "activation_must_reprove=true forced_activation=false safety_gates_bypassed=false",
            MARKER,
        )
        return True
    except Exception as exc:
        LOGGER.warning(
            "COINBASE_EXIT_V344_LATCH_RECOVERY_ERROR marker=%s err=%s:%s active_preserved=true trading_fail_closed=true",
            MARKER, type(exc).__name__, exc,
        )
        return False


def _register_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_coinbase_exit_recovery_v344"] = _READY_FLAG
        return True
    except Exception:
        return False


def _worker() -> None:
    while True:
        try:
            _patch_coinbase_product_metadata()
            _patch_rejection_classifier()
            attempt_polluted_latch_recovery_once()
        except Exception:
            LOGGER.debug("V344 worker pulse failed", exc_info=True)
        time.sleep(2.0)


def install_import_hook() -> bool:
    global _THREAD
    with _LOCK:
        metadata_ready = classifier_ready = manifest_ready = False
        try:
            metadata_ready = bool(_patch_coinbase_product_metadata())
            classifier_ready = bool(_patch_rejection_classifier())
            manifest_ready = bool(_register_manifest())
        except Exception as exc:
            LOGGER.exception(
                "RUNTIME_COINBASE_EXIT_RECOVERY_V344_INSTALL_ERROR marker=%s error=%s:%s fail_closed=true",
                MARKER, type(exc).__name__, exc,
            )
        ready = bool(metadata_ready and classifier_ready and manifest_ready)
        os.environ[_READY_FLAG] = "1" if ready else "0"
        if ready and (_THREAD is None or not _THREAD.is_alive()):
            _THREAD = threading.Thread(target=_worker, name="CoinbaseExitRecoveryV344", daemon=True)
            _THREAD.start()
        log = LOGGER.critical if ready else LOGGER.error
        log(
            "RUNTIME_COINBASE_EXIT_RECOVERY_V344_%s marker=%s ready=%s "
            "coinbase_missing_increment_repaired=%s deterministic_reject_provenance=%s manifest=%s "
            "quantity_enlarged=false rejection_thresholds_unchanged=true kill_switch_generic_autoclear=false "
            "writer_nonce_capital_risk_position_sync_ecel_broker_health_ack_fill_gates_unchanged=true "
            "execution_proof_fabricated=false forced_activation=false safety_gates_bypassed=false",
            "READY" if ready else "NOT_READY", MARKER, str(ready).lower(),
            str(metadata_ready).lower(), str(classifier_ready).lower(), str(manifest_ready).lower(),
        )
        return ready


def install() -> bool:
    return install_import_hook()


__all__ = [
    "MARKER", "RELEASE_ID", "install", "install_import_hook",
    "_complete_coinbase_increment", "_deterministic_non_health",
    "_provenance_is_exactly_recoverable", "attempt_polluted_latch_recovery_once",
]
