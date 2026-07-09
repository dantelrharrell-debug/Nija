from __future__ import annotations

import builtins
import logging
import os
import sys
from dataclasses import replace
from functools import wraps
from types import ModuleType
from typing import Any, Optional

logger = logging.getLogger("nija.broker_native_quote_routing_patch")
_MARKER = "BROKER_NATIVE_QUOTE_ROUTING_PATCHED marker=20260709y"
_PATCHED_ATTR = "_nija_broker_native_quote_routing_20260709y"
_TRUTHY = {"1", "true", "yes", "on", "enabled", "y"}


def _truthy(name: str, default: bool = True) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in _TRUTHY


def _float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        amount = float(value)
        if amount != amount:
            return default
        return amount
    except Exception:
        return default


def _norm_broker(value: Any) -> str:
    text = str(value or "").strip().lower()
    if ":" in text:
        text = text.split(":")[-1]
    compact = text.replace("_", "").replace("-", "").replace(" ", "")
    aliases = {
        "okxbrokeradapter": "okx",
        "okxbroker": "okx",
        "okx": "okx",
        "coinbasebrokeradapter": "coinbase",
        "coinbasebroker": "coinbase",
        "coinbase": "coinbase",
        "krakenbrokeradapter": "kraken",
        "krakenbroker": "kraken",
        "kraken": "kraken",
    }
    return aliases.get(compact, text)


def _broker_from_request(request: Any) -> str:
    preferred = _norm_broker(getattr(request, "preferred_broker", ""))
    if preferred:
        return preferred
    meta = dict(getattr(request, "metadata", {}) or {})
    for key in ("broker_name", "selected_broker", "execution_broker", "broker"):
        label = _norm_broker(meta.get(key))
        if label:
            return label
    broker_client = meta.get("broker_client")
    if broker_client is not None:
        for value in (
            getattr(getattr(broker_client, "broker_type", None), "value", None),
            getattr(broker_client, "broker_type", None),
            getattr(broker_client, "NAME", None),
            getattr(broker_client, "name", None),
            broker_client.__class__.__name__,
        ):
            label = _norm_broker(value)
            if label:
                return label
    return ""


def _norm_symbol(value: Any) -> str:
    text = str(value or "").strip().upper().replace("/", "-").replace("_", "-").replace(":", "-")
    while "--" in text:
        text = text.replace("--", "-")
    if text.endswith("-USDTT"):
        text = text[:-6] + "-USDT"
    if text.endswith("-USDTC"):
        text = text[:-6] + "-USDC"
    return text


def _symbol_parts(symbol: str) -> tuple[str, str]:
    symbol = _norm_symbol(symbol)
    if "-" not in symbol:
        return symbol, ""
    base, quote = symbol.rsplit("-", 1)
    return base, quote


def _required_quote(size_usd: Any) -> float:
    requested = max(_float(size_usd, 0.0), 0.0)
    buffer_pct = max(0.0, min(_float(os.environ.get("NIJA_OKX_QUOTE_FUND_BUFFER_PCT"), 0.015), 0.20))
    return requested * (1.0 + buffer_pct)


def _extract_quote_from_mapping(payload: Any, quote: str) -> Optional[float]:
    quote = str(quote or "").upper()
    if not isinstance(payload, dict):
        return None

    for key in (quote, quote.lower()):
        if key in payload:
            entry = payload.get(key)
            if isinstance(entry, dict):
                for subkey in ("availBal", "available", "available_balance", "free", "cash", "balance", "amount", "eq", "equity"):
                    if subkey in entry:
                        return _float(entry.get(subkey), 0.0)
            return _float(entry, 0.0)

    total = 0.0
    found = False
    for container_key in ("data", "details", "balances", "accounts", "assets", "result"):
        nested = payload.get(container_key)
        if isinstance(nested, dict):
            amount = _extract_quote_from_mapping(nested, quote)
            if amount is not None:
                total += amount
                found = True
        elif isinstance(nested, (list, tuple)):
            for item in nested:
                if isinstance(item, dict):
                    currency = str(item.get("ccy") or item.get("currency") or item.get("asset") or item.get("symbol") or "").upper()
                    if currency == quote:
                        for subkey in ("availBal", "available", "available_balance", "free", "cash", "balance", "amount", "eq", "equity"):
                            if subkey in item:
                                total += _float(item.get(subkey), 0.0)
                                found = True
                                break
                    amount = _extract_quote_from_mapping(item, quote)
                    if amount is not None and currency != quote:
                        total += amount
                        found = True
    if found:
        return total
    return None


def _call_zero_arg(obj: Any, method_name: str) -> Any:
    fn = getattr(obj, method_name, None)
    if not callable(fn):
        return None
    try:
        return fn()
    except TypeError:
        return None
    except Exception as exc:
        logger.debug("OKX quote balance probe %s failed: %s", method_name, exc)
        return None


def _resolve_quote_balance(broker_client: Any, quote: str) -> Optional[float]:
    quote = str(quote or "").upper()
    if not quote:
        return None
    if broker_client is None:
        return None

    attr_names = (
        f"_available_{quote.lower()}",
        f"_last_known_{quote.lower()}",
        f"_spot_available_{quote.lower()}",
        f"_{quote.lower()}_available",
        f"available_{quote.lower()}",
    )
    for attr in attr_names:
        if hasattr(broker_client, attr):
            amount = _float(getattr(broker_client, attr), -1.0)
            if amount >= 0:
                return amount

    for attr in (
        "_balance_cache",
        "_last_balance_snapshot",
        "_last_account_inventory",
        "_last_raw_balance",
        "_last_balance_response",
        "_cached_balance_response",
    ):
        try:
            amount = _extract_quote_from_mapping(getattr(broker_client, attr, None), quote)
            if amount is not None:
                return amount
        except Exception:
            pass

    for method in (
        "get_spot_balances",
        "get_account_balances",
        "get_balances",
        "get_available_balances",
        "fetch_balance",
        "get_balance",
        "get_account_balance",
    ):
        payload = _call_zero_arg(broker_client, method)
        amount = _extract_quote_from_mapping(payload, quote)
        if amount is not None:
            return amount
    return None


def _native_symbol(symbol: str, broker: str) -> str:
    symbol = _norm_symbol(symbol)
    broker = _norm_broker(broker)
    if not symbol or "-" not in symbol:
        return symbol
    base, quote = symbol.rsplit("-", 1)
    if not base:
        return symbol
    if broker in {"coinbase", "kraken"} and quote == "USDT":
        return f"{base}-USD"
    if broker == "okx" and quote == "USD":
        return f"{base}-USDT"
    return symbol


def _replace_request(req: Any, **changes: Any) -> Any:
    try:
        return replace(req, **changes)
    except Exception:
        for key, value in changes.items():
            try:
                setattr(req, key, value)
            except Exception:
                pass
        return req


def _reroute_away_from_okx(request: Any, symbol: str, reason: str) -> Any:
    meta = dict(getattr(request, "metadata", {}) or {})
    for key in ("broker_client", "broker_name", "selected_broker", "execution_broker", "broker"):
        meta.pop(key, None)
    meta["okx_quote_reroute_reason"] = reason
    return _replace_request(request, symbol=symbol, preferred_broker=None, metadata=meta)


def _okx_quote_cash_available(request: Any, quote: str) -> tuple[bool, Optional[float], float, str]:
    meta = dict(getattr(request, "metadata", {}) or {})
    broker_client = meta.get("broker_client")
    required = _required_quote(getattr(request, "size_usd", 0.0))
    available = _resolve_quote_balance(broker_client, quote)
    if available is None:
        return False, None, required, f"okx_{quote.lower()}_quote_balance_unknown"
    if available + 1e-9 >= required:
        return True, available, required, "okx_quote_available"
    return False, available, required, f"okx_{quote.lower()}_quote_below_required_notional"


def _maybe_route_okx_buy_by_spendable_quote(request: Any, symbol: str, native: str, side: str) -> tuple[Any, str]:
    if not _truthy("NIJA_OKX_SPENDABLE_QUOTE_ROUTING_GUARD", True):
        return _replace_request(request, symbol=native), native
    side_l = str(side or "").lower()
    if side_l not in {"buy", "long"}:
        return _replace_request(request, symbol=native), native
    base, quote = _symbol_parts(symbol)
    if not base:
        return _replace_request(request, symbol=native), native

    if quote in {"USDT", "USDC"}:
        ok, available, required, reason = _okx_quote_cash_available(request, quote)
        if ok:
            logger.critical(
                "OKX_DIRECT_SPENDABLE_QUOTE_APPROVED marker=20260709y symbol=%s quote=%s available=%.8f required=%.8f",
                symbol,
                quote,
                float(available or 0.0),
                required,
            )
            return _replace_request(request, symbol=symbol), symbol
        logger.critical(
            "OKX_DIRECT_SPENDABLE_QUOTE_REROUTE marker=20260709y symbol=%s quote=%s available=%s required=%.8f reason=%s action=clear_okx_direct_broker_before_submit",
            symbol,
            quote,
            "unknown" if available is None else f"{available:.8f}",
            required,
            reason,
        )
        print(
            f"[NIJA-PRINT] OKX_DIRECT_SPENDABLE_QUOTE_REROUTE marker=20260709y symbol={symbol} quote={quote} reason={reason}",
            flush=True,
        )
        # Preserve the same symbol so the higher-level broker selector can decide
        # whether Coinbase/Kraken symbol normalization or another candidate is valid.
        return _reroute_away_from_okx(request, symbol, reason), symbol

    if quote != "USD":
        return _replace_request(request, symbol=native), native

    meta = dict(getattr(request, "metadata", {}) or {})
    broker_client = meta.get("broker_client")
    required = _required_quote(getattr(request, "size_usd", 0.0))
    usdt = _resolve_quote_balance(broker_client, "USDT")
    usdc = _resolve_quote_balance(broker_client, "USDC")

    if usdt is not None and usdt >= required:
        selected = f"{base}-USDT"
        logger.critical(
            "OKX_SPENDABLE_QUOTE_ROUTE_APPROVED marker=20260709y symbol=%s quote=USDT available=%.8f required=%.8f selected=%s",
            symbol,
            usdt,
            required,
            selected,
        )
        return _replace_request(request, symbol=selected), selected

    if usdc is not None and usdc >= required:
        selected = f"{base}-USDC"
        logger.critical(
            "OKX_SPENDABLE_QUOTE_ROUTE_APPROVED marker=20260709y symbol=%s quote=USDC available=%.8f required=%.8f selected=%s",
            symbol,
            usdc,
            required,
            selected,
        )
        return _replace_request(request, symbol=selected), selected

    if usdt is None and usdc is None and not _truthy("NIJA_OKX_ALLOW_UNKNOWN_QUOTE_BALANCE_BUYS", False):
        reason = "okx_quote_balance_unknown_for_usdt_usdc_buy"
    elif (usdt or 0.0) <= 0 and (usdc or 0.0) <= 0:
        reason = "okx_no_spendable_usdt_or_usdc_for_buy"
    else:
        reason = "okx_spendable_quote_below_required_notional"

    logger.critical(
        "OKX_SPENDABLE_QUOTE_REROUTE marker=20260709y symbol=%s native_candidate=%s side=%s required_quote=%.8f usdt_available=%s usdc_available=%s reason=%s action=clear_okx_direct_broker",
        symbol,
        native,
        side,
        required,
        "unknown" if usdt is None else f"{usdt:.8f}",
        "unknown" if usdc is None else f"{usdc:.8f}",
        reason,
    )
    print(
        f"[NIJA-PRINT] OKX_SPENDABLE_QUOTE_REROUTE marker=20260709y symbol={symbol} required={required:.2f} reason={reason}",
        flush=True,
    )
    return _reroute_away_from_okx(request, symbol, reason), symbol


def _patch_pipeline(module: ModuleType) -> bool:
    cls = getattr(module, "ExecutionPipeline", None)
    if not isinstance(cls, type):
        return False
    original = getattr(cls, "execute", None)
    if not callable(original) or getattr(original, _PATCHED_ATTR, False):
        return bool(getattr(original, _PATCHED_ATTR, False))

    @wraps(original)
    def execute(self: Any, request: Any, *args: Any, **kwargs: Any):
        broker = _broker_from_request(request)
        symbol = _norm_symbol(getattr(request, "symbol", ""))
        side = str(getattr(request, "side", "") or "").strip().lower()
        native = _native_symbol(symbol, broker)
        if broker == "okx":
            request, native = _maybe_route_okx_buy_by_spendable_quote(request, symbol, native, side)
        elif broker in {"coinbase", "kraken"} and native and native != symbol:
            request = _replace_request(request, symbol=native)

        if broker in {"coinbase", "kraken", "okx"} and native and native != symbol:
            logger.critical(
                "BROKER_NATIVE_QUOTE_ROUTING_REPAIRED marker=20260709y broker=%s side=%s old_symbol=%s new_symbol=%s",
                broker,
                side,
                symbol,
                native,
            )
            print(
                f"[NIJA-PRINT] BROKER_NATIVE_QUOTE_ROUTING_REPAIRED marker=20260709y broker={broker} old_symbol={symbol} new_symbol={native}",
                flush=True,
            )
        return original(self, request, *args, **kwargs)

    setattr(execute, _PATCHED_ATTR, True)
    setattr(cls, "execute", execute)
    logger.warning("%s class=ExecutionPipeline", _MARKER)
    print("[NIJA-PRINT] BROKER_NATIVE_QUOTE_ROUTING_PATCHED marker=20260709y", flush=True)
    return True


def _try_patch_loaded() -> bool:
    patched = False
    for name in ("bot.execution_pipeline", "execution_pipeline"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            patched = _patch_pipeline(module) or patched
    return patched


def install_import_hook() -> None:
    _try_patch_loaded()
    if getattr(builtins, "_NIJA_BROKER_NATIVE_QUOTE_ROUTING_HOOK_V20260709Y", False):
        return
    original_import = builtins.__import__

    def guarded_import(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
        module = original_import(name, globals, locals, fromlist, level)
        try:
            if name.endswith("execution_pipeline"):
                _try_patch_loaded()
            else:
                _try_patch_loaded()
        except Exception as exc:
            logger.warning("BROKER_NATIVE_QUOTE_ROUTING hook failed name=%s error=%s", name, exc)
        return module

    builtins.__import__ = guarded_import
    setattr(builtins, "_NIJA_BROKER_NATIVE_QUOTE_ROUTING_HOOK_V20260709Y", True)
    logger.warning("BROKER_NATIVE_QUOTE_ROUTING_IMPORT_HOOK marker=20260709y")


def install() -> None:
    install_import_hook()
