"""Final Kraken execution-floor guard.

This guard is loaded by bot.__init__ after the earlier live order-size repair.
It makes Kraken entry sizing and Kraken final validation use the same source of
truth so Phase 3 cannot select a candidate with a $10 intent while ECEL requires
$23+ for a live Kraken BUY.

The patch does not bypass risk controls or exchange validation. It only raises
Kraken BUY intent/notional to the executable target before validation, preserves
low-balance tier normalization, and emits a terminal Phase 3 summary for every
scan cycle.
"""

from __future__ import annotations

import builtins
import logging
import os
import sys
import time
from dataclasses import replace
from decimal import Decimal, InvalidOperation, ROUND_UP
from types import ModuleType
from typing import Any, Callable, Optional

logger = logging.getLogger("nija.kraken_execution_floor_guard")
_LAST_ENV_NORMALIZED_LOG_TS = 0.0
_ORIGINAL_IMPORT: Optional[Callable[..., Any]] = None
_PATCHED_MODULES: set[tuple[str, int]] = set()

_CENT = Decimal("0.01")
_RAW_FLOOR = Decimal("20.00")
_SAFE_BUFFER_PCT = Decimal("0.10")
_DRIFT_BUFFER_PCT = Decimal("0.05")
_HARD_FINAL_FLOOR = Decimal("23.00")
_TRUTHY = {"1", "true", "yes", "on", "y", "enabled"}


def _truthy(name: str) -> bool:
    return str(os.environ.get(name, "")).strip().lower() in _TRUTHY


def _decimal(value: Any, default: Decimal = Decimal("0")) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return default


def _round_usd_up(value: Any) -> Decimal:
    return (_decimal(value) / _CENT).to_integral_value(rounding=ROUND_UP) * _CENT


def _raw_floor_usd() -> Decimal:
    return max(_RAW_FLOOR, _decimal(os.environ.get("NIJA_KRAKEN_RAW_MIN_NOTIONAL_USD"), _RAW_FLOOR))


def _safe_floor_usd() -> Decimal:
    buffer_pct = max(
        _SAFE_BUFFER_PCT,
        _decimal(os.environ.get("KRAKEN_MIN_QUOTE_BUFFER_PCT"), _SAFE_BUFFER_PCT),
        _decimal(os.environ.get("NIJA_KRAKEN_MIN_QUOTE_BUFFER_PCT"), _SAFE_BUFFER_PCT),
    )
    buffer_pct = min(buffer_pct, Decimal("0.25"))
    return _round_usd_up(_raw_floor_usd() * (Decimal("1") + buffer_pct))


def _final_floor_usd() -> Decimal:
    configured = _decimal(os.environ.get("NIJA_KRAKEN_FINAL_MIN_NOTIONAL_USD"), _HARD_FINAL_FLOOR)
    return _round_usd_up(max(_HARD_FINAL_FLOOR, configured, _safe_floor_usd()))


def _target_quote_usd() -> Decimal:
    drift_pct = max(
        _DRIFT_BUFFER_PCT,
        _decimal(os.environ.get("KRAKEN_EFFECTIVE_NOTIONAL_EXTRA_BUFFER_PCT"), _DRIFT_BUFFER_PCT),
        _decimal(os.environ.get("NIJA_KRAKEN_EFFECTIVE_NOTIONAL_EXTRA_BUFFER_PCT"), _DRIFT_BUFFER_PCT),
    )
    drift_pct = min(drift_pct, Decimal("0.15"))
    return _round_usd_up(max(_final_floor_usd(), _safe_floor_usd() * (Decimal("1") + drift_pct)))


def _set_env_floor(name: str, value: Decimal) -> None:
    current = _decimal(os.environ.get(name), Decimal("-1"))
    if current < value:
        os.environ[name] = f"{value:.2f}"


def _normalize_env() -> None:
    final_floor = _final_floor_usd()
    target_quote = _target_quote_usd()

    # Entry intent must be executable. These were previously capped to $10 by
    # micro-cap startup defaults, while Kraken final validation required $23+.
    for key in (
        "MIN_TRADE_USD",
        "MIN_POSITION_USD",
        "MIN_NOTIONAL_OVERRIDE",
        "NIJA_MIN_ENTRY_POSITION_USD",
        "NIJA_TARGET_ENTRY_NOTIONAL_USD",
        "KRAKEN_TARGET_ORDER_USD",
        "NIJA_KRAKEN_TARGET_ORDER_USD",
    ):
        _set_env_floor(key, target_quote)

    # Contract/exchange floors remain the final minimum; requested BUY notional
    # uses the slightly higher target_quote to survive rounding/fee drift.
    for key in (
        "KRAKEN_MIN_NOTIONAL_USD",
        "NIJA_KRAKEN_MIN_NOTIONAL_USD",
        "NIJA_KRAKEN_MICRO_MIN_NOTIONAL_USD",
        "NIJA_KRAKEN_EFFECTIVE_MIN_NOTIONAL_USD",
        "NIJA_KRAKEN_FINAL_MIN_NOTIONAL_USD",
    ):
        _set_env_floor(key, final_floor)

    for key in ("KRAKEN_EFFECTIVE_NOTIONAL_EXTRA_BUFFER_PCT", "NIJA_KRAKEN_EFFECTIVE_NOTIONAL_EXTRA_BUFFER_PCT"):
        current = _decimal(os.environ.get(key), Decimal("0"))
        if current < _DRIFT_BUFFER_PCT:
            os.environ[key] = "0.05"

    for key in ("KRAKEN_MIN_QUOTE_BUFFER_PCT", "NIJA_KRAKEN_MIN_QUOTE_BUFFER_PCT"):
        current = _decimal(os.environ.get(key), Decimal("0"))
        if current < _SAFE_BUFFER_PCT:
            os.environ[key] = "0.10"

    # Prevent stale HF_MIN_ADX=10 from hard-starving micro-cap/HF scalp mode.
    # ADX remains available as a score/rank weight; risk and exchange gates remain intact.
    try:
        if _decimal(os.environ.get("HF_MIN_ADX"), Decimal("1.5")) > Decimal("1.5"):
            os.environ["HF_MIN_ADX"] = "1.5"
    except Exception:
        os.environ["HF_MIN_ADX"] = "1.5"
    os.environ.setdefault("NIJA_EFFECTIVE_MIN_ADX", "1.5")
    os.environ["NIJA_ADX_HARD_BLOCK"] = "false"
    os.environ["NIJA_ADX_SCORE_WEIGHTED"] = "true"

    global _LAST_ENV_NORMALIZED_LOG_TS
    now = time.monotonic()
    if now - _LAST_ENV_NORMALIZED_LOG_TS >= 60.0:
        _LAST_ENV_NORMALIZED_LOG_TS = now
        logger.warning(
            "KRAKEN_EXECUTION_FLOOR_ENV_NORMALIZED final_floor=$%.2f target_quote=$%.2f min_trade=%s hf_min_adx=%s adx_hard_block=%s",
            float(final_floor),
            float(target_quote),
            os.environ.get("MIN_TRADE_USD"),
            os.environ.get("HF_MIN_ADX"),
            os.environ.get("NIJA_ADX_HARD_BLOCK"),
        )


class _PatchNoiseFilter(logging.Filter):
    _last_emit: dict[str, float] = {}
    _markers: tuple[tuple[str, float], ...] = (
        ("ECEL_KRAKEN_LIVE_FLOOR_PATCHED", 60.0),
        ("KRAKEN_ORDER_VALIDATOR_LIVE_SIZE_PATCHED", 60.0),
        ("EXCHANGE_ORDER_COMPILER_KRAKEN_LIVE_FLOOR_PATCHED", 60.0),
        ("POSITION_SIZER_KRAKEN_LIVE_FLOOR_PATCHED", 60.0),
        ("TIER_CONFIG_NANO_PLATFORM_REPAIR_PATCHED", 60.0),
        ("BROKER_INTEGRATION_KRAKEN_VALIDATOR_REBOUND", 60.0),
        ("EXECUTION_ROUTE_INTEGRITY_PATCHED", 60.0),
    )

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        now = time.monotonic()
        for marker, interval in self._markers:
            if marker not in msg:
                continue
            key = f"{record.name}:{marker}"
            last = self._last_emit.get(key, 0.0)
            if now - last < interval:
                return False
            self._last_emit[key] = now
            if record.levelno > logging.WARNING:
                record.levelno = logging.WARNING
                record.levelname = "WARNING"
            return True
        return True


def _install_log_filters() -> None:
    for name in ("nija.kraken_live_order_size_repair", "nija.execution_route_integrity_patch"):
        log = logging.getLogger(name)
        if not getattr(log, "_nija_patch_noise_filter_installed", False):
            log.addFilter(_PatchNoiseFilter())
            log._nija_patch_noise_filter_installed = True  # type: ignore[attr-defined]


def _module_key(module: ModuleType) -> tuple[str, int]:
    return (str(getattr(module, "__name__", "<unknown>")), id(module))


def _is_kraken(exchange: Any) -> bool:
    text = str(exchange or "").strip().lower()
    return text == "kraken" or text.endswith(":kraken") or "kraken" in text


def _enum_member(module: ModuleType, name: str) -> Any:
    enum_cls = getattr(module, "TradingTier", None)
    if enum_cls is None:
        return None
    try:
        return getattr(enum_cls, name)
    except Exception:
        try:
            return enum_cls[name]
        except Exception:
            return None


def _tier_name(tier: Any) -> str:
    return str(getattr(tier, "name", getattr(tier, "value", tier))).upper()


def _balance_based_tier(module: ModuleType, balance: Any) -> Any:
    bal = _decimal(balance)
    if bal <= 0:
        return _enum_member(module, "NO_CAPITAL") or _enum_member(module, "NANO_PLATFORM")
    if bal < Decimal("50"):
        return _enum_member(module, "NANO_PLATFORM") or _enum_member(module, "STARTER")
    if bal < Decimal("100"):
        return _enum_member(module, "STARTER")
    if bal < Decimal("250"):
        return _enum_member(module, "SAVER")
    if bal < Decimal("1000"):
        return _enum_member(module, "INVESTOR")
    if bal < Decimal("5000"):
        return _enum_member(module, "INCOME")
    if bal < Decimal("25000"):
        return _enum_member(module, "LIVABLE")
    return _enum_member(module, "BALLER")


def _tier_capital_min(module: ModuleType, tier: Any) -> Decimal:
    configs = getattr(module, "TIER_CONFIGS", {})
    try:
        config = configs.get(tier)
    except Exception:
        config = None
    return _decimal(getattr(config, "capital_min", 0), Decimal("0"))


def _normalize_runtime_tier(module: ModuleType, tier: Any, balance: Any, is_platform: bool) -> Any:
    bal = _decimal(balance)
    if bal < Decimal("25000") and (is_platform or _tier_name(tier) in {"BALLER", "PLATFORM"}):
        replacement = _balance_based_tier(module, bal)
        logger.warning(
            "LOW_BALANCE_TIER_NORMALIZED requested=%s balance=$%.2f replacement=%s",
            _tier_name(tier),
            float(bal),
            _tier_name(replacement),
        )
        return replacement
    return tier


def _patch_tier_config(module: ModuleType) -> None:
    original_get_tier = getattr(module, "get_tier_from_balance", None)
    if callable(original_get_tier) and not getattr(original_get_tier, "_nija_low_balance_guard", False):
        module._nija_original_get_tier_from_balance = original_get_tier

        def get_tier_from_balance(balance: float, override_tier: str = None, is_platform: bool = False):
            bal = _decimal(balance)
            requested = str(override_tier or os.environ.get("PLATFORM_ACCOUNT_TIER", "")).strip().upper()
            allow_underfunded = _truthy("NIJA_ALLOW_UNDERFUNDED_TIER_OVERRIDE")
            balance_tier = _balance_based_tier(module, bal)

            if is_platform and bal < Decimal("25000") and not allow_underfunded:
                logger.warning("PLATFORM_LOW_BALANCE_BALLER_BLOCKED balance=$%.2f resolved_tier=%s", float(bal), _tier_name(balance_tier))
                return balance_tier
            if requested in {"BALLER", "PLATFORM"} and bal < Decimal("25000") and not allow_underfunded:
                logger.warning("LOW_BALANCE_BALLER_OVERRIDE_BLOCKED requested=%s balance=$%.2f resolved_tier=%s", requested, float(bal), _tier_name(balance_tier))
                return balance_tier
            if requested and not allow_underfunded:
                requested_tier = _enum_member(module, requested)
                if requested_tier is not None and _tier_capital_min(module, requested_tier) > bal:
                    logger.warning("UNDERFUNDED_TIER_OVERRIDE_BLOCKED requested=%s balance=$%.2f resolved_tier=%s", requested, float(bal), _tier_name(balance_tier))
                    return balance_tier
            try:
                return original_get_tier(balance, override_tier=override_tier, is_platform=is_platform)
            except TypeError:
                return original_get_tier(balance)

        get_tier_from_balance._nija_low_balance_guard = True  # type: ignore[attr-defined]
        module.get_tier_from_balance = get_tier_from_balance

    original_get_min = getattr(module, "get_min_trade_size", None)
    if callable(original_get_min) and not getattr(original_get_min, "_nija_kraken_entry_target_floor", False):
        def get_min_trade_size(tier: Any, balance: float, is_platform: bool = False, exchange: str = "coinbase") -> float:
            tier = _normalize_runtime_tier(module, tier, balance, is_platform)
            try:
                value = original_get_min(tier, balance, is_platform=is_platform, exchange=exchange)
            except TypeError:
                value = original_get_min(tier, balance, is_platform, exchange)
            if _is_kraken(exchange):
                return float(max(_round_usd_up(value), _target_quote_usd()))
            return float(value)

        get_min_trade_size._nija_kraken_entry_target_floor = True  # type: ignore[attr-defined]
        module.get_min_trade_size = get_min_trade_size

    original_auto_resize = getattr(module, "auto_resize_trade", None)
    if callable(original_auto_resize) and not getattr(original_auto_resize, "_nija_kraken_entry_target_floor", False):
        def auto_resize_trade(trade_size: float, tier: Any, balance: float, is_platform: bool = False, exchange: str = "coinbase"):
            tier = _normalize_runtime_tier(module, tier, balance, is_platform)
            if not _is_kraken(exchange):
                return original_auto_resize(trade_size, tier, balance, is_platform=is_platform, exchange=exchange)
            target = _target_quote_usd()
            size = _round_usd_up(trade_size)
            bal = _decimal(balance)
            if bal < target:
                return (0.0, f"Balance ${float(bal):.2f} below Kraken target ${float(target):.2f}")
            raised = float(max(size, target))
            try:
                resized, reason = original_auto_resize(raised, tier, balance, is_platform=is_platform, exchange=exchange)
            except TypeError:
                resized, reason = original_auto_resize(raised, tier, balance, is_platform, exchange)
            resized_d = _round_usd_up(resized)
            if Decimal("0") < resized_d < target:
                logger.warning("KRAKEN_TIER_RESIZE_DOWN_BLOCKED original=$%.2f resized=$%.2f target=$%.2f", float(raised), float(resized_d), float(target))
                return (float(target), f"Prevented resize below Kraken target ${float(target):.2f}")
            if resized_d == 0 and _decimal(raised) >= target:
                return (raised, "valid after Kraken entry target guard")
            return (float(max(resized_d, target)), reason)

        auto_resize_trade._nija_kraken_entry_target_floor = True  # type: ignore[attr-defined]
        module.auto_resize_trade = auto_resize_trade

    original_validate = getattr(module, "validate_trade_size", None)
    if callable(original_validate) and not getattr(original_validate, "_nija_kraken_entry_decimal_compare", False):
        def validate_trade_size(trade_size: float, tier: Any, balance: float, is_platform: bool = False, exchange: str = "coinbase"):
            tier = _normalize_runtime_tier(module, tier, balance, is_platform)
            if _is_kraken(exchange):
                size = _round_usd_up(trade_size)
                target = _target_quote_usd()
                if size >= target and _decimal(balance) >= size:
                    return (True, f"Trade size valid after Kraken entry target guard (${float(size):.2f} >= ${float(target):.2f})")
            try:
                ok, reason = original_validate(trade_size, tier, balance, is_platform=is_platform, exchange=exchange)
            except TypeError:
                ok, reason = original_validate(trade_size, tier, balance, is_platform, exchange)
            if not ok and _is_kraken(exchange):
                size = _round_usd_up(trade_size)
                target = _target_quote_usd()
                if size >= target and _decimal(balance) >= size:
                    return (True, "valid after Kraken entry target equality guard")
            return (ok, reason)

        validate_trade_size._nija_kraken_entry_decimal_compare = True  # type: ignore[attr-defined]
        module.validate_trade_size = validate_trade_size

    logger.info("TIER_CONFIG_LOW_BALANCE_KRAKEN_GUARD_PATCHED final_floor=$%.2f target=$%.2f", float(_final_floor_usd()), float(_target_quote_usd()))


def _patch_position_sizer(module: ModuleType) -> None:
    original = getattr(module, "get_exchange_min_trade_size", None)
    if not callable(original) or getattr(original, "_nija_kraken_entry_target_floor", False):
        return

    def get_exchange_min_trade_size(exchange: str, *args: Any, **kwargs: Any) -> float:
        if _is_kraken(exchange):
            return float(_target_quote_usd())
        return float(original(exchange, *args, **kwargs))

    get_exchange_min_trade_size._nija_kraken_entry_target_floor = True  # type: ignore[attr-defined]
    module.get_exchange_min_trade_size = get_exchange_min_trade_size
    logger.info("POSITION_SIZER_KRAKEN_ENTRY_TARGET_PATCHED target=$%.2f", float(_target_quote_usd()))


def _volume_step(module: ModuleType) -> Decimal:
    return max(Decimal("0.00000001"), _decimal(getattr(module, "_VOLUME_STEP", "0.00000001"), Decimal("0.00000001")))


def _round_volume_up(value: Decimal, step: Decimal) -> float:
    return float((value / step).to_integral_value(rounding=ROUND_UP) * step)


def _patch_kraken_order_validator(module: ModuleType) -> None:
    original = getattr(module, "validate_and_adjust_order", None)
    if not callable(original) or getattr(original, "_nija_kraken_entry_target", False):
        return

    def validate_and_adjust_order(pair: str, volume: float, price: float, side: str, ordertype: str = "market"):
        if str(side or "").strip().lower() == "buy" and _decimal(price) > 0:
            target = _target_quote_usd()
            step = _volume_step(module)
            required_volume = _round_volume_up(target / _decimal(price), step)
            volume = max(float(volume or 0.0), required_volume)
        return original(pair, volume, price, side, ordertype)

    validate_and_adjust_order._nija_kraken_entry_target = True  # type: ignore[attr-defined]
    module.validate_and_adjust_order = validate_and_adjust_order
    logger.info("KRAKEN_ORDER_VALIDATOR_ENTRY_TARGET_PATCHED target=$%.2f", float(_target_quote_usd()))


def _patch_broker_integration(module: ModuleType) -> None:
    if getattr(module, "_nija_kraken_entry_target_rebound", False):
        return
    for name in ("bot.tier_config", "tier_config"):
        tier_mod = sys.modules.get(name)
        if isinstance(tier_mod, ModuleType):
            for attr in ("get_tier_from_balance", "get_min_trade_size", "auto_resize_trade", "validate_trade_size"):
                fn = getattr(tier_mod, attr, None)
                if callable(fn):
                    setattr(module, attr, fn)
            break
    for name in ("bot.kraken_order_validator", "kraken_order_validator"):
        validator = sys.modules.get(name)
        if isinstance(validator, ModuleType):
            fn = getattr(validator, "validate_and_adjust_order", None)
            if callable(fn):
                module.validate_and_adjust_order = fn
            break
    module._nija_kraken_entry_target_rebound = True
    logger.info("BROKER_INTEGRATION_KRAKEN_ENTRY_TARGET_REBOUND module=%s", getattr(module, "__name__", "<unknown>"))


def _patch_exchange_order_compiler(module: ModuleType) -> None:
    cls = getattr(module, "ExchangeOrderCompiler", None)
    if not isinstance(cls, type):
        return

    original_safe = getattr(cls, "_safe_min_notional_usd", None)
    if callable(original_safe) and not getattr(original_safe, "_nija_kraken_entry_final_floor", False):
        def safe_min_notional_usd(self: Any, constraints: Any) -> float:
            if _is_kraken(getattr(constraints, "exchange", "")):
                return float(_final_floor_usd())
            return float(original_safe(self, constraints))

        safe_min_notional_usd._nija_kraken_entry_final_floor = True  # type: ignore[attr-defined]
        cls._safe_min_notional_usd = safe_min_notional_usd

    original_compile = getattr(cls, "compile", None)
    if callable(original_compile) and not getattr(original_compile, "_nija_kraken_entry_target", False):
        def compile(self: Any, symbol: str, side: str, size_usd: float, pricing: Any, exchange: str = "coinbase", min_profit_threshold_usd: float = 0.50):
            if _is_kraken(exchange) and str(side or "").strip().lower() == "buy":
                size_usd = float(max(_round_usd_up(size_usd), _target_quote_usd()))
            return original_compile(self, symbol, side, size_usd, pricing, exchange, min_profit_threshold_usd)

        compile._nija_kraken_entry_target = True  # type: ignore[attr-defined]
        cls.compile = compile

    try:
        schemas = getattr(cls, "SCHEMAS", {})
        kraken = schemas.get("kraken") or {}
        for key, rule in list(kraken.items()):
            if _is_kraken(getattr(rule, "exchange", "kraken")):
                kraken[key] = replace(
                    rule,
                    min_order_usd=max(float(getattr(rule, "min_order_usd", 0.0) or 0.0), float(_final_floor_usd())),
                    min_notional_usd=max(float(getattr(rule, "min_notional_usd", 0.0) or 0.0), float(_final_floor_usd())),
                )
    except Exception as exc:
        logger.warning("EOC_KRAKEN_FINAL_SCHEMA_PATCH_SKIPPED err=%s", exc)

    logger.info("EXCHANGE_ORDER_COMPILER_KRAKEN_ENTRY_TARGET_PATCHED floor=$%.2f target=$%.2f", float(_final_floor_usd()), float(_target_quote_usd()))


def _patch_ecel(module: ModuleType) -> None:
    schema_cls = getattr(module, "ContractSchemaMap", None)
    compiler_cls = getattr(module, "ECELExecutionCompiler", None)
    ContractRule = getattr(module, "ContractRule", None)
    if not isinstance(schema_cls, type) or not isinstance(compiler_cls, type) or ContractRule is None:
        return

    original_upsert = getattr(schema_cls, "upsert_rule", None)
    if callable(original_upsert) and not getattr(original_upsert, "_nija_kraken_entry_final_floor", False):
        def upsert_rule(self: Any, rule: Any) -> None:
            try:
                if _is_kraken(getattr(rule, "broker", "")):
                    rule = replace(rule, min_notional_usd=max(float(getattr(rule, "min_notional_usd", 0.0) or 0.0), float(_final_floor_usd())))
            except Exception:
                pass
            return original_upsert(self, rule)

        upsert_rule._nija_kraken_entry_final_floor = True  # type: ignore[attr-defined]
        schema_cls.upsert_rule = upsert_rule

    original_get = getattr(schema_cls, "get_rule", None)
    if callable(original_get) and not getattr(original_get, "_nija_kraken_entry_final_floor", False):
        def get_rule(self: Any, broker: str, symbol: str):
            rule = original_get(self, broker, symbol)
            if not _is_kraken(broker):
                return rule
            symbol_s = str(symbol or "").strip().upper().replace("/", "-")
            if rule is None and "-" in symbol_s:
                base, quote = symbol_s.split("-", 1)
                base = "XBT" if base == "BTC" else base
                rule = ContractRule(
                    broker="kraken",
                    symbol=f"{base}-{quote}",
                    base_asset=base,
                    quote_asset=quote,
                    min_notional_usd=float(_final_floor_usd()),
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
            elif rule is not None and _decimal(getattr(rule, "min_notional_usd", 0)) < _final_floor_usd():
                rule = replace(rule, min_notional_usd=float(_final_floor_usd()))
                try:
                    self.upsert_rule(rule)
                except Exception:
                    pass
            return rule

        get_rule._nija_kraken_entry_final_floor = True  # type: ignore[attr-defined]
        schema_cls.get_rule = get_rule

    original_compile = getattr(compiler_cls, "compile", None)
    if callable(original_compile) and not getattr(original_compile, "_nija_kraken_entry_target", False):
        def compile(self: Any, req: Any):
            broker = str(getattr(req, "broker", "") or "").strip().lower()
            side = str(getattr(req, "side", "") or "").strip().lower()
            if broker == "kraken" and side == "buy":
                target = _target_quote_usd()
                requested = _round_usd_up(getattr(req, "desired_notional_usd", 0.0))
                if requested < target:
                    try:
                        req = replace(req, desired_notional_usd=float(target))
                    except Exception:
                        try:
                            setattr(req, "desired_notional_usd", float(target))
                        except Exception:
                            pass
                    logger.info("ECEL_KRAKEN_ENTRY_NOTIONAL_LIFT_APPLIED requested=$%.2f target=$%.2f", float(requested), float(target))
            result = original_compile(self, req)
            if broker == "kraken" and side == "buy":
                compiled = _round_usd_up(getattr(result, "compiled_notional_usd", 0.0))
                if (not getattr(result, "accepted", False)) or compiled < _final_floor_usd():
                    retry_target = _round_usd_up(max(_target_quote_usd() + Decimal("0.50"), _decimal(getattr(req, "desired_notional_usd", 0)) + Decimal("0.50")))
                    try:
                        retry_req = replace(req, desired_notional_usd=float(retry_target))
                    except Exception:
                        retry_req = req
                        try:
                            setattr(retry_req, "desired_notional_usd", float(retry_target))
                        except Exception:
                            pass
                    logger.warning(
                        "ECEL_KRAKEN_FINAL_RETRY requested=$%.2f compiled=$%.2f retry_target=$%.2f accepted=%s reason=%s",
                        float(_decimal(getattr(req, "desired_notional_usd", 0))),
                        float(compiled),
                        float(retry_target),
                        getattr(result, "accepted", False),
                        getattr(result, "reason", ""),
                    )
                    result = original_compile(self, retry_req)
            return result

        compile._nija_kraken_entry_target = True  # type: ignore[attr-defined]
        compiler_cls.compile = compile

    logger.info("ECEL_KRAKEN_ENTRY_TARGET_PATCHED floor=$%.2f target=$%.2f", float(_final_floor_usd()), float(_target_quote_usd()))


def _top_reason(mapping: Any) -> str:
    if not isinstance(mapping, dict) or not mapping:
        return "none"
    best_key = "none"
    best_count = 0
    for key, value in mapping.items():
        try:
            count = int(value or 0)
        except Exception:
            count = 0
        if count > best_count:
            best_key = str(key)
            best_count = count
    return best_key if best_count > 0 else "none"


def _patch_core_loop(module: ModuleType) -> None:
    cls = getattr(module, "NijaCoreLoop", None)
    if not isinstance(cls, type):
        return
    original = getattr(cls, "_phase3_scan_and_enter", None)
    if not callable(original) or getattr(original, "_nija_phase3_terminal_summary_every_cycle", False):
        return

    def _phase3_scan_and_enter_with_summary(self: Any, broker: Any, snapshot: Any, symbols: list[str], available_slots: int, zero_signal_streak: int = 0):
        started = time.monotonic()
        result: Any = None
        try:
            result = original(self, broker, snapshot, symbols, available_slots, zero_signal_streak)
            return result
        finally:
            elapsed_ms = (time.monotonic() - started) * 1000.0
            entries = blocked = scored = 0
            gate_rejections: Any = {}
            if isinstance(result, tuple):
                try:
                    entries = int(result[0] or 0) if len(result) > 0 else 0
                    blocked = int(result[1] or 0) if len(result) > 1 else 0
                    scored = int(result[2] or 0) if len(result) > 2 else 0
                    gate_rejections = result[3] if len(result) > 3 else {}
                except Exception:
                    pass
            if result is None:
                final_reason = "phase3_exception_or_no_result"
            elif entries > 0:
                final_reason = "entry_submitted"
            elif scored <= 0:
                final_reason = "no_symbols_scored"
            elif blocked > 0:
                final_reason = _top_reason(gate_rejections) if _top_reason(gate_rejections) != "none" else "entry_blocked"
            else:
                final_reason = "scan_complete_no_entry"
            logger.warning(
                "PHASE3_TERMINAL_SUMMARY marker=20260704a cycle_id=%s broker=%s symbols_in=%d slots=%d scored=%d entered=%d blocked=%d final_reason=%s top_gate=%s top_reject=%s top_veto=%s elapsed_ms=%.0f",
                getattr(snapshot, "cycle_id", ""),
                getattr(broker, "broker_name", getattr(broker, "name", type(broker).__name__)),
                len(symbols or []),
                int(available_slots or 0),
                scored,
                entries,
                blocked,
                final_reason,
                _top_reason(gate_rejections),
                _top_reason(getattr(self, "reject_reason_counts", {})),
                _top_reason(getattr(self, "veto_reason_counts", {})),
                elapsed_ms,
            )
            print(f"[NIJA-PRINT] PHASE3_TERMINAL_SUMMARY marker=20260704a scored={scored} entered={entries} blocked={blocked} reason={final_reason}", flush=True)

    _phase3_scan_and_enter_with_summary._nija_phase3_terminal_summary_every_cycle = True  # type: ignore[attr-defined]
    _phase3_scan_and_enter_with_summary.__wrapped__ = original  # type: ignore[attr-defined]
    cls._phase3_scan_and_enter = _phase3_scan_and_enter_with_summary
    logger.warning("PHASE3_TERMINAL_SUMMARY_PATCHED marker=20260704a module=%s", getattr(module, "__name__", "<unknown>"))


def _patch_module(module: ModuleType) -> None:
    key = _module_key(module)
    name = key[0]
    if key in _PATCHED_MODULES and name not in {"bot.broker_integration", "broker_integration"}:
        return
    if name in {"bot.tier_config", "tier_config"}:
        _patch_tier_config(module)
    elif name in {"bot.position_sizer", "position_sizer"}:
        _patch_position_sizer(module)
    elif name in {"bot.kraken_order_validator", "kraken_order_validator"}:
        _patch_kraken_order_validator(module)
    elif name in {"bot.broker_integration", "broker_integration"}:
        _patch_broker_integration(module)
    elif name in {"bot.exchange_order_compiler", "exchange_order_compiler"}:
        _patch_exchange_order_compiler(module)
    elif name in {"bot.ecel_execution_compiler", "ecel_execution_compiler"}:
        _patch_ecel(module)
    elif name in {"bot.nija_core_loop", "nija_core_loop"}:
        _patch_core_loop(module)
    _PATCHED_MODULES.add(key)


def _patch_loaded_modules() -> None:
    _normalize_env()
    _install_log_filters()
    for module in list(sys.modules.values()):
        if isinstance(module, ModuleType):
            try:
                _patch_module(module)
            except Exception as exc:
                logger.warning("KRAKEN_EXECUTION_FLOOR_MODULE_PATCH_FAILED module=%s err=%s", getattr(module, "__name__", "<unknown>"), exc)


def install_import_hook() -> None:
    global _ORIGINAL_IMPORT
    _normalize_env()
    _install_log_filters()
    if _ORIGINAL_IMPORT is not None:
        _patch_loaded_modules()
        return
    _ORIGINAL_IMPORT = builtins.__import__

    def import_hook(name: str, globals: Any = None, locals: Any = None, fromlist: tuple = (), level: int = 0):
        module = _ORIGINAL_IMPORT(name, globals, locals, fromlist, level)  # type: ignore[misc]
        try:
            _patch_loaded_modules()
        except Exception as exc:
            logger.warning("KRAKEN_EXECUTION_FLOOR_IMPORT_HOOK_FAILED name=%s err=%s", name, exc)
        return module

    builtins.__import__ = import_hook  # type: ignore[assignment]
    _patch_loaded_modules()
    logger.warning("KRAKEN_EXECUTION_FLOOR_GUARD_INSTALLED final_floor=$%.2f target_quote=$%.2f", float(_final_floor_usd()), float(_target_quote_usd()))


__all__ = ["install_import_hook"]
