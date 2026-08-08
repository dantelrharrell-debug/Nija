"""Canonical NIJA runtime launcher v26.

This is the production Python front door used by ``start.sh``. It installs the
canonical broker-startup convergence hook before importing ``main.py`` or the
``bot`` package. That ordering is important: importing any ``bot.*`` module can
execute ``bot.__init__`` and load ``bot.bot_main`` before a late hook has a
chance to wrap writer acquisition.

The launcher does not acquire writer authority, connect brokers, synthesize
capital, force activation, or submit orders. It installs the existing
fail-closed startup, reconnect, capital-readiness, and production-corrective
contracts before application imports.
"""
from __future__ import annotations

import importlib.util
import logging
import os
from pathlib import Path
import runpy
import sys
from types import ModuleType
from typing import Any

MARKER = "20260807-canonical-runtime-launcher-v26-v41-v40-v39-v38-v37-v18"
ROOT = Path(__file__).resolve().parents[1]
V24_PATH = ROOT / "bot" / "canonical_broker_startup_convergence_v24.py"
V32_PATH = ROOT / "bot" / "runtime_execution_convergence_v32.py"
V33_PATH = ROOT / "bot" / "runtime_execution_convergence_v33.py"
V34_PATH = ROOT / "bot" / "capital_readiness_handoff_v34.py"
V35_PATH = ROOT / "bot" / "capital_refresh_stall_guard_v35.py"
V37_PATH = ROOT / "bot" / "capital_refresh_sticky_success_v37_patch.py"
V38_PATH = ROOT / "bot" / "heartbeat_authority_identity_v38_patch.py"
V39_PATH = ROOT / "bot" / "production_readiness_v39_patch.py"
V40_PATH = ROOT / "bot" / "stale_renewal_recovery_v40_patch.py"
V41_PATH = ROOT / "bot" / "activation_lifecycle_handoff_v41_patch.py"
V18_PATH = ROOT / "bot" / "production_corrective_set_v18_patch.py"
V19_PATH = ROOT / "bot" / "entrypoint_writer_epoch_recovery_v19_patch.py"
MAIN_PATH = ROOT / "main.py"
LOGGER = logging.getLogger("nija.canonical_runtime_launcher")


def _load_module_by_path(module_name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load module spec: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _install_runtime_execution_convergence() -> ModuleType:
    if not V32_PATH.is_file():
        raise RuntimeError(f"runtime execution convergence module missing: {V32_PATH}")
    module = _load_module_by_path("nija_runtime_execution_convergence_v32_prebot", V32_PATH)
    installer: Any = getattr(module, "install_import_hook", None) or getattr(module, "install", None)
    if not callable(installer) or not bool(installer()):
        raise RuntimeError("runtime execution convergence v32 installer failed")
    if os.environ.get("NIJA_RUNTIME_EXECUTION_CONVERGENCE_V32_INSTALLED") != "1":
        raise RuntimeError("runtime execution convergence v32 did not attest installed")
    if not V33_PATH.is_file():
        raise RuntimeError(f"runtime execution convergence hotfix missing: {V33_PATH}")
    hotfix = _load_module_by_path("nija_runtime_execution_convergence_v33_prebot", V33_PATH)
    hotfix_installer: Any = getattr(hotfix, "install_import_hook", None) or getattr(hotfix, "install", None)
    if not callable(hotfix_installer) or not bool(hotfix_installer()):
        raise RuntimeError("runtime execution convergence v33 installer failed")
    if os.environ.get("NIJA_RUNTIME_EXECUTION_CONVERGENCE_V33_INSTALLED") != "1":
        raise RuntimeError("runtime execution convergence v33 did not attest installed")
    return module


def _install_capital_readiness_handoff() -> ModuleType:
    if not V34_PATH.is_file():
        raise RuntimeError(f"capital readiness handoff missing: {V34_PATH}")
    module = _load_module_by_path("nija_capital_readiness_handoff_v34_prebot", V34_PATH)
    installer: Any = getattr(module, "install_import_hook", None) or getattr(module, "install", None)
    if not callable(installer) or not bool(installer()):
        raise RuntimeError("capital readiness handoff v34 installer failed")
    if os.environ.get("NIJA_CAPITAL_READINESS_HANDOFF_V34_INSTALLED") != "1":
        raise RuntimeError("capital readiness handoff v34 did not attest installed")
    return module


def _install_capital_refresh_stall_guard() -> ModuleType:
    if not V35_PATH.is_file():
        raise RuntimeError(f"capital refresh stall guard missing: {V35_PATH}")
    module = _load_module_by_path("nija_capital_refresh_stall_guard_v35_prebot", V35_PATH)
    installer: Any = getattr(module, "install_import_hook", None) or getattr(module, "install", None)
    if not callable(installer) or not bool(installer()):
        raise RuntimeError("capital refresh stall guard v36 installer failed")
    if os.environ.get("NIJA_CAPITAL_REFRESH_STALL_GUARD_V36_INSTALLED") != "1":
        raise RuntimeError("capital refresh stall guard v36 did not attest installed")
    return module


def _install_capital_refresh_sticky_success() -> ModuleType:
    if not V37_PATH.is_file():
        raise RuntimeError(f"capital refresh sticky-success hotfix missing: {V37_PATH}")
    module = _load_module_by_path("nija_capital_refresh_sticky_success_v37_prebot", V37_PATH)
    installer: Any = getattr(module, "install_import_hook", None) or getattr(module, "install", None)
    if not callable(installer) or not bool(installer()):
        raise RuntimeError("capital refresh sticky-success v37 installer failed")
    if os.environ.get("NIJA_CAPITAL_REFRESH_STICKY_SUCCESS_V37_INSTALLED") != "1":
        raise RuntimeError("capital refresh sticky-success v37 did not attest installed")
    return module


def _install_heartbeat_authority_identity() -> ModuleType:
    if not V38_PATH.is_file():
        raise RuntimeError(f"heartbeat authority identity v38 missing: {V38_PATH}")
    module = _load_module_by_path("nija_heartbeat_authority_identity_v38_prebot", V38_PATH)
    installer: Any = getattr(module, "install_import_hook", None) or getattr(module, "install", None)
    if not callable(installer) or not bool(installer()):
        raise RuntimeError("heartbeat authority identity v38 installer failed")
    if os.environ.get("NIJA_HEARTBEAT_AUTHORITY_IDENTITY_V38_INSTALLED") != "1":
        raise RuntimeError("heartbeat authority identity v38 did not attest installed")
    return module


def _install_writer_epoch_recovery() -> ModuleType:
    if not V19_PATH.is_file():
        raise RuntimeError(f"writer epoch recovery missing: {V19_PATH}")
    module = _load_module_by_path("nija_writer_epoch_recovery_v19_prebot", V19_PATH)
    installer: Any = getattr(module, "install_import_hook", None) or getattr(module, "install", None)
    if not callable(installer) or not bool(installer()):
        raise RuntimeError("writer epoch recovery v19 installer failed")
    if os.environ.get("NIJA_WRITER_EPOCH_RECOVERY_V19_INSTALLED") != "1":
        raise RuntimeError("writer epoch recovery v19 did not attest installed")
    return module


def _install_production_readiness_v39() -> ModuleType:
    if not V39_PATH.is_file():
        raise RuntimeError(f"production readiness v39 missing: {V39_PATH}")
    module = _load_module_by_path("nija_production_readiness_v39_prebot", V39_PATH)
    installer: Any = getattr(module, "install_import_hook", None) or getattr(module, "install", None)
    if not callable(installer) or not bool(installer()):
        raise RuntimeError("production readiness v39 installer failed")
    if os.environ.get("NIJA_PRODUCTION_READINESS_V39_INSTALLED") != "1":
        raise RuntimeError("production readiness v39 did not attest installed")
    return module


def _install_stale_renewal_recovery_v40() -> ModuleType:
    if not V40_PATH.is_file():
        raise RuntimeError(f"stale renewal recovery v40 missing: {V40_PATH}")
    module = _load_module_by_path("nija_stale_renewal_recovery_v40_prebot", V40_PATH)
    installer: Any = getattr(module, "install_import_hook", None) or getattr(module, "install", None)
    if not callable(installer) or not bool(installer()):
        raise RuntimeError("stale renewal recovery v40 installer failed")
    if os.environ.get("NIJA_STALE_RENEWAL_RECOVERY_V40_INSTALLED") != "1":
        raise RuntimeError("stale renewal recovery v40 did not attest installed")
    return module


def _install_activation_lifecycle_handoff_v41() -> ModuleType:
    if not V41_PATH.is_file():
        raise RuntimeError(f"activation lifecycle handoff v41 missing: {V41_PATH}")
    module = _load_module_by_path("nija_activation_lifecycle_handoff_v41_prebot", V41_PATH)
    installer: Any = getattr(module, "install_import_hook", None) or getattr(module, "install", None)
    if not callable(installer) or not bool(installer()):
        raise RuntimeError("activation lifecycle handoff v41 installer failed")
    if os.environ.get("NIJA_ACTIVATION_LIFECYCLE_HANDOFF_V41_INSTALLED") != "1":
        raise RuntimeError("activation lifecycle handoff v41 did not attest installed")
    return module


def _install_production_corrective_set() -> ModuleType:
    if not V18_PATH.is_file():
        raise RuntimeError(f"production corrective set missing: {V18_PATH}")
    module = _load_module_by_path("nija_production_corrective_set_v18_prebot", V18_PATH)
    installer: Any = getattr(module, "install_import_hook", None) or getattr(module, "install", None)
    if not callable(installer) or not bool(installer()):
        raise RuntimeError("production corrective set v18 installer failed")
    if os.environ.get("NIJA_PRODUCTION_CORRECTIVE_SET_V18_INSTALLED") != "1":
        raise RuntimeError("production corrective set v18 did not attest installed")
    return module


def install_canonical_startup_guard() -> ModuleType:
    if "bot.bot_main" in sys.modules:
        raise RuntimeError("bot.bot_main loaded before canonical launcher guard; startup ordering unsafe")
    module = _load_module_by_path("nija_canonical_broker_startup_convergence_v24_prebot", V24_PATH)
    installer: Any = getattr(module, "install_import_hook", None) or getattr(module, "install", None)
    if not callable(installer) or not bool(installer()):
        raise RuntimeError("canonical startup convergence v24 installer failed")
    if os.environ.get("NIJA_CANONICAL_BROKER_STARTUP_CONVERGENCE_V24_INSTALLED") != "1":
        raise RuntimeError("canonical startup convergence v24 did not attest installed")
    _install_runtime_execution_convergence()
    _install_capital_readiness_handoff()
    _install_capital_refresh_stall_guard()
    _install_capital_refresh_sticky_success()
    _install_heartbeat_authority_identity()
    _install_writer_epoch_recovery()
    _install_production_readiness_v39()
    _install_stale_renewal_recovery_v40()
    _install_activation_lifecycle_handoff_v41()
    _install_production_corrective_set()
    os.environ["NIJA_CANONICAL_RUNTIME_LAUNCHER_V26_READY"] = "1"
    os.environ["NIJA_CANONICAL_RUNTIME_LAUNCHER_V26_MARKER"] = MARKER
    LOGGER.critical("CANONICAL_RUNTIME_LAUNCHER_V26_READY marker=%s bot_main_preloaded=false v24_installed=true v32_installed=true v33_installed=true v34_installed=true v36_installed=true v37_installed=true v38_installed=true v19_installed=true v39_installed=true v40_installed=true v41_installed=true v18_installed=true", MARKER)
    return module


def main() -> int:
    os.environ["NIJA_DEFER_RUNTIME_SITE_HOOKS"] = "1"
    os.environ["NIJA_CANONICAL_ENTRYPOINT_FAST_PATH"] = "1"
    if not MAIN_PATH.is_file():
        raise RuntimeError(f"canonical main.py missing: {MAIN_PATH}")
    install_canonical_startup_guard()
    print("CANONICAL_ENTRYPOINT_FAST_PATH_ARMED marker=20260807-canonical-fast-entrypoint-v41-v40-v39-v38-v37-v18 package_hook_fanout=deferred", flush=True)
    runpy.run_path(str(MAIN_PATH), run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
