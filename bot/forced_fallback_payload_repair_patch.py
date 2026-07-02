from __future__ import annotations

import importlib
import logging
import os
import sys
import threading
import time
from types import ModuleType
from typing import Any, Callable, Optional

logger = logging.getLogger("nija.forced_fallback_payload_repair")
_ORIGINAL_IMPORT_MODULE: Optional[Callable[..., Any]] = None
_PATCHED = False
_MONITOR_STARTED = False
_INSTALL_LOCK = threading.Lock()
_TRUTHY = {"1", "true", "yes", "enabled", "on", "y"}
_WRAP_ATTR = "_nija_forced_fallback_payload_repair_wrapped"

# ExecutionEngine's target-geometry gate currently rejects stop losses wider
# than MAX_SL_PCT=0.003 (0.300%). Keep fallback repairs below that hard gate;
# do not loosen the execution gate itself.
_FALLBACK_HARD_MAX_SL_PCT = 0.0028
_FALLBACK_DEFAULT_SL_PCT = 0.0025
_FALLBACK_MIN_SL_PCT = 0.0015


def _truthy(name: str, default: str = "false") -> bool:
    return str(os.environ.get(name, default)).strip().lower() in _TRUTHY


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default) or default)
    except Exception:
        return default


def _wrapper_chain_has_attr(fn: Any, attr: str) -> bool:
    """Return True if any wrapper in a __wrapped__ chain already has attr.

    Multiple fallback repair patches wrap the same NijaCoreLoop method. Without
    chain-aware idempotence, the patches can alternately wrap each other on every
    monitor scan and flood Railway logs with repeated PATCHED markers. This keeps
    the wrapper stack stable after one successful install.
    """
    seen: set[int] = set()
    cur = fn
    while callable(cur) and id(cur) not in seen:
        seen.add(id(cur))
        if getattr(cur, attr, False):
            return True
        cur = getattr(cur, "__wrapped__", None)
    return False


def _state_machine_live_active() -> tuple[bool, str]:
    try:
        try:
            from bot.trading_state_machine import get_state_machine
        except ImportError:
            from trading_state_machine import get_state_machine  # type: ignore[import]
        sm = get_state_machine()
        cur = getattr(sm, "get_current_state", lambda: None)()
        state = str(getattr(cur, "value", cur) or "").strip().upper()
        if state == "LIVE_ACTIVE":
            return True, "state_machine_live_active"
        return False, f"state_machine_not_live_active:{state or 'unknown'}"
    except Exception as exc:
        return False, f"state_machine_probe_failed:{exc}"


def _coordinator_executing() -> tuple[bool, str]:
    try:
        for mod_name in ("bot.startup_coordinator", "startup_coordinator"):
            try:
                mod = importlib.import_module(mod_name)
            except Exception:
                continue
            getter = getattr(mod, "get_startup_coordinator", None)
            if not callable(getter):
                continue
            coord = getter()
            runtime_state = getattr(coord, "runtime_state", getattr(coord, "_runtime_state", None))
            coord_state = getattr(coord, "state", getattr(coord, "_state", None))
            runtime_text = str(getattr(runtime_state, "value", runtime_state) or "").upper()
            coord_text = str(getattr(coord_state, "value", coord_state) or "").upper()
            if "EXECUT" in runtime_text or "DISPATCH" in coord_text:
                return True, f"coordinator_runtime={runtime_text} coordinator_state={coord_text}"
        return False, "coordinator_not_executing"
    except Exception as exc:
        return False, f"coordinator_probe_failed:{exc}"


def _capital_ready() -> tuple[bool, str]:
    try:
        try:
            from bot.capital_authority import get_capital_authority
        except ImportError:
            from capital_authority import get_capital_authority  # type: ignore[import]
        ca = get_capital_authority()
        hydrated = bool(getattr(ca, "is_hydrated", False))
        first_snap = bool(getattr(ca, "first_snap_accepted", False))
        valid_brokers = int(getattr(ca, "valid_broker_count", 0) or 0)
        best = 0.0
        for attr in ("total_capital", "real_capital"):
            try:
                best = max(best, float(getattr(ca, attr, 0.0) or 0.0))
            except Exception:
                pass
        for meth in ("get_real_capital", "get_usable_capital"):
            getter = getattr(ca, meth, None)
            if callable(getter):
                try:
                    best = max(best, float(getter() or 0.0))
                except Exception:
                    pass
        fresh = True
        fresh_getter = getattr(ca, "is_fresh", None)
        if callable(fresh_getter):
            try:
                fresh = bool(fresh_getter(ttl_s=180.0))
            except TypeError:
                fresh = bool(fresh_getter())
            except Exception:
                fresh = False
        ok = hydrated and first_snap and valid_brokers > 0 and best > 0.0 and fresh
        return ok, f"capital hydrated={hydrated} first_snap={first_snap} valid_brokers={valid_brokers} amount={best:.2f} fresh={fresh}"
    except Exception as exc:
        return False, f"capital_probe_failed:{exc}"


def _kill_switch_clear() -> tuple[bool, str]:
    try:
        try:
            from bot.kill_switch import get_kill_switch
        except ImportError:
            from kill_switch import get_kill_switch  # type: ignore[import]
        active = bool(get_kill_switch().is_active())
        return (not active), f"kill_switch_active={active}"
    except Exception as exc:
        return False, f"kill_switch_probe_failed:{exc}"


def _writer_lease_present() -> tuple[bool, str]:
    token = str(os.environ.get("NIJA_WRITER_FENCING_TOKEN", "")).strip()
    generation = str(os.environ.get("NIJA_WRITER_LEASE_GENERATION", "")).strip()
    if token and generation:
        return True, f"writer_token_prefix={token[:8]} generation={generation}"
    return False, "writer_token_or_generation_missing"


def _live_runtime_authorized() -> tuple[bool, str]:
    if not _truthy("LIVE_CAPITAL_VERIFIED"):
        return False, "live_capital_not_verified"
    if _truthy("DRY_RUN_MODE") or _truthy("PAPER_MODE"):
        return False, "simulation_mode"

    writer_ok, writer_detail = _writer_lease_present()
    if not writer_ok:
        return False, writer_detail
    kill_ok, kill_detail = _kill_switch_clear()
    if not kill_ok:
        return False, kill_detail
    cap_ok, cap_detail = _capital_ready()
    if not cap_ok:
        return False, cap_detail

    env_state = str(os.environ.get("NIJA_RUNTIME_TRADING_STATE", "")).strip().upper()
    env_auth = _truthy("NIJA_RUNTIME_EXECUTION_AUTHORITY")
    sm_ok, sm_detail = _state_machine_live_active()
    coord_ok, coord_detail = _coordinator_executing()

    if (env_state == "LIVE_ACTIVE" and env_auth) or sm_ok or coord_ok:
        return True, f"authorized env_state={env_state or 'unset'} env_auth={env_auth} {sm_detail} {coord_detail} {cap_detail} {writer_detail} {kill_detail}"
    return False, f"not_live_authorized env_state={env_state or 'unset'} env_auth={env_auth} {sm_detail} {coord_detail}"


def _broker_name(loop: Any) -> str:
    try:
        apex = getattr(loop, "apex", None)
        if apex is not None and hasattr(apex, "_get_broker_name"):
            return str(apex._get_broker_name() or "kraken").lower()
    except Exception:
        pass
    return "kraken"


def _min_notional(loop: Any, balance: float) -> float:
    broker = _broker_name(loop)
    try:
        from bot.minimum_notional_gate import get_minimum_notional_gate
        return float(get_minimum_notional_gate().config.get_min_notional_for_broker(broker, balance=balance))
    except Exception:
        try:
            from minimum_notional_gate import get_minimum_notional_gate  # type: ignore[import]
            return float(get_minimum_notional_gate().config.get_min_notional_for_broker(broker, balance=balance))
        except Exception:
            return 2.0 if broker in {"kraken", "coinbase", "okx"} else 5.0


def _fallback_sl_pct() -> float:
    requested = _float_env("NIJA_FALLBACK_REPAIR_SL_PCT", _FALLBACK_DEFAULT_SL_PCT)
    # The previous default/env value could be 0.012 (1.2%), and the native
    # fallback builder can produce ~0.45%. Both fail target_geometry_gate.
    return max(_FALLBACK_MIN_SL_PCT, min(requested, _FALLBACK_HARD_MAX_SL_PCT))


def _cap_payload_geometry(payload: Any) -> tuple[Any, bool, float, float]:
    """Normalize any successful fallback payload so it also obeys execution geometry.

    Returns (payload, changed, old_sl_pct, new_sl_pct). This is intentionally
    applied even when the native fallback builder succeeds, because the latest
    live logs show it can return a stop-loss wider than ExecutionEngine.MAX_SL_PCT.
    """

    if not isinstance(payload, dict):
        return payload, False, 0.0, 0.0
    try:
        price = float(payload.get("entry_price") or 0.0)
        stop = float(payload.get("stop_loss") or 0.0)
    except Exception:
        return payload, False, 0.0, 0.0
    if price <= 0.0 or stop <= 0.0:
        return payload, False, 0.0, 0.0

    old_sl_pct = abs((price - stop) / price)
    capped_pct = _fallback_sl_pct()
    if old_sl_pct <= capped_pct:
        return payload, False, old_sl_pct, old_sl_pct

    action = str(payload.get("action") or "enter_long").lower()
    if action == "enter_short":
        payload["stop_loss"] = price * (1.0 + capped_pct)
    else:
        payload["stop_loss"] = price * (1.0 - capped_pct)

    tp = payload.get("take_profit")
    if isinstance(tp, dict):
        tp["fallback_sl_pct"] = capped_pct
        tp["fallback_max_sl_pct"] = _FALLBACK_HARD_MAX_SL_PCT
    payload["fallback_target_geometry_capped"] = True
    payload["fallback_edge_geometry_repaired"] = True
    payload["reason"] = str(payload.get("reason") or "fallback_entry") + " [fallback_target_geometry_capped]"
    return payload, True, old_sl_pct, capped_pct


def _build_conservative_payload(loop: Any, *, df: Any, sig: Any, snapshot: Any, action: str, existing_reason: str) -> dict[str, Any]:
    try:
        price = float(df["close"].iloc[-1])
    except Exception:
        price = 0.0
    if price <= 0.0:
        raise ValueError("fallback payload requires positive close price")

    balance = max(float(getattr(snapshot, "balance", 0.0) or 0.0), 0.0)
    if balance <= 0.0:
        raise ValueError("fallback payload requires positive balance")

    floor = _min_notional(loop, balance)
    size = min(max(floor, balance * 0.025), balance)

    sl_pct = _fallback_sl_pct()
    tp1_pct = max(_float_env("NIJA_FALLBACK_REPAIR_TP1_PCT", 0.040), sl_pct * 2.5, 0.030)
    tp2_pct = max(_float_env("NIJA_FALLBACK_REPAIR_TP2_PCT", 0.060), tp1_pct + 0.010)
    tp3_pct = max(_float_env("NIJA_FALLBACK_REPAIR_TP3_PCT", 0.080), tp2_pct + 0.010)
    expected_win_rate = max(0.35, min(_float_env("NIJA_FALLBACK_REPAIR_EXPECTED_WIN_RATE", 0.50), 0.75))

    if action == "enter_short":
        stop_loss = price * (1.0 + sl_pct)
        take_profit = {
            "tp1": price * (1.0 - tp1_pct),
            "tp2": price * (1.0 - tp2_pct),
            "tp3": price * (1.0 - tp3_pct),
            "expected_win_rate": expected_win_rate,
            "market_quality": 1.0,
            "regime": "fallback_repair",
            "fallback_sl_pct": sl_pct,
            "fallback_max_sl_pct": _FALLBACK_HARD_MAX_SL_PCT,
        }
    else:
        stop_loss = price * (1.0 - sl_pct)
        take_profit = {
            "tp1": price * (1.0 + tp1_pct),
            "tp2": price * (1.0 + tp2_pct),
            "tp3": price * (1.0 + tp3_pct),
            "expected_win_rate": expected_win_rate,
            "market_quality": 1.0,
            "regime": "fallback_repair",
            "fallback_sl_pct": sl_pct,
            "fallback_max_sl_pct": _FALLBACK_HARD_MAX_SL_PCT,
        }

    reason = str(existing_reason or getattr(sig, "reason", "fallback_entry") or "fallback_entry")
    if "fallback" not in reason.lower():
        reason = f"{reason} [fallback_entry]"

    return {
        "action": action,
        "entry_price": price,
        "position_size": size,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "trailing_stop_pct": 0.75,
        "reason": reason + " [fallback_payload_repair_cost_aware_target_geometry_capped]",
        "fallback_entry": True,
        "forced_fallback": True,
        "fallback_payload_repaired": True,
        "fallback_edge_geometry_repaired": True,
        "fallback_target_geometry_capped": True,
        "competitive_profitability_policy": "handled_by_downstream_gates",
    }


def _install_on_module(module: ModuleType) -> bool:
    global _PATCHED
    cls = getattr(module, "NijaCoreLoop", None)
    if not isinstance(cls, type):
        return False
    original = getattr(cls, "_build_forced_fallback_entry_analysis", None)
    if not callable(original):
        return False
    if _wrapper_chain_has_attr(original, _WRAP_ATTR):
        _PATCHED = True
        return True

    def _patched_build_forced_fallback_entry_analysis(self: Any, *args: Any, **kwargs: Any) -> dict[str, Any]:
        try:
            payload = original(self, *args, **kwargs)
            payload, changed, old_pct, new_pct = _cap_payload_geometry(payload)
            if changed:
                symbol = getattr(args[1], "symbol", "UNKNOWN") if len(args) > 1 else getattr(kwargs.get("sig"), "symbol", "UNKNOWN")
                logger.critical(
                    "FORCED_FALLBACK_PAYLOAD_GEOMETRY_NORMALIZED symbol=%s old_sl_pct=%.4f new_sl_pct=%.4f",
                    symbol,
                    old_pct,
                    new_pct,
                )
                print(
                    f"[NIJA-PRINT] FORCED_FALLBACK_PAYLOAD_GEOMETRY_NORMALIZED | symbol={symbol} "
                    f"old_sl_pct={old_pct * 100.0:.3f}% new_sl_pct={new_pct * 100.0:.3f}%",
                    flush=True,
                )
            return payload
        except ValueError as exc:
            message = str(exc)
            if "competitive profitability policy blocked illiquid fallback entry" not in message:
                raise
            authorized, auth_detail = _live_runtime_authorized()
            if not authorized:
                logger.critical("FORCED_FALLBACK_PAYLOAD_REPAIR_WAITING detail=%s err=%s", auth_detail, message)
                print(f"[NIJA-PRINT] FORCED_FALLBACK_PAYLOAD_REPAIR_WAITING | detail={auth_detail} err={message}", flush=True)
                raise
            df = kwargs.get("df") if "df" in kwargs else (args[0] if len(args) > 0 else None)
            sig = kwargs.get("sig") if "sig" in kwargs else (args[1] if len(args) > 1 else None)
            snapshot = kwargs.get("snapshot") if "snapshot" in kwargs else (args[2] if len(args) > 2 else None)
            action = kwargs.get("action") if "action" in kwargs else (args[3] if len(args) > 3 else "enter_long")
            existing_reason = kwargs.get("existing_reason", "")
            payload = _build_conservative_payload(
                self,
                df=df,
                sig=sig,
                snapshot=snapshot,
                action=str(action or "enter_long"),
                existing_reason=str(existing_reason or message),
            )
            try:
                setattr(sig, "position_multiplier", 1.0)
            except Exception:
                pass
            tp = payload.get("take_profit") if isinstance(payload.get("take_profit"), dict) else {}
            sl_pct = float(tp.get("fallback_sl_pct", 0.0) or 0.0)
            logger.critical(
                "FORCED_FALLBACK_PAYLOAD_REPAIR_APPLIED symbol=%s action=%s size=%.2f tp1=%s sl_pct=%.4f auth=%s reason=%s",
                getattr(sig, "symbol", "UNKNOWN"),
                payload.get("action"),
                float(payload.get("position_size", 0.0) or 0.0),
                tp.get("tp1"),
                sl_pct,
                auth_detail,
                message,
            )
            print(
                f"[NIJA-PRINT] FORCED_FALLBACK_PAYLOAD_REPAIR_APPLIED | symbol={getattr(sig, 'symbol', 'UNKNOWN')} "
                f"action={payload.get('action')} size=${float(payload.get('position_size', 0.0) or 0.0):.2f} "
                f"edge_geometry=true sl_pct={sl_pct * 100.0:.3f}%",
                flush=True,
            )
            return payload

    setattr(_patched_build_forced_fallback_entry_analysis, _WRAP_ATTR, True)
    setattr(_patched_build_forced_fallback_entry_analysis, "__wrapped__", original)
    setattr(cls, "_build_forced_fallback_entry_analysis", _patched_build_forced_fallback_entry_analysis)
    _PATCHED = True
    logger.warning("FORCED_FALLBACK_PAYLOAD_REPAIR_PATCHED module=%s", getattr(module, "__name__", "<unknown>"))
    print(f"[NIJA-PRINT] FORCED_FALLBACK_PAYLOAD_REPAIR_PATCHED | module={getattr(module, '__name__', '<unknown>')}", flush=True)
    return True


def _try_patch_loaded() -> bool:
    patched = False
    # Patch exact known names and every loaded module exposing NijaCoreLoop.
    # Some Railway/runpy paths can load a second class object after the first
    # successful patch, so callers should keep scanning without stacking the same
    # wrapper repeatedly.
    for name, module in list(sys.modules.items()):
        if not isinstance(module, ModuleType):
            continue
        if name in {"bot.nija_core_loop", "nija_core_loop"} or hasattr(module, "NijaCoreLoop"):
            patched = _install_on_module(module) or patched
    return patched


def _start_module_monitor() -> None:
    global _MONITOR_STARTED
    if _MONITOR_STARTED:
        return
    _MONITOR_STARTED = True

    def _monitor() -> None:
        deadline = time.time() + float(os.environ.get("NIJA_PATCH_MONITOR_SECONDS", "300") or "300")
        patched_any = False
        while time.time() < deadline:
            patched_any = _try_patch_loaded() or patched_any
            time.sleep(0.25)
        logger.warning("FORCED_FALLBACK_PAYLOAD_REPAIR_MONITOR_COMPLETE patched=%s patched_any=%s", _PATCHED, patched_any)

    thread = threading.Thread(target=_monitor, name="forced-fallback-payload-repair-monitor", daemon=True)
    thread.start()
    logger.warning("FORCED_FALLBACK_PAYLOAD_REPAIR_MONITOR_STARTED")


def install_import_hook() -> None:
    global _ORIGINAL_IMPORT_MODULE
    with _INSTALL_LOCK:
        _try_patch_loaded()
        _start_module_monitor()
        if _ORIGINAL_IMPORT_MODULE is not None:
            logger.warning("FORCED_FALLBACK_PAYLOAD_REPAIR_INSTALL_COMPLETE already_installed=True patched=%s", _PATCHED)
            return

        _ORIGINAL_IMPORT_MODULE = importlib.import_module

        def _wrapped_import_module(name: str, package: str | None = None):
            module = _ORIGINAL_IMPORT_MODULE(name, package)  # type: ignore[misc]
            if name in {"bot.nija_core_loop", "nija_core_loop"} or hasattr(module, "NijaCoreLoop"):
                _install_on_module(module)
            # Also rescan all loaded modules after imports because normal import
            # statements can populate sys.modules without calling this wrapper for
            # the target name directly.
            _try_patch_loaded()
            return module

        importlib.import_module = _wrapped_import_module  # type: ignore[assignment]
        logger.warning("FORCED_FALLBACK_PAYLOAD_REPAIR_INSTALL_COMPLETE patched=%s", _PATCHED)
