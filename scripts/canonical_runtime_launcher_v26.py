"""Canonical NIJA runtime launcher v26.

This is the production Python front door used by ``start.sh``. It installs the
canonical broker-startup convergence hook before importing ``main.py`` or the
``bot`` package. That ordering is important: importing any ``bot.*`` module can
execute ``bot.__init__`` and load ``bot.bot_main`` before a late hook has a
chance to wrap writer acquisition.

The launcher also establishes the canonical writer before ``main.py`` runs its
compatibility/runtime installer fanout. v111 makes the bootstrap-critical module
loads use CPython's canonical frozen import primitive so historical
``importlib.import_module`` wrappers cannot recursively re-enter ``bot.bot``
before the writer-first handoff completes. Runtime hooks and all fail-closed
writer/nonce/risk/kill-switch checks remain authoritative.
"""
from __future__ import annotations

import importlib
import importlib.util
import logging
import os
from pathlib import Path
import runpy
import sys
from types import ModuleType
from typing import Any

MARKER = "20260816-canonical-runtime-launcher-v111"
WRITER_FIRST_MARKER = "20260816-canonical-writer-first-v111"
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
V42_PATH = ROOT / "bot" / "heartbeat_authority_reanchor_v42_patch.py"
V43_PATH = ROOT / "bot" / "capital_publication_convergence_v43_patch.py"
V44_PATH = ROOT / "bot" / "kraken_connection_convergence_v44_patch.py"
V18_PATH = ROOT / "bot" / "production_corrective_set_v18_patch.py"
V19_PATH = ROOT / "bot" / "entrypoint_writer_epoch_recovery_v19_patch.py"
RENDER_MEMORY_GUARD_PATH = ROOT / "scripts" / "render_memory_pressure_guard.py"
MAIN_PATH = ROOT / "main.py"
LOGGER = logging.getLogger("nija.canonical_runtime_launcher")


def _canonical_import(module_name: str) -> ModuleType:
    """Load a bootstrap-critical module without mutable import_module wrappers."""
    bootstrap = getattr(importlib, "_bootstrap", None)
    gcd_import = getattr(bootstrap, "_gcd_import", None) if bootstrap is not None else None
    if not callable(gcd_import):
        raise RuntimeError("canonical_import_primitive_unavailable")
    module = gcd_import(module_name)
    if not isinstance(module, ModuleType):
        raise RuntimeError(f"canonical_import_invalid_module:{module_name}")
    return module


def _start_render_memory_pressure_guard() -> bool:
    """Start the stdlib-only Render guard before importing the bot package."""
    if not RENDER_MEMORY_GUARD_PATH.is_file():
        raise RuntimeError(
            f"Render memory pressure guard missing: {RENDER_MEMORY_GUARD_PATH}"
        )
    module = _load_module_by_path(
        "nija_render_memory_pressure_guard_v151",
        RENDER_MEMORY_GUARD_PATH,
    )
    starter = getattr(module, "start", None)
    if not callable(starter):
        raise RuntimeError("Render memory pressure guard start callable unavailable")
    started = bool(starter())
    if started and os.environ.get("NIJA_RENDER_MEMORY_PRESSURE_GUARD_V151_READY") != "1":
        raise RuntimeError("Render memory pressure guard did not attest ready")
    return started


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


def _install_heartbeat_authority_reanchor_v42() -> ModuleType:
    if not V42_PATH.is_file():
        raise RuntimeError(f"heartbeat authority re-anchor v42 missing: {V42_PATH}")
    module = _load_module_by_path("nija_heartbeat_authority_reanchor_v42_prebot", V42_PATH)
    installer: Any = getattr(module, "install_import_hook", None) or getattr(module, "install", None)
    if not callable(installer) or not bool(installer()):
        raise RuntimeError("heartbeat authority re-anchor v42 installer failed")
    if os.environ.get("NIJA_HEARTBEAT_AUTHORITY_REANCHOR_V42_INSTALLED") != "1":
        raise RuntimeError("heartbeat authority re-anchor v42 did not attest installed")
    return module


def _install_capital_publication_convergence_v43() -> ModuleType:
    if not V43_PATH.is_file():
        raise RuntimeError(f"capital publication convergence v43 missing: {V43_PATH}")
    module = _load_module_by_path("nija_capital_publication_convergence_v43_prebot", V43_PATH)
    installer: Any = getattr(module, "install_import_hook", None) or getattr(module, "install", None)
    if not callable(installer) or not bool(installer()):
        raise RuntimeError("capital publication convergence v43 installer failed")
    if os.environ.get("NIJA_CAPITAL_PUBLICATION_CONVERGENCE_V43_INSTALLED") != "1":
        raise RuntimeError("capital publication convergence v43 did not attest installed")
    return module


def _install_kraken_connection_convergence_v44() -> ModuleType:
    if not V44_PATH.is_file():
        raise RuntimeError(f"Kraken connection convergence v44 missing: {V44_PATH}")
    module = _load_module_by_path("nija_kraken_connection_convergence_v44_prebot", V44_PATH)
    installer: Any = getattr(module, "install_import_hook", None) or getattr(module, "install", None)
    if not callable(installer) or not bool(installer()):
        raise RuntimeError("Kraken connection convergence v44 installer failed")
    if os.environ.get("NIJA_KRAKEN_CONNECTION_CONVERGENCE_V44_INSTALLED") != "1":
        raise RuntimeError("Kraken connection convergence v44 did not attest installed")
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
    _install_heartbeat_authority_reanchor_v42()
    _install_capital_publication_convergence_v43()
    _install_kraken_connection_convergence_v44()
    _install_production_corrective_set()
    os.environ["NIJA_CANONICAL_RUNTIME_LAUNCHER_V26_READY"] = "1"
    os.environ["NIJA_CANONICAL_RUNTIME_LAUNCHER_V26_MARKER"] = MARKER
    LOGGER.critical(
        "CANONICAL_RUNTIME_LAUNCHER_V26_READY marker=%s bot_main_preloaded=false v111_launcher_import=true",
        MARKER,
    )
    return module


def _release_early_writer(bot_main: ModuleType, *, reason: str) -> None:
    release = getattr(bot_main, "_release_writer_authority", None)
    if callable(release):
        try:
            release()
        except Exception as exc:
            LOGGER.warning(
                "CANONICAL_EARLY_WRITER_RELEASE_FAILED marker=%s reason=%s err=%s:%s",
                WRITER_FIRST_MARKER,
                reason,
                type(exc).__name__,
                exc,
            )


def _bootstrap_writer_first() -> tuple[ModuleType, ModuleType]:
    """Import canonical entrypoint and prove Redis writer authority first."""
    bot_entry = _canonical_import("bot.bot")
    bot_main = _canonical_import("bot.bot_main")
    acquire = getattr(bot_main, "_acquire_writer_authority_before_nonce", None)
    if not callable(acquire):
        raise RuntimeError("canonical writer bootstrap function unavailable")

    if not bool(acquire()):
        error = str(getattr(bot_main, "_writer_authority_last_error", "") or "unknown")
        raise RuntimeError(f"canonical writer bootstrap failed:{error}")

    runtime = getattr(bot_main, "_writer_authority_runtime", None)
    generation_text = str(os.environ.get("NIJA_WRITER_LEASE_GENERATION", "") or "").strip()
    token = str(os.environ.get("NIJA_WRITER_FENCING_TOKEN", "") or "").strip()
    try:
        generation = int(generation_text or "0")
    except (TypeError, ValueError):
        generation = 0

    exact_runtime = bool(
        runtime is not None
        and bool(getattr(runtime, "acquired", False))
        and not bool(getattr(runtime, "lost", True))
        and not bool(getattr(runtime, "_local_fallback", False))
        and generation > 0
        and token
    )
    if not exact_runtime:
        _release_early_writer(bot_main, reason="runtime_lineage_incomplete")
        raise RuntimeError("canonical writer bootstrap did not establish exact distributed lineage")

    try:
        authority = _canonical_import("bot.execution_authority_context")
        verify = getattr(authority, "assert_distributed_writer_authority", None)
        if not callable(verify):
            raise RuntimeError("distributed authority verifier unavailable")
        verify()
    except Exception:
        _release_early_writer(bot_main, reason="exact_authority_reverify_failed")
        raise

    os.environ["NIJA_CANONICAL_WRITER_FIRST_V59_READY"] = "1"
    os.environ["NIJA_CANONICAL_LAUNCHER_IMPORT_V111_READY"] = "1"
    LOGGER.critical(
        "CANONICAL_EARLY_WRITER_BOOTSTRAP_VERIFIED marker=%s generation=%s token_prefix=%s "
        "exact_redis_proof=true local_fallback=false runtime_fanout_started=false "
        "bootstrap_import_loader=frozen_bootstrap",
        WRITER_FIRST_MARKER,
        generation,
        token[:8],
    )
    return bot_entry, bot_main


def _run_main_single_identity(bot_entry: ModuleType, bot_main: ModuleType) -> None:
    """Run ``main.py`` while reusing the canonical ``bot.bot`` module once."""
    original_run_module = runpy.run_module
    handoff_started = False

    def run_module_once(
        mod_name: str,
        init_globals: dict[str, Any] | None = None,
        run_name: str | None = None,
        alter_sys: bool = False,
    ) -> dict[str, Any]:
        nonlocal handoff_started
        if mod_name != "bot.bot":
            return original_run_module(
                mod_name,
                init_globals=init_globals,
                run_name=run_name,
                alter_sys=alter_sys,
            )
        canonical = sys.modules.get("bot.bot")
        if canonical is None or canonical is not bot_entry:
            raise RuntimeError("canonical bot.bot module identity changed before handoff")
        entry_main = getattr(canonical, "main", None)
        if not callable(entry_main):
            raise RuntimeError("canonical bot.bot main callable unavailable")
        handoff_started = True
        LOGGER.critical(
            "CANONICAL_BOT_SINGLE_IDENTITY_HANDOFF marker=%s module=bot.bot reused_module=true run_name=%s",
            WRITER_FIRST_MARKER,
            run_name or "unset",
        )
        result = entry_main()
        raise SystemExit(int(result or 0))

    runpy.run_module = run_module_once
    try:
        runpy.run_path(str(MAIN_PATH), run_name="__main__")
    finally:
        runpy.run_module = original_run_module
        if not handoff_started:
            _release_early_writer(bot_main, reason="main_wrapper_failed_before_handoff")


def main() -> int:
    os.environ["NIJA_DEFER_RUNTIME_SITE_HOOKS"] = "1"
    os.environ["NIJA_CANONICAL_ENTRYPOINT_FAST_PATH"] = "1"
    if not MAIN_PATH.is_file():
        raise RuntimeError(f"canonical main.py missing: {MAIN_PATH}")
    _start_render_memory_pressure_guard()
    install_canonical_startup_guard()
    bot_entry, bot_main = _bootstrap_writer_first()
    print(
        "CANONICAL_ENTRYPOINT_FAST_PATH_ARMED marker=20260816-canonical-runtime-launcher-v111 "
        "package_hook_fanout=deferred bootstrap_import_loader=frozen_bootstrap",
        flush=True,
    )
    _run_main_single_identity(bot_entry, bot_main)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
