#!/usr/bin/env python3
"""
validate_all_env_vars.py — Pre-flight credential checker for the Nija trading bot.

Usage:
    python3 validate_all_env_vars.py

Exit codes:
    0  All required credentials are present and valid → safe to start the bot.
    1  One or more required credentials are missing or contain placeholder values.
NIJA — Validate All Environment Variables

Checks that every required credential (platform and per-user) is populated
before starting the bot.  Run this after setting credentials to confirm
everything is in place.

Credential layout
-----------------
Platform account (NIJA AI engine):
  KRAKEN_PLATFORM_API_KEY          — required
  KRAKEN_PLATFORM_API_SECRET       — required

User accounts (individual subscribers):
  Tania Gilbert  (user_id: tania_gilbert):
    KRAKEN_USER_TANIA_GILBERT_API_KEY    — primary (full name)
    KRAKEN_USER_TANIA_GILBERT_API_SECRET — primary (full name)
    KRAKEN_USER_TANIA_API_KEY            — accepted as fallback (first name)
    KRAKEN_USER_TANIA_API_SECRET         — accepted as fallback (first name)

  Daivon Frazier (user_id: daivon_frazier):
    KRAKEN_USER_DAIVON_API_KEY     — required
    KRAKEN_USER_DAIVON_API_SECRET  — required

Optional brokers (warnings only, bot still starts if absent):
  Coinbase: COINBASE_API_KEY / COINBASE_API_SECRET
  Alpaca:   ALPACA_API_KEY / ALPACA_API_SECRET
  Binance:  BINANCE_API_KEY / BINANCE_API_SECRET
  OKX:      OKX_API_KEY / OKX_API_SECRET / OKX_PASSPHRASE

Usage:
  python3 validate_all_env_vars.py

Exit codes:
  0 — all required credentials are present
  1 — one or more required credentials are missing or invalid
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
# ── Load .env if python-dotenv is available ────────────────────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # env vars must be injected externally (e.g. Railway, Docker)


# ── Colour helpers ─────────────────────────────────────────────────────────────
_USE_COLOUR = sys.stdout.isatty()


def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _USE_COLOUR else text


def _ok(msg: str) -> None:
    print(f"  {_c('32', '✅')} {msg}")


def _fail(msg: str) -> None:
    print(f"  {_c('31', '❌')} {msg}")


def _warn(msg: str) -> None:
    print(f"  {_c('33', '⚠️ ')} {msg}")


def _info(msg: str) -> None:
    print(f"  {_c('2', 'ℹ️ ')} {msg}")


def _section(title: str) -> None:
    bar = "─" * 60
    print(f"\n{_c('1', bar)}")
    print(f"{_c('1', title)}")
    print(_c('1', bar))


# ── Helpers ────────────────────────────────────────────────────────────────────

_PLACEHOLDERS = {
    "xxx", "yyy", "your_api_key", "your-api-key", "api_key",
    "your_api_secret", "your-api-secret", "api_secret",
    "changeme", "replace_me", "placeholder",
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
def _get(name: str) -> str:
    """Return stripped env-var value, or empty string if unset."""
    return os.getenv(name, "").strip()


def _mask(value: str) -> str:
    """Show length only — never log secret values."""
    return f"<{len(value)} chars>" if value else "(empty)"


def _check_var(name: str) -> tuple:
    """
    Validate a single env var.

    Returns:
        (is_ok: bool, display_value: str)
    """
    value = _get(name)
    if not value:
        return False, "(not set)"
    if value.lower() in _PLACEHOLDERS:
        return False, f"(placeholder: '{value}')"
    return True, _mask(value)


def _check_pair(key_name: str, secret_name: str) -> bool:
    """Check a key/secret pair. Prints results. Returns True if both are valid."""
    key_ok, key_disp = _check_var(key_name)
    sec_ok, sec_disp = _check_var(secret_name)

    if key_ok:
        _ok(f"{key_name} = {key_disp}")
    else:
        _fail(f"{key_name} — {key_disp}")

    if sec_ok:
        _ok(f"{secret_name} = {sec_disp}")
    else:
        _fail(f"{secret_name} — {sec_disp}")

    return key_ok and sec_ok


# ── Section checks ─────────────────────────────────────────────────────────────

def check_kraken_platform() -> bool:
    """Check NIJA platform (bot's own Kraken account)."""
    _section("Kraken PLATFORM account  (NIJA AI engine)")
    ok = _check_pair("KRAKEN_PLATFORM_API_KEY", "KRAKEN_PLATFORM_API_SECRET")

    # Legacy fallback awareness
    if not ok:
        leg_key_ok, _ = _check_var("KRAKEN_API_KEY")
        leg_sec_ok, _ = _check_var("KRAKEN_API_SECRET")
        if leg_key_ok and leg_sec_ok:
            _warn(
                "KRAKEN_API_KEY / KRAKEN_API_SECRET are set (legacy names). "
                "The bot will fall back to these, but prefer "
                "KRAKEN_PLATFORM_API_KEY / KRAKEN_PLATFORM_API_SECRET."
            )
            return True  # legacy is acceptable

    return ok


def check_kraken_user_tania() -> bool:
    """
    Check Kraken credentials for user Tania Gilbert.

    Primary env var names use the full user_id in uppercase:
      KRAKEN_USER_TANIA_GILBERT_API_KEY / _SECRET

    First-name-only variants are also accepted as fallbacks:
      KRAKEN_USER_TANIA_API_KEY / _SECRET
    """
    _section("Kraken USER — Tania Gilbert  (user_id: tania_gilbert)")

    # Primary: full name
    full_key_ok, full_key_disp = _check_var("KRAKEN_USER_TANIA_GILBERT_API_KEY")
    full_sec_ok, full_sec_disp = _check_var("KRAKEN_USER_TANIA_GILBERT_API_SECRET")

    # Fallback: first name only
    short_key_ok, short_key_disp = _check_var("KRAKEN_USER_TANIA_API_KEY")
    short_sec_ok, short_sec_disp = _check_var("KRAKEN_USER_TANIA_API_SECRET")

    key_ok = full_key_ok or short_key_ok
    sec_ok = full_sec_ok or short_sec_ok

    # Report key
    if full_key_ok:
        _ok(f"KRAKEN_USER_TANIA_GILBERT_API_KEY = {full_key_disp}")
    elif short_key_ok:
        _ok(
            f"KRAKEN_USER_TANIA_API_KEY = {short_key_disp}  "
            f"(fallback accepted; prefer KRAKEN_USER_TANIA_GILBERT_API_KEY)"
        )
    else:
        _fail("KRAKEN_USER_TANIA_GILBERT_API_KEY — not set or invalid")
        _info(
            "Also tried fallback: KRAKEN_USER_TANIA_API_KEY — "
            + short_key_disp
        )

    # Report secret
    if full_sec_ok:
        _ok(f"KRAKEN_USER_TANIA_GILBERT_API_SECRET = {full_sec_disp}")
    elif short_sec_ok:
        _ok(
            f"KRAKEN_USER_TANIA_API_SECRET = {short_sec_disp}  "
            f"(fallback accepted; prefer KRAKEN_USER_TANIA_GILBERT_API_SECRET)"
        )
    else:
        _fail("KRAKEN_USER_TANIA_GILBERT_API_SECRET — not set or invalid")
        _info(
            "Also tried fallback: KRAKEN_USER_TANIA_API_SECRET — "
            + short_sec_disp
        )

    if not key_ok or not sec_ok:
        print()
        _info("To fix, run:")
        _info('  export KRAKEN_USER_TANIA_GILBERT_API_KEY="<your-api-key>"')
        _info('  export KRAKEN_USER_TANIA_GILBERT_API_SECRET="<your-api-secret>"')
        _info("Or add those lines to your .env file.")

    return key_ok and sec_ok


def check_kraken_user_daivon() -> bool:
    """Check Kraken credentials for user Daivon Frazier."""
    _section("Kraken USER — Daivon Frazier  (user_id: daivon_frazier)")
    ok = _check_pair("KRAKEN_USER_DAIVON_API_KEY", "KRAKEN_USER_DAIVON_API_SECRET")

    if not ok:
        print()
        _info("To fix, run:")
        _info('  export KRAKEN_USER_DAIVON_API_KEY="<your-api-key>"')
        _info('  export KRAKEN_USER_DAIVON_API_SECRET="<your-api-secret>"')
        _info("Or add those lines to your .env file.")

    return ok


def check_coinbase() -> bool:
    """Check Coinbase Advanced Trade credentials (optional broker)."""
    _section("Coinbase Advanced Trade  (optional)")
    ok = _check_pair("COINBASE_API_KEY", "COINBASE_API_SECRET")

    if not ok:
        _warn("Coinbase credentials not configured — Coinbase trading will be disabled.")

    # Informational JWT fields
    for var in ("COINBASE_JWT_ISSUER", "COINBASE_JWT_KID"):
        is_set, disp = _check_var(var)
        if is_set:
            _info(f"{var} = {disp}  (optional — present)")
        else:
            _info(f"{var} — not set (optional)")

    return ok  # optional: not counted toward required pass/fail


def check_alpaca() -> bool:
    """Check Alpaca credentials (optional broker)."""
    _section("Alpaca Trading  (optional)")
    ok = _check_pair("ALPACA_API_KEY", "ALPACA_API_SECRET")
    paper_val = _get("ALPACA_PAPER") or "true (default)"
    _info(f"ALPACA_PAPER = {paper_val}")
    if not ok:
        _warn("Alpaca credentials not configured — Alpaca trading will be disabled.")
    return ok


def check_binance() -> bool:
    """Check Binance credentials (optional broker)."""
    _section("Binance  (optional)")
    key_ok, _ = _check_var("BINANCE_API_KEY")
    sec_ok, _ = _check_var("BINANCE_API_SECRET")
    if key_ok and sec_ok:
        _ok("BINANCE_API_KEY + BINANCE_API_SECRET — both set")
        return True
    _info("Binance credentials not configured (optional broker)")
    return False


def check_okx() -> bool:
    """Check OKX credentials (optional broker)."""
    _section("OKX  (optional)")
    key_ok, _ = _check_var("OKX_API_KEY")
    sec_ok, _ = _check_var("OKX_API_SECRET")
    pp_ok, _ = _check_var("OKX_PASSPHRASE")
    if key_ok and sec_ok and pp_ok:
        _ok("OKX_API_KEY + OKX_API_SECRET + OKX_PASSPHRASE — all set")
        return True
    _info("OKX credentials not fully configured (optional broker)")
    return False


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> int:
    print(_c("1", "\n" + "=" * 60))
    print(_c("1", "  NIJA — Environment Variable Validation"))
    print(_c("1", "=" * 60))

    # Required checks (failures block the bot)
    platform_ok = check_kraken_platform()
    tania_ok = check_kraken_user_tania()
    daivon_ok = check_kraken_user_daivon()

    # Optional checks (informational only)
    check_coinbase()
    check_alpaca()
    check_binance()
    check_okx()

    # ── Summary ────────────────────────────────────────────────────────────────
    _section("Summary")

    required = [
        ("Kraken PLATFORM", platform_ok),
        ("Kraken USER — Tania Gilbert", tania_ok),
        ("Kraken USER — Daivon Frazier", daivon_ok),
    ]

    all_ok = True
    for label, status in required:
        if status:
            _ok(f"{label}")
        else:
            _fail(f"{label}")
            all_ok = False

    print()
    if all_ok:
        print(_c("32", _c("1", "✅  ALL REQUIRED CREDENTIALS ARE SET — bot is ready to start.")))
        print()
        print("Next step:  restart the bot")
        print("  ./start.sh")
        return 0
    else:
        print(_c("31", _c("1", "❌  ONE OR MORE REQUIRED CREDENTIALS ARE MISSING.")))
        print()
        print("Set the missing variables in your .env file or via export, then re-run:")
        print("  python3 validate_all_env_vars.py")
        return 1


if __name__ == "__main__":
    sys.exit(main())
