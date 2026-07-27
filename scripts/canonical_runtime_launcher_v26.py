"""Canonical NIJA runtime launcher v26.

This is the production Python front door used by ``start.sh``. It installs the
canonical broker-startup convergence hook before importing ``main.py`` or the
``bot`` package. That ordering is important: importing any ``bot.*`` module can
execute ``bot.__init__`` and load ``bot.bot_main`` before a late hook has a
chance to wrap writer acquisition.

The launcher does not acquire writer authority, connect brokers, synthesize
capital, force activation, or submit orders. It installs the existing
fail-closed startup, reconnect, and capital-readiness convergence contracts
before application imports.
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

MARKER = "20260727-canonical-runtime-launcher-v26-v35"
ROOT = Path(__file__).resolve().parents[1]
V24_PATH = ROOT / "bot" / "canonical_broker_startup_convergence_v24.py"
V32_PATH = ROOT / "bot" / "runtime_execution_convergence_v32.py"
V33_PATH = ROOT / "bot" / "runtime_execution_convergence_v33.py"
V34_PATH = ROOT / "bot" / "capital_readiness_handoff_v34.py"
V35_PATH = ROOT / "bot" / "capital_refresh_stall_guard_v35.py"
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
    """Install reconnect/Kraken convergence and bound-method safety."""
    if not V32_PATH.is_file():
        raise RuntimeError(f"runtime execution convergence module missing: {V32_PATH}")
    module = _load_module_by_path(
        "nija_runtime_execution_convergence_v32_prebot", V32_PATH
    )
    installer: Any = getattr(module, "install_import_hook", None) or getattr(
        module, "install", None
    )
    if not callable(installer) or not bool(installer()):
        raise RuntimeError("runtime execution convergence v32 installer failed")
    if os.environ.get("NIJA_RUNTIME_EXECUTION_CONVERGENCE_V32_INSTALLED") != "1":
        raise RuntimeError("runtime execution convergence v32 did not attest installed")

    if not V33_PATH.is_file():
        raise RuntimeError(f"runtime execution convergence hotfix missing: {V33_PATH}")
    hotfix = _load_module_by_path(
        "nija_runtime_execution_convergence_v33_prebot", V33_PATH
    )
    hotfix_installer: Any = getattr(hotfix, "install_import_hook", None) or getattr(
        hotfix, "install", None
    )
    if not callable(hotfix_installer) or not bool(hotfix_installer()):
        raise RuntimeError("runtime execution convergence v33 installer failed")
    if os.environ.get("NIJA_RUNTIME_EXECUTION_CONVERGENCE_V33_INSTALLED") != "1":
        raise RuntimeError("runtime execution convergence v33 did not attest installed")
    return module


def _install_capital_readiness_handoff() -> ModuleType:
    """Install the evidence-backed CSM-to-execution readiness handoff."""
    if not V34_PATH.is_file():
        raise RuntimeError(f"capital readiness handoff missing: {V34_PATH}")
    module = _load_module_by_path(
        "nija_capital_readiness_handoff_v34_prebot", V34_PATH
    )
    installer: Any = getattr(module, "install_import_hook", None) or getattr(
        module, "install", None
    )
    if not callable(installer) or not bool(installer()):
        raise RuntimeError("capital readiness handoff v34 installer failed")
    if os.environ.get("NIJA_CAPITAL_READINESS_HANDOFF_V34_INSTALLED") != "1":
        raise RuntimeError("capital readiness handoff v34 did not attest installed")
    return module


def _install_capital_refresh_stall_guard() -> ModuleType:
    """Bound coordinator broker fetches so bootstrap cannot remain in-flight."""
    if not V35_PATH.is_file():
        raise RuntimeError(f"capital refresh stall guard missing: {V35_PATH}")
    module = _load_module_by_path(
        "nija_capital_refresh_stall_guard_v35_prebot", V35_PATH
    )
    installer: Any = getattr(module, "install_import_hook", None) or getattr(
        module, "install", None
    )
    if not callable(installer) or not bool(installer()):
        raise RuntimeError("capital refresh stall guard v35 installer failed")
    if os.environ.get("NIJA_CAPITAL_REFRESH_STALL_GUARD_V35_INSTALLED") != "1":
        raise RuntimeError("capital refresh stall guard v35 did not attest installed")
    return module


def install_canonical_startup_guard() -> ModuleType:
    """Install v24, v32, v33, v34, and v35 before any application import."""
    if "bot.bot_main" in sys.modules:
        raise RuntimeError(
            "bot.bot_main loaded before canonical launcher guard; startup ordering unsafe"
        )

    module = _load_module_by_path(
        "nija_canonical_broker_startup_convergence_v24_prebot", V24_PATH
    )
    installer: Any = getattr(module, "install_import_hook", None) or getattr(
        module, "install", None
    )
    if not callable(installer) or not bool(installer()):
        raise RuntimeError("canonical startup convergence v24 installer failed")
    if os.environ.get(
        "NIJA_CANONICAL_BROKER_STARTUP_CONVERGENCE_V24_INSTALLED"
    ) != "1":
        raise RuntimeError("canonical startup convergence v24 did not attest installed")

    _install_runtime_execution_convergence()
    _install_capital_readiness_handoff()
    _install_capital_refresh_stall_guard()

    os.environ["NIJA_CANONICAL_RUNTIME_LAUNCHER_V26_READY"] = "1"
    os.environ["NIJA_CANONICAL_RUNTIME_LAUNCHER_V26_MARKER"] = MARKER
    LOGGER.critical(
        "CANONICAL_RUNTIME_LAUNCHER_V26_READY marker=%s "
        "bot_main_preloaded=false v24_installed=true v32_installed=true "
        "v33_installed=true v34_installed=true v35_installed=true",
        MARKER,
    )
    return module


def main() -> int:
    os.environ["NIJA_DEFER_RUNTIME_SITE_HOOKS"] = "1"
    os.environ["NIJA_CANONICAL_ENTRYPOINT_FAST_PATH"] = "1"
    if not MAIN_PATH.is_file():
        raise RuntimeError(f"canonical main.py missing: {MAIN_PATH}")
    install_canonical_startup_guard()
    print(
        "CANONICAL_ENTRYPOINT_FAST_PATH_ARMED "
        "marker=20260727-canonical-fast-entrypoint-v35 "
        "package_hook_fanout=deferred",
        flush=True,
    )
    runpy.run_path(str(MAIN_PATH), run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
