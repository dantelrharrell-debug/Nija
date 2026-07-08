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

logger = logging.getLogger("nija.filesystem_emergency_stop_replay_recovery")
_PATCHED_ATTR = "_nija_filesystem_emergency_stop_replay_recovery_20260708b"
_HOOK_ATTR = "_NIJA_FILESYSTEM_EMERGENCY_STOP_REPLAY_RECOVERY_HOOK_20260708B"
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}
_UNSAFE_TOKENS = (
    "manual",
    "operator",
    "ui",
    "cli",
    "daily loss",
    "weekly loss",
    "drawdown",
    "loss limit",
    "consecutive losses",
    "unexpected balance",
    "balance delta",
    "api instability",
    "liquidation",
    "panic",
)
_SAFE_REPLAY_TOKENS = (
    "kill switch file detected",
    "emergency stop active",
    "file_system",
    "filesystem",
)


def _truthy(name: str, default: str = "true") -> bool:
    return str(os.environ.get(name, default)).strip().lower() in _TRUE


def _base_path(explicit: Any = None) -> Path:
    if explicit:
        return Path(str(explicit)).resolve()
    # In Railway the project root is commonly /app.  For repo-local execution this
    # resolves to the parent of bot/.
    return Path(__file__).resolve().parents[1]


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore") if path.exists() else ""
    except Exception:
        return ""


def _load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(_read(path)) if path.exists() else {}
    except Exception:
        return {}


def _has_unsafe(text: str) -> bool:
    lowered = str(text or "").lower()
    return any(token in lowered for token in _UNSAFE_TOKENS)


def _looks_like_filesystem_replay(kill_text: str, state: dict[str, Any]) -> bool:
    combined = f"{kill_text}\n{json.dumps(state, default=str, sort_keys=True)}".lower()
    if not combined.strip() or _has_unsafe(combined):
        return False
    # Exact stale pattern from this incident: file-system self-replay with no
    # underlying drawdown/manual/operator reason.
    if "reason: kill switch file detected" in combined:
        return True
    if "kill switch file detected" in combined and "file_system" in combined:
        return True
    if "emergency stop active" in combined and "kill switch file detected" in combined:
        return True
    return False


def _quarantine(path: Path, suffix: str) -> Path | None:
    if not path.exists():
        return None
    target = path.with_name(f"{path.name}.quarantined.{suffix}")
    try:
        path.replace(target)
        return target
    except Exception as exc:
        logger.error(
            "FILESYSTEM_EMERGENCY_STOP_REPLAY_QUARANTINE_FAILED marker=20260708b path=%s error=%s",
            path,
            exc,
        )
        return None


def _reset_state_machine(reason: str) -> None:
    try:
        try:
            from bot.trading_state_machine import get_state_machine, TradingState
        except ImportError:
            from trading_state_machine import get_state_machine, TradingState  # type: ignore[import]
        sm = get_state_machine()
        current = sm.get_current_state()
        if current == TradingState.EMERGENCY_STOP:
            sm.transition_to(TradingState.OFF, reason)
            logger.critical(
                "FILESYSTEM_EMERGENCY_STOP_REPLAY_STATE_RESET marker=20260708b state=OFF reason=%s",
                reason,
            )
    except Exception as exc:
        logger.warning(
            "FILESYSTEM_EMERGENCY_STOP_REPLAY_STATE_RESET_SKIPPED marker=20260708b error=%s",
            exc,
        )
    os.environ["NIJA_RUNTIME_TRADING_STATE"] = "OFF"
    os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] = "0"


def recover(base_path: Any = None) -> bool:
    if not _truthy("NIJA_FILESYSTEM_EMERGENCY_STOP_REPLAY_RECOVERY_ENABLED", "true"):
        return False
    base = _base_path(base_path)
    kill_file = base / "EMERGENCY_STOP"
    state_file = base / ".nija_kill_switch_state.json"
    if not kill_file.exists():
        return False
    kill_text = _read(kill_file)
    state = _load_json(state_file)
    if not _looks_like_filesystem_replay(kill_text, state):
        logger.critical(
            "FILESYSTEM_EMERGENCY_STOP_REPLAY_RECOVERY_SKIPPED marker=20260708b reason=not_safe_to_auto_clear kill_file=%s",
            kill_file,
        )
        return False
    suffix = str(int(time.time()))
    moved_kill = _quarantine(kill_file, suffix)
    moved_state = _quarantine(state_file, suffix)
    if moved_kill is None:
        return False
    reason = "stale file-system EMERGENCY_STOP replay quarantined after capital/authority recovery"
    _reset_state_machine(reason)
    logger.critical(
        "FILESYSTEM_EMERGENCY_STOP_REPLAY_QUARANTINED marker=20260708b kill_file=%s state_file=%s reason=%s",
        moved_kill,
        moved_state,
        reason,
    )
    print(
        f"[NIJA-PRINT] FILESYSTEM_EMERGENCY_STOP_REPLAY_QUARANTINED marker=20260708b kill_file={moved_kill.name}",
        flush=True,
    )
    return True


def _patch_module(module: ModuleType) -> bool:
    cls = getattr(module, "KillSwitch", None)
    if not isinstance(cls, type):
        return False
    patched = False
    original_init = getattr(cls, "__init__", None)
    if callable(original_init) and not getattr(original_init, _PATCHED_ATTR, False):
        @wraps(original_init)
        def __init__(self: Any, base_path: Any = None, *args: Any, **kwargs: Any):
            try:
                recover(base_path)
            except Exception as exc:
                logger.warning("FILESYSTEM_EMERGENCY_STOP_REPLAY_RECOVERY_ERROR marker=20260708b stage=init error=%s", exc)
            return original_init(self, base_path, *args, **kwargs)
        setattr(__init__, _PATCHED_ATTR, True)
        setattr(cls, "__init__", __init__)
        patched = True
    original_is_active = getattr(cls, "is_active", None)
    if callable(original_is_active) and not getattr(original_is_active, _PATCHED_ATTR, False):
        @wraps(original_is_active)
        def is_active(self: Any, *args: Any, **kwargs: Any):
            try:
                recover(getattr(self, "_base_path", None))
                # If recovery happened, keep this object consistent with disk state.
                if not Path(getattr(self, "_kill_file", "")).exists() and getattr(self, "_is_active", False):
                    if _looks_like_filesystem_replay("kill switch file detected", {"source": "FILE_SYSTEM"}):
                        self._is_active = False
            except Exception as exc:
                logger.warning("FILESYSTEM_EMERGENCY_STOP_REPLAY_RECOVERY_ERROR marker=20260708b stage=is_active error=%s", exc)
            return original_is_active(self, *args, **kwargs)
        setattr(is_active, _PATCHED_ATTR, True)
        setattr(cls, "is_active", is_active)
        patched = True
    if patched:
        logger.warning("FILESYSTEM_EMERGENCY_STOP_REPLAY_RECOVERY_PATCHED marker=20260708b module=%s", getattr(module, "__name__", "unknown"))
        print("[NIJA-PRINT] FILESYSTEM_EMERGENCY_STOP_REPLAY_RECOVERY_PATCHED marker=20260708b", flush=True)
    return patched


def _patch_loaded() -> None:
    for name in ("bot.kill_switch", "kill_switch"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            try:
                _patch_module(module)
            except Exception as exc:
                logger.warning("FILESYSTEM_EMERGENCY_STOP_REPLAY_PATCH_FAILED marker=20260708b module=%s error=%s", name, exc)


def install_import_hook() -> None:
    os.environ.setdefault("NIJA_FILESYSTEM_EMERGENCY_STOP_REPLAY_RECOVERY_ENABLED", "true")
    try:
        recover(None)
    except Exception as exc:
        logger.warning("FILESYSTEM_EMERGENCY_STOP_REPLAY_EARLY_RECOVER_ERROR marker=20260708b error=%s", exc)
    _patch_loaded()
    if getattr(builtins, _HOOK_ATTR, False):
        return
    original_import = builtins.__import__

    def guarded_import(name: str, globals: Any = None, locals: Any = None, fromlist: Any = (), level: int = 0):
        module = original_import(name, globals, locals, fromlist, level)
        if str(name).endswith("kill_switch") or name in {"bot.kill_switch", "kill_switch"}:
            _patch_loaded()
        return module

    builtins.__import__ = guarded_import
    setattr(builtins, _HOOK_ATTR, True)
    logger.warning("FILESYSTEM_EMERGENCY_STOP_REPLAY_RECOVERY_IMPORT_HOOK marker=20260708b")


def install() -> None:
    install_import_hook()
