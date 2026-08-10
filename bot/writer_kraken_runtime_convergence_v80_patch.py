"""Runtime convergence v80 for writer heartbeat and Kraken recovery.

Production on eb2cb141 proved v78's slow-broker capital path but exposed two
remaining liveness gaps:

* the heartbeat generation could remain authoritative while the canonical
  EntrypointWriterAuthority runtime reports ``acquired=False``; v42 then blocks
  re-anchor with ``runtime_not_acquired``;
* Kraken could remain configured/disconnected while Coinbase and OKX are ready.

v80 composes the existing fail-closed authorities rather than inventing state.
For writer recovery it invokes v77's exact-owner-or-canonical-reacquire path
whenever heartbeat health is stale and the runtime is not acquired.  For Kraken
it invokes v44's authenticated reconnect reconciler after writer convergence.
No Redis lock, broker connection, balance, order or fill is fabricated.
"""
from __future__ import annotations

import builtins
import logging
import os
import threading
from typing import Any

from bot import kraken_connection_convergence_v44_patch as v44
from bot import kraken_all_account_supervision_v86 as v86
from bot import writer_authority_reconstitution_v77_patch as v77

LOGGER = logging.getLogger("nija.writer_kraken_runtime_convergence_v80")
MARKER = "20260809-writer-kraken-runtime-convergence-v80"
_LOCK = threading.RLock()
_STOP = threading.Event()
_STARTED = False
_HOOK_FLAG = "_NIJA_WRITER_KRAKEN_RUNTIME_CONVERGENCE_V80_INSTALLED"


def _heartbeat_stale() -> tuple[bool, str]:
    """Use canonical heartbeat health when available; unknown remains fail-closed."""
    try:
        from bot import heartbeat_authority_single_source_patch as heartbeat
        probe = getattr(heartbeat, "check_heartbeat", None)
        if not callable(probe):
            return True, "heartbeat_probe_unavailable"
        result = probe(source="writer_kraken_v80")
        if isinstance(result, tuple):
            healthy = bool(result[0])
        else:
            healthy = bool(result)
        return (not healthy), "heartbeat_stale" if not healthy else "heartbeat_healthy"
    except Exception as exc:
        return True, f"heartbeat_probe_error:{type(exc).__name__}:{exc}"


def reconcile_writer_once() -> dict[str, Any]:
    runtime, runtime_reason = v77._runtime()
    acquired = bool(getattr(runtime, "acquired", False)) if runtime is not None else False
    lost = bool(getattr(runtime, "lost", False)) if runtime is not None else False
    stale, heartbeat_reason = _heartbeat_stale()
    result: dict[str, Any] = {
        "ok": False,
        "acquired": acquired,
        "lost": lost,
        "heartbeat_stale": stale,
        "action": "none",
        "reason": runtime_reason or heartbeat_reason,
    }
    if acquired and not lost and not stale:
        result.update(ok=True, reason="writer_runtime_and_heartbeat_healthy")
        return result

    ok, generation, reason = v77.repair_or_reacquire("writer_kraken_v80")
    result.update(ok=bool(ok), generation=int(generation or 0), reason=str(reason or ""))
    result["action"] = "reconstituted_or_reacquired" if ok else "fail_closed"
    if ok:
        LOGGER.critical(
            "WRITER_V80_CONVERGED marker=%s generation=%s prior_acquired=%s prior_lost=%s prior_heartbeat_stale=%s",
            MARKER,
            generation,
            str(acquired).lower(),
            str(lost).lower(),
            str(stale).lower(),
        )
    else:
        LOGGER.warning(
            "WRITER_V80_BLOCKED marker=%s reason=%s prior_acquired=%s prior_lost=%s heartbeat=%s fail_closed=true",
            MARKER,
            reason,
            str(acquired).lower(),
            str(lost).lower(),
            heartbeat_reason,
        )
    return result


def reconcile_kraken_once() -> dict[str, Any]:
    writer = reconcile_writer_once()
    if not writer.get("ok"):
        return {
            "ok": False,
            "connected": False,
            "action": "blocked",
            "reason": f"writer_not_ready:{writer.get('reason')}",
        }
    state = dict(v44.reconcile_once() or {})
    if state.get("connected"):
        return state
    if state.get("action") in {"recovery_started", "observe"}:
        LOGGER.warning(
            "KRAKEN_V80_RECOVERY_ACTIVE marker=%s action=%s reason=%s fabricated_connected=false",
            MARKER,
            state.get("action"),
            state.get("reason"),
        )
    return state


def reconcile_once() -> dict[str, Any]:
    with _LOCK:
        writer = reconcile_writer_once()
        if not writer.get("ok"):
            return {"writer": writer, "kraken": {"ok": False, "reason": "writer_not_ready"}}
        kraken = dict(v44.reconcile_once() or {})
        kraken_users = dict(v86.reconcile_once() or {})
        return {"writer": writer, "kraken": kraken, "kraken_users": kraken_users}


def _watchdog() -> None:
    try:
        interval = max(2.0, float(os.environ.get("NIJA_RUNTIME_CONVERGENCE_V80_POLL_S", "5") or "5"))
    except (TypeError, ValueError):
        interval = 5.0
    last = ""
    while not _STOP.wait(interval):
        try:
            state = reconcile_once()
            writer = state.get("writer", {})
            kraken = state.get("kraken", {})
            users = state.get("kraken_users", {})
            signature = (
                f"{writer.get('ok')}:{writer.get('reason')}:"
                f"{kraken.get('connected')}:{kraken.get('reason')}:"
                f"{users.get('connected')}:{users.get('disconnected')}:{users.get('reason')}"
            )
            if signature != last:
                log = LOGGER.info if writer.get("ok") and kraken.get("connected") else LOGGER.warning
                log(
                    "RUNTIME_V80_STATE marker=%s writer_ok=%s writer_reason=%s "
                    "kraken_connected=%s kraken_action=%s kraken_reason=%s "
                    "kraken_users_connected=%s kraken_users_disconnected=%s",
                    MARKER,
                    str(bool(writer.get("ok"))).lower(),
                    writer.get("reason"),
                    str(bool(kraken.get("connected"))).lower(),
                    kraken.get("action"),
                    kraken.get("reason"),
                    users.get("connected", 0),
                    users.get("disconnected", 0),
                )
                last = signature
        except Exception as exc:
            LOGGER.warning("RUNTIME_V80_WATCHDOG_ERROR marker=%s error=%s:%s", MARKER, type(exc).__name__, exc)


def install_import_hook() -> bool:
    global _STARTED
    with _LOCK:
        v77.install_import_hook()
        v44.install_import_hook()
        v86.install()
        if not _STARTED:
            _STARTED = True
            threading.Thread(target=_watchdog, name="WriterKrakenRuntimeConvergenceV80", daemon=True).start()
        setattr(builtins, _HOOK_FLAG, True)
        os.environ["NIJA_WRITER_KRAKEN_RUNTIME_CONVERGENCE_V80_INSTALLED"] = "1"
    try:
        reconcile_once()
    except Exception as exc:
        LOGGER.warning("RUNTIME_V80_INITIAL_RECONCILE_FAILED marker=%s error=%s:%s", MARKER, type(exc).__name__, exc)
    LOGGER.critical(
        "WRITER_KRAKEN_RUNTIME_CONVERGENCE_V80_INSTALLED marker=%s "
        "writer_exact_or_reacquire=true kraken_platform_authenticated_recovery=true "
        "kraken_users_authenticated_recovery=true fail_closed=true",
        MARKER,
    )
    return True


def install() -> bool:
    return install_import_hook()


__all__ = ["MARKER", "install", "install_import_hook", "reconcile_once", "reconcile_writer_once", "reconcile_kraken_once"]
