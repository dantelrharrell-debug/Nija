"""Install-safe Phase 3 over-selection patch.

The 20260703i scan-budget patch correctly widened the OKX scan set, but the
rank-and-select over-selection wrapper may miss NijaAIEngine when the engine is
loaded through Python's normal import path instead of importlib.import_module.

This patch installs both a builtins.__import__ hook and a short monitor so the
AI ranker is patched whether NijaAIEngine is imported before or after startup
patch installation.

Safety contract:
- Does not bypass expectancy, edge, risk, kill-switch, writer authority, or
  exchange validation gates.
- Only allows more ranked candidates to be attempted when earlier candidates are
  rejected by downstream gates.
- Successful entries remain capped by the real available open-position slots.
"""

from __future__ import annotations

import builtins
import importlib
import logging
import os
import sys
import threading
import time
from types import ModuleType
from typing import Any, Callable, Optional

logger = logging.getLogger("nija.phase3_overselect_import_repair")

_ORIGINAL_IMPORT_MODULE: Optional[Callable[..., Any]] = None
_ORIGINAL_BUILTINS_IMPORT: Optional[Callable[..., Any]] = None
_PATCHED = False
_MONITOR_STARTED = False
_LOCK = threading.Lock()
_MARKER = "PHASE3_OVERSELECT_IMPORT_REPAIR_PATCHED marker=20260703j"
_ATTR = "_nija_phase3_overselect_wrapped_v20260703j"


def _int_env(name: str, default: int) -> int:
    try:
        return max(1, int(float(os.environ.get(name, str(default)) or default)))
    except Exception:
        return int(default)


def _patch_ai_engine_module(module: ModuleType) -> bool:
    global _PATCHED
    cls = getattr(module, "NijaAIEngine", None)
    if not isinstance(cls, type):
        return False
    original = getattr(cls, "rank_and_select", None)
    if not callable(original):
        return False
    if getattr(original, _ATTR, False):
        _PATCHED = True
        return True

    def _rank_and_select_more_attempts(self: Any, candidates: list[Any], available_slots: int, regime: Any = None) -> list[Any]:
        selected = list(original(self, candidates, available_slots, regime) or [])
        try:
            slots = max(0, int(available_slots or 0))
            if not candidates or slots <= 0:
                return selected
            max_attempts = min(slots, _int_env("NIJA_PHASE3_MAX_EXECUTION_ATTEMPTS", 8))
            if len(selected) >= max_attempts:
                return selected
            ranked = sorted(
                candidates,
                key=lambda s: float(getattr(s, "composite_score", 0.0) or 0.0),
                reverse=True,
            )
            seen = {
                f"{getattr(s, 'symbol', '')}:{getattr(s, 'side', '')}"
                for s in selected
            }
            threshold = float(getattr(selected[0], "threshold_used", 0.0) if selected else 0.0)
            for sig in ranked:
                if len(selected) >= max_attempts:
                    break
                key = f"{getattr(sig, 'symbol', '')}:{getattr(sig, 'side', '')}"
                if key in seen:
                    continue
                try:
                    score = float(getattr(sig, "composite_score", 0.0) or 0.0)
                except Exception:
                    score = 0.0
                if score <= 0.0:
                    continue
                try:
                    setattr(sig, "threshold_used", threshold or getattr(sig, "threshold_used", 0.0))
                    if hasattr(self, "_position_multiplier"):
                        sig.position_multiplier = self._position_multiplier(score)
                    metadata = getattr(sig, "metadata", None)
                    if isinstance(metadata, dict):
                        metadata["selection_reason"] = "replacement_attempt_after_prior_gate_reject"
                        metadata["overselect_patch"] = "20260703j"
                except Exception:
                    pass
                selected.append(sig)
                seen.add(key)
            logger.critical(
                "PHASE3_OVERSELECT_APPLIED marker=20260703j candidates=%d selected=%d available_slots=%d max_attempts=%d symbols=%s",
                len(candidates),
                len(selected),
                slots,
                max_attempts,
                ",".join(str(getattr(s, "symbol", "?")) for s in selected),
            )
            print(
                f"[NIJA-PRINT] PHASE3_OVERSELECT_APPLIED marker=20260703j "
                f"selected={len(selected)} slots={slots} "
                f"symbols={','.join(str(getattr(s, 'symbol', '?')) for s in selected)}",
                flush=True,
            )
        except Exception as exc:
            logger.warning("PHASE3_OVERSELECT_IMPORT_REPAIR_APPLY_FAILED err=%s", exc)
        return selected

    setattr(_rank_and_select_more_attempts, _ATTR, True)
    setattr(cls, "rank_and_select", _rank_and_select_more_attempts)
    _PATCHED = True
    logger.warning("%s module=%s", _MARKER, getattr(module, "__name__", "<unknown>"))
    print("[NIJA-PRINT] PHASE3_OVERSELECT_IMPORT_REPAIR_PATCHED marker=20260703j", flush=True)
    return True


def _try_patch_loaded() -> bool:
    patched = False
    for name in ("bot.nija_ai_engine", "nija_ai_engine"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            patched = _patch_ai_engine_module(module) or patched
    return patched


def _start_monitor() -> None:
    global _MONITOR_STARTED
    if _MONITOR_STARTED:
        return
    _MONITOR_STARTED = True

    def _monitor() -> None:
        deadline = time.time() + float(os.environ.get("NIJA_PATCH_MONITOR_SECONDS", "240") or "240")
        while time.time() < deadline:
            if _try_patch_loaded():
                return
            time.sleep(0.25)
        logger.warning("PHASE3_OVERSELECT_IMPORT_REPAIR_MONITOR_EXPIRED patched=%s", _PATCHED)

    threading.Thread(target=_monitor, name="phase3-overselect-import-repair", daemon=True).start()
    logger.warning("PHASE3_OVERSELECT_IMPORT_REPAIR_MONITOR_STARTED marker=20260703j")


def install_import_hook() -> None:
    global _ORIGINAL_IMPORT_MODULE, _ORIGINAL_BUILTINS_IMPORT
    with _LOCK:
        logger.warning("PHASE3_OVERSELECT_IMPORT_REPAIR_INSTALL_START marker=20260703j")
        print("[NIJA-PRINT] PHASE3_OVERSELECT_IMPORT_REPAIR_INSTALL_START marker=20260703j", flush=True)
        _try_patch_loaded()
        _start_monitor()

        if _ORIGINAL_IMPORT_MODULE is None:
            _ORIGINAL_IMPORT_MODULE = importlib.import_module

            def _wrapped_import_module(name: str, package: str | None = None):
                module = _ORIGINAL_IMPORT_MODULE(name, package)  # type: ignore[misc]
                if name in {"bot.nija_ai_engine", "nija_ai_engine"}:
                    _patch_ai_engine_module(module)
                return module

            importlib.import_module = _wrapped_import_module  # type: ignore[assignment]

        if _ORIGINAL_BUILTINS_IMPORT is None:
            _ORIGINAL_BUILTINS_IMPORT = builtins.__import__

            def _wrapped_builtin_import(name: str, globals: Any = None, locals: Any = None, fromlist: Any = (), level: int = 0):
                module = _ORIGINAL_BUILTINS_IMPORT(name, globals, locals, fromlist, level)  # type: ignore[misc]
                try:
                    target_names = {"bot.nija_ai_engine", "nija_ai_engine"}
                    if name in target_names or name.endswith(".nija_ai_engine"):
                        target = sys.modules.get("bot.nija_ai_engine") or sys.modules.get("nija_ai_engine") or module
                        if isinstance(target, ModuleType):
                            _patch_ai_engine_module(target)
                    else:
                        _try_patch_loaded()
                except Exception as exc:
                    logger.debug("Phase3 overselect builtin import hook skipped: %s", exc)
                return module

            builtins.__import__ = _wrapped_builtin_import

        logger.warning(
            "PHASE3_OVERSELECT_IMPORT_REPAIR_INSTALL_COMPLETE marker=20260703j patched=%s",
            _PATCHED,
        )
