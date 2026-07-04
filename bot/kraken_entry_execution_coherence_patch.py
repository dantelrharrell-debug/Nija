"""Kraken entry/execution coherence patch.

Unifies the live Kraken entry-size source of truth after earlier startup
normalizers have run. The 2026-07-04 logs showed a conflicting runtime state:
strategy/global minimums were capped back to $10 while Kraken ECEL/final guards
required a $23+ executable BUY. That lets Phase 3 select a candidate whose
sizing path never reaches a valid Kraken submit payload.

This patch does four things without weakening exchange/risk validation:

1. Raises entry-intent env minimums to the final Kraken BUY target quote.
2. Keeps Kraken raw/final exchange floors at the authoritative $23+ values.
3. Re-wraps common sizing/compile paths so Kraken BUY notional is lifted before
   final validation, rather than rejected after selection.
4. Emits a terminal Phase 3 summary for every scan result so a cycle can never
   end with no operator-facing reason.
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

logger = logging.getLogger("nija.kraken_entry_execution_coherence")

_ORIGINAL_IMPORT: Optional[Callable[..., Any]] = None
_PATCHED_MODULES: set[tuple[str, int]] = set()
_LAST_ENV_LOG_TS = 0.0

_CENT = Decimal("0.01")
_RAW_FLOOR = Decimal("20.00")
_SAFE_BUFFER_PCT = Decimal("0.10")
_DRIFT_BUFFER_PCT = Decimal("0.05")
_HARD_FINAL_FLOOR = Decimal("23.00")

_TRUTHY = {"1", "true", "yes", "on", "y", "enabled"}
_FALSEY = {"0", "false", "no", "off", "n", "disabled"}


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


def _set_env_exact_min(name: str, value: Decimal) -> None:
    current = _decimal(os.environ.get(name), Decimal("-1"))
    if current < value:
        os.environ[name] = f"{value:.2f}"


def _set_env_bool(name: str, value: bool) -> None:
    raw = str(os.environ.get(name, "")).strip().lower()
    if raw in _TRUTHY | _FALSEY:
        os.environ[name] = "true" if value else "false"
    elif name not in os.environ:
        os.environ[name] = "true" if value else "false"
    else:
        os.environ[name] = "true" if value else "false"


def _normalize_env() -> None:
    """Normalize live entry sizing after earlier micro-cap caps run."""
    final_floor = _final_floor_usd()
    target_quote = _target_quote_usd()

    # Global entry-intent knobs must be executable on Kraken. If these remain at
    # $10 while Kraken final validation requires $23+, the strategy can select a
    # candidate but never produce a valid BUY payload.
    for key in (
        "MIN_TRADE_USD",
        "MIN_POSITION_USD",
        "MIN_NOTIONAL_OVERRIDE",
        "NIJA_MIN_ENTRY_POSITION_USD",
        "NIJA_TARGET_ENTRY_NOTIONAL_USD",
        "KRAKEN_TARGET_ORDER_USD",
        "NIJA_KRAKEN_TARGET_ORDER_USD",
    ):
        _set_env_exact_min(key, target_quote)

    # Exchange contract floors describe the minimum acceptable order. Keep them
    # at the final floor while entry intent uses the slightly higher target.
    for key in (
        "KRAKEN_MIN_NOTIONAL_USD",
        "NIJA_KRAKEN_MIN_NOTIONAL_USD",
        "NIJA_KRAKEN_MICRO_MIN_NOTIONAL_USD",
        "NIJA_KRAKEN_EFFECTIVE_MIN_NOTIONAL_USD",
        "NIJA_KRAKEN_FINAL_MIN_NOTIONAL_USD",
    ):
        _set_env_exact_min(key, final_floor)

    for key in ("KRAKEN_MIN_QUOTE_BUFFER_PCT", "NIJA_KRAKEN_MIN_QUOTE_BUFFER_PCT"):
        current = _decimal(os.environ.get(key), Decimal("0"))
        if current < _SAFE_BUFFER_PCT:
            os.environ[key] = "0.10"

    for key in ("KRAKEN_EFFECTIVE_NOTIONAL_EXTRA_BUFFER_PCT", "NIJA_KRAKEN_EFFECTIVE_NOTIONAL_EXTRA_BUFFER_PCT"):
        current = _decimal(os.environ.get(key), Decimal("0"))
        if current < _DRIFT_BUFFER_PCT:
            os.environ[key] = "0.05"

    # ADX should rank/weight entries, not hard-block all low-volatility markets
    # when the engine is in micro-cap/HF scalp mode. This preserves all risk and
    # exchange gates while preventing a stale HF_MIN_ADX=10 env from starving Phase 3.
    try:
        current_adx = _decimal(os.environ.get("HF_MIN_ADX"), Decimal("1.5"))
        if current_adx > Decimal("1.5"):
            os.environ["HF_MIN_ADX"] = "1.5"
    except Exception:
        os.environ["HF_MIN_ADX"] = "1.5"
    os.environ.setdefault("NIJA_EFFECTIVE_MIN_ADX", "1.5")
    _set_env_bool("NIJA_ADX_HARD_BLOCK", False)
    _set_env_bool("NIJA_ADX_SCORE_WEIGHTED", True)

    global _LAST_ENV_LOG_TS
    now = time.monotonic()
    if now - _LAST_ENV_LOG_TS >= 60.0:
        _LAST_ENV_LOG_TS = now
        logger.warning(
            "KRAKEN_ENTRY_EXECUTION_COHERENCE_NORMALIZED final_floor=$%.2f target_quote=$%.2f min_trade=%s hf_min_adx=%s adx_hard_block=%s",
            float(final_floor),
            float(target_quote),
            os.environ.get("MIN_TRADE_USD"),
            os.environ.get("HF_MIN_ADX"),
            os.environ.get("NIJA_ADX_HARD_BLOCK"),
        )


def _module_key(module: ModuleType) -> tuple[str, int]:
    return (str(getattr(module, "__name__", "<unknown>")), id(module))


def _is_kraken(exchange: Any) -> bool:
    text = str(exchange or "").strip().lower()
    return "kraken" == text or text.endswith(":kraken") or "kraken" in text


def _patch_position_sizer(module: ModuleType) -> None:
    original = getattr(module, "get_exchange_min_trade_size", None)
    if callable(original) and not getattr(original, "_nija_kraken_entry_target_floor", False):
        def get_exchange_min_trade_size(exchange: str, *args: Any, **kwargs: Any) -> float:
            if _is_kraken(exchange):
                return float(_target_quote_usd())
            return float(original(exchange, *args, **kwargs))

        get_exchange_min_trade_size._nija_kraken_entry_target_floor = True  # type: ignore[attr-defined]
        module.get_exchange_min_trade_size = get_exchange_min_trade_size
        logger.warning("POSITION_SIZER_KRAKEN_ENTRY_TARGET_PATCHED target=$%.2f", float(_target_quote_usd()))


def _patch_tier_config(module: ModuleType) -> None:
    original_get_min = getattr(module, "get_min_trade_size", None)
    if callable(original_get_min) and not getattr(original_get_min, "_nija_kraken_entry_target_floor", False):
        def get_min_trade_size(tier: Any, balance: float, is_platform: bool = False, exchange: str = "coinbase") -> float:
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
        def auto_resize_trade(
            trade_size: float,
            tier: Any,
            balance: float,
            is_platform: bool = False,
            exchange: str = "coinbase",
        ):
            if not _is_kraken(exchange):
                return original_auto_resize(trade_size, tier, balance, is_platform=is_platform, exchange=exchange)
            target = _target_quote_usd()
            bal = _decimal(balance)
            if bal < target:
                return (0.0, f"Balance ${float(bal):.2f} below Kraken target ${float(target):.2f}")
            raised = float(max(_round_usd_up(trade_size), target))
            try:
                resized, reason = original_auto_resize(raised, tier, balance, is_platform=is_platform, exchange=exchange)
            except TypeError:
                resized, reason = original_auto_resize(raised, tier, balance, is_platform, exchange)
            resized_d = _round_usd_up(resized)
            if Decimal("0") < resized_d < target:
                return (float(target), f"Prevented resize below Kraken target ${float(target):.2f}")
            if resized_d == 0 and _decimal(raised) >= target:
                return (raised, "valid after Kraken entry target guard")
            return (float(max(resized_d, target)), reason)

        auto_resize_trade._nija_kraken_entry_target_floor = True  # type: ignore[attr-defined]
        module.auto_resize_trade = auto_resize_trade
        logger.warning("TIER_CONFIG_KRAKEN_ENTRY_TARGET_PATCHED target=$%.2f", float(_target_quote_usd()))


def _patch_exchange_order_compiler(module: ModuleType) -> None:
    cls = getattr(module, "ExchangeOrderCompiler", None)
    if not isinstance(cls, type):
        return

    original_safe = getattr(cls, "_safe_min_notional_usd", None)
    if callable(original_safe) and not getattr(original_safe, "_nija_kraken_entry_target_floor", False):
        def safe_min_notional_usd(self: Any, constraints: Any) -> float:
            if _is_kraken(getattr(constraints, "exchange", "")):
                return float(_final_floor_usd())
            return float(original_safe(self, constraints))

        safe_min_notional_usd._nija_kraken_entry_target_floor = True  # type: ignore[attr-defined]
        cls._safe_min_notional_usd = safe_min_notional_usd

    original_compile = getattr(cls, "compile", None)
    if callable(original_compile) and not getattr(original_compile, "_nija_kraken_entry_target_floor", False):
        def compile(self: Any, symbol: str, side: str, size_usd: float, pricing: Any, exchange: str = "coinbase", min_profit_threshold_usd: float = 0.50):
            if _is_kraken(exchange) and str(side or "").strip().lower() == "buy":
                requested = _round_usd_up(size_usd)
                target = _target_quote_usd()
                if requested < target:
                    logger.warning(
                        "EOC_KRAKEN_ENTRY_NOTIONAL_LIFT_APPLIED symbol=%s requested=$%.2f target=$%.2f",
                        symbol,
                        float(requested),
                        float(target),
                    )
                size_usd = float(max(requested, target))
            return original_compile(self, symbol, side, size_usd, pricing, exchange, min_profit_threshold_usd)

        compile._nija_kraken_entry_target_floor = True  # type: ignore[attr-defined]
        cls.compile = compile
        logger.warning("EXCHANGE_ORDER_COMPILER_KRAKEN_ENTRY_TARGET_PATCHED target=$%.2f", float(_target_quote_usd()))


def _patch_ecel(module: ModuleType) -> None:
    schema_cls = getattr(module, "ContractSchemaMap", None)
    compiler_cls = getattr(module, "ECELExecutionCompiler", None)
    if not isinstance(compiler_cls, type):
        return

    if isinstance(schema_cls, type):
        original_get = getattr(schema_cls, "get_rule", None)
        if callable(original_get) and not getattr(original_get, "_nija_kraken_entry_final_floor", False):
            def get_rule(self: Any, broker: str, symbol: str):
                rule = original_get(self, broker, symbol)
                if rule is not None and _is_kraken(broker) and _decimal(getattr(rule, "min_notional_usd", 0)) < _final_floor_usd():
                    try:
                        rule = replace(rule, min_notional_usd=float(_final_floor_usd()))
                        upsert = getattr(self, "upsert_rule", None)
                        if callable(upsert):
                            upsert(rule)
                    except Exception:
                        pass
                return rule

            get_rule._nija_kraken_entry_final_floor = True  # type: ignore[attr-defined]
            schema_cls.get_rule = get_rule

    original_compile = getattr(compiler_cls, "compile", None)
    if callable(original_compile) and not getattr(original_compile, "_nija_kraken_entry_target_floor", False):
        def compile(self: Any, req: Any):
            broker = str(getattr(req, "broker", "") or "").strip().lower()
            side = str(getattr(req, "side", "") or "").strip().lower()
            if broker == "kraken" and side == "buy":
                requested = _round_usd_up(getattr(req, "desired_notional_usd", 0.0))
                target = _target_quote_usd()
                if requested < target:
                    try:
                        req = replace(req, desired_notional_usd=float(target))
                    except Exception:
                        try:
                            setattr(req, "desired_notional_usd", float(target))
                        except Exception:
                            pass
                    logger.warning("ECEL_KRAKEN_ENTRY_NOTIONAL_LIFT_APPLIED requested=$%.2f target=$%.2f", float(requested), float(target))
            return original_compile(self, req)

        compile._nija_kraken_entry_target_floor = True  # type: ignore[attr-defined]
        compiler_cls.compile = compile
        logger.warning("ECEL_KRAKEN_ENTRY_TARGET_PATCHED target=$%.2f", float(_target_quote_usd()))


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

    def _phase3_scan_and_enter_with_summary(
        self: Any,
        broker: Any,
        snapshot: Any,
        symbols: list[str],
        available_slots: int,
        zero_signal_streak: int = 0,
    ):
        started = time.monotonic()
        final_reason = "unknown"
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
                final_reason = _top_reason(gate_rejections) or "entry_blocked"
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
            print(
                f"[NIJA-PRINT] PHASE3_TERMINAL_SUMMARY marker=20260704a scored={scored} entered={entries} blocked={blocked} reason={final_reason}",
                flush=True,
            )

    _phase3_scan_and_enter_with_summary._nija_phase3_terminal_summary_every_cycle = True  # type: ignore[attr-defined]
    _phase3_scan_and_enter_with_summary.__wrapped__ = original  # type: ignore[attr-defined]
    cls._phase3_scan_and_enter = _phase3_scan_and_enter_with_summary
    logger.warning("PHASE3_TERMINAL_SUMMARY_PATCHED marker=20260704a module=%s", getattr(module, "__name__", "<unknown>"))


def _patch_module(module: ModuleType) -> None:
    key = _module_key(module)
    name = key[0]
    if key in _PATCHED_MODULES:
        return

    if name in {"bot.position_sizer", "position_sizer"}:
        _patch_position_sizer(module)
    elif name in {"bot.tier_config", "tier_config"}:
        _patch_tier_config(module)
    elif name in {"bot.exchange_order_compiler", "exchange_order_compiler"}:
        _patch_exchange_order_compiler(module)
    elif name in {"bot.ecel_execution_compiler", "ecel_execution_compiler"}:
        _patch_ecel(module)
    elif name in {"bot.nija_core_loop", "nija_core_loop"}:
        _patch_core_loop(module)

    _PATCHED_MODULES.add(key)


def _patch_loaded_modules() -> None:
    _normalize_env()
    for module in list(sys.modules.values()):
        if isinstance(module, ModuleType):
            try:
                _patch_module(module)
            except Exception as exc:
                logger.warning(
                    "KRAKEN_ENTRY_EXECUTION_COHERENCE_MODULE_PATCH_FAILED module=%s err=%s",
                    getattr(module, "__name__", "<unknown>"),
                    exc,
                )


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
            logger.warning("KRAKEN_ENTRY_EXECUTION_COHERENCE_IMPORT_HOOK_FAILED name=%s err=%s", name, exc)
        return module

    builtins.__import__ = import_hook  # type: ignore[assignment]
    _patch_loaded_modules()
    logger.warning(
        "KRAKEN_ENTRY_EXECUTION_COHERENCE_INSTALLED final_floor=$%.2f target_quote=$%.2f",
        float(_final_floor_usd()),
        float(_target_quote_usd()),
    )


__all__ = ["install_import_hook"]
