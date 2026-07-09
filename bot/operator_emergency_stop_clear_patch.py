from __future__ import annotations

import json
import logging
import os
import shutil
import time
from pathlib import Path
from typing import Iterable

logger = logging.getLogger("nija.operator_emergency_stop_clear")
_MARKER = "20260709w"
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
    values: Iterable[str]
    if raw:
        values = [piece.strip() for piece in raw.split(",") if piece.strip()]
    else:
        values = defaults
    found: list[Path] = []
    for item in values:
        try:
            path = Path(item).expanduser()
            if path.exists() and path.is_file():
                found.append(path)
        except Exception as exc:
            logger.warning("OPERATOR_EMERGENCY_STOP_CLEAR_PATH_CHECK_FAILED marker=%s path=%s err=%s", _MARKER, item, exc)
    return found


def _kill_files() -> list[Path]:
    return _split_paths(_clean(os.environ.get("NIJA_EMERGENCY_STOP_FILES")), _DEFAULT_KILL_FILES)


def _state_files() -> list[Path]:
    return _split_paths(_clean(os.environ.get("NIJA_EMERGENCY_STOP_STATE_FILES")), _DEFAULT_STATE_FILES)


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
    for env_name in (
        "NIJA_EMERGENCY_STOP_REASON",
        "NIJA_KILL_SWITCH_REASON",
        "NIJA_PRE_HALT_REASON",
        "NIJA_RUNTIME_STOP_REASON",
        "NIJA_OPERATOR_EMERGENCY_STOP_REASON",
    ):
        value = os.environ.get(env_name)
        if value:
            chunks.append(f"{env_name}={value}")
    return "\n".join(chunks).lower()


def _stop_reason_safe_to_clear(paths: Iterable[Path]) -> tuple[bool, str]:
    text = _combined_stop_text(paths)
    if any(token in text for token in _TERMINAL_RISK_TOKENS):
        return False, "terminal_risk_reason_present"
    if text and not any(token in text for token in _MANUAL_CLEAR_ALLOWED_TOKENS):
        # Unknown stop source should not be auto-cleared. The operator clear path
        # is explicit, but still refuses opaque terminal stop content.
        return False, "unknown_emergency_stop_reason"
    return True, "operator_manual_clear_allowed"


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
    if _truthy("NIJA_FORCE_ACTIVATION", False) or _truthy("NIJA_FORCE_LOCAL_WRITER_LOCK_FALLBACK", False):
        return False, "unsafe_force_activation_or_local_fallback_present"
    if _truthy("NIJA_DISABLE_WRITER_LOCK", False) or _truthy("NIJA_UNSAFE_BYPASS_DISTRIBUTED_LOCK", False):
        return False, "unsafe_writer_lock_bypass_present"
    if _truthy("NIJA_CLEAR_TERMINAL_RISK_BLOCKS", False) or _truthy("NIJA_BYPASS_RISK_GATES", False):
        return False, "unsafe_risk_bypass_present"
    stop_ok, stop_reason = _stop_reason_safe_to_clear(all_paths)
    if not stop_ok:
        return False, stop_reason
    return True, "operator_approved"


def _quarantine(path: Path) -> Path:
    ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    target_dir = Path(os.environ.get("NIJA_EMERGENCY_STOP_QUARANTINE_DIR", "/app/data/emergency_stop_quarantine"))
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        target_dir = path.parent
    target = target_dir / f"{path.name}.{ts}.cleared_by_operator"
    try:
        shutil.move(str(path), str(target))
    except Exception:
        path.unlink(missing_ok=True)
        target.write_text("original emergency stop removed after move failure\n", encoding="utf-8")
    return target


def _clear_runtime_env() -> None:
    for env_name in (
        "NIJA_EMERGENCY_STOP_REASON",
        "NIJA_KILL_SWITCH_REASON",
        "NIJA_PRE_HALT_REASON",
        "NIJA_RUNTIME_STOP_REASON",
        "NIJA_OPERATOR_EMERGENCY_STOP_REASON",
    ):
        os.environ.pop(env_name, None)
    # Do not force LIVE_ACTIVE here. Clearing an operator stop only returns the
    # system to a neutral non-emergency runtime; activation/convergence patches
    # still have to prove CapitalAuthority, writer authority and heartbeat.
    if os.environ.get("NIJA_RUNTIME_TRADING_STATE", "").strip().upper() == "EMERGENCY_STOP":
        os.environ["NIJA_RUNTIME_TRADING_STATE"] = "OFF"
    if os.environ.get("NIJA_RUNTIME_EXECUTION_AUTHORITY", "").strip() == "0":
        os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] = "0"


def run_once() -> int:
    kill_files = _kill_files()
    state_files = _state_files()
    all_paths = kill_files + [path for path in state_files if path not in kill_files]
    if not all_paths:
        logger.info("OPERATOR_EMERGENCY_STOP_CLEAR_NOOP marker=%s reason=no_kill_or_state_file_found", _MARKER)
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
    cleared = []
    for path in all_paths:
        try:
            target = _quarantine(path)
            cleared.append(f"{path}->{target}")
        except Exception as exc:
            logger.critical("OPERATOR_EMERGENCY_STOP_CLEAR_FAILED marker=%s path=%s err=%s", _MARKER, path, exc)
    if cleared:
        _clear_runtime_env()
        logger.critical(
            "OPERATOR_EMERGENCY_STOP_CLEAR_APPLIED marker=%s cleared=%s reason=%s force_activation=false risk_bypass=false state_files_included=true",
            _MARKER,
            ";".join(cleared),
            _clean(os.environ.get("NIJA_OPERATOR_CLEAR_EMERGENCY_STOP_REASON")),
        )
        print(f"[NIJA-PRINT] OPERATOR_EMERGENCY_STOP_CLEAR_APPLIED marker={_MARKER} cleared={len(cleared)}", flush=True)
    return len(cleared)


def install_import_hook() -> None:
    run_once()


def install() -> None:
    run_once()


if __name__ == "__main__":
    raise SystemExit(0 if run_once() >= 0 else 1)
