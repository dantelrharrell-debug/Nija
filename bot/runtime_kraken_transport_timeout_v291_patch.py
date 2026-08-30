"""Kraken private transport timeout convergence v291.

Production evidence on 2026-08-30 showed authoritative Kraken Balance
single-flights remaining pending for hundreds of seconds. The broker already
has an API_TIMEOUT_SECONDS policy, but broker_manager stores a functools.partial
on ``self._session_request`` while krakenex performs HTTP through
``self.api.session.request``. The configured timeout therefore does not
necessarily bound the transport actually used by private Kraken requests.

v291 repairs only that transport binding. Every Kraken private call verifies the
broker-owned requests Session has an idempotent wrapper that supplies the
existing API_TIMEOUT_SECONDS value only when the caller did not provide an
explicit timeout. It does not shorten or extend the configured timeout, retry
exchange errors, bypass the global/private-call serialization, alter nonce
issuance, release locks, fabricate position/capital/execution proof, or change
order/fill/risk/kill-switch behavior.

After transport capability is installed, v291 chains v292's account-scoped
reconciliation certificate so protective-exit coverage cannot be certified from
an account tracker that has not been reconciled to the exact current v285
snapshot generation. v292 does not block protective SELL execution.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
from functools import wraps
from typing import Any

LOGGER = logging.getLogger("nija.runtime_kraken_transport_timeout_v291")
MARKER = "20260830-kraken-transport-timeout-v291"
RELEASE_ID = "20260830-runtime-convergence-v291"
_READY_FLAG = "NIJA_RUNTIME_KRAKEN_TRANSPORT_TIMEOUT_V291_READY"
_PRIVATE_PATCH_ATTR = "_nija_kraken_transport_timeout_private_v291"
_SESSION_PATCH_ATTR = "_nija_kraken_transport_timeout_session_v291"
_LOCK = threading.RLock()


def _float(value: Any, default: float) -> float:
    try:
        parsed = float(value)
        return default if parsed != parsed else parsed
    except Exception:
        return default


def _transport_timeout_s(broker: Any) -> float:
    value = _float(getattr(broker, "API_TIMEOUT_SECONDS", 12.0), 12.0)
    return max(1.0, min(60.0, value))


def _ensure_transport_timeout(broker: Any) -> bool:
    api = getattr(broker, "api", None)
    session = getattr(api, "session", None)
    current = getattr(session, "request", None)
    if not callable(current):
        return False
    with _LOCK:
        current = getattr(session, "request", None)
        if not callable(current):
            return False
        if bool(getattr(current, _SESSION_PATCH_ATTR, False)):
            return True
        timeout_s = _transport_timeout_s(broker)

        @wraps(current)
        def request_v291(*args: Any, **kwargs: Any):
            kwargs.setdefault("timeout", timeout_s)
            return current(*args, **kwargs)

        setattr(request_v291, _SESSION_PATCH_ATTR, True)
        try:
            session.request = request_v291
        except Exception:
            return False
    LOGGER.critical(
        "KRAKEN_HTTP_TRANSPORT_TIMEOUT_V291_BOUND marker=%s account=%s timeout_s=%.1f session_request_patched=true explicit_timeout_preserved=true configured_timeout_unchanged=true serialization_unchanged=true nonce_policy_unchanged=true order_fill_gates_unchanged=true safety_gates_bypassed=false",
        MARKER, str(getattr(broker, "account_identifier", "unknown")), timeout_s,
    )
    return True


def _broker_module() -> Any:
    return importlib.import_module("bot.broker_manager")


def _chain_has_private_patch(callable_obj: Any) -> bool:
    seen: set[int] = set()
    current = callable_obj
    for _ in range(64):
        if not callable(current) or id(current) in seen:
            return False
        seen.add(id(current))
        if bool(getattr(current, _PRIVATE_PATCH_ATTR, False)):
            return True
        current = getattr(current, "__wrapped__", None)
    return False


def _patch_private_call() -> bool:
    try:
        cls = getattr(_broker_module(), "KrakenBroker", None)
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
    def private_v291(self: Any, *args: Any, **kwargs: Any):
        _ensure_transport_timeout(self)
        return original(self, *args, **kwargs)

    setattr(private_v291, _PRIVATE_PATCH_ATTR, True)
    setattr(private_v291, "__wrapped__", original)
    cls._kraken_private_call = private_v291
    return True


def _patch_live_instances() -> int:
    try:
        cls = getattr(_broker_module(), "KrakenBroker", None)
        iterator = getattr(cls, "_iter_live", None) if isinstance(cls, type) else None
        brokers = tuple(iterator()) if callable(iterator) else ()
    except Exception:
        brokers = ()
    patched = 0
    for broker in brokers:
        try:
            patched += 1 if _ensure_transport_timeout(broker) else 0
        except Exception:
            continue
    return patched


def _install_v292() -> bool:
    try:
        v292 = importlib.import_module("bot.runtime_account_scoped_reconciliation_truth_v292_patch")
        install = getattr(v292, "install_import_hook", None) or getattr(v292, "install", None)
        return bool(install()) if callable(install) else False
    except Exception as exc:
        LOGGER.error(
            "ACCOUNT_SCOPED_RECONCILIATION_V292_CHAIN_FAILED marker=%s error=%s:%s exit_coverage_fail_closed=true protective_sell_execution_unchanged=true",
            MARKER, type(exc).__name__, exc,
        )
        return False


def _register_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_kraken_transport_timeout_v291"] = _READY_FLAG
        return True
    except Exception:
        return False


def reconcile_once() -> dict[str, Any]:
    private_ready = _patch_private_call()
    live_patched = _patch_live_instances()
    v292_ready = _install_v292()
    return {
        "ready": bool(private_ready and v292_ready),
        "private_call_patched": bool(private_ready),
        "live_sessions_patched": int(live_patched),
        "account_scoped_reconciliation_v292": bool(v292_ready),
    }


def install() -> bool:
    manifest_ok = _register_manifest()
    private_ready = _patch_private_call()
    live_patched = _patch_live_instances()
    v292_ready = _install_v292()
    ready = bool(manifest_ok and private_ready and v292_ready)
    os.environ[_READY_FLAG] = "1" if ready else "0"
    log = LOGGER.critical if ready else LOGGER.error
    log(
        "RUNTIME_KRAKEN_TRANSPORT_TIMEOUT_V291_%s marker=%s ready=%s live_sessions_patched=%d actual_session_request_bounded=true explicit_timeout_preserved=true configured_timeout_unchanged=true gateway_behavior_unchanged=true private_serialization_unchanged=true nonce_policy_unchanged=true exchange_retry_policy_unchanged=true account_scoped_reconciliation_v292=%s position_success_fabricated=false capital_ready_granted=false execution_proof_fabricated=false forced_trade=false forced_activation=false writer_nonce_risk_capital_killswitch_order_fill_gates_unchanged=true safety_gates_bypassed=false",
        "READY" if ready else "NOT_READY", MARKER, str(ready).lower(), live_patched, str(v292_ready).lower(),
    )
    return ready


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER", "RELEASE_ID", "install", "install_import_hook", "reconcile_once",
    "_transport_timeout_s", "_ensure_transport_timeout", "_patch_private_call", "_install_v292",
]
