"""Make canonical broker prebootstrap unavoidable across supported entrypoints.

Render has historically launched NIJA through more than one command: the reviewed
``main.py -> bot.bot -> bot.bot_main`` path, the legacy root ``bot.py`` path, and
source-only services that do not contain Docker-installed ``.pth`` hooks.  The
v22 canonical prebootstrap correctly initializes the MultiAccountBrokerManager,
but only after its installer has been imported.  A legacy path can therefore
reach SelfHealingStartup with a writer lease while the manager FSM is still
uninitialized, leaving capital at zero and the runtime fail-closed forever.

This release installs lightweight import hooks only.  It does not initialize a
broker during Python site startup.  Instead it wraps SelfHealingStartup.run and
the canonical bot_main functions as those modules are imported.  In live mode,
SelfHealingStartup may proceed only after verified writer lineage exists and the
v22 canonical manager preparation succeeds.  Non-live execution remains
unchanged.  Coinbase diagnostics v5 are also loaded early so malformed Coinbase
credentials are quarantined without blocking healthy independent venues.
"""
from __future__ import annotations

import importlib
import importlib.abc
import importlib.machinery
import logging
import os
import sys
import threading
from functools import wraps
from pathlib import Path
from types import ModuleType
from typing import Any, Callable

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
            "CANONICAL_STARTUP_SECONDARY_DIAGNOSTICS_READY marker=%s release=20260723-secondary-runtime-diagnostics-v5",
            _MARKER,
        )
        return True
    except Exception as exc:
        # Coinbase remains fail-closed.  A diagnostics import failure must not
        # create false readiness or block the installation of broker-manager
        # convergence for Kraken/OKX.
        logger.exception(
            "CANONICAL_STARTUP_SECONDARY_DIAGNOSTICS_FAILED marker=%s err=%s:%s",
            _MARKER,
            type(exc).__name__,
            exc,
        )
        return False


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
                    "CANONICAL_BROKER_STARTUP_CONVERGENCE_V24_BLOCKED marker=%s reason=%s trading_remains_fail_closed=true",
                    _MARKER,
                    lineage_reason,
                )
                raise RuntimeError(
                    "SelfHealingStartup blocked before canonical broker preparation: "
                    + lineage_reason
                )
            try:
                _prepare_canonical_manager()
            except Exception as exc:
                os.environ[
                    "NIJA_CANONICAL_BROKER_STARTUP_CONVERGENCE_V24_READY"
                ] = "0"
                logger.critical(
                    "CANONICAL_BROKER_STARTUP_CONVERGENCE_V24_FAILED marker=%s err=%s:%s trading_remains_fail_closed=true",
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
        "CANONICAL_BROKER_STARTUP_CONVERGENCE_V24_SELF_HEALING_PATCHED marker=%s module=%s",
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
    ready = acquire_ok and main_ok
    setattr(module, _BOT_MAIN_PATCH_ATTR, ready)
    logger.critical(
        "CANONICAL_BROKER_STARTUP_CONVERGENCE_V24_BOT_MAIN_PATCHED marker=%s acquire=%s main=%s",
        _MARKER,
        acquire_ok,
        main_ok,
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
                    "CANONICAL_BROKER_STARTUP_CONVERGENCE_V24_LOADED_PATCH_FAILED marker=%s module=%s",
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
            "CANONICAL_BROKER_STARTUP_CONVERGENCE_V24_INSTALLED marker=%s import_hook=true",
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
    "_patch_self_healing_module",
    "_patch_bot_main_module",
]
