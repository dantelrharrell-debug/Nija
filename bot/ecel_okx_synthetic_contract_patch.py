from __future__ import annotations

import builtins
import logging
import os
import re
import sys
from types import ModuleType
from typing import Any

logger = logging.getLogger("nija.ecel_okx_synthetic_contract")
_PATCHED_ATTR = "_NIJA_OKX_SYNTHETIC_CONTRACT_PATCHED"
_QUOTES = ("USDT", "USDC", "USD")


def _norm_symbol(value: Any) -> str:
    return str(value or "").strip().upper().replace("/", "-").replace("_", "-")


def _norm_broker(value: Any) -> str:
    return str(getattr(value, "value", value) or "").strip().lower()


def _split_symbol(symbol: str) -> tuple[str, str]:
    sym = _norm_symbol(symbol)
    if "-" in sym:
        base, quote = sym.rsplit("-", 1)
        return re.sub(r"[^A-Z0-9]", "", base), re.sub(r"[^A-Z0-9]", "", quote)
    compact = re.sub(r"[^A-Z0-9]", "", sym)
    for quote in _QUOTES:
        if compact.endswith(quote) and len(compact) > len(quote):
            return compact[: -len(quote)], quote
    return compact, ""


def _synthetic_okx_rule(ecel_module: ModuleType, symbol: Any):
    ContractRule = getattr(ecel_module, "ContractRule", None)
    if ContractRule is None:
        return None
    sym = _norm_symbol(symbol)
    base, quote = _split_symbol(sym)
    if not base or quote not in {"USDT", "USDC"}:
        return None
    try:
        min_notional = float(
            os.getenv("NIJA_OKX_ECEL_MIN_NOTIONAL_USD")
            or os.getenv("OKX_MIN_ORDER_USD")
            or os.getenv("NIJA_OKX_MIN_ORDER_USD")
            or "10.0"
        )
    except Exception:
        min_notional = 10.0
    min_notional = max(1.0, min_notional)
    return ContractRule(
        broker="okx",
        symbol=sym,
        base_asset=base,
        quote_asset=quote,
        min_notional_usd=min_notional,
        min_base_size=0.00000001,
        base_step_size=0.00000001,
        price_step_size=0.00000001,
        base_precision=8,
        price_precision=8,
        max_base_size=None,
    )


def _patch_module(ecel_module: ModuleType) -> bool:
    schema_cls = getattr(ecel_module, "ContractSchemaMap", None)
    if not isinstance(schema_cls, type):
        return False
    original_get_rule = getattr(schema_cls, "get_rule", None)
    if not callable(original_get_rule):
        return False
    if getattr(original_get_rule, _PATCHED_ATTR, False):
        return True

    def _get_rule_with_okx_synthetic(self: Any, broker: str, symbol: str):
        rule = original_get_rule(self, broker, symbol)
        if rule is not None:
            return rule
        broker_norm = _norm_broker(broker)
        sym = _norm_symbol(symbol)
        if broker_norm != "okx":
            return None
        synthetic = _synthetic_okx_rule(ecel_module, sym)
        if synthetic is None:
            return None
        try:
            self.upsert_rule(synthetic)
        except Exception:
            pass
        logger.critical(
            "ECEL_OKX_SYNTHETIC_CONTRACT_ADDED symbol=%s min_notional=$%.2f base_step=%s price_step=%s",
            sym,
            float(getattr(synthetic, "min_notional_usd", 0.0) or 0.0),
            getattr(synthetic, "base_step_size", None),
            getattr(synthetic, "price_step_size", None),
        )
        print(
            f"[NIJA-PRINT] ECEL_OKX_SYNTHETIC_CONTRACT_ADDED | symbol={sym} min_notional=${float(getattr(synthetic, 'min_notional_usd', 0.0) or 0.0):.2f}",
            flush=True,
        )
        return synthetic

    setattr(_get_rule_with_okx_synthetic, _PATCHED_ATTR, True)
    setattr(schema_cls, "get_rule", _get_rule_with_okx_synthetic)
    logger.warning("ECEL_OKX_SYNTHETIC_CONTRACT_PATCHED module=%s", ecel_module.__name__)
    print("[NIJA-PRINT] ECEL_OKX_SYNTHETIC_CONTRACT_PATCHED", flush=True)
    return True


def _patch_loaded() -> None:
    for name in ("bot.ecel_execution_compiler", "ecel_execution_compiler"):
        mod = sys.modules.get(name)
        if isinstance(mod, ModuleType):
            try:
                _patch_module(mod)
            except Exception as exc:  # noqa: BLE001
                logger.warning("ECEL_OKX_SYNTHETIC_CONTRACT_PATCH_FAILED module=%s err=%s", name, exc)


def install_import_hook() -> None:
    _patch_loaded()
    if getattr(builtins, "_NIJA_ECEL_OKX_SYNTHETIC_CONTRACT_IMPORT_HOOK_INSTALLED", False):
        return
    original_import = builtins.__import__

    def guarded_import(name: str, globals: Any = None, locals: Any = None, fromlist: Any = (), level: int = 0) -> Any:
        module = original_import(name, globals, locals, fromlist, level)
        if name in {"bot.ecel_execution_compiler", "ecel_execution_compiler"} or str(name).endswith("ecel_execution_compiler"):
            _patch_loaded()
        return module

    builtins.__import__ = guarded_import
    setattr(builtins, "_NIJA_ECEL_OKX_SYNTHETIC_CONTRACT_IMPORT_HOOK_INSTALLED", True)
    logger.warning("ECEL_OKX_SYNTHETIC_CONTRACT_INSTALL_COMPLETE")


def install() -> None:
    install_import_hook()
