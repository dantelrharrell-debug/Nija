from __future__ import annotations

import builtins
import logging
import sys
from types import ModuleType
from typing import Any, Dict

logger = logging.getLogger("nija.ai_hub_terminal_rejection_hard_gate")
_PATCHED_ATTR = "_nija_ai_hub_terminal_rejection_hard_gate_20260708a"
_TERMINAL_TOKENS = (
    "terminal_risk_hard_block",
    "portfolio exposure limit reached",
    "position blocked by risk engine",
    "hard_sector_limit_block",
    "hard sector limit block",
)


def _terminal_ai_reject(result: Any) -> tuple[bool, str]:
    if not isinstance(result, dict):
        return False, ""
    action = str(result.get("action") or "").strip().lower()
    if action not in {"enter_long", "enter_short", "buy", "sell"}:
        return False, ""
    metadata = result.get("metadata")
    if not isinstance(metadata, dict):
        return False, ""
    ai_eval = metadata.get("ai_eval")
    if not isinstance(ai_eval, dict):
        return False, ""
    approved = bool(ai_eval.get("ai_approved", True))
    reason = str(ai_eval.get("ai_reason") or ai_eval.get("exposure_rejection_reason") or "")
    if approved:
        return False, ""
    if any(token in reason.lower() for token in _TERMINAL_TOKENS):
        return True, reason or "ai_hub_terminal_rejection"
    return False, reason


def _patch_strategy_module(module: ModuleType) -> bool:
    cls = getattr(module, "NIJAApexStrategyV71", None)
    if not isinstance(cls, type):
        return False
    original = getattr(cls, "analyze_market", None)
    if not callable(original) or getattr(original, _PATCHED_ATTR, False):
        return bool(getattr(original, _PATCHED_ATTR, False))

    def analyze_market_ai_terminal_guard(self: Any, *args: Any, **kwargs: Any):
        result = original(self, *args, **kwargs)
        blocked, reason = _terminal_ai_reject(result)
        if not blocked:
            return result
        symbol = str(result.get("symbol") or kwargs.get("symbol") or "") if isinstance(result, dict) else ""
        if not symbol and args:
            # Most analyze_market call sites pass symbol separately or infer from logs;
            # keep fallback empty rather than guessing from a DataFrame argument.
            symbol = "unknown"
        action = str(result.get("action") or "") if isinstance(result, dict) else ""
        logger.critical(
            "AI_HUB_TERMINAL_REJECTION_HARD_GATE marker=20260708a symbol=%s action=%s reason=%s",
            symbol,
            action,
            reason,
        )
        return {
            "action": "hold",
            "reason": f"AI Hub terminal risk hard block: {reason}",
            "filter_stage": "ai_hub_terminal_rejection",
            "metadata": dict(result.get("metadata", {}) or {}) if isinstance(result, dict) else {},
        }

    setattr(analyze_market_ai_terminal_guard, _PATCHED_ATTR, True)
    setattr(cls, "analyze_market", analyze_market_ai_terminal_guard)
    logger.warning("AI_HUB_TERMINAL_REJECTION_HARD_GATE_PATCHED marker=20260708a module=%s", getattr(module, "__name__", "unknown"))
    return True


def _patch_loaded() -> None:
    for name in ("bot.nija_apex_strategy_v71", "nija_apex_strategy_v71"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            try:
                _patch_strategy_module(module)
            except Exception as exc:
                logger.warning("AI_HUB_TERMINAL_REJECTION_HARD_GATE_PATCH_FAILED marker=20260708a module=%s err=%s", name, exc)


def install_import_hook() -> None:
    _patch_loaded()
    if getattr(builtins, "_NIJA_AI_HUB_TERMINAL_REJECTION_HARD_GATE_HOOK_20260708A", False):
        return
    original_import = builtins.__import__

    def importing(name: str, globals: Any = None, locals: Any = None, fromlist: Any = (), level: int = 0):
        module = original_import(name, globals, locals, fromlist, level)
        if name in {"bot.nija_apex_strategy_v71", "nija_apex_strategy_v71"} or str(name).endswith("nija_apex_strategy_v71"):
            _patch_loaded()
        return module

    builtins.__import__ = importing
    setattr(builtins, "_NIJA_AI_HUB_TERMINAL_REJECTION_HARD_GATE_HOOK_20260708A", True)
    logger.warning("AI_HUB_TERMINAL_REJECTION_HARD_GATE_INSTALL_COMPLETE marker=20260708a")


def install() -> None:
    install_import_hook()
