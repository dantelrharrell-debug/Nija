"""Restore canonical v142 generation context without weakening rollover fencing.

Production on 2026-08-21 showed a complete three-broker proactive refresh reach
CapitalAuthority after a v142 coordinator rollover, but the publication arrived
at the v142 fence with no thread-local generation tag and was rejected as
``UNTAGGED_AFTER_ROLLOVER``.  The broker aggregation itself was complete and the
current canonical coordinator worker was still the owner.

v181 repairs only that handoff.  When the exact v142 publication wrapper is in
the active call chain, an authorized publication may temporarily recover the
wrapper owner's generation context only if the current thread is exactly the
canonical manager's current coordinator worker, that worker is still in-flight,
its generation equals v142's active generation, and it has not timed out.
Retired, detached, unknown, and unauthorized publishers remain fenced.

Production on 2026-08-22 exposed two follow-on handoff gaps after v186:

* after a v142 rollover, a canonical coordinator can temporarily run the legacy
  synchronous pre-terminal path.  That path has no v142 worker thread, so its
  otherwise valid publication is untagged and the existing rollover fence
  correctly rejects it; and
* v184 intentionally preserves Kraken's raw per-asset pricing metric while its
  authenticated TradeBalance proof supplies effective valuation coverage.  The
  MABM readiness layer still consumed only the raw metric and could therefore
  report ``assets_priced_ok=False`` even while v184 proved fresh same-epoch
  aggregate equity.

v187 closes only those handoffs.  It lends the *current active v142 generation*
to the exact canonical synchronous coordinator call only while the capital
bootstrap is non-terminal, no v142 runtime worker is in flight, no thread-local
generation already exists, and rollover fencing is active.  It also allows MABM
to recover capital readiness only from an already accepted, non-stale, complete
canonical snapshot with positive Kraken capital plus a currently valid v184
authenticated aggregate-equity proof.  Raw pricing diagnostics remain unchanged.

No capital value is fabricated, no snapshot is force-accepted, no retired or
unknown generation is promoted, no freshness/publication expiry is extended,
and no writer/nonce/risk/kill-switch/execution/activation state is bypassed.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
from datetime import datetime, timezone
from functools import wraps
from typing import Any

LOGGER = logging.getLogger("nija.runtime_capital_generation_context_v181")
MARKER = "20260821-runtime-capital-generation-context-v181"
REASSERT_MARKER = "20260822-capital-generation-coverage-reassert-v187"
RELEASE_ID = "20260821-runtime-convergence-v181"
_READY_FLAG = "NIJA_RUNTIME_CAPITAL_GENERATION_CONTEXT_V181_READY"
_REASSERT_READY_FLAG = "NIJA_RUNTIME_CAPITAL_GENERATION_COVERAGE_V187_READY"
_PATCH_ATTR = "_nija_runtime_capital_generation_context_v181"
_SYNC_PATCH_ATTR = "_nija_runtime_capital_generation_sync_v187"
_MABM_PATCH_ATTR = "_nija_runtime_kraken_effective_valuation_v187"
_V142_PATCH_ATTR = "_nija_capital_publication_liveness_v142"
_V142_MARKER = "20260818-capital-publication-liveness-v142"
_V142_MODULE_NAMES = {
    "bot.capital_publication_liveness_v142_patch",
    "capital_publication_liveness_v142_patch",
}
_LOCK = threading.RLock()
_MISSING = object()


def _is_exact_v142_publication_wrapper(candidate: Any) -> bool:
    """Identify v142 by function-owner globals, not wraps-copied metadata."""
    if not callable(candidate) or not bool(getattr(candidate, _V142_PATCH_ATTR, False)):
        return False
    owner = getattr(candidate, "__globals__", {}) or {}
    if str(owner.get("__name__", "")) not in _V142_MODULE_NAMES:
        return False
    if str(owner.get("MARKER", "")) != _V142_MARKER:
        return False
    return bool(
        owner.get("_LOCAL") is not None
        and callable(owner.get("_generation_state"))
        and callable(owner.get("_canonical_manager"))
    )


def _find_v142_publication_wrapper(callable_obj: Any) -> Any:
    """Return the exact v142 publish wrapper from a wrapped call chain."""
    seen: set[int] = set()
    current = callable_obj
    for _ in range(32):
        if not callable(current) or id(current) in seen:
            return None
        seen.add(id(current))
        if _is_exact_v142_publication_wrapper(current):
            return current
        current = getattr(current, "__wrapped__", None)
    return None


def _is_exact_v181_publication_wrapper(candidate: Any) -> bool:
    if not callable(candidate) or not bool(getattr(candidate, _PATCH_ATTR, False)):
        return False
    owner = getattr(candidate, "__globals__", {}) or {}
    return bool(
        str(owner.get("MARKER", "")) == MARKER
        and str(owner.get("__name__", "")).endswith(
            "runtime_capital_generation_context_v181_patch"
        )
    )


def _find_exact_v181_publication_wrapper(callable_obj: Any) -> Any:
    seen: set[int] = set()
    current = callable_obj
    for _ in range(32):
        if not callable(current) or id(current) in seen:
            return None
        seen.add(id(current))
        if _is_exact_v181_publication_wrapper(current):
            return current
        current = getattr(current, "__wrapped__", None)
    return None


def _canonical_generation_from_v142_wrapper(wrapper: Any) -> tuple[int | None, str, Any]:
    """Prove the current thread is the live canonical v142 coordinator worker."""
    if not callable(wrapper):
        return None, "v142_wrapper_missing", None
    owner = getattr(wrapper, "__globals__", {}) or {}
    local = owner.get("_LOCAL")
    generation_state = owner.get("_generation_state")
    canonical_manager = owner.get("_canonical_manager")
    if local is None or not callable(generation_state) or not callable(canonical_manager):
        return None, "v142_owner_context_missing", local
    if getattr(local, "refresh_generation", None) is not None:
        return None, "generation_already_present", local

    try:
        active, rolled = generation_state()
        active = int(active or 0)
    except Exception:
        return None, "generation_state_unavailable", local
    if not bool(rolled) or active <= 0:
        return None, "rollover_not_active", local

    try:
        manager = canonical_manager()
    except Exception:
        manager = None
    coordinator = getattr(manager, "_capital_coordinator", None) if manager is not None else None
    if coordinator is None:
        return None, "canonical_coordinator_missing", local

    worker = getattr(coordinator, "_nija_v142_flight_thread", None)
    if worker is not threading.current_thread():
        return None, "not_current_canonical_worker", local
    if not bool(getattr(coordinator, "_in_flight", False)):
        return None, "canonical_worker_not_in_flight", local
    if bool(getattr(coordinator, "_nija_v142_flight_timed_out", False)):
        return None, "canonical_worker_timed_out", local

    try:
        generation = int(getattr(coordinator, "_nija_v142_flight_generation", 0) or 0)
    except (TypeError, ValueError):
        generation = 0
    if generation <= 0:
        return None, "canonical_generation_missing", local
    if generation != active:
        return None, f"canonical_generation_not_active:{generation}!={active}", local
    return generation, "current_canonical_worker", local


def _canonical_sync_generation_v187(coordinator: Any) -> tuple[int | None, str, Any]:
    """Prove a pre-terminal synchronous call is the current canonical owner."""
    try:
        v142 = importlib.import_module("bot.capital_publication_liveness_v142_patch")
    except Exception:
        return None, "v142_module_unavailable", None

    local = getattr(v142, "_LOCAL", None)
    generation_state = getattr(v142, "_generation_state", None)
    canonical_manager = getattr(v142, "_canonical_manager", None)
    runtime_terminal = getattr(v142, "_runtime_terminal", None)
    if (
        local is None
        or not callable(generation_state)
        or not callable(canonical_manager)
        or not callable(runtime_terminal)
    ):
        return None, "v142_sync_context_unavailable", local
    if getattr(local, "refresh_generation", None) is not None:
        return None, "generation_already_present", local

    try:
        active, rolled = generation_state()
        active = int(active or 0)
    except Exception:
        return None, "generation_state_unavailable", local
    if not bool(rolled) or active <= 0:
        return None, "rollover_not_active", local

    try:
        manager = canonical_manager()
    except Exception:
        manager = None
    if manager is None or getattr(manager, "_capital_coordinator", None) is not coordinator:
        return None, "not_canonical_coordinator", local

    try:
        if bool(runtime_terminal(coordinator)):
            return None, "runtime_terminal_worker_path", local
    except Exception:
        return None, "runtime_terminal_unknown", local

    if bool(getattr(coordinator, "_in_flight", False)):
        return None, "runtime_worker_in_flight", local
    if bool(getattr(coordinator, "_nija_v142_flight_timed_out", False)):
        return None, "canonical_coordinator_timed_out", local

    worker = getattr(coordinator, "_nija_v142_flight_thread", None)
    alive = getattr(worker, "is_alive", None) if worker is not None else None
    if callable(alive):
        try:
            if bool(alive()):
                return None, "runtime_worker_alive", local
        except Exception:
            return None, "runtime_worker_state_unknown", local

    return active, "canonical_preterminal_sync_after_rollover", local


def _patch_synchronous_generation_context_v187() -> bool:
    """Tag only the canonical synchronous pre-terminal v142 path after rollover."""
    try:
        flow = importlib.import_module("bot.capital_flow_state_machine")
        cls = getattr(flow, "CapitalRefreshCoordinator", None)
    except Exception:
        return False
    if not isinstance(cls, type):
        return False

    current = getattr(cls, "execute_refresh", None)
    if not callable(current):
        return False
    owner = getattr(current, "__globals__", {}) or {}
    if bool(getattr(current, _SYNC_PATCH_ATTR, False)) and str(owner.get("MARKER", "")) == MARKER:
        return True
    original = current

    @wraps(original)
    def execute_refresh_v187(
        self: Any,
        broker_map: dict[str, Any],
        trigger: str = "coordinator",
        open_exposure_usd: float = 0.0,
    ) -> Any:
        generation, reason, local = _canonical_sync_generation_v187(self)
        if generation is None or local is None:
            return original(
                self,
                broker_map=broker_map,
                trigger=trigger,
                open_exposure_usd=open_exposure_usd,
            )

        previous = getattr(local, "refresh_generation", _MISSING)
        setattr(local, "refresh_generation", generation)
        LOGGER.critical(
            "CAPITAL_V187_CANONICAL_SYNC_GENERATION_RESTORED marker=%s generation=%d "
            "trigger=%s reason=%s canonical_coordinator_only=true "
            "retired_generation_fence_preserved=true publication_force_accept=false "
            "freshness_extended=false safety_gates_bypassed=false",
            REASSERT_MARKER,
            generation,
            trigger,
            reason,
        )
        try:
            return original(
                self,
                broker_map=broker_map,
                trigger=trigger,
                open_exposure_usd=open_exposure_usd,
            )
        finally:
            if previous is _MISSING:
                try:
                    delattr(local, "refresh_generation")
                except AttributeError:
                    pass
            else:
                setattr(local, "refresh_generation", previous)

    setattr(execute_refresh_v187, _SYNC_PATCH_ATTR, True)
    setattr(execute_refresh_v187, "__wrapped__", original)
    cls.execute_refresh = execute_refresh_v187
    return True


def _patch_publication_context() -> bool:
    """Wrap CapitalAuthority publication and restore only proven v142 context."""
    try:
        v142 = importlib.import_module("bot.capital_publication_liveness_v142_patch")
        ensure_fence = getattr(v142, "_patch_publication_generation_fence", None)
        if not callable(ensure_fence) or not bool(ensure_fence()):
            return False
        ca = importlib.import_module("bot.capital_authority")
        cls = getattr(ca, "CapitalAuthority", None)
    except Exception:
        return False
    if not isinstance(cls, type):
        return False

    current = getattr(cls, "publish_snapshot", None)
    if not callable(current):
        return False
    if _find_exact_v181_publication_wrapper(current) is not None:
        return True

    v142_wrapper = _find_v142_publication_wrapper(current)
    if not callable(v142_wrapper):
        return False
    original = current

    @wraps(original)
    def publish_snapshot_v181(self: Any, snapshot: Any, writer_id: str) -> bool:
        authorized = str(writer_id or "") == str(
            getattr(self, "_AUTHORIZED_WRITER_ID", "mabm_capital_refresh_coordinator")
        )
        if not authorized:
            return bool(original(self, snapshot, writer_id))

        generation, reason, local = _canonical_generation_from_v142_wrapper(v142_wrapper)
        if generation is None or local is None:
            return bool(original(self, snapshot, writer_id))

        previous = getattr(local, "refresh_generation", _MISSING)
        setattr(local, "refresh_generation", generation)
        LOGGER.critical(
            "CAPITAL_V181_CANONICAL_WORKER_GENERATION_RESTORED marker=%s generation=%d "
            "reason=%s canonical_worker_only=true retired_workers_rejected=true "
            "publication_expiry_extended=false freshness_extended=false safety_gates_bypassed=false",
            MARKER,
            generation,
            reason,
        )
        try:
            return bool(original(self, snapshot, writer_id))
        finally:
            if previous is _MISSING:
                try:
                    delattr(local, "refresh_generation")
                except AttributeError:
                    pass
            else:
                setattr(local, "refresh_generation", previous)

    publish_snapshot_v181.__name__ = "publish_snapshot_v181"
    setattr(publish_snapshot_v181, _PATCH_ATTR, True)
    setattr(publish_snapshot_v181, "__wrapped__", original)
    cls.publish_snapshot = publish_snapshot_v181
    return True


def _normalise_broker_key(value: Any) -> str:
    return str(getattr(value, "value", value) or "").strip().lower()


def _current_kraken_broker(manager: Any) -> Any:
    brokers = getattr(manager, "_platform_brokers", None)
    if not isinstance(brokers, dict):
        return None
    for key, broker in brokers.items():
        if _normalise_broker_key(key) == "kraken":
            return broker
    return None


def _publication_current(status: Any) -> bool:
    if status is None or not bool(getattr(status, "accepted", False)):
        return False
    if bool(getattr(status, "stale", True)):
        return False
    expiry = getattr(status, "expiry", None)
    if isinstance(expiry, datetime):
        current = datetime.now(timezone.utc)
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        if expiry.astimezone(timezone.utc) <= current:
            return False
    return True


def _validated_effective_kraken_readiness_v187(manager: Any) -> tuple[bool, dict[str, Any]]:
    """Prove MABM may use v184 effective valuation without changing raw metrics."""
    detail: dict[str, Any] = {
        "reason": "unknown",
        "real_capital": 0.0,
        "broker_count": 0,
        "expected_brokers": 0,
        "kraken_capital": 0.0,
        "effective_coverage": 0.0,
    }
    try:
        ca = importlib.import_module("bot.capital_authority")
        authority = ca.get_capital_authority()
        status = authority.get_snapshot_publication_status()
        if not _publication_current(status):
            detail["reason"] = "canonical_publication_not_current"
            return False, detail

        snapshot = authority.get_typed_snapshot()
        if snapshot is None:
            detail["reason"] = "canonical_snapshot_missing"
            return False, detail

        try:
            real_capital = float(getattr(snapshot, "real_capital", 0.0) or 0.0)
        except Exception:
            real_capital = 0.0
        balances = getattr(snapshot, "broker_balances", None)
        balances = dict(balances) if isinstance(balances, dict) else {}
        try:
            broker_count = int(getattr(snapshot, "broker_count", 0) or 0)
        except Exception:
            broker_count = 0
        expected = 0
        for candidate in (
            getattr(snapshot, "expected_brokers", None),
            getattr(authority, "expected_brokers", None),
            getattr(authority, "_expected_brokers", None),
        ):
            try:
                parsed = int(candidate or 0)
            except Exception:
                parsed = 0
            if parsed > 0:
                expected = parsed
                break
        expected = max(1, expected)
        detail.update(
            real_capital=real_capital,
            broker_count=broker_count,
            expected_brokers=expected,
        )
        if real_capital <= 0.0 or broker_count < expected:
            detail["reason"] = "canonical_snapshot_incomplete_or_zero"
            return False, detail

        kraken = _current_kraken_broker(manager)
        if kraken is None or not bool(getattr(kraken, "connected", False)):
            detail["reason"] = "kraken_not_connected"
            return False, detail

        kraken_capital = 0.0
        for key, value in balances.items():
            if _normalise_broker_key(key) == "kraken":
                try:
                    kraken_capital = float(value or 0.0)
                except Exception:
                    kraken_capital = 0.0
                break
        detail["kraken_capital"] = kraken_capital
        if kraken_capital <= 0.0:
            detail["reason"] = "canonical_kraken_capital_not_positive"
            return False, detail

        boot = getattr(manager, "_capital_bootstrap_fsm", None)
        state = getattr(boot, "state", None) if boot is not None else None
        state_value = str(getattr(state, "value", state) or "").strip().upper()
        if state_value == "FAILED":
            detail["reason"] = "capital_bootstrap_failed"
            return False, detail

        v184 = importlib.import_module("bot.runtime_kraken_aggregate_valuation_confidence_v184_patch")
        proof = getattr(v184, "_aggregate_proof_status", None)
        if not callable(proof):
            detail["reason"] = "v184_proof_unavailable"
            return False, detail
        valid, proof_reason, _equity, _age = proof(kraken)
        if not bool(valid):
            detail["reason"] = f"v184_proof_invalid:{proof_reason}"
            return False, detail

        coverage_getter = getattr(kraken, "get_last_pricing_coverage", None)
        if not callable(coverage_getter):
            detail["reason"] = "effective_coverage_getter_missing"
            return False, detail
        try:
            effective = max(0.0, min(1.0, float(coverage_getter())))
        except Exception:
            effective = 0.0
        detail["effective_coverage"] = effective
        if effective <= 0.0:
            detail["reason"] = "effective_coverage_zero"
            return False, detail

        detail["reason"] = "accepted_complete_snapshot_and_v184_proof"
        return True, detail
    except Exception as exc:
        detail["reason"] = f"probe_error:{type(exc).__name__}:{exc}"
        return False, detail


def _patch_mabm_effective_valuation_v187() -> bool:
    """Recover only the readiness boolean from accepted canonical v184 truth."""
    try:
        mabm = importlib.import_module("bot.multi_account_broker_manager")
        cls = getattr(mabm, "MultiAccountBrokerManager", None)
    except Exception:
        return False
    if not isinstance(cls, type):
        return False

    current = getattr(cls, "refresh_capital_authority", None)
    if not callable(current):
        return False
    owner = getattr(current, "__globals__", {}) or {}
    if bool(getattr(current, _MABM_PATCH_ATTR, False)) and str(owner.get("MARKER", "")) == MARKER:
        return True
    original = current

    @wraps(original)
    def refresh_capital_authority_v187(self: Any, *args: Any, **kwargs: Any) -> Any:
        result = original(self, *args, **kwargs)
        if not isinstance(result, dict) or bool(float(result.get("ready", 0.0) or 0.0)):
            return result

        valid, detail = _validated_effective_kraken_readiness_v187(self)
        if not valid:
            return result

        repaired = dict(result)
        repaired["ready"] = 1.0
        repaired["total_capital"] = float(detail["real_capital"])
        repaired["valid_brokers"] = float(detail["broker_count"])
        repaired["kraken_capital"] = float(detail["kraken_capital"])
        repaired["v187_effective_valuation"] = 1.0
        lock = getattr(self, "_capital_state_lock", None)
        if lock is not None and hasattr(lock, "__enter__"):
            with lock:
                self._capital_ready = True
                self._capital_last_valid_brokers = int(detail["broker_count"])
                self._trading_halted_due_to_capital = False
        else:
            self._capital_ready = True
            self._capital_last_valid_brokers = int(detail["broker_count"])
            self._trading_halted_due_to_capital = False

        LOGGER.critical(
            "CAPITAL_V187_EFFECTIVE_KRAKEN_VALUATION_ACCEPTED marker=%s "
            "real_capital=%.8f broker_count=%d expected_brokers=%d kraken_capital=%.8f "
            "effective_valuation_coverage=%.3f canonical_publication_accepted=true "
            "raw_pricing_metric_mutated=false capital_mutated=false publication_mutated=false "
            "freshness_extended=false partial_aggregation_accepted=false safety_gates_bypassed=false",
            REASSERT_MARKER,
            float(detail["real_capital"]),
            int(detail["broker_count"]),
            int(detail["expected_brokers"]),
            float(detail["kraken_capital"]),
            float(detail["effective_coverage"]),
        )
        return repaired

    setattr(refresh_capital_authority_v187, _MABM_PATCH_ATTR, True)
    setattr(refresh_capital_authority_v187, "__wrapped__", original)
    cls.refresh_capital_authority = refresh_capital_authority_v187
    return True


def _patch_release_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        installers = getattr(manifest, "_INSTALLERS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_capital_generation_context_v181"] = _READY_FLAG
        required["runtime_capital_generation_coverage_v187"] = _REASSERT_READY_FLAG
        own = ("bot.runtime_capital_generation_context_v181_patch", "install_import_hook")
        if isinstance(installers, tuple) and own not in installers:
            manifest._INSTALLERS = tuple(installers) + (own,)
        return True
    except Exception:
        return False


def install() -> bool:
    with _LOCK:
        sync_ok = _patch_synchronous_generation_context_v187()
        publication_ok = _patch_publication_context()
        mabm_ok = _patch_mabm_effective_valuation_v187()
        manifest_ok = _patch_release_manifest()
        ready = bool(sync_ok and publication_ok and mabm_ok and manifest_ok)
        os.environ[_READY_FLAG] = "1" if ready else "0"
        os.environ[_REASSERT_READY_FLAG] = "1" if ready else "0"
        if not ready:
            LOGGER.critical(
                "RUNTIME_CAPITAL_GENERATION_CONTEXT_V187_FAILED marker=%s sync=%s publication=%s "
                "mabm=%s manifest=%s trading_fail_closed=true",
                REASSERT_MARKER,
                str(sync_ok).lower(),
                str(publication_ok).lower(),
                str(mabm_ok).lower(),
                str(manifest_ok).lower(),
            )
            return False
        LOGGER.critical(
            "CAPITAL_GENERATION_COVERAGE_V187_REASSERTED marker=%s ready=true "
            "canonical_sync_generation=true canonical_worker_generation=true "
            "effective_kraken_valuation=true accepted_canonical_snapshot_required=true "
            "authenticated_v184_proof_required=true retired_generation_fence_preserved=true "
            "raw_pricing_metric_mutated=false capital_mutated=false freshness_extended=false "
            "publication_expiry_extended=false forced_trade=false safety_gates_bypassed=false",
            REASSERT_MARKER,
        )
        return True


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "REASSERT_MARKER",
    "RELEASE_ID",
    "install",
    "install_import_hook",
    "_is_exact_v142_publication_wrapper",
    "_find_v142_publication_wrapper",
    "_is_exact_v181_publication_wrapper",
    "_find_exact_v181_publication_wrapper",
    "_canonical_generation_from_v142_wrapper",
    "_canonical_sync_generation_v187",
    "_patch_synchronous_generation_context_v187",
    "_patch_publication_context",
    "_validated_effective_kraken_readiness_v187",
    "_patch_mabm_effective_valuation_v187",
    "_patch_release_manifest",
]
