"""Admit current authenticated Kraken aggregate equity into capital refresh v227.

Production on 2026-08-24 showed a contradictory same-process capital epoch:
Kraken's authenticated TradeBalance proof reported positive equivalent equity,
while the bounded capital batch returned a scalar zero and v37 therefore marked
Kraken ``include=false reason=zero_balance``.  The canonical 3/3 publisher then
rejected the snapshot as 2/3 even though the exact Kraken broker had a fresh,
same-epoch authenticated aggregate-equity proof.

v227 repairs only that representation handoff.  If, and only if, the bounded
capital result for the exact Kraken broker is zero, v184's existing
``_aggregate_proof_status`` re-validates a positive authenticated TradeBalance
``eb`` against the exact broker instance, canonical freshness TTL, balance
observation epoch, error count, availability and broker health.  A valid proof
is returned as the bounded broker's current balance and the same-cycle guard
provenance is updated to that exact value/timestamp.

Positive ordinary broker results are untouched.  Missing, stale, mismatched,
error, unavailable or non-Kraken observations remain fail closed.  This patch
does not extend freshness, synthesize capital, alter broker-count thresholds,
clear a kill switch, mark readiness, grant execution authority, or force trade.
"""
from __future__ import annotations

import builtins
import importlib
import logging
import math
import os
import sys
import time
from functools import wraps
from types import ModuleType
from typing import Any, Callable

LOGGER = logging.getLogger("nija.runtime_kraken_capital_admission_v227")
MARKER = "20260824-runtime-kraken-capital-admission-v227"
_READY_FLAG = "NIJA_RUNTIME_KRAKEN_CAPITAL_ADMISSION_V227_READY"
_PATCH_ATTR = "_nija_runtime_kraken_capital_admission_v227"
_IMPORT_HOOK_ATTR = "_NIJA_RUNTIME_KRAKEN_CAPITAL_ADMISSION_V227_IMPORT_HOOK"

_GUARD_NAMES = (
    "nija_capital_refresh_stall_guard_v35_prebot",
    "bot.capital_refresh_stall_guard_v35",
    "capital_refresh_stall_guard_v35",
)
_TARGET_SUFFIXES = (
    "capital_refresh_stall_guard_v35",
    "capital_refresh_sticky_success_v37_patch",
    "runtime_kraken_aggregate_valuation_confidence_v184_patch",
    "runtime_release_manifest_patch",
)


def _scalar(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(parsed) or parsed < 0.0:
        return None
    return parsed


def _canonical_guard() -> ModuleType | None:
    for name in _GUARD_NAMES:
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            return module
    return None


def _validated_kraken_equity(broker: Any) -> tuple[bool, float, float, str]:
    """Return a current v184-authenticated equity proof for this exact broker."""
    try:
        v184 = importlib.import_module(
            "bot.runtime_kraken_aggregate_valuation_confidence_v184_patch"
        )
        checker = getattr(v184, "_aggregate_proof_status", None)
        if not callable(checker):
            return False, 0.0, 0.0, "v184_status_checker_missing"
        valid, reason, equity, proof_age = checker(broker)
        equity_value = float(equity or 0.0)
        if not bool(valid) or not math.isfinite(equity_value) or equity_value <= 0.0:
            return False, 0.0, 0.0, str(reason or "aggregate_proof_invalid")
        proof_ts = float(
            getattr(broker, "_nija_v184_tradebalance_equity_ts", 0.0) or 0.0
        )
        if proof_ts <= 0.0:
            return False, 0.0, 0.0, "aggregate_proof_timestamp_missing"
        return True, equity_value, proof_ts, str(reason or "authenticated_tradebalance_equity")
    except Exception as exc:
        return False, 0.0, 0.0, f"v184_status_error:{type(exc).__name__}:{exc}"


def _publish_same_cycle_provenance(
    guard: ModuleType,
    batch: Any,
    equity: float,
    proof_ts: float,
) -> None:
    """Replace only the current Kraken zero observation with the validated eb."""
    now_epoch = time.time()
    now_mono = time.monotonic()
    proof_age = max(0.0, now_epoch - float(proof_ts))
    observed_mono = max(0.0, now_mono - proof_age)

    refresh = getattr(guard, "_REFRESH_CONTEXT", None)
    live = dict(getattr(refresh, "live_brokers", {}) or {}) if refresh is not None else {}
    existing = dict(live.get("kraken", {}) or {})
    sequence = int(
        existing.get("sequence")
        or getattr(guard, "_BROKER_SEQUENCE", {}).get("kraken", 0)
        or 0
    )
    live["kraken"] = {
        "value": float(equity),
        "observed_monotonic": observed_mono,
        "observed_epoch": float(proof_ts),
        "sequence": sequence,
        "source": "authenticated_tradebalance_equity_v227",
    }
    if refresh is not None:
        refresh.live_brokers = live
        excluded = dict(getattr(refresh, "excluded_brokers", {}) or {})
        excluded.pop("kraken", None)
        refresh.excluded_brokers = excluded

    observations = getattr(guard, "_OBSERVATIONS", None)
    observation_cls = getattr(guard, "_Observation", None)
    observation_lock = getattr(guard, "_OBSERVATION_LOCK", None)
    if isinstance(observations, dict) and observation_cls is not None:
        try:
            observation = observation_cls(
                value=float(equity),
                observed_monotonic=observed_mono,
                observed_epoch=float(proof_ts),
                sequence=sequence,
            )
        except TypeError:
            observation = observation_cls(
                float(equity), observed_mono, float(proof_ts), sequence
            )
        if observation_lock is None:
            observations["kraken"] = observation
        else:
            with observation_lock:
                observations["kraken"] = observation

    resolved = getattr(batch, "_nija_v37_resolved", None)
    resolved_lock = getattr(batch, "_nija_v37_lock", None)
    if isinstance(resolved, dict):
        if resolved_lock is None:
            resolved["kraken"] = float(equity)
        else:
            with resolved_lock:
                resolved["kraken"] = float(equity)

    v37 = sys.modules.get("bot.capital_refresh_sticky_success_v37_patch") or sys.modules.get(
        "capital_refresh_sticky_success_v37_patch"
    )
    decision = getattr(v37, "_decision", None) if isinstance(v37, ModuleType) else None
    if callable(decision):
        try:
            decision("kraken", True, "authenticated_tradebalance_equity_v227")
        except Exception:
            pass


def _patch_loaded_guard() -> bool:
    guard = _canonical_guard()
    if guard is None:
        return False
    batch_cls = getattr(guard, "_BalanceFetchBatch", None)
    if not isinstance(batch_cls, type):
        return False
    current = getattr(batch_cls, "result_for", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True

    @wraps(current)
    def result_for_v227(self: Any, broker_id: str, broker: Any) -> Any:
        result = current(self, broker_id, broker)
        bid = str(getattr(broker_id, "value", broker_id) or "").strip().lower()
        if bid != "kraken":
            return result
        current_value = _scalar(result)
        if current_value is None or current_value > 0.0:
            return result

        valid, equity, proof_ts, reason = _validated_kraken_equity(broker)
        if not valid:
            LOGGER.warning(
                "KRAKEN_CAPITAL_ADMISSION_V227_PRESERVED_ZERO marker=%s reason=%s "
                "authenticated_equity_admitted=false capital_fabricated=false trading_fail_closed=true",
                MARKER,
                reason,
            )
            return result

        _publish_same_cycle_provenance(guard, self, equity, proof_ts)
        LOGGER.critical(
            "KRAKEN_CAPITAL_ADMISSION_V227_APPLIED marker=%s broker=kraken "
            "bounded_result_before=0.0 authenticated_eb=%.8f proof_timestamp=%.6f "
            "proof_reason=%s exact_broker_instance=true same_epoch_v184_required=true "
            "capital_fabricated=false freshness_extended=false broker_threshold_unchanged=true "
            "kill_switch_unchanged=true readiness_fabricated=false execution_authority_granted=false "
            "forced_trade=false safety_gates_bypassed=false",
            MARKER,
            equity,
            proof_ts,
            reason,
        )
        return float(equity)

    setattr(result_for_v227, _PATCH_ATTR, True)
    setattr(result_for_v227, "__wrapped__", current)
    batch_cls.result_for = result_for_v227
    return bool(getattr(batch_cls.result_for, _PATCH_ATTR, False))


def _register_manifest_if_loaded() -> bool:
    manifest = sys.modules.get("bot.runtime_release_manifest_patch")
    if not isinstance(manifest, ModuleType):
        return True
    required = getattr(manifest, "_REQUIRED_FLAGS", None)
    installers = getattr(manifest, "_INSTALLERS", None)
    if not isinstance(required, dict):
        return False
    required["runtime_kraken_capital_admission_v227"] = _READY_FLAG
    own = ("bot.runtime_kraken_capital_admission_v227_patch", "install_import_hook")
    if isinstance(installers, tuple) and own not in installers:
        manifest._INSTALLERS = tuple(installers) + (own,)
    return True


def _install_import_hook() -> bool:
    if bool(getattr(builtins, _IMPORT_HOOK_ATTR, False)):
        return True
    original_import: Callable[..., Any] = builtins.__import__

    def guarded_import(name: str, globals: Any = None, locals: Any = None, fromlist: Any = (), level: int = 0) -> Any:
        module = original_import(name, globals, locals, fromlist, level)
        imported = str(name or "")
        if imported.endswith(_TARGET_SUFFIXES):
            try:
                _patch_loaded_guard()
                _register_manifest_if_loaded()
            except Exception as exc:
                LOGGER.warning(
                    "KRAKEN_CAPITAL_ADMISSION_V227_REASSERT_ERROR marker=%s imported=%s err=%s:%s "
                    "trading_fail_closed=true",
                    MARKER,
                    imported,
                    type(exc).__name__,
                    exc,
                )
        return module

    builtins.__import__ = guarded_import
    setattr(builtins, _IMPORT_HOOK_ATTR, True)
    return True


def install() -> bool:
    hook_ok = _install_import_hook()
    guard = _canonical_guard()
    patch_ok = _patch_loaded_guard() if guard is not None else True
    manifest_ok = _register_manifest_if_loaded()
    ready = bool(hook_ok and patch_ok and manifest_ok)
    os.environ[_READY_FLAG] = "1" if ready else "0"
    if not ready:
        LOGGER.critical(
            "KRAKEN_CAPITAL_ADMISSION_V227_FAILED marker=%s hook=%s patch=%s manifest=%s "
            "trading_fail_closed=true",
            MARKER,
            str(hook_ok).lower(),
            str(patch_ok).lower(),
            str(manifest_ok).lower(),
        )
        return False
    LOGGER.critical(
        "KRAKEN_CAPITAL_ADMISSION_V227_READY marker=%s ready=true "
        "zero_result_only=true authenticated_v184_equity_required=true exact_broker_instance=true "
        "same_epoch_required=true freshness_ttl_unchanged=true positive_results_unchanged=true "
        "capital_fabricated=false kill_switch_unchanged=true readiness_fabricated=false "
        "execution_authority_granted=false forced_trade=false safety_gates_bypassed=false",
        MARKER,
    )
    return True


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "install",
    "install_import_hook",
    "_validated_kraken_equity",
    "_publish_same_cycle_provenance",
    "_patch_loaded_guard",
]
