#!/usr/bin/env python3
"""
NIJA State Machine Reset Utility
=================================

Resets a stuck or test-triggered EMERGENCY_STOP back to a live-trading state
so the bot can resume without a full redeploy.

Usage
-----
    python scripts/reset_state_machine.py [--dry-run]

What it does
------------
1. Loads the persisted trading-state JSON (.nija_trading_state.json).
2. If the current state is EMERGENCY_STOP, transitions → OFF.
3. If LIVE_CAPITAL_VERIFIED=true is set in the environment (or .env), it then
   calls maybe_auto_activate() which transitions OFF → LIVE_ACTIVE.
4. Prints the resulting state so the operator knows what happened.

Flags
-----
--dry-run   Show what would happen without writing any state changes.
--force     Skip the "are you sure?" confirmation prompt.
--to OFF    Stop at OFF instead of attempting auto-activate to LIVE_ACTIVE.

This script is idempotent: running it multiple times is safe.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# ── Path bootstrap ─────────────────────────────────────────────────────────────
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "bot"))

# Load .env if present so LIVE_CAPITAL_VERIFIED is visible
try:
    from dotenv import load_dotenv
    load_dotenv(_REPO_ROOT / ".env")
except ImportError:
    pass  # dotenv not installed; env vars must already be set


# ── Helpers ────────────────────────────────────────────────────────────────────

STATE_FILE = _REPO_ROOT / ".nija_trading_state.json"

_YELLOW = "\033[33m"
_GREEN  = "\033[32m"
_RED    = "\033[31m"
_CYAN   = "\033[36m"
_BOLD   = "\033[1m"
_RESET  = "\033[0m"

def _col(color: str, text: str) -> str:
    return f"{color}{text}{_RESET}"


def _read_raw_state() -> dict:
    if not STATE_FILE.exists():
        return {"current_state": "UNKNOWN", "history": [], "last_updated": None}
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception as exc:
        print(_col(_RED, f"❌  Cannot read state file: {exc}"))
        return {"current_state": "UNKNOWN", "history": [], "last_updated": None}


def _print_history(data: dict) -> None:
    history = data.get("history", [])[-5:]
    if not history:
        return
    print(_col(_CYAN, "\nRecent state history:"))
    for entry in history:
        ts = entry.get("timestamp", "?")[:19]
        print(f"  {ts}  {entry.get('from')} → {entry.get('to')}  ({entry.get('reason','')[:80]})")


def _confirm(prompt: str) -> bool:
    try:
        ans = input(f"{prompt} [y/N] ").strip().lower()
        return ans in ("y", "yes")
    except (EOFError, KeyboardInterrupt):
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Reset NIJA trading state machine to OFF or LIVE_ACTIVE.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would happen without modifying any state.",
    )
    parser.add_argument(
        "--force", "-f", action="store_true",
        help="Skip confirmation prompt.",
    )
    parser.add_argument(
        "--to", choices=["OFF", "LIVE_ACTIVE"], default=None,
        help="Target state.  Default: OFF, then auto-activate if LIVE_CAPITAL_VERIFIED=true.",
    )
    args = parser.parse_args(argv)

    print(_col(_BOLD, "\n══════════════════════════════════════════"))
    print(_col(_BOLD, "  NIJA State Machine Reset"))
    print(_col(_BOLD, "══════════════════════════════════════════\n"))

    # ── Show current state ──────────────────────────────────────────────────
    raw = _read_raw_state()
    current = raw.get("current_state", "UNKNOWN")
    last_updated = raw.get("last_updated", "unknown")
    print(f"  Current state : {_col(_YELLOW, current)}")
    print(f"  Last updated  : {last_updated}")
    _print_history(raw)
    print()

    if current not in ("EMERGENCY_STOP", "OFF"):
        print(_col(_GREEN, f"✅  State is already {current} — nothing to reset.\n"))
        return 0

    if current == "EMERGENCY_STOP":
        print(_col(_YELLOW, "⚠️   State machine is in EMERGENCY_STOP — all trading is halted."))
        print("     Checking last emergency-stop reason …")
        history = raw.get("history", [])
        for entry in reversed(history):
            if entry.get("to") == "EMERGENCY_STOP":
                print(f"     Trigger : {entry.get('reason', 'unknown')}")
                print(f"     Time    : {entry.get('timestamp', 'unknown')}")
                break
        print()

        if not args.dry_run and not args.force:
            if not _confirm("Reset EMERGENCY_STOP → OFF?"):
                print("Aborted.")
                return 1

    # ── Attempt reset using the state machine singleton ─────────────────────
    if args.dry_run:
        print(_col(_CYAN, "[DRY RUN] Would reset:"))
        if current == "EMERGENCY_STOP":
            print(f"  EMERGENCY_STOP → OFF")
        lcv = os.environ.get("LIVE_CAPITAL_VERIFIED", "false").lower()
        if args.to != "OFF" and lcv in ("true", "1", "yes", "enabled"):
            print(f"  OFF → LIVE_ACTIVE  (LIVE_CAPITAL_VERIFIED={lcv})")
        else:
            print(f"  (stop at OFF — LIVE_CAPITAL_VERIFIED not set or --to OFF requested)")
        return 0

    try:
        from trading_state_machine import get_state_machine, TradingState

        sm = get_state_machine()
        current_enum = sm.get_current_state()

        # The SM's _load_state() auto-clears EMERGENCY_STOP → OFF in memory on
        # every instantiation, but does NOT persist that change back to disk.
        # Detect this case (disk=EMERGENCY_STOP, memory=OFF) and write the
        # corrected OFF state to disk using the JSON fallback path, which is
        # public and does not touch SM internals.
        if current == "EMERGENCY_STOP" and current_enum == TradingState.OFF:
            # Auto-clear already happened in memory — persist it to disk via JSON patch
            _raw_json_reset(raw, args)
            print(_col(_GREEN, "✅  EMERGENCY_STOP → OFF  (auto-cleared on SM load; persisted to disk)"))

        elif current_enum == TradingState.EMERGENCY_STOP:
            sm.transition_to(
                TradingState.OFF,
                "Manual reset via scripts/reset_state_machine.py — emergency stop cleared by operator",
            )
            print(_col(_GREEN, "✅  EMERGENCY_STOP → OFF"))

        if args.to == "OFF":
            print(_col(_GREEN, "\n  State is now OFF.  Set LIVE_CAPITAL_VERIFIED=true and restart to go live.\n"))
            return 0

        # Auto-activate to LIVE_ACTIVE if all gates pass
        current_enum = sm.get_current_state()
        if current_enum == TradingState.OFF:
            activated = sm.maybe_auto_activate()
            if activated:
                print(_col(_GREEN, "✅  OFF → LIVE_ACTIVE  (all safety gates passed)\n"))
            else:
                lcv = os.environ.get("LIVE_CAPITAL_VERIFIED", "false").lower()
                print(_col(_YELLOW, f"⚠️   Stopped at OFF — auto-activate blocked."))
                if lcv not in ("true", "1", "yes", "enabled"):
                    print("     LIVE_CAPITAL_VERIFIED is not set to true.")
                    print("     Add  LIVE_CAPITAL_VERIFIED=true  to your .env and restart the bot.")
                else:
                    print("     Kill switch may be active.  Check kill-switch state.")
                print()

        final = sm.get_current_state()
        print(f"  Final state: {_col(_BOLD + _GREEN, final.value)}\n")
        return 0

    except ImportError as exc:
        # dotenv / krakenex / etc. not installed — fall back to raw JSON edit
        print(_col(_YELLOW, f"⚠️   Could not import trading_state_machine ({exc})."))
        print("     Applying raw JSON patch to state file …")
        _raw_json_reset(raw, args)
        return 0

    except Exception as exc:
        print(_col(_RED, f"❌  State machine error: {exc}"))
        import traceback
        traceback.print_exc()
        return 1


def _raw_json_reset(raw: dict, args: argparse.Namespace) -> None:
    """Fallback: edit the state JSON directly when the SM module can't be imported."""
    from datetime import datetime

    current = raw.get("current_state", "UNKNOWN")
    history = raw.get("history", [])

    ts = datetime.utcnow().isoformat()

    if current == "EMERGENCY_STOP":
        history.append({
            "from": "EMERGENCY_STOP",
            "to": "OFF",
            "reason": "Manual reset via scripts/reset_state_machine.py (raw-JSON fallback)",
            "timestamp": ts,
        })
        raw["current_state"] = "OFF"
        raw["last_updated"] = ts
        print(_col(_GREEN, "  EMERGENCY_STOP → OFF  (raw JSON)"))

    lcv = os.environ.get("LIVE_CAPITAL_VERIFIED", "false").lower()
    if args.to != "OFF" and lcv in ("true", "1", "yes", "enabled"):
        if raw["current_state"] == "OFF":
            history.append({
                "from": "OFF",
                "to": "LIVE_ACTIVE",
                "reason": "Auto-activated by reset_state_machine.py (LIVE_CAPITAL_VERIFIED=true)",
                "timestamp": ts,
            })
            raw["current_state"] = "LIVE_ACTIVE"
            raw["last_updated"] = ts
            print(_col(_GREEN, "  OFF → LIVE_ACTIVE  (raw JSON)"))

    raw["history"] = history
    STATE_FILE.write_text(json.dumps(raw, indent=2))
    print(_col(_GREEN, f"\n  State file updated → {raw['current_state']}\n"))


if __name__ == "__main__":
    sys.exit(main())
