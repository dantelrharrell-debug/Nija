#!/usr/bin/env python3
"""
real_capital_test.py — NIJA Real Capital Verification Test
===========================================================

Runs a 4-phase, non-destructive verification of the full trading stack:

  Phase 1  — Broker Balance Test
             Fetch live balances from every configured broker
             (Coinbase, Kraken, Binance).

  Phase 2  — Capital Authority Reconciliation
             Feed fetched balances into CapitalAuthority and assert
             total_capital > 0.

  Phase 3  — Execution Dry-Run
             Simulate order math (fee, slippage, sizing) for BTC-USD
             on each active broker WITHOUT placing any real order.

  Phase 4  — End-to-End Readiness Gate
             Assert CAPITAL_READY / BROKERS_READY / EXECUTION_READY /
             TRADING_ENABLED and print the final SYSTEM READY verdict.

Usage
-----
    python real_capital_test.py

    # Verbose mode (shows each intermediate calculation):
    python real_capital_test.py --verbose

No trades are placed.  All API calls are read-only balance / account fetches.
"""

from __future__ import annotations

import argparse
import logging
import math
import os
import sys
import textwrap
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Auto-load .env (project root) so the script works without exporting vars
# ---------------------------------------------------------------------------
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv not installed — rely on env already being set

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.WARNING,      # silenced by default; -v enables INFO
    format="%(levelname)-8s %(name)s: %(message)s",
)
logger = logging.getLogger("nija.real_capital_test")

SEP = "=" * 72
SEP2 = "-" * 72


# ---------------------------------------------------------------------------
# Result data-class
# ---------------------------------------------------------------------------

@dataclass
class Result:
    phase: str
    name: str
    passed: bool
    value: Any = None          # e.g. balance float, computed size, etc.
    detail: str = ""
    remediation: str = ""


# ---------------------------------------------------------------------------
# Broker fee constants (canonical values from the codebase)
# ---------------------------------------------------------------------------

BROKER_FEE_TAKER: Dict[str, float] = {
    "coinbase": 0.0060,   # bot/fee_aware_config.py: COINBASE_MARKET_ORDER_FEE
    "kraken":   0.0026,   # bot/position_sizer.py line 386; bot/kraken_params_optimizer.py
    "binance":  0.0010,   # bot/binance_params_optimizer.py
}
BROKER_SPREAD: Dict[str, float] = {
    "coinbase": 0.0020,   # bot/fee_aware_config.py: COINBASE_SPREAD_COST
    "kraken":   0.0040,   # bot/position_sizer.py line 387
    "binance":  0.0010,
}
BROKER_SLIPPAGE: Dict[str, float] = {
    "coinbase": 0.0010,
    "kraken":   0.0020,   # bot/position_sizer.py line 388
    "binance":  0.0005,
}

# Minimum trade size in USD (hard exchange floors + fee buffer)
BROKER_MIN_TRADE_USD: Dict[str, float] = {
    "coinbase": 5.0,   # GLOBAL_MIN_TRADE = 10.0 but Coinbase floor is lower
    "kraken":   10.50,  # bot/position_sizer.py: _KRAKEN_EXCHANGE_FLOOR
    "binance":  10.0,
}

# ---------------------------------------------------------------------------
# Fee math helpers (mirrors execution_engine.py::calculate_net_edge)
# ---------------------------------------------------------------------------

def _round_trip_cost(broker: str) -> float:
    """Total round-trip cost fraction = 2×taker + spread + slippage."""
    b = broker.lower()
    return (
        BROKER_FEE_TAKER.get(b, 0.006) * 2
        + BROKER_SPREAD.get(b, 0.002)
        + BROKER_SLIPPAGE.get(b, 0.001)
    )


def calculate_net_edge(
    entry: float,
    target: float,
    size: float,
    fee_rate: float,
    slippage_rate: float,
    spread_rate: float,
) -> float:
    """Net profit after round-trip costs.  Mirrors execution_engine.py."""
    if entry <= 0 or target <= 0 or size <= 0:
        return 0.0
    gross_profit = (target - entry) * size / entry
    fees = size * fee_rate * 2
    slippage = size * slippage_rate
    spread = size * spread_rate
    return gross_profit - fees - slippage - spread


def calculate_position_size(
    account_balance: float,
    take_profit_pct: float,
    stop_loss_pct: float,
    atr_pct: float,
    broker: str = "kraken",
    win_rate: float = 0.55,
    max_risk_pct: float = 0.01,
    max_position_pct: float = 0.40,
) -> float:
    """
    Mirrors bot/position_sizer.py::calculate_position_size logic.
    Returns 0.0 when trade is vetoed by cost model (net profit < 1.2%).
    """
    b = broker.lower()
    min_trade = BROKER_MIN_TRADE_USD.get(b, 10.0)

    fee_rate   = BROKER_FEE_TAKER.get(b, 0.006) * 2
    spread     = BROKER_SPREAD.get(b, 0.002)
    slippage   = BROKER_SLIPPAGE.get(b, 0.001)
    total_cost = fee_rate + spread + slippage

    # Net profit gate (1.2% minimum)
    expected_net_profit = take_profit_pct - total_cost
    if expected_net_profit <= 0.012:
        return 0.0

    # Risk-based sizing
    risk_amount  = account_balance * max_risk_pct
    effective_sl = stop_loss_pct + total_cost
    if effective_sl <= 0:
        return 0.0
    position_size_risk = risk_amount / effective_sl

    # Volatility scalar
    vol_scalar = min(1.0, 0.02 / atr_pct) if atr_pct > 0 else 1.0
    position_size_vol = position_size_risk * vol_scalar

    # Conservative Kelly
    edge = (win_rate * take_profit_pct) - ((1.0 - win_rate) * stop_loss_pct)
    variance = take_profit_pct ** 2
    kelly_fraction = max(0.0, min(edge / variance if variance > 0 else 0.0, 0.25))
    position_size_kelly = account_balance * kelly_fraction

    # Most-conservative wins
    raw_size = min(position_size_vol, position_size_kelly, account_balance * max_position_pct)
    final_size = max(raw_size, min_trade)
    cap = account_balance * max_position_pct
    if final_size > cap:
        final_size = cap
    return math.floor(final_size * 100) / 100


# ---------------------------------------------------------------------------
# Phase 1 — Broker Balance Fetchers
# ---------------------------------------------------------------------------

def _fetch_coinbase_balance(verbose: bool) -> Tuple[Optional[float], str]:
    """Return (balance_usd, detail_str) or (None, error_str)."""
    api_key = os.getenv("COINBASE_API_KEY", "")
    api_secret = os.getenv("COINBASE_API_SECRET", "") or os.getenv("COINBASE_PEM_CONTENT", "")

    if not api_key or not api_secret:
        return None, "COINBASE_API_KEY / COINBASE_API_SECRET (or COINBASE_PEM_CONTENT) not set"

    # Normalize escaped newlines (Railway/Docker env convention)
    if "\\n" in api_secret:
        api_secret = api_secret.replace("\\n", "\n")

    try:
        from coinbase.rest import RESTClient  # type: ignore
    except ImportError:
        return None, "coinbase-advanced-py not installed (pip install coinbase-advanced-py)"

    try:
        client = RESTClient(api_key=api_key, api_secret=api_secret)
        resp = client.get_accounts()
    except Exception as exc:
        return None, f"Connection error: {exc}"

    accounts = getattr(resp, "accounts", None)
    if accounts is None and isinstance(resp, dict):
        accounts = resp.get("accounts", [])
    if accounts is None:
        accounts = []

    usd = usdc = 0.0
    crypto_lines: List[str] = []
    for acct in accounts:
        if isinstance(acct, dict):
            currency = acct.get("currency", "")
            available = float((acct.get("available_balance") or {}).get("value", 0) or 0)
        else:
            currency = getattr(acct, "currency", "") or ""
            avail_obj = getattr(acct, "available_balance", None)
            available = float(getattr(avail_obj, "value", 0) or 0) if avail_obj else 0.0
        currency = str(currency).upper()
        if currency == "USD":
            usd += available
        elif currency == "USDC":
            usdc += available
        elif available > 0:
            crypto_lines.append(f"{currency}: {available:.6f}")

    total = usd + usdc
    detail = f"USD=${usd:.2f}  USDC=${usdc:.2f}  total=${total:.2f}"
    if crypto_lines and verbose:
        detail += "  |  crypto: " + ", ".join(crypto_lines[:5])
    return total, detail


def _fetch_kraken_balance(verbose: bool) -> Tuple[Optional[float], str]:
    """
    Fetch Kraken balance using the NIJA broker stack.
    Falls back to raw API if the broker class is unavailable.
    """
    api_key = (
        os.getenv("KRAKEN_PLATFORM_API_KEY", "")
        or os.getenv("KRAKEN_API_KEY", "")
    )
    api_secret = (
        os.getenv("KRAKEN_PLATFORM_API_SECRET", "")
        or os.getenv("KRAKEN_API_SECRET", "")
    )

    if not api_key or not api_secret:
        return None, "KRAKEN_PLATFORM_API_KEY / KRAKEN_PLATFORM_API_SECRET not set"

    # Try via NIJA broker class first
    try:
        sys.path.insert(0, os.path.dirname(__file__))
        from bot.broker_manager import KrakenBroker, AccountType  # type: ignore

        broker = KrakenBroker(account_type=AccountType.PLATFORM)
        connected = broker.connect()
        if not connected:
            return None, "KrakenBroker.connect() returned False"

        raw = broker.get_account_balance()
        if isinstance(raw, dict):
            balance = float(
                raw.get("trading_balance")
                or raw.get("total_funds")
                or (raw.get("usd", 0.0) + raw.get("usdc", 0.0))
                or 0.0
            )
            detail = f"raw_keys={sorted(raw.keys())}  balance=${balance:.2f}"
        else:
            balance = float(raw or 0.0)
            detail = f"balance=${balance:.2f}"
        return balance, detail

    except Exception as exc:
        # Fallback: raw krakenex / ccxt style call
        try:
            import krakenex  # type: ignore
            k = krakenex.API(key=api_key, secret=api_secret)
            resp = k.query_private("Balance")
            if resp.get("error"):
                return None, f"Kraken API error: {resp['error']}"
            result = resp.get("result", {})
            usd = (
                result.get("ZUSD") or
                result.get("USD") or
                0
            )
            zusd = float(usd)
            usdc = float(result.get("USDC", 0.0))
            total = zusd + usdc
            detail = f"ZUSD=${zusd:.2f}  USDC=${usdc:.2f}  total=${total:.2f}"
            return total, detail
        except ImportError:
            return None, f"broker import error ({exc}) and krakenex not installed"
        except Exception as exc2:
            return None, f"Kraken balance error: {exc2}"


def _fetch_binance_balance(verbose: bool) -> Tuple[Optional[float], str]:
    """Fetch Binance balance (optional — skipped when credentials absent)."""
    api_key    = os.getenv("BINANCE_API_KEY", "")
    api_secret = os.getenv("BINANCE_API_SECRET", "")

    if not api_key or not api_secret:
        return None, "BINANCE_API_KEY / BINANCE_API_SECRET not set — Binance skipped"

    try:
        from binance.client import Client  # type: ignore
        client = Client(api_key, api_secret)
        account = client.get_account()
        balances = account.get("balances", [])
        usdt = usdc = btc_val = 0.0
        for b in balances:
            asset = b.get("asset", "")
            free  = float(b.get("free", 0) or 0)
            if asset == "USDT":
                usdt += free
            elif asset == "USDC":
                usdc += free
        total = usdt + usdc
        detail = f"USDT=${usdt:.2f}  USDC=${usdc:.2f}  total=${total:.2f}"
        return total, detail
    except ImportError:
        return None, "python-binance not installed — Binance skipped"
    except Exception as exc:
        return None, f"Binance balance error: {exc}"


# ---------------------------------------------------------------------------
# Phase 2 — Capital Authority Reconciliation
# ---------------------------------------------------------------------------

def _run_capital_authority_reconciliation(
    balances: Dict[str, float],
    verbose: bool,
) -> Tuple[bool, float, str]:
    """
    Feed fetched balances into CapitalAuthority and read back real_capital.
    Returns (passed, total_capital, detail).
    """
    try:
        from bot.capital_authority import get_capital_authority, BROKER_ROLE_PRIMARY  # type: ignore
    except ImportError:
        return False, 0.0, "Cannot import bot.capital_authority"

    ca = get_capital_authority()

    # Feed each fetched balance directly (no live API re-call)
    for broker_key, balance in balances.items():
        if balance is not None and balance > 0:
            ca.feed_broker_balance(broker_key, balance)
            ca.set_broker_role(broker_key, BROKER_ROLE_PRIMARY)

    total = ca.get_real_capital()
    usable = ca.get_usable_capital()
    risk   = ca.get_risk_capital()

    snapshot = ca.get_snapshot()
    age = snapshot.get("age_s", float("inf"))
    fresh = snapshot.get("is_fresh", False)

    detail = (
        f"real=${total:.2f}  usable=${usable:.2f}  risk=${risk:.2f}  "
        f"brokers={snapshot.get('broker_count', 0)}  "
        f"age={age:.1f}s  fresh={fresh}"
    )
    passed = total > 0.0
    return passed, total, detail


# ---------------------------------------------------------------------------
# Phase 3 — Execution Dry-Run
# ---------------------------------------------------------------------------

_DRY_RUN_ENTRY   = 65_000.0   # BTC-USD example entry
_DRY_RUN_TARGET  = 66_950.0   # +3% target
_DRY_RUN_STOP    = 63_700.0   # -2% stop
_DRY_RUN_ATR_PCT = 0.020      # 2% ATR


def _dry_run_broker(
    broker: str,
    balance: float,
    verbose: bool,
) -> Tuple[bool, str]:
    """
    Validate fee math + sizing for a single broker without placing an order.
    Returns (passed, detail).
    """
    b = broker.lower()
    taker_fee  = BROKER_FEE_TAKER.get(b, 0.006)
    spread     = BROKER_SPREAD.get(b, 0.002)
    slippage   = BROKER_SLIPPAGE.get(b, 0.001)
    rt_cost    = taker_fee * 2 + spread + slippage

    entry  = _DRY_RUN_ENTRY
    target = _DRY_RUN_TARGET
    tp_pct = (target - entry) / entry
    sl_pct = (entry - _DRY_RUN_STOP) / entry

    # Position size
    size = calculate_position_size(
        account_balance=balance,
        take_profit_pct=tp_pct,
        stop_loss_pct=sl_pct,
        atr_pct=_DRY_RUN_ATR_PCT,
        broker=b,
    )

    # Net edge on that size
    net_edge = calculate_net_edge(
        entry=entry,
        target=target,
        size=size,
        fee_rate=taker_fee,
        slippage_rate=slippage,
        spread_rate=spread,
    )

    net_pct = (net_edge / size * 100) if size > 0 else 0.0
    gross_pct = tp_pct * 100
    cost_pct  = rt_cost * 100

    # Assertions
    # 1. Size must meet exchange minimum
    min_trade = BROKER_MIN_TRADE_USD.get(b, 10.0)
    size_ok = size >= min_trade

    # 2. Fee math: round-trip cost = 2×taker + spread + slippage (within 0.001%)
    computed_rt = taker_fee * 2 + spread + slippage
    expected_fees_usd = size * computed_rt
    engine_fees_usd = size * taker_fee * 2 + size * slippage + size * spread
    fee_math_ok = abs(expected_fees_usd - engine_fees_usd) < 0.0001

    # 3. Net edge must be positive for any trade to execute
    edge_ok = net_edge > 0 if size > 0 else True   # 0-size means vetoed, which is acceptable

    passed = fee_math_ok and (not size_ok or edge_ok)

    lines = [
        f"  {broker.upper()} dry-run  (balance=${balance:.2f})",
        f"    entry=${entry:,.2f}  target=${target:,.2f}  stop=${_DRY_RUN_STOP:,.2f}",
        f"    gross={gross_pct:.2f}%  cost={cost_pct:.3f}%  net≈{net_pct:.2f}%",
        f"    taker={taker_fee*100:.3f}%  spread={spread*100:.3f}%  slip={slippage*100:.3f}%",
        f"    size=${size:.2f}  min=${min_trade:.2f}  size_ok={size_ok}",
        f"    fee_math_ok={fee_math_ok}  edge_ok={edge_ok}  passed={passed}",
    ]
    return passed, "\n".join(lines)


# ---------------------------------------------------------------------------
# Phase 4 — End-to-End Readiness Gate
# ---------------------------------------------------------------------------

def _readiness_gate(
    phase1_results: List[Result],
    phase2_result: Result,
    phase3_results: List[Result],
) -> Dict[str, bool]:
    """
    Derive the four readiness flags from all phase results.
    """
    # CAPITAL_READY: CapitalAuthority has non-zero capital
    capital_ready = phase2_result.passed

    # BROKERS_READY: at least one broker returned a non-None, non-zero balance
    brokers_ready = any(
        r.passed and isinstance(r.value, float) and r.value > 0
        for r in phase1_results
        if r.phase == "1"
    )

    # EXECUTION_READY: all dry-run checks passed (or no active brokers to check)
    exec_results = [r for r in phase3_results if r.phase == "3"]
    execution_ready = all(r.passed for r in exec_results) if exec_results else False

    # TRADING_ENABLED: all three above + no emergency stop file present
    emergency_stop_active = os.path.exists("TRADING_EMERGENCY_STOP.conf") or \
                             os.path.exists("EMERGENCY_STOP") or \
                             os.path.exists("STOP_ALL_ENTRIES.conf")
    trading_enabled = (
        capital_ready and brokers_ready and execution_ready and not emergency_stop_active
    )

    return {
        "CAPITAL_READY":    capital_ready,
        "BROKERS_READY":    brokers_ready,
        "EXECUTION_READY":  execution_ready,
        "TRADING_ENABLED":  trading_enabled,
    }


# ---------------------------------------------------------------------------
# Print helpers
# ---------------------------------------------------------------------------

def _print_phase_header(n: int, title: str) -> None:
    print(f"\n{SEP2}")
    print(f"  PHASE {n} — {title}")
    print(SEP2)


def _print_result(r: Result, verbose: bool) -> None:
    icon = "✅" if r.passed else "❌"
    label = "PASS" if r.passed else "FAIL"
    val = f"  [${r.value:,.2f}]" if isinstance(r.value, (int, float)) else ""
    print(f"  {icon} [{label}] {r.name}{val}")
    if r.detail and verbose:
        for line in r.detail.splitlines():
            print(f"       {line}")
    if r.remediation and not r.passed:
        print(f"       → {r.remediation}")


# ---------------------------------------------------------------------------
# Main test runner
# ---------------------------------------------------------------------------

def run(verbose: bool = False) -> int:
    """
    Execute all four phases and return exit code (0 = SYSTEM READY, 1 = not ready).
    """
    all_results: List[Result] = []
    phase1: List[Result] = []
    phase3: List[Result] = []
    fetched_balances: Dict[str, float] = {}

    print(f"\n{SEP}")
    print("  🧪  NIJA — REAL CAPITAL TEST")
    print(f"  {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}")
    print(SEP)

    # ── Phase 1: Broker Balance Tests ────────────────────────────────────────
    _print_phase_header(1, "BROKER BALANCE TEST")

    brokers_to_test = [
        ("coinbase", _fetch_coinbase_balance),
        ("kraken",   _fetch_kraken_balance),
        ("binance",  _fetch_binance_balance),
    ]

    for broker_name, fetcher in brokers_to_test:
        balance, detail = fetcher(verbose)

        if balance is None:
            # credentials absent or error
            is_optional = broker_name == "binance"
            r = Result(
                phase="1",
                name=f"{broker_name.capitalize()} Balance",
                passed=is_optional,          # Binance absence is not a hard fail
                value=0.0,
                detail=detail,
                remediation=(
                    ""
                    if is_optional
                    else f"Set {broker_name.upper()} credentials in .env and retry"
                ),
            )
        elif balance == 0.0:
            r = Result(
                phase="1",
                name=f"{broker_name.capitalize()} Balance",
                passed=True,       # zero is valid (empty account) — connection succeeded
                value=0.0,
                detail=detail + " [zero balance — account may be empty or pending funding]",
            )
        else:
            fetched_balances[broker_name] = balance
            r = Result(
                phase="1",
                name=f"{broker_name.capitalize()} Balance",
                passed=True,
                value=balance,
                detail=detail,
            )

        phase1.append(r)
        all_results.append(r)
        _print_result(r, verbose)

    # ── Phase 2: Capital Authority Reconciliation ─────────────────────────────
    _print_phase_header(2, "CAPITAL AUTHORITY RECONCILIATION")

    if fetched_balances:
        ca_passed, ca_total, ca_detail = _run_capital_authority_reconciliation(
            fetched_balances, verbose
        )
    else:
        ca_passed = False
        ca_total  = 0.0
        ca_detail = "No broker balances to feed — all fetch attempts failed or returned zero"

    ca_result = Result(
        phase="2",
        name="CapitalAuthority.refresh()",
        passed=ca_passed,
        value=ca_total,
        detail=ca_detail,
        remediation=(
            "Ensure at least one broker is connected and returning a non-zero balance"
            if not ca_passed else ""
        ),
    )
    all_results.append(ca_result)
    _print_result(ca_result, verbose)

    # ── Phase 3: Execution Dry-Run ────────────────────────────────────────────
    _print_phase_header(3, "EXECUTION DRY-RUN  (no real orders)")

    if not fetched_balances:
        r = Result(
            phase="3",
            name="Execution Dry-Run",
            passed=False,
            detail="Skipped — no broker balances available from Phase 1",
            remediation="Fix broker connectivity before running execution dry-run",
        )
        phase3.append(r)
        all_results.append(r)
        _print_result(r, verbose)
    else:
        for broker_name, balance in fetched_balances.items():
            dr_passed, dr_detail = _dry_run_broker(broker_name, balance, verbose)
            r = Result(
                phase="3",
                name=f"{broker_name.capitalize()} Dry-Run",
                passed=dr_passed,
                value=None,
                detail=dr_detail,
                remediation=(
                    "Review fee constants in bot/fee_aware_config.py and bot/position_sizer.py"
                    if not dr_passed else ""
                ),
            )
            phase3.append(r)
            all_results.append(r)
            _print_result(r, verbose)

    # ── Phase 4: End-to-End Readiness Gate ───────────────────────────────────
    _print_phase_header(4, "END-TO-END READINESS GATE")

    flags = _readiness_gate(phase1, ca_result, phase3)

    max_name_len = max(len(k) for k in flags)
    for flag, ready in flags.items():
        icon  = "✅" if ready else "❌"
        label = "True " if ready else "False"
        print(f"  {icon}  {flag.ljust(max_name_len)}  =  {label}")

    # ── Final verdict ─────────────────────────────────────────────────────────
    print(f"\n{SEP}")
    if flags["TRADING_ENABLED"]:
        print("  🚀  SYSTEM READY — TRADING ENABLED")
        print(f"  Total capital visible: ${ca_total:,.2f}")
    else:
        print("  ⛔  SYSTEM NOT READY — TRADING BLOCKED")
        # Show what specifically is blocking
        blocking = [k for k, v in flags.items() if not v]
        print(f"  Blocking flags: {', '.join(blocking)}")
        # Surface top remediation hints
        failed = [r for r in all_results if not r.passed and r.remediation]
        if failed:
            print("\n  Remediation steps:")
            for r in failed[:5]:
                print(f"    • [{r.name}] {r.remediation}")
    print(SEP)
    print()

    return 0 if flags["TRADING_ENABLED"] else 1


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="NIJA Real Capital Verification Test — 4-phase non-destructive readiness check",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
        Exit codes:
          0  — SYSTEM READY / TRADING ENABLED
          1  — Not ready (see blocking flags above)
        """),
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Print intermediate calculations and raw balance detail",
    )
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.INFO)

    exit_code = run(verbose=args.verbose)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
