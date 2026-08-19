from __future__ import annotations

import importlib
import logging
import os
import re
import sys
import threading
import time
from types import MappingProxyType, ModuleType
from typing import Any, Callable, Dict, Optional, Tuple

logger = logging.getLogger("nija.trading_state_dispatch_latch_repair")
_ORIGINAL_IMPORT_MODULE: Optional[Callable[..., Any]] = None
_PATCHED = False
_KILL_SWITCH_PATCHED = False
_CORE_LOOP_PATCHED = False
_LEASE_GENERATION_PATCHED = False
_CAPITAL_AUTHORITY_PATCHED = False
_STARTUP_COORDINATOR_PATCHED = False
_MONITOR_STARTED = False
_INSTALL_LOCK = threading.Lock()
_LOG_THROTTLE_LOCK = threading.Lock()
_LOG_THROTTLE_STATE: Dict[str, Tuple[str, float, int]] = {}
_VALID_TRADING_STATES = {
    "OFF",
    "DRY_RUN",
    "LIVE_PENDING_CONFIRMATION",
    "LIVE_ACTIVE",
    "EMERGENCY_STOP",
}


def _truthy(name: str, default: str = "") -> bool:
    return str(os.environ.get(name, default)).strip().lower() in {
        "1", "true", "yes", "enabled", "on", "y"
    }


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)) or default)
    except Exception:
        return default


def _emit_throttled(
    key: str,
    signature: str,
    message: str,
    *args: Any,
    level: int = logging.CRITICAL,
    interval_s: Optional[float] = None,
) -> None:
    interval = float(
        interval_s
        if interval_s is not None
        else _float_env("NIJA_PATCH_LOG_THROTTLE_S", 30.0)
    )
    now = time.monotonic()
    suppressed = 0
    with _LOG_THROTTLE_LOCK:
        last_sig, last_ts, last_suppressed = _LOG_THROTTLE_STATE.get(
            key, ("", 0.0, 0)
        )
        if signature == last_sig and (now - last_ts) < interval:
            _LOG_THROTTLE_STATE[key] = (
                last_sig, last_ts, last_suppressed + 1
            )
            return
        suppressed = last_suppressed
        _LOG_THROTTLE_STATE[key] = (signature, now, 0)
    if suppressed:
        logger.info(
            "NIJA_PATCH_LOG_THROTTLED key=%s signature=%s suppressed=%d",
            key,
            signature,
            suppressed,
        )
    logger.log(level, message, *args)


def _current_state_value(sm: Any) -> str:
    try:
        cur = getattr(sm, "get_current_state", lambda: None)()
        return str(getattr(cur, "value", cur) or "unknown").upper()
    except Exception:
        return "UNKNOWN"


def _canonical_trading_state(incoming: Any) -> str:
    """Replace only invalid/UNKNOWN input with canonical runtime state."""
    normalized = str(getattr(incoming, "value", incoming) or "").strip().upper()
    if normalized in _VALID_TRADING_STATES:
        return normalized

    env_state = str(os.environ.get("NIJA_RUNTIME_TRADING_STATE", "")).strip().upper()
    if env_state in _VALID_TRADING_STATES:
        return env_state

    for module_name in ("bot.trading_state_machine", "trading_state_machine"):
        module = sys.modules.get(module_name)
        if not isinstance(module, ModuleType):
            continue
        getter = getattr(module, "get_trading_state_machine", None)
        if callable(getter):
            try:
                state = _current_state_value(getter())
                if state in _VALID_TRADING_STATES:
                    return state
            except Exception:
                pass
        singleton = getattr(module, "trading_state_machine", None)
        if singleton is not None:
            state = _current_state_value(singleton)
            if state in _VALID_TRADING_STATES:
                return state

    return normalized or "OFF"


def _capital_probe() -> Dict[str, Any]:
    detail: Dict[str, Any] = {
        "hydrated": False,
        "first_snap": False,
        "valid_brokers": 0,
        "registered_brokers": 0,
        "expected_brokers": 1,
        "brokers_complete": False,
        "real": 0.0,
        "usable": 0.0,
        "fresh": False,
        "source": "unavailable",
    }
    try:
        try:
            from bot.capital_authority import get_capital_authority
        except ImportError:
            from capital_authority import get_capital_authority  # type: ignore[import]
        ca = get_capital_authority()
        detail["source"] = "capital_authority"
        detail["hydrated"] = bool(getattr(ca, "is_hydrated", False))
        detail["first_snap"] = bool(
            getattr(ca, "first_snap_accepted", False)
            or getattr(ca, "_first_snap_accepted", False)
            or getattr(ca, "first_snapshot_accepted", False)
        )
        try:
            detail["valid_brokers"] = int(
                getattr(ca, "valid_broker_count", 0) or 0
            )
        except Exception:
            pass
        try:
            detail["registered_brokers"] = int(
                getattr(ca, "registered_broker_count", 0) or 0
            )
        except Exception:
            pass
        try:
            detail["expected_brokers"] = max(
                1, int(getattr(ca, "expected_brokers", 1) or 1)
            )
        except Exception:
            pass
        complete_getter = getattr(ca, "is_brokers_complete", None)
        if callable(complete_getter):
            try:
                detail["brokers_complete"] = bool(complete_getter())
            except Exception:
                pass
        else:
            detail["brokers_complete"] = bool(
                int(detail["registered_brokers"])
                >= int(detail["expected_brokers"])
            )

        for method_name, target in (
            ("get_real_capital", "real"),
            ("get_usable_capital", "usable"),
        ):
            getter = getattr(ca, method_name, None)
            if callable(getter):
                try:
                    detail[target] = float(getter() or 0.0)
                except Exception:
                    pass
        fresh_getter = getattr(ca, "is_fresh", None)
        if callable(fresh_getter):
            try:
                detail["fresh"] = bool(fresh_getter(ttl_s=180.0))
            except TypeError:
                detail["fresh"] = bool(fresh_getter())
            except Exception:
                detail["fresh"] = False
    except Exception as exc:
        detail["source"] = f"capital_authority_error:{exc}"

    if float(detail["usable"]) <= 0.0 and float(detail["real"]) > 0.0:
        detail["usable"] = float(detail["real"])
    return detail


def _kill_switch_clear() -> bool:
    try:
        try:
            from bot.kill_switch import get_kill_switch
        except ImportError:
            from kill_switch import get_kill_switch  # type: ignore[import]
        return not bool(get_kill_switch().is_active())
    except Exception:
        return True


def _capital_ready() -> tuple[bool, str]:
    try:
        probe = _capital_probe()
        hydrated = bool(probe["hydrated"])
        valid_brokers = int(probe["valid_brokers"] or 0)
        registered = int(probe["registered_brokers"] or 0)
        expected = max(1, int(probe["expected_brokers"] or 1))
        complete = bool(probe["brokers_complete"] and registered >= expected)
        real = float(probe["real"] or 0.0)
        usable = float(probe["usable"] or 0.0)
        fresh = bool(probe["fresh"])
        ok = bool(
            hydrated
            and complete
            and valid_brokers > 0
            and real > 0.0
            and usable > 0.0
            and fresh
        )
        return ok, (
            f"hydrated={hydrated} complete={complete} "
            f"registered_brokers={registered} expected_brokers={expected} "
            f"valid_brokers={valid_brokers} real={real:.2f} usable={usable:.2f} "
            f"fresh={fresh} source={probe.get('source')}"
        )
    except Exception as exc:
        return False, f"capital_probe_failed:{exc}"


def _strict_live_dispatch_ready(sm: Any) -> tuple[bool, str]:
    state = _current_state_value(sm)
    if state != "LIVE_ACTIVE":
        return False, f"state_not_live_active:{state}"
    if not _truthy("LIVE_CAPITAL_VERIFIED"):
        return False, "live_capital_not_verified"
    if _truthy("DRY_RUN_MODE") or _truthy("PAPER_MODE"):
        return False, "simulation_mode"
    if not _truthy("NIJA_RUNTIME_EXECUTION_AUTHORITY"):
        return False, "runtime_execution_authority_missing"
    if not str(os.environ.get("NIJA_WRITER_FENCING_TOKEN", "")).strip():
        return False, "writer_fencing_token_missing"
    if not str(os.environ.get("NIJA_WRITER_LEASE_GENERATION", "")).strip():
        return False, "writer_lease_generation_missing"
    if not _kill_switch_clear():
        return False, "kill_switch_active"
    cap_ok, cap_detail = _capital_ready()
    if not cap_ok:
        return False, cap_detail
    return True, f"strict_live_dispatch_ready state={state} {cap_detail}"


def _install_kill_switch_patch_on_module(module: ModuleType) -> bool:
    global _KILL_SWITCH_PATCHED
    cls = getattr(module, "KillSwitch", None)
    if not isinstance(cls, type):
        return False
    original = getattr(cls, "_check_file_activation", None)
    if not callable(original):
        return False
    if getattr(original, "_nija_kill_switch_file_log_throttle_wrapped", False):
        _KILL_SWITCH_PATCHED = True
        return True

    def _patched_check_file_activation(self: Any, *args: Any, **kwargs: Any) -> Any:
        kill_file = str(getattr(self, "_kill_file", "") or "")
        try:
            exists = bool(kill_file and os.path.exists(kill_file))
        except Exception:
            exists = False
        if not exists:
            return None
        active_before = bool(getattr(self, "_is_active", False))
        _emit_throttled(
            "kill_switch_file_detected",
            f"{kill_file}:active={active_before}",
            "Kill switch file detected: %s active=%s",
            kill_file,
            active_before,
            level=logging.WARNING,
            interval_s=_float_env("NIJA_KILL_SWITCH_LOG_THROTTLE_S", 60.0),
        )
        if not active_before:
            activate = getattr(self, "_activate_internal", None)
            if callable(activate):
                return activate("Kill switch file detected", "FILE_SYSTEM")
        return None

    setattr(_patched_check_file_activation, "_nija_kill_switch_file_log_throttle_wrapped", True)
    setattr(cls, "_check_file_activation", _patched_check_file_activation)
    _KILL_SWITCH_PATCHED = True
    logger.warning("KILL_SWITCH_FILE_LOG_THROTTLE_PATCHED module=%s", module.__name__)
    return True


def _install_core_loop_patch_on_module(module: ModuleType) -> bool:
    global _CORE_LOOP_PATCHED
    original = getattr(module, "_capture_cycle_capital_state", None)
    if not callable(original):
        return False
    if getattr(original, "_nija_cycle_capital_normalizer_wrapped", False):
        _CORE_LOOP_PATCHED = True
        return True

    def _patched_capture_cycle_capital_state(*args: Any, **kwargs: Any):
        snapshot = original(*args, **kwargs)
        try:
            result = dict(snapshot or {})
        except Exception:
            return snapshot
        try:
            probe = _capital_probe()
            real = float(probe.get("real", 0.0) or 0.0)
            registered = int(probe.get("registered_brokers", 0) or 0)
            expected = max(1, int(probe.get("expected_brokers", 1) or 1))
            complete = bool(probe.get("brokers_complete") and registered >= expected)
            changed = False
            if real > 0.0 and float(result.get("ca_total_capital", 0.0) or 0.0) <= 0.0:
                result["ca_total_capital"] = real
                result["ca_is_hydrated"] = bool(probe.get("hydrated"))
                result["is_post_hydration"] = bool(probe.get("hydrated"))
                result["snapshot_source"] = "capital_authority"
                changed = True

            ca_valid = int(probe.get("valid_brokers", 0) or 0)
            if int(result.get("ca_valid_brokers", 0) or 0) != ca_valid:
                result["ca_valid_brokers"] = ca_valid
                changed = True
            if bool(result.get("aggregation_normalized", False)) != complete:
                result["aggregation_normalized"] = complete
                changed = True

            if changed:
                _emit_throttled(
                    "cycle_capital_snapshot_repaired",
                    f"{result.get('ca_total_capital')}:{registered}/{expected}:{complete}",
                    "CYCLE_CAPITAL_SNAPSHOT_REPAIRED total=%.8f registered=%d expected=%d complete=%s probe=%s",
                    float(result.get("ca_total_capital", 0.0) or 0.0),
                    registered,
                    expected,
                    complete,
                    probe,
                    interval_s=_float_env("NIJA_CAPITAL_REPAIR_LOG_THROTTLE_S", 30.0),
                )
                return MappingProxyType(result)
        except Exception as exc:
            logger.debug("cycle capital normalizer failed: %s", exc)
        return snapshot

    setattr(_patched_capture_cycle_capital_state, "_nija_cycle_capital_normalizer_wrapped", True)
    setattr(module, "_capture_cycle_capital_state", _patched_capture_cycle_capital_state)
    _CORE_LOOP_PATCHED = True
    logger.warning("CYCLE_CAPITAL_NORMALIZER_PATCHED module=%s", module.__name__)
    return True


def _install_capital_authority_patch_on_module(module: ModuleType) -> bool:
    global _CAPITAL_AUTHORITY_PATCHED
    cls = getattr(module, "CapitalAuthority", None)
    if not isinstance(cls, type):
        return False
    original = getattr(cls, "publish_snapshot", None)
    if not callable(original):
        return False
    if getattr(original, "_nija_complete_snapshot_regression_guard_wrapped", False):
        _CAPITAL_AUTHORITY_PATCHED = True
        return True

    def _patched_publish_snapshot(self: Any, snapshot: Any, writer_id: str) -> bool:
        try:
            incoming_balances = dict(getattr(snapshot, "broker_balances", {}) or {})
            incoming_count = len(incoming_balances)
            expected = max(1, int(getattr(self, "expected_brokers", 1) or 1))
            current_balances = dict(getattr(self, "_broker_balances", {}) or {})
            current_count = len(current_balances)
            fresh_getter = getattr(self, "is_fresh", None)
            current_fresh = bool(fresh_getter()) if callable(fresh_getter) else False
            if (
                incoming_count < expected
                and current_count >= expected
                and current_fresh
            ):
                logger.critical(
                    "CAPITAL_PARTIAL_SNAPSHOT_REGRESSION_REJECTED incoming=%d expected=%d current=%d writer_id=%s state_preserved=true",
                    incoming_count,
                    expected,
                    current_count,
                    writer_id,
                )
                return False
        except Exception as exc:
            logger.warning("capital partial-snapshot guard probe failed: %s", exc)
        return bool(original(self, snapshot, writer_id))

    setattr(_patched_publish_snapshot, "_nija_complete_snapshot_regression_guard_wrapped", True)
    setattr(cls, "publish_snapshot", _patched_publish_snapshot)
    _CAPITAL_AUTHORITY_PATCHED = True
    logger.warning("CAPITAL_PARTIAL_SNAPSHOT_REGRESSION_GUARD_PATCHED module=%s", module.__name__)
    return True


def _install_startup_coordinator_patch_on_module(module: ModuleType) -> bool:
    global _STARTUP_COORDINATOR_PATCHED
    cls = getattr(module, "StartupCoordinator", None)
    if not isinstance(cls, type):
        return False
    original = getattr(cls, "build_snapshot", None)
    if not callable(original):
        return False
    if getattr(original, "_nija_canonical_trading_state_input_wrapped", False):
        _STARTUP_COORDINATOR_PATCHED = True
        return True

    def _patched_build_snapshot(
        self: Any, *, trading_state: str, activation_intent: bool
    ) -> Any:
        canonical = _canonical_trading_state(trading_state)
        incoming = str(getattr(trading_state, "value", trading_state) or "").strip().upper()
        if canonical != incoming:
            _emit_throttled(
                "startup_trading_state_canonicalized",
                f"{incoming}->{canonical}",
                "STARTUP_TRADING_STATE_CANONICALIZED incoming=%s canonical=%s",
                incoming or "<empty>",
                canonical,
                level=logging.WARNING,
                interval_s=30.0,
            )
        return original(
            self,
            trading_state=canonical,
            activation_intent=bool(activation_intent),
        )

    setattr(_patched_build_snapshot, "_nija_canonical_trading_state_input_wrapped", True)
    setattr(cls, "build_snapshot", _patched_build_snapshot)
    _STARTUP_COORDINATOR_PATCHED = True
    logger.warning("STARTUP_CANONICAL_TRADING_STATE_PATCHED module=%s", module.__name__)
    return True


def _install_lease_generation_patch_on_module(module: ModuleType) -> bool:
    global _LEASE_GENERATION_PATCHED
    original = getattr(module, "_writer_lease_generation_gate", None)
    if not callable(original):
        return False
    if getattr(original, "_nija_lease_generation_regression_repair_wrapped", False):
        _LEASE_GENERATION_PATCHED = True
        return True

    def _patched_writer_lease_generation_gate(*args: Any, **kwargs: Any) -> tuple[bool, str]:
        ok, detail = original(*args, **kwargs)
        if ok or not str(detail or "").startswith("lease_generation_regression"):
            return ok, detail
        if not _truthy("NIJA_AUTO_REPAIR_LEASE_GENERATION_REGRESSION", "true"):
            return ok, detail
        match = re.search(r"prev=(\d+)\s+current=(\d+)", str(detail or ""))
        if not match:
            return ok, detail
        prev = int(match.group(1))
        current = int(match.group(2))
        if current <= 0:
            return ok, detail
        expected_raw = os.environ.get("NIJA_WRITER_LEASE_GENERATION_EXPECTED", "").strip()
        if expected_raw and expected_raw != str(current):
            os.environ.pop("NIJA_WRITER_LEASE_GENERATION_EXPECTED", None)
        os.environ["NIJA_WRITER_LEASE_GENERATION"] = str(current)
        os.environ["NIJA_WRITER_LEASE_GENERATION_LAST"] = str(current)
        _emit_throttled(
            "lease_generation_regression_repaired",
            f"{prev}->{current}",
            "LEASE_GENERATION_REGRESSION_REPAIRED prev=%d current=%d expected_cleared=%s",
            prev,
            current,
            bool(expected_raw and expected_raw != str(current)),
        )
        try:
            return original(*args, **kwargs)
        except Exception as exc:
            return False, f"lease_generation_recheck_failed_after_repair:{exc}"

    setattr(_patched_writer_lease_generation_gate, "_nija_lease_generation_regression_repair_wrapped", True)
    setattr(module, "_writer_lease_generation_gate", _patched_writer_lease_generation_gate)
    _LEASE_GENERATION_PATCHED = True
    logger.warning("LEASE_GENERATION_REGRESSION_REPAIR_PATCHED module=%s", module.__name__)
    return True


def _install_on_module(module: ModuleType) -> bool:
    global _PATCHED
    _install_lease_generation_patch_on_module(module)
    cls = getattr(module, "TradingStateMachine", None)
    if not isinstance(cls, type):
        return False
    original = getattr(cls, "can_dispatch_trades", None)
    if not callable(original):
        return False
    if getattr(original, "_nija_trading_state_dispatch_latch_repair_wrapped", False):
        _PATCHED = True
        return True

    def _patched_can_dispatch_trades(self: Any, *args: Any, **kwargs: Any) -> bool:
        try:
            if bool(original(self, *args, **kwargs)):
                return True
        except Exception as exc:
            logger.warning(
                "TRADING_STATE_DISPATCH_LATCH_REPAIR original_can_dispatch_failed err=%s",
                exc,
            )
        ready, detail = _strict_live_dispatch_ready(self)
        if ready:
            try:
                setattr(self, "_activation_committed", True)
                setattr(self, "_execution_authority", True)
                setattr(self, "_core_loop_owns_execution", False)
                setattr(self, "_can_dispatch_trades", True)
            except Exception:
                pass
            logger.critical(
                "TRADING_STATE_DISPATCH_LATCH_REPAIR_APPLIED detail=%s token_prefix=%s generation=%s",
                detail,
                os.environ.get("NIJA_WRITER_FENCING_TOKEN", "")[:8],
                os.environ.get("NIJA_WRITER_LEASE_GENERATION", ""),
            )
            return True
        _emit_throttled(
            "trading_state_dispatch_latch_waiting",
            str(detail),
            "TRADING_STATE_DISPATCH_LATCH_REPAIR_WAITING detail=%s",
            detail,
            interval_s=_float_env("NIJA_DISPATCH_LATCH_WAIT_LOG_THROTTLE_S", 30.0),
        )
        return False

    setattr(_patched_can_dispatch_trades, "_nija_trading_state_dispatch_latch_repair_wrapped", True)
    setattr(cls, "can_dispatch_trades", _patched_can_dispatch_trades)
    _PATCHED = True
    logger.warning("TRADING_STATE_DISPATCH_LATCH_REPAIR_PATCHED module=%s", module.__name__)
    return True


def _try_patch_loaded() -> bool:
    patched = False
    for name in ("bot.trading_state_machine", "trading_state_machine"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            patched = _install_on_module(module) or patched
    for name in ("bot.kill_switch", "kill_switch"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            _install_kill_switch_patch_on_module(module)
    for name in ("bot.nija_core_loop", "nija_core_loop"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            _install_core_loop_patch_on_module(module)
    for name in ("bot.capital_authority", "capital_authority"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            _install_capital_authority_patch_on_module(module)
    for name in ("bot.startup_coordinator", "startup_coordinator"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            _install_startup_coordinator_patch_on_module(module)
    return patched


def _all_patches_ready() -> bool:
    return bool(
        _PATCHED
        and _KILL_SWITCH_PATCHED
        and _CORE_LOOP_PATCHED
        and _LEASE_GENERATION_PATCHED
        and _CAPITAL_AUTHORITY_PATCHED
        and _STARTUP_COORDINATOR_PATCHED
    )


def _start_monitor() -> None:
    global _MONITOR_STARTED
    if _MONITOR_STARTED:
        return
    _MONITOR_STARTED = True

    def _monitor() -> None:
        deadline = time.time() + float(
            os.environ.get("NIJA_PATCH_MONITOR_SECONDS", "240") or "240"
        )
        while time.time() < deadline:
            _try_patch_loaded()
            if _all_patches_ready():
                return
            time.sleep(0.25)
        logger.warning(
            "TRADING_STATE_DISPATCH_LATCH_REPAIR_MONITOR_EXPIRED trading=%s kill=%s core=%s lease=%s capital=%s startup=%s",
            _PATCHED,
            _KILL_SWITCH_PATCHED,
            _CORE_LOOP_PATCHED,
            _LEASE_GENERATION_PATCHED,
            _CAPITAL_AUTHORITY_PATCHED,
            _STARTUP_COORDINATOR_PATCHED,
        )

    threading.Thread(
        target=_monitor,
        name="trading-state-dispatch-latch-repair-monitor",
        daemon=True,
    ).start()
    logger.warning("TRADING_STATE_DISPATCH_LATCH_REPAIR_MONITOR_STARTED")


def install_import_hook() -> None:
    global _ORIGINAL_IMPORT_MODULE
    with _INSTALL_LOCK:
        _try_patch_loaded()
        _start_monitor()
        if _ORIGINAL_IMPORT_MODULE is not None:
            logger.warning(
                "TRADING_STATE_DISPATCH_LATCH_REPAIR_INSTALL_COMPLETE already_installed=True all_ready=%s",
                _all_patches_ready(),
            )
            return
        _ORIGINAL_IMPORT_MODULE = importlib.import_module

        def _wrapped_import_module(name: str, package: str | None = None):
            module = _ORIGINAL_IMPORT_MODULE(name, package)  # type: ignore[misc]
            if name in {"bot.trading_state_machine", "trading_state_machine"}:
                _install_on_module(module)
            elif name in {"bot.kill_switch", "kill_switch"}:
                _install_kill_switch_patch_on_module(module)
            elif name in {"bot.nija_core_loop", "nija_core_loop"}:
                _install_core_loop_patch_on_module(module)
            elif name in {"bot.capital_authority", "capital_authority"}:
                _install_capital_authority_patch_on_module(module)
            elif name in {"bot.startup_coordinator", "startup_coordinator"}:
                _install_startup_coordinator_patch_on_module(module)
            return module

        importlib.import_module = _wrapped_import_module  # type: ignore[assignment]
        logger.warning(
            "TRADING_STATE_DISPATCH_LATCH_REPAIR_INSTALL_COMPLETE all_ready=%s trading=%s kill=%s core=%s lease=%s capital=%s startup=%s",
            _all_patches_ready(),
            _PATCHED,
            _KILL_SWITCH_PATCHED,
            _CORE_LOOP_PATCHED,
            _LEASE_GENERATION_PATCHED,
            _CAPITAL_AUTHORITY_PATCHED,
            _STARTUP_COORDINATOR_PATCHED,
        )
