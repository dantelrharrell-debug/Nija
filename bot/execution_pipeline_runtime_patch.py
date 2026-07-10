"""Compatibility loader for NIJA's consolidated final execution contract."""
from __future__ import annotations

import builtins
import logging
import sys
from types import ModuleType

from .execution_contract_engine import patch_apex, patch_engine
from .execution_contract_pipeline import patch_pipeline, patch_router
from .execution_contract_primitives import MARKER

logger = logging.getLogger("nija.execution_pipeline_runtime_patch")
TARGETS = {
    "execution_pipeline", "execution_engine", "nija_apex_strategy_v71",
    "multi_broker_execution_router", "execution_router",
}


def _patch_loaded() -> bool:
    changed = False
    for name, module in tuple(sys.modules.items()):
        if not isinstance(module, ModuleType):
            continue
        tail = name.rsplit(".", 1)[-1]
        try:
            if tail == "execution_pipeline":
                changed = patch_pipeline(module) or changed
            elif tail == "execution_engine":
                changed = patch_engine(module) or changed
            elif tail == "nija_apex_strategy_v71":
                changed = patch_apex(module) or changed
            elif tail in {"multi_broker_execution_router", "execution_router"}:
                changed = patch_router(module) or changed
        except Exception as exc:
            logger.warning("FINAL_EXECUTION_CONTRACT_PATCH_FAILED marker=%s module=%s err=%s", MARKER, name, exc)
    return changed


def install_import_hook() -> None:
    _patch_loaded()
    flag = "_NIJA_FINAL_EXECUTION_CONTRACT_HOOK_20260710A"
    if getattr(builtins, flag, False):
        return
    original_import = builtins.__import__

    def importing(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
        module = original_import(name, globals, locals, fromlist, level)
        if str(name).rsplit(".", 1)[-1] in TARGETS:
            _patch_loaded()
        return module

    builtins.__import__ = importing
    setattr(builtins, flag, True)
    setattr(builtins, "_NIJA_EXECUTION_PIPELINE_PATCH_HOOK_INSTALLED", True)
    logger.warning("FINAL_EXECUTION_CONTRACT_IMPORT_HOOK_INSTALLED marker=%s", MARKER)


def install() -> None:
    install_import_hook()
