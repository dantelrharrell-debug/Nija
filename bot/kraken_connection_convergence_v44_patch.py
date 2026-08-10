"""NIJA Kraken connection convergence v44 with post-v59 convergence v60.

v44 keeps Kraken's canonical platform connection recoverable without ever
fabricating a successful connection.  It reuses the authenticated recovery path
from canonical_broker_startup_convergence_v24 and remains writer-scoped.

Production after the v59 writer-first merge exposed two additional state-split
failures that are repaired here as v60:

* The entrypoint writer can continue renewing the exact Redis lock while the
  process-local v17 renewal timestamp becomes stale.  v40 then correctly fails
  closed, but authority can remain blocked even though Redis still proves the
  same live writer.  v60 may re-anchor only the *local renewal timestamp*, and
  only after an exact, read-only Redis proof of lock value, fencing token,
  generation, positive TTL, and fresh writer metadata.  It never SETs, EXPIREs,
  recreates, or extends the writer lease.
* Kraken can authenticate/reconnect while the MultiAccountBrokerManager Kraken
  startup FSM or reconnect-supervisor failure latch still reflects an earlier
  failure.  v60 synchronizes that stale mirror only when the canonical broker
  object itself already reports connected=True.  Invalid-nonce failures remain
  recoverable because the distributed nonce manager can resynchronize them;
  bad key/signature/permission/configuration failures remain permanently latched
  while Kraken is disconnected.

No writer, capital, risk, strategy, nonce, or execution-readiness bypass is
introduced.  All positive convergence requires existing canonical proof.
"""
from __future__ import annotations

import importlib
import json
import logging
import os
import sys
import threading
import time
from functools import wraps
from types import ModuleType
from typing import Any, Optional

LOGGER = logging.getLogger("nija.kraken_connection_convergence_v44")
MARKER = "20260807-kraken-connection-convergence-v44"
POST_V59_MARKER = "20260809-post-v59-runtime-convergence-v60"

_LOCK = threading.RLock()
_STOP = threading.Event()
_WATCHDOG_STARTED = False
_WRITER_STOP = threading.Event()
_WRITER_WATCHDOG_STARTED = False
_WRITER_LAST_SIGNATURE = ""
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}
_MANAGER_PATCH_ATTR = "_nija_post_v59_kraken_fsm_v60"
_SUPERVISOR_PATCH_ATTR = "_nija_post_v59_nonce_classification_v60"

_V24_NAMES = (
    "nija_canonical_broker_startup_convergence_v24_prebot",
    "bot.canonical_broker_startup_convergence_v24",
    "canonical_broker_startup_convergence_v24",
)


def _truthy(name: str) -> bool:
    return str(os.environ.get(name, "") or "").strip().lower() in _TRUE


def _as_text(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value or "")


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _v24() -> Optional[ModuleType]:
    for name in _V24_NAMES:
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            return module
    try:
        module = importlib.import_module("bot.canonical_broker_startup_convergence_v24")
    except Exception:
        return None
    return module if isinstance(module, ModuleType) else None


def _broker_label(value: Any) -> str:
    raw = getattr(value, "value", value)
    return str(raw or "").strip().lower()


def _manager_kraken_pair(manager: Any) -> tuple[Any, Any]:
    if manager is None:
        return None, None
    mapping = getattr(manager, "_platform_brokers", {})
    try:
        items = list(mapping.items())
    except Exception:
        items = []
    for key, broker in items:
        if _broker_label(key) == "kraken":
            return key, broker
    return None, None


def _patch_manager_module(module: ModuleType) -> bool:
    """Prefer an actually-connected Kraken broker over a stale FAILED FSM mirror."""
    cls = getattr(module, "MultiAccountBrokerManager", None)
    if not isinstance(cls, type) or getattr(cls, _MANAGER_PATCH_ATTR, False):
        return False
    original = getattr(cls, "wait_for_platform_ready", None)
    if not callable(original):
        return False

    @wraps(original)
    def wait_for_platform_ready(self: Any, broker_type: Any, *args: Any, **kwargs: Any):
        if _broker_label(broker_type) == "kraken":
            broker = getattr(self, "_platform_brokers", {}).get(broker_type)
            if broker is None:
                _key, broker = _manager_kraken_pair(self)
            if broker is not None and bool(getattr(broker, "connected", False)):
                marker = getattr(self, "_mark_platform_connected", None)
                if callable(marker):
                    marker(broker_type)
                _clear_stale_permanent_failure(
                    "canonical_broker_connected_before_platform_wait",
                    allow_any=True,
                )
                LOGGER.critical(
                    "KRAKEN_V60_STALE_FSM_RECONCILED marker=%s source=wait_for_platform_ready "
                    "canonical_connected=true fabricated_connected=false",
                    POST_V59_MARKER,
                )
                return True
        return original(self, broker_type, *args, **kwargs)

    cls.wait_for_platform_ready = wait_for_platform_ready
    setattr(cls, _MANAGER_PATCH_ATTR, True)
    LOGGER.warning(
        "KRAKEN_V60_MANAGER_WAIT_PATCHED marker=%s module=%s",
        POST_V59_MARKER,
        module.__name__,
    )
    return True


def _manager() -> Any:
    """Return the loaded canonical manager without initiating runtime imports."""
    for name in ("bot.multi_account_broker_manager", "multi_account_broker_manager"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            _patch_manager_module(module)
            getter = getattr(module, "get_broker_manager", None)
            if callable(getter):
                try:
                    return getter()
                except Exception:
                    pass
    return None


def _loaded_manager() -> Any:
    """Return an already-loaded manager without importing the bot package."""
    for name in ("bot.multi_account_broker_manager", "multi_account_broker_manager"):
        module = sys.modules.get(name)
        if not isinstance(module, ModuleType):
            continue
        _patch_manager_module(module)
        getter = getattr(module, "get_broker_manager", None)
        if callable(getter):
            try:
                return getter()
            except Exception:
                return None
    return None


def _canonical_kraken(manager: Any) -> Any:
    _key, broker = _manager_kraken_pair(manager)
    if broker is not None:
        return broker
    if manager is None:
        return None
    try:
        broker_module = importlib.import_module("bot.broker_manager")
    except Exception:
        return None
    broker_type = getattr(getattr(broker_module, "BrokerType", None), "KRAKEN", None)
    if broker_type is not None:
        broker = getattr(manager, "_platform_brokers", {}).get(broker_type)
        if broker is not None:
            return broker
    getter = getattr(broker_module, "get_platform_broker", None)
    if callable(getter):
        for key in ("kraken", broker_type):
            if key is None:
                continue
            try:
                broker = getter(key)
            except Exception:
                continue
            if broker is not None:
                return broker
    return None


def _sync_connected_kraken(manager: Any, broker: Any, source: str) -> bool:
    """Synchronize mirrors only from a canonical broker already connected."""
    if manager is None or broker is None or not bool(getattr(broker, "connected", False)):
        return False
    key, registered = _manager_kraken_pair(manager)
    if key is None or registered is not broker:
        return False
    label = _broker_label(key)
    state = getattr(manager, "_platform_state", {}).get(label)
    state_label = _broker_label(state)
    failed = key in getattr(manager, "_platform_failed_types", set())
    connected_flag = bool(getattr(manager, "_platform_connected", {}).get(label, False))
    if connected_flag and not failed and state_label == "connected":
        return False

    sync = getattr(manager, "_sync_reconnect_readiness", None)
    if callable(sync):
        sync(key, broker)
    else:
        mark = getattr(manager, "_mark_platform_connected", None)
        if not callable(mark):
            return False
        mark(key)

    LOGGER.critical(
        "KRAKEN_V60_CONNECTED_STATE_RECONCILED marker=%s source=%s "
        "canonical_connected=true prior_state=%s prior_failed=%s fabricated_connected=false",
        POST_V59_MARKER,
        source,
        state_label or "unknown",
        str(failed).lower(),
    )
    return True


def _lineage_ready(v24: ModuleType) -> tuple[bool, str]:
    probe = getattr(v24, "_writer_lineage", None)
    if not callable(probe):
        return False, "writer_lineage_probe_unavailable"
    try:
        ready, reason = probe()
        return bool(ready), str(reason or "")
    except Exception as exc:
        return False, f"writer_lineage_error:{type(exc).__name__}:{exc}"


def _credentials_ready(v24: ModuleType) -> bool:
    probe = getattr(v24, "_kraken_credentials_configured", None)
    if not callable(probe):
        return False
    try:
        return bool(probe())
    except Exception:
        return False


def _patch_supervisor_module(module: ModuleType) -> bool:
    """Keep nonce resync failures retryable; leave real auth/config failures fatal."""
    if getattr(module, _SUPERVISOR_PATCH_ATTR, False):
        return False
    original = getattr(module, "_is_permanent_failure", None)
    if not callable(original):
        return False

    @wraps(original)
    def _is_permanent_failure(error_str: str) -> bool:
        text = str(error_str or "").strip().lower()
        if "invalid nonce" in text or "nonce_rejected" in text:
            return False
        return bool(original(error_str))

    module._is_permanent_failure = _is_permanent_failure
    setattr(module, _SUPERVISOR_PATCH_ATTR, True)
    LOGGER.warning(
        "KRAKEN_V60_NONCE_CLASSIFICATION_PATCHED marker=%s module=%s "
        "invalid_nonce=retryable auth_config_failures=latched",
        POST_V59_MARKER,
        module.__name__,
    )
    return True


def _supervisor_module(*, import_if_missing: bool = True) -> Optional[ModuleType]:
    for name in ("bot.kraken_reconnect_supervisor", "kraken_reconnect_supervisor"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            _patch_supervisor_module(module)
            return module
    if not import_if_missing:
        return None
    try:
        module = importlib.import_module("bot.kraken_reconnect_supervisor")
    except Exception:
        return None
    if isinstance(module, ModuleType):
        _patch_supervisor_module(module)
        return module
    return None


def _permanent_failure_detail() -> str:
    module = _supervisor_module(import_if_missing=False)
    if module is None:
        return ""
    return str(getattr(module, "_PERMANENT_FAILURE_SEEN", "") or "").strip()


def _permanent_failure_latched() -> bool:
    module = _supervisor_module(import_if_missing=True)
    if module is None:
        return False
    probe = getattr(module, "is_permanent_failure_latched", None)
    if callable(probe):
        try:
            return bool(probe())
        except Exception:
            return True
    return bool(str(getattr(module, "_PERMANENT_FAILURE_SEEN", "") or "").strip())


def _clear_stale_permanent_failure(reason: str, *, allow_any: bool = False) -> bool:
    module = _supervisor_module(import_if_missing=False)
    if module is None:
        return False
    detail = str(getattr(module, "_PERMANENT_FAILURE_SEEN", "") or "").strip()
    if not detail:
        return False
    lowered = detail.lower()
    nonce_latch = "invalid nonce" in lowered or "nonce_rejected" in lowered
    if not allow_any and not nonce_latch:
        return False
    reset = getattr(module, "reset_permanent_failure_latch", None)
    if not callable(reset):
        return False
    reset()
    LOGGER.critical(
        "KRAKEN_V60_STALE_PERMANENT_LATCH_CLEARED marker=%s reason=%s "
        "nonce_latch=%s authenticated_connected_proof=%s",
        POST_V59_MARKER,
        reason,
        str(nonce_latch).lower(),
        str(bool(allow_any)).lower(),
    )
    return True


def _rearm_if_stale_success(v24: ModuleType, broker: Any) -> bool:
    """Clear only the stale post-success guard; never interrupt in-flight recovery."""
    if broker is None or bool(getattr(broker, "connected", False)):
        return False
    if not bool(getattr(v24, "_KRAKEN_RECOVERY_STARTED", False)):
        return False
    if not _truthy("NIJA_KRAKEN_AUTHENTICATED_RECOVERY_READY"):
        return False
    with _LOCK:
        if bool(getattr(broker, "connected", False)):
            return False
        if not bool(getattr(v24, "_KRAKEN_RECOVERY_STARTED", False)):
            return False
        if not _truthy("NIJA_KRAKEN_AUTHENTICATED_RECOVERY_READY"):
            return False
        setattr(v24, "_KRAKEN_RECOVERY_STARTED", False)
        os.environ["NIJA_KRAKEN_AUTHENTICATED_RECOVERY_READY"] = "0"
    LOGGER.critical(
        "KRAKEN_V44_STALE_SUCCESS_REARMED marker=%s connected=false previous_ready=true",
        MARKER,
    )
    return True


def _writer_runtime() -> Any:
    """Return only an already-loaded writer runtime; never import bot preboot."""
    for name in ("bot.entrypoint_writer_authority", "entrypoint_writer_authority"):
        module = sys.modules.get(name)
        getter = getattr(module, "get_entrypoint_writer_authority", None) if module else None
        if callable(getter):
            try:
                return getter()
            except Exception:
                return None
    return None


def _writer_interval_s(runtime: Any) -> float:
    raw = str(os.environ.get("NIJA_WRITER_HEARTBEAT_INTERVAL_S", "") or "").strip()
    if raw:
        try:
            return max(1.0, float(raw))
        except (TypeError, ValueError):
            pass
    try:
        ttl_s = max(15.0, float(getattr(runtime, "_ttl_s", 60.0) or 60.0))
    except (TypeError, ValueError):
        ttl_s = 60.0
    return min(5.0, max(1.0, ttl_s / 3.0))


def _exact_writer_renewal_proof(runtime: Any, max_age_s: float) -> dict[str, Any]:
    """Read-only exact Redis proof used solely to repair a stale local timestamp."""
    proof: dict[str, Any] = {
        "ok": False,
        "reason": "uninitialized",
        "pttl_ms": -2,
        "metadata_age_s": float("inf"),
    }
    if runtime is None:
        proof["reason"] = "runtime_missing"
        return proof
    if not bool(getattr(runtime, "acquired", False)) or bool(getattr(runtime, "lost", False)):
        proof["reason"] = "runtime_not_active"
        return proof
    if bool(getattr(runtime, "_local_fallback", False)):
        proof["reason"] = "local_fallback_rejected"
        return proof

    stop = getattr(runtime, "_stop", None)
    if stop is not None and callable(getattr(stop, "is_set", None)) and stop.is_set():
        proof["reason"] = "renewal_stop_requested"
        return proof
    thread = getattr(runtime, "_heartbeat_thread", None)
    if thread is None or not callable(getattr(thread, "is_alive", None)) or not thread.is_alive():
        proof["reason"] = "renewal_thread_not_alive"
        return proof

    client = getattr(runtime, "_client", None)
    lock_key = str(getattr(runtime, "_lock_key", "") or "").strip()
    meta_key = str(getattr(runtime, "_meta_key", "") or "").strip()
    fencing_key = str(getattr(runtime, "_fencing_key", "") or "").strip()
    expected_lock = str(getattr(runtime, "_lock_value", "") or "").strip()
    token = str(getattr(runtime, "_token", "") or "").strip()
    generation = _as_int(getattr(runtime, "_generation", 0), 0)
    generation_key = str(
        os.environ.get("NIJA_LEASE_GENERATION_KEY", "") or "nija:lease:generation"
    ).strip()
    if client is None or not lock_key or not meta_key or not expected_lock or not token or generation <= 0:
        proof["reason"] = "writer_exact_proof_inputs_missing"
        return proof

    try:
        current_lock = _as_text(client.get(lock_key)).strip()
        pttl_ms = _as_int(client.pttl(lock_key), -2)
        redis_generation = _as_int(client.get(generation_key), 0)
        current_fence = _as_text(client.get(fencing_key)).strip() if fencing_key else token
        meta_raw = client.get(meta_key)
    except Exception as exc:
        proof["reason"] = f"redis_read_error:{type(exc).__name__}:{exc}"
        return proof

    proof["pttl_ms"] = pttl_ms
    if current_lock != expected_lock:
        proof["reason"] = "lock_value_mismatch"
        return proof
    interval_s = _writer_interval_s(runtime)
    safety_ms = int(max(5000.0, interval_s * 2.0 * 1000.0))
    if pttl_ms <= safety_ms:
        proof["reason"] = f"lock_ttl_too_low:{pttl_ms}<={safety_ms}"
        return proof
    if redis_generation != generation:
        proof["reason"] = f"generation_mismatch:{redis_generation}!={generation}"
        return proof
    if fencing_key and current_fence != token:
        proof["reason"] = "fencing_token_mismatch"
        return proof

    try:
        meta = json.loads(_as_text(meta_raw))
    except Exception:
        proof["reason"] = "writer_metadata_unparseable"
        return proof
    meta_token = str(meta.get("token") or "").strip()
    meta_generation = _as_int(meta.get("generation"), 0)
    heartbeat_at = float(meta.get("heartbeat_at") or 0.0)
    if meta_token != token:
        proof["reason"] = "metadata_token_mismatch"
        return proof
    if meta_generation != generation:
        proof["reason"] = "metadata_generation_mismatch"
        return proof
    if heartbeat_at <= 0:
        proof["reason"] = "metadata_heartbeat_missing"
        return proof
    metadata_age_s = max(0.0, time.time() - heartbeat_at)
    proof["metadata_age_s"] = metadata_age_s
    metadata_max_age_s = max(10.0, float(max_age_s or 0.0), interval_s * 3.0)
    if metadata_age_s > metadata_max_age_s:
        proof["reason"] = f"metadata_heartbeat_stale:{metadata_age_s:.1f}>{metadata_max_age_s:.1f}"
        return proof

    proof.update(
        ok=True,
        reason="exact_redis_writer_renewal_proof",
        generation=generation,
        token_prefix=token[:8],
        metadata_max_age_s=metadata_max_age_s,
    )
    return proof


def reconcile_writer_renewal_once(runtime: Any = None) -> dict[str, Any]:
    """Repair only a stale local renewal timestamp after exact Redis proof."""
    runtime = runtime if runtime is not None else _writer_runtime()
    result: dict[str, Any] = {"ok": False, "action": "none", "reason": "runtime_unavailable"}
    if runtime is None:
        return result
    health = getattr(runtime, "_nija_lease_renewal_health", None)
    if not callable(health):
        result["reason"] = "renewal_health_unavailable"
        return result
    try:
        ok, reason, age_s, max_age_s = health()
    except Exception as exc:
        result["reason"] = f"renewal_health_error:{type(exc).__name__}:{exc}"
        return result
    if bool(ok):
        result.update(ok=True, reason="renewal_healthy", age_s=float(age_s))
        return result
    reason = str(reason or "")
    result.update(reason=reason, age_s=float(age_s), max_age_s=float(max_age_s))
    if reason != "renewal_success_stale":
        return result

    proof = _exact_writer_renewal_proof(runtime, float(max_age_s))
    result["proof"] = proof
    if not bool(proof.get("ok")):
        result["reason"] = f"exact_redis_proof_failed:{proof.get('reason')}"
        return result

    now_mono = time.monotonic()
    now_epoch = time.time()
    setattr(runtime, "_nija_last_lease_renewal_monotonic", now_mono)
    setattr(runtime, "_nija_last_lease_renewal_epoch", now_epoch)
    os.environ["NIJA_WRITER_LEASE_RENEWAL_ACTIVE"] = "1"
    os.environ["NIJA_WRITER_LEASE_RENEWED_TS"] = f"{now_epoch:.6f}"

    notify = getattr(runtime, "_notify_runtime_reconciliation", None)
    if callable(notify):
        try:
            notify("post_v59_exact_writer_renewal_reanchor_v60")
        except Exception:
            LOGGER.debug("writer v60 runtime reconciliation deferred", exc_info=True)

    LOGGER.critical(
        "WRITER_V60_RENEWAL_PROOF_REANCHORED marker=%s generation=%s "
        "previous_age_s=%.1f pttl_ms=%s metadata_age_s=%.2f "
        "redis_mutation=false exact_lock=true exact_generation=true exact_fencing=true",
        POST_V59_MARKER,
        proof.get("generation"),
        float(age_s),
        proof.get("pttl_ms"),
        float(proof.get("metadata_age_s", 0.0)),
    )
    result.update(ok=True, action="reanchored", reason="exact_redis_writer_renewal_proof")
    return result


def _writer_watchdog_loop() -> None:
    global _WRITER_LAST_SIGNATURE
    try:
        interval = max(
            0.5,
            float(os.environ.get("NIJA_POST_V59_WRITER_PROOF_POLL_S", "1.0") or "1.0"),
        )
    except (TypeError, ValueError):
        interval = 1.0
    while not _WRITER_STOP.wait(interval):
        try:
            state = reconcile_writer_renewal_once()
            if state.get("ok"):
                _WRITER_LAST_SIGNATURE = ""
                continue
            signature = str(state.get("reason") or "")
            if signature and signature != _WRITER_LAST_SIGNATURE and signature.startswith("exact_redis_proof_failed"):
                LOGGER.warning(
                    "WRITER_V60_REANCHOR_BLOCKED marker=%s reason=%s fail_closed=true",
                    POST_V59_MARKER,
                    signature,
                )
                _WRITER_LAST_SIGNATURE = signature
        except Exception as exc:
            LOGGER.warning(
                "WRITER_V60_WATCHDOG_ERROR marker=%s error=%s:%s",
                POST_V59_MARKER,
                type(exc).__name__,
                exc,
            )


def reconcile_once() -> dict[str, Any]:
    result: dict[str, Any] = {
        "ok": False,
        "action": "none",
        "reason": "uninitialized",
        "connected": False,
    }
    v24 = _v24()
    if v24 is None:
        result["reason"] = "v24_unavailable"
        return result
    if not _credentials_ready(v24):
        result["reason"] = "credentials_not_configured_or_disabled"
        return result
    lineage_ok, lineage_reason = _lineage_ready(v24)
    if not lineage_ok:
        result["reason"] = lineage_reason or "writer_lineage_not_ready"
        return result

    # Preserve the original fail-closed ordering for a real permanent failure.
    # A real latch carries a detail string.  Only then may v60 inspect an
    # already-loaded canonical broker to see whether a later authenticated
    # success has made that latch stale.  Tests/operators that explicitly force
    # the boolean latch without detail retain the original immediate block.
    if _permanent_failure_latched():
        detail = _permanent_failure_detail()
        if detail:
            manager_loaded = _loaded_manager()
            broker_loaded = _canonical_kraken(manager_loaded) if manager_loaded is not None else None
            if broker_loaded is not None and bool(getattr(broker_loaded, "connected", False)):
                _sync_connected_kraken(manager_loaded, broker_loaded, "permanent_latch_connected_proof")
                _clear_stale_permanent_failure(
                    "authenticated_canonical_broker_connected",
                    allow_any=True,
                )
            else:
                _clear_stale_permanent_failure(
                    "recoverable_invalid_nonce_latch",
                    allow_any=False,
                )
        if _permanent_failure_latched():
            result["reason"] = "permanent_auth_or_config_failure_latched"
            return result

    manager = _manager()
    if manager is None:
        result["reason"] = "canonical_manager_unavailable"
        return result
    broker = _canonical_kraken(manager)
    if broker is None:
        prepare = getattr(v24, "_prepare_canonical_manager", None)
        if callable(prepare):
            try:
                manager = prepare()
                broker = _canonical_kraken(manager)
            except Exception as exc:
                result["reason"] = f"canonical_prepare_failed:{type(exc).__name__}:{exc}"
                return result
    if broker is None:
        result["reason"] = "canonical_kraken_unavailable"
        return result

    connected = bool(getattr(broker, "connected", False))
    result["connected"] = connected
    if connected:
        _sync_connected_kraken(manager, broker, "v44_reconcile_connected")
        _clear_stale_permanent_failure(
            "authenticated_canonical_broker_connected",
            allow_any=True,
        )
        result.update(ok=True, action="none", reason="already_connected")
        return result

    rearmed = _rearm_if_stale_success(v24, broker)
    starter = getattr(v24, "_start_kraken_authenticated_recovery", None)
    if not callable(starter):
        result["reason"] = "authenticated_recovery_unavailable"
        return result

    already_started = bool(getattr(v24, "_KRAKEN_RECOVERY_STARTED", False))
    if already_started and not rearmed:
        result["reason"] = "authenticated_recovery_in_flight"
        result["action"] = "observe"
        return result

    try:
        started = bool(starter(manager))
    except Exception as exc:
        result["reason"] = f"authenticated_recovery_start_failed:{type(exc).__name__}:{exc}"
        return result

    if started:
        result.update(
            ok=True,
            action="recovery_started",
            reason="stale_success_rearmed" if rearmed else "disconnected_recovery_started",
        )
        LOGGER.warning(
            "KRAKEN_V44_RECOVERY_STARTED marker=%s reason=%s writer_lineage=%s",
            MARKER,
            result["reason"],
            lineage_reason,
        )
    else:
        result["reason"] = "authenticated_recovery_not_started"
    return result


def _watchdog_loop() -> None:
    try:
        interval = max(
            2.0,
            float(os.environ.get("NIJA_KRAKEN_CONNECTION_WATCHDOG_INTERVAL_S", "5") or "5"),
        )
    except (TypeError, ValueError):
        interval = 5.0
    last_signature = ""
    while not _STOP.wait(interval):
        try:
            state = reconcile_once()
            signature = f"{state.get('action')}:{state.get('reason')}:{state.get('connected')}"
            if signature != last_signature:
                log = LOGGER.info if state.get("connected") else LOGGER.warning
                log(
                    "KRAKEN_V44_WATCHDOG marker=%s connected=%s action=%s reason=%s",
                    MARKER,
                    str(bool(state.get("connected"))).lower(),
                    state.get("action"),
                    state.get("reason"),
                )
                last_signature = signature
        except Exception as exc:
            LOGGER.warning(
                "KRAKEN_V44_WATCHDOG_ERROR marker=%s error=%s:%s",
                MARKER,
                type(exc).__name__,
                exc,
            )


def install() -> bool:
    global _WATCHDOG_STARTED, _WRITER_WATCHDOG_STARTED
    with _LOCK:
        if not _WATCHDOG_STARTED:
            _WATCHDOG_STARTED = True
            thread = threading.Thread(
                target=_watchdog_loop,
                name="KrakenConnectionConvergenceV44",
                daemon=True,
            )
            thread.start()
        if not _WRITER_WATCHDOG_STARTED:
            _WRITER_WATCHDOG_STARTED = True
            writer_thread = threading.Thread(
                target=_writer_watchdog_loop,
                name="PostV59WriterRenewalProofV60",
                daemon=True,
            )
            writer_thread.start()
        os.environ["NIJA_KRAKEN_CONNECTION_CONVERGENCE_V44_INSTALLED"] = "1"
        os.environ["NIJA_POST_V59_RUNTIME_CONVERGENCE_V60_INSTALLED"] = "1"

    # Reconcile once immediately.  These helpers remain safe before bot imports:
    # writer reconciliation never imports the entrypoint module, and Kraken
    # reconciliation returns before importing MABM until writer lineage exists.
    try:
        reconcile_writer_renewal_once()
    except Exception:
        LOGGER.exception("WRITER_V60_INITIAL_RECONCILE_FAILED marker=%s", POST_V59_MARKER)
    try:
        reconcile_once()
    except Exception:
        LOGGER.exception("KRAKEN_V44_INITIAL_RECONCILE_FAILED marker=%s", MARKER)
    LOGGER.critical(
        "KRAKEN_CONNECTION_CONVERGENCE_V44_INSTALLED marker=%s fail_closed=true fabricates_connected=false",
        MARKER,
    )
    LOGGER.critical(
        "POST_V59_RUNTIME_CONVERGENCE_V60_INSTALLED marker=%s "
        "writer_redis_mutation=false kraken_fabricates_connected=false invalid_nonce_retryable=true",
        POST_V59_MARKER,
    )
    return True


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "POST_V59_MARKER",
    "install",
    "install_import_hook",
    "reconcile_once",
    "reconcile_writer_renewal_once",
    "_exact_writer_renewal_proof",
    "_patch_manager_module",
    "_patch_supervisor_module",
    "_rearm_if_stale_success",
]
