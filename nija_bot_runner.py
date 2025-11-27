#!/usr/bin/env python3
"""
Small wrapper to start the trading loop in the container.
This avoids import-time side effects in nija_client when gunicorn imports modules.
"""
from nija_client import start_trading_loop

if __name__ == "__main__":
    # blocking; logs handled by nija_client logger
    start_trading_loop(poll_seconds=5)
