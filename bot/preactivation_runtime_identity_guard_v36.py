"""Canonical runtime-identity repair for preactivation readiness.

The legacy v16 monitor can observe an imported capital-authority alias that is
older than the live coordinator snapshot. It can also miss a published
strategy when the strategy is stored on a runtime module not included in its
small hard-coded module list. This guard replaces those two probes with
process-wide canonical discovery while preserving all original fail-closed
activation gates.
"""
from __future__ import annotations

import importlib
import logging
import os
import sys
from types import ModuleType
from typing import Any

logger = logging.getLogger("nija.preactivation_runtime_identity_guard_v36")
_MARKER = "20260727-preactivation-runtime-identity-v36"
_INSTALLED = False
_ORIGINAL_CAPITAL_SNAPSHOT = None
_ORIGINAL_STRATEGY_PUBLISHED = None

_TRUE = {"1", "true", "yes", "on", "enabled", "y"}


def _truthy(name: str, default: str = "false") -> bool:
    return str(os.environ.get(name, default) or "").strip().lower() in _TRUE


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value if value not in (None, "") else default)
    except Exception:
        return default


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value if value not in (None, "") else default))
    except Exception:
        return default


_TRUE = {"1", "true", "yes", "on", "enabled", "y"}


def _truthy_env(name: str, default: str = "false") -> bool:
    return str(os.environ.get(name, default) or "").strip().lower() in _TRUE


def _authority_snapshot(authority: Any, source: str) -> dict[str, Any]:
    result: dict[str, Any] = {
        "hydrated": bool(getattr(authority, "is_hydrated", False)),
        "stale": True,
        "real": 0.0,
        "registered": 0,
        "source": source,
        "timestamp": 0.0,
    }
    result["real"] = max(
        _float(getattr(authority, "total_capital", 0.0)),
        _float(getattr(authority, "real_capital", 0.0)),
        _float(getattr(authority, "available_capital", 0.0)),
    )
    for method_name in ("get_real_capital", "get_total_capital", "get_usable_capital"):
        method = getattr(authority, method_name, None)
        if callable(method):
            try:
                result["real"] = max(result["real"], _float(method()))
            except Exception:
                pass
    result["registered"] = max(
        _int(getattr(authority, "registered_broker_count", 0)),
        _int(getattr(authority, "valid_broker_count", 0)),
        _int(getattr(authority, "broker_count", 0)),
    )
    values = getattr(authority, "broker_values", None) or getattr(authority, "values", None) or {}
    if isinstance(values, dict):
        result["registered"] = max(
            result["registered"],
            sum(1 for value in values.values() if _float(value) > 0.0),
        )
    stale_probe = getattr(authority, "is_stale", None)
    try:
        result["stale"] = bool(stale_probe()) if callable(stale_probe) else bool(
            getattr(authority, "stale", getattr(authority, "is_stale", False))
        )
    except Exception:
        result["stale"] = True
    for name in ("snapshot_timestamp", "last_updated", "updated_at", "timestamp"):
        value = getattr(authority, name, None)
        if hasattr(value, "timestamp"):
            try:
                value = value.timestamp()
            except Exception:
                value = 0.0
        result["timestamp"] = max(result["timestamp"], _float(value))
    return result


def _candidate_authorities() -> list[tuple[Any, str]]:
    found: list[tuple[Any, str]] = []
    seen: set[int] = set()
    module_names = (
        "bot.capital_authority",
        "capital_authority",
        "bot.capital_flow_state_machine",
        "bot.capital_csm_v2",
        "capital_csm_v2",
        "bot.multi_account_broker_manager",
        "bot.bot",
        "bot.bot_main",
        "__main__",
    )
    for module_name in module_names:
        module = sys.modules.get(module_name)
        if module is None:
            try:
                module = importlib.import_module(module_name)
            except Exception:
                continue
        for getter_name in ("get_capital_authority", "get_authority", "get_capital_csm"):
            getter = getattr(module, getter_name, None)
            if callable(getter):
                try:
                    authority = getter()
                except Exception:
                    continue
                if authority is not None and id(authority) not in seen:
                    seen.add(id(authority))
                    found.append((authority, f"{module_name}.{getter_name}"))
        for attr_name in (
            "_capital_authority",
            "capital_authority",
            "CAPITAL_AUTHORITY",
            "authority",
            "capital_csm",
            "_capital_csm",
            "csm",
        ):
            authority = getattr(module, attr_name, None)
            if authority is not None and id(authority) not in seen:
                seen.add(id(authority))
                found.append((authority, f"{module_name}.{attr_name}"))
    return found


def _capital_snapshot() -> dict[str, Any]:
    snapshots = [_authority_snapshot(authority, source) for authority, source in _candidate_authorities()]
    if callable(_ORIGINAL_CAPITAL_SNAPSHOT):
        try:
            original = dict(_ORIGINAL_CAPITAL_SNAPSHOT())
            original.setdefault("source", "v16_original")
            original.setdefault("timestamp", 0.0)
            snapshots.append(original)
        except Exception:
            pass
    if not snapshots:
        return {"hydrated": False, "stale": True, "real": 0.0, "registered": 0, "source": "none"}

    best = max(
        snapshots,
        key=lambda item: (
            bool(item.get("hydrated")) and not bool(item.get("stale")),
            bool(item.get("hydrated")),
            _int(item.get("registered")),
            _float(item.get("real")),
            _float(item.get("timestamp")),
        ),
    )
    best = dict(best)
    best["candidate_count"] = len(snapshots)

    # v34 publishes NIJA_CAPITAL_READINESS_HANDOFF_V34 after CapitalCSMv2 has
    # accepted a fresh positive snapshot. Accept the legacy *_READY spelling as
    # well for compatibility with any already-running deployment.
    handoff_ready = (
        _truthy_env("NIJA_CAPITAL_READINESS_HANDOFF_V34")
        or _truthy_env("NIJA_CAPITAL_READINESS_HANDOFF_V34_READY")
        or (_truthy_env("CAPITAL_SYSTEM_READY") and _truthy_env("NIJA_CAPITAL_READY"))
        _truthy("NIJA_CAPITAL_READINESS_HANDOFF_V34")
        or _truthy("NIJA_CAPITAL_READINESS_HANDOFF_V34_READY")
        or (_truthy("CAPITAL_SYSTEM_READY") and _truthy("NIJA_CAPITAL_READY"))
    )
    if handoff_ready and best.get("hydrated") and _float(best.get("real")) > 0.0 and _int(best.get("registered")) > 0:
        best["stale"] = False
        best["handoff_corroborated"] = True
    return best


def _strategy_published() -> bool:
    if callable(_ORIGINAL_STRATEGY_PUBLISHED):
        try:
            if bool(_ORIGINAL_STRATEGY_PUBLISHED()):
                return True
        except Exception:
            pass
    for module_name, module in tuple(sys.modules.items()):
        if not isinstance(module, ModuleType):
            continue
        if module_name.startswith(("pytest", "unittest", "importlib")):
            continue
        for attr in (
            "TRADING_STRATEGY",
            "strategy",
            "trading_strategy",
            "_published_strategy",
            "_canonical_strategy",
        ):
            value = getattr(module, attr, None)
            if value is None:
                continue
            if type(value).__name__ == "TradingStrategy" and (
                callable(getattr(value, "run_cycle", None))
                or callable(getattr(value, "run", None))
            ):
                return True
    return False


def install() -> bool:
    global _INSTALLED, _ORIGINAL_CAPITAL_SNAPSHOT, _ORIGINAL_STRATEGY_PUBLISHED
    if _INSTALLED:
        return True
    patch = importlib.import_module("preactivation_readiness_convergence_v16_patch")
    _ORIGINAL_CAPITAL_SNAPSHOT = getattr(patch, "_capital_snapshot", None)
    _ORIGINAL_STRATEGY_PUBLISHED = getattr(patch, "_strategy_published", None)
    patch._capital_snapshot = _capital_snapshot
    patch._strategy_published = _strategy_published
    _INSTALLED = True
    os.environ["NIJA_PREACTIVATION_RUNTIME_IDENTITY_V36_INSTALLED"] = "1"
    logger.critical(
        "PREACTIVATION_RUNTIME_IDENTITY_V36_INSTALLED marker=%s capital_probe=canonical_multi_alias strategy_probe=process_wide fail_closed=true",
        _MARKER,
    )
    return True


def install_import_hook() -> bool:
    return install()


__all__ = ["install", "install_import_hook", "_capital_snapshot", "_strategy_published"]
