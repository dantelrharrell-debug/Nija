"""Converge canonical startup into core registration without bypassing safety gates.

Production release v123 proved writer authority, broker connectivity, balance
hydration, capital, risk, nonce, and position synchronization while bot_main was
still blocked in the legacy SelfHealingStartup compatibility phase.  Canonical
broker prebootstrap already establishes and verifies those prerequisites before
bot_main reaches Step 1, so repeating the legacy recovery sequence can delay core
registration indefinitely while the BootstrapFSM remains LOCK_ACQUIRED.

v124 replaces only that redundant canonical Step-1 wait.  The fast handoff is
allowed when all proof-backed prerequisites are currently true:

* canonical fast-path production launch is active;
* exact distributed writer authority verifies successfully;
* the canonical broker manager contract is initialized;
* at least one connected platform broker exists;
* broker_connected, balance_hydrated, capital_ready, risk_ready, nonce_ready,
  and position_sync_ready are all true; and
* no process-exit/shutdown request is active.

If any proof is absent, the original SelfHealingStartup path runs unchanged.  The
patch never marks strategy/execution/bootstrap readiness, never fabricates nonce
or broker state, never grants execution authority, and keeps trading fail-closed
until the existing post-core activation convergence completes.
"""
from __future__ import annotations

import logging
import os
import sys
import threading
from functools import wraps
from types import ModuleType
from typing import Any

LOGGER = logging.getLogger("nija.canonical_self_healing_handoff_v124")
MARKER = "20260816-canonical-self-healing-handoff-v124"
RELEASE_ID = "20260816-runtime-convergence-v124"
_FLAG = "NIJA_CANONICAL_SELF_HEALING_HANDOFF_V124_INSTALLED"
_PATCH_ATTR = "_nija_canonical_self_healing_handoff_v124"
_WIRING_GUARD_ATTR = "_nija_v124_idempotent_install_guard"
_LOCK = threading.RLock()
_INSTALLED = False
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}
_REQUIRED_READINESS = (
    "broker_connected",
    "balance_hydrated",
    "capital_ready",
    "risk_ready",
    "nonce_ready",
    "position_sync_ready",
)


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in _TRUE


def _canonical_fast_path() -> bool:
    if not (
        _truthy(os.environ.get("NIJA_CANONICAL_ENTRYPOINT_FAST_PATH"))
        and _truthy(os.environ.get("NIJA_DEFER_RUNTIME_SITE_HOOKS"))
        and str(os.environ.get("NIJA_CANONICAL_RUNTIME_LAUNCHER_V26_READY", "")) == "1"
    ):
        return False
    try:
        from bot.runtime_mode import resolve_runtime_mode

        return bool(resolve_runtime_mode().is_live)
    except Exception:
        return False


def _shutdown_requested(module: ModuleType | None = None) -> bool:
    if _truthy(os.environ.get("NIJA_PROCESS_EXIT_REQUESTED")):
        return True
    module = module or sys.modules.get("bot.bot_main") or sys.modules.get("bot_main")
    shutdown = getattr(module, "_shutdown_event", None) if isinstance(module, ModuleType) else None
    return bool(
        shutdown is not None
        and callable(getattr(shutdown, "is_set", None))
        and shutdown.is_set()
    )


def _connected_broker(manager: Any) -> tuple[Any | None, str]:
    brokers = getattr(manager, "platform_brokers", None)
    if callable(brokers):
        brokers = brokers()
    if brokers is None:
        brokers = getattr(manager, "_platform_brokers", {})
    try:
        items = list(dict(brokers or {}).items())
    except Exception:
        items = []

    # Prefer Kraken when healthy because it is the funded primary account in
    # the canonical production path, but any already-connected platform broker
    # remains a valid recovery/fallback surface.
    healthy: list[tuple[int, str, Any]] = []
    for key, broker in items:
        if broker is None or not bool(getattr(broker, "connected", False)):
            continue
        name = str(getattr(key, "value", None) or key or type(broker).__name__).lower()
        priority = 0 if "kraken" in name or "kraken" in type(broker).__name__.lower() else 1
        healthy.append((priority, name, broker))
    if not healthy:
        return None, ""
    healthy.sort(key=lambda row: (row[0], row[1]))
    _, name, broker = healthy[0]
    return broker, name


def _fast_handoff_proof(module: ModuleType | None = None) -> tuple[bool, Any | None, str, str]:
    if not _canonical_fast_path():
        return False, None, "", "canonical_fast_live_path_inactive"
    if _shutdown_requested(module):
        return False, None, "", "shutdown_requested"

    try:
        from bot.execution_authority_context import assert_distributed_writer_authority

        assert_distributed_writer_authority()
    except Exception as exc:
        return False, None, "", f"writer_authority:{type(exc).__name__}:{exc}"

    try:
        from bot import canonical_broker_prebootstrap_v22 as prebootstrap

        manager = prebootstrap._canonical_manager()
        writer_ok, writer_reason = prebootstrap._writer_handoff_proof()
        if not writer_ok:
            return False, None, "", f"writer_handoff:{writer_reason}"
        contract_ok, contract_reason = prebootstrap._manager_contract(manager)
        if not contract_ok:
            return False, None, "", f"manager_contract:{contract_reason}"
        registered, connected, names = prebootstrap._platform_counts(manager)
        if connected < 1:
            return False, None, "", f"connected_broker_missing:registered={registered}:names={names}"
    except Exception as exc:
        return False, None, "", f"prebootstrap:{type(exc).__name__}:{exc}"

    try:
        from bot.readiness_table import snapshot

        readiness = dict(snapshot() or {})
    except Exception as exc:
        return False, None, "", f"readiness_snapshot:{type(exc).__name__}:{exc}"

    missing = [key for key in _REQUIRED_READINESS if not bool(readiness.get(key, False))]
    if missing:
        return False, None, "", "readiness_false:" + ",".join(missing)

    broker, broker_name = _connected_broker(manager)
    if broker is None:
        return False, None, "", "connected_broker_selection_failed"

    return True, broker, broker_name, (
        "proofs_ready:writer,manager,broker,balance,capital,risk,nonce,position_sync"
    )


def _patch_bot_main(module: ModuleType | None = None) -> bool:
    module = module or sys.modules.get("bot.bot_main") or sys.modules.get("bot_main")
    if not isinstance(module, ModuleType):
        try:
            import bot.bot_main as module  # type: ignore[no-redef]
        except Exception:
            return False

    current = getattr(module, "_run_self_healing_startup", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True

    @wraps(current)
    def run_self_healing_startup_v124(*args: Any, **kwargs: Any):
        ok, broker, broker_name, detail = _fast_handoff_proof(module)
        if ok:
            # Explicitly preserve fail-closed execution truth.  Step 2/3 and the
            # existing post-core convergence own all later readiness/authority.
            os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] = "0"
            os.environ["NIJA_EXECUTION_ACTIVE"] = "false"
            LOGGER.critical(
                "CANONICAL_SELF_HEALING_FAST_HANDOFF_V124_READY marker=%s broker=%s detail=%s legacy_recovery_skipped=true core_registration_next=true execution_authority_granted=false safety_gates_unchanged=true",
                MARKER,
                broker_name,
                detail,
            )
            return True, broker, broker_name

        LOGGER.warning(
            "CANONICAL_SELF_HEALING_FAST_HANDOFF_V124_FALLBACK marker=%s detail=%s action=run_original_self_healing execution_authority_granted=false",
            MARKER,
            detail,
        )
        return current(*args, **kwargs)

    setattr(run_self_healing_startup_v124, _PATCH_ATTR, True)
    setattr(run_self_healing_startup_v124, "__wrapped__", current)
    module._run_self_healing_startup = run_self_healing_startup_v124
    return True


def _method_wiring_ready(cls: type) -> bool:
    getattribute = getattr(cls, "__getattribute__", None)
    run_cycle = getattr(cls, "run_cycle", None)
    init = getattr(cls, "__init__", None)
    get_ok = bool(getattr(getattribute, "_nija_apex_backref_getattribute_20260709ah", False))
    run_ok = not callable(run_cycle) or bool(getattr(run_cycle, "_nija_apex_wiring_wrapped_20260709ah", False))
    init_ok = not callable(init) or bool(getattr(init, "_nija_apex_wiring_wrapped_20260709ah", False))
    return get_ok and run_ok and init_ok


def _patch_wiring_reinstall_churn() -> bool:
    """Suppress no-op TradingStrategy reinstall churn while preserving reload repair."""
    try:
        from bot import trading_strategy_apex_wiring_patch as wiring
    except Exception:
        return False

    current = getattr(wiring, "_install_on_module", None)
    if not callable(current):
        return False
    if bool(getattr(current, _WIRING_GUARD_ATTR, False)):
        return True

    @wraps(current)
    def install_on_module_v124(module: ModuleType) -> bool:
        cls = getattr(module, "TradingStrategy", None)
        if isinstance(cls, type) and _method_wiring_ready(cls):
            return True
        return bool(current(module))

    setattr(install_on_module_v124, _WIRING_GUARD_ATTR, True)
    setattr(install_on_module_v124, "__wrapped__", current)
    wiring._install_on_module = install_on_module_v124
    LOGGER.critical(
        "TRADING_STRATEGY_APEX_WIRING_V124_CHURN_GUARD_INSTALLED marker=%s reload_repair_preserved=true no_op_repatch_suppressed=true",
        MARKER,
    )
    return True


def _patch_release_manifest() -> bool:
    try:
        import bot.runtime_release_manifest_patch as manifest
    except Exception:
        return False
    required = getattr(manifest, "_REQUIRED_FLAGS", None)
    if not isinstance(required, dict):
        return False
    required["canonical_self_healing_handoff_v124"] = _FLAG
    manifest.RELEASE_ID = RELEASE_ID
    return True


def install() -> bool:
    global _INSTALLED
    with _LOCK:
        if _INSTALLED and os.environ.get(_FLAG) == "1":
            return True
        bot_main_ok = _patch_bot_main()
        wiring_ok = _patch_wiring_reinstall_churn()
        manifest_ok = _patch_release_manifest()
        if not (bot_main_ok and wiring_ok and manifest_ok):
            os.environ.pop(_FLAG, None)
            _INSTALLED = False
            LOGGER.critical(
                "CANONICAL_SELF_HEALING_HANDOFF_V124_INSTALL_FAILED marker=%s bot_main=%s wiring=%s manifest=%s trading_fail_closed=true",
                MARKER,
                bot_main_ok,
                wiring_ok,
                manifest_ok,
            )
            return False
        os.environ[_FLAG] = "1"
        _INSTALLED = True
        LOGGER.critical(
            "CANONICAL_SELF_HEALING_HANDOFF_V124_INSTALLED marker=%s release=%s proof_backed_fast_handoff=true fallback_preserved=true execution_gates_unchanged=true",
            MARKER,
            RELEASE_ID,
        )
        return True


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "RELEASE_ID",
    "install",
    "install_import_hook",
    "_fast_handoff_proof",
    "_patch_bot_main",
    "_patch_wiring_reinstall_churn",
]
