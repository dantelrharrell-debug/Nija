#!/usr/bin/env python3
"""
validate_all_env_vars.py — Pre-flight credential checker for the Nija trading bot.

Usage:
    python3 validate_all_env_vars.py

Exit codes:
    0  All required credentials are present and valid → safe to start the bot.
    1  One or more required credentials are missing or contain placeholder values.
"""

import os
import sys

# ---------------------------------------------------------------------------
# Placeholder / dummy-value detection
# ---------------------------------------------------------------------------

_PLACEHOLDER_PATTERNS = {
    "xxx", "yyy", "zzz",
    "changeme", "change_me",
    "your_key", "your_secret", "your_api_key", "your_api_secret",
    "placeholder", "replace_me", "todo",
    "none", "null", "n/a", "na",
    "test", "demo", "fake", "dummy",
    "<your-api-key>", "<your-api-secret>",
}


def _is_placeholder(value: str) -> bool:
    """Return True when *value* looks like a dummy / unfilled placeholder."""
    stripped = value.strip().lower()
    if not stripped:
        return True
    # Exact match
    if stripped in _PLACEHOLDER_PATTERNS:
        return True
    # Starts-with match (e.g. "xxx_something")
    for pat in _PLACEHOLDER_PATTERNS:
        if stripped.startswith(pat):
            return True
    return False


def _check_var(name: str) -> tuple[bool, str | None]:
    """
    Return (is_valid, raw_value).

    is_valid = True  when the variable is set, non-empty, and not a placeholder.
    raw_value        is the raw os.environ value (or None when unset).
    """
    raw = os.environ.get(name)
    if raw is None:
        return False, None
    if not raw.strip():
        return False, raw
    if _is_placeholder(raw):
        return False, raw
    return True, raw


# ---------------------------------------------------------------------------
# Credential definitions
# ---------------------------------------------------------------------------

# Each entry: (display_label, [(key_name, secret_name), ...], required, fallback_note)
#   - The *first* pair is the primary name.
#   - Additional pairs are accepted fallbacks (checked in order).
#   - required=True  → failure causes exit 1
#   - required=False → failure prints a warning only

_CREDENTIALS = [
    # ── Kraken platform account (master) ────────────────────────────────────
    {
        "label": "Kraken Platform (master account)",
        "pairs": [
            ("KRAKEN_PLATFORM_API_KEY", "KRAKEN_PLATFORM_API_SECRET"),
        ],
        "required": True,
        "fallback_note": None,
    },
    # ── Kraken user: Tania Gilbert ───────────────────────────────────────────
    {
        "label": "Kraken User — Tania Gilbert",
        "pairs": [
            ("KRAKEN_USER_TANIA_GILBERT_API_KEY", "KRAKEN_USER_TANIA_GILBERT_API_SECRET"),
            ("KRAKEN_USER_TANIA_API_KEY",         "KRAKEN_USER_TANIA_API_SECRET"),
        ],
        "required": True,
        "fallback_note": (
            "Primary: KRAKEN_USER_TANIA_GILBERT_API_KEY / _SECRET\n"
            "         Fallback accepted: KRAKEN_USER_TANIA_API_KEY / _SECRET"
        ),
    },
    # ── Kraken user: Daivon ─────────────────────────────────────────────────
    {
        "label": "Kraken User — Daivon",
        "pairs": [
            ("KRAKEN_USER_DAIVON_API_KEY", "KRAKEN_USER_DAIVON_API_SECRET"),
        ],
        "required": True,
        "fallback_note": None,
    },
    # ── Optional brokers ────────────────────────────────────────────────────
    {
        "label": "Coinbase",
        "pairs": [
            ("COINBASE_API_KEY", "COINBASE_API_SECRET"),
        ],
        "required": False,
        "fallback_note": None,
    },
    {
        "label": "Alpaca",
        "pairs": [
            ("ALPACA_API_KEY", "ALPACA_API_SECRET"),
        ],
        "required": False,
        "fallback_note": None,
    },
    {
        "label": "Binance",
        "pairs": [
            ("BINANCE_API_KEY", "BINANCE_API_SECRET"),
        ],
        "required": False,
        "fallback_note": None,
    },
    {
        "label": "OKX",
        "pairs": [
            ("OKX_API_KEY", "OKX_API_SECRET"),
        ],
        "required": False,
        "fallback_note": None,
    },
]


# ---------------------------------------------------------------------------
# Validation logic
# ---------------------------------------------------------------------------

def _validate_credential(cred: dict) -> dict:
    """
    Evaluate a single credential entry.

    Returns a result dict:
        ok          bool   — True when at least one pair is fully valid
        matched_key str    — env-var name that passed (key side)
        matched_sec str    — env-var name that passed (secret side)
        issues      list   — human-readable problem descriptions
        fix_exports list   — "export KEY=..." lines to print on failure
    """
    issues: list[str] = []
    fix_exports: list[str] = []

    for key_name, secret_name in cred["pairs"]:
        key_ok, key_raw = _check_var(key_name)
        sec_ok, sec_raw = _check_var(secret_name)

        if key_ok and sec_ok:
            return {
                "ok": True,
                "matched_key": key_name,
                "matched_sec": secret_name,
                "issues": [],
                "fix_exports": [],
            }

        # Record problems for this pair
        if key_raw is None:
            issues.append(f"  • {key_name} is not set")
            fix_exports.append(f'  export {key_name}="your_actual_key_here"')
        elif not key_ok:
            issues.append(f"  • {key_name} is set but contains a placeholder value: {key_raw!r}")
            fix_exports.append(f'  export {key_name}="your_actual_key_here"')

        if sec_raw is None:
            issues.append(f"  • {secret_name} is not set")
            fix_exports.append(f'  export {secret_name}="your_actual_secret_here"')
        elif not sec_ok:
            issues.append(f"  • {secret_name} is set but contains a placeholder value: {sec_raw!r}")
            fix_exports.append(f'  export {secret_name}="your_actual_secret_here"')

    return {
        "ok": False,
        "matched_key": None,
        "matched_sec": None,
        "issues": issues,
        "fix_exports": fix_exports,
    }


def main() -> int:
    print()
    print("=" * 60)
    print("  Nija Bot — Pre-flight Credential Validator")
    print("=" * 60)
    print()

    any_required_failed = False
    export_lines: list[str] = []

    for cred in _CREDENTIALS:
        label = cred["label"]
        required = cred["required"]
        result = _validate_credential(cred)

        tag = "[REQUIRED]" if required else "[OPTIONAL]"

        if result["ok"]:
            matched = f"{result['matched_key']} / {result['matched_sec']}"
            print(f"  ✅  {tag} {label}")
            print(f"       Matched: {matched}")
        else:
            icon = "❌" if required else "⚠️ "
            status = "MISSING / INVALID" if required else "NOT SET (optional)"
            print(f"  {icon}  {tag} {label} — {status}")

            if cred["fallback_note"]:
                for line in cred["fallback_note"].splitlines():
                    print(f"       {line}")

            for issue in result["issues"]:
                print(f"     {issue}")

            if required:
                any_required_failed = True
                export_lines.extend(result["fix_exports"])

        print()

    # ── Summary ─────────────────────────────────────────────────────────────
    print("-" * 60)
    if any_required_failed:
        print()
        print("  ❌  One or more REQUIRED credentials are missing or invalid.")
        print()
        print("  Run the following export commands, then re-run this script:")
        print()
        # Deduplicate while preserving order
        seen: set[str] = set()
        for line in export_lines:
            if line not in seen:
                print(line)
                seen.add(line)
        print()
        print("  Re-run: python3 validate_all_env_vars.py")
        print()
        return 1
    else:
        print()
        print("  ✅  All required credentials are present and valid.")
        print("      Safe to start the bot.")
        print()
        return 0


if __name__ == "__main__":
    sys.exit(main())
