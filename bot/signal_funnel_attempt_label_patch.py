"""Relabel signal funnel execution counters as attempts, not fills."""

from __future__ import annotations

import importlib
import logging
import sys
import threading
import time
from types import ModuleType
from typing import Any, Callable, Optional

logger = logging.getLogger("nija.signal_funnel_attempt_label")

_MARKER = "SIGNAL_FUNNEL_ATTEMPT_LABEL_PATCHED marker=20260706b"
_TARGETS = {"bot.signal_funnel_diagnostics", "signal_funnel_diagnostics"}
_LOCK = threading.Lock()
_ORIGINAL_IMPORT_MODULE: Optional[Callable[..., Any]] = None
_MONITOR_STARTED = False
_PATCHED = False


class _AttemptLabelFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            if isinstance(record.msg, str):
                record.msg = record.msg.replace(" executed=%d", " execution_attempts=%d")
        except Exception:
            pass
        return True


def _patch_module(module: ModuleType) -> bool:
    global _PATCHED
    stats_cls = getattr(module, "FunnelStats", None)
    diag_cls = getattr(module, "SignalFunnelDiagnostics", None)
    if not isinstance(stats_cls, type) or not isinstance(diag_cls, type):
        return False

    original_line = getattr(stats_cls, "as_log_line", None)
    if callable(original_line) and not getattr(original_line, "_nija_attempt_label_v20260706b", False):
        def as_log_line(self: Any) -> str:
            return str(original_line(self)).replace("execution_pass=", "execution_attempts=")
        setattr(as_log_line, "_nija_attempt_label_v20260706b", True)
        setattr(stats_cls, "as_log_line", as_log_line)

    original_report = getattr(diag_cls, "maybe_report_and_reset", None)
    if callable(original_report) and not getattr(original_report, "_nija_attempt_summary_label_v20260706b", False):
        def maybe_report_and_reset(self: Any) -> None:
            funnel_logger = logging.getLogger("nija.signal_funnel")
            filt = _AttemptLabelFilter()
            funnel_logger.addFilter(filt)
            try:
                return original_report(self)
            finally:
                try:
                    funnel_logger.removeFilter(filt)
                except Exception:
                    pass
        setattr(maybe_report_and_reset, "_nija_attempt_summary_label_v20260706b", True)
        setattr(diag_cls, "maybe_report_and_reset", maybe_report_and_reset)

    _PATCHED = True
    logger.warning("%s module=%s", _MARKER, getattr(module, "__name__", "<unknown>"))
    return True


def _try_patch_loaded() -> bool:
    changed = False
    for name in _TARGETS:
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            changed = _patch_module(module) or changed
    return changed


def _start_monitor() -> None:
    global _MONITOR_STARTED
    if _MONITOR_STARTED:
        return
    _MONITOR_STARTED = True

    def _monitor() -> None:
        deadline = time.time() + 240.0
        while time.time() < deadline:
            if _try_patch_loaded():
                return
            time.sleep(0.5)
        logger.warning("SIGNAL_FUNNEL_ATTEMPT_LABEL_MONITOR_EXPIRED patched=%s", _PATCHED)

    threading.Thread(target=_monitor, name="signal-funnel-attempt-label", daemon=True).start()


def install_import_hook() -> None:
    global _ORIGINAL_IMPORT_MODULE
    with _LOCK:
        logger.warning("SIGNAL_FUNNEL_ATTEMPT_LABEL_INSTALL_START marker=20260706b")
        _try_patch_loaded()
        _start_monitor()
        if _ORIGINAL_IMPORT_MODULE is not None:
            return
        _ORIGINAL_IMPORT_MODULE = importlib.import_module

        def _wrapped_import_module(name: str, package: str | None = None):
            module = _ORIGINAL_IMPORT_MODULE(name, package)  # type: ignore[misc]
            if name in _TARGETS:
                _patch_module(module)
            return module

        importlib.import_module = _wrapped_import_module  # type: ignore[assignment]


def install() -> None:
    install_import_hook()
