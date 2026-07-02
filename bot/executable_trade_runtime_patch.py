"""Runtime repairs for executable NIJA entries after exchange resizing.

The July 2026 live log proved the scanner can generate entries and capital
authority is ready, but a Kraken entry was resized to the exchange executable
minimum and then rejected by the expectancy gate.  These hooks keep the safety
gate intact while making the executable size and profitability geometry
deterministic before an order can reach broker submission.
"""

from __future__ import annotations

import builtins
import logging
import os
import threading
from functools import wraps
from typing import Any, Optional, Tuple

logger = logging.getLogger("nija.executable_trade_runtime_patch")

_PATCHED_ATTR = "__nija_executable_trade_runtime_patch__"
_TRUTHY = {"1", "true", "yes", "on", "y", "enabled"}
_KRAKEN_UNKNOWN_PAIRS = {
    "AIR-USDT",
    "AIR-USD",
    "AIR/USDT",
    "AIR/USD",
}


def _truthy(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in _TRUTHY


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _set_min_float(name: str, floor: float) -> bool:
    """Set env var to *floor* when missing or configured below it."""
    try:
        current = float(os.environ.get(name, "nan"))
    except (TypeError, ValueError):
        current = float("nan")
    if name not in os.environ or current != current or current < floor:
        os.environ[name] = f"{floor:.2f}".rstrip("0").rstrip(".")
        return True
    return False


def _set_default(name: str, value: str) -> bool:
    if not str(os.environ.get(name, "")).strip():
        os.environ[name] = value
        return True
    return False


def _kraken_min_notional() -> float:
    configured = max(
        _float_env("NIJA_KRAKEN_EFFECTIVE_MIN_NOTIONAL_USD", 10.50),
        _float_env("KRAKEN_MIN_NOTIONAL_USD", 0.0),
        _float_env("NIJA_KRAKEN_MICRO_MIN_NOTIONAL_USD", 0.0),
    )
    return max(10.50, configured)


def normalize_execution_profile_env() -> None:
    """Align runtime defaults with the latest executable Kraken profile."""
    kraken_floor = _kraken_min_notional()
    changed = []

    for key in ("KRAKEN_MIN_NOTIONAL_USD", "NIJA_KRAKEN_MICRO_MIN_NOTIONAL_USD"):
        if _set_min_float(key, kraken_floor):
            changed.append(f"{key}>={kraken_floor:.2f}")

    if _truthy("NIJA_APPLY_GLOBAL_EXECUTABLE_MIN_TRADE", True):
        for key in ("MIN_TRADE_USD", "MIN_POSITION_USD", "MIN_NOTIONAL_OVERRIDE"):
            if _set_min_float(key, kraken_floor):
                changed.append(f"{key}>={kraken_floor:.2f}")

    for key, value in (
        ("HF_TAKE_PROFIT_PCT", "1.0"),
        ("NIJA_MICROCAP_TP1_PERCENT", "1.0"),
        ("NIJA_MICROCAP_STOP_LOSS_PERCENT", "0.30"),
        ("MIN_EXPECTANCY_THRESHOLD_PCT", "0.00"),
        ("NIJA_PROFITABILITY_GUARD_ENABLED", "true"),
        # execution_engine uses decimal fractions for these two:
        # 0.010 = 1.0% minimum TP geometry; 0.003 = 0.30% maximum SL geometry.
        ("MIN_TP_PCT", "0.010"),
        ("MAX_SL_PCT", "0.003"),
    ):
        if _set_default(key, value):
            changed.append(f"{key}={value}")

    if changed:
        logger.warning("EXECUTABLE_TRADE_PROFILE_ENV_NORMALIZED %s", ",".join(changed))


def _broker_is_kraken(broker_name: Any) -> bool:
    return "kraken" in str(broker_name or "").lower()


def _patch_minimum_notional_gate(module: Any) -> bool:
    config_cls = getattr(module, "NotionalGateConfig", None)
    gate_cls = getattr(module, "MinimumNotionalGate", None)
    if not isinstance(config_cls, type) or not isinstance(gate_cls, type):
        return False
    if getattr(module, _PATCHED_ATTR, False):
        return True

    original_post_init = getattr(config_cls, "__post_init__", None)
    original_get_min = getattr(config_cls, "get_min_notional_for_broker", None)
    original_validate = getattr(gate_cls, "validate_entry_size", None)

    def __post_init__(self: Any) -> None:
        normalize_execution_profile_env()
        if callable(original_post_init):
            original_post_init(self)
        limits = dict(getattr(self, "broker_specific_limits", {}) or {})
        limits["kraken"] = max(float(limits.get("kraken", 0.0) or 0.0), _kraken_min_notional())
        self.broker_specific_limits = limits

    def get_min_notional_for_broker(self: Any, broker_name: str, balance: float = 0.0) -> float:
        normalize_execution_profile_env()
        if _broker_is_kraken(broker_name):
            # Kraken's exchange minimum is not a policy floor and must not be
            # capped down to the current spendable balance.  If spendable cash is
            # below this value, the caller must reject instead of submitting a
            # below-minimum order that Kraken will refuse.
            legacy = 0.0
            if callable(original_get_min):
                try:
                    legacy = float(original_get_min(self, broker_name, balance=0.0) or 0.0)
                except Exception:
                    legacy = 0.0
            limits = dict(getattr(self, "broker_specific_limits", {}) or {})
            return max(
                _kraken_min_notional(),
                _float_env("MIN_NOTIONAL_OVERRIDE", 0.0),
                float(limits.get("kraken", 0.0) or 0.0),
                legacy,
            )
        if callable(original_get_min):
            return original_get_min(self, broker_name, balance=balance)
        return max(1.0, _float_env("MIN_NOTIONAL_OVERRIDE", _float_env("MIN_TRADE_USD", 10.50)))

    def validate_entry_size(
        self: Any,
        symbol: str,
        size_usd: float,
        is_stop_loss: bool = False,
        broker_name: Optional[str] = None,
        balance: float = 0.0,
    ):
        normalize_execution_profile_env()
        if broker_name and _broker_is_kraken(broker_name):
            floor = self.config.get_min_notional_for_broker(broker_name, balance=balance)
            if float(size_usd or 0.0) < floor:
                return (
                    False,
                    f"Entry size ${float(size_usd or 0.0):.2f} below Kraken executable minimum ${floor:.2f} USD",
                )
            return True, None
        if callable(original_validate):
            return original_validate(self, symbol, size_usd, is_stop_loss, broker_name, balance)
        return True, None

    setattr(config_cls, "__post_init__", __post_init__)
    setattr(config_cls, "get_min_notional_for_broker", get_min_notional_for_broker)
    setattr(gate_cls, "validate_entry_size", validate_entry_size)

    try:
        setattr(module, "_default_gate", None)
    except Exception:
        pass

    setattr(module, _PATCHED_ATTR, True)
    logger.warning("EXECUTABLE_MIN_NOTIONAL_GATE_PATCHED kraken_floor=%.2f", _kraken_min_notional())
    return True


def _patch_execution_engine(module: Any) -> bool:
    engine_cls = getattr(module, "ExecutionEngine", None)
    if not isinstance(engine_cls, type):
        return False
    if getattr(engine_cls, _PATCHED_ATTR, False):
        return True

    normalize_execution_profile_env()
    kraken_floor = _kraken_min_notional()

    for attr in ("MIN_TRADE_USD", "MIN_NOTIONAL_USD"):
        try:
            if hasattr(module, attr) and float(getattr(module, attr) or 0.0) < kraken_floor:
                setattr(module, attr, kraken_floor)
        except Exception:
            pass

    original_apply_gate = getattr(engine_cls, "_apply_minimum_notional_gate", None)

    if callable(original_apply_gate):
        @wraps(original_apply_gate)
        def _apply_minimum_notional_gate(
            self: Any,
            *,
            symbol: str,
            position_size: float,
            broker_name: Optional[str],
            balance_usd: float,
            affordable_usd: Optional[float],
        ) -> Tuple[Optional[float], Optional[str]]:
            normalize_execution_profile_env()
            if _broker_is_kraken(broker_name):
                floor = _kraken_min_notional()
                size = float(position_size or 0.0)
                affordable = None if affordable_usd is None else float(affordable_usd or 0.0)
                if size < floor:
                    if affordable is not None and affordable < floor:
                        return (
                            None,
                            f"Kraken executable minimum ${floor:.2f} exceeds spendable ${affordable:.2f}; refusing below-minimum order",
                        )
                    logger.info(
                        "📏 Kraken executable minimum resize: $%.2f -> $%.2f before expectancy gate",
                        size,
                        floor,
                    )
                    return floor, None
            return original_apply_gate(
                self,
                symbol=symbol,
                position_size=position_size,
                broker_name=broker_name,
                balance_usd=balance_usd,
                affordable_usd=affordable_usd,
            )

        setattr(engine_cls, "_apply_minimum_notional_gate", _apply_minimum_notional_gate)

    original_rejection = getattr(engine_cls, "_log_execute_entry_rejection", None)
    if callable(original_rejection):
        @wraps(original_rejection)
        def _log_execute_entry_rejection(self: Any, *args: Any, **kwargs: Any) -> Any:
            stage = kwargs.get("stage", "")
            reason = kwargs.get("reason", "")
            result = original_rejection(self, *args, **kwargs)
            if stage == "expectancy_gate" and reason == "non_positive_expectancy":
                logger.warning(
                    "EXECUTABLE_EXPECTANCY_REJECT_CONFIRMED symbol=%s size=$%.2f "
                    "meaning=setup_was_sized_to_executable_notional_but_failed_positive_EV_math",
                    kwargs.get("symbol", "unknown"),
                    float(kwargs.get("position_size", 0.0) or 0.0),
                )
            return result

        setattr(engine_cls, "_log_execute_entry_rejection", _log_execute_entry_rejection)

    setattr(engine_cls, _PATCHED_ATTR, True)
    logger.warning("EXECUTABLE_EXECUTION_ENGINE_PATCHED kraken_floor=%.2f", kraken_floor)
    return True


def _patch_live_entry_quarantine(module: Any) -> bool:
    unknown_pairs = getattr(module, "_UNKNOWN_PAIRS", None)
    if not isinstance(unknown_pairs, set):
        return False
    before = len(unknown_pairs)
    for pair in _KRAKEN_UNKNOWN_PAIRS:
        unknown_pairs.add(("kraken", pair.upper()))
    if len(unknown_pairs) != before:
        logger.warning("EXECUTABLE_PAIR_QUARANTINE_ADDED broker=kraken pairs=%s", sorted(_KRAKEN_UNKNOWN_PAIRS))
    return True


def _patch_kraken_symbol_support(module: Any) -> bool:
    patched = False
    for value in list(vars(module).values()):
        if not isinstance(value, type):
            continue
        class_name = getattr(value, "__name__", "").lower()
        if "kraken" not in class_name:
            continue
        original = getattr(value, "supports_symbol", None)
        if not callable(original) or getattr(original, _PATCHED_ATTR, False):
            continue

        @wraps(original)
        def supports_symbol(self: Any, symbol: Any, *args: Any, __orig=original, **kwargs: Any) -> bool:
            sym = str(symbol or "").upper().replace("_", "-")
            if sym in _KRAKEN_UNKNOWN_PAIRS:
                logger.info("PAIR_SKIPPED_UNKNOWN broker=kraken pair=%s reason=static_runtime_quarantine", sym)
                return False
            return bool(__orig(self, symbol, *args, **kwargs))

        setattr(supports_symbol, _PATCHED_ATTR, True)
        setattr(value, "supports_symbol", supports_symbol)
        patched = True
    if patched:
        logger.warning("EXECUTABLE_KRAKEN_SYMBOL_SUPPORT_PATCHED")
    return patched


def _patch_core_loop(module: Any) -> bool:
    if getattr(module, f"{_PATCHED_ATTR}_core", False):
        return True

    original_run = getattr(module, "run_trading_loop", None)
    if callable(original_run):
        @wraps(original_run)
        def run_trading_loop(strategy: Any, cycle_secs: int = 150) -> None:
            if bool(getattr(module, "_loop_running", False)) or bool(getattr(module, "_nija_loop_starting", False)):
                logger.info(
                    "Trading loop already active; skipping duplicate start "
                    "(_loop_running=%s _nija_loop_starting=%s)",
                    getattr(module, "_loop_running", False),
                    getattr(module, "_nija_loop_starting", False),
                )
                return None
            setattr(module, "_nija_loop_starting", True)
            try:
                return original_run(strategy, cycle_secs=cycle_secs)
            finally:
                if not bool(getattr(module, "_loop_running", False)):
                    setattr(module, "_nija_loop_starting", False)

        setattr(module, "run_trading_loop", run_trading_loop)

    original_start = getattr(module, "start_trading_engine", None)
    if callable(original_start):
        @wraps(original_start)
        def start_trading_engine(strategy: Any) -> threading.Thread:
            active_thread = getattr(module, "_nija_active_trading_thread", None)
            if (
                bool(getattr(module, "_loop_running", False))
                or bool(getattr(module, "_nija_loop_starting", False))
            ):
                logger.info(
                    "Trading loop already active; skipping duplicate thread spawn "
                    "(_loop_running=%s _nija_loop_starting=%s)",
                    getattr(module, "_loop_running", False),
                    getattr(module, "_nija_loop_starting", False),
                )
                if isinstance(active_thread, threading.Thread):
                    return active_thread
                return threading.current_thread()
            thread = original_start(strategy)
            setattr(module, "_nija_active_trading_thread", thread)
            return thread

        setattr(module, "start_trading_engine", start_trading_engine)

    setattr(module, f"{_PATCHED_ATTR}_core", True)
    logger.warning("EXECUTABLE_CORE_LOOP_DUPLICATE_START_PATCHED")
    return True


def _patch_module(name: str, module: Any) -> None:
    if module is None:
        return
    try:
        if name.endswith("minimum_notional_gate"):
            _patch_minimum_notional_gate(module)
        if name.endswith("execution_engine"):
            _patch_execution_engine(module)
        if name.endswith("live_entry_runtime_fixes"):
            _patch_live_entry_quarantine(module)
        if name.endswith("nija_core_loop"):
            _patch_core_loop(module)
        if "kraken" in name.lower():
            _patch_kraken_symbol_support(module)
    except Exception as exc:
        logger.warning("Executable trade runtime patch failed for %s: %s", name, exc)


def install_import_hook() -> None:
    if not _truthy("NIJA_EXECUTABLE_TRADE_RUNTIME_PATCH", True):
        logger.warning("EXECUTABLE_TRADE_RUNTIME_PATCH_DISABLED")
        return

    normalize_execution_profile_env()

    import sys

    for name, module in list(sys.modules.items()):
        if name.endswith(("minimum_notional_gate", "execution_engine", "live_entry_runtime_fixes", "nija_core_loop")) or "kraken" in name.lower():
            _patch_module(name, module)

    if getattr(builtins, "_NIJA_EXECUTABLE_TRADE_PATCH_HOOK_INSTALLED", False):
        return

    original_import = builtins.__import__

    def guarded_import(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
        module = original_import(name, globals, locals, fromlist, level)
        try:
            targets = ("minimum_notional_gate", "execution_engine", "live_entry_runtime_fixes", "nija_core_loop")
            if name.endswith(targets) or "kraken" in name.lower():
                _patch_module(name, module)
            for loaded_name, loaded_module in list(sys.modules.items()):
                if loaded_name.endswith(targets) or "kraken" in loaded_name.lower():
                    _patch_module(loaded_name, loaded_module)
        except Exception as exc:
            logger.warning("Executable trade runtime import hook failed for %s: %s", name, exc)
        return module

    builtins.__import__ = guarded_import
    setattr(builtins, "_NIJA_EXECUTABLE_TRADE_PATCH_HOOK_INSTALLED", True)
    logger.warning("EXECUTABLE_TRADE_RUNTIME_PATCH_INSTALL_COMPLETE kraken_floor=%.2f", _kraken_min_notional())
