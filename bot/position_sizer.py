"""
NIJA Position Sizer
===================

Single-source position sizing helpers for platform and user accounts.
This module deliberately avoids importing trading_strategy at import time: that
import path is circular during startup and caused callers to fall back to a hard
$10 minimum.  Runtime floors are now resolved directly from environment values.
"""

from __future__ import annotations

import logging
import math
import os
from typing import Dict, Iterable, Optional

logger = logging.getLogger("nija.position_sizer")


def _float_env(names: Iterable[str], default: float) -> float:
    for name in names:
        raw = os.getenv(name)
        if raw is None or str(raw).strip() == "":
            continue
        try:
            value = float(raw)
            if value > 0:
                return value
        except (TypeError, ValueError):
            logger.warning("Invalid numeric env %s=%r; ignoring", name, raw)
    return float(default)


# Single source of truth for micro-cap floors.  The default is intentionally
# $2.00 to match NIJA's current live micro-cap profile; exchange/order compiler
# layers can still enforce higher venue-specific minimums when required.
GLOBAL_MIN_TRADE = _float_env(
    ("MIN_POSITION_USD", "MIN_TRADE_USD", "MIN_NOTIONAL_OVERRIDE", "GLOBAL_MIN_TRADE"),
    2.0,
)
MIN_POSITION_USD: float = GLOBAL_MIN_TRADE

KRAKEN_MIN_TRADE_USD: float = max(
    _float_env(("KRAKEN_MIN_NOTIONAL_USD", "KRAKEN_MIN_ORDER_USD"), GLOBAL_MIN_TRADE),
    GLOBAL_MIN_TRADE,
)
COINBASE_MIN_TRADE_USD: float = _float_env(
    ("COINBASE_MIN_ORDER_USD", "COINBASE_MIN_ORDER"),
    GLOBAL_MIN_TRADE,
)
OKX_MIN_TRADE_USD: float = _float_env(("OKX_MIN_ORDER_USD", "OKX_MIN_NOTIONAL_USD"), GLOBAL_MIN_TRADE)
BINANCE_MIN_TRADE_USD: float = _float_env(("BINANCE_MIN_ORDER_USD", "BINANCE_MIN_NOTIONAL_USD"), GLOBAL_MIN_TRADE)

POSITION_SIZE_FEE_BUFFER_FACTOR = 1.02

EXCHANGE_MIN_TRADE_USD = {
    "kraken": KRAKEN_MIN_TRADE_USD,
    "coinbase": COINBASE_MIN_TRADE_USD,
    "okx": OKX_MIN_TRADE_USD,
    "binance": BINANCE_MIN_TRADE_USD,
}

SYMBOL_MIN_TRADE_USD: dict[str, float] = {
    "MOVR": 5.0,
    "HBAR": 5.0,
    "DOT": 5.0,
    "BAND": 5.0,
    "NMR": 5.0,
    "RLC": 5.0,
}

MIN_BASE_SIZES = {
    "BTC": 0.000001,
    "ETH": 0.0001,
    "BNB": 0.001,
    "SOL": 0.01,
    "AVAX": 0.01,
    "LINK": 0.01,
    "DOT": 0.01,
    "LTC": 0.001,
    "BCH": 0.001,
    "UNI": 0.01,
    "AAVE": 0.001,
    "ATOM": 0.01,
    "FIL": 0.01,
    "ICP": 0.01,
    "XRP": 1.0,
    "ADA": 1.0,
    "DOGE": 1.0,
    "MATIC": 1.0,
    "XLM": 1.0,
    "ALGO": 1.0,
    "VET": 1.0,
    "HBAR": 1.0,
    "EOS": 1.0,
    "TRX": 1.0,
    "CHZ": 1.0,
    "XDC": 100.0,
    "SHIB": 1_000_000,
    "PEPE": 1_000_000,
    "BONK": 1_000_000,
    "MANA": 1.0,
}


def _extract_base_currency(symbol: str) -> str:
    if not symbol:
        return ""
    symbol = str(symbol).upper().strip()
    if "-" in symbol or "/" in symbol:
        return symbol.split("-")[0].split("/")[0]
    for suffix in ("USDT", "USDC", "USD", "BTC", "ETH"):
        if symbol.endswith(suffix) and len(symbol) > len(suffix):
            return symbol[: -len(suffix)]
    return symbol


def get_min_base_size(symbol: str) -> float:
    return MIN_BASE_SIZES.get(_extract_base_currency(symbol), 0.0001)


def get_exchange_min_trade_size(exchange: str = "coinbase", symbol: str = "") -> float:
    exchange_lower = str(exchange or "").lower()
    exchange_min = EXCHANGE_MIN_TRADE_USD.get(exchange_lower, MIN_POSITION_USD)
    if symbol:
        base = _extract_base_currency(symbol)
        return max(exchange_min, SYMBOL_MIN_TRADE_USD.get(base, 0.0))
    return exchange_min


def calculate_user_position_size(
    platform_size: float,
    platform_balance: float,
    user_balance: float,
    size_type: str = "quote",
    symbol: Optional[str] = None,
    min_position_usd: float = MIN_POSITION_USD,
) -> Dict:
    try:
        if platform_balance <= 0:
            return {"size": 0, "size_type": size_type, "valid": False, "reason": f"Invalid master balance: {platform_balance}", "scale_factor": 0}
        if user_balance <= 0:
            return {"size": 0, "size_type": size_type, "valid": False, "reason": f"User balance too low: ${user_balance:.2f}", "scale_factor": 0}
        if platform_size <= 0:
            return {"size": 0, "size_type": size_type, "valid": False, "reason": f"Invalid master size: {platform_size}", "scale_factor": 0}

        scale_factor = user_balance / platform_balance
        user_size = platform_size * scale_factor

        logger.info("📊 Position Sizing Calculation:")
        logger.info("   Platform: $%.2f balance, %s size (%s)", platform_balance, platform_size, size_type)
        logger.info("   User: $%.2f balance", user_balance)
        logger.info("   Scale Factor: %.4f (%.2f%%)", scale_factor, scale_factor * 100)
        logger.info("   Calculated User Size: %s (%s)", user_size, size_type)

        if size_type == "quote":
            fee_adjusted_cap = math.floor((user_balance / POSITION_SIZE_FEE_BUFFER_FACTOR) * 100) / 100
            if user_size > fee_adjusted_cap:
                logger.info("   📉 Size capped: $%.2f → $%.2f", user_size, fee_adjusted_cap)
                user_size = fee_adjusted_cap
            if user_size < min_position_usd:
                return {
                    "size": user_size,
                    "size_type": size_type,
                    "valid": False,
                    "reason": f"Position too small: ${user_size:.2f} < ${min_position_usd:.2f} minimum",
                    "scale_factor": scale_factor,
                }
        elif size_type == "base" and symbol:
            min_base = get_min_base_size(symbol)
            base_currency = _extract_base_currency(symbol)
            if user_size < min_base:
                return {
                    "size": user_size,
                    "size_type": size_type,
                    "valid": False,
                    "reason": f"Position too small: {user_size} < {min_base} {base_currency} minimum",
                    "scale_factor": scale_factor,
                }

        return {"size": user_size, "size_type": size_type, "valid": True, "reason": "Position size valid", "scale_factor": scale_factor}
    except Exception as exc:
        logger.exception("❌ Error calculating position size: %s", exc)
        return {"size": 0, "size_type": size_type, "valid": False, "reason": f"Calculation error: {exc}", "scale_factor": 0}


def calculate_position_size(
    account_balance: float,
    entry_price: float,
    stop_loss_pct: float,
    take_profit_pct: float,
    atr_pct: float,
    win_rate: float = 0.55,
    broker: str = "kraken",
    max_risk_pct: float = 0.01,
    max_position_pct: float = 0.40,
) -> float:
    min_trade = get_exchange_min_trade_size(broker)

    fee_rate = 0.0026 * 2
    spread = 0.004
    slippage = 0.002
    total_cost = fee_rate + spread + slippage

    expected_net_profit = take_profit_pct - total_cost
    if expected_net_profit <= 0.012:
        logger.info(
            "calculate_position_size: trade VETOED — net profit %.2f %% ≤ 1.20 %% (tp=%.2f %%, cost=%.2f %%)",
            expected_net_profit * 100,
            take_profit_pct * 100,
            total_cost * 100,
        )
        return 0.0

    risk_amount = account_balance * max_risk_pct
    effective_sl = stop_loss_pct + total_cost
    if effective_sl <= 0:
        return 0.0

    position_size_risk = risk_amount / effective_sl
    volatility_scalar = min(1.0, 0.02 / atr_pct) if atr_pct > 0 else 1.0
    position_size_vol = position_size_risk * volatility_scalar

    edge = (win_rate * take_profit_pct) - ((1.0 - win_rate) * stop_loss_pct)
    variance = take_profit_pct ** 2
    kelly_fraction = max(0.0, min(edge / variance if variance > 0 else 0.0, 0.25))
    position_size_kelly = account_balance * kelly_fraction

    raw_size = min(position_size_vol, position_size_kelly, account_balance * max_position_pct)
    final_size = max(raw_size, min_trade)
    cap = account_balance * max_position_pct
    if final_size > cap:
        final_size = cap
    final_size = math.floor(final_size * 100) / 100

    logger.debug(
        "calculate_position_size: balance=$%.2f tp=%.2f%% sl=%.2f%% atr=%.2f%% → risk=$%.2f vol=$%.2f kelly=$%.2f → final=$%.2f",
        account_balance,
        take_profit_pct * 100,
        stop_loss_pct * 100,
        atr_pct * 100,
        position_size_risk,
        position_size_vol,
        position_size_kelly,
        final_size,
    )
    return final_size


def validate_position_size(
    size: float,
    size_type: str,
    symbol: Optional[str] = None,
    min_position_usd: float = MIN_POSITION_USD,
) -> Dict:
    try:
        if size <= 0:
            return {"valid": False, "reason": "Size must be positive"}
        if size_type == "quote" and size < min_position_usd:
            return {"valid": False, "reason": f"Size ${size:.2f} below minimum ${min_position_usd:.2f}"}
        if size_type == "base" and symbol:
            min_base = get_min_base_size(symbol)
            base_currency = _extract_base_currency(symbol)
            if size < min_base:
                return {"valid": False, "reason": f"Size {size} {base_currency} below minimum {min_base}"}
        return {"valid": True, "reason": "Valid position size"}
    except Exception as exc:
        logger.error("❌ Error validating position size: %s", exc)
        return {"valid": False, "reason": f"Validation error: {exc}"}


def round_to_exchange_precision(size: float, symbol: str, size_type: str = "quote") -> float:
    try:
        if size_type == "quote":
            return round(size, 2)
        if size_type == "base" and symbol:
            base_currency = _extract_base_currency(symbol)
            precision_map = {
                "BTC": 8,
                "ETH": 6,
                "SOL": 4,
                "XRP": 2,
                "ADA": 2,
                "DOGE": 2,
                "AVAX": 4,
                "DOT": 4,
                "LINK": 4,
                "LTC": 8,
            }
            return round(size, precision_map.get(base_currency, 4))
        return size
    except Exception as exc:
        logger.warning("⚠️  Error rounding position size: %s, returning original", exc)
        return size
