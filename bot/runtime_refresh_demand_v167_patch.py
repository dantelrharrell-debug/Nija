"""Runtime refresh-demand convergence v167.

Attests the pre-bootstrap v32 refresh-demand repair and keeps it installed after
late imports. Routine capital freshness belongs to v137 once that scheduler is
available; genuine reconnect/recovery triggers retain authoritative refreshes.

If the legacy periodic runtime-convergence path ever has to fall back because
v137 is unavailable, classify that refresh as proactive for v166 timing so it
uses the same bounded 30s fetch / 50s total runtime budget instead of reopening
the older 80s coordinator path. v168 is installed immediately afterward so
retired physical v142 generations cannot starve the canonical recovery lane.
v169 is then reasserted so authority-liveness heartbeats cannot masquerade as
ORDER/FILL proof and fresh broker-owned observations are seeded immediately
before canonical publication augmentation. v170 then makes accepted capital
publication/readiness monotonic, v171 reasserts the bounded concurrent
market-data path used by Phase 3, v172 aligns the finite post-core activation
wait with the longer capital convergence budget without changing any gate, v173
keeps Kraken's post-Balance valuation tail from self-amplifying stale balance
flights, v174 admits an already-fresh, sequence-fenced Kraken observation without
re-waiting the full proactive budget, and v175 restores process-local writer
lineage only from exact current Redis ownership while making the v161 position
monitor prefer the populated canonical broker manager over empty compatibility
aliases.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
from functools import wraps
from typing import Any

LOGGER = logging.getLogger("nija.runtime_refresh_demand_v167")
MARKER = "20260819-runtime-refresh-demand-v167"
_READY_FLAG = "NIJA_RUNTIME_REFRESH_DEMAND_V167_READY"
_PATCH_ATTR = "_nija_runtime_refresh_demand_v167"
_LOCK = threading.RLock()


def _v32() -> Any:
    return importlib.import_module("bot.runtime_execution_convergence_v32")


def _v166() -> Any:
    return importlib.import_module("bot.runtime_capital_refresh_ownership_v166_patch")


def _verify_v32() -> bool:
    module = _v32()
    reconcile = getattr(module, "_request_runtime_reconciliation", None)
    monitor = getattr(module, "_monitor", None)
    owner = getattr(module, "_routine_refresh_owned_by_v137", None)
    startup = getattr(module, "_startup_runtime_refresh_ready", None)
    return bool(
        callable(reconcile)
        and bool(getattr(reconcile, "_nija_runtime_refresh_demand_v167", False))
        and callable(monitor)
        and callable(owner)
        and callable(startup)
    )


def _patch_v166_periodic_fallback() -> bool:
    """Keep any periodic fallback inside the proactive v166 runtime budget."""
    try:
        v166 = _v166()
    except Exception:
        return False
    current = getattr(v166, "_is_proactive_trigger", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True
    original = current

    @wraps(original)
    def proactive_v167(value: Any = None) -> bool:
        if value is None:
            try:
                trigger = str(getattr(v166, "_trigger")() or "").strip().lower()
            except Exception:
                trigger = ""
        else:
            trigger = str(value or "").strip().lower()
        if trigger == "periodic_runtime_convergence" or trigger.startswith(
            "periodic_runtime_convergence:"
        ):
            return True
        return bool(original(value))

    setattr(proactive_v167, _PATCH_ATTR, True)
    setattr(proactive_v167, "__wrapped__", original)
    v166._is_proactive_trigger = proactive_v167
    return True


def _patch_release_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_refresh_demand_v167"] = _READY_FLAG
        return True
    except Exception:
        return False


def _install_named(module_name: str, label: str) -> bool:
    try:
        module = importlib.import_module(module_name)
        installer = getattr(module, "install", None) or getattr(module, "install_import_hook", None)
        if not callable(installer):
            return False
        return bool(installer())
    except Exception as exc:
        LOGGER.error(
            "%s_INSTALL_ERROR marker=%s module=%s error=%s:%s trading_fail_closed=true",
            label,
            MARKER,
            module_name,
            type(exc).__name__,
            exc,
        )
        return False


def _install_v168_generation_liveness() -> bool:
    return _install_named(
        "bot.runtime_capital_generation_liveness_v168_patch",
        "RUNTIME_CAPITAL_GENERATION_LIVENESS_V168",
    )


def _install_v169_execution_capital_integrity() -> bool:
    return _install_named(
        "bot.runtime_execution_capital_integrity_v169_patch",
        "RUNTIME_EXECUTION_CAPITAL_INTEGRITY_V169",
    )


def _install_v170_capital_monotonicity() -> bool:
    return _install_named(
        "bot.runtime_capital_publication_monotonicity_v170_patch",
        "RUNTIME_CAPITAL_PUBLICATION_MONOTONICITY_V170",
    )


def _install_v171_market_data_concurrency() -> bool:
    return _install_named(
        "bot.runtime_market_data_concurrency_v171_patch",
        "RUNTIME_MARKET_DATA_CONCURRENCY_V171",
    )


def _install_v172_post_core_activation_budget() -> bool:
    return _install_named(
        "bot.runtime_post_core_activation_budget_v172_patch",
        "RUNTIME_POST_CORE_ACTIVATION_BUDGET_V172",
    )


def _install_v173_kraken_capital_tail_liveness() -> bool:
    return _install_named(
        "bot.runtime_kraken_capital_tail_liveness_v173_patch",
        "RUNTIME_KRAKEN_CAPITAL_TAIL_LIVENESS_V173",
    )


def _install_v174_kraken_capital_observation_admission() -> bool:
    return _install_named(
        "bot.runtime_kraken_capital_observation_admission_v174_patch",
        "RUNTIME_KRAKEN_CAPITAL_OBSERVATION_ADMISSION_V174",
    )


def _install_v175_authority_position_convergence() -> bool:
    return _install_named(
        "bot.runtime_authority_position_convergence_v175_patch",
        "RUNTIME_AUTHORITY_POSITION_CONVERGENCE_V175",
    )


def install() -> bool:
    with _LOCK:
        try:
            module = _v32()
            installer = getattr(module, "install", None)
            if callable(installer):
                installer()
        except Exception as exc:
            LOGGER.error(
                "RUNTIME_REFRESH_DEMAND_V167_V32_INSTALL_ERROR marker=%s error=%s:%s",
                MARKER,
                type(exc).__name__,
                exc,
            )
        verified = _verify_v32()
        periodic_ok = _patch_v166_periodic_fallback()
        manifest_ok = _patch_release_manifest()
        v168_ok = _install_v168_generation_liveness()
        v169_ok = _install_v169_execution_capital_integrity()
        v170_ok = _install_v170_capital_monotonicity()
        v171_ok = _install_v171_market_data_concurrency()
        v172_ok = _install_v172_post_core_activation_budget()
        v173_ok = _install_v173_kraken_capital_tail_liveness()
        v174_ok = _install_v174_kraken_capital_observation_admission()
        v175_ok = _install_v175_authority_position_convergence()
        ready = bool(
            verified
            and periodic_ok
            and manifest_ok
            and v168_ok
            and v169_ok
            and v170_ok
            and v171_ok
            and v172_ok
            and v173_ok
            and v174_ok
            and v175_ok
        )
        os.environ[_READY_FLAG] = "1" if ready else "0"
        if not ready:
            LOGGER.critical(
                "RUNTIME_REFRESH_DEMAND_V167_FAILED marker=%s v32_verified=%s periodic_fallback_ok=%s "
                "manifest_ok=%s v168_ok=%s v169_ok=%s v170_ok=%s v171_ok=%s v172_ok=%s "
                "v173_ok=%s v174_ok=%s v175_ok=%s trading_fail_closed=true",
                MARKER,
                str(verified).lower(),
                str(periodic_ok).lower(),
                str(manifest_ok).lower(),
                str(v168_ok).lower(),
                str(v169_ok).lower(),
                str(v170_ok).lower(),
                str(v171_ok).lower(),
                str(v172_ok).lower(),
                str(v173_ok).lower(),
                str(v174_ok).lower(),
                str(v175_ok).lower(),
            )
            return False
        LOGGER.critical(
            "RUNTIME_REFRESH_DEMAND_V167 marker=%s ready=true startup_double_refresh_removed=true "
            "monitor_initial_delay=true routine_refresh_owner=v137 periodic_fallback_bounded=true "
            "recovery_refresh_preserved=true v168_generation_liveness=true "
            "v169_execution_capital_integrity=true v170_capital_monotonicity=true "
            "v171_market_data_concurrency=true v172_post_core_activation_budget=true "
            "v173_kraken_capital_tail_liveness=true v174_kraken_observation_admission=true "
            "v175_authority_position_convergence=true publication_expiry_extended=false "
            "stale_promoted=false safety_gates_bypassed=false",
            MARKER,
        )
        return True


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "install",
    "install_import_hook",
    "_verify_v32",
    "_patch_v166_periodic_fallback",
    "_install_v168_generation_liveness",
    "_install_v169_execution_capital_integrity",
    "_install_v170_capital_monotonicity",
    "_install_v171_market_data_concurrency",
    "_install_v172_post_core_activation_budget",
    "_install_v173_kraken_capital_tail_liveness",
    "_install_v174_kraken_capital_observation_admission",
    "_install_v175_authority_position_convergence",
]
