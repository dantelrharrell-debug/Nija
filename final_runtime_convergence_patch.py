"""Final convergence repair for duplicate scans and auth hook recursion.

This patch is intentionally narrow. It preserves broker authentication, writer
lineage, risk controls, exchange validation, and all exit protections.
"""
from __future__ import annotations

import logging
import os
import sys
import threading
from types import ModuleType, SimpleNamespace
from typing import Any, Callable

logger = logging.getLogger("nija.final_runtime_convergence")
MARKER = "20260712d"
_LOCK = threading.RLock()
_PATCHED = False


def _auth_module() -> ModuleType | None:
    module = sys.modules.get("broker_auth_recovery_patch")
    return module if isinstance(module, ModuleType) else None


def _set_okx_endpoint(instance: Any, url: str) -> None:
    normalized = str(url or "").strip().rstrip("/")
    if not normalized:
        return
    os.environ["OKX_BASE_URL"] = normalized
    for attr in ("base_url", "api_base_url", "endpoint", "api_url", "rest_url"):
        try:
            if hasattr(instance, attr):
                setattr(instance, attr, normalized)
        except Exception:
            pass


def _safe_normalize(venue: str, instance: Any | None = None) -> None:
    auth = _auth_module()
    if auth is None:
        return
    normalizer = getattr(auth, f"normalize_{venue}_environment", None)
    if callable(normalizer):
        normalizer()
    if venue == "okx" and instance is not None:
        _set_okx_endpoint(instance, os.environ.get("OKX_BASE_URL", ""))


def _replace_recursive_auth_hooks() -> bool:
    patched = False
    legacy = sys.modules.get("runtime_convergence_hardening_patch")
    if isinstance(legacy, ModuleType):
        def safe_patch_auth_surface(target: ModuleType) -> bool:
            changed = False
            for class_name in dir(target):
                cls = getattr(target, class_name, None)
                if not isinstance(cls, type):
                    continue
                lowered = class_name.lower()
                venue = "coinbase" if "coinbase" in lowered else "okx" if "okx" in lowered else ""
                if not venue:
                    continue
                for method_name in ("connect", "verify_connection", "test_connection"):
                    original = getattr(cls, method_name, None)
                    if not callable(original) or getattr(original, "_nija_final_auth_safe", False):
                        continue

                    def wrapped(self: Any, *args: Any, __original: Callable[..., Any] = original,
                                __venue: str = venue, **kwargs: Any) -> Any:
                        _safe_normalize(__venue, self)
                        return __original(self, *args, **kwargs)

                    wrapped._nija_final_auth_safe = True  # type: ignore[attr-defined]
                    wrapped.__wrapped__ = original  # type: ignore[attr-defined]
                    setattr(cls, method_name, wrapped)
                    changed = True
            return changed

        legacy._patch_auth_surface = safe_patch_auth_surface
        patched = True

    v2 = sys.modules.get("runtime_convergence_v2_patch")
    if isinstance(v2, ModuleType):
        v2._normalize_auth = lambda venue: _safe_normalize(str(venue))
        patched = True

    if patched:
        logger.warning("AUTH_IMPORT_RECURSION_REMOVED marker=%s", MARKER)
    return patched


def _duplicate_result() -> SimpleNamespace:
    return SimpleNamespace(
        symbols_scored=0,
        entries_taken=0,
        entries_blocked=1,
        exits_taken=0,
        next_interval=max(5, int(float(os.getenv("NIJA_DUPLICATE_SCAN_NEXT_INTERVAL_S", "15") or 15))),
        errors=["duplicate_scan_suppressed"],
        metadata={"duplicate_scan": True},
    )


def _coerce_scan_result(result: Any) -> Any:
    if result is None:
        return _duplicate_result()
    if isinstance(result, tuple):
        scored = int(result[0] or 0) if len(result) > 0 else 0
        blocked = int(result[1] or 0) if len(result) > 1 else 0
        entered = int(result[2] or 0) if len(result) > 2 else 0
        meta = result[3] if len(result) > 3 and isinstance(result[3], dict) else {}
        return SimpleNamespace(
            symbols_scored=scored,
            entries_taken=entered,
            entries_blocked=blocked,
            exits_taken=int(meta.get("exits_taken", 0) or 0),
            next_interval=int(meta.get("next_interval", 15) or 15),
            errors=list(meta.get("errors", [])),
            metadata=meta,
        )
    return result


def _patch_core_loop(module: ModuleType) -> bool:
    cls = getattr(module, "NijaCoreLoop", None)
    if not isinstance(cls, type):
        return False
    original = getattr(cls, "run_scan_phase", None)
    if not callable(original) or getattr(original, "_nija_final_result_contract", False):
        return False

    def run_scan_phase(self: Any, *args: Any, **kwargs: Any) -> Any:
        result = original(self, *args, **kwargs)
        coerced = _coerce_scan_result(result)
        if coerced is not result:
            logger.warning(
                "DUPLICATE_SCAN_RESULT_CONTRACT_REPAIRED marker=%s result_type=%s",
                MARKER, type(result).__name__,
            )
        return coerced

    run_scan_phase._nija_final_result_contract = True  # type: ignore[attr-defined]
    run_scan_phase.__wrapped__ = original  # type: ignore[attr-defined]
    setattr(cls, "run_scan_phase", run_scan_phase)
    logger.warning("SCAN_RESULT_CONTRACT_PATCHED marker=%s", MARKER)
    return True


def _patch_okx_classes() -> bool:
    changed = False
    for module_name in (
        "bot.broker_manager", "broker_manager",
        "bot.broker_integration", "broker_integration",
        "bot.multi_account_broker_manager", "multi_account_broker_manager",
    ):
        module = sys.modules.get(module_name)
        if not isinstance(module, ModuleType):
            continue
        for class_name in dir(module):
            cls = getattr(module, class_name, None)
            if not isinstance(cls, type) or "okx" not in class_name.lower():
                continue
            original = getattr(cls, "connect", None)
            if not callable(original) or getattr(original, "_nija_final_okx_endpoint", False):
                continue

            def connect(self: Any, *args: Any, __original: Callable[..., Any] = original, **kwargs: Any) -> Any:
                _safe_normalize("okx", self)
                before = str(os.environ.get("OKX_BASE_URL", "") or "").strip().rstrip("/")
                result = __original(self, *args, **kwargs)
                after = str(os.environ.get("OKX_BASE_URL", "") or "").strip().rstrip("/")
                if after and after != before:
                    _set_okx_endpoint(self, after)
                return result

            connect._nija_final_okx_endpoint = True  # type: ignore[attr-defined]
            connect.__wrapped__ = original  # type: ignore[attr-defined]
            setattr(cls, "connect", connect)
            changed = True
    if changed:
        logger.warning("OKX_LIVE_ENDPOINT_CONVERGENCE_PATCHED marker=%s", MARKER)
    return changed


def install() -> None:
    global _PATCHED
    with _LOCK:
        changed = _replace_recursive_auth_hooks()
        for name in ("bot.nija_core_loop", "nija_core_loop"):
            module = sys.modules.get(name)
            if isinstance(module, ModuleType):
                changed = _patch_core_loop(module) or changed
        changed = _patch_okx_classes() or changed
        _PATCHED = _PATCHED or changed
        logger.warning("FINAL_RUNTIME_CONVERGENCE_INSTALLED marker=%s patched=%s", MARKER, _PATCHED)


def installed() -> bool:
    return _PATCHED


__all__ = ["install", "installed", "_coerce_scan_result", "_duplicate_result"]
