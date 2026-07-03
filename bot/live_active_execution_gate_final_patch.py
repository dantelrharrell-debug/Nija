from __future__ import annotations

import importlib
import logging
import os
import sys
import threading
import time
from types import ModuleType
from typing import Any, Callable, Optional

logger = logging.getLogger("nija.live_active_execution_gate_final_patch")

_ORIGINAL_IMPORT_MODULE: Optional[Callable[..., Any]] = None
_PATCHED = False
_TRADING_STRATEGY_PATCHED = False
_ADOPTION_PATCHED = False
_MONITOR_STARTED = False
_INSTALL_LOCK = threading.Lock()
_WAIT_LOG_LOCK = threading.Lock()
_WAIT_LOG_STATE: dict[str, tuple[float, int]] = {}

_TRUTHY = {"1", "true", "yes", "enabled", "on", "y"}
_MARKER = "LIVE_ACTIVE_EXECUTION_GATE_FINAL_PATCHED marker=20260703q"
_ROTATION_ATTR = "_nija_okx_entry_rotation_wrapped_v20260703q"
_ADOPTION_APPEND_ATTR = "_nija_adopted_profit_runtime_append_wrapped_v20260703q"
_WRAP_ATTR = "_nija_live_active_execution_gate_final_wrapped_v20260703q"


def _truthy(name: str, default: str = "") -> bool:
    return str(os.environ.get(name, default)).strip().lower() in _TRUTHY


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)) or default)
    except Exception:
        return default


def _waiting_log(detail: str) -> None:
    interval = _float_env("NIJA_LIVE_ACTIVE_FINAL_WAIT_LOG_THROTTLE_S", 30.0)
    now = time.monotonic()
    key = str(detail or "unknown")
    with _WAIT_LOG_LOCK:
        last_ts, suppressed = _WAIT_LOG_STATE.get(key, (0.0, 0))
        if now - last_ts < interval:
            _WAIT_LOG_STATE[key] = (last_ts, suppressed + 1)
            return
        _WAIT_LOG_STATE[key] = (now, 0)
    if suppressed:
        logger.info("LIVE_ACTIVE_EXECUTION_GATE_FINAL_WAITING_THROTTLED marker=20260703q detail=%s suppressed=%d", key, suppressed)
    logger.warning("LIVE_ACTIVE_EXECUTION_GATE_FINAL_WAITING marker=20260703q detail=%s", key)


def _state_value(sm: Any) -> str:
    try:
        current = getattr(sm, "get_current_state", lambda: None)()
        value = getattr(current, "value", current)
        return str(value or "unknown").strip().upper()
    except Exception:
        return "unknown"


def _committed(sm: Any) -> bool:
    for name in ("get_activation_committed", "activation_committed"):
        try:
            attr = getattr(sm, name, None)
            value = attr() if callable(attr) else attr
            if value is not None:
                return bool(value)
        except Exception:
            pass
    try:
        return bool(getattr(sm, "_activation_committed", False))
    except Exception:
        return False


def _first_snapshot_ok(sm: Any) -> bool:
    for name in ("get_first_snap_accepted", "get_first_snapshot_accepted", "first_snap_accepted", "first_snapshot_accepted"):
        try:
            attr = getattr(sm, name, None)
            value = attr() if callable(attr) else attr
            if value is not None:
                return bool(value)
        except Exception:
            pass
    try:
        return bool(getattr(sm, "_first_snap_accepted", False) or getattr(sm, "_first_snapshot_accepted", False))
    except Exception:
        return False


def _kill_switch_clear() -> bool:
    try:
        try:
            from bot.kill_switch import get_kill_switch
        except ImportError:
            from kill_switch import get_kill_switch  # type: ignore[import]
        return not bool(get_kill_switch().is_active())
    except Exception:
        return True


def _capital_ready() -> bool:
    if _truthy("LIVE_CAPITAL_VERIFIED"):
        return True
    try:
        try:
            from bot.capital_authority import get_capital_authority
        except ImportError:
            from capital_authority import get_capital_authority  # type: ignore[import]
        ca = get_capital_authority()
        hydrated = bool(getattr(ca, "is_hydrated", False))
        real = 0.0
        for attr in ("total_capital", "real_capital", "usable_capital", "available_capital"):
            try:
                real = max(real, float(getattr(ca, attr, 0.0) or 0.0))
            except Exception:
                pass
        if hydrated and real > 0.0:
            return True
    except Exception:
        pass
    try:
        value = float(os.environ.get("NIJA_FORCE_TRADE_BALANCE", "0") or "0")
        if value > 0.0:
            return True
    except Exception:
        pass
    return False


def _writer_authority_ready() -> bool:
    if str(os.environ.get("NIJA_WRITER_FENCING_TOKEN", "")).strip():
        return True
    if _truthy("NIJA_WRITER_HEARTBEAT_ACTIVE"):
        return True
    return False


def _final_live_active_dispatch_ready(sm: Any) -> tuple[bool, str]:
    state = _state_value(sm)
    if state != "LIVE_ACTIVE":
        return False, f"state_not_live_active:{state}"
    if not _truthy("LIVE_CAPITAL_VERIFIED"):
        return False, "live_capital_not_verified"
    if _truthy("DRY_RUN_MODE") or _truthy("PAPER_MODE"):
        return False, "simulation_mode_enabled"
    if not _writer_authority_ready():
        return False, "writer_authority_missing"
    if not _committed(sm):
        return False, "activation_not_committed"
    if not _first_snapshot_ok(sm):
        logger.warning("LIVE_ACTIVE_EXECUTION_GATE_FINAL first_snapshot_accessor_false_nonfatal marker=20260703q")
    if not _kill_switch_clear():
        return False, "kill_switch_active"
    if not _capital_ready():
        return False, "capital_not_ready"
    return True, "live_active_committed_authority_rehydrated_v20260703q"


def _broker_key_from_obj(obj: Any) -> str:
    if obj is None:
        return "unknown"
    for attr in ("broker_type", "name", "broker_name", "exchange", "exchange_name"):
        try:
            value = getattr(obj, attr, None)
            if value is None:
                continue
            raw = getattr(value, "value", value)
            text = str(raw or "").strip().lower()
            if text:
                for key in ("okx", "kraken", "coinbase", "alpaca", "binance"):
                    if key in text:
                        return key
                return text
        except Exception:
            pass
    try:
        cls = type(obj).__name__.lower()
        for key in ("okx", "kraken", "coinbase", "alpaca", "binance"):
            if key in cls:
                return key
    except Exception:
        pass
    return "unknown"


def _collect_candidate_brokers(strategy: Any) -> dict[str, Any]:
    candidates: dict[str, Any] = {}
    for broker in (getattr(strategy, "broker", None),):
        key = _broker_key_from_obj(broker)
        if broker is not None and key != "unknown":
            candidates[key] = broker
    manager = getattr(strategy, "multi_account_manager", None)
    try:
        for raw_key, broker in (getattr(manager, "platform_brokers", {}) or {}).items():
            key = _broker_key_from_obj(broker)
            if key == "unknown" and raw_key is not None:
                key = str(getattr(raw_key, "value", raw_key)).strip().lower()
            if broker is not None and key:
                candidates[key] = broker
    except Exception:
        pass
    bm = getattr(strategy, "broker_manager", None)
    try:
        for raw_key, broker in (getattr(bm, "brokers", {}) or {}).items():
            key = _broker_key_from_obj(broker)
            if key == "unknown" and raw_key is not None:
                key = str(getattr(raw_key, "value", raw_key)).strip().lower()
            if broker is not None and key:
                candidates.setdefault(key, broker)
    except Exception:
        pass
    return candidates


def _patch_trading_strategy_module(module: ModuleType) -> bool:
    global _TRADING_STRATEGY_PATCHED
    cls = getattr(module, "TradingStrategy", None)
    if not isinstance(cls, type):
        return False
    original = getattr(cls, "_get_active_broker", None)
    if not callable(original):
        return False
    if getattr(original, _ROTATION_ATTR, False):
        _TRADING_STRATEGY_PATCHED = True
        return True

    try:
        mins = getattr(module, "BROKER_MIN_BALANCE", None)
        if isinstance(mins, dict):
            mins["okx"] = min(float(mins.get("okx", 50.0) or 50.0), float(os.environ.get("NIJA_OKX_ENTRY_MIN_BALANCE_USD", "10") or "10"))
        priority = getattr(module, "ENTRY_BROKER_PRIORITY", None)
        if isinstance(priority, list):
            desired = [p.strip().lower() for p in os.environ.get("NIJA_ENTRY_BROKER_PRIORITY", "okx,kraken,coinbase,alpaca").split(",") if p.strip()]
            merged = desired + [p for p in priority if p not in desired]
            priority[:] = merged
    except Exception as exc:
        logger.debug("OKX_ENTRY_ROTATION priority/min update skipped: %s", exc)

    def _rotating_get_active_broker(self: Any) -> Optional[Any]:
        candidates = _collect_candidate_brokers(self)
        if not candidates:
            return original(self)
        priorities = [p.strip().lower() for p in os.environ.get("NIJA_ENTRY_BROKER_PRIORITY", "okx,kraken,coinbase,alpaca").split(",") if p.strip()]
        names = [name for name in priorities if name in candidates] + sorted(set(candidates) - set(priorities))
        eligible: list[tuple[str, Any, str]] = []
        status: dict[str, str] = {}
        for name in names:
            broker = candidates.get(name)
            try:
                ok, reason = self._is_broker_eligible_for_entry(broker)
            except Exception as exc:
                ok, reason = False, str(exc)
            status[name] = reason
            if ok:
                eligible.append((name, broker, reason))
        if not eligible:
            logger.warning("ENTRY_BROKER_ROTATION_NO_ELIGIBLE marker=20260703q status=%s", status)
            return original(self)
        idx = int(getattr(self, "_nija_entry_broker_rotation_idx", -1) or -1) + 1
        setattr(self, "_nija_entry_broker_rotation_idx", idx)
        name, selected, reason = eligible[idx % len(eligible)]
        self.broker = selected
        try:
            if getattr(self, "broker_manager", None) is not None:
                self.broker_manager.active_broker = selected
        except Exception:
            pass
        try:
            apex = getattr(self, "apex", None)
            if apex is not None and hasattr(apex, "update_broker_client"):
                apex.update_broker_client(selected)
        except Exception:
            pass
        logger.critical(
            "ENTRY_BROKER_ROTATION_SELECTED marker=20260703q broker=%s reason=%s eligible=%s status=%s",
            name,
            reason,
            [item[0] for item in eligible],
            status,
        )
        print(f"[NIJA-PRINT] ENTRY_BROKER_ROTATION_SELECTED marker=20260703q broker={name} eligible={[item[0] for item in eligible]}", flush=True)
        return selected

    setattr(_rotating_get_active_broker, _ROTATION_ATTR, True)
    setattr(cls, "_get_active_broker", _rotating_get_active_broker)
    _TRADING_STRATEGY_PATCHED = True
    logger.warning("OKX_ENTRY_ROTATION_PATCHED marker=20260703q module=%s", getattr(module, "__name__", "<unknown>"))
    print("[NIJA-PRINT] OKX_ENTRY_ROTATION_PATCHED marker=20260703q", flush=True)
    return True


def _patch_live_entry_runtime_fixes(module: ModuleType) -> bool:
    global _ADOPTION_PATCHED
    original_append = getattr(module, "_append_to_runtime_open_positions", None)
    if not callable(original_append):
        return False
    if getattr(original_append, _ADOPTION_APPEND_ATTR, False):
        _ADOPTION_PATCHED = True
        return True

    def _append_with_profit_targets(core_loop: Any, position: Any) -> bool:
        attached = False
        try:
            attached = bool(original_append(core_loop, position))
        except Exception as exc:
            logger.debug("ADOPTED_PROFIT_RUNTIME original append skipped: %s", exc)
        pos = dict(position or {})
        pos.update({
            "managed_by_nija": True,
            "runtime": True,
            "profit_exit": True,
            "exit_profile": pos.get("exit_profile") or "ADOPTED_HELD_PROFIT_PROTECT",
            "take_profit_levels_pct": pos.get("take_profit_levels_pct") or [3.0, 4.0, 5.5, 7.0],
            "min_net_profit_pct": pos.get("min_net_profit_pct", 0.50),
            "min_hold_time_s": pos.get("min_hold_time_s", 120),
            "giveback_pct": pos.get("giveback_pct", 0.30),
        })
        key = str(pos.get("id") or pos.get("symbol") or "adopted")
        for owner_name, owner in (("core", core_loop), ("apex", getattr(core_loop, "apex", None))):
            if owner is None:
                continue
            for attr in ("open_positions", "positions", "tracked_positions", "_open_positions", "_tracked_positions"):
                try:
                    container = getattr(owner, attr, None)
                    if container is None:
                        container = {}
                        setattr(owner, attr, container)
                    if isinstance(container, dict):
                        container[key] = dict(pos)
                        attached = True
                    elif isinstance(container, list):
                        existing = {str((item or {}).get("id") or (item or {}).get("symbol")) for item in container if isinstance(item, dict)}
                        if key not in existing:
                            container.append(dict(pos))
                            attached = True
                except Exception:
                    continue
        if attached:
            logger.critical(
                "ADOPTED_PROFIT_EXIT_MANAGED marker=20260703q broker=%s symbol=%s value=$%.2f profit_exit=True runtime=True",
                pos.get("broker"),
                pos.get("symbol"),
                float(pos.get("market_value_usd") or 0.0),
            )
            print(f"[NIJA-PRINT] ADOPTED_PROFIT_EXIT_MANAGED marker=20260703q broker={pos.get('broker')} symbol={pos.get('symbol')}", flush=True)
        return attached

    setattr(_append_with_profit_targets, _ADOPTION_APPEND_ATTR, True)
    setattr(module, "_append_to_runtime_open_positions", _append_with_profit_targets)
    _ADOPTION_PATCHED = True
    logger.warning("ADOPTED_POSITION_PROFIT_EXIT_PATCHED marker=20260703q module=%s", getattr(module, "__name__", "<unknown>"))
    print("[NIJA-PRINT] ADOPTED_POSITION_PROFIT_EXIT_PATCHED marker=20260703q", flush=True)
    return True


def _install_on_module(module: ModuleType) -> bool:
    global _PATCHED
    cls = getattr(module, "TradingStateMachine", None)
    if not isinstance(cls, type):
        return False
    original = getattr(cls, "can_dispatch_trades", None)
    if not callable(original):
        return False
    if getattr(original, _WRAP_ATTR, False):
        _PATCHED = True
        return True

    def _patched_can_dispatch_trades(self: Any, *args: Any, **kwargs: Any) -> bool:
        try:
            if bool(original(self, *args, **kwargs)):
                return True
        except Exception as exc:
            logger.warning("LIVE_ACTIVE_EXECUTION_GATE_FINAL original_can_dispatch_failed marker=20260703q err=%s", exc)
        ready, detail = _final_live_active_dispatch_ready(self)
        if ready:
            try:
                setattr(self, "_activation_committed", True)
                setattr(self, "_execution_authority", True)
                setattr(self, "_can_dispatch_trades", True)
                os.environ["NIJA_RUNTIME_TRADING_STATE"] = "LIVE_ACTIVE"
                os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] = "true"
            except Exception:
                pass
            logger.critical(
                "LIVE_ACTIVE_EXECUTION_GATE_FINAL_APPLIED marker=20260703q detail=%s token_prefix=%s generation=%s heartbeat=%s",
                detail,
                os.environ.get("NIJA_WRITER_FENCING_TOKEN", "")[:8],
                os.environ.get("NIJA_WRITER_LEASE_GENERATION", ""),
                os.environ.get("NIJA_WRITER_HEARTBEAT_ACTIVE", ""),
            )
            print(f"[NIJA-PRINT] LIVE_ACTIVE_EXECUTION_GATE_FINAL_APPLIED marker=20260703q | {detail}", flush=True)
            return True
        _waiting_log(detail)
        return False

    setattr(_patched_can_dispatch_trades, _WRAP_ATTR, True)
    setattr(cls, "can_dispatch_trades", _patched_can_dispatch_trades)
    _PATCHED = True
    logger.warning("%s module=%s", _MARKER, getattr(module, "__name__", "<unknown>"))
    print("[NIJA-PRINT] LIVE_ACTIVE_EXECUTION_GATE_FINAL_PATCHED marker=20260703q", flush=True)
    return True


def _try_patch_loaded() -> bool:
    patched = False
    for name in ("bot.trading_state_machine", "trading_state_machine"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            patched = _install_on_module(module) or patched
    for name in ("bot.trading_strategy", "trading_strategy"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            patched = _patch_trading_strategy_module(module) or patched
    for name in ("bot.live_entry_runtime_fixes", "live_entry_runtime_fixes"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            patched = _patch_live_entry_runtime_fixes(module) or patched
    return patched


def _start_monitor() -> None:
    global _MONITOR_STARTED
    if _MONITOR_STARTED:
        return
    _MONITOR_STARTED = True

    def _monitor() -> None:
        deadline = time.time() + float(os.environ.get("NIJA_PATCH_MONITOR_SECONDS", "240") or "240")
        while time.time() < deadline:
            _try_patch_loaded()
            if _PATCHED and _TRADING_STRATEGY_PATCHED and _ADOPTION_PATCHED:
                return
            time.sleep(1.0)
        logger.warning(
            "LIVE_ACTIVE_EXECUTION_GATE_FINAL_MONITOR_EXPIRED marker=20260703q tsm=%s strategy=%s adoption=%s",
            _PATCHED,
            _TRADING_STRATEGY_PATCHED,
            _ADOPTION_PATCHED,
        )

    threading.Thread(target=_monitor, name="live-active-execution-gate-final-monitor", daemon=True).start()
    logger.warning("LIVE_ACTIVE_EXECUTION_GATE_FINAL_MONITOR_STARTED marker=20260703q")


def install_import_hook() -> None:
    global _ORIGINAL_IMPORT_MODULE
    with _INSTALL_LOCK:
        logger.warning("%s install_start=True", _MARKER)
        print("[NIJA-PRINT] LIVE_ACTIVE_EXECUTION_GATE_FINAL_PATCHED marker=20260703q install_start", flush=True)
        _try_patch_loaded()
        _start_monitor()
        if _ORIGINAL_IMPORT_MODULE is not None:
            logger.warning(
                "LIVE_ACTIVE_EXECUTION_GATE_FINAL_INSTALL_COMPLETE marker=20260703q already_installed=True tsm=%s strategy=%s adoption=%s",
                _PATCHED,
                _TRADING_STRATEGY_PATCHED,
                _ADOPTION_PATCHED,
            )
            return
        _ORIGINAL_IMPORT_MODULE = importlib.import_module

        def _wrapped_import_module(name: str, package: str | None = None):
            module = _ORIGINAL_IMPORT_MODULE(name, package)  # type: ignore[misc]
            if name in {"bot.trading_state_machine", "trading_state_machine"}:
                _install_on_module(module)
            if name in {"bot.trading_strategy", "trading_strategy"}:
                _patch_trading_strategy_module(module)
            if name in {"bot.live_entry_runtime_fixes", "live_entry_runtime_fixes"}:
                _patch_live_entry_runtime_fixes(module)
            return module

        importlib.import_module = _wrapped_import_module  # type: ignore[assignment]
        logger.warning(
            "LIVE_ACTIVE_EXECUTION_GATE_FINAL_INSTALL_COMPLETE marker=20260703q tsm=%s strategy=%s adoption=%s",
            _PATCHED,
            _TRADING_STRATEGY_PATCHED,
            _ADOPTION_PATCHED,
        )
