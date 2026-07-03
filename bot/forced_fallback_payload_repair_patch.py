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
_WRAP_ATTR = "_nija_forced_fallback_payload_repair_wrapped_v20260703r"

# ExecutionEngine's target-geometry gate currently rejects stop losses wider
# than MAX_SL_PCT=0.003 (0.300%). Keep fallback repairs below that hard gate;
# do not loosen the execution gate itself.
_FALLBACK_HARD_MAX_SL_PCT = 0.0028
_FALLBACK_DEFAULT_SL_PCT = 0.0025
_FALLBACK_MIN_SL_PCT = 0.0015
_ILLQUID_POLICY_TEXT = "competitive profitability policy blocked illiquid fallback entry"
_MIN_EXPECTANCY_MARGIN = 0.0001


def _truthy(name: str, default: str = "false") -> bool:
    return str(os.environ.get(name, default)).strip().lower() in _TRUTHY


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default) or default)
    except Exception:
        return default


def _wrapper_chain_has_attr(fn: Any, attr: str) -> bool:
    """Return True if any wrapper in a __wrapped__ chain already has attr."""
    seen: set[int] = set()
    cur = fn
    while callable(cur) and id(cur) not in seen:
        seen.add(id(cur))
        if getattr(cur, attr, False):
            return True
        cur = getattr(cur, "__wrapped__", None)
    return False


def _coerce_probability(value: Any) -> float:
    try:
        p = float(value)
    except Exception:
        return 0.0
    if p > 1.0:
        p = p / 100.0
    return max(0.0, min(p, 1.0))


def _signal_expected_win_rate(sig: Any) -> float:
    """Return only explicit win-rate/probability evidence from a signal.

    Do not infer win rate from score or confidence here. If the signal has no
    explicit probability edge, fallback entries must prove EV downstream or be
    skipped before execution.
    """
    for name in (
        "expected_win_rate",
        "win_rate",
        "win_probability",
        "probability_of_success",
        "success_probability",
        "edge_probability",
    ):
        try:
            p = _coerce_probability(getattr(sig, name, None))
            if p > 0.0:
                return p
        except Exception:
            pass
    try:
        analysis = getattr(sig, "analysis", None)
        if isinstance(analysis, dict):
            for name in (
                "expected_win_rate",
                "win_rate",
                "win_probability",
                "probability_of_success",
                "success_probability",
                "edge_probability",
            ):
                p = _coerce_probability(analysis.get(name))
                if p > 0.0:
                    return p
    except Exception:
        pass
    return 0.0


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
    return max(_FALLBACK_MIN_SL_PCT, min(requested, _FALLBACK_HARD_MAX_SL_PCT))


def _payload_ev(payload: Any) -> tuple[bool, str, float, float, float]:
    """Check fallback payload expectancy before execution.

    Returns (ok, detail, expected_wr, breakeven_wr, expectancy_pct).
    This mirrors the ExecutionEngine guard at a conservative preflight level so
    low-EV fallbacks become skipped signals, not rejected orders.
    """
    if not isinstance(payload, dict):
        return True, "non_dict_payload", 0.0, 0.0, 0.0
    if not bool(payload.get("fallback_entry") or payload.get("forced_fallback")):
        return True, "not_fallback", 0.0, 0.0, 0.0
    try:
        entry = float(payload.get("entry_price") or 0.0)
        stop = float(payload.get("stop_loss") or 0.0)
        take_profit = payload.get("take_profit")
        if isinstance(take_profit, dict):
            tp1 = float(take_profit.get("tp1") or take_profit.get("target") or 0.0)
            expected_wr = _coerce_probability(take_profit.get("expected_win_rate"))
        else:
            tp1 = float(take_profit or 0.0)
            expected_wr = 0.0
    except Exception as exc:
        return False, f"fallback_ev_unavailable:{exc}", 0.0, 0.0, 0.0
    if entry <= 0.0 or stop <= 0.0 or tp1 <= 0.0:
        return False, "fallback_ev_missing_price_geometry", expected_wr, 0.0, 0.0
    win_pct = abs(tp1 - entry) / entry
    loss_pct = abs(entry - stop) / entry
    fee_pct = _float_env("NIJA_FALLBACK_PREFLIGHT_ROUND_TRIP_FEE_PCT", 0.003)
    net_win = max(0.0, win_pct - fee_pct)
    net_loss = loss_pct + fee_pct
    if net_win <= 0.0:
        return False, f"fallback_net_win_nonpositive win_pct={win_pct:.4f} fee_pct={fee_pct:.4f}", expected_wr, 1.0, -net_loss
    breakeven = net_loss / (net_win + net_loss)
    expectancy_pct = (expected_wr * net_win) - ((1.0 - expected_wr) * net_loss)
    ok = expected_wr > 0.0 and expectancy_pct > _MIN_EXPECTANCY_MARGIN and expected_wr > breakeven
    detail = (
        f"expected_wr={expected_wr:.4f} breakeven_wr={breakeven:.4f} "
        f"expectancy_pct={expectancy_pct:.4f} win_pct={win_pct:.4f} loss_pct={loss_pct:.4f} fee_pct={fee_pct:.4f}"
    )
    return ok, detail, expected_wr, breakeven, expectancy_pct


def _enforce_fallback_positive_ev(payload: Any, *, sig: Any, symbol: str) -> Any:
    if not isinstance(payload, dict):
        return payload
    tp = payload.get("take_profit")
    if isinstance(tp, dict):
        explicit_wr = _signal_expected_win_rate(sig)
        if explicit_wr > 0.0:
            tp["expected_win_rate"] = explicit_wr
    ok, detail, expected_wr, breakeven, expectancy_pct = _payload_ev(payload)
    if ok:
        return payload
    logger.warning(
        "FORCED_FALLBACK_POSITIVE_EV_PREFILTER_SKIPPED marker=20260703r symbol=%s detail=%s action=skip_before_execute",
        symbol,
        detail,
    )
    print(
        f"[NIJA-PRINT] FORCED_FALLBACK_POSITIVE_EV_PREFILTER_SKIPPED marker=20260703r symbol={symbol} "
        f"expected_wr={expected_wr:.4f} breakeven_wr={breakeven:.4f} expectancy_pct={expectancy_pct:.4f}",
        flush=True,
    )
    raise ValueError(f"fallback positive-EV prefilter blocked execution: {detail}")


def _cap_payload_geometry(payload: Any) -> tuple[Any, bool, float, float]:
    """Normalize any successful fallback payload so it also obeys execution geometry."""
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
    signal_wr = _signal_expected_win_rate(sig)
    expected_win_rate = signal_wr if signal_wr > 0.0 else max(0.35, min(_float_env("NIJA_FALLBACK_REPAIR_EXPECTED_WIN_RATE", 0.50), 0.75))

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
        sig = kwargs.get("sig") if "sig" in kwargs else (args[1] if len(args) > 1 else None)
        symbol = str(getattr(sig, "symbol", "UNKNOWN") or "UNKNOWN")
        try:
            payload = original(self, *args, **kwargs)
            payload, changed, old_pct, new_pct = _cap_payload_geometry(payload)
            if changed:
                logger.critical(
                    "FORCED_FALLBACK_PAYLOAD_GEOMETRY_NORMALIZED marker=20260703r symbol=%s old_sl_pct=%.4f new_sl_pct=%.4f",
                    symbol,
                    old_pct,
                    new_pct,
                )
                print(
                    f"[NIJA-PRINT] FORCED_FALLBACK_PAYLOAD_GEOMETRY_NORMALIZED marker=20260703r | symbol={symbol} "
                    f"old_sl_pct={old_pct * 100.0:.3f}% new_sl_pct={new_pct * 100.0:.3f}%",
                    flush=True,
                )
            return _enforce_fallback_positive_ev(payload, sig=sig, symbol=symbol)
        except ValueError as exc:
            message = str(exc)
            if _ILLQUID_POLICY_TEXT in message:
                logger.warning(
                    "FORCED_FALLBACK_PAYLOAD_REPAIR_SKIPPED marker=20260703r symbol=%s reason=%s action=preserve_competitive_profitability_policy",
                    symbol,
                    message,
                )
                print(
                    f"[NIJA-PRINT] FORCED_FALLBACK_PAYLOAD_REPAIR_SKIPPED marker=20260703r symbol={symbol} reason=illiquid_policy_block",
                    flush=True,
                )
                raise
            if "fallback positive-EV prefilter blocked execution" in message:
                raise
            if "competitive profitability policy" in message:
                logger.warning(
                    "FORCED_FALLBACK_POLICY_SKIP marker=20260703r symbol=%s reason=%s action=skip_before_execute",
                    symbol,
                    message,
                )
                raise
            authorized, auth_detail = _live_runtime_authorized()
            if not authorized:
                logger.critical("FORCED_FALLBACK_PAYLOAD_REPAIR_WAITING marker=20260703r detail=%s err=%s", auth_detail, message)
                print(f"[NIJA-PRINT] FORCED_FALLBACK_PAYLOAD_REPAIR_WAITING marker=20260703r | detail={auth_detail} err={message}", flush=True)
                raise
            df = kwargs.get("df") if "df" in kwargs else (args[0] if len(args) > 0 else None)
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
            payload = _enforce_fallback_positive_ev(payload, sig=sig, symbol=symbol)
            try:
                setattr(sig, "position_multiplier", 1.0)
            except Exception:
                pass
            tp = payload.get("take_profit") if isinstance(payload.get("take_profit"), dict) else {}
            sl_pct = float(tp.get("fallback_sl_pct", 0.0) or 0.0)
            logger.critical(
                "FORCED_FALLBACK_PAYLOAD_REPAIR_APPLIED marker=20260703r symbol=%s action=%s size=%.2f tp1=%s sl_pct=%.4f auth=%s reason=%s",
                symbol,
                payload.get("action"),
                float(payload.get("position_size", 0.0) or 0.0),
                tp.get("tp1"),
                sl_pct,
                auth_detail,
                message,
            )
            print(
                f"[NIJA-PRINT] FORCED_FALLBACK_PAYLOAD_REPAIR_APPLIED marker=20260703r | symbol={symbol} "
                f"action={payload.get('action')} size=${float(payload.get('position_size', 0.0) or 0.0):.2f} "
                f"edge_geometry=true sl_pct={sl_pct * 100.0:.3f}%",
                flush=True,
            )
            return payload

    setattr(_patched_build_forced_fallback_entry_analysis, _WRAP_ATTR, True)
    setattr(_patched_build_forced_fallback_entry_analysis, "__wrapped__", original)
    setattr(cls, "_build_forced_fallback_entry_analysis", _patched_build_forced_fallback_entry_analysis)
    _PATCHED = True
    logger.warning("FORCED_FALLBACK_PAYLOAD_REPAIR_PATCHED marker=20260703r module=%s", getattr(module, "__name__", "<unknown>"))
    print(f"[NIJA-PRINT] FORCED_FALLBACK_PAYLOAD_REPAIR_PATCHED marker=20260703r | module={getattr(module, '__name__', '<unknown>')}", flush=True)
    return True


def _try_patch_loaded() -> bool:
    patched = False
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
            time.sleep(1.0)
        logger.warning("FORCED_FALLBACK_PAYLOAD_REPAIR_MONITOR_COMPLETE marker=20260703r patched=%s patched_any=%s", _PATCHED, patched_any)

    thread = threading.Thread(target=_monitor, name="forced-fallback-payload-repair-monitor", daemon=True)
    thread.start()
    logger.warning("FORCED_FALLBACK_PAYLOAD_REPAIR_MONITOR_STARTED marker=20260703r")


def install_import_hook() -> None:
    global _ORIGINAL_IMPORT_MODULE
    with _INSTALL_LOCK:
        _try_patch_loaded()
        _start_module_monitor()
        if _ORIGINAL_IMPORT_MODULE is not None:
            logger.warning("FORCED_FALLBACK_PAYLOAD_REPAIR_INSTALL_COMPLETE marker=20260703r already_installed=True patched=%s", _PATCHED)
            return

        _ORIGINAL_IMPORT_MODULE = importlib.import_module

        def _wrapped_import_module(name: str, package: str | None = None):
            module = _ORIGINAL_IMPORT_MODULE(name, package)  # type: ignore[misc]
            if name in {"bot.nija_core_loop", "nija_core_loop"} or hasattr(module, "NijaCoreLoop"):
                _install_on_module(module)
            _try_patch_loaded()
            return module

        importlib.import_module = _wrapped_import_module  # type: ignore[assignment]
        logger.warning("FORCED_FALLBACK_PAYLOAD_REPAIR_INSTALL_COMPLETE marker=20260703r patched=%s", _PATCHED)
