"""Credential-scoped Kraken private-call serialization v293.

Production evidence on 2026-08-30 showed that NIJA's canonical Kraken private-call
boundary serialized PLATFORM and every USER account through one process-wide API
lock. That preserves nonce ordering but unnecessarily couples independent Kraken
API keys: one slow private read can hold every other account behind it long enough
for authoritative position snapshots to miss their bounded readiness window.

Kraken nonce ordering is a per-API-key property. v293 therefore changes only the
lock selected by the existing ``KrakenBroker._kraken_private_call`` implementation:

* calls using the same proven API key continue to share one re-entrant lock;
* calls using different proven API keys receive different locks and may progress
  independently;
* if credential identity cannot be proven, the original process-wide lock is
  retained as the fail-closed fallback;
* code paths that request the Kraken API lock outside ``_kraken_private_call``
  also retain the original process-wide lock.

The existing private-call implementation still owns rate limiting, nonce pause,
nonce generation, jitter, transport, authentication, response handling, and all
order semantics. No lock is force-released or bypassed, no read result is
fabricated, and writer/capital/risk/kill-switch/order/fill gates are unchanged.
"""
from __future__ import annotations

import hashlib
import importlib
import logging
import os
import threading
from functools import wraps
from typing import Any, Callable

LOGGER = logging.getLogger("nija.runtime_kraken_credential_lock_scope_v293")
MARKER = "20260830-kraken-credential-lock-scope-v293"
RELEASE_ID = "20260830-runtime-convergence-v293"
_READY_FLAG = "NIJA_RUNTIME_KRAKEN_CREDENTIAL_LOCK_SCOPE_V293_READY"
_PRIVATE_PATCH_ATTR = "_nija_kraken_credential_lock_scope_private_v293"
_DISPATCH_PATCH_ATTR = "_nija_kraken_credential_lock_scope_dispatch_v293"
_LOCK = threading.RLock()
_SCOPE_LOCAL = threading.local()
_SCOPE_LOCKS: dict[str, threading.RLock] = {}
_ORIGINAL_GET_LOCK: Callable[[], Any] | None = None


def _broker_module() -> Any:
    return importlib.import_module("bot.broker_manager")


def _credential_scope_key(broker: Any) -> str:
    """Return a non-reversible key fingerprint, or empty when identity is unproven."""
    api = getattr(broker, "api", None)
    candidates = (
        getattr(api, "key", None),
        getattr(broker, "api_key", None),
        getattr(broker, "_api_key", None),
    )
    for raw in candidates:
        if raw is None:
            continue
        if isinstance(raw, bytes):
            material = bytes(raw)
        else:
            text = str(raw or "").strip()
            if not text:
                continue
            material = text.encode("utf-8", errors="strict")
        if not material:
            continue
        return hashlib.sha256(material).hexdigest()
    return ""


def _scoped_lock(scope_key: str) -> threading.RLock:
    if not scope_key:
        raise ValueError("credential_scope_required")
    with _LOCK:
        lock = _SCOPE_LOCKS.get(scope_key)
        if lock is None:
            lock = threading.RLock()
            _SCOPE_LOCKS[scope_key] = lock
        return lock


def _scoped_get_kraken_api_lock() -> Any:
    """Dispatch to the active credential lock, otherwise the canonical global lock."""
    active = getattr(_SCOPE_LOCAL, "lock", None)
    if active is not None:
        return active
    original = _ORIGINAL_GET_LOCK
    if callable(original):
        return original()
    raise RuntimeError("canonical_kraken_api_lock_unavailable")


setattr(_scoped_get_kraken_api_lock, _DISPATCH_PATCH_ATTR, True)


def _invoke_with_credential_scope(broker: Any, call: Callable[[], Any]) -> Any:
    scope_key = _credential_scope_key(broker)
    if not scope_key:
        return call()

    lock = _scoped_lock(scope_key)
    prior_lock = getattr(_SCOPE_LOCAL, "lock", None)
    prior_scope = getattr(_SCOPE_LOCAL, "scope", None)
    _SCOPE_LOCAL.lock = lock
    _SCOPE_LOCAL.scope = scope_key
    try:
        return call()
    finally:
        if prior_lock is None:
            try:
                delattr(_SCOPE_LOCAL, "lock")
            except AttributeError:
                pass
        else:
            _SCOPE_LOCAL.lock = prior_lock
        if prior_scope is None:
            try:
                delattr(_SCOPE_LOCAL, "scope")
            except AttributeError:
                pass
        else:
            _SCOPE_LOCAL.scope = prior_scope


def _patch_lock_dispatch() -> bool:
    global _ORIGINAL_GET_LOCK
    try:
        module = _broker_module()
    except Exception:
        return False

    current = getattr(module, "get_kraken_api_lock", None)
    if not callable(current):
        return False
    if bool(getattr(current, _DISPATCH_PATCH_ATTR, False)):
        return callable(_ORIGINAL_GET_LOCK)

    with _LOCK:
        current = getattr(module, "get_kraken_api_lock", None)
        if not callable(current):
            return False
        if bool(getattr(current, _DISPATCH_PATCH_ATTR, False)):
            return callable(_ORIGINAL_GET_LOCK)
        _ORIGINAL_GET_LOCK = current
        module.get_kraken_api_lock = _scoped_get_kraken_api_lock
    return True


def _chain_has_private_patch(callable_obj: Any) -> bool:
    seen: set[int] = set()
    current = callable_obj
    for _ in range(96):
        if not callable(current) or id(current) in seen:
            return False
        seen.add(id(current))
        if bool(getattr(current, _PRIVATE_PATCH_ATTR, False)):
            return True
        current = getattr(current, "__wrapped__", None)
    return False


def _patch_private_call() -> bool:
    try:
        module = _broker_module()
        cls = getattr(module, "KrakenBroker", None)
    except Exception:
        return False
    if not isinstance(cls, type):
        return False

    current = getattr(cls, "_kraken_private_call", None)
    if not callable(current):
        return False
    if _chain_has_private_patch(current):
        return True
    original = current

    @wraps(original)
    def private_v293(self: Any, *args: Any, **kwargs: Any):
        return _invoke_with_credential_scope(
            self,
            lambda: original(self, *args, **kwargs),
        )

    setattr(private_v293, _PRIVATE_PATCH_ATTR, True)
    setattr(private_v293, "__wrapped__", original)
    cls._kraken_private_call = private_v293
    return True


def _register_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_kraken_credential_lock_scope_v293"] = _READY_FLAG
        return True
    except Exception:
        return False


def reconcile_once() -> dict[str, Any]:
    dispatch_ready = _patch_lock_dispatch()
    private_ready = _patch_private_call()
    with _LOCK:
        scope_count = len(_SCOPE_LOCKS)
    return {
        "ready": bool(dispatch_ready and private_ready),
        "dispatch_ready": bool(dispatch_ready),
        "private_call_patched": bool(private_ready),
        "credential_lock_scopes": int(scope_count),
    }


def install() -> bool:
    manifest_ok = _register_manifest()
    dispatch_ready = _patch_lock_dispatch()
    private_ready = _patch_private_call()
    ready = bool(manifest_ok and dispatch_ready and private_ready)
    os.environ[_READY_FLAG] = "1" if ready else "0"
    log = LOGGER.critical if ready else LOGGER.error
    log(
        "RUNTIME_KRAKEN_CREDENTIAL_LOCK_SCOPE_V293_%s marker=%s ready=%s "
        "same_key_serialized=true distinct_keys_independent=true "
        "unproven_key_uses_global_lock=true outside_private_call_uses_global_lock=true "
        "global_lock_force_release=false lock_bypass=false nonce_generation_unchanged=true "
        "rate_limits_unchanged=true transport_timeout_unchanged=true "
        "mutating_order_semantics_unchanged=true position_success_fabricated=false "
        "capital_ready_granted=false execution_proof_fabricated=false forced_trade=false "
        "forced_activation=false writer_nonce_risk_capital_killswitch_order_fill_gates_unchanged=true "
        "safety_gates_bypassed=false",
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
    "_credential_scope_key",
    "_scoped_lock",
    "_scoped_get_kraken_api_lock",
    "_invoke_with_credential_scope",
    "_patch_lock_dispatch",
    "_patch_private_call",
]
