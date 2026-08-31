"""Bound read-only Kraken HTTP calls and canonical API-lock admission.

Production generation logs showed repeated v117 Kraken position generations
reaching the 12-second caller timeout. NIJA's Kraken private-call wrapper holds
a Kraken API serialization lock while calling ``krakenex.API.query_private``.
v121 already bounds the HTTP request itself, but production on 2026-08-24 proved
a second liveness gap: a read-only caller can wait indefinitely *before* the
HTTP timeout begins while another caller owns the selected API lock. Heartbeat
v210 then times out its outer caller while the underlying daemon remains blocked
on the lock, causing every later heartbeat retry to see the same in-flight worker.

This hardening bounds only acquisition of the existing Kraken lock dispatcher
for read-only private calls. Mutating methods (AddOrder/Cancel/Edit/etc.)
preserve their existing serialization and timeout semantics so an ambiguous
client timeout cannot trigger an automatic duplicate mutation. Once the read
lock is acquired, the existing method runs unchanged and re-enters the same
``RLock``; HTTP read timeouts remain owned by v121. Public reads are unchanged.
v117 remains the outer fail-closed position snapshot authority and synthetic
empty snapshots remain forbidden.

Wrapper-order convergence v310 fixes a later interaction with v293. The v117
dispatch hook can reassert v121 after the credential-scoped v293 wrapper has
already been installed. In that order, the old v121 wrapper asked for the lock
*before* v293 could establish the credential thread-local, accidentally falling
back to the process-wide Kraken lock and re-coupling PLATFORM and USER accounts.
v310 makes v121 itself credential-scope aware whenever v293 is already loaded,
and makes v121 patch detection chain-aware so reassertion cannot stack another
outer v121 wrapper. If credential scope is unavailable or unproven, the original
canonical/global lock remains the fail-closed fallback.

Early read convergence v311 addresses a startup-order gap observed on 2026-08-31.
The broader production convergence chain installed v286/v292/v293/v297/v299 only
after the first heartbeat and authoritative PLATFORM Balance reconciliation had
already started. That allowed an otherwise-correct pre-convergence Balance
flight to monopolize the same credential long enough for startup reconciliation
to remain pending. v311 installs only those already-existing, idempotent Kraken
read-liveness repairs from v121's earlier installation point. A v311 failure is
non-authoritative and leaves the previous fail-closed behavior intact; the later
v88 convergence chain remains the canonical full installer.

No new builtins/importlib hook is installed. Future broker_manager imports are
patched by extending v117's already-installed broker-manager dispatch hook.
No lock is bypassed or force-released and nonce/rate/transport/order/fill/risk,
capital, kill-switch and execution-proof semantics remain unchanged.
"""
from __future__ import annotations

import importlib
import logging
import os
import sys
import threading
from functools import wraps
from types import ModuleType
from typing import Any, Callable

LOGGER = logging.getLogger("nija.kraken_read_timeout_v121")
MARKER = "20260816-kraken-read-timeout-v121"
LOCK_BOUND_MARKER = "20260824-kraken-read-lock-bound-v212"
LOCK_SCOPE_MARKER = "20260831-kraken-read-lock-wrapper-order-v310"
EARLY_READ_MARKER = "20260831-kraken-early-read-convergence-v311"
RELEASE_ID = "20260816-runtime-convergence-v121"
_PATCH_ATTR = "_nija_kraken_read_timeout_v121"
_API_ATTR = "_nija_kraken_read_timeout_v121_api"
_V117_DISPATCH_ATTR = "_nija_kraken_read_timeout_v121_dispatch"
_LOCK_SCOPE_READY_FLAG = "NIJA_KRAKEN_READ_LOCK_SCOPE_V310_READY"
_EARLY_READ_READY_FLAG = "NIJA_KRAKEN_EARLY_READ_CONVERGENCE_V311_READY"
_EARLY_READ_MODULES = (
    "bot.runtime_kraken_position_refresh_liveness_v286_patch",
    "bot.runtime_kraken_transport_timeout_v292_patch",
    "bot.runtime_kraken_credential_lock_scope_v293_patch",
    "bot.runtime_kraken_monitoring_fairness_v297_patch",
    "bot.runtime_kraken_credential_read_convergence_v299_patch",
)
_LOCK = threading.RLock()
_INSTALLED = False

_MUTATING = {
    "AddOrder",
    "AddOrderBatch",
    "CancelOrder",
    "CancelOrderBatch",
    "CancelAll",
    "CancelAllOrdersAfter",
    "EditOrder",
}


class KrakenReadLockBusy(RuntimeError):
    """Fail-closed signal that a read could not enter the selected Kraken API lock."""


def _env_timeout(name: str, default: float, *, maximum: float = 30.0) -> float:
    try:
        value = float(os.environ.get(name, str(default)) or default)
    except (TypeError, ValueError):
        value = default
    return max(1.0, min(maximum, value))


def _private_read_timeout_s() -> float:
    return _env_timeout("NIJA_KRAKEN_PRIVATE_READ_TIMEOUT_S", 8.0)


def _public_read_timeout_s() -> float:
    return _env_timeout("NIJA_KRAKEN_PUBLIC_READ_TIMEOUT_S", 6.0)


def _private_read_lock_wait_s() -> float:
    # Keep lock admission + the default 8 s HTTP read bound inside the
    # heartbeat v210 12 s outer budget under normal configuration.
    return _env_timeout("NIJA_KRAKEN_PRIVATE_READ_LOCK_WAIT_S", 3.0, maximum=10.0)


def _wrap_api(api: Any) -> bool:
    if api is None:
        return True
    if bool(getattr(api, _API_ATTR, False)):
        return True

    original_private = getattr(api, "query_private", None)
    original_public = getattr(api, "query_public", None)
    if not callable(original_private):
        return False

    @wraps(original_private)
    def query_private(method: str, data: Any = None, timeout: Any = None):
        selected = timeout
        read_only = str(method or "") not in _MUTATING
        if selected is None and read_only:
            selected = _private_read_timeout_s()
        if selected is not None and read_only:
            LOGGER.debug(
                "KRAKEN_READ_TIMEOUT_V121_PRIVATE method=%s timeout_s=%.2f read_only=true",
                method,
                float(selected),
            )
        return original_private(method, data, timeout=selected)

    api.query_private = query_private

    if callable(original_public):
        @wraps(original_public)
        def query_public(method: str, data: Any = None, timeout: Any = None):
            selected = timeout if timeout is not None else _public_read_timeout_s()
            return original_public(method, data, timeout=selected)

        api.query_public = query_public

    setattr(api, _API_ATTR, True)
    LOGGER.critical(
        "KRAKEN_READ_TIMEOUT_V121_API_PATCHED marker=%s private_read_timeout_s=%.2f public_read_timeout_s=%.2f mutating_timeout_semantics_unchanged=true",
        MARKER,
        _private_read_timeout_s(),
        _public_read_timeout_s(),
    )
    return True


def _method_from_call(args: tuple[Any, ...], kwargs: dict[str, Any]) -> str:
    if args:
        return str(args[0] or "")
    return str(kwargs.get("method") or "")


def _chain_has_patch(callable_obj: Any) -> bool:
    """Return true when any wrapper in the current chain is already v121."""
    seen: set[int] = set()
    current = callable_obj
    for _ in range(128):
        if not callable(current) or id(current) in seen:
            return False
        seen.add(id(current))
        if bool(getattr(current, _PATCH_ATTR, False)):
            return True
        current = getattr(current, "__wrapped__", None)
    return False


def _credential_scope_runner() -> Callable[[Any, Callable[[], Any]], Any] | None:
    """Return v293's scope runner only when that repair is already loaded.

    v121 is installed earlier in startup than v293. Importing v293 from here
    would change startup ordering, so this helper deliberately consults only
    already-loaded modules. Later v117 reassertions then become order-safe
    without creating a new import cycle.
    """
    module = (
        sys.modules.get("bot.runtime_kraken_credential_lock_scope_v293_patch")
        or sys.modules.get("runtime_kraken_credential_lock_scope_v293_patch")
    )
    if not isinstance(module, ModuleType):
        return None
    runner = getattr(module, "_invoke_with_credential_scope", None)
    return runner if callable(runner) else None


def _acquire_global_read_lock(module: ModuleType, method: str) -> tuple[Any | None, bool]:
    """Bound read-only admission to the canonical Kraken lock dispatcher.

    With v293 loaded, ``module.get_kraken_api_lock`` may resolve to a credential-
    scoped lock when its credential context is active. Without v293 (or without
    proven credential identity), it resolves to the original process-wide lock.

    Returning ``(None, False)`` means the canonical getter is unavailable and
    the existing broker method should run unchanged. A busy selected lock raises
    ``KrakenReadLockBusy`` so the caller fails closed without leaving a daemon
    parked indefinitely behind another Kraken request.
    """
    if method in _MUTATING:
        return None, False

    getter = getattr(module, "get_kraken_api_lock", None)
    if not callable(getter):
        return None, False

    try:
        selected_lock = getter()
    except Exception:
        # Preserve the broker's existing error behavior if its canonical lock
        # getter itself is unavailable/broken.
        return None, False

    acquire = getattr(selected_lock, "acquire", None)
    release = getattr(selected_lock, "release", None)
    if not callable(acquire) or not callable(release):
        return None, False

    wait_s = _private_read_lock_wait_s()
    try:
        acquired = bool(acquire(timeout=wait_s))
    except TypeError:
        acquired = bool(acquire(True, wait_s))

    if not acquired:
        LOGGER.warning(
            "KRAKEN_READ_LOCK_V212_BUSY marker=%s method=%s wait_s=%.2f "
            "read_only=true action=fail_closed_retry canonical_lock_dispatch_preserved=true "
            "credential_scope_compatible=true http_timeout_unchanged=true mutating_calls_unchanged=true",
            LOCK_BOUND_MARKER,
            method or "unknown",
            wait_s,
        )
        raise KrakenReadLockBusy(
            f"Kraken read lock busy after {wait_s:.2f}s for {method or 'private_read'}"
        )

    return selected_lock, True


def _invoke_bounded_read(
    module: ModuleType,
    broker: Any,
    method: str,
    call: Callable[[], Any],
) -> Any:
    """Acquire the bounded read lock inside v293 scope when available.

    This is the v310 wrapper-order repair. If v121 is reasserted outside v293,
    the v293 runner establishes the credential-local dispatch context *before*
    v121 asks ``get_kraken_api_lock`` for the selected lock. The inner original
    call may pass through v293 again; nested scope on the same RLock is safe and
    preserves the existing serialization contract.
    """

    def _admit_then_call() -> Any:
        selected_lock, acquired = _acquire_global_read_lock(module, method)
        if not acquired or selected_lock is None:
            return call()
        try:
            return call()
        finally:
            selected_lock.release()

    runner = _credential_scope_runner()
    if callable(runner):
        return runner(broker, _admit_then_call)
    return _admit_then_call()


def _patch_broker_manager(module: ModuleType | None = None) -> bool:
    module = module or sys.modules.get("bot.broker_manager") or sys.modules.get("broker_manager")
    if not isinstance(module, ModuleType):
        return True

    cls = getattr(module, "KrakenBroker", None)
    if not isinstance(cls, type):
        return False

    current = getattr(cls, "_kraken_private_call", None)
    if not callable(current):
        return False
    if not _chain_has_patch(current):
        @wraps(current)
        def kraken_private_call_v121(self: Any, *args: Any, **kwargs: Any):
            _wrap_api(getattr(self, "api", None))
            method = _method_from_call(args, kwargs)

            # Mutations deliberately keep the original lock wait and request
            # timeout semantics. Only read-only calls get bounded admission.
            if method in _MUTATING:
                return current(self, *args, **kwargs)

            return _invoke_bounded_read(
                module,
                self,
                method,
                lambda: current(self, *args, **kwargs),
            )

        setattr(kraken_private_call_v121, _PATCH_ATTR, True)
        setattr(kraken_private_call_v121, "__wrapped__", current)
        cls._kraken_private_call = kraken_private_call_v121

    iterator = getattr(cls, "_iter_live", None)
    if callable(iterator):
        try:
            for broker in list(iterator() or []):
                _wrap_api(getattr(broker, "api", None))
        except Exception:
            LOGGER.debug("KRAKEN_READ_TIMEOUT_V121 live-instance patch skipped", exc_info=True)

    LOGGER.critical(
        "KRAKEN_READ_TIMEOUT_V121_BROKER_PATCHED marker=%s lock_marker=%s scope_marker=%s broker_class=KrakenBroker "
        "private_read_timeout_s=%.2f public_read_timeout_s=%.2f private_read_lock_wait_s=%.2f "
        "read_lock_wait_bounded=true chain_aware_patch_detection=true credential_scope_compatible=true "
        "canonical_lock_dispatch_preserved=true mutating_lock_wait_unchanged=true synthetic_empty_snapshot=false",
        MARKER,
        LOCK_BOUND_MARKER,
        LOCK_SCOPE_MARKER,
        _private_read_timeout_s(),
        _public_read_timeout_s(),
        _private_read_lock_wait_s(),
    )
    return True


def _patch_v117_dispatch() -> bool:
    try:
        from bot import position_fetch_generation_v117_patch as v117
    except Exception:
        return False

    current = getattr(v117, "_patch_broker_manager", None)
    if not callable(current):
        return False
    if getattr(current, _V117_DISPATCH_ATTR, False):
        return True

    @wraps(current)
    def patch_broker_manager_v121() -> bool:
        if not current():
            return False
        module = sys.modules.get("bot.broker_manager") or sys.modules.get("broker_manager")
        return _patch_broker_manager(module if isinstance(module, ModuleType) else None)

    setattr(patch_broker_manager_v121, _V117_DISPATCH_ATTR, True)
    setattr(patch_broker_manager_v121, "__wrapped__", current)
    v117._patch_broker_manager = patch_broker_manager_v121
    LOGGER.critical(
        "KRAKEN_READ_TIMEOUT_V121_V117_DISPATCH_PATCHED marker=%s scope_marker=%s existing_import_hook_reused=true new_import_hook=false chain_aware_reassertion=true",
        MARKER,
        LOCK_SCOPE_MARKER,
    )
    return True


def _install_early_read_module(module_name: str) -> tuple[bool, str]:
    try:
        module = importlib.import_module(module_name)
        installer = getattr(module, "install_import_hook", None) or getattr(module, "install", None)
        if not callable(installer):
            return False, "installer_unavailable"
        result = installer()
        if result is False:
            return False, "installer_returned_false"
        return True, "ok"
    except Exception as exc:
        return False, f"{type(exc).__name__}:{exc}"


def _install_early_read_convergence_v311() -> bool:
    """Install the narrow Kraken read-liveness subset before first reconciliation.

    This does not grant readiness. The full production v88 chain remains the
    canonical later installer and safely reasserts these idempotent modules.
    """
    if os.environ.get(_EARLY_READ_READY_FLAG) == "1":
        return True

    outcomes: dict[str, str] = {}
    ready = True
    for module_name in _EARLY_READ_MODULES:
        ok, detail = _install_early_read_module(module_name)
        outcomes[module_name] = detail
        if not ok:
            ready = False
            break

    os.environ[_EARLY_READ_READY_FLAG] = "1" if ready else "0"
    if ready:
        LOGGER.critical(
            "KRAKEN_EARLY_READ_CONVERGENCE_V311_READY marker=%s ready=true modules=%s "
            "before_first_reconciliation=true v88_full_chain_preserved=true "
            "credential_scoped_serialization=true monitoring_prewait=true balance_single_flight=true "
            "same_credential_coalescing=true transport_timeout_bound=true "
            "readiness_granted=false reconciliation_fabricated=false position_success_fabricated=false "
            "lock_force_release=false lock_bypass=false nonce_rate_order_fill_risk_capital_killswitch_execution_gates_unchanged=true "
            "execution_proof_fabricated=false forced_trade=false forced_activation=false safety_gates_bypassed=false",
            EARLY_READ_MARKER,
            ",".join(_EARLY_READ_MODULES),
        )
    else:
        LOGGER.warning(
            "KRAKEN_EARLY_READ_CONVERGENCE_V311_DEFERRED marker=%s ready=false outcomes=%s "
            "previous_fail_closed_behavior_preserved=true v88_full_chain_still_authoritative=true "
            "readiness_granted=false execution_proof_fabricated=false safety_gates_bypassed=false",
            EARLY_READ_MARKER,
            outcomes,
        )
    return ready


def _patch_release_manifest() -> bool:
    manifest = sys.modules.get("bot.runtime_release_manifest_patch") or sys.modules.get(
        "runtime_release_manifest_patch"
    )
    if not isinstance(manifest, ModuleType):
        try:
            import bot.runtime_release_manifest_patch as manifest  # type: ignore[no-redef]
        except Exception:
            return False
    required = getattr(manifest, "_REQUIRED_FLAGS", None)
    if not isinstance(required, dict):
        return False
    required["kraken_read_timeout_v121"] = "NIJA_KRAKEN_READ_TIMEOUT_V121_INSTALLED"
    required["kraken_read_lock_scope_v310"] = _LOCK_SCOPE_READY_FLAG
    manifest.RELEASE_ID = RELEASE_ID
    return True


def install() -> bool:
    global _INSTALLED
    with _LOCK:
        if not _patch_v117_dispatch():
            return False
        if not _patch_broker_manager():
            return False
        os.environ["NIJA_KRAKEN_READ_TIMEOUT_V121_INSTALLED"] = "1"
        os.environ[_LOCK_SCOPE_READY_FLAG] = "1"
        if not _patch_release_manifest():
            os.environ.pop("NIJA_KRAKEN_READ_TIMEOUT_V121_INSTALLED", None)
            os.environ.pop(_LOCK_SCOPE_READY_FLAG, None)
            return False
        # v311 is deliberately best-effort from the v121 contract perspective.
        # If an early dependency is not yet importable, v121 remains installed
        # and fail-closed; subsequent v121 reassertions may retry, while the full
        # v88 convergence chain remains the canonical later installer.
        _install_early_read_convergence_v311()
        _INSTALLED = True
        LOGGER.critical(
            "KRAKEN_READ_TIMEOUT_V121_INSTALLED marker=%s lock_marker=%s private_read_timeout_s=%.2f "
            "public_read_timeout_s=%.2f private_read_lock_wait_s=%.2f read_lock_wait_bounded=true "
            "mutating_calls_unchanged=true import_hook_added=false execution_gates_unchanged=true",
            MARKER,
            LOCK_BOUND_MARKER,
            _private_read_timeout_s(),
            _public_read_timeout_s(),
            _private_read_lock_wait_s(),
        )
        LOGGER.critical(
            "KRAKEN_READ_LOCK_SCOPE_V310_READY marker=%s ready=true "
            "v121_reassertion_chain_aware=true credential_scope_entered_before_lock_selection=true "
            "distinct_credentials_independent_when_v293_loaded=true same_credential_serialized=true "
            "unproven_credential_global_fallback=true lock_force_release=false lock_bypass=false "
            "nonce_rate_transport_order_fill_risk_capital_killswitch_execution_gates_unchanged=true "
            "execution_proof_fabricated=false forced_trade=false forced_activation=false safety_gates_bypassed=false",
            LOCK_SCOPE_MARKER,
        )
        return True


def install_import_hook() -> bool:
    """Compatibility installer name; v121 deliberately adds no import hook."""
    return install()


__all__ = [
    "MARKER",
    "LOCK_BOUND_MARKER",
    "LOCK_SCOPE_MARKER",
    "EARLY_READ_MARKER",
    "RELEASE_ID",
    "KrakenReadLockBusy",
    "install",
    "install_import_hook",
    "_private_read_lock_wait_s",
    "_wrap_api",
    "_chain_has_patch",
    "_credential_scope_runner",
    "_acquire_global_read_lock",
    "_invoke_bounded_read",
    "_patch_broker_manager",
    "_patch_v117_dispatch",
    "_install_early_read_module",
    "_install_early_read_convergence_v311",
]
