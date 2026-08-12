"""Post-merge production activation repair v59.

Addresses regressions observed after PR #2494:
- canonical stalled-writer monitor must never own BootstrapFSM/runtime authority;
- writer core registration must not synchronously wait on broker readiness I/O;
- v16 proof monitor must actually run on the canonical fast path;
- accepted fresh CapitalAuthority snapshot must reach TradingStateMachine's
  first-snapshot latch through the existing fail-closed activation bridge.

No trading/risk/nonce/SEAK/venue thresholds are weakened.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
from functools import wraps
from typing import Any

logger = logging.getLogger("nija.final_production_activation_repair_v59")
MARKER = "20260812-final-production-activation-v59"
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}
_LOCK = threading.RLock()
_INSTALLED = False


def _truthy(name: str) -> bool:
    return str(os.environ.get(name, "") or "").strip().lower() in _TRUE


def _canonical_fast_path() -> bool:
    return _truthy("NIJA_CANONICAL_ENTRYPOINT_FAST_PATH") and _truthy("NIJA_DEFER_RUNTIME_SITE_HOOKS")


def _patch_stalled_writer_diagnostic_only() -> bool:
    guard = importlib.import_module("bot.stalled_writer_release_guard_v22")

    original_bootstrap = getattr(guard, "_attempt_bootstrap_progression", None)
    original_authority = getattr(guard, "_attempt_authority_convergence_retry", None)

    if callable(original_bootstrap) and not getattr(original_bootstrap, "_nija_v59_diagnostic_only", False):
        @wraps(original_bootstrap)
        def bootstrap_only(source: str) -> bool:
            if _canonical_fast_path():
                logger.warning(
                    "STALLED_WRITER_BOOTSTRAP_MUTATION_SUPPRESSED marker=%s source=%s "
                    "reason=canonical_bot_main_single_owner diagnostic_only=true",
                    MARKER,
                    source,
                )
                return False
            return bool(original_bootstrap(source))
        bootstrap_only._nija_v59_diagnostic_only = True  # type: ignore[attr-defined]
        guard._attempt_bootstrap_progression = bootstrap_only

    if callable(original_authority) and not getattr(original_authority, "_nija_v59_diagnostic_only", False):
        @wraps(original_authority)
        def authority_only(source: str) -> bool:
            if _canonical_fast_path():
                logger.warning(
                    "STALLED_WRITER_AUTHORITY_MUTATION_SUPPRESSED marker=%s source=%s "
                    "reason=canonical_bot_main_single_owner diagnostic_only=true",
                    MARKER,
                    source,
                )
                return False
            return bool(original_authority(source))
        authority_only._nija_v59_diagnostic_only = True  # type: ignore[attr-defined]
        guard._attempt_authority_convergence_retry = authority_only

    os.environ["NIJA_STALLED_WRITER_CANONICAL_DIAGNOSTIC_ONLY"] = "1"
    logger.critical(
        "FINAL_ACTIVATION_V59_STALLED_WRITER_DIAGNOSTIC_ONLY marker=%s "
        "bootstrap_mutation=false authority_mutation=false writer_release=false",
        MARKER,
    )
    return True


def _patch_writer_reconciliation_async() -> bool:
    module = importlib.import_module("bot.entrypoint_writer_authority")
    cls = getattr(module, "EntrypointWriterAuthority", None)
    if not isinstance(cls, type):
        return False

    current = getattr(cls, "_notify_runtime_reconciliation", None)
    if not callable(current):
        return False
    if getattr(current, "_nija_v59_all_async", False):
        return True

    def notify_async(self: Any, trigger: str) -> None:
        """Never block lease/core registration on exchange/readiness I/O."""
        lock = getattr(self, "_runtime_reconcile_lock", None)
        if lock is None:
            lock = threading.Lock()
            self._runtime_reconcile_lock = lock

        with lock:
            worker = getattr(self, "_runtime_reconcile_thread", None)
            if worker is not None and worker.is_alive():
                logger.info(
                    "WRITER_READINESS_RECONCILE_DEDUPED marker=%s trigger=%s existing_worker=true",
                    MARKER,
                    trigger,
                )
                return

            def _worker() -> None:
                try:
                    runner = getattr(self, "_run_runtime_reconciliation", None)
                    if callable(runner):
                        runner(trigger)
                except Exception:
                    logger.exception(
                        "WRITER_READINESS_RECONCILE_ASYNC_FAILED marker=%s trigger=%s",
                        MARKER,
                        trigger,
                    )
                finally:
                    with lock:
                        if getattr(self, "_runtime_reconcile_thread", None) is threading.current_thread():
                            self._runtime_reconcile_thread = None

            worker = threading.Thread(
                target=_worker,
                name=f"writer-readiness-reconciliation-{trigger}"[:80],
                daemon=True,
            )
            self._runtime_reconcile_thread = worker
            worker.start()
            logger.critical(
                "WRITER_READINESS_RECONCILE_ASYNC_DISPATCHED marker=%s trigger=%s "
                "core_registration_blocked=false",
                MARKER,
                trigger,
            )

    notify_async._nija_v59_all_async = True  # type: ignore[attr-defined]
    notify_async.__wrapped__ = current  # type: ignore[attr-defined]
    cls._notify_runtime_reconciliation = notify_async
    logger.critical(
        "FINAL_ACTIVATION_V59_WRITER_RECONCILE_PATCHED marker=%s all_triggers_async=true",
        MARKER,
    )
    return True


def _install_proof_convergence() -> bool:
    """Start the already-existing proof stack; never fabricate a proof."""
    identity = importlib.import_module("runtime_module_identity_convergence_patch")
    identity_install = getattr(identity, "install", None) or getattr(identity, "install_import_hook", None)
    if callable(identity_install):
        identity_install()

    v15 = importlib.import_module("runtime_convergence_v15_patch")
    v15_install = getattr(v15, "install", None)
    if callable(v15_install):
        v15_install()

    v16 = importlib.import_module("preactivation_readiness_convergence_v16_patch")
    # v58 must already have replaced this function with incremental publication.
    mark = getattr(v16, "_mark_proven_readiness", None)
    if not callable(mark):
        return False
    v16_install = getattr(v16, "install", None) or getattr(v16, "install_import_hook", None)
    if not callable(v16_install):
        return False
    result = v16_install()
    logger.critical(
        "FINAL_ACTIVATION_V59_PROOF_MONITORS_STARTED marker=%s "
        "module_identity=true runtime_v15=true preactivation_v16=true",
        MARKER,
    )
    return result is not False


def _install_first_snapshot_bridge() -> bool:
    bridge = importlib.import_module("bot.activation_snapshot_bridge_patch")
    installer = getattr(bridge, "install_import_hook", None)
    if not callable(installer):
        return False
    installer()
    logger.critical(
        "FINAL_ACTIVATION_V59_FIRST_SNAPSHOT_BRIDGE_STARTED marker=%s "
        "source=accepted_capital_authority fail_closed=true",
        MARKER,
    )
    return True


def install_import_hook() -> bool:
    return install()


def install() -> bool:
    global _INSTALLED
    with _LOCK:
        if _INSTALLED:
            return True
        failures: list[str] = []
        for name, step in (
            ("stalled_writer_diagnostic_only", _patch_stalled_writer_diagnostic_only),
            ("writer_reconciliation_async", _patch_writer_reconciliation_async),
            ("proof_convergence", _install_proof_convergence),
            ("first_snapshot_bridge", _install_first_snapshot_bridge),
        ):
            try:
                if step() is False:
                    failures.append(name)
            except Exception as exc:
                failures.append(f"{name}:{type(exc).__name__}:{exc}")
                logger.critical(
                    "FINAL_ACTIVATION_V59_STEP_FAILED marker=%s step=%s err=%s",
                    MARKER,
                    name,
                    exc,
                    exc_info=True,
                )
        _INSTALLED = not failures
        os.environ["NIJA_FINAL_PRODUCTION_ACTIVATION_V59_INSTALLED"] = "1" if _INSTALLED else "0"
        logger.critical(
            "FINAL_PRODUCTION_ACTIVATION_V59_INSTALLED marker=%s ready=%s failures=%s "
            "thresholds_unchanged=true force_activation=false",
            MARKER,
            _INSTALLED,
            failures or "none",
        )
        return _INSTALLED


__all__ = ["MARKER", "install", "install_import_hook"]
