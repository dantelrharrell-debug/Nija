"""Canonical live-capital freshness enforcement v64.

Production activation can remain LIVE_ACTIVE while the capital refresh worker is
between publications.  Every observer and new-risk dispatch path must therefore
use the same CapitalAuthority freshness contract instead of treating the static
LIVE_CAPITAL_VERIFIED mode flag as proof that current capital is still usable.

v64 makes three narrow repairs:

* preactivation v16 reads the canonical capital freshness TTL (default 90s)
  instead of CapitalAuthority.is_stale()'s legacy 60s default;
* the historical LIVE_ACTIVE compatibility gate no longer accepts
  LIVE_CAPITAL_VERIFIED as a substitute for a fresh funded CapitalAuthority;
* ExecutionPipeline rejects new-risk entries when current authoritative capital
  is unavailable, stale, unfunded, or broker-incomplete, while reduce/exit
  intents remain available for protective risk reduction.

No writer, nonce, kill-switch, risk, strategy, or execution-authority gate is
weakened by this patch.
"""
from __future__ import annotations

import builtins
import logging
import os
import sys
import threading
from functools import wraps
from types import ModuleType
from typing import Any

LOGGER = logging.getLogger("nija.live_capital_freshness_v64")
MARKER = "20260812-live-capital-freshness-v64"
_LOCK = threading.RLock()
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}
_V16_ATTR = "_nija_live_capital_freshness_v64"
_LIVE_GATE_ATTR = "_nija_live_capital_freshness_v64"
_PIPELINE_ATTR = "_nija_live_capital_freshness_v64"
_HOOK_FLAG = "_NIJA_LIVE_CAPITAL_FRESHNESS_V64_IMPORT_HOOK"
_TARGET_NAMES = {
    "preactivation_readiness_convergence_v16_patch",
    "bot.preactivation_readiness_convergence_v16_patch",
    "bot.live_active_execution_gate_final_patch",
    "live_active_execution_gate_final_patch",
    "bot.execution_pipeline",
    "execution_pipeline",
}


def _truthy(name: str, default: str = "false") -> bool:
    return str(os.environ.get(name, default) or "").strip().lower() in _TRUE


def _ttl_s() -> float:
    raw = os.environ.get("NIJA_CAPITAL_FRESHNESS_TTL_S", "90")
    try:
        return max(1.0, float(raw or 90.0))
    except (TypeError, ValueError):
        return 90.0


def _capital_authority() -> Any:
    for name in ("bot.capital_authority", "capital_authority"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            getter = getattr(module, "get_capital_authority", None)
            if callable(getter):
                try:
                    return getter()
                except Exception:
                    return None
    try:
        import importlib

        module = importlib.import_module("bot.capital_authority")
        getter = getattr(module, "get_capital_authority", None)
        return getter() if callable(getter) else None
    except Exception:
        return None


def _real_capital(authority: Any) -> float:
    values: list[float] = []
    for name in ("get_real_capital", "get_total_capital", "get_usable_capital"):
        method = getattr(authority, name, None)
        if callable(method):
            try:
                values.append(float(method() or 0.0))
            except Exception:
                pass
    for name in ("total_capital", "real_capital", "available_capital"):
        try:
            values.append(float(getattr(authority, name, 0.0) or 0.0))
        except Exception:
            pass
    return max(values or [0.0])


def _registered_count(authority: Any) -> int:
    counts: list[int] = []
    for name in ("registered_broker_count", "valid_broker_count"):
        try:
            counts.append(int(getattr(authority, name, 0) or 0))
        except Exception:
            pass
    values = getattr(authority, "broker_values", None) or getattr(authority, "values", None)
    if isinstance(values, dict):
        counts.append(len(values))
    return max(counts or [0])


def _canonical_capital_status() -> tuple[bool, str, dict[str, Any]]:
    """Return current authoritative capital usability for NEW risk only."""
    authority = _capital_authority()
    ttl = _ttl_s()
    details: dict[str, Any] = {"ttl_s": ttl}
    if authority is None:
        return False, "capital_authority_unavailable", details

    hydrated = bool(getattr(authority, "is_hydrated", False))
    real = _real_capital(authority)
    registered = _registered_count(authority)
    details.update(
        {
            "hydrated": hydrated,
            "real_capital": real,
            "registered": registered,
        }
    )

    is_fresh = getattr(authority, "is_fresh", None)
    if callable(is_fresh):
        try:
            fresh = bool(is_fresh(ttl_s=ttl))
        except TypeError:
            try:
                fresh = bool(is_fresh(ttl))
            except Exception:
                fresh = False
        except Exception:
            fresh = False
    else:
        is_stale = getattr(authority, "is_stale", None)
        if callable(is_stale):
            try:
                fresh = not bool(is_stale(ttl_s=ttl))
            except TypeError:
                try:
                    fresh = not bool(is_stale(ttl))
                except Exception:
                    fresh = False
            except Exception:
                fresh = False
        else:
            fresh = False
    details["fresh"] = fresh

    complete = True
    is_complete = getattr(authority, "is_brokers_complete", None)
    if callable(is_complete):
        try:
            complete = bool(is_complete())
        except Exception:
            complete = False
    details["brokers_complete"] = complete

    if not hydrated:
        return False, "capital_not_hydrated", details
    if real <= 0.0:
        return False, "capital_not_funded", details
    if registered <= 0:
        return False, "capital_no_registered_brokers", details
    if not fresh:
        return False, "capital_snapshot_stale", details
    if not complete:
        return False, "capital_brokers_incomplete", details
    return True, "capital_fresh_funded_complete", details


def _patch_v16(module: ModuleType) -> bool:
    current = getattr(module, "_capital_snapshot", None)
    if not callable(current):
        return False
    if getattr(current, _V16_ATTR, False):
        return True

    @wraps(current)
    def capital_snapshot_v64() -> dict[str, Any]:
        result = dict(current() or {})
        authority = _capital_authority()
        if authority is None:
            result["stale"] = True
            result["v64_freshness_reason"] = "capital_authority_unavailable"
            result["v64_freshness_ttl_s"] = _ttl_s()
            return result

        ttl = _ttl_s()
        fresh = False
        is_fresh = getattr(authority, "is_fresh", None)
        if callable(is_fresh):
            try:
                fresh = bool(is_fresh(ttl_s=ttl))
            except TypeError:
                try:
                    fresh = bool(is_fresh(ttl))
                except Exception:
                    fresh = False
            except Exception:
                fresh = False
        else:
            is_stale = getattr(authority, "is_stale", None)
            if callable(is_stale):
                try:
                    fresh = not bool(is_stale(ttl_s=ttl))
                except TypeError:
                    try:
                        fresh = not bool(is_stale(ttl))
                    except Exception:
                        fresh = False
                except Exception:
                    fresh = False

        result["stale"] = not fresh
        result["v64_freshness_ttl_s"] = ttl
        result["v64_freshness_reason"] = "canonical_is_fresh" if fresh else "canonical_stale"
        return result

    setattr(capital_snapshot_v64, _V16_ATTR, True)
    module._capital_snapshot = capital_snapshot_v64
    LOGGER.critical(
        "LIVE_CAPITAL_FRESHNESS_V64_V16_PATCHED marker=%s module=%s canonical_ttl=true",
        MARKER,
        module.__name__,
    )
    return True


def _patch_live_active_gate(module: ModuleType) -> bool:
    current = getattr(module, "_capital_ready", None)
    if not callable(current):
        return False
    if getattr(current, _LIVE_GATE_ATTR, False):
        return True

    @wraps(current)
    def capital_ready_v64() -> bool:
        ready, reason, details = _canonical_capital_status()
        if not ready:
            LOGGER.warning(
                "LIVE_CAPITAL_FRESHNESS_V64_COMPAT_BLOCK marker=%s reason=%s details=%s live_capital_verified=%s",
                MARKER,
                reason,
                details,
                _truthy("LIVE_CAPITAL_VERIFIED"),
            )
        return ready

    setattr(capital_ready_v64, _LIVE_GATE_ATTR, True)
    module._capital_ready = capital_ready_v64
    LOGGER.critical(
        "LIVE_CAPITAL_FRESHNESS_V64_COMPAT_PATCHED marker=%s module=%s static_live_flag_bypass=false",
        MARKER,
        module.__name__,
    )
    return True


def _is_protective_intent(request: Any) -> bool:
    intent = str(getattr(request, "intent_type", "") or "entry").strip().lower()
    if intent in {"reduce", "exit", "close", "liquidate"}:
        return True
    try:
        if bool(getattr(request, "reduce_only", False)):
            return True
    except Exception:
        pass
    return False


def _patch_execution_pipeline(module: ModuleType) -> bool:
    cls = getattr(module, "ExecutionPipeline", None)
    if not isinstance(cls, type):
        return False
    current = getattr(cls, "_enforce_execution_gate", None)
    if not callable(current):
        return False
    if getattr(current, _PIPELINE_ATTR, False):
        return True

    @wraps(current)
    def enforce_execution_gate_v64(self: Any, request: Any, t_start: float):
        existing = current(self, request, t_start)
        if existing is not None:
            return existing
        if _is_protective_intent(request):
            return None

        ready, reason, details = _canonical_capital_status()
        if ready:
            return None

        LOGGER.critical(
            "LIVE_CAPITAL_FRESHNESS_V64_ENTRY_BLOCK marker=%s reason=%s symbol=%s side=%s details=%s protective=false",
            MARKER,
            reason,
            getattr(request, "symbol", "?"),
            getattr(request, "side", "?"),
            details,
        )
        deny = getattr(self, "_deny", None)
        if callable(deny):
            return deny(
                request,
                t_start,
                f"Capital freshness deny: {reason}",
            )
        return existing

    setattr(enforce_execution_gate_v64, _PIPELINE_ATTR, True)
    cls._enforce_execution_gate = enforce_execution_gate_v64
    LOGGER.critical(
        "LIVE_CAPITAL_FRESHNESS_V64_PIPELINE_PATCHED marker=%s module=%s new_entries_fail_closed=true protective_exits_bypass=true",
        MARKER,
        module.__name__,
    )
    return True


def _patch_loaded() -> bool:
    patched = False
    seen: set[int] = set()
    for name in tuple(_TARGET_NAMES):
        module = sys.modules.get(name)
        if not isinstance(module, ModuleType) or id(module) in seen:
            continue
        seen.add(id(module))
        if "preactivation_readiness_convergence_v16_patch" in name:
            patched = _patch_v16(module) or patched
        elif "live_active_execution_gate_final_patch" in name:
            patched = _patch_live_active_gate(module) or patched
        elif name.endswith("execution_pipeline"):
            patched = _patch_execution_pipeline(module) or patched
    return patched


def install_import_hook() -> bool:
    with _LOCK:
        _patch_loaded()
        if not getattr(builtins, _HOOK_FLAG, False):
            original_import = builtins.__import__

            @wraps(original_import)
            def importing(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
                result = original_import(name, globals, locals, fromlist, level)
                text = str(name or "")
                if any(target in text for target in (
                    "preactivation_readiness_convergence_v16_patch",
                    "live_active_execution_gate_final_patch",
                    "execution_pipeline",
                )):
                    _patch_loaded()
                return result

            builtins.__import__ = importing
            setattr(builtins, _HOOK_FLAG, True)

        os.environ["NIJA_LIVE_CAPITAL_FRESHNESS_V64_READY"] = "1"
        LOGGER.critical(
            "LIVE_CAPITAL_FRESHNESS_V64_INSTALLED marker=%s canonical_ttl_s=%.1f new_entries_fail_closed=true protective_exits_preserved=true",
            MARKER,
            _ttl_s(),
        )
        return True


def install() -> bool:
    return install_import_hook()


__all__ = [
    "MARKER",
    "install",
    "install_import_hook",
    "_canonical_capital_status",
    "_is_protective_intent",
]
