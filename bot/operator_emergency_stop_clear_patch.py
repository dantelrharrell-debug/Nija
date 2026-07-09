from __future__ import annotations

import logging
import os
import shutil
import time
from pathlib import Path
from typing import Iterable

logger = logging.getLogger("nija.operator_emergency_stop_clear")
_MARKER = "20260709a"
_TRUTHY = {"1", "true", "yes", "on", "y", "enabled"}
_APPROVAL_PHRASE = "CLEAR_EMERGENCY_STOP_FOR_LIVE_TRADING"
_DEFAULT_KILL_FILES = ("/app/EMERGENCY_STOP", "./EMERGENCY_STOP", "./data/EMERGENCY_STOP")


def _truthy(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in _TRUTHY


def _clean(value: object) -> str:
    return str(value or "").strip().strip('"').strip("'").strip()


def _live_mode() -> bool:
    return not _truthy("DRY_RUN_MODE") and not _truthy("PAPER_MODE")


def _kill_files() -> list[Path]:
    raw = _clean(os.environ.get("NIJA_EMERGENCY_STOP_FILES"))
    values: Iterable[str]
    if raw:
        values = [piece.strip() for piece in raw.split(",") if piece.strip()]
    else:
        values = _DEFAULT_KILL_FILES
    found: list[Path] = []
    for item in values:
        try:
            path = Path(item).expanduser()
            if path.exists() and path.is_file():
                found.append(path)
        except Exception as exc:
            logger.warning("OPERATOR_EMERGENCY_STOP_CLEAR_PATH_CHECK_FAILED marker=%s path=%s err=%s", _MARKER, item, exc)
    return found


def _safe_to_clear() -> tuple[bool, str]:
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


def run_once() -> int:
    kill_files = _kill_files()
    if not kill_files:
        logger.info("OPERATOR_EMERGENCY_STOP_CLEAR_NOOP marker=%s reason=no_kill_file_found", _MARKER)
        return 0
    ok, reason = _safe_to_clear()
    if not ok:
        logger.critical(
            "OPERATOR_EMERGENCY_STOP_CLEAR_SKIPPED marker=%s reason=%s kill_files=%s",
            _MARKER,
            reason,
            ",".join(str(path) for path in kill_files),
        )
        return 0
    cleared = []
    for path in kill_files:
        try:
            target = _quarantine(path)
            cleared.append(f"{path}->{target}")
        except Exception as exc:
            logger.critical("OPERATOR_EMERGENCY_STOP_CLEAR_FAILED marker=%s path=%s err=%s", _MARKER, path, exc)
    if cleared:
        logger.critical(
            "OPERATOR_EMERGENCY_STOP_CLEAR_APPLIED marker=%s cleared=%s reason=%s force_activation=false risk_bypass=false",
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
