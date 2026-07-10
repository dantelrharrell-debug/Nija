from __future__ import annotations

import builtins
import json
import logging
import os
import shutil
import time
from pathlib import Path
from typing import Iterable

logger = logging.getLogger("nija.operator_emergency_stop_clear")
_MARKER = "20260710s"
_INSTALL_SENTINEL = "_NIJA_OPERATOR_EMERGENCY_STOP_CLEAR_INSTALLED_20260710S"
_TRUTHY = {"1", "true", "yes", "on", "y", "enabled"}
_APPROVAL_PHRASE = "CLEAR_EMERGENCY_STOP_FOR_LIVE_TRADING"
_DEFAULT_KILL_FILES = (
    "/app/EMERGENCY_STOP",
    "./EMERGENCY_STOP",
    "./data/EMERGENCY_STOP",
)
_DEFAULT_STATE_FILES = (
    "/app/.nija_kill_switch_state.json",
    "./.nija_kill_switch_state.json",
    "./data/.nija_kill_switch_state.json",
)
_STOP_ENV_NAMES = (
    "NIJA_EMERGENCY_STOP_REASON",
    "NIJA_KILL_SWITCH_REASON",
    "NIJA_PRE_HALT_REASON",
    "NIJA_RUNTIME_STOP_REASON",
    "NIJA_OPERATOR_EMERGENCY_STOP_REASON",
)
_MANUAL_CLEAR_ALLOWED_TOKENS = (
    "manual",
    "operator",
    "kill switch file detected",
    "emergency stop active",
    "file_system",
    "filesystem",
)
_TERMINAL_RISK_TOKENS = (
    "daily loss",
    "weekly loss",
    "drawdown",
    "loss limit",
    "consecutive losses",
    "liquidation",
    "panic",
    "api instability",
    "unexpected balance",
    "balance delta",
)
_UNSAFE_BYPASS_ENVS = (
    "NIJA_FORCE_ACTIVATION",
    "NIJA_FORCE_LOCAL_WRITER_LOCK_FALLBACK",
    "NIJA_DISABLE_WRITER_LOCK",
    "NIJA_UNSAFE_BYPASS_DISTRIBUTED_LOCK",
    "NIJA_CLEAR_TERMINAL_RISK_BLOCKS",
    "NIJA_BYPASS_RISK_GATES",
)


def _truthy(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in _TRUTHY


def _clean(value: object) -> str:
    return str(value or "").strip().strip('"').strip("'").strip()


def _live_mode() -> bool:
    return not _truthy("DRY_RUN_MODE") and not _truthy("PAPER_MODE")


def _split_paths(raw: str, defaults: Iterable[str]) -> list[Path]:
    values: Iterable[str] = (
        [piece.strip() for piece in raw.split(",") if piece.strip()]
        if raw
        else defaults
    )
    found: list[Path] = []
    for item in values:
        try:
            path = Path(item).expanduser()
            if path.exists() and path.is_file():
                found.append(path)
        except Exception as exc:
            logger.warning(
                "OPERATOR_EMERGENCY_STOP_CLEAR_PATH_CHECK_FAILED marker=%s path=%s err=%s",
                _MARKER,
                item,
                exc,
            )
    return found


def _kill_files() -> list[Path]:
    return _split_paths(
        _clean(os.environ.get("NIJA_EMERGENCY_STOP_FILES")),
        _DEFAULT_KILL_FILES,
    )


def _state_files() -> list[Path]:
    return _split_paths(
        _clean(os.environ.get("NIJA_EMERGENCY_STOP_STATE_FILES")),
        _DEFAULT_STATE_FILES,
    )


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def _combined_stop_text(paths: Iterable[Path]) -> str:
    chunks: list[str] = []
    for path in paths:
        raw = _read_text(path)
        if raw:
            chunks.append(f"{path}={raw}")
            try:
                if path.suffix == ".json":
                    parsed = json.loads(raw)
                    chunks.append(json.dumps(parsed, sort_keys=True, default=str))
            except Exception:
                pass
    for env_name in _STOP_ENV_NAMES:
        value = os.environ.get(env_name)
        if value:
            chunks.append(f"{env_name}={value}")
    return "\n".join(chunks).lower()


def _stop_reason_safe_to_clear(paths: Iterable[Path]) -> tuple[bool, str]:
    text = _combined_stop_text(paths)
    if any(token in text for token in _TERMINAL_RISK_TOKENS):
        return False, "terminal_risk_reason_present"
    if text and not any(token in text for token in _MANUAL_CLEAR_ALLOWED_TOKENS):
        return False, "unknown_emergency_stop_reason"
    return True, "operator_manual_clear_allowed"


def _unsafe_bypass_env_present() -> tuple[bool, str]:
    for name in _UNSAFE_BYPASS_ENVS:
        if _truthy(name, False):
            return True, name
    return False, ""


def _safe_to_clear(all_paths: Iterable[Path]) -> tuple[bool, str]:
    if not _truthy("NIJA_OPERATOR_CLEAR_EMERGENCY_STOP", False):
        return False, "operator_clear_flag_not_set"
    approval = _clean(os.environ.get("NIJA_OPERATOR_CLEAR_EMERGENCY_STOP_ACK"))
    if approval != _APPROVAL_PHRASE:
        return False, "missing_exact_operator_ack_phrase"
    reason = _clean(os.environ.get("NIJA_OPERATOR_CLEAR_EMERGENCY_STOP_REASON"))
    if len(reason) < 12:
        return False, "missing_operator_reason"
    if not _live_mode():
        return False, "not_live_mode"
    unsafe, unsafe_name = _unsafe_bypass_env_present()
    if unsafe:
        return False, f"unsafe_bypass_env_present:{unsafe_name}"
    stop_ok, stop_reason = _stop_reason_safe_to_clear(all_paths)
    if not stop_ok:
        return False, stop_reason
    return True, "operator_approved"


def _env_only_stop_present() -> tuple[bool, str]:
    """Detect an actual environment-only emergency stop latch.

    ``NIJA_RUNTIME_EXECUTION_AUTHORITY=0`` is the normal fail-closed startup
    state before writer lineage, heartbeat, and capital proof. It is never, by
    itself, evidence of an emergency stop.
    """

    text = _combined_stop_text(())
    env_state = os.environ.get("NIJA_RUNTIME_TRADING_STATE", "").strip().upper()
    env_auth = os.environ.get("NIJA_RUNTIME_EXECUTION_AUTHORITY", "").strip()
    if text.strip():
        return True, text
    if env_state == "EMERGENCY_STOP":
        return True, f"runtime_state={env_state} exec_auth={env_auth or 'missing'}"
    return False, f"runtime_state={env_state or 'missing'} exec_auth={env_auth or 'missing'}"


def _safe_to_clear_stale_env_only() -> tuple[bool, str]:
    if not _truthy("NIJA_AUTO_CLEAR_STALE_MANUAL_EMERGENCY_ENV", True):
        return False, "stale_env_auto_clear_disabled"
    if not _live_mode():
        return False, "not_live_mode"
    unsafe, unsafe_name = _unsafe_bypass_env_present()
    if unsafe:
        return False, f"unsafe_bypass_env_present:{unsafe_name}"
    present, text = _env_only_stop_present()
    if not present:
        return False, "no_stop_env_latch_present"
    if any(token in text for token in _TERMINAL_RISK_TOKENS):
        return False, "terminal_risk_reason_present"
    if text and any(token in text for token in _MANUAL_CLEAR_ALLOWED_TOKENS):
        return True, "stale_manual_env_latch_no_kill_file"
    if "runtime_state=emergency_stop" in text:
        return True, "stale_runtime_env_latch_no_kill_file"
    return False, "unknown_emergency_stop_reason"


def _quarantine(path: Path) -> Path:
    ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    target_dir = Path(
        os.environ.get(
            "NIJA_EMERGENCY_STOP_QUARANTINE_DIR",
            "/app/data/emergency_stop_quarantine",
        )
    )
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        target_dir = path.parent
    target = target_dir / f"{path.name}.{ts}.cleared_by_operator"
    try:
        shutil.move(str(path), str(target))
    except Exception:
        path.unlink(missing_ok=True)
        target.write_text(
            "original emergency stop removed after move failure\n",
            encoding="utf-8",
        )
    return target


def _clear_runtime_env() -> None:
    for env_name in _STOP_ENV_NAMES:
        os.environ.pop(env_name, None)
    os.environ.pop("NIJA_OPERATOR_CLEAR_EMERGENCY_STOP", None)
    os.environ.pop("NIJA_OPERATOR_CLEAR_EMERGENCY_STOP_ACK", None)
    os.environ.pop("NIJA_OPERATOR_CLEAR_EMERGENCY_STOP_REASON", None)
    # Clearing an operator stop returns the process only to a neutral state.
    # Normal writer/capital/heartbeat convergence must independently grant live
    # execution authority.
    if os.environ.get("NIJA_RUNTIME_TRADING_STATE", "").strip().upper() == "EMERGENCY_STOP":
        os.environ["NIJA_RUNTIME_TRADING_STATE"] = "OFF"
    os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] = "0"


def run_once() -> int:
    kill_files = _kill_files()
    state_files = _state_files()
    all_paths = kill_files + [path for path in state_files if path not in kill_files]

    if not all_paths:
        ok, reason = _safe_to_clear_stale_env_only()
        if ok:
            _clear_runtime_env()
            logger.critical(
                "OPERATOR_EMERGENCY_STOP_ENV_ONLY_CLEAR_APPLIED marker=%s reason=%s force_activation=false risk_bypass=false state_files_included=false",
                _MARKER,
                reason,
            )
            print(
                f"[NIJA-PRINT] OPERATOR_EMERGENCY_STOP_ENV_ONLY_CLEAR_APPLIED marker={_MARKER} reason={reason}",
                flush=True,
            )
            return 1
        logger.info(
            "OPERATOR_EMERGENCY_STOP_CLEAR_NOOP marker=%s reason=no_kill_or_state_file_found env_reason=%s",
            _MARKER,
            reason,
        )
        return 0

    ok, reason = _safe_to_clear(all_paths)
    if not ok:
        logger.critical(
            "OPERATOR_EMERGENCY_STOP_CLEAR_SKIPPED marker=%s reason=%s files=%s",
            _MARKER,
            reason,
            ",".join(str(path) for path in all_paths),
        )
        return 0

    operator_reason = _clean(os.environ.get("NIJA_OPERATOR_CLEAR_EMERGENCY_STOP_REASON"))
    cleared: list[str] = []
    for path in all_paths:
        try:
            target = _quarantine(path)
            cleared.append(f"{path}->{target}")
        except Exception as exc:
            logger.critical(
                "OPERATOR_EMERGENCY_STOP_CLEAR_FAILED marker=%s path=%s err=%s",
                _MARKER,
                path,
                exc,
            )
    if cleared:
        _clear_runtime_env()
        logger.critical(
            "OPERATOR_EMERGENCY_STOP_CLEAR_APPLIED marker=%s cleared=%s reason=%s force_activation=false risk_bypass=false state_files_included=true",
            _MARKER,
            ";".join(cleared),
            operator_reason,
        )
        print(
            f"[NIJA-PRINT] OPERATOR_EMERGENCY_STOP_CLEAR_APPLIED marker={_MARKER} cleared={len(cleared)}",
            flush=True,
        )
    return len(cleared)


def install_import_hook() -> None:
    """Run startup clear logic once even if sitecustomize reloads the module."""

    if getattr(builtins, _INSTALL_SENTINEL, False):
        return
    setattr(builtins, _INSTALL_SENTINEL, True)
    run_once()


def install() -> None:
    install_import_hook()


if __name__ == "__main__":
    raise SystemExit(0 if run_once() >= 0 else 1)
