"""Runtime position classification for Coinbase crypto balances.

Coinbase portfolio breakdown can report USD as available cash and separate
crypto holdings such as ADA/ATOM/ETH.  Those crypto balances are not held USD or
open-order locks, but they are active exposure and should be visible to NIJA's
position/risk/exit layers.
"""

from __future__ import annotations

import builtins
import logging
from functools import wraps
from typing import Any, Dict, Iterable

logger = logging.getLogger("nija.coinbase_position_patch")
_PATCHED_ATTR = "__nija_coinbase_position_patch__"
_CASH_ASSETS = {"USD", "USDC", "USDT"}


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return default


def _position_from_crypto(symbol: str, qty: float, price: float = 0.0) -> Dict[str, Any]:
    base = str(symbol or "").upper().strip()
    return {
        "symbol": f"{base}-USD",
        "asset": base,
        "currency": base,
        "quantity": qty,
        "side": "long",
        "current_price": price,
        "size_usd": qty * price if price > 0 else 0.0,
        "source": "coinbase.crypto_balance",
        "status": "active_position",
    }


def _extract_crypto_positions(payload: Any) -> list[Dict[str, Any]]:
    positions: list[Dict[str, Any]] = []
    if not isinstance(payload, dict):
        return positions
    crypto = payload.get("crypto") or payload.get("crypto_balances") or payload.get("holdings")
    if isinstance(crypto, dict):
        iterable: Iterable[tuple[Any, Any]] = crypto.items()
    elif isinstance(crypto, list):
        iterable = []
        rows = []
        for row in crypto:
            if isinstance(row, dict):
                asset = row.get("asset") or row.get("currency") or row.get("symbol")
                qty = row.get("quantity") or row.get("balance") or row.get("amount")
                rows.append((asset, qty))
        iterable = rows
    else:
        iterable = []
    for asset, raw_qty in iterable:
        base = str(asset or "").upper().strip()
        qty = _safe_float(raw_qty)
        if not base or base in _CASH_ASSETS or qty <= 0:
            continue
        positions.append(_position_from_crypto(base, qty))
    return positions


def _call_possible_balance_methods(instance: Any) -> dict:
    for method_name in ("get_portfolio_breakdown", "get_account_balance", "get_balance_snapshot", "get_balances"):
        method = getattr(instance, method_name, None)
        if not callable(method):
            continue
        try:
            try:
                value = method(verbose=False)
            except TypeError:
                value = method()
            if isinstance(value, dict):
                return value
            # Some balance methods log and return float; then inspect cached fields.
            for attr in ("_last_raw_balances", "last_raw_balances", "_portfolio_breakdown", "portfolio_breakdown"):
                cached = getattr(instance, attr, None)
                if isinstance(cached, dict):
                    return cached
        except Exception as exc:
            logger.debug("coinbase position balance probe skipped method=%s error=%s", method_name, exc)
    for attr in ("_last_raw_balances", "last_raw_balances", "_portfolio_breakdown", "portfolio_breakdown"):
        cached = getattr(instance, attr, None)
        if isinstance(cached, dict):
            return cached
    return {}


def _sync_positions_to_tracker(instance: Any, positions: list[Dict[str, Any]]) -> None:
    if not positions:
        return
    for tracker_attr in ("position_tracker", "_position_tracker", "tracker"):
        tracker = getattr(instance, tracker_attr, None)
        if tracker is None:
            continue
        for pos in positions:
            for method_name in ("add_position", "record_position", "sync_position", "update_position"):
                method = getattr(tracker, method_name, None)
                if not callable(method):
                    continue
                try:
                    method(pos)
                    break
                except TypeError:
                    try:
                        method(pos.get("symbol"), pos.get("quantity"), pos.get("current_price", 0.0))
                        break
                    except Exception:
                        continue
                except Exception:
                    continue


def _patch_coinbase_class(cls: type) -> bool:
    if getattr(cls, _PATCHED_ATTR, False):
        return True

    original_get_positions = getattr(cls, "get_positions", None)

    def get_positions(self: Any):
        existing = []
        if callable(original_get_positions):
            try:
                result = original_get_positions(self)
                if isinstance(result, list):
                    existing.extend(result)
            except Exception as exc:
                logger.warning("COINBASE_POSITION_CLASSIFICATION original get_positions failed: %s", exc)
        payload = _call_possible_balance_methods(self)
        crypto_positions = _extract_crypto_positions(payload)
        seen = {str(p.get("symbol", "")).upper() for p in existing if isinstance(p, dict)}
        for pos in crypto_positions:
            if str(pos.get("symbol", "")).upper() not in seen:
                existing.append(pos)
        if crypto_positions:
            _sync_positions_to_tracker(self, crypto_positions)
            logger.warning(
                "COINBASE_CRYPTO_POSITIONS_CLASSIFIED count=%d symbols=%s",
                len(crypto_positions),
                ",".join(str(p.get("symbol")) for p in crypto_positions),
            )
        return existing

    setattr(cls, "get_positions", get_positions)

    original_connect = getattr(cls, "connect", None)
    if callable(original_connect):
        @wraps(original_connect)
        def connect(self: Any, *args: Any, **kwargs: Any):
            result = original_connect(self, *args, **kwargs)
            try:
                positions = get_positions(self)
                if positions:
                    logger.warning(
                        "COINBASE_STARTUP_POSITION_SYNC positions=%d symbols=%s",
                        len(positions),
                        ",".join(str(p.get("symbol")) for p in positions if isinstance(p, dict)),
                    )
            except Exception as exc:
                logger.warning("COINBASE_STARTUP_POSITION_SYNC_ERROR error=%s", exc)
            return result
        setattr(cls, "connect", connect)

    setattr(cls, _PATCHED_ATTR, True)
    logger.warning("COINBASE_POSITION_CLASSIFICATION_PATCHED class=%s", cls.__name__)
    return True


def _patch_module(module: Any) -> bool:
    patched = False
    for name in dir(module):
        if "coinbase" not in name.lower():
            continue
        obj = getattr(module, name, None)
        if isinstance(obj, type):
            patched = _patch_coinbase_class(obj) or patched
    return patched


def install_import_hook() -> None:
    import sys

    for name, module in list(sys.modules.items()):
        if name.endswith(("broker_manager", "coinbase_broker", "execution_engine")):
            try:
                if _patch_module(module):
                    return
            except Exception:
                continue

    if getattr(builtins, "_NIJA_COINBASE_POSITION_PATCH_HOOK_INSTALLED", False):
        return

    original_import = builtins.__import__

    def guarded_import(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
        module = original_import(name, globals, locals, fromlist, level)
        if name.endswith(("broker_manager", "coinbase_broker", "execution_engine")):
            try:
                if _patch_module(module):
                    builtins.__import__ = original_import
                    setattr(builtins, "_NIJA_COINBASE_POSITION_PATCH_HOOK_INSTALLED", False)
            except Exception as exc:
                logger.warning("Coinbase position runtime patch failed: %s", exc)
        return module

    builtins.__import__ = guarded_import
    setattr(builtins, "_NIJA_COINBASE_POSITION_PATCH_HOOK_INSTALLED", True)
