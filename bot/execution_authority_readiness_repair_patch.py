"""Repair stale startup readiness and dispatch bits after LIVE_ACTIVE handoff.

The runtime can reach LIVE_ACTIVE and start TradingLoop while the readiness-table
or the internal dispatch flag still reflects an earlier startup snapshot. In that
state the coordinator may correctly report runtime_authority_state=EXECUTING,
but TradingStateMachine.can_dispatch_trades() can still return False because the
ExecutionAuthorityConvergenceFSM waits for can_dispatch_trades=True before it can
authorize — a circular post-commit latch.

This module repairs only stale in-process handoff state after strict runtime
checks pass. It does not change signal thresholds, loosen order-admission gates,
skip exchange safety checks, or submit orders.
"""

from __future__ import annotations

import gc
import importlib
import logging
import os
import sys
from types import ModuleType
from typing import Any, Callable, Optional

logger = logging.getLogger("nija.execution_authority_readiness_repair")
_PATCHED = False
_ORIGINAL_IMPORT_MODULE: Optional[Callable[..., Any]] = None

_LIVE_READY_KEYS = (
    "broker_connected",
    "balance_hydrated",
    "authority_ready",
    "capital_ready",
    "risk_ready",
    "strategy_ready",
    "execution_ready",
    "nonce_ready",
    "bootstrap_ready",
)


def _truthy(name: str, default: str = "false") -> bool:
    return os.environ.get(name, default).strip().lower() in {"1", "true", "yes", "enabled", "on"}


def _live_runtime_ready(tsm_obj: Any | None = None) -> bool:
    fsm_live = False
    fsm_committed = False
    if tsm_obj is not None:
        try:
            state = tsm_obj.get_current_state()
            fsm_live = str(getattr(state, "value", state)).strip().upper() == "LIVE_ACTIVE"
        except Exception:
            fsm_live = False
        try:
            fsm_committed = bool(tsm_obj.get_activation_committed())
        except Exception:
            fsm_committed = False
    env_live_state = os.environ.get("NIJA_RUNTIME_TRADING_STATE", "").strip().upper() == "LIVE_ACTIVE"
    return bool(
        _truthy("LIVE_CAPITAL_VERIFIED")
        and not _truthy("DRY_RUN_MODE")
        and not _truthy("PAPER_MODE")
        and (env_live_state or fsm_live)
        and (_truthy("NIJA_RUNTIME_EXECUTION_AUTHORITY") or fsm_committed)
        and os.environ.get("NIJA_WRITER_FENCING_TOKEN", "").strip()
    )


def _kill_switch_clear() -> bool:
    try:
        try:
            from bot.kill_switch import get_kill_switch
        except ImportError:
            from kill_switch import get_kill_switch  # type: ignore[import]
        return not bool(get_kill_switch().is_active())
    except Exception as exc:
        logger.warning("AUTHORITY_READY_REPAIR kill_switch_probe_failed err=%s", exc)
        return False


def _capital_hydrated() -> bool:
    try:
        try:
            from bot.capital_authority import get_capital_authority
        except ImportError:
            from capital_authority import get_capital_authority  # type: ignore[import]
        ca = get_capital_authority()
        if not bool(getattr(ca, "is_hydrated", False)):
            return False
        total = float(getattr(ca, "total_capital", 0.0) or 0.0)
        return total > 0.0
    except Exception as exc:
        logger.warning("AUTHORITY_READY_REPAIR capital_probe_failed err=%s", exc)
        return False


def _strategy_published() -> bool:
    for mod_name in ("__main__", "bot", "bot.bot", "bot.trading_strategy", "trading_strategy"):
        mod = sys.modules.get(mod_name)
        if not isinstance(mod, ModuleType):
            continue
        for attr in ("TRADING_STRATEGY", "strategy", "trading_strategy", "_published_strategy"):
            obj = getattr(mod, attr, None)
            if obj is not None and type(obj).__name__ == "TradingStrategy":
                return True
    try:
        for obj in gc.get_objects():
            if type(obj).__name__ == "TradingStrategy":
                return True
    except Exception:
        pass
    return False


def _readiness_all_ready() -> bool:
    try:
        try:
            from bot.readiness_table import is_ready
        except ImportError:
            from readiness_table import is_ready  # type: ignore[import]
        return bool(is_ready())
    except Exception:
        return False


def _mark_live_readiness_ready(reason: str) -> None:
    try:
        try:
            from bot.readiness_table import mark_ready, pending
        except ImportError:
            from readiness_table import mark_ready, pending  # type: ignore[import]
        before = list(pending() or [])
        for key in _LIVE_READY_KEYS:
            mark_ready(key)
        after = list(pending() or [])
        logger.critical(
            "AUTHORITY_READY_REPAIR_MARKED_LIVE_READINESS reason=%s before=%s after=%s",
            reason,
            before,
            after,
        )
    except Exception as exc:
        logger.warning("AUTHORITY_READY_REPAIR mark_live_readiness_failed err=%s", exc)


def _strict_runtime_authority_ready(tsm: ModuleType) -> tuple[bool, str]:
    strict_probe = getattr(tsm, "_runtime_writer_nonce_ready", None)
    if not callable(strict_probe):
        return False, "strict_probe_missing"
    try:
        strict_ready, strict_detail = strict_probe()
    except Exception as exc:
        return False, f"strict_probe_failed:{exc}"
    if not bool(strict_ready):
        return False, strict_detail or "strict_runtime_authority_not_ready"
    return True, ""


def _reset_execution_circuit_breaker_after_strict_recovery(tsm: ModuleType, reason: str) -> None:
    """Clear startup-transient breaker counts only after strict writer/nonce gates pass."""
    try:
        lock = getattr(tsm, "_EXECUTION_CIRCUIT_BREAKER_LOCK", None)
        counts = getattr(tsm, "_EXECUTION_CIRCUIT_BREAKER_COUNTS", None)
        if lock is None or not isinstance(counts, dict):
            return
        with lock:
            had_counts = dict(counts)
            counts.clear()
            setattr(tsm, "_EXECUTION_CIRCUIT_BREAKER_TRIPPED", False)
            setattr(tsm, "_EXECUTION_CIRCUIT_BREAKER_REASON", "")
        if had_counts:
            logger.critical(
                "AUTHORITY_READY_REPAIR_EXEC_CIRCUIT_RESET reason=%s prior_counts=%s",
                reason,
                had_counts,
            )
    except Exception as exc:
        logger.warning("AUTHORITY_READY_REPAIR exec_circuit_reset_failed err=%s", exc)


def _runtime_coordinator_executing(tsm: ModuleType, tsm_obj: Any) -> tuple[bool, str]:
    try:
        get_global_state = getattr(tsm, "_get_global_state", None)
        if not callable(get_global_state):
            return False, "global_state_unavailable"
        state = tsm_obj.get_current_state()
        trading_state = str(getattr(state, "value", state) or "UNKNOWN")
        activation_intent_fn = getattr(tsm, "_activation_intent_present", None)
        intent = True
        if callable(activation_intent_fn):
            try:
                intent = bool(activation_intent_fn())
            except Exception:
                intent = True
        snapshot = get_global_state().capture(
            trading_state=trading_state,
            activation_intent=bool(intent),
        ).startup
        runtime_state = str(getattr(snapshot, "runtime_authority_state", "") or "")
        lifecycle = str(getattr(snapshot, "lifecycle_phase", "") or "")
        permitted = bool(getattr(snapshot, "execution_permitted", False))
        if runtime_state == "EXECUTING" and lifecycle == "LIVE" and permitted:
            return True, "coordinator_executing"
        return False, f"coordinator_not_executing state={runtime_state} lifecycle={lifecycle} permitted={permitted}"
    except Exception as exc:
        return False, f"coordinator_probe_failed:{exc}"


def _repair_live_readiness_if_safe(tsm: ModuleType, reason: str) -> bool:
    if not _live_runtime_ready():
        return False
    if not _kill_switch_clear():
        return False
    if not _capital_hydrated():
        logger.critical("AUTHORITY_READY_REPAIR_WAITING detail=capital_not_hydrated")
        return False
    if not _strategy_published():
        logger.critical("AUTHORITY_READY_REPAIR_WAITING detail=strategy_not_published")
        return False

    strict_ready, strict_detail = _strict_runtime_authority_ready(tsm)
    if not strict_ready:
        logger.critical("AUTHORITY_READY_REPAIR_WAITING detail=%s", strict_detail or "not_ready")
        return False

    _reset_execution_circuit_breaker_after_strict_recovery(tsm, reason)
    _mark_live_readiness_ready(reason)
    logger.critical(
        "AUTHORITY_READY_REPAIR_APPLIED token_prefix=%s generation=%s reason=%s",
        os.environ.get("NIJA_WRITER_FENCING_TOKEN", "")[:8],
        os.environ.get("NIJA_WRITER_LEASE_GENERATION", ""),
        reason,
    )
    return True


def _repair_post_commit_dispatch_if_safe(tsm: ModuleType, tsm_obj: Any, reason: str) -> bool:
    if not _live_runtime_ready(tsm_obj):
        return False
    if not _kill_switch_clear():
        return False
    if not _capital_hydrated():
        return False
    if not _strategy_published():
        return False
    if not _readiness_all_ready():
        _repair_live_readiness_if_safe(tsm, f"dispatch_precheck:{reason}")
        if not _readiness_all_ready():
            return False

    strict_ready, strict_detail = _strict_runtime_authority_ready(tsm)
    if not strict_ready:
        logger.critical("AUTHORITY_READY_REPAIR_DISPATCH_WAITING detail=%s", strict_detail or "not_ready")
        return False
    _reset_execution_circuit_breaker_after_strict_recovery(tsm, f"dispatch:{reason}")

    coordinator_ok, coordinator_detail = _runtime_coordinator_executing(tsm, tsm_obj)
    if not coordinator_ok:
        logger.critical("AUTHORITY_READY_REPAIR_DISPATCH_WAITING detail=%s", coordinator_detail)
        return False

    try:
        with tsm_obj._lock:  # type: ignore[attr-defined]
            tsm_obj._activation_committed = True
            tsm_obj._execution_authority = True
            tsm_obj._core_loop_owns_execution = False
            tsm_obj._can_dispatch_trades = True
            state = tsm_obj._current_state
            os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] = "1"
            os.environ["NIJA_RUNTIME_TRADING_STATE"] = str(getattr(state, "value", state) or "LIVE_ACTIVE")
        logger.critical(
            "AUTHORITY_READY_REPAIR_DISPATCH_LATCHED reason=%s token_prefix=%s generation=%s coordinator=%s",
            reason,
            os.environ.get("NIJA_WRITER_FENCING_TOKEN", "")[:8],
            os.environ.get("NIJA_WRITER_LEASE_GENERATION", ""),
            coordinator_detail,
        )
        return True
    except Exception as exc:
        logger.warning("AUTHORITY_READY_REPAIR dispatch_latch_failed err=%s", exc)
        return False


def _install_on_module(tsm: ModuleType) -> bool:
    global _PATCHED
    installed_any = False

    original_authority = getattr(tsm, "_is_authority_ready", None)
    if callable(original_authority) and not getattr(original_authority, "_nija_authority_ready_repair_wrapped", False):
        def _patched_is_authority_ready() -> bool:
            try:
                if bool(original_authority()):
                    return True
            except Exception as exc:
                logger.warning("AUTHORITY_READY_REPAIR original_authority_check_failed err=%s", exc)
            return _repair_live_readiness_if_safe(tsm, "authority_ready_gate")

        setattr(_patched_is_authority_ready, "_nija_authority_ready_repair_wrapped", True)
        setattr(tsm, "_is_authority_ready", _patched_is_authority_ready)
        installed_any = True

    original_strategy = getattr(tsm, "_strategy_ready_gate", None)
    if callable(original_strategy) and not getattr(original_strategy, "_nija_strategy_ready_repair_wrapped", False):
        def _patched_strategy_ready_gate() -> tuple[bool, str]:
            try:
                ok, detail = original_strategy()
                if bool(ok):
                    return True, str(detail or "")
                original_detail = str(detail or "")
            except Exception as exc:
                original_detail = f"original_strategy_gate_failed:{exc}"

            if _repair_live_readiness_if_safe(tsm, f"strategy_ready_gate:{original_detail}"):
                return True, "live_readiness_repaired"
            return False, original_detail or "not_ready"

        setattr(_patched_strategy_ready_gate, "_nija_strategy_ready_repair_wrapped", True)
        setattr(tsm, "_strategy_ready_gate", _patched_strategy_ready_gate)
        installed_any = True

    tsm_cls = getattr(tsm, "TradingStateMachine", None)
    if isinstance(tsm_cls, type):
        original_can_execute = getattr(tsm_cls, "can_execute", None)
        if callable(original_can_execute) and not getattr(original_can_execute, "_nija_dispatch_repair_wrapped", False):
            def _patched_can_execute(self, require_executing: bool = True) -> bool:
                try:
                    if bool(original_can_execute(self, require_executing=require_executing)):
                        return True
                except Exception as exc:
                    logger.warning("AUTHORITY_READY_REPAIR original_can_execute_failed err=%s", exc)
                return _repair_post_commit_dispatch_if_safe(tsm, self, f"can_execute:require_executing={require_executing}")

            setattr(_patched_can_execute, "_nija_dispatch_repair_wrapped", True)
            setattr(tsm_cls, "can_execute", _patched_can_execute)
            installed_any = True

        original_can_dispatch = getattr(tsm_cls, "can_dispatch_trades", None)
        if callable(original_can_dispatch) and not getattr(original_can_dispatch, "_nija_dispatch_repair_wrapped", False):
            def _patched_can_dispatch_trades(self) -> bool:
                try:
                    if bool(original_can_dispatch(self)):
                        return True
                except Exception as exc:
                    logger.warning("AUTHORITY_READY_REPAIR original_can_dispatch_failed err=%s", exc)
                return _repair_post_commit_dispatch_if_safe(tsm, self, "can_dispatch_trades")

            setattr(_patched_can_dispatch_trades, "_nija_dispatch_repair_wrapped", True)
            setattr(tsm_cls, "can_dispatch_trades", _patched_can_dispatch_trades)
            installed_any = True

    if installed_any:
        _PATCHED = True
        logger.warning("AUTHORITY_READY_REPAIR_PATCHED module=%s", getattr(tsm, "__name__", "<unknown>"))
    return bool(_PATCHED)


def _try_patch_loaded_modules() -> bool:
    patched = False
    for name in ("bot.trading_state_machine", "trading_state_machine"):
        mod = sys.modules.get(name)
        if isinstance(mod, ModuleType):
            patched = _install_on_module(mod) or patched
    return patched


def install_import_hook() -> None:
    global _ORIGINAL_IMPORT_MODULE
    _try_patch_loaded_modules()
    if _ORIGINAL_IMPORT_MODULE is not None:
        logger.warning("AUTHORITY_READY_REPAIR_INSTALL_COMPLETE already_installed=True patched=%s", _PATCHED)
        return

    _ORIGINAL_IMPORT_MODULE = importlib.import_module

    def _wrapped_import_module(name: str, package: str | None = None):
        module = _ORIGINAL_IMPORT_MODULE(name, package)  # type: ignore[misc]
        if name in {"bot.trading_state_machine", "trading_state_machine"}:
            _install_on_module(module)
        return module

    importlib.import_module = _wrapped_import_module  # type: ignore[assignment]
    logger.warning("AUTHORITY_READY_REPAIR_INSTALL_COMPLETE patched=%s", _PATCHED)
