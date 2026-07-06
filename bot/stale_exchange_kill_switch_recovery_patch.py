from __future__ import annotations

import builtins
import json
import logging
import os
import sys
import time
from functools import wraps
from pathlib import Path
from types import ModuleType
from typing import Any

logger = logging.getLogger("nija.stale_exchange_kill_switch_recovery")
_MARKER = "STALE_EXCHANGE_KILL_SWITCH_RECOVERY_PATCHED marker=20260706b"
_PATCHED_ATTR = "_nija_stale_exchange_kill_switch_recovery_20260706b"
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}

_SAFE_EXCHANGE_PATTERNS = (
    "exchange kill-switch",
    "order rejection rate",
    "orders rejected",
)
_UNSAFE_PATTERNS = (
    "manual",
    "daily loss",
    "weekly loss",
    "drawdown",
    "unexpected balance",
    "balance delta",
    "api instability",
    "consecutive losing",
    "operator",
    "ui",
    "cli",
)


def _truthy(name: str, default: str = "true") -> bool:
    return str(os.environ.get(name, default)).strip().lower() in _TRUE


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def _read_state(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except Exception:
        return {}


def _safe_reason(text: str) -> bool:
    lowered = str(text or "").lower()
    if not lowered:
        return False
    if any(pattern in lowered for pattern in _UNSAFE_PATTERNS):
        return False
    return all(pattern in lowered for pattern in _SAFE_EXCHANGE_PATTERNS)


def _state_safe(state: dict[str, Any]) -> bool:
    history = state.get("history") or []
    activations = [h for h in history if isinstance(h, dict) and h.get("source")]
    if not activations:
        return True
    last = activations[-1]
    source = str(last.get("source") or "").lower()
    reason = str(last.get("reason") or "")
    if source and source not in {"exchange_monitor", "auto"}:
        return False
    return _safe_reason(reason)


def _quarantine(path: Path, suffix: str) -> Path | None:
    if not path.exists():
        return None
    target = path.with_name(f"{path.name}.quarantined.{suffix}")
    try:
        path.replace(target)
        return target
    except Exception as exc:
        logger.error("STALE_EXCHANGE_KILL_SWITCH_QUARANTINE_FAILED marker=20260706b path=%s error=%s", path, exc)
        return None


def _recover(base_path: str | None) -> bool:
    if not _truthy("NIJA_STALE_EXCHANGE_KILL_SWITCH_RECOVERY_ENABLED", "true"):
        logger.warning("STALE_EXCHANGE_KILL_SWITCH_RECOVERY_DISABLED marker=20260706b")
        return False
    base = Path(base_path or Path(__file__).resolve().parents[1]).resolve()
    kill_file = base / "EMERGENCY_STOP"
    state_file = base / ".nija_kill_switch_state.json"
    if not kill_file.exists():
        return False
    kill_text = _read_text(kill_file)
    state = _read_state(state_file)
    state_text = json.dumps(state, sort_keys=True, default=str)
    candidate_text = f"{kill_text}\n{state_text}"
    if not _safe_reason(candidate_text) or not _state_safe(state):
        logger.critical(
            "STALE_EXCHANGE_KILL_SWITCH_RECOVERY_SKIPPED marker=20260706b reason=not_safe_to_auto_recover kill_file=%s",
            kill_file,
        )
        return False
    suffix = str(int(time.time()))
    moved_kill = _quarantine(kill_file, suffix)
    moved_state = _quarantine(state_file, suffix)
    if moved_kill is None:
        return False
    logger.critical(
        "STALE_EXCHANGE_KILL_SWITCH_QUARANTINED marker=20260706b kill_file=%s state_file=%s reason=known_exchange_rejection_storm_recovered",
        moved_kill,
        moved_state,
    )
    print(
        f"[NIJA-PRINT] STALE_EXCHANGE_KILL_SWITCH_QUARANTINED marker=20260706b kill_file={moved_kill.name}",
        flush=True,
    )
    return True


def _patch_module(module: ModuleType) -> bool:
    cls = getattr(module, "KillSwitch", None)
    if not isinstance(cls, type):
        return False
    original_init = getattr(cls, "__init__", None)
    if not callable(original_init) or getattr(original_init, _PATCHED_ATTR, False):
        return bool(getattr(original_init, _PATCHED_ATTR, False))

    @wraps(original_init)
    def __init__(self: Any, base_path: str | None = None, *args: Any, **kwargs: Any):
        try:
            _recover(base_path)
        except Exception as exc:
            logger.error("STALE_EXCHANGE_KILL_SWITCH_RECOVERY_ERROR marker=20260706b error=%s", exc)
        return original_init(self, base_path, *args, **kwargs)

    setattr(__init__, _PATCHED_ATTR, True)
    setattr(cls, "__init__", __init__)
    logger.warning("%s class=KillSwitch", _MARKER)
    print("[NIJA-PRINT] STALE_EXCHANGE_KILL_SWITCH_RECOVERY_PATCHED marker=20260706b", flush=True)
    return True


def _try_patch_loaded() -> bool:
    patched = False
    for name in ("bot.kill_switch", "kill_switch"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            patched = _patch_module(module) or patched
    return patched


def install_import_hook() -> None:
    os.environ.setdefault("NIJA_STALE_EXCHANGE_KILL_SWITCH_RECOVERY_ENABLED", "true")
    _try_patch_loaded()
    if getattr(builtins, "_NIJA_STALE_EXCHANGE_KILL_SWITCH_RECOVERY_HOOK", False):
        return
    original_import = builtins.__import__

    def guarded_import(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
        module = original_import(name, globals, locals, fromlist, level)
        try:
            if name.endswith("kill_switch"):
                _try_patch_loaded()
            else:
                _try_patch_loaded()
        except Exception as exc:
            logger.warning("STALE_EXCHANGE_KILL_SWITCH_RECOVERY hook failed name=%s error=%s", name, exc)
        return module

    builtins.__import__ = guarded_import
    setattr(builtins, "_NIJA_STALE_EXCHANGE_KILL_SWITCH_RECOVERY_HOOK", True)
    logger.warning("STALE_EXCHANGE_KILL_SWITCH_RECOVERY_IMPORT_HOOK marker=20260706b")


def install() -> None:
    install_import_hook()
