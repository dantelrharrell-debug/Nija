#!/usr/bin/env python3
"""
NIJA .env Setup Wizard
=======================

Interactively creates (or updates) your .env file from .env.example so the
bot can connect to exchanges and start trading.

Usage
-----
    python scripts/setup_env.py               # interactive walk-through
    python scripts/setup_env.py --check-only  # just report what is missing

What it does
------------
1. Reads .env.example to discover every recognised variable.
2. Reads the existing .env (if any) to avoid overwriting values you already set.
3. Groups variables by category (Required, Recommended, Optional) and prompts
   you for each missing Required / Recommended value.
4. Writes the result to .env.  Secrets are never echoed to the terminal.
5. Runs a quick validation pass and reports any remaining gaps.

Non-destructive
---------------
* Values already in .env are NEVER overwritten — only blank ones are filled.
* Run with --check-only to see what is missing without writing anything.
* Run with --reset-all to re-prompt for every variable (use with caution).
"""

from __future__ import annotations

import argparse
import getpass
import os
import re
import sys
from pathlib import Path
from typing import Optional

# ── Path bootstrap ─────────────────────────────────────────────────────────────
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "bot"))

_ENV_EXAMPLE = _REPO_ROOT / ".env.example"
_ENV_FILE    = _REPO_ROOT / ".env"

# ── Terminal colours ───────────────────────────────────────────────────────────
_BOLD   = "\033[1m"
_GREEN  = "\033[32m"
_YELLOW = "\033[33m"
_RED    = "\033[31m"
_CYAN   = "\033[36m"
_DIM    = "\033[2m"
_RESET  = "\033[0m"

def _c(color: str, text: str) -> str:
    return f"{color}{text}{_RESET}"


# ── Variable categories ────────────────────────────────────────────────────────
# Variables in REQUIRED must be set before the bot will trade.
# RECOMMENDED are strongly advised; the bot degrades without them.
# Everything else is Optional.

_REQUIRED = {
    # At least one exchange credential set is needed
    "KRAKEN_PLATFORM_API_KEY",
    "KRAKEN_PLATFORM_API_SECRET",
    # Safety gate
    "LIVE_CAPITAL_VERIFIED",
}

_RECOMMENDED = {
    "KRAKEN_API_KEY",
    "KRAKEN_API_SECRET",
    "COINBASE_API_KEY",
    "COINBASE_API_SECRET",
    "TRADINGVIEW_WEBHOOK_SECRET",
}

# Variables whose values should not be echoed (they contain secrets)
_SECRET_VARS = {
    "KRAKEN_PLATFORM_API_KEY",
    "KRAKEN_PLATFORM_API_SECRET",
    "KRAKEN_API_KEY",
    "KRAKEN_API_SECRET",
    "KRAKEN_USER_DAIVON_API_KEY",
    "KRAKEN_USER_DAIVON_API_SECRET",
    "KRAKEN_USER_TANIA_API_KEY",
    "KRAKEN_USER_TANIA_API_SECRET",
    "KRAKEN_USER_TANIA_GILBERT_API_KEY",
    "KRAKEN_USER_TANIA_GILBERT_API_SECRET",
    "ALPACA_USER_TANIA_API_KEY",
    "ALPACA_USER_TANIA_API_SECRET",
    "COINBASE_API_KEY",
    "COINBASE_API_SECRET",
    "COINBASE_PEM_CONTENT",
    "ALPACA_API_KEY",
    "ALPACA_API_SECRET",
    "OKX_API_KEY",
    "OKX_API_SECRET",
    "OKX_PASSPHRASE",
    "BINANCE_API_KEY",
    "BINANCE_API_SECRET",
    "JWT_SECRET_KEY",
    "TRADINGVIEW_WEBHOOK_SECRET",
}

# Human-friendly descriptions for prompts
_DESCRIPTIONS: dict[str, str] = {
    "KRAKEN_PLATFORM_API_KEY":     "Kraken PLATFORM API key (Classic key, NOT OAuth)",
    "KRAKEN_PLATFORM_API_SECRET":  "Kraken PLATFORM API secret",
    "KRAKEN_API_KEY":              "Kraken legacy API key (used as fallback)",
    "KRAKEN_API_SECRET":           "Kraken legacy API secret",
    "COINBASE_API_KEY":            "Coinbase Advanced Trade API key",
    "COINBASE_API_SECRET":         "Coinbase Advanced Trade API secret",
    "LIVE_CAPITAL_VERIFIED":       "Enable live trading? (true/false — set true only when ready)",
    "TRADINGVIEW_WEBHOOK_SECRET":  "Secret token that TradingView webhooks must include",
    "JWT_SECRET_KEY":              "Random secret key for JWT tokens (any long random string)",
}

# Defaults to suggest for non-secret variables
_DEFAULTS: dict[str, str] = {
    "LIVE_CAPITAL_VERIFIED": "false",
    "DRY_RUN_MODE":          "false",
    "HEARTBEAT_TRADE":       "false",
    "APP_STORE_MODE":        "false",
    "TRADING_MODE":          "independent",
    "ALPACA_PAPER":          "true",
    "OKX_USE_TESTNET":       "false",
    "BINANCE_USE_TESTNET":   "false",
    "PORT":                  "5000",
    "WEB_CONCURRENCY":       "1",
    "RETRY_DELAY":           "5",
    "MAX_RETRIES":           "5",
    "MAX_CONCURRENT_POSITIONS": "7",
    "MINIMUM_TRADING_BALANCE": "1.0",
    "SECRETS_BACKEND":       "env",
    "RATELIMIT_STORAGE_URI": "memory://",
}


# ── Parsers ────────────────────────────────────────────────────────────────────

def _parse_env_file(path: Path) -> dict[str, str]:
    """Return {key: value} from an env file (strips comments, inline comments, quotes)."""
    result: dict[str, str] = {}
    if not path.exists():
        return result
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        # Strip inline comment AFTER splitting on = to avoid breaking URLs
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        # Remove inline comment (space + # …) but only if not inside quotes
        val = val.strip()
        if not (val.startswith('"') or val.startswith("'")):
            val = re.sub(r"\s+#.*$", "", val).strip()
        # Strip surrounding quotes
        val = val.strip('"').strip("'")
        if key:
            result[key] = val
    return result


def _parse_example_order(path: Path) -> list[tuple[str, str, str]]:
    """
    Return list of (key, raw_value, comment) preserving .env.example order.
    comment is the # comment on the same line (or empty).
    """
    rows: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, rest = line.partition("=")
        key = key.strip()
        if key in seen:
            continue
        seen.add(key)
        val_part, _, comment = rest.partition("  #")
        val = val_part.strip().strip('"').strip("'")
        rows.append((key, val, comment.strip()))
    return rows


# ── Interactive prompts ────────────────────────────────────────────────────────

def _prompt(key: str, existing: str, default: str, is_secret: bool) -> str:
    """Prompt the user for a value. Returns existing value if user hits Enter."""
    desc = _DESCRIPTIONS.get(key, "")
    category = (
        _c(_RED, "REQUIRED")
        if key in _REQUIRED
        else _c(_YELLOW, "recommended")
        if key in _RECOMMENDED
        else "optional"
    )

    print()
    print(f"  {_c(_BOLD, key)}  [{category}]")
    if desc:
        print(f"  {_c(_DIM, desc)}")
    if existing:
        masked = ("*" * min(8, len(existing))) if is_secret else existing
        print(f"  Current value: {_c(_DIM, masked)}  (press Enter to keep)")

    suggested = existing or default
    prompt_suffix = f" [{suggested[:20]}…]" if suggested and len(suggested) > 20 else (f" [{suggested}]" if suggested else "")

    try:
        if is_secret:
            raw = getpass.getpass(f"  Enter value{prompt_suffix}: ")
        else:
            raw = input(f"  Enter value{prompt_suffix}: ").strip()
    except (EOFError, KeyboardInterrupt):
        raw = ""

    return raw.strip() or existing or default


def _category_label(key: str) -> str:
    if key in _REQUIRED:
        return "REQUIRED"
    if key in _RECOMMENDED:
        return "recommended"
    return "optional"


def _is_secret_var(key: str) -> bool:
    """Return True when a variable should be treated as secret."""
    if key in _SECRET_VARS:
        return True
    return any(
        key.endswith(suffix)
        for suffix in ("_API_KEY", "_API_SECRET", "_SECRET")
    )


# ── Main logic ─────────────────────────────────────────────────────────────────

def _check_only(example_rows: list, existing: dict, final: dict) -> None:
    """Print a status report without writing anything."""
    missing_required: list[str] = []
    missing_recommended: list[str] = []

    print(_c(_BOLD, "\n  Variable status\n"))
    for key, default_val, _ in example_rows:
        val = final.get(key, "")
        cat = _category_label(key)
        if val:
            masked = ("*" * 8) if _is_secret_var(key) else val[:40]
            print(f"  {_c(_GREEN, '✅')} {key:<45} {masked}")
        elif cat == "REQUIRED":
            print(f"  {_c(_RED,    '❌')} {key:<45} (REQUIRED — not set)")
            missing_required.append(key)
        elif cat == "recommended":
            print(f"  {_c(_YELLOW, '⚠️ ')} {key:<45} (recommended — not set)")
            missing_recommended.append(key)
        else:
            print(f"  {_c(_DIM,    '—  ')} {key:<45} (optional)")

    print()
    if missing_required:
        print(_c(_RED,    f"  🔴 {len(missing_required)} required variable(s) missing — bot cannot trade"))
    if missing_recommended:
        print(_c(_YELLOW, f"  ⚠️  {len(missing_recommended)} recommended variable(s) not set"))
    if not missing_required and not missing_recommended:
        print(_c(_GREEN, "  ✅  All required and recommended variables are set"))
    print()


def _write_env(existing_path: Path, updates: dict[str, str]) -> None:
    """Merge updates into the existing .env (or create it)."""
    lines: list[str] = []

    if existing_path.exists():
        for raw_line in existing_path.read_text().splitlines():
            stripped = raw_line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                lines.append(raw_line)
                continue
            key = stripped.split("=", 1)[0].strip()
            if key in updates:
                # Replace the line with the new value
                new_val = updates.pop(key)
                lines.append(f"{key}={new_val}")
            else:
                lines.append(raw_line)
    # Append any remaining new keys that weren't in the file
    if updates:
        lines.append("")
        lines.append("# ── Added by scripts/setup_env.py ──────────────────────────────────────")
        for key, val in updates.items():
            lines.append(f"{key}={val}")

    existing_path.write_text("\n".join(lines) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Interactive NIJA .env setup wizard.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--check-only", action="store_true",
        help="Report missing variables without writing anything.",
    )
    parser.add_argument(
        "--reset-all", action="store_true",
        help="Re-prompt for every variable, including ones already set.",
    )
    parser.add_argument(
        "--required-only", action="store_true",
        help="Only prompt for REQUIRED variables (skip recommended/optional).",
    )
    args = parser.parse_args(argv)

    print(_c(_BOLD, "\n══════════════════════════════════════════"))
    print(_c(_BOLD, "  NIJA .env Setup Wizard"))
    print(_c(_BOLD, "══════════════════════════════════════════\n"))

    if not _ENV_EXAMPLE.exists():
        print(_c(_RED, f"❌  {_ENV_EXAMPLE} not found — cannot proceed."))
        return 1

    example_rows = _parse_example_order(_ENV_EXAMPLE)
    existing     = _parse_env_file(_ENV_FILE)
    final        = dict(existing)  # will accumulate updates

    env_exists = _ENV_FILE.exists()
    if env_exists:
        print(f"  Found existing .env at {_ENV_FILE}")
    else:
        print(f"  No .env found — will create {_ENV_FILE}")

    print(f"  Loaded {len(example_rows)} variables from .env.example\n")

    if args.check_only:
        _check_only(example_rows, existing, final)
        return 0

    # ── Prompt loop ────────────────────────────────────────────────────────
    print(_c(_CYAN, "  Walking through variables — press Enter to accept the shown value.\n"))
    updates: dict[str, str] = {}

    for key, example_val, _ in example_rows:
        current_val = existing.get(key, "")
        cat         = _category_label(key)

        # Decide whether to prompt
        if args.reset_all:
            should_prompt = True
        elif current_val:
            should_prompt = False  # already set — don't overwrite
        elif cat == "REQUIRED":
            should_prompt = True
        elif cat == "recommended" and not args.required_only:
            should_prompt = True
        else:
            should_prompt = False

        if not should_prompt:
            if current_val:
                final[key] = current_val  # keep existing
            elif example_val:
                final[key] = example_val  # use example default silently
            continue

        default = _DEFAULTS.get(key, example_val)
        is_secret = _is_secret_var(key)
        new_val = _prompt(key, current_val, default, is_secret)
        if new_val and new_val != current_val:
            updates[key] = new_val
            final[key]   = new_val

    # ── Write .env ─────────────────────────────────────────────────────────
    if updates:
        try:
            _write_env(_ENV_FILE, updates)
            print(_c(_GREEN, f"\n  ✅  .env written ({len(updates)} variable(s) updated/added)\n"))
        except Exception as exc:
            print(_c(_RED, f"\n  ❌  Failed to write .env: {exc}\n"))
            return 1
    else:
        print(_c(_GREEN, "\n  ✅  No changes needed — .env is already up to date.\n"))

    # ── Final status report ────────────────────────────────────────────────
    final_env = _parse_env_file(_ENV_FILE)
    example_current = _parse_example_order(_ENV_EXAMPLE)
    print(_c(_BOLD, "  Final status:"))
    _check_only(example_current, final_env, final_env)

    # ── Quick exchange-credential check ───────────────────────────────────
    has_kraken = bool(
        (final_env.get("KRAKEN_PLATFORM_API_KEY") and final_env.get("KRAKEN_PLATFORM_API_SECRET"))
        or (final_env.get("KRAKEN_API_KEY") and final_env.get("KRAKEN_API_SECRET"))
    )
    has_coinbase = bool(
        final_env.get("COINBASE_API_KEY") and final_env.get("COINBASE_API_SECRET")
    )
    lcv = final_env.get("LIVE_CAPITAL_VERIFIED", "false").lower()
    live_ok = lcv in ("true", "1", "yes")

    print(_c(_BOLD, "  Trading readiness:"))
    print(f"  {'✅' if has_kraken   else '❌'} Kraken credentials    {'configured' if has_kraken else 'NOT SET'}")
    print(f"  {'✅' if has_coinbase else '⚠️ '} Coinbase credentials  {'configured' if has_coinbase else 'not set (optional but recommended)'}")
    print(f"  {'✅' if live_ok      else '❌'} LIVE_CAPITAL_VERIFIED  = {lcv}")
    print()

    if not has_kraken and not has_coinbase:
        print(_c(_RED, "  🔴 No exchange credentials — the bot cannot connect to any broker."))
        print("     Set KRAKEN_PLATFORM_API_KEY + KRAKEN_PLATFORM_API_SECRET (or COINBASE equivalents).")
        return 1

    if not live_ok:
        print(_c(_YELLOW, "  ⚠️   LIVE_CAPITAL_VERIFIED is not true — bot will start in MONITOR mode."))
        print("     Set  LIVE_CAPITAL_VERIFIED=true  in .env when you're ready to trade live.")

    print(_c(_BOLD, "  Next steps:"))
    print("  1. Run:  python scripts/preflight_check.py  (full pre-flight validation)")
    print("  2. Run:  python scripts/reset_state_machine.py  (if state machine is in EMERGENCY_STOP)")
    print("  3. Start the bot:  bash start.sh\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
