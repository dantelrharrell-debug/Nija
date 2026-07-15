"""Recover broker-verified cost basis for held Kraken positions.

Kraken balance snapshots expose quantities but not acquisition cost.  The exit
supervisor therefore receives adoption/display prices that the final safety guard
correctly refuses to trust.  This module reconstructs the outstanding weighted
average cost from the exact account's private TradesHistory and annotates each
held position with explicit provenance before profit-taking is evaluated.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from functools import wraps
from typing import Any, Iterable, Mapping, MutableMapping

logger = logging.getLogger("nija.kraken_verified_cost_basis")
_MARKER = "20260715-kraken-cost-basis-v1"
_LOCK = threading.RLock()
_INSTALLED = False
_CACHE: dict[int, tuple[float, dict[str, tuple[float, float]]]] = {}


def _f(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
        return default if parsed != parsed else parsed
    except Exception:
        return default


def _base_from_pair(pair: Any) -> str:
    text = str(pair or "").upper().replace("/", "").replace("-", "").replace("_", "")
    for quote in ("ZUSD", "USD", "USDT", "USDC", "ZEUR", "EUR"):
        if text.endswith(quote) and len(text) > len(quote):
            text = text[: -len(quote)]
            break
    aliases = {"XXBT": "XBT", "BTC": "XBT", "XETH": "ETH"}
    return aliases.get(text, text.lstrip("XZ"))


def _position_base(runtime: Any, position: Mapping[str, Any]) -> str:
    symbol = runtime._normalise_symbol(position.get("symbol"))
    base = symbol.split("-", 1)[0] if "-" in symbol else symbol
    return _base_from_pair(base)


def _private_trades(broker: Any) -> Mapping[str, Any]:
    caller = getattr(broker, "_kraken_api_call", None)
    if callable(caller):
        payload = caller("TradesHistory", {"type": "all", "trades": True})
    else:
        api = getattr(broker, "api", None)
        query_private = getattr(api, "query_private", None)
        if not callable(query_private):
            return {}
        payload = query_private("TradesHistory", {"type": "all", "trades": True})
    if not isinstance(payload, Mapping) or payload.get("error"):
        return {}
    result = payload.get("result")
    trades = result.get("trades") if isinstance(result, Mapping) else None
    return trades if isinstance(trades, Mapping) else {}


def _reconstruct(trades: Mapping[str, Any]) -> dict[str, tuple[float, float]]:
    """Return base -> (remaining quantity, fee-inclusive weighted cost)."""
    inventory: dict[str, list[float]] = {}
    rows = [row for row in trades.values() if isinstance(row, Mapping)]
    rows.sort(key=lambda row: _f(row.get("time")))
    for row in rows:
        base = _base_from_pair(row.get("pair"))
        qty = abs(_f(row.get("vol")))
        price = _f(row.get("price"))
        cost = abs(_f(row.get("cost"), qty * price))
        fee = abs(_f(row.get("fee")))
        if not base or qty <= 0 or price <= 0:
            continue
        state = inventory.setdefault(base, [0.0, 0.0])
        side = str(row.get("type") or "").lower()
        if side == "buy":
            state[0] += qty
            state[1] += cost + fee
        elif side == "sell" and state[0] > 0:
            avg = state[1] / state[0]
            removed = min(qty, state[0])
            state[0] -= removed
            state[1] = max(0.0, state[1] - removed * avg)
    return {
        base: (qty, total_cost / qty)
        for base, (qty, total_cost) in inventory.items()
        if qty > 1e-12 and total_cost > 0
    }


def _basis_map(broker: Any, *, force: bool = False) -> dict[str, tuple[float, float]]:
    ttl = max(15.0, _f(os.environ.get("NIJA_KRAKEN_COST_BASIS_CACHE_TTL_S"), 60.0))
    now = time.time()
    cached = _CACHE.get(id(broker))
    if not force and cached and now - cached[0] < ttl:
        return cached[1]
    basis = _reconstruct(_private_trades(broker))
    _CACHE[id(broker)] = (now, basis)
    return basis


def _already_verified(position: Mapping[str, Any]) -> bool:
    return bool(position.get("cost_basis_verified") is True and _f(position.get("entry_price")) > 0)


def _patch_runtime(runtime: Any) -> bool:
    current = getattr(runtime, "_position_rows", None)
    if not callable(current) or getattr(current, "_nija_kraken_verified_basis_v1", False):
        return bool(getattr(current, "_nija_kraken_verified_basis_v1", False))

    @wraps(current)
    def position_rows(broker: Any) -> Iterable[MutableMapping[str, Any]]:
        basis = _basis_map(broker)
        account = runtime._identity(broker)
        for raw in current(broker):
            position = dict(raw) if isinstance(raw, Mapping) else raw
            if not isinstance(position, MutableMapping):
                continue
            if _already_verified(position):
                yield position
                continue
            base = _position_base(runtime, position)
            held = runtime._quantity(position)
            recovered_qty, avg = basis.get(base, (0.0, 0.0))
            tolerance = max(1e-8, held * 0.02)
            if held > 0 and avg > 0 and recovered_qty + tolerance >= held:
                position["entry_price"] = avg
                position["avg_entry_price"] = avg
                position["cost_basis_verified"] = True
                position["entry_price_source"] = "kraken_private_trades_history_weighted_average"
                position["cost_basis_provenance"] = "kraken:TradesHistory"
                position["auto_exit_blocked"] = False
                position.pop("auto_exit_block_reason", None)
                logger.critical(
                    "KRAKEN_COST_BASIS_VERIFIED marker=%s account=%s symbol=%s held_qty=%.8f history_qty=%.8f entry=$%.8f",
                    _MARKER, account, position.get("symbol"), held, recovered_qty, avg,
                )
            else:
                position["cost_basis_verified"] = False
                position["auto_exit_blocked"] = True
                position["auto_exit_block_reason"] = "kraken_trade_history_insufficient_for_current_holding"
                logger.warning(
                    "KRAKEN_COST_BASIS_UNRESOLVED marker=%s account=%s symbol=%s held_qty=%.8f history_qty=%.8f",
                    _MARKER, account, position.get("symbol"), held, recovered_qty,
                )
            yield position

    position_rows._nija_kraken_verified_basis_v1 = True  # type: ignore[attr-defined]
    position_rows.__wrapped__ = current  # type: ignore[attr-defined]
    runtime._position_rows = position_rows
    return True


def install() -> bool:
    global _INSTALLED
    with _LOCK:
        if _INSTALLED:
            return True
        try:
            from bot import kraken_all_account_exit_runtime_patch as runtime
        except Exception:
            import kraken_all_account_exit_runtime_patch as runtime  # type: ignore
        installer = getattr(runtime, "install_import_hook", None)
        if callable(installer):
            installer()
        if not _patch_runtime(runtime):
            raise RuntimeError("kraken_exit_runtime_position_rows_not_patchable")
        os.environ["NIJA_KRAKEN_VERIFIED_COST_BASIS_RECOVERY_INSTALLED"] = "1"
        _INSTALLED = True
        logger.critical(
            "KRAKEN_VERIFIED_COST_BASIS_RECOVERY_INSTALLED marker=%s source=private_trades_history fail_closed=true",
            _MARKER,
        )
        return True


__all__ = ["install", "_reconstruct", "_basis_map", "_patch_runtime", "_base_from_pair"]
