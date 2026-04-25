#!/usr/bin/env python3
"""Minimal reproduction: bypass FSM and directly start the trading loop.

Goal
----
Isolate whether the trading state machine is the only blocker by:
1) bypassing FSM checks inside the core loop, and
2) directly starting the trading loop thread.

Usage
-----
python3 minimal_repro_bypass_fsm.py --allow-live --duration-seconds 120

Notes
-----
- This can execute real trades if credentials are valid and live mode is enabled.
- Set credentials and runtime env vars in the same shell before running.
"""

from __future__ import annotations

import argparse
import os
import sys
import time


REQUIRED_ENV = (
    "KRAKEN_PLATFORM_API_KEY",
    "KRAKEN_PLATFORM_API_SECRET",
)


def _require_env() -> None:
    missing = [k for k in REQUIRED_ENV if not os.getenv(k)]
    if missing:
        raise RuntimeError(
            "Missing required environment variables: " + ", ".join(missing)
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Bypass FSM and directly start NIJA trading loop for reproduction testing."
    )
    parser.add_argument(
        "--allow-live",
        action="store_true",
        help="Required acknowledgement: this test may execute live trades.",
    )
    parser.add_argument(
        "--duration-seconds",
        type=int,
        default=120,
        help="How long to run before requesting loop stop.",
    )
    args = parser.parse_args()

    if not args.allow_live:
        print("Refusing to run without --allow-live acknowledgement.")
        return 2

    _require_env()

    # Repro conditions requested: bypass FSM and run loop directly.
    os.environ.setdefault("LIVE_CAPITAL_VERIFIED", "true")
    os.environ.setdefault("FORCE_TRADE_MODE", "true")
    os.environ.setdefault("FORCE_TRADE", "true")
    os.environ["SUPERVISOR_MODE"] = "false"

    print("=" * 72)
    print("MINIMAL REPRO: BYPASS FSM + DIRECT CORE LOOP START")
    print("=" * 72)
    print(f"LIVE_CAPITAL_VERIFIED={os.getenv('LIVE_CAPITAL_VERIFIED')}")
    print(f"SUPERVISOR_MODE={os.getenv('SUPERVISOR_MODE')}")
    print(f"FORCE_TRADE_MODE={os.getenv('FORCE_TRADE_MODE')}")
    print(f"DURATION={args.duration_seconds}s")
    print("=" * 72)

    # Imports after env setup so module init sees final values.
    from bot.multi_account_broker_manager import (  # pylint: disable=import-error
        multi_account_broker_manager,
    )
    from bot.trading_strategy import TradingStrategy  # pylint: disable=import-error
    import bot.nija_core_loop as nija_core_loop  # pylint: disable=import-error

    print("[1/4] Initializing platform brokers...")
    broker_results = multi_account_broker_manager.initialize_platform_brokers()

    print("[2/4] Connecting configured user brokers...")
    connected_user_brokers = multi_account_broker_manager.connect_users_from_config()

    print("[3/4] Building strategy...")
    strategy = TradingStrategy(
        broker_results=broker_results if broker_results else None,
        connected_user_brokers=connected_user_brokers if connected_user_brokers else None,
    )

    print("[4/4] Bypassing FSM and starting core loop directly...")
    nija_core_loop._SM_AVAILABLE = False  # type: ignore[attr-defined]
    nija_core_loop._get_state_machine = None  # type: ignore[attr-defined]
    nija_core_loop.TRADING_ENGINE_READY.set()
    loop_thread = nija_core_loop.start_trading_engine(strategy)

    deadline = time.time() + max(5, args.duration_seconds)
    while time.time() < deadline and loop_thread.is_alive():
        time.sleep(1)

    # Stop request for bounded repro run.
    if loop_thread.is_alive():
        nija_core_loop._trading_active = False  # type: ignore[attr-defined]
        loop_thread.join(timeout=15)

    print("=" * 72)
    print(f"THREAD_ALIVE_AFTER_TEST={loop_thread.is_alive()}")
    print("If trades executed in this run, FSM gating is confirmed as the blocker.")
    print("=" * 72)

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # pragma: no cover - operator-facing script
        print(f"ERROR: {exc}")
        raise SystemExit(1)
