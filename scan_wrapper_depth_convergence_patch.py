"""Prevent unbounded ``NijaCoreLoop.run_scan_phase`` wrapper growth.

The broker-independent live execution patch historically checked only the
outermost method for its marker and did not expose ``__wrapped__``. Once the
canonical scan owner became outermost, the broker monitor installed another
broker wrapper. The two layers alternated until runtime recovery reported more
than one thousand wrappers.

This guard makes that installer chain-aware, repairs the next installed wrapper
to expose its base, and audits the live scan chain. A release is unsafe when the
chain cycles, exceeds the configured depth, or contains duplicate canonical or
broker-independent owners.

``functools.wraps`` copies the wrapped function's ``__dict__``. A later wrapper
can therefore carry NIJA ownership marker attributes even though its code was
defined by a different patch. Ownership counts use the function code filename,
while raw marker counts remain diagnostic. This distinguishes real duplicate
owners from copied metadata.
"""
from __future__ import annotations

import importlib
import logging
import os
import sys
import threading
import time
from functools import wraps
from pathlib import Path
from types import ModuleType
from typing import Any, Callable

logger = logging.getLogger("nija.scan_wrapper_depth_convergence")
_MARKER = "20260715-scan-depth-v1"
_GUARD_ATTR = "_nija_scan_depth_guard_v1"
_BROKER_ATTR = "_nija_broker_independent_live_execution_v20260705a"
_CANONICAL_RELEASE_ATTR = "_nija_scan_wrapper_release"
_BROKER_OWNER_FILE = "broker_independent_live_execution_patch.py"
_CANONICAL_OWNER_FILE = "scan_wrapper_convergence_repair_patch.py"
_LOCK = threading.RLock()
_STARTED = False
_LAST_SIGNATURE = ""

_CLOSURE_NAMES = (
    "original",
    "original_run_scan_phase",
    "original_scan_phase",
    "original_method",
    "wrapped",
    "base",
)


def _closure_link(func: Callable[..., Any]) -> Callable[..., Any] | None:
    try:
        code = getattr(func, "__code__", None)
        closure = tuple(getattr(func, "__closure__", ()) or ())
        freevars = tuple(getattr(code, "co_freevars", ()) or ())
        values = {name: cell.cell_contents for name, cell in zip(freevars, closure)}
    except Exception:
        return None
    for name in _CLOSURE_NAMES:
        candidate = values.get(name)
        if callable(candidate) and candidate is not func:
            return candidate
    return None


def _next_link(func: Callable[..., Any]) -> Callable[..., Any] | None:
    wrapped = getattr(func, "__wrapped__", None)
    if callable(wrapped) and wrapped is not func:
        return wrapped
    return _closure_link(func)


def _code_filename(func: Any) -> str:
    try:
        code = getattr(func, "__code__", None)
        return str(getattr(code, "co_filename", "") or "").replace("\\", "/")
    except Exception:
        return ""


def _owns_marker(func: Any, attr: str, owner_file: str) -> bool:
    if not bool(getattr(func, attr, False)):
        return False
    filename = _code_filename(func)
    return bool(filename and Path(filename).name == owner_file)


def inspect_chain(func: Any, *, limit: int = 4096) -> dict[str, Any]:
    current = func
    seen: set[int] = set()
    depth = 0
    broker_layers = 0
    canonical_layers = 0
    raw_broker_markers = 0
    raw_canonical_markers = 0
    cycle = False
    names: list[str] = []
    while callable(current):
        ident = id(current)
        if ident in seen:
            cycle = True
            break
        seen.add(ident)
        names.append(getattr(current, "__qualname__", getattr(current, "__name__", type(current).__name__)))
        raw_broker_markers += int(bool(getattr(current, _BROKER_ATTR, False)))
        raw_canonical_markers += int(bool(getattr(current, _CANONICAL_RELEASE_ATTR, "")))
        broker_layers += int(_owns_marker(current, _BROKER_ATTR, _BROKER_OWNER_FILE))
        canonical_layers += int(
            _owns_marker(current, _CANONICAL_RELEASE_ATTR, _CANONICAL_OWNER_FILE)
        )
        nxt = _next_link(current)
        if not callable(nxt):
            break
        current = nxt
        depth += 1
        if depth >= limit:
            cycle = True
            break
    return {
        "depth": depth,
        "broker_layers": broker_layers,
        "canonical_layers": canonical_layers,
        "raw_broker_markers": raw_broker_markers,
        "raw_canonical_markers": raw_canonical_markers,
        "cycle": cycle,
        "head": names[0] if names else "missing",
        "tail": names[-1] if names else "missing",
    }


def _chain_has_broker_layer(func: Any) -> bool:
    return bool(inspect_chain(func).get("broker_layers"))


def _repair_new_broker_wrapper(cls: type, previous: Callable[..., Any]) -> None:
    current = getattr(cls, "run_scan_phase", None)
    if not callable(current) or current is previous:
        return
    if getattr(current, _BROKER_ATTR, False) and not callable(getattr(current, "__wrapped__", None)):
        try:
            setattr(current, "__wrapped__", previous)
        except Exception:
            logger.exception("BROKER_SCAN_WRAPPER_LINK_REPAIR_FAILED marker=%s", _MARKER)


def _guard_broker_module(module: ModuleType) -> bool:
    patch_core = getattr(module, "_patch_core_loop_module", None)
    if not callable(patch_core):
        return False
    if getattr(patch_core, _GUARD_ATTR, False):
        os.environ["NIJA_SCAN_WRAPPER_DEPTH_GUARD_INSTALLED"] = "1"
        return True

    @wraps(patch_core)
    def guarded_patch_core(core_module: ModuleType) -> bool:
        cls = getattr(core_module, "NijaCoreLoop", None)
        current = getattr(cls, "run_scan_phase", None) if isinstance(cls, type) else None
        if callable(current) and _chain_has_broker_layer(current):
            try:
                setattr(module, "_PATCHED", True)
            except Exception:
                pass
            return True
        previous = current
        result = bool(patch_core(core_module))
        if result and isinstance(cls, type) and callable(previous):
            _repair_new_broker_wrapper(cls, previous)
        return result

    setattr(guarded_patch_core, _GUARD_ATTR, True)
    setattr(guarded_patch_core, "__wrapped__", patch_core)
    module._patch_core_loop_module = guarded_patch_core
    os.environ["NIJA_SCAN_WRAPPER_DEPTH_GUARD_INSTALLED"] = "1"
    logger.critical(
        "BROKER_SCAN_INSTALLER_CHAIN_GUARDED marker=%s module=%s chain_aware=true",
        _MARKER,
        module.__name__,
    )
    return True


def _patch_loaded_broker_modules() -> bool:
    patched = False
    for name in (
        "bot.broker_independent_live_execution_patch",
        "broker_independent_live_execution_patch",
        "nija_broker_independent_live_execution_patch",
    ):
        module = sys.modules.get(name)
        if not isinstance(module, ModuleType):
            try:
                module = importlib.import_module(name)
            except Exception:
                continue
        if isinstance(module, ModuleType):
            patched = _guard_broker_module(module) or patched
    return patched


def _core_method() -> Any:
    for name in ("bot.nija_core_loop", "nija_core_loop"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            cls = getattr(module, "NijaCoreLoop", None)
            method = getattr(cls, "run_scan_phase", None) if isinstance(cls, type) else None
            if callable(method):
                return method
    return None


def audit() -> tuple[bool, dict[str, str]]:
    _patch_loaded_broker_modules()
    method = _core_method()
    if method is None:
        os.environ["NIJA_SCAN_WRAPPER_DEPTH_READY"] = "0"
        return False, {"scan_chain": "core_loop_not_loaded"}

    status = inspect_chain(method)
    try:
        max_depth = max(4, min(64, int(float(os.environ.get("NIJA_MAX_SCAN_WRAPPER_DEPTH", "24") or 24))))
    except Exception:
        max_depth = 24
    ready = (
        not bool(status["cycle"])
        and int(status["depth"]) <= max_depth
        and int(status["broker_layers"]) <= 1
        and int(status["canonical_layers"]) <= 1
    )
    os.environ["NIJA_SCAN_WRAPPER_DEPTH_READY"] = "1" if ready else "0"
    os.environ["NIJA_SCAN_WRAPPER_DEPTH"] = str(status["depth"])
    details = {
        "scan_chain": (
            f"depth={status['depth']};max={max_depth};broker_layers={status['broker_layers']};"
            f"canonical_layers={status['canonical_layers']};raw_broker_markers={status['raw_broker_markers']};"
            f"raw_canonical_markers={status['raw_canonical_markers']};cycle={status['cycle']};"
            f"head={status['head']};tail={status['tail']}"
        )
    }
    return ready, details


def _watchdog() -> None:
    global _LAST_SIGNATURE
    while True:
        try:
            ready, details = audit()
            signature = f"{ready}:{details}"
            if signature != _LAST_SIGNATURE:
                _LAST_SIGNATURE = signature
                logger.log(
                    logging.INFO if ready else logging.CRITICAL,
                    "SCAN_WRAPPER_DEPTH_AUDIT marker=%s ready=%s details=%s",
                    _MARKER,
                    str(ready).lower(),
                    details,
                )
        except Exception as exc:
            os.environ["NIJA_SCAN_WRAPPER_DEPTH_READY"] = "0"
            logger.critical("SCAN_WRAPPER_DEPTH_AUDIT_FAILED marker=%s error=%s", _MARKER, exc)
        time.sleep(max(1.0, float(os.environ.get("NIJA_SCAN_WRAPPER_DEPTH_AUDIT_S", "5") or 5)))


def install() -> None:
    global _STARTED
    with _LOCK:
        _patch_loaded_broker_modules()
        os.environ["NIJA_SCAN_WRAPPER_DEPTH_GUARD_INSTALLED"] = "1"
        if not _STARTED:
            _STARTED = True
            threading.Thread(target=_watchdog, name="ScanWrapperDepthGuard", daemon=True).start()
        logger.critical(
            "SCAN_WRAPPER_DEPTH_GUARD_INSTALLED marker=%s max_depth=%s ownership=code_origin",
            _MARKER,
            os.environ.get("NIJA_MAX_SCAN_WRAPPER_DEPTH", "24"),
        )


def install_import_hook() -> None:
    install()


__all__ = [
    "install",
    "install_import_hook",
    "audit",
    "inspect_chain",
    "_guard_broker_module",
    "_chain_has_broker_layer",
    "_code_filename",
    "_owns_marker",
]
