"""Admit fresh Kraken capital observations without re-waiting the full runtime budget.

Production on 2026-08-21 showed a remaining liveness gap after v173: Kraken could
finish a genuine platform balance read and leave a fresh, sequence-fenced v35
observation, while the next proactive publication cycle still waited the full
30-second synchronous fetch budget before consulting that same observation.
During that wait the last canonical publication remained 2/3 and execution
correctly stayed fail closed.

v174 changes only the timing of an already-authorized fallback decision:

* only proactive runtime publication refreshes are eligible;
* only the canonical ``kraken`` broker is eligible;
* only a positive v35 observation that is still inside both the canonical
  freshness TTL and a stricter proactive cache-admission age may fast-path;
* the existing v37 ``_handle_failure`` path performs the actual admission, so
  fallback provenance, observation timestamp, sequence fencing, and v166
  computed-at capping remain authoritative;
* the live Kraken balance worker is not cancelled. It continues asynchronously
  and may refresh the observation for a later cycle.

This patch does not extend freshness/publication expiry, accept a partial
snapshot, fabricate capital, bypass v162 sequence fencing, change risk limits,
force activation/trading, or grant writer/nonce/execution authority.
"""
from __future__ import annotations

import importlib
import logging
import math
import os
import threading
import time
from functools import wraps
from typing import Any, Optional

LOGGER = logging.getLogger("nija.runtime_kraken_capital_observation_admission_v174")
MARKER = "20260821-runtime-kraken-capital-observation-admission-v174"
_READY_FLAG = "NIJA_RUNTIME_KRAKEN_CAPITAL_OBSERVATION_ADMISSION_V174_READY"
_PATCH_ATTR = "_nija_runtime_kraken_capital_observation_admission_v174"
_LOCK = threading.RLock()
_DEFAULT_MAX_AGE_S = 30.0


def _guard() -> Any:
    return importlib.import_module("bot.capital_refresh_stall_guard_v35")


def _v166() -> Any:
    return importlib.import_module("bot.runtime_capital_refresh_ownership_v166_patch")


def _is_proactive_trigger() -> bool:
    try:
        checker = getattr(_v166(), "_is_proactive_trigger", None)
        return bool(checker()) if callable(checker) else False
    except Exception:
        return False


def _freshness_ttl_seconds(guard: Any | None = None) -> float:
    target = guard if guard is not None else _guard()
    try:
        getter = getattr(target, "_freshness_ttl_seconds", None)
        if callable(getter):
            return max(5.0, float(getter()))
    except Exception:
        pass
    return 90.0


def _max_admission_age_seconds(guard: Any | None = None) -> float:
    """Use a stricter-than-TTL age for the no-wait admission fast path."""
    ttl_s = _freshness_ttl_seconds(guard)
    try:
        proactive_budget = float(_v166()._proactive_fetch_budget_seconds())
    except Exception:
        proactive_budget = _DEFAULT_MAX_AGE_S
    try:
        requested = float(
            os.environ.get(
                "NIJA_KRAKEN_CAPITAL_OBSERVATION_FASTPATH_MAX_AGE_S",
                str(_DEFAULT_MAX_AGE_S),
            )
            or _DEFAULT_MAX_AGE_S
        )
    except (TypeError, ValueError):
        requested = _DEFAULT_MAX_AGE_S
    return max(1.0, min(requested, proactive_budget, ttl_s))


def _coerce_positive(value: Any) -> Optional[float]:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(result) or result <= 0.0:
        return None
    return result


def _read_fresh_observation(
    guard: Any,
    broker_id: str,
    *,
    now_mono: float | None = None,
) -> tuple[Any | None, float]:
    """Return a positive, sequence-fenced v35 observation inside fast-path age."""
    bid = str(broker_id or "").strip().lower()
    if bid != "kraken":
        return None, float("inf")

    observations = getattr(guard, "_OBSERVATIONS", None)
    lock = getattr(guard, "_OBSERVATION_LOCK", None)
    if not isinstance(observations, dict):
        return None, float("inf")

    def read() -> Any:
        return observations.get(bid)

    if lock is None:
        observation = read()
    else:
        with lock:
            observation = read()
    if observation is None:
        return None, float("inf")

    value = _coerce_positive(getattr(observation, "value", None))
    try:
        observed_mono = float(getattr(observation, "observed_monotonic", 0.0) or 0.0)
    except (TypeError, ValueError, OverflowError):
        observed_mono = 0.0
    if value is None or observed_mono <= 0.0:
        return None, float("inf")

    now = time.monotonic() if now_mono is None else float(now_mono)
    age_s = max(0.0, now - observed_mono)
    if age_s > _max_admission_age_seconds(guard):
        return None, age_s
    return observation, age_s


def _patch_batch_result() -> bool:
    guard = _guard()
    batch_cls = getattr(guard, "_BalanceFetchBatch", None)
    if not isinstance(batch_cls, type):
        return False
    current = getattr(batch_cls, "result_for", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True
    if not callable(getattr(batch_cls, "_handle_failure", None)):
        return False

    original = current

    @wraps(original)
    def result_for_v174(self: Any, broker_id: str, broker: Any) -> Any:
        bid = str(broker_id or "").strip().lower()
        if bid == "kraken" and _is_proactive_trigger():
            resolved = getattr(self, "_nija_v37_resolved", {})
            if bid not in resolved:
                observation, age_s = _read_fresh_observation(guard, bid)
                if observation is not None:
                    value = self._handle_failure(
                        bid,
                        "v174_proactive_fresh_observation",
                    )
                    scalar = _coerce_positive(value)
                    if scalar is not None:
                        LOGGER.critical(
                            "CAPITAL_V174_KRAKEN_OBSERVATION_ADMITTED marker=%s broker=kraken "
                            "balance=%.8f age_s=%.2f sequence=%s proactive=true "
                            "synchronous_wait_bypassed=true source=v35_fenced_observation "
                            "fallback_timestamp_preserved=true freshness_extended=false "
                            "partial_aggregation_gate_unchanged=true safety_gates_bypassed=false",
                            MARKER,
                            scalar,
                            age_s,
                            getattr(observation, "sequence", "unknown"),
                        )
                        return value
        return original(self, broker_id, broker)

    setattr(result_for_v174, _PATCH_ATTR, True)
    setattr(result_for_v174, "__wrapped__", original)
    batch_cls.result_for = result_for_v174
    return True


def _patch_release_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_kraken_capital_observation_admission_v174"] = _READY_FLAG
        return True
    except Exception:
        return False


def install() -> bool:
    with _LOCK:
        batch_ok = _patch_batch_result()
        manifest_ok = _patch_release_manifest()
        ready = bool(batch_ok and manifest_ok)
        os.environ[_READY_FLAG] = "1" if ready else "0"
        if not ready:
            LOGGER.critical(
                "RUNTIME_KRAKEN_CAPITAL_OBSERVATION_ADMISSION_V174_FAILED marker=%s "
                "batch_ok=%s manifest_ok=%s trading_fail_closed=true",
                MARKER,
                str(batch_ok).lower(),
                str(manifest_ok).lower(),
            )
            return False

        LOGGER.critical(
            "RUNTIME_KRAKEN_CAPITAL_OBSERVATION_ADMISSION_V174 marker=%s ready=true "
            "proactive_kraken_only=true max_fastpath_age_s=%.1f "
            "v37_fallback_authoritative=true v162_sequence_fence_preserved=true "
            "fallback_timestamp_preserved=true freshness_extended=false "
            "partial_aggregation_gate_unchanged=true forced_trade=false safety_gates_bypassed=false",
            MARKER,
            _max_admission_age_seconds(),
        )
        return True


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "install",
    "install_import_hook",
    "_max_admission_age_seconds",
    "_read_fresh_observation",
    "_patch_batch_result",
]
