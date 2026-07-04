"""Final live-execution runtime hardening.

This overlay is intentionally loaded after the July 4 runtime repair hooks.  It
turns the fixed Kraken quote floor into a pair-aware minimum so symbols such as
SOLUSD, whose exchange rule is a minimum *base* amount, are either lifted to an
executable size or skipped before broker submission.  It also keeps platform
execution capital separated from user-account reporting capital and prevents
warm supervisor paths from resetting readiness after the trading loop is already
LIVE_ACTIVE.
"""

from __future__ import annotations

import builtins
import logging
import os
import sys
from dataclasses import replace
from decimal import Decimal, InvalidOperation, ROUND_UP
from types import ModuleType
from typing import Any, Callable, Optional

logger = logging.getLogger("nija.live_execution_runtime_hardening")

_ORIGINAL_IMPORT: Optional[Callable[..., Any]] = None
_PATCHED: set[tuple[str, int]] = set()
_CENT = Decimal("0.01")
_VOL_STEP = Decimal("0.00000001")
_TRUTHY = {"1", "true", "yes", "on", "y", "enabled"}

# Static fallback only applies when Kraken metadata cannot be read from the
# validator module.  The validator's live pair metadata remains authoritative.
_KRAKEN_FALLBACK_MIN_BASE: dict[str, Decimal] = {
    # Observed live failure 2026-07-04: SOLUSD requires 0.5 SOL minimum volume.
    "SOL": Decimal("0.5"),
}


def _truthy(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in _TRUTHY


def _decimal(value: Any, default: Decimal = Decimal("0")) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return default


def _round_usd_up(value: Any) -> Decimal:
    d = _decimal(value)
    return (d / _CENT).to_integral_value(rounding=ROUND_UP) * _CENT


def _round_volume_up(value: Decimal, step: Decimal = _VOL_STEP) -> Decimal:
    step = step if step > 0 else _VOL_STEP
    return (value / step).to_integral_value(rounding=ROUND_UP) * step


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except Exception:
        return default


def _set_env_value(name: str, value: str) -> None:
    current = os.environ.get(name)
    if current != value:
        os.environ[name] = value


def _set_env_cap(name: str, cap: float) -> None:
    try:
        current = float(os.environ.get(name, cap))
    except Exception:
        current = cap
    if name not in os.environ or current > cap:
        os.environ[name] = f"{cap:.2f}".rstrip("0").rstrip(".")
        logger.warning("GLOBAL_POLICY_MIN_NOTIONAL_RESTORED %s %.2f -> %.2f", name, current, cap)


def normalize_live_execution_env() -> None:
    """Keep global policy floors small and let Kraken pair rules be authoritative."""
    if not _truthy("NIJA_LIVE_EXECUTION_HARDENING_ENABLED", True):
        return

    _set_env_value("NIJA_KRAKEN_PAIR_AWARE_MINIMUMS", "true")
    _set_env_value("NIJA_PLATFORM_EXECUTION_CAPITAL_ONLY", "true")
    _set_env_value("NIJA_AGGREGATE_USER_CAPITAL_IN_AUTHORITY", "false")
    _set_env_value("NIJA_APPLY_GLOBAL_EXECUTABLE_MIN_TRADE", "false")

    # Global policy floors must not masquerade as exchange rules.  Kraken still
    # gets its pair-specific hard minimum in the final validator/compiler layer.
    policy_floor = max(1.0, _float_env("NIJA_MICRO_CAP_MIN_TRADE_USD", 10.0))
    for key in ("MIN_TRADE_USD", "MIN_POSITION_USD", "MIN_NOTIONAL_OVERRIDE"):
        _set_env_cap(key, policy_floor)


def _module_key(module: ModuleType) -> tuple[str, int]:
    return (str(getattr(module, "__name__", "<unknown>")), id(module))


def _is_kraken(value: Any) -> bool:
    return "kraken" in str(value or "").strip().lower()


def _symbol_text(symbol: Any) -> str:
    return str(symbol or "").strip().upper().replace("/", "-").replace("_", "-")


def _base_asset(symbol: Any) -> str:
    s = _symbol_text(symbol)
    if "-" in s:
        base = s.split("-", 1)[0]
    elif s.endswith("USDT"):
        base = s[:-4]
    elif s.endswith("USDC"):
        base = s[:-4]
    elif s.endswith("USD"):
        base = s[:-3]
    else:
        base = s
    if base in {"XBT", "XXBT"}:
        return "BTC"
    if base.startswith("X") and len(base) > 3:
        # Kraken often prefixes legacy assets (XETH, XXBT).  Keep normal symbols
        # like XDC unchanged by stripping only the common long legacy form.
        stripped = base[1:]
        if stripped in {"ETH", "BT", "XBT"}:
            return "BTC" if stripped in {"BT", "XBT"} else stripped
    return base


def _extract_price(obj: Any) -> Decimal:
    """Best-effort extraction of a live/mark/last price from compiler inputs."""
    if obj is None:
        return Decimal("0")
    if isinstance(obj, (int, float, str, Decimal)):
        return _decimal(obj)

    keys = (
        "price",
        "last_price",
        "last",
        "mark_price",
        "market_price",
        "current_price",
        "entry_price",
        "ask",
        "bid",
        "mid",
        "close",
        "lastTradePrice",
    )

    if isinstance(obj, dict):
        for key in keys:
            if key in obj:
                price = _decimal(obj.get(key))
                if price > 0:
                    return price
        for nested_key in ("pricing", "market", "ticker", "quote"):
            nested = obj.get(nested_key)
            price = _extract_price(nested)
            if price > 0:
                return price
        return Decimal("0")

    for key in keys:
        if hasattr(obj, key):
            price = _decimal(getattr(obj, key))
            if price > 0:
                return price
    for nested_key in ("pricing", "market", "ticker", "quote"):
        if hasattr(obj, nested_key):
            price = _extract_price(getattr(obj, nested_key))
            if price > 0:
                return price
    return Decimal("0")


def _read_minimum_dict(module: Optional[ModuleType], pair: str) -> tuple[Decimal, Decimal, str]:
    """Return ``(min_base, min_quote, source)`` from Kraken validator metadata."""
    min_base = Decimal("0")
    min_quote = Decimal("0")
    source = "none"

    if module is not None:
        for fn_name in ("get_pair_minimums", "get_pair_safe_minimums"):
            fn = getattr(module, fn_name, None)
            if not callable(fn):
                continue
            try:
                data = fn(pair)
            except Exception as exc:
                logger.debug("PAIR_MIN_METADATA_READ_FAILED fn=%s pair=%s err=%s", fn_name, pair, exc)
                continue
            if not isinstance(data, dict):
                continue
            for key in ("min_base", "base_min", "ordermin", "minimum_order_size", "min_volume"):
                if key in data:
                    min_base = max(min_base, _decimal(data.get(key)))
            for key in ("min_quote", "quote_min", "costmin", "min_cost", "min_notional", "raw_min_quote"):
                if key in data:
                    min_quote = max(min_quote, _decimal(data.get(key)))
            source = fn_name
            if min_base > 0 or min_quote > 0:
                break

    base = _base_asset(pair)
    fallback_base = _KRAKEN_FALLBACK_MIN_BASE.get(base, Decimal("0"))
    if fallback_base > min_base:
        min_base = fallback_base
        source = f"{source}+static_fallback:{base}" if source != "none" else f"static_fallback:{base}"

    return min_base, min_quote, source


def _pair_buffer_pct() -> Decimal:
    raw = max(
        Decimal("0.03"),
        _decimal(os.environ.get("NIJA_KRAKEN_PAIR_MIN_BASE_BUFFER_PCT"), Decimal("0.03")),
    )
    return min(raw, Decimal("0.10"))


def _configured_kraken_floor() -> Decimal:
    return max(
        _decimal(os.environ.get("NIJA_KRAKEN_FINAL_MIN_NOTIONAL_USD"), Decimal("0")),
        _decimal(os.environ.get("NIJA_KRAKEN_EFFECTIVE_MIN_NOTIONAL_USD"), Decimal("0")),
        _decimal(os.environ.get("KRAKEN_MIN_NOTIONAL_USD"), Decimal("0")),
        Decimal("0"),
    )


def resolve_pair_required_quote(pair: str, price: Any, module: Optional[ModuleType] = None) -> tuple[Decimal, dict[str, Any]]:
    """Resolve executable Kraken BUY quote for a symbol at a live price."""
    price_d = _decimal(price)
    min_base, min_quote, source = _read_minimum_dict(module, pair)
    configured = _configured_kraken_floor()
    base_quote = min_base * price_d if min_base > 0 and price_d > 0 else Decimal("0")

    target = max(configured, min_quote, base_quote)
    if base_quote > 0 and base_quote >= configured and base_quote >= min_quote:
        target = base_quote * (Decimal("1") + _pair_buffer_pct())

    target = _round_usd_up(target)
    details = {
        "pair": _symbol_text(pair),
        "price": float(price_d),
        "min_base": float(min_base),
        "min_quote": float(min_quote),
        "base_quote": float(base_quote),
        "configured_floor": float(configured),
        "required_quote": float(target),
        "source": source,
    }
    return target, details


def resolve_pair_required_volume(pair: str, price: Any, module: Optional[ModuleType] = None) -> tuple[Decimal, dict[str, Any]]:
    price_d = _decimal(price)
    target_quote, details = resolve_pair_required_quote(pair, price_d, module)
    min_base = _decimal(details.get("min_base", 0))
    if price_d <= 0:
        return min_base, details
    required_by_quote = _round_volume_up(target_quote / price_d)
    volume = max(min_base, required_by_quote)
    details["required_volume"] = float(volume)
    return volume, details


def _patch_kraken_order_validator(module: ModuleType) -> None:
    original = getattr(module, "validate_and_adjust_order", None)
    if not callable(original) or getattr(original, "_nija_pair_aware_minimums", False):
        return

    def validate_and_adjust_order(pair: str, volume: float, price: float, side: str, ordertype: str = "market"):
        normalize_live_execution_env()
        if str(side or "").strip().lower() == "buy" and _decimal(price) > 0:
            required_volume, details = resolve_pair_required_volume(pair, price, module)
            input_volume = _decimal(volume)
            if required_volume > input_volume:
                logger.warning(
                    "KRAKEN_PAIR_MIN_VOLUME_LIFT_APPLIED pair=%s price=$%.8f input_volume=%.8f "
                    "required_volume=%.8f required_quote=$%.2f min_base=%.8f source=%s",
                    details["pair"],
                    details["price"],
                    float(input_volume),
                    float(required_volume),
                    details["required_quote"],
                    details["min_base"],
                    details["source"],
                )
                volume = float(required_volume)
        return original(pair, volume, price, side, ordertype)

    validate_and_adjust_order._nija_pair_aware_minimums = True  # type: ignore[attr-defined]
    module.validate_and_adjust_order = validate_and_adjust_order
    logger.warning("KRAKEN_ORDER_VALIDATOR_PAIR_MINIMUM_PATCHED")


def _patch_exchange_order_compiler(module: ModuleType) -> None:
    cls = getattr(module, "ExchangeOrderCompiler", None)
    if not isinstance(cls, type):
        return
    original = getattr(cls, "compile", None)
    if not callable(original) or getattr(original, "_nija_pair_aware_minimums", False):
        return

    def compile(self: Any, *args: Any, **kwargs: Any):
        normalize_live_execution_env()
        arg_list = list(args)
        symbol = kwargs.get("symbol", arg_list[0] if len(arg_list) > 0 else None)
        side = kwargs.get("side", arg_list[1] if len(arg_list) > 1 else None)
        size_usd = kwargs.get("size_usd", arg_list[2] if len(arg_list) > 2 else None)
        pricing = kwargs.get("pricing", arg_list[3] if len(arg_list) > 3 else None)
        exchange = kwargs.get("exchange", arg_list[4] if len(arg_list) > 4 else None)

        if _is_kraken(exchange) and str(side or "").lower() == "buy":
            price = _extract_price(pricing)
            if price > 0:
                target, details = resolve_pair_required_quote(str(symbol), price)
                current = _round_usd_up(size_usd)
                if target > current:
                    if len(arg_list) > 2:
                        arg_list[2] = float(target)
                    else:
                        kwargs["size_usd"] = float(target)
                    logger.warning(
                        "EXCHANGE_COMPILER_PAIR_MIN_NOTIONAL_LIFT pair=%s requested=$%.2f target=$%.2f "
                        "min_base=%.8f source=%s",
                        details["pair"],
                        float(current),
                        float(target),
                        details["min_base"],
                        details["source"],
                    )
        return original(self, *tuple(arg_list), **kwargs)

    compile._nija_pair_aware_minimums = True  # type: ignore[attr-defined]
    cls.compile = compile
    logger.warning("EXCHANGE_ORDER_COMPILER_PAIR_MINIMUM_PATCHED")


def _patch_ecel(module: ModuleType) -> None:
    cls = getattr(module, "ECELExecutionCompiler", None)
    if not isinstance(cls, type):
        return
    original = getattr(cls, "compile", None)
    if not callable(original) or getattr(original, "_nija_pair_aware_minimums", False):
        return

    def compile(self: Any, req: Any):
        normalize_live_execution_env()
        broker = getattr(req, "broker", "")
        side = str(getattr(req, "side", "") or "").strip().lower()
        symbol = getattr(req, "symbol", None) or getattr(req, "pair", None)
        if _is_kraken(broker) and side == "buy" and symbol:
            price = _extract_price(req)
            if price > 0:
                target, details = resolve_pair_required_quote(str(symbol), price)
                current = _round_usd_up(getattr(req, "desired_notional_usd", 0.0))
                if target > current:
                    try:
                        req = replace(req, desired_notional_usd=float(target))
                    except Exception:
                        try:
                            setattr(req, "desired_notional_usd", float(target))
                        except Exception:
                            pass
                    logger.warning(
                        "ECEL_PAIR_MIN_NOTIONAL_LIFT_APPLIED pair=%s requested=$%.2f target=$%.2f "
                        "min_base=%.8f source=%s",
                        details["pair"],
                        float(current),
                        float(target),
                        details["min_base"],
                        details["source"],
                    )
        return original(self, req)

    compile._nija_pair_aware_minimums = True  # type: ignore[attr-defined]
    cls.compile = compile
    logger.warning("ECEL_PAIR_MINIMUM_PATCHED")


def _platform_only_payload(payload: Any) -> Any:
    if not isinstance(payload, dict):
        return payload
    if not _truthy("NIJA_PLATFORM_EXECUTION_CAPITAL_ONLY", True):
        return payload
    if "platform" not in payload:
        return payload

    users = payload.get("users")
    user_count = 0
    if isinstance(users, dict):
        user_count = len(users)
    cleaned = dict(payload)
    cleaned["users"] = {}
    cleaned["users_excluded_from_execution_capital"] = f"true:user_count={user_count}"
    return cleaned


def _patch_multi_account_manager(module: ModuleType) -> None:
    cls = getattr(module, "MultiAccountBrokerManager", None)
    if not isinstance(cls, type) or getattr(cls, "_nija_capital_scope_patched", False):
        return

    original_refresh = getattr(cls, "refresh_capital_authority", None)
    if callable(original_refresh):
        def refresh_capital_authority(self: Any, *args: Any, **kwargs: Any):
            normalize_live_execution_env()
            if _truthy("NIJA_AGGREGATE_USER_CAPITAL_IN_AUTHORITY", False):
                return original_refresh(self, *args, **kwargs)

            saved_users = getattr(self, "user_brokers", None)
            excluded = 0
            try:
                if isinstance(saved_users, dict) and saved_users:
                    excluded = len(saved_users)
                    setattr(self, "user_brokers", {})
                    logger.warning(
                        "CAPITAL_SCOPE_PLATFORM_ONLY_AUTHORITY_ACTIVE excluded_user_groups=%d",
                        excluded,
                    )
                result = original_refresh(self, *args, **kwargs)
                if isinstance(result, dict):
                    result = dict(result)
                    result["platform_execution_capital_only"] = 1.0
                    result["excluded_user_groups"] = float(excluded)
                return result
            finally:
                if saved_users is not None:
                    try:
                        setattr(self, "user_brokers", saved_users)
                    except Exception:
                        pass

        cls.refresh_capital_authority = refresh_capital_authority

    original_get_all_balances = getattr(cls, "get_all_balances", None)
    if callable(original_get_all_balances):
        def get_all_balances(self: Any, *args: Any, **kwargs: Any):
            payload = original_get_all_balances(self, *args, **kwargs)
            cleaned = _platform_only_payload(payload)
            if cleaned is not payload:
                logger.warning("CAPITAL_SCOPE_PLATFORM_ONLY_BALANCE_PAYLOAD_ACTIVE")
            return cleaned

        cls.get_all_balances = get_all_balances

    cls._nija_capital_scope_patched = True
    logger.warning("MULTI_ACCOUNT_CAPITAL_SCOPE_PATCHED platform_execution_only=true")


def _live_active() -> bool:
    if str(os.environ.get("NIJA_RUNTIME_TRADING_STATE", "")).strip().upper() == "LIVE_ACTIVE":
        return True
    if _truthy("NIJA_RUNTIME_EXECUTION_AUTHORITY") and _truthy("LIVE_CAPITAL_VERIFIED"):
        # Startup logs set execution authority only after the live dispatch latch.
        return True
    for mod_name in ("bot.nija_core_loop", "nija_core_loop"):
        mod = sys.modules.get(mod_name)
        if mod is not None and bool(getattr(mod, "_loop_running", False)):
            return True
    return False


def _patch_readiness_table(module: ModuleType) -> None:
    original = getattr(module, "reset", None)
    if not callable(original) or getattr(original, "_nija_live_active_guard", False):
        return

    def reset() -> None:
        if _live_active() and not _truthy("NIJA_ALLOW_LIVE_ACTIVE_READINESS_RESET", False):
            logger.warning("READINESS_RESET_SKIPPED_LIVE_ACTIVE reason=trading_loop_already_active")
            return None
        return original()

    reset._nija_live_active_guard = True  # type: ignore[attr-defined]
    module.reset = reset
    logger.warning("READINESS_TABLE_LIVE_ACTIVE_RESET_GUARD_PATCHED")


def _patch_bootstrap_fsm(module: ModuleType) -> None:
    cls = getattr(module, "BootstrapStateMachine", None)
    state_cls = getattr(module, "BootstrapState", None)
    if not isinstance(cls, type) or getattr(cls, "_nija_live_active_retry_guard", False):
        return
    original = getattr(cls, "reset_for_retry", None)
    if not callable(original):
        return

    def reset_for_retry(self: Any, reason: str = "retry") -> None:
        if _live_active() and not _truthy("NIJA_ALLOW_LIVE_ACTIVE_BOOTSTRAP_RESET", False):
            current = getattr(getattr(self, "state", None), "value", getattr(self, "state", "unknown"))
            logger.warning(
                "BOOTSTRAP_RESET_FOR_RETRY_SKIPPED_LIVE_ACTIVE state=%s reason=%s",
                current,
                reason,
            )
            if state_cls is not None and hasattr(state_cls, "RUNNING_SUPERVISED"):
                try:
                    self._state = state_cls.RUNNING_SUPERVISED
                    self._boot_complete = True
                    self._execution_authority = True
                except Exception:
                    pass
            return None
        return original(self, reason)

    cls.reset_for_retry = reset_for_retry
    cls._nija_live_active_retry_guard = True
    logger.warning("BOOTSTRAP_FSM_LIVE_ACTIVE_RETRY_GUARD_PATCHED")


def _patch_executable_trade_patch(module: ModuleType) -> None:
    original = getattr(module, "normalize_execution_profile_env", None)
    if callable(original) and not getattr(original, "_nija_pair_scope_wrapped", False):
        def normalize_execution_profile_env() -> None:
            # Ensure the old hook sees the global executable-min flag disabled.
            _set_env_value("NIJA_APPLY_GLOBAL_EXECUTABLE_MIN_TRADE", "false")
            original()
            normalize_live_execution_env()

        normalize_execution_profile_env._nija_pair_scope_wrapped = True  # type: ignore[attr-defined]
        module.normalize_execution_profile_env = normalize_execution_profile_env
        logger.warning("EXECUTABLE_PROFILE_NORMALIZER_PAIR_SCOPE_PATCHED")


def _patch_module(module: ModuleType) -> None:
    name = str(getattr(module, "__name__", ""))
    key = _module_key(module)

    # Some modules (broker_integration) legitimately need rebinding after other
    # hooks change validator/compiler functions, so do not over-cache them.
    if key in _PATCHED and name not in {"bot.broker_integration", "broker_integration"}:
        return

    if name in {"bot.kraken_order_validator", "kraken_order_validator"}:
        _patch_kraken_order_validator(module)
    elif name in {"bot.exchange_order_compiler", "exchange_order_compiler"}:
        _patch_exchange_order_compiler(module)
    elif name in {"bot.ecel_execution_compiler", "ecel_execution_compiler"}:
        _patch_ecel(module)
    elif name in {"bot.multi_account_broker_manager", "multi_account_broker_manager"}:
        _patch_multi_account_manager(module)
    elif name in {"bot.readiness_table", "readiness_table"}:
        _patch_readiness_table(module)
    elif name in {"bot.bootstrap_state_machine", "bootstrap_state_machine"}:
        _patch_bootstrap_fsm(module)
    elif name in {"bot.executable_trade_runtime_patch", "executable_trade_runtime_patch"}:
        _patch_executable_trade_patch(module)

    _PATCHED.add(key)


def _patch_loaded_modules() -> None:
    normalize_live_execution_env()
    for module in list(sys.modules.values()):
        if isinstance(module, ModuleType):
            try:
                _patch_module(module)
            except Exception as exc:
                logger.warning(
                    "LIVE_EXECUTION_HARDENING_MODULE_PATCH_FAILED module=%s err=%s",
                    getattr(module, "__name__", "<unknown>"),
                    exc,
                )


def install_import_hook() -> None:
    global _ORIGINAL_IMPORT
    normalize_live_execution_env()

    if _ORIGINAL_IMPORT is not None:
        _patch_loaded_modules()
        return

    _ORIGINAL_IMPORT = builtins.__import__

    def import_hook(name: str, globals: Any = None, locals: Any = None, fromlist: tuple = (), level: int = 0):
        module = _ORIGINAL_IMPORT(name, globals, locals, fromlist, level)  # type: ignore[misc]
        try:
            _patch_loaded_modules()
        except Exception as exc:
            logger.warning("LIVE_EXECUTION_HARDENING_IMPORT_HOOK_FAILED name=%s err=%s", name, exc)
        return module

    builtins.__import__ = import_hook  # type: ignore[assignment]
    _patch_loaded_modules()
    logger.warning("LIVE_EXECUTION_RUNTIME_HARDENING_INSTALLED pair_minimums=true platform_execution_capital_only=true")


__all__ = [
    "install_import_hook",
    "resolve_pair_required_quote",
    "resolve_pair_required_volume",
    "normalize_live_execution_env",
]
