"""Make canonical broker prebootstrap unavoidable across supported entrypoints.

Render has historically launched NIJA through more than one command: the reviewed
``main.py -> bot.bot -> bot.bot_main`` path, the legacy root ``bot.py`` path, and
source-only services that do not contain Docker-installed ``.pth`` hooks. The
v22 canonical prebootstrap correctly initializes the MultiAccountBrokerManager,
but only after its installer has been imported. A legacy path can therefore
reach SelfHealingStartup with a writer lease while the manager FSM is still
uninitialized, leaving capital at zero and the runtime fail-closed forever.

This release installs lightweight import hooks only. It does not initialize a
broker during Python site startup. Instead it wraps SelfHealingStartup.run and
the canonical bot_main functions as those modules are imported. In live mode,
SelfHealingStartup may proceed only after verified writer lineage exists and the
v22 canonical manager preparation succeeds. Non-live execution remains
unchanged. Coinbase diagnostics v5 are also loaded early so malformed Coinbase
credentials are quarantined without blocking healthy independent venues.
"""
from __future__ import annotations

import importlib
import importlib.abc
import importlib.machinery
import importlib.util
import logging
import os
import sys
import threading
import time
from functools import wraps
from pathlib import Path
from types import ModuleType
from typing import Any

logger = logging.getLogger("nija.canonical_broker_startup_convergence")

_MARKER = "20260723-canonical-broker-startup-convergence-v24"
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}
_TARGETS = {
    "bot.bot_main",
    "bot.self_healing_startup",
    "self_healing_startup",
}
_LOCK = threading.RLock()
_INSTALLED = False
_FINDER: "_CanonicalStartupFinder | None" = None
_RUN_WRAP_ATTR = "_nija_canonical_broker_startup_convergence_v24"
_BOT_MAIN_PATCH_ATTR = "_nija_canonical_broker_startup_convergence_bot_main_v24"
_BOT_MAIN_ACQUIRE_WRAP_ATTR = "_nija_canonical_broker_startup_acquire_v30"
_KRAKEN_RECOVERY_STARTED = False
_KRAKEN_RECOVERY_COORDINATOR_STARTED = False


def _truthy(name: str, default: str = "false") -> bool:
    return str(os.environ.get(name, default) or "").strip().lower() in _TRUE


def _live_intent() -> bool:
    if _truthy("DRY_RUN_MODE") or _truthy("PAPER_MODE"):
        return False
    state = str(os.environ.get("NIJA_RUNTIME_TRADING_STATE", "") or "").strip().upper()
    return bool(
        _truthy("LIVE_TRADING")
        or _truthy("LIVE_CAPITAL_VERIFIED")
        or _truthy("NIJA_EXECUTION_ACTIVE")
        or state.startswith("LIVE_")
    )


def _writer_lineage() -> tuple[bool, str]:
    token = str(os.environ.get("NIJA_WRITER_FENCING_TOKEN", "") or "").strip()
    generation = str(os.environ.get("NIJA_WRITER_LEASE_GENERATION", "") or "").strip()
    lease = _truthy("NIJA_WRITER_LEASE_ACQUIRED") or _truthy(
        "NIJA_PREBOT_WRITER_AUTHORITY_READY"
    )
    if not token:
        return False, "fencing_token_missing"
    if not generation:
        return False, "lease_generation_missing"
    if not lease:
        return False, "lease_not_acquired"
    return True, f"lineage_ready generation={generation}"


def _load_v22_module() -> ModuleType:
    existing = sys.modules.get("nija_canonical_broker_prebootstrap_v22")
    if isinstance(existing, ModuleType):
        return existing

    path = Path(__file__).resolve().with_name("canonical_broker_prebootstrap_v22.py")
    spec = importlib.util.spec_from_file_location(
        "nija_canonical_broker_prebootstrap_v22", path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load canonical prebootstrap module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _install_secondary_diagnostics_v5() -> bool:
    try:
        module = importlib.import_module("secondary_venue_runtime_diagnostics")
        installer = getattr(module, "install", None)
        if callable(installer):
            installer()
        logger.warning(
            "CANONICAL_STARTUP_SECONDARY_DIAGNOSTICS_READY marker=%s "
            "release=20260723-secondary-runtime-diagnostics-v5",
            _MARKER,
        )
        return True
    except Exception as exc:
        # Coinbase remains fail-closed. A diagnostics import failure must not
        # create false readiness or block installation of broker-manager
        # convergence for Kraken/OKX.
        logger.exception(
            "CANONICAL_STARTUP_SECONDARY_DIAGNOSTICS_FAILED marker=%s err=%s:%s",
            _MARKER,
            type(exc).__name__,
            exc,
        )
        return False


def _kraken_credentials_configured() -> bool:
    key = (
        os.environ.get("KRAKEN_PLATFORM_API_KEY")
        or os.environ.get("KRAKEN_API_KEY")
        or ""
    ).strip()
    secret = (
        os.environ.get("KRAKEN_PLATFORM_API_SECRET")
        or os.environ.get("KRAKEN_API_SECRET")
        or ""
    ).strip()
    disabled = str(
        os.environ.get("NIJA_DISABLE_KRAKEN")
        or os.environ.get("KRAKEN_EXECUTION_DISABLED")
        or "false"
    ).strip().lower() in _TRUE
    return bool(key and secret and not disabled)


def _resolve_or_register_kraken_broker(manager: Any) -> tuple[Any, Any, Any]:
    """Return the canonical Kraken broker, repairing only a missing registration."""
    broker_module = importlib.import_module("bot.broker_manager")
    manager_module = importlib.import_module("bot.multi_account_broker_manager")
    broker_type = getattr(broker_module, "BrokerType").KRAKEN
    broker = getattr(manager, "_platform_brokers", {}).get(broker_type)
    if broker is None:
        broker = getattr(broker_module, "get_platform_broker")("kraken")
    if broker is None:
        broker_cls = getattr(broker_module, "KrakenBroker")
        account_type = getattr(broker_module, "AccountType").PLATFORM
        broker = broker_cls(account_type=account_type)
        register = getattr(manager, "register_platform_broker_instance", None)
        if not callable(register):
            raise RuntimeError("canonical Kraken registration method unavailable")
        register(
            broker_type,
            broker,
            mark_connected_state=False,
            allow_recovery_registration=True,
        )
        logger.critical(
            "KRAKEN_AUTHENTICATED_RECOVERY_REGISTERED "
            "marker=20260726-kraken-registration-recovery-v30 "
            "source=canonical_manager late_registration=true"
        )
    return broker, broker_type, manager_module


def _start_kraken_authenticated_recovery(manager: Any) -> bool:
    """Reconnect the registered platform Kraken broker before live cycles start.

    The legacy reconnect method is normally called from a trading cycle. When
    Kraken fails its first startup handshake, LIVE_ACTIVE may not exist yet, so
    that cycle can never provide the retry. This writer-scoped recovery closes
    that dependency without creating another broker or bypassing authentication.
    """
    global _KRAKEN_RECOVERY_STARTED
    with _LOCK:
        if _KRAKEN_RECOVERY_STARTED or not _kraken_credentials_configured():
            return _KRAKEN_RECOVERY_STARTED
        _KRAKEN_RECOVERY_STARTED = True

    def recover() -> None:
        marker = "20260725-kraken-authenticated-recovery-v29"
        deadline = time.monotonic() + max(
            120.0,
            float(os.environ.get("NIJA_KRAKEN_RECOVERY_WINDOW_S", "1200") or 1200),
        )
        interval = max(
            10.0,
            float(os.environ.get("NIJA_KRAKEN_RECOVERY_INTERVAL_S", "30") or 30),
        )
        attempt = 0
        while time.monotonic() < deadline:
            lineage_ready, lineage_reason = _writer_lineage()
            if not lineage_ready:
                logger.warning(
                    "KRAKEN_AUTHENTICATED_RECOVERY_WAITING marker=%s reason=%s "
                    "retry_s=%.1f",
                    marker,
                    lineage_reason,
                    interval,
                )
                time.sleep(interval)
                continue
            try:
                broker_module = importlib.import_module("bot.broker_manager")
                broker, broker_type, manager_module = _resolve_or_register_kraken_broker(
                    manager
                )

                fsm = getattr(broker_module, "_KRAKEN_STARTUP_FSM", None)
                broker_connected = bool(getattr(broker, "connected", False))
                # Use broker.connected as the authoritative live-connection check.
                # fsm.is_connected is a startup-only latch and stays True after
                # the initial handshake, so it must not be used alone — a broker
                # that disconnected post-startup has connected=False but
                # fsm.is_connected=True, and still needs reconnection.
                if broker_connected:
                    register = getattr(
                        broker_module, "register_platform_broker", None
                    )
                    if callable(register):
                        register("kraken", broker, connected=True)
                    transition = getattr(manager, "_transition_platform_state", None)
                    state = getattr(manager_module, "ConnectionState", None)
                    if callable(transition) and state is not None:
                        transition(broker_type, state.CONNECTED)
                    ready_hook = getattr(manager, "on_broker_ready", None)
                    if callable(ready_hook):
                        ready_hook("kraken", broker.get_account_balance)
                    refresh = getattr(manager, "refresh_capital_authority", None)
                    if callable(refresh):
                        try:
                            refresh(trigger="kraken_authenticated_recovery")
                        except Exception as refresh_exc:
                            logger.warning(
                                "KRAKEN_AUTHENTICATED_RECOVERY_CAPITAL_REFRESH_PENDING "
                                "marker=%s error=%s:%s",
                                marker,
                                type(refresh_exc).__name__,
                                refresh_exc,
                            )
                    try:
                        state_module = importlib.import_module("bot.trading_state_machine")
                        state_machine = state_module.get_state_machine()
                        state_machine.maybe_auto_activate()
                    except Exception as activation_exc:
                        logger.warning(
                            "KRAKEN_AUTHENTICATED_RECOVERY_ACTIVATION_PENDING "
                            "marker=%s error=%s:%s",
                            marker,
                            type(activation_exc).__name__,
                            activation_exc,
                        )
                    # Publish the updated activation state immediately so the
                    # three-venue readiness flags (NIJA_KRAKEN_ACTIVATED,
                    # NIJA_KRAKEN_TRADING_READY) reflect CONNECTED without
                    # waiting for the next periodic poll cycle.
                    try:
                        readiness_module = importlib.import_module(
                            "three_venue_execution_readiness"
                        )
                        publish = getattr(readiness_module, "publish_once", None)
                        if callable(publish):
                            publish(force=True)
                    except Exception as pub_exc:
                        logger.warning(
                            "KRAKEN_AUTHENTICATED_RECOVERY_READINESS_PUBLISH_PENDING "
                            "marker=%s error=%s:%s",
                            marker,
                            type(pub_exc).__name__,
                            pub_exc,
                        )
                    os.environ["NIJA_KRAKEN_AUTHENTICATED_RECOVERY_READY"] = "1"
                    logger.critical(
                        "KRAKEN_AUTHENTICATED_RECOVERY_READY marker=%s "
                        "attempt=%d connected=true capital_rechecked=true",
                        marker,
                        attempt,
                    )
                    return

                if bool(getattr(fsm, "is_connecting", False)):
                    time.sleep(interval)
                    continue

                attempt += 1
                logger.warning(
                    "KRAKEN_AUTHENTICATED_RECOVERY_ATTEMPT marker=%s attempt=%d "
                    "writer_scoped=true",
                    marker,
                    attempt,
                )
                reset = getattr(fsm, "reset", None)
                if callable(reset):
                    reset()
                begin = getattr(manager, "begin_platform_connection", None)
                if callable(begin):
                    begin(broker_type)
                connected = bool(broker.connect())
                if connected:
                    continue
                failed = getattr(manager, "mark_platform_failed", None)
                if callable(failed):
                    failed(broker_type)
            except Exception as exc:
                logger.error(
                    "KRAKEN_AUTHENTICATED_RECOVERY_FAILED marker=%s attempt=%d "
                    "error=%s:%s",
                    marker,
                    attempt,
                    type(exc).__name__,
                    exc,
                )
            time.sleep(interval)

        os.environ["NIJA_KRAKEN_AUTHENTICATED_RECOVERY_READY"] = "0"
        logger.error(
            "KRAKEN_AUTHENTICATED_RECOVERY_EXPIRED marker=%s attempts=%d "
            "authentication_remains_fail_closed=true",
            marker,
            attempt,
        )
        # Reset the one-shot guard so a new recovery cycle can be triggered
        # if Kraken disconnects again after this window expires.
        global _KRAKEN_RECOVERY_STARTED
        with _LOCK:
            _KRAKEN_RECOVERY_STARTED = False
        logger.warning(
            "KRAKEN_AUTHENTICATED_RECOVERY_RESET marker=%s "
            "recovery_restartable=true",
            marker,
        )

    threading.Thread(
        target=recover,
        name="KrakenAuthenticatedRecoveryV29",
        daemon=True,
    ).start()
    logger.warning(
        "KRAKEN_AUTHENTICATED_RECOVERY_STARTED "
        "marker=20260725-kraken-authenticated-recovery-v29"
    )
    return True



def _start_kraken_recovery_coordinator() -> bool:
    """Close the timing gap between import-hook install and writer acquisition.

    A rolling Render deployment can install this module before the writer
    fencing environment is published.  The coordinator waits for that lineage
    instead of relying on a single wrapper callback.  It never connects a
    broker until writer authority and the canonical manager FSM are both ready.
    """
    global _KRAKEN_RECOVERY_COORDINATOR_STARTED
    with _LOCK:
        if _KRAKEN_RECOVERY_COORDINATOR_STARTED:
            return True
        _KRAKEN_RECOVERY_COORDINATOR_STARTED = True

    def coordinate() -> None:
        marker = "20260726-kraken-recovery-coordinator-v31"
        deadline = time.monotonic() + max(
            120.0,
            float(
                os.environ.get(
                    "NIJA_KRAKEN_RECOVERY_COORDINATOR_WINDOW_S", "1800"
                )
                or 1800
            ),
        )
        interval = max(
            2.0,
            float(
                os.environ.get(
                    "NIJA_KRAKEN_RECOVERY_COORDINATOR_INTERVAL_S", "5"
                )
                or 5
            ),
        )
        last_reason = ""
        while time.monotonic() < deadline:
            if _KRAKEN_RECOVERY_STARTED:
                return
            if not _kraken_credentials_configured():
                reason = "credentials_not_configured_or_explicitly_disabled"
            else:
                lineage_ready, lineage_reason = _writer_lineage()
                if not lineage_ready:
                    reason = lineage_reason
                else:
                    try:
                        _prepare_canonical_manager()
                        if _KRAKEN_RECOVERY_STARTED:
                            logger.critical(
                                "KRAKEN_RECOVERY_COORDINATOR_HANDOFF marker=%s "
                                "writer_lineage=true recovery_started=true",
                                marker,
                            )
                            return
                        reason = "canonical_manager_ready_recovery_not_started"
                    except Exception as exc:
                        reason = f"{type(exc).__name__}:{exc}"
            if reason != last_reason:
                logger.warning(
                    "KRAKEN_RECOVERY_COORDINATOR_WAITING marker=%s reason=%s "
                    "retry_s=%.1f",
                    marker,
                    reason,
                    interval,
                )
                last_reason = reason
            time.sleep(interval)

        os.environ["NIJA_KRAKEN_AUTHENTICATED_RECOVERY_READY"] = "0"
        logger.error(
            "KRAKEN_RECOVERY_COORDINATOR_EXPIRED marker=%s "
            "recovery_started=%s trading_remains_fail_closed=true",
            marker,
            _KRAKEN_RECOVERY_STARTED,
        )
        # Reset the one-shot guard so a new coordinator cycle can be triggered
        # if the deployment retries before the environment is fully ready.
        with _LOCK:
            _KRAKEN_RECOVERY_COORDINATOR_STARTED = False
        logger.warning(
            "KRAKEN_RECOVERY_COORDINATOR_RESET marker=%s "
            "coordinator_restartable=true",
            marker,
        )

    threading.Thread(
        target=coordinate,
        name="KrakenRecoveryCoordinatorV31",
        daemon=True,
    ).start()
    logger.warning(
        "KRAKEN_RECOVERY_COORDINATOR_STARTED "
        "marker=20260726-kraken-recovery-coordinator-v31"
    )
    return True


def _prepare_canonical_manager() -> Any:
    lineage_ready, lineage_reason = _writer_lineage()
    if not lineage_ready:
        raise RuntimeError(
            "canonical broker preparation requires verified writer lineage: "
            + lineage_reason
        )

    v22 = _load_v22_module()
    prepare = getattr(v22, "prepare_canonical_broker_runtime", None)
    if not callable(prepare):
        raise RuntimeError("v22 canonical broker preparation function unavailable")
    manager = prepare()
    if not bool(getattr(manager, "_fsm_initialized", False)):
        raise RuntimeError("canonical broker manager returned without initialized FSM")

    logger.critical(
        "CANONICAL_BROKER_STARTUP_CONVERGENCE_V24_READY marker=%s generation=%s",
        _MARKER,
        os.environ.get("NIJA_WRITER_LEASE_GENERATION", "unknown"),
    )
    os.environ["NIJA_CANONICAL_BROKER_STARTUP_CONVERGENCE_V24_READY"] = "1"
    _start_kraken_authenticated_recovery(manager)
    return manager


def _patch_self_healing_module(module: ModuleType) -> bool:
    cls = getattr(module, "SelfHealingStartup", None)
    current = getattr(cls, "run", None) if cls is not None else None
    if not callable(current):
        return False
    if bool(getattr(current, _RUN_WRAP_ATTR, False)):
        return True

    @wraps(current)
    def guarded_run(self: Any, *args: Any, **kwargs: Any):
        if _live_intent():
            lineage_ready, lineage_reason = _writer_lineage()
            if not lineage_ready:
                os.environ[
                    "NIJA_CANONICAL_BROKER_STARTUP_CONVERGENCE_V24_READY"
                ] = "0"
                logger.critical(
                    "CANONICAL_BROKER_STARTUP_CONVERGENCE_V24_BLOCKED "
                    "marker=%s reason=%s trading_remains_fail_closed=true",
                    _MARKER,
                    lineage_reason,
                )
                raise RuntimeError(
                    "SelfHealingStartup blocked before canonical broker preparation: "
                    + lineage_reason
                )
            try:
                _start_kraken_recovery_coordinator()
                _prepare_canonical_manager()
            except Exception as exc:
                os.environ[
                    "NIJA_CANONICAL_BROKER_STARTUP_CONVERGENCE_V24_READY"
                ] = "0"
                logger.critical(
                    "CANONICAL_BROKER_STARTUP_CONVERGENCE_V24_FAILED "
                    "marker=%s err=%s:%s trading_remains_fail_closed=true",
                    _MARKER,
                    type(exc).__name__,
                    exc,
                    exc_info=True,
                )
                raise
        return current(self, *args, **kwargs)

    setattr(guarded_run, _RUN_WRAP_ATTR, True)
    setattr(guarded_run, "__wrapped__", current)
    setattr(cls, "run", guarded_run)
    logger.critical(
        "CANONICAL_BROKER_STARTUP_CONVERGENCE_V24_SELF_HEALING_PATCHED "
        "marker=%s module=%s",
        _MARKER,
        module.__name__,
    )
    return True


def _patch_bot_main_module(module: ModuleType) -> bool:
    if bool(getattr(module, _BOT_MAIN_PATCH_ATTR, False)):
        return True
    v22 = _load_v22_module()
    patch_acquire = getattr(v22, "_patch_writer_acquire", None)
    patch_main = getattr(v22, "_patch_main", None)
    if not callable(patch_acquire) or not callable(patch_main):
        return False
    acquire_ok = bool(patch_acquire(module))
    main_ok = bool(patch_main(module))
    current_acquire = getattr(module, "_acquire_writer_authority_before_nonce", None)
    if acquire_ok and callable(current_acquire) and not bool(
        getattr(current_acquire, _BOT_MAIN_ACQUIRE_WRAP_ATTR, False)
    ):
        @wraps(current_acquire)
        def converged_acquire(*args: Any, **kwargs: Any) -> bool:
            acquired = bool(current_acquire(*args, **kwargs))
            if not acquired:
                return False
            try:
                _start_kraken_recovery_coordinator()
                _prepare_canonical_manager()
                return True
            except Exception as exc:
                os.environ["NIJA_CANONICAL_BROKER_STARTUP_CONVERGENCE_V24_READY"] = "0"
                logger.critical(
                    "CANONICAL_BROKER_STARTUP_CONVERGENCE_V30_FAILED "
                    "marker=20260726-kraken-registration-recovery-v30 "
                    "error=%s:%s trading_remains_fail_closed=true",
                    type(exc).__name__,
                    exc,
                    exc_info=True,
                )
                release = getattr(module, "_release_writer_authority", None)
                if callable(release):
                    try:
                        release()
                    except Exception:
                        logger.exception(
                            "CANONICAL_BROKER_STARTUP_CONVERGENCE_V30_RELEASE_FAILED "
                            "marker=20260726-kraken-registration-recovery-v30"
                        )
                return False

        setattr(converged_acquire, _BOT_MAIN_ACQUIRE_WRAP_ATTR, True)
        v22_attr = getattr(v22, "_ACQUIRE_WRAP_ATTR", "")
        if v22_attr:
            setattr(converged_acquire, v22_attr, True)
        setattr(converged_acquire, "__wrapped__", current_acquire)
        setattr(module, "_acquire_writer_authority_before_nonce", converged_acquire)
        logger.critical(
            "CANONICAL_BROKER_STARTUP_CONVERGENCE_V30_ACQUIRE_PATCHED "
            "marker=20260726-kraken-registration-recovery-v30 module=%s",
            module.__name__,
        )
    final_acquire = getattr(module, "_acquire_writer_authority_before_nonce", None)
    recovery_trigger = bool(
        not callable(current_acquire)
        or (
            callable(final_acquire)
            and getattr(final_acquire, _BOT_MAIN_ACQUIRE_WRAP_ATTR, False)
        )
    )
    ready = bool(acquire_ok and main_ok and recovery_trigger)
    setattr(module, _BOT_MAIN_PATCH_ATTR, ready)
    logger.critical(
        "CANONICAL_BROKER_STARTUP_CONVERGENCE_V24_BOT_MAIN_PATCHED "
        "marker=%s acquire=%s main=%s recovery_trigger=%s",
        _MARKER,
        acquire_ok,
        main_ok,
        ready,
    )
    return ready


def _patch_module(module: ModuleType) -> bool:
    if module.__name__ == "bot.bot_main":
        return _patch_bot_main_module(module)
    if module.__name__ in {"bot.self_healing_startup", "self_healing_startup"}:
        return _patch_self_healing_module(module)
    return False


class _CanonicalStartupLoader(importlib.abc.Loader):
    def __init__(self, wrapped: importlib.abc.Loader) -> None:
        self._wrapped = wrapped

    def create_module(self, spec):  # type: ignore[no-untyped-def]
        creator = getattr(self._wrapped, "create_module", None)
        return creator(spec) if callable(creator) else None

    def exec_module(self, module: ModuleType) -> None:
        executor = getattr(self._wrapped, "exec_module", None)
        if not callable(executor):
            raise ImportError(f"wrapped loader cannot execute {module.__name__}")
        executor(module)
        _patch_module(module)


class _CanonicalStartupFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname: str, path=None, target=None):  # type: ignore[no-untyped-def]
        if fullname not in _TARGETS:
            return None
        spec = importlib.machinery.PathFinder.find_spec(fullname, path)
        if spec is None or spec.loader is None:
            return None
        if isinstance(spec.loader, _CanonicalStartupLoader):
            return spec
        spec.loader = _CanonicalStartupLoader(spec.loader)
        return spec


def _patch_loaded_modules() -> None:
    for name in tuple(_TARGETS):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            try:
                _patch_module(module)
            except Exception:
                logger.exception(
                    "CANONICAL_BROKER_STARTUP_CONVERGENCE_V24_LOADED_PATCH_FAILED "
                    "marker=%s module=%s",
                    _MARKER,
                    name,
                )


def install_import_hook() -> bool:
    global _INSTALLED, _FINDER
    with _LOCK:
        _install_secondary_diagnostics_v5()
        _patch_loaded_modules()
        if _FINDER is None:
            _FINDER = _CanonicalStartupFinder()
        if not any(item is _FINDER for item in sys.meta_path):
            sys.meta_path.insert(0, _FINDER)
        _INSTALLED = True
        os.environ["NIJA_CANONICAL_BROKER_STARTUP_CONVERGENCE_V24_INSTALLED"] = "1"
        logger.critical(
            "CANONICAL_BROKER_STARTUP_CONVERGENCE_V24_INSTALLED "
            "marker=%s import_hook=true",
            _MARKER,
        )
        print(
            "[NIJA-PRINT] CANONICAL_BROKER_STARTUP_CONVERGENCE_V24_INSTALLED "
            f"marker={_MARKER}",
            flush=True,
        )
        return True


def install() -> bool:
    return install_import_hook()


__all__ = [
    "install",
    "install_import_hook",
    "_live_intent",
    "_writer_lineage",
    "_prepare_canonical_manager",
    "_kraken_credentials_configured",
    "_start_kraken_authenticated_recovery",
    "_start_kraken_recovery_coordinator",
    "_patch_self_healing_module",
    "_patch_bot_main_module",
]
