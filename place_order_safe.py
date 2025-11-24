#!/usr/bin/env python3
"""
Safe order placement CLI.

- Requires MODE==LIVE and --confirm flag to actually send an order.
- Otherwise prints dry-run diagnostics and exits.
- Reads Coinbase config from environment variables.

Usage examples:
  MODE=DRY_RUN COINBASE_API_KEY=... COINBASE_API_SECRET=... python place_order_safe.py --product_id BTC-USD --side buy --size 0.001
  MODE=LIVE COINBASE_API_KEY=... COINBASE_API_SECRET=... python place_order_safe.py --product_id BTC-USD --side buy --size 0.001 --confirm
"""
import os
import argparse
import logging
from typing import Optional

from nija_client import CoinbaseClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("place_order_safe")


def main():
    parser = argparse.ArgumentParser(description="Safe order placement script (requires MODE=LIVE and --confirm).")
    parser.add_argument("--product_id", required=True, help="Product id, e.g. BTC-USD or ETH-USD")
    parser.add_argument("--side", required=True, choices=("buy", "sell"), help="buy or sell")
    parser.add_argument("--size", required=True, type=float, help="size (amount) to trade")
    parser.add_argument("--confirm", action="store_true", help="Confirm to actually place the order when MODE=LIVE")
    args = parser.parse_args()

    mode = os.getenv("MODE", "DRY_RUN")
    logger.info(f"MODE={mode}")

    client = CoinbaseClient()
    adapter_name = getattr(client.adapter, "client_name", None)
    logger.info(f"Detected adapter: {adapter_name}")

    connected = client.is_connected()
    logger.info(f"Connected (accounts fetched): {connected}")

    if mode != "LIVE":
        logger.info("Application is NOT in LIVE mode. This is a DRY_RUN. No order will be placed.")
        return

    if not args.confirm:
        logger.info("Order requires --confirm to run in LIVE mode. Aborting.")
        return

    if not connected:
        logger.error("Client not connected or no accounts available. Aborting live order.")
        return

    logger.info(f"Placing market order: {args.side} {args.size} {args.product_id}")
    resp = client.place_market_order(args.product_id, args.side, args.size)
    logger.info(f"Order response: {resp}")


if __name__ == "__main__":
    main()
