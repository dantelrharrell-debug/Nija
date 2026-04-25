#!/usr/bin/env python3
"""
Map exchange minimum constraints vs NIJA runtime configuration.

This script is read-only and safe to run in production environments.
It uses Coinbase public product metadata via ECEL's public schema refresh.
"""

from __future__ import annotations

import os
import sys
from typing import Dict, List

try:
    from bot.ecel_execution_compiler import ContractSchemaMap
    from bot.exchange_constraints_enforcer import (
        COINBASE_MIN_ORDER_USD,
        GLOBAL_MIN_ORDER_USD,
    )
    from bot.broker_adapters import CoinbaseAdapter
except Exception:
    # Fallback for environments where root bot.py shadows the bot package.
    _repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _bot_dir = os.path.join(_repo_root, "bot")
    if _bot_dir not in sys.path:
        sys.path.insert(0, _bot_dir)

    from ecel_execution_compiler import ContractSchemaMap
    from exchange_constraints_enforcer import (
        COINBASE_MIN_ORDER_USD,
        GLOBAL_MIN_ORDER_USD,
    )
    from broker_adapters import CoinbaseAdapter


def _fmt(v: object) -> str:
    if isinstance(v, float):
        return f"{v:.8f}".rstrip("0").rstrip(".")
    return str(v)


def _get_symbols() -> List[str]:
    raw = os.getenv("NIJA_MIN_MAP_SYMBOLS", "BTC-USD,ETH-USD,SOL-USD,ADA-USD")
    return [s.strip().upper().replace("/", "-") for s in raw.split(",") if s.strip()]


def _build_config_snapshot() -> Dict[str, float]:
    env = os.environ
    return {
        "COINBASE_MIN_ORDER_USD": float(env.get("COINBASE_MIN_ORDER_USD", env.get("COINBASE_MIN_ORDER", "1.0"))),
        "COINBASE_OPERATIONAL_MIN_NOTIONAL_USD": float(
            env.get("COINBASE_OPERATIONAL_MIN_NOTIONAL_USD", str(CoinbaseAdapter.MIN_NOTIONAL_DEFAULT))
        ),
        "MIN_NOTIONAL_USD": float(env.get("MIN_NOTIONAL_USD", str(GLOBAL_MIN_ORDER_USD))),
        "COINBASE_MAX_POSITION_PCT": float(env.get("COINBASE_MAX_POSITION_PCT", "0.25")),
        "NIJA_LOW_CAPITAL_THRESHOLD": float(env.get("NIJA_LOW_CAPITAL_THRESHOLD", "50")),
        "NIJA_LOW_CAPITAL_POSITION_PCT": float(env.get("NIJA_LOW_CAPITAL_POSITION_PCT", "0.20")),
        "NIJA_LOW_CAPITAL_MIN_CONFIDENCE": float(env.get("NIJA_LOW_CAPITAL_MIN_CONFIDENCE", "0.45")),
    }


def main() -> int:
    symbols = _get_symbols()
    schema = ContractSchemaMap()
    refresh = schema.refresh_from_public_endpoints(target_broker="coinbase")
    config = _build_config_snapshot()

    print("\n=== NIJA: Exchange Minimums vs Config ===")
    print(f"Coinbase rules refreshed: {refresh.get('coinbase', 0)}")
    print("\n-- Config Snapshot --")
    for k, v in config.items():
        print(f"{k:40} {_fmt(v)}")

    print("\n-- Core Floors In Code --")
    print(f"exchange_constraints_enforcer.COINBASE_MIN_ORDER_USD: {_fmt(COINBASE_MIN_ORDER_USD)}")
    print(f"exchange_constraints_enforcer.GLOBAL_MIN_ORDER_USD:   {_fmt(GLOBAL_MIN_ORDER_USD)}")
    print(f"broker_adapters.CoinbaseAdapter.MIN_NOTIONAL_DEFAULT: {_fmt(CoinbaseAdapter.MIN_NOTIONAL_DEFAULT)}")

    print("\n-- Coinbase Public Product Rules --")
    headers = [
        "symbol",
        "exchange_min_notional",
        "exchange_min_base_size",
        "base_step",
        "price_step",
        "configured_operational_min",
        "effective_floor(max(exchange,operational,global))",
    ]
    print(" | ".join(headers))

    for symbol in symbols:
        rule = schema.get_rule("coinbase", symbol)
        if rule is None:
            print(f"{symbol} | N/A | N/A | N/A | N/A | {_fmt(config['COINBASE_OPERATIONAL_MIN_NOTIONAL_USD'])} | N/A")
            continue

        exchange_min_notional = float(rule.min_notional_usd)
        exchange_min_base_size = float(rule.min_base_size)
        base_step = float(rule.base_step_size)
        price_step = float(rule.price_step_size)

        configured_operational = config["COINBASE_OPERATIONAL_MIN_NOTIONAL_USD"]
        configured_global = config["MIN_NOTIONAL_USD"]
        effective_floor = max(exchange_min_notional, configured_operational, configured_global)

        print(
            " | ".join(
                [
                    symbol,
                    _fmt(exchange_min_notional),
                    _fmt(exchange_min_base_size),
                    _fmt(base_step),
                    _fmt(price_step),
                    _fmt(configured_operational),
                    _fmt(effective_floor),
                ]
            )
        )

    print("\nLegend: effective_floor is the practical minimum notional after applying your config policy on top of exchange rules.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
