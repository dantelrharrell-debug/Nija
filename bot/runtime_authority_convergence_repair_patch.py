from __future__ import annotations

import builtins
import logging
import os
import sys
import threading
import time
from types import ModuleType
from typing import Any

logger = logging.getLogger("nija.runtime_authority_convergence_repair")
_MARKER = "20260709u"
_HOOK_FLAG = "_NIJA_RUNTIME_AUTHORITY_CONVERGENCE_REPAIR_HOOK_V20260709U"
_MONITOR_STARTED = False
_MONITOR_LOCK = threading.Lock()
_CONVERGENCE_LOCAL = threading.local()
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}

try:
    from bot.heartbeat_state import get_heartbeat_state as _get_heartbeat_state
except ImportError:
    from heartbeat_state import get_heartbeat_state as _get_heartbeat_state  # type: ignore[import]
_UNSAFE_REASON_TOKENS = (
    "manual",
    "operator",
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


def _truthy(name: str, default: str = "false") -> bool:
    return str(os.environ.get(name, default)).strip().lower() in _TRUE


def _handoff_ready_env() -> bool:
    return bool(
        _truthy("NIJA_CAPITAL_READINESS_HANDOFF_V34")
        or _truthy("NIJA_CAPITAL_READINESS_HANDOFF_V34_READY")
        or (_truthy("CAPITAL_SYSTEM_READY") and _truthy("NIJA_CAPITAL_READY"))
    )


def _f(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        amount = float(value)
        if amount != amount:
            return default
        return amount
    except Exception:
        return default


_BALANCE_TOTAL_KEYS = (
    "total_funds",
    "total_balance",
    "total_equity",
    "equity",
    "account_equity",
    "portfolio_value",
    "trading_balance",
    "balance",
    "usd_value",
)


def _balance_total(value: Any) -> float:
    if isinstance(value, dict):
        for key in _BALANCE_TOTAL_KEYS:
            amount = _f(value.get(key))
            if amount > 0.0:
                return amount
        return 0.0
    return max(0.0, _f(value))


def _cached_broker_balance(
    broker_obj: Any,
    broker_key: str,
    capital_authority: Any = None,
) -> tuple[float, str]:
    """Read an already-published balance without invoking broker I/O."""

    for attr in (
        "_last_known_balance",
        "_last_confirmed_balance",
        "last_known_balance",
        "cached_balance",
    ):
        amount = _balance_total(getattr(broker_obj, attr, None))
        if amount > 0.0:
            return amount, attr

    balances = getattr(capital_authority, "_broker_balances", {}) or {}
    if isinstance(balances, dict):
        wanted = broker_key.strip().lower()
        for key, value in balances.items():
            normalized = str(getattr(key, "value", key)).strip().lower()
            if normalized == wanted:
                amount = _balance_total(value)
                if amount > 0.0:
                    return amount, "capital_authority"

    return 0.0, "unavailable"


def _i(value: Any, default: int = 0) -> int:
    try:
        return int(float(value or 0))
    except Exception:
        return default


def _state_text(state: Any) -> str:
    return str(getattr(state, "value", state) or "unknown")


def _emergency_reason_text() -> str:
    chunks: list[str] = []
    for env_name in (
        "NIJA_EMERGENCY_STOP_REASON",
        "NIJA_KILL_SWITCH_REASON",
        "NIJA_PRE_HALT_REASON",
        "NIJA_RUNTIME_STOP_REASON",
        "NIJA_OPERATOR_EMERGENCY_STOP_REASON",
    ):
        value = os.environ.get(env_name, "")
        if value:
            chunks.append(f"{env_name}={value}")
    for path in ("EMERGENCY_STOP", ".nija_kill_switch_state.json", "data/EMERGENCY_STOP"):
        try:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8", errors="ignore") as handle:
                    chunks.append(f"{path}={handle.read(2048)}")
        except Exception:
            pass
    return "\n".join(chunks)


def _unsafe_emergency_reason_present() -> tuple[bool, str]:
    text = _emergency_reason_text().lower()
    if not text.strip():
        return False, ""
    for token in _UNSAFE_REASON_TOKENS:
        if token in text:
            return True, token
    return False, ""


def _kill_switch_clear() -> tuple[bool, str]:
    unsafe, token = _unsafe_emergency_reason_present()
    if unsafe:
        return False, f"unsafe_emergency_reason:{token}"
    try:
        try:
            from bot.kill_switch import get_kill_switch
        except ImportError:
            from kill_switch import get_kill_switch  # type: ignore[import]
        kill_switch = get_kill_switch()
        if bool(kill_switch.is_active()):
            return False, "kill_switch_active"
    except Exception as exc:
        return False, f"kill_switch_probe_failed:{exc}"
    return True, "kill_switch_clear"


def _broker_manager_capital_payload() -> dict[str, Any]:
    """Observe connected brokers using accepted in-memory balances only.

    This recovery monitor must never own exchange refreshes.  The broker manager
    and BalanceService are the only components allowed to call private balance
    endpoints and publish CapitalAuthority feeds.  Returning no balance here is
    intentionally fail-closed until one of those owners publishes a snapshot.
    """

    result: dict[str, Any] = {
        "connected_count": 0,
        "total_balance": 0.0,
        "per_broker": {},
        "sources": {},
        "source": "cached_only",
    }
    mabm_mod = sys.modules.get("bot.multi_account_broker_manager") or sys.modules.get(
        "multi_account_broker_manager"
    )
    if mabm_mod is None:
        return result

    try:
        getter = getattr(mabm_mod, "get_broker_manager", None)
        if not callable(getter):
            return result
        mgr = getter()
        if mgr is None:
            return result

        ca = None
        ca_mod = sys.modules.get("bot.capital_authority") or sys.modules.get(
            "capital_authority"
        )
        if ca_mod is not None:
            ca_getter = getattr(ca_mod, "get_capital_authority", None)
            if callable(ca_getter):
                try:
                    ca = ca_getter()
                except Exception:
                    ca = None

        total_balance = 0.0
        per_broker: dict[str, float] = {}
        sources: dict[str, str] = {}
        platform_brokers = getattr(mgr, "_platform_brokers", {})
        for broker_type, broker_obj in list(platform_brokers.items()):
            if broker_obj is None:
                continue
            try:
                connected = bool(getattr(broker_obj, "connected", False))
                if not connected:
                    is_connected = getattr(mgr, "is_platform_connected", None)
                    if callable(is_connected):
                        connected = bool(is_connected(broker_type))
                if not connected:
                    continue

                broker_key = str(getattr(broker_type, "value", broker_type))
                balance, source = _cached_broker_balance(broker_obj, broker_key, ca)
                if balance <= 0.0:
                    logger.debug(
                        "RUNTIME_AUTHORITY_CONVERGENCE cached_balance_unavailable broker=%s",
                        broker_key,
                    )
                    continue

                per_broker[broker_key] = balance
                sources[broker_key] = source
                total_balance += balance
            except Exception as exc:
                logger.debug(
                    "RUNTIME_AUTHORITY_CONVERGENCE broker_payload_error broker=%s err=%s",
                    broker_type,
                    exc,
                )

        return {
            "connected_count": len(per_broker),
            "total_balance": total_balance,
            "per_broker": per_broker,
            "sources": sources,
            "source": "cached_only",
        }
    except Exception as exc:
        logger.debug(
            "RUNTIME_AUTHORITY_CONVERGENCE broker_manager_payload_error err=%s",
            exc,
        )
        return result


def _capital_authority_ready() -> tuple[bool, str, dict[str, Any]]:
    handoff_ready = _handoff_ready_env()
    if not (_truthy("LIVE_CAPITAL_VERIFIED") or handoff_ready):
        return False, "live_capital_not_verified", {}
    if _truthy("DRY_RUN_MODE") or _truthy("PAPER_MODE"):
        return False, "simulation_mode", {}
    _broker_manager_capital_payload()
    try:
        try:
            from bot.capital_authority import get_capital_authority
        except ImportError:
            from capital_authority import get_capital_authority  # type: ignore[import]
        ca = get_capital_authority()
    except Exception as exc:
        return False, f"capital_authority_unavailable:{exc}", {}

    hydrated = bool(getattr(ca, "is_hydrated", False))
    real = 0.0
    usable = 0.0
    for attr in ("total_capital", "real_capital", "available_capital"):
        real = max(real, _f(getattr(ca, attr, 0.0)))
    for method_name in ("get_real_capital", "get_total_capital"):
        method = getattr(ca, method_name, None)
        if callable(method):
            try:
                real = max(real, _f(method()))
            except Exception:
                pass
    for attr in ("usable_capital", "risk_capital", "available_capital"):
        usable = max(usable, _f(getattr(ca, attr, 0.0)))
    method = getattr(ca, "get_usable_capital", None)
    if callable(method):
        try:
            usable = max(usable, _f(method()))
        except Exception:
            pass
    if usable <= 0.0 and real > 0.0 and handoff_ready:
        usable = real
    valid_brokers = max(
        _i(getattr(ca, "valid_broker_count", 0)),
        _i(getattr(ca, "registered_broker_count", 0)),
        _i(getattr(ca, "valid_brokers", 0)),
        _i(getattr(ca, "broker_count", 0)),
        _i(getattr(ca, "_valid_broker_count", 0)),
    )
    try:
        values = getattr(ca, "broker_values", None) or getattr(ca, "values", None) or {}
        if isinstance(values, dict):
            valid_brokers = max(valid_brokers, sum(1 for value in values.values() if _f(value) > 0.0))
    except Exception:
        pass
    ttl_s = max(
        30.0,
        _f(
            os.environ.get("NIJA_RUNTIME_AUTHORITY_CONVERGENCE_CAPITAL_TTL_S"),
            240.0,
        ),
    )
    fresh = False
    fresh_reader = getattr(ca, "is_fresh", None)
    stale_reader = getattr(ca, "is_stale", None)
    try:
        if callable(fresh_reader):
            try:
                fresh = bool(fresh_reader(ttl_s=ttl_s))
            except TypeError:
                fresh = bool(fresh_reader())
        elif fresh_reader is not None:
            fresh = bool(fresh_reader)
        elif callable(stale_reader):
            try:
                fresh = not bool(stale_reader(ttl_s=ttl_s))
            except TypeError:
                fresh = not bool(stale_reader())
        elif stale_reader is not None:
            fresh = not bool(stale_reader)
    except Exception:
        fresh = False
    min_capital = max(1.0, _f(os.environ.get("NIJA_RUNTIME_AUTHORITY_CONVERGENCE_MIN_CAPITAL_USD"), 10.0))
    min_brokers = max(1, _i(os.environ.get("NIJA_RUNTIME_AUTHORITY_CONVERGENCE_MIN_BROKERS"), 2))
    if handoff_ready and hydrated and real >= min_capital and valid_brokers >= min_brokers:
        fresh = True
    detail = {
        "hydrated": hydrated,
        "real": real,
        "usable": usable,
        "valid_brokers": valid_brokers,
        "fresh": fresh,
        "handoff_ready": handoff_ready,
    }
    ready = bool(hydrated and real >= min_capital and usable > 0.0 and valid_brokers >= min_brokers and fresh)
    if ready:
        return True, f"capital_ready real={real:.2f} usable={usable:.2f} valid_brokers={valid_brokers} handoff={handoff_ready}", detail
    return False, f"capital_not_ready hydrated={hydrated} real={real:.2f} usable={usable:.2f} valid_brokers={valid_brokers} fresh={fresh} handoff={handoff_ready}", detail


def _heartbeat_ready() -> tuple[bool, str]:
    token = os.environ.get("NIJA_WRITER_FENCING_TOKEN", "").strip()
    generation = (
        os.environ.get("NIJA_WRITER_LEASE_GENERATION", "").strip()
        or os.environ.get("NIJA_WRITER_GENERATION", "").strip()
    )
    active = os.environ.get("NIJA_WRITER_HEARTBEAT_ACTIVE", "").strip()
    if not _truthy("NIJA_WRITER_LEASE_ACQUIRED"):
        return False, "writer_lease_not_acquired"
    if not token:
        try:
            try:
                from bot.execution_authority_context import (
                    get_distributed_writer_authority_status,
                )
            except ImportError:
                from execution_authority_context import (  # type: ignore[import]
                    get_distributed_writer_authority_status,
                )
            status = get_distributed_writer_authority_status(force_refresh=True) or {}
            recovered_token = str(status.get("token_prefix", "") or "").strip()
            if recovered_token:
                token = os.environ.get("NIJA_WRITER_FENCING_TOKEN", "").strip()
        except Exception:
            pass
    if not token or not generation:
        return False, f"writer_token_or_generation_missing token={bool(token)} generation={generation or 'missing'}"
    if not _truthy("NIJA_WRITER_HEARTBEAT_ACTIVE"):
        return False, f"heartbeat_inactive active={active or 'missing'}"
    if not _truthy("NIJA_CORE_THREAD_ALIVE"):
        return False, "core_thread_not_alive"
    kraken_nonce_required = _truthy("KRAKEN_NONCE_LEASE_REQUIRED")
    if kraken_nonce_required:
        try:
            try:
                from bot.execution_authority_context import _runtime_nonce_authority_status
            except ImportError:
                from execution_authority_context import _runtime_nonce_authority_status  # type: ignore[import]
            nonce_ok, nonce_detail = _runtime_nonce_authority_status()
            if not nonce_ok:
                return False, f"nonce_manager_not_ready:{nonce_detail or 'blocked'}"
        except Exception as exc:
            return False, f"nonce_manager_status_unavailable:{exc}"
    # Freshness check: always read the canonical HeartbeatState to avoid
    # consuming a cached / stale env-var timestamp.  If the canonical state
    # reports healthy and the last beat is within max_age_s the check passes.
    max_age = max(5.0, _f(os.environ.get("NIJA_RUNTIME_AUTHORITY_CONVERGENCE_HEARTBEAT_MAX_AGE_S"), 90.0))
    try:
        hs = _get_heartbeat_state()
        snap = hs.snapshot()
        if snap.healthy and snap.timestamp > 0.0:
            age = max(0.0, time.time() - snap.timestamp)
            if age > max_age:
                return False, f"heartbeat_stale age_s={age:.1f} max_age_s={max_age:.1f}"
            return True, f"heartbeat_ready age_s={age:.1f} generation={generation}"
        # HeartbeatState not yet populated — fall back to env-var path so the
        # check does not permanently fail in environments where heartbeat_state
        # was never seeded (e.g. tests that only set env vars).
    except Exception:
        pass
    # Env-var fallback
    alive_raw = os.environ.get("NIJA_WRITER_HEARTBEAT_ALIVE_TS", "").strip()
    alive_ts = _f(alive_raw, 0.0)
    if alive_ts <= 0.0:
        return False, "heartbeat_alive_ts_missing"
    age = max(0.0, time.time() - alive_ts)
    if age > max_age:
        return False, f"heartbeat_stale age_s={age:.1f} max_age_s={max_age:.1f}"
    return True, f"heartbeat_ready age_s={age:.1f} generation={generation}"


def _distributed_writer_ready() -> tuple[bool, str]:
    try:
        try:
            from bot.execution_authority_context import assert_distributed_writer_authority
        except ImportError:
            from execution_authority_context import assert_distributed_writer_authority  # type: ignore[import]
        assert_distributed_writer_authority()
        return True, "distributed_writer_ready"
    except Exception as exc:
        return False, f"distributed_writer_not_ready:{exc}"


def _safe_to_recover() -> tuple[bool, str, dict[str, Any]]:
    kill_ok, kill_detail = _kill_switch_clear()
    if not kill_ok:
        return False, kill_detail, {}
    capital_ok, capital_detail, capital_meta = _capital_authority_ready()
    if not capital_ok:
        return False, capital_detail, capital_meta
    hb_ok, hb_detail = _heartbeat_ready()
    if not hb_ok:
        return False, hb_detail, capital_meta
    writer_ok, writer_detail = _distributed_writer_ready()
    if not writer_ok:
        return False, writer_detail, capital_meta
    return True, f"{kill_detail}; {capital_detail}; {hb_detail}; {writer_detail}", capital_meta


def _converge_runtime_authority_once(source: str = "manual") -> bool:
    if not _truthy("NIJA_RUNTIME_AUTHORITY_CONVERGENCE_REPAIR_ENABLED", "true"):
        return False
    env_state = os.environ.get("NIJA_RUNTIME_TRADING_STATE", "").strip().upper()
    env_auth = os.environ.get("NIJA_RUNTIME_EXECUTION_AUTHORITY", "").strip()
    if env_state == "LIVE_ACTIVE" and _truthy("NIJA_RUNTIME_EXECUTION_AUTHORITY"):
        return False
    ready, detail, meta = _safe_to_recover()
    if not ready:
        logger.warning(
            "RUNTIME_AUTHORITY_CONVERGENCE_WAITING marker=%s source=%s env_state=%s env_auth=%s detail=%s",
            _MARKER,
            source,
            env_state or "missing",
            env_auth or "missing",
            detail,
        )
        return False
    try:
        try:
            from bot.trading_state_machine import get_state_machine, TradingState
        except ImportError:
            from trading_state_machine import get_state_machine, TradingState  # type: ignore[import]
        sm = get_state_machine()
        state = sm.get_current_state()
        state_value = _state_text(state)
        if state == TradingState.EMERGENCY_STOP:
            sm.transition_to(TradingState.OFF, f"stale emergency runtime-authority convergence reset marker={_MARKER}")
            state = sm.get_current_state()
            state_value = _state_text(state)
        if state != TradingState.LIVE_ACTIVE:
            cycle_capital = {
                "snapshot_source": "capital_authority",
                "ca_valid_brokers": int(meta.get("valid_brokers") or 0),
                "aggregation_normalized": True,
                "capital_hydrated": bool(meta.get("hydrated")),
                "ca_not_stale": bool(meta.get("fresh")),
                "real_capital": float(meta.get("real") or 0.0),
            }
            committed = False
            commit = getattr(sm, "commit_activation", None)
            if callable(commit):
                try:
                    committed = bool(commit(cycle_capital=cycle_capital))
                except Exception as exc:
                    logger.warning("RUNTIME_AUTHORITY_CONVERGENCE_COMMIT_FAILED marker=%s err=%s", _MARKER, exc)
            if not committed:
                logger.warning(
                    "RUNTIME_AUTHORITY_CONVERGENCE_COMMIT_REJECTED marker=%s "
                    "source=%s state=%s activation_gates_remain_authoritative=true",
                    _MARKER,
                    source,
                    state_value,
                )
                return False
        with getattr(sm, "_lock", threading.Lock()):
            if hasattr(sm, "_activation_committed"):
                sm._activation_committed = True
            if hasattr(sm, "_execution_authority"):
                sm._execution_authority = True
            if hasattr(sm, "_core_loop_owns_execution"):
                sm._core_loop_owns_execution = False
            if hasattr(sm, "_can_dispatch_trades"):
                sm._can_dispatch_trades = True
        os.environ["NIJA_RUNTIME_TRADING_STATE"] = "LIVE_ACTIVE"
        os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] = "1"
        logger.critical(
            "RUNTIME_AUTHORITY_CONVERGENCE_REPAIRED marker=%s source=%s from_state=%s detail=%s",
            _MARKER,
            source,
            state_value,
            detail,
        )
        print(
            f"[NIJA-PRINT] RUNTIME_AUTHORITY_CONVERGENCE_REPAIRED marker={_MARKER} source={source}",
            flush=True,
        )
        return True
    except Exception as exc:
        logger.warning("RUNTIME_AUTHORITY_CONVERGENCE_FAILED marker=%s source=%s err=%s", _MARKER, source, exc)
        return False


def converge_runtime_authority(source: str = "manual") -> bool:
    """Converge authority once per thread without recursive activation calls."""

    if bool(getattr(_CONVERGENCE_LOCAL, "active", False)):
        logger.debug(
            "RUNTIME_AUTHORITY_CONVERGENCE_REENTRY_BLOCKED marker=%s source=%s",
            _MARKER,
            source,
        )
        return False
    _CONVERGENCE_LOCAL.active = True
    try:
        return _converge_runtime_authority_once(source)
    finally:
        _CONVERGENCE_LOCAL.active = False


def _monitor() -> None:
    interval = max(1.0, _f(os.environ.get("NIJA_RUNTIME_AUTHORITY_CONVERGENCE_INTERVAL_S"), 5.0))
    while True:
        try:
            converge_runtime_authority("monitor")
        except Exception as exc:
            logger.warning("RUNTIME_AUTHORITY_CONVERGENCE_MONITOR_ERROR marker=%s err=%s", _MARKER, exc)
        time.sleep(interval)


def _start_monitor() -> None:
    global _MONITOR_STARTED
    if _MONITOR_STARTED:
        return
    with _MONITOR_LOCK:
        if _MONITOR_STARTED:
            return
        _MONITOR_STARTED = True
        thread = threading.Thread(target=_monitor, name="runtime-authority-convergence-repair", daemon=True)
        thread.start()
        logger.warning("RUNTIME_AUTHORITY_CONVERGENCE_MONITOR_STARTED marker=%s thread_alive=%s", _MARKER, thread.is_alive())


def _patch_core_loop_module(module: ModuleType) -> bool:
    if not hasattr(module, "NijaCoreLoop"):
        return False
    converge_runtime_authority("core_loop_import")
    logger.warning("RUNTIME_AUTHORITY_CONVERGENCE_CORE_LOOP_SEEN marker=%s module=%s", _MARKER, getattr(module, "__name__", ""))
    return True


def _try_patch_loaded() -> bool:
    patched = False
    for name, module in list(sys.modules.items()):
        if isinstance(module, ModuleType) and (name.endswith("nija_core_loop") or hasattr(module, "NijaCoreLoop")):
            try:
                patched = _patch_core_loop_module(module) or patched
            except Exception as exc:
                logger.warning("RUNTIME_AUTHORITY_CONVERGENCE_PATCH_FAILED marker=%s module=%s err=%s", _MARKER, name, exc)
    return patched


def install_import_hook() -> None:
    os.environ.setdefault("NIJA_RUNTIME_AUTHORITY_CONVERGENCE_REPAIR_ENABLED", "true")
    _start_monitor()
    converge_runtime_authority("install")
    _try_patch_loaded()
    if getattr(builtins, _HOOK_FLAG, False):
        return
    original_import = builtins.__import__

    def guarded_import(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
        module = original_import(name, globals, locals, fromlist, level)
        try:
            if "nija_core_loop" in str(name) or "trading_state_machine" in str(name):
                converge_runtime_authority("import_hook")
                _try_patch_loaded()
        except Exception as exc:
            logger.warning("RUNTIME_AUTHORITY_CONVERGENCE_IMPORT_HOOK_FAILED marker=%s name=%s err=%s", _MARKER, name, exc)
        return module

    builtins.__import__ = guarded_import
    setattr(builtins, _HOOK_FLAG, True)
    logger.warning("RUNTIME_AUTHORITY_CONVERGENCE_IMPORT_HOOK marker=%s", _MARKER)


def install() -> None:
    install_import_hook()
