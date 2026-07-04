"""Kraken live order-size repair.

Fixes the 2026-07-04 live failure where Kraken rejected a compiled order
because final post-conversion notional landed at $20.51 while Kraken's buffered
minimum was $20.60.  The patch raises Kraken's effective live floor and repairs
all runtime modules that can size, validate, or compile Kraken orders.
"""

from __future__ import annotations

import builtins
import logging
import os
import sys
from dataclasses import replace
from decimal import Decimal, ROUND_UP
from types import ModuleType
from typing import Any, Callable, Optional

logger = logging.getLogger("nija.kraken_live_order_size_repair")
_ORIGINAL_IMPORT: Optional[Callable[..., Any]] = None
_PATCHED: set[tuple[str, int]] = set()


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default) or default)
    except Exception:
        return default


def _set_min_env(name: str, value: float) -> None:
    current = _float_env(name, value)
    if name not in os.environ or current < value:
        os.environ[name] = f"{value:g}"


def _round_usd_up(value: float) -> float:
    return float((Decimal(str(value)) / Decimal("0.01")).to_integral_value(rounding=ROUND_UP) * Decimal("0.01"))


def _raw_min_usd() -> float:
    # Treat $20 as Kraken's raw operational floor. Do not derive raw floor from
    # KRAKEN_MIN_NOTIONAL_USD because this patch normalizes that env var to the
    # already-buffered safe floor.
    return max(20.0, _float_env("NIJA_KRAKEN_RAW_MIN_NOTIONAL_USD", 20.0))


def _buffer_pct() -> float:
    # The old 3% buffer produced $20.60, but fee/headroom/8dp conversion reduced
    # the order to $20.51. Use at least 10% for Kraken live sizing.
    return min(
        0.25,
        max(
            0.10,
            _float_env("KRAKEN_MIN_QUOTE_BUFFER_PCT", 0.10),
            _float_env("NIJA_KRAKEN_MIN_QUOTE_BUFFER_PCT", 0.10),
        ),
    )


def _safe_min_usd() -> float:
    return _round_usd_up(_raw_min_usd() * (1.0 + _buffer_pct()))


def _target_min_usd() -> float:
    extra = min(max(_float_env("KRAKEN_EFFECTIVE_NOTIONAL_EXTRA_BUFFER_PCT", 0.015), 0.0), 0.10)
    return _round_usd_up(_safe_min_usd() * (1.0 + extra))


def _normalize_env() -> None:
    # Operator-facing env should describe the live effective floor, not the old
    # micro floor. This keeps downstream sizing from requesting $20.61 again.
    _set_min_env("KRAKEN_MIN_NOTIONAL_USD", _safe_min_usd())
    _set_min_env("NIJA_KRAKEN_MIN_NOTIONAL_USD", _safe_min_usd())
    _set_min_env("NIJA_KRAKEN_MICRO_MIN_NOTIONAL_USD", _safe_min_usd())
    _set_min_env("KRAKEN_MIN_QUOTE_BUFFER_PCT", 0.10)
    _set_min_env("NIJA_KRAKEN_MIN_QUOTE_BUFFER_PCT", 0.10)
    _set_min_env("NIJA_KRAKEN_EFFECTIVE_MIN_NOTIONAL_USD", _safe_min_usd())
    _set_min_env("MIN_TRADE_USD", _safe_min_usd())
    _set_min_env("MIN_POSITION_USD", _safe_min_usd())
    _set_min_env("MIN_NOTIONAL_OVERRIDE", _safe_min_usd())


def _module_key(module: ModuleType) -> tuple[str, int]:
    return (str(getattr(module, "__name__", "<unknown>")), id(module))


def _volume_step(module: ModuleType) -> Decimal:
    try:
        step = Decimal(str(getattr(module, "_VOLUME_STEP", "0.00000001")))
    except Exception:
        step = Decimal("0.00000001")
    return step if step > 0 else Decimal("0.00000001")


def _round_volume_up(value: Decimal, step: Decimal) -> float:
    return float((value / step).to_integral_value(rounding=ROUND_UP) * step)


def _patch_kraken_order_validator(module: ModuleType) -> None:
    key = _module_key(module)
    if key in _PATCHED or getattr(module, "_nija_kraken_live_order_size_patched", False):
        return

    try:
        module.KRAKEN_MINIMUM_ORDER_USD = max(float(getattr(module, "KRAKEN_MINIMUM_ORDER_USD", 20.0) or 20.0), _raw_min_usd())
    except Exception:
        pass

    def resolve_min_quote_buffer_pct() -> float:
        return _buffer_pct()

    def get_safe_min_quote(raw_min_quote: float) -> float:
        return _round_usd_up(max(float(raw_min_quote or 0.0), _raw_min_usd()) * (1.0 + _buffer_pct()))

    original_get_pair_minimums = getattr(module, "get_pair_minimums", None)

    def get_pair_safe_minimums(pair: str) -> dict[str, float]:
        minimums = original_get_pair_minimums(pair) if callable(original_get_pair_minimums) else {}
        raw_min = max(float(minimums.get("min_quote", 0.0) or 0.0), _raw_min_usd())
        return {
            "min_base": float(minimums.get("min_base", 0.0) or 0.0),
            "min_quote": get_safe_min_quote(raw_min),
            "raw_min_quote": raw_min,
            "quote_buffer_pct": _buffer_pct(),
        }

    def validate_and_adjust_order(pair: str, volume: float, price: float, side: str, ordertype: str = "market"):
        if price <= 0:
            return False, volume, f"Invalid price {price} for {pair}"
        side_l = str(side or "").strip().lower()
        safe = get_pair_safe_minimums(pair)
        target_quote = _target_min_usd() if side_l == "buy" else safe["min_quote"]
        step = _volume_step(module)
        required_quote_volume = _round_volume_up(Decimal(str(target_quote)) / Decimal(str(price)), step)
        adjusted_volume = max(float(volume or 0.0), required_quote_volume, float(safe.get("min_base", 0.0) or 0.0))

        validator = getattr(module, "validate_order_size", None)
        if callable(validator):
            ok, error = validator(pair, adjusted_volume, price, side)
            if not ok and side_l == "buy":
                adjusted_volume = _round_volume_up(Decimal(str(target_quote + 0.50)) / Decimal(str(price)), step)
                ok, error = validator(pair, adjusted_volume, price, side)
            if not ok:
                return False, volume, error

        logger.critical(
            "KRAKEN_LIVE_ORDER_SIZE_REPAIR_APPLIED pair=%s side=%s input_volume=%.12f adjusted_volume=%.12f price=%.8f safe_min=$%.2f target_min=$%.2f",
            pair,
            side_l,
            float(volume or 0.0),
            adjusted_volume,
            float(price),
            _safe_min_usd(),
            target_quote,
        )
        return True, adjusted_volume, None

    module._resolve_min_quote_buffer_pct = resolve_min_quote_buffer_pct
    module.get_safe_min_quote = get_safe_min_quote
    module.get_pair_safe_minimums = get_pair_safe_minimums
    module.validate_and_adjust_order = validate_and_adjust_order
    module._nija_kraken_live_order_size_patched = True
    _PATCHED.add(key)
    logger.critical("KRAKEN_ORDER_VALIDATOR_LIVE_SIZE_PATCHED safe_min=$%.2f target_min=$%.2f", _safe_min_usd(), _target_min_usd())


def _patch_broker_integration(module: ModuleType) -> None:
    if getattr(module, "_nija_kraken_validator_rebound", False):
        return
    for name in ("bot.kraken_order_validator", "kraken_order_validator"):
        validator = sys.modules.get(name)
        if isinstance(validator, ModuleType):
            _patch_kraken_order_validator(validator)
            fn = getattr(validator, "validate_and_adjust_order", None)
            if callable(fn):
                module.validate_and_adjust_order = fn
            break
    module._nija_kraken_validator_rebound = True
    logger.critical("BROKER_INTEGRATION_KRAKEN_VALIDATOR_REBOUND module=%s", getattr(module, "__name__", "<unknown>"))


def _patch_position_sizer(module: ModuleType) -> None:
    original = getattr(module, "get_exchange_min_trade_size", None)
    if not callable(original) or getattr(original, "_nija_kraken_live_floor_wrapped", False):
        return

    def get_exchange_min_trade_size(exchange: str, *args: Any, **kwargs: Any) -> float:
        if str(exchange or "").strip().lower() == "kraken":
            return _safe_min_usd()
        return float(original(exchange, *args, **kwargs))

    get_exchange_min_trade_size._nija_kraken_live_floor_wrapped = True  # type: ignore[attr-defined]
    module.get_exchange_min_trade_size = get_exchange_min_trade_size
    logger.critical("POSITION_SIZER_KRAKEN_LIVE_FLOOR_PATCHED floor=$%.2f", _safe_min_usd())


def _patch_tier_config(module: ModuleType) -> None:
    if getattr(module, "_nija_nano_platform_tier_patched", False):
        return
    TradingTier = getattr(module, "TradingTier", None)
    TierConfig = getattr(module, "TierConfig", None)
    configs = getattr(module, "TIER_CONFIGS", None)
    if TradingTier is None or TierConfig is None or not isinstance(configs, dict):
        return
    nano = getattr(TradingTier, "NANO_PLATFORM", None)
    if nano is not None and nano not in configs:
        configs[nano] = TierConfig(
            name="NANO_PLATFORM",
            capital_min=1.0,
            capital_max=49.99,
            risk_per_trade_pct=(10.0, 50.0),
            trade_size_min=1.0,
            trade_size_max=25.0,
            max_positions=1,
            description="Isolated micro-capital mode; exchange-specific min-notional remains authoritative",
            min_visible_size=1.0,
        )

    original_get = getattr(module, "get_tier_config", None)
    if callable(original_get) and not getattr(original_get, "_nija_tier_normalized", False):
        def get_tier_config(tier: Any):
            try:
                if isinstance(tier, str):
                    tier = getattr(TradingTier, tier, TradingTier(tier))
            except Exception:
                pass
            if tier == nano and nano in configs:
                return configs[nano]
            return original_get(tier)
        get_tier_config._nija_tier_normalized = True  # type: ignore[attr-defined]
        module.get_tier_config = get_tier_config

    module._nija_nano_platform_tier_patched = True
    logger.critical("TIER_CONFIG_NANO_PLATFORM_REPAIR_PATCHED has_config=%s", bool(nano in configs if nano is not None else False))


def _patch_exchange_order_compiler(module: ModuleType) -> None:
    cls = getattr(module, "ExchangeOrderCompiler", None)
    if not isinstance(cls, type) or getattr(cls, "_nija_kraken_live_floor_patched", False):
        return

    original_resolve = getattr(cls, "_resolve_min_quote_buffer_pct", None)

    @staticmethod
    def resolve_min_quote_buffer_pct(exchange: str) -> float:
        if str(exchange or "").strip().lower() == "kraken":
            return _buffer_pct()
        if callable(original_resolve):
            return float(original_resolve(exchange))
        return 0.0

    def safe_min_notional_usd(self: Any, constraints: Any) -> float:
        raw = max(float(getattr(constraints, "min_order_usd", 0.0) or 0.0), float(getattr(constraints, "min_notional_usd", 0.0) or 0.0))
        if str(getattr(constraints, "exchange", "")).strip().lower() == "kraken":
            return _round_usd_up(max(raw, _raw_min_usd()) * (1.0 + _buffer_pct()))
        return raw

    cls._resolve_min_quote_buffer_pct = resolve_min_quote_buffer_pct
    cls._safe_min_notional_usd = safe_min_notional_usd

    try:
        schemas = getattr(cls, "SCHEMAS", {})
        kraken = schemas.get("kraken") or {}
        for key, rule in list(kraken.items()):
            kraken[key] = replace(rule, min_order_usd=max(float(rule.min_order_usd), _raw_min_usd()), min_notional_usd=max(float(rule.min_notional_usd), _raw_min_usd()))
    except Exception as exc:
        logger.warning("EOC_KRAKEN_SCHEMA_LIVE_FLOOR_PATCH_SKIPPED err=%s", exc)

    cls._nija_kraken_live_floor_patched = True
    logger.critical("EXCHANGE_ORDER_COMPILER_KRAKEN_LIVE_FLOOR_PATCHED safe_min=$%.2f", _safe_min_usd())


def _patch_ecel(module: ModuleType) -> None:
    schema_cls = getattr(module, "ContractSchemaMap", None)
    compiler_cls = getattr(module, "ECELExecutionCompiler", None)
    ContractRule = getattr(module, "ContractRule", None)
    if not isinstance(schema_cls, type) or not isinstance(compiler_cls, type) or ContractRule is None:
        return

    original_upsert = getattr(schema_cls, "upsert_rule", None)
    if callable(original_upsert) and not getattr(original_upsert, "_nija_kraken_live_floor_wrapped", False):
        def upsert_rule(self: Any, rule: Any) -> None:
            try:
                if str(getattr(rule, "broker", "")).strip().lower() == "kraken":
                    rule = replace(rule, min_notional_usd=max(float(getattr(rule, "min_notional_usd", 0.0) or 0.0), _safe_min_usd()))
            except Exception:
                pass
            return original_upsert(self, rule)
        upsert_rule._nija_kraken_live_floor_wrapped = True  # type: ignore[attr-defined]
        schema_cls.upsert_rule = upsert_rule

    original_get = getattr(schema_cls, "get_rule", None)
    if callable(original_get) and not getattr(original_get, "_nija_kraken_live_floor_wrapped", False):
        def get_rule(self: Any, broker: str, symbol: str):
            rule = original_get(self, broker, symbol)
            if str(broker or "").strip().lower() != "kraken":
                return rule
            symbol_s = str(symbol or "").strip().upper().replace("/", "-")
            if rule is None and symbol_s.endswith("-USDT"):
                base = symbol_s.split("-", 1)[0]
                base = "XBT" if base == "BTC" else base
                rule = ContractRule(
                    broker="kraken",
                    symbol=f"{base}-USDT",
                    base_asset=base,
                    quote_asset="USDT",
                    min_notional_usd=_safe_min_usd(),
                    min_base_size=0.00001 if base in {"XBT", "BTC"} else 0.00000001,
                    base_step_size=0.00000001,
                    price_step_size=0.1 if base in {"XBT", "BTC"} else 0.01,
                    base_precision=8,
                    price_precision=1 if base in {"XBT", "BTC"} else 2,
                )
                try:
                    self.upsert_rule(rule)
                except Exception:
                    pass
            elif rule is not None and float(getattr(rule, "min_notional_usd", 0.0) or 0.0) < _safe_min_usd():
                rule = replace(rule, min_notional_usd=_safe_min_usd())
                try:
                    self.upsert_rule(rule)
                except Exception:
                    pass
            return rule
        get_rule._nija_kraken_live_floor_wrapped = True  # type: ignore[attr-defined]
        schema_cls.get_rule = get_rule

    original_compile = getattr(compiler_cls, "compile", None)
    if callable(original_compile) and not getattr(original_compile, "_nija_kraken_live_floor_wrapped", False):
        def compile(self: Any, req: Any):
            if str(getattr(req, "broker", "") or "").strip().lower() == "kraken":
                requested = float(getattr(req, "desired_notional_usd", 0.0) or 0.0)
                target = _target_min_usd()
                if requested < target:
                    try:
                        req = replace(req, desired_notional_usd=target)
                    except Exception:
                        try:
                            setattr(req, "desired_notional_usd", target)
                        except Exception:
                            pass
                    logger.critical("ECEL_KRAKEN_LIVE_NOTIONAL_LIFT_APPLIED requested=$%.2f target=$%.2f", requested, target)
            return original_compile(self, req)
        compile._nija_kraken_live_floor_wrapped = True  # type: ignore[attr-defined]
        compiler_cls.compile = compile

    logger.critical("ECEL_KRAKEN_LIVE_FLOOR_PATCHED safe_min=$%.2f target=$%.2f", _safe_min_usd(), _target_min_usd())


def _patch_module(module: ModuleType) -> None:
    name = str(getattr(module, "__name__", ""))
    if name in {"bot.kraken_order_validator", "kraken_order_validator"}:
        _patch_kraken_order_validator(module)
    elif name in {"bot.broker_integration", "broker_integration"}:
        _patch_broker_integration(module)
    elif name in {"bot.position_sizer", "position_sizer"}:
        _patch_position_sizer(module)
    elif name in {"bot.tier_config", "tier_config"}:
        _patch_tier_config(module)
    elif name in {"bot.exchange_order_compiler", "exchange_order_compiler"}:
        _patch_exchange_order_compiler(module)
    elif name in {"bot.ecel_execution_compiler", "ecel_execution_compiler"}:
        _patch_ecel(module)


def _patch_loaded_modules() -> None:
    _normalize_env()
    for module in list(sys.modules.values()):
        if isinstance(module, ModuleType):
            try:
                _patch_module(module)
            except Exception as exc:
                logger.warning("KRAKEN_LIVE_ORDER_SIZE_MODULE_PATCH_FAILED module=%s err=%s", getattr(module, "__name__", "<unknown>"), exc)


def install_import_hook() -> None:
    global _ORIGINAL_IMPORT
    _normalize_env()
    if _ORIGINAL_IMPORT is not None:
        _patch_loaded_modules()
        return
    _ORIGINAL_IMPORT = builtins.__import__

    def import_hook(name: str, globals: Any = None, locals: Any = None, fromlist: tuple = (), level: int = 0):
        module = _ORIGINAL_IMPORT(name, globals, locals, fromlist, level)  # type: ignore[misc]
        try:
            _patch_loaded_modules()
        except Exception as exc:
            logger.warning("KRAKEN_LIVE_ORDER_SIZE_IMPORT_HOOK_FAILED name=%s err=%s", name, exc)
        return module

    builtins.__import__ = import_hook  # type: ignore[assignment]
    _patch_loaded_modules()
    logger.critical("KRAKEN_LIVE_ORDER_SIZE_IMPORT_HOOK_INSTALLED safe_min=$%.2f target_min=$%.2f", _safe_min_usd(), _target_min_usd())


__all__ = ["install_import_hook"]
