#!/usr/bin/env python3
"""
NIJA Trading Bot — Broker Credential Validator

Pre-deployment check that validates all broker API credentials are present,
non-empty, and structurally correct before the bot attempts live connections.

Checks performed:
  • Kraken PLATFORM  — key/secret present, Classic API key format
  • Coinbase         — key/secret present, JWT/CDP key format
  • Alpaca           — key/secret present
  • Binance          — key/secret present
  • OKX              — key/secret/passphrase present

Usage:
    python validate_broker_credentials.py

Exit codes:
    0 — all configured brokers passed validation
    1 — one or more critical credential errors found
NIJA Broker Credential Validator

Diagnoses why the trading bot is stuck in monitor mode by validating all
broker credentials and testing live API connections.

Checks:
  1. Kraken PLATFORM credentials + nonce state
  2. Coinbase credentials + live auth test
  3. Kraken USER (daivon_frazier) credentials
  4. Alpaca credentials
  5. Binance / OKX credentials (optional)
  6. Nonce file state for Kraken

Usage:
    python3 validate_broker_credentials.py

Exit codes:
    0 — At least one broker is fully operational
    1 — All brokers failed or no credentials found
"""

import os
import sys
import re
import time

# ── Load .env if present ──────────────────────────────────────────────────────
import time
import json
import socket
import hashlib
import hmac
import base64
import urllib.parse
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple

# ── Try to load .env if present ──────────────────────────────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv not installed; rely on platform-injected env vars

# ── Colour helpers (graceful fallback when terminal has no colour support) ────
    pass  # dotenv not installed; env vars must be set externally

# ── Colour helpers (graceful fallback on Windows / no-tty) ───────────────────
_USE_COLOUR = sys.stdout.isatty()

def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _USE_COLOUR else text

OK    = lambda t: _c("32", t)   # green
WARN  = lambda t: _c("33", t)   # yellow
ERR   = lambda t: _c("31", t)   # red
BOLD  = lambda t: _c("1",  t)   # bold
DIM   = lambda t: _c("2",  t)   # dim


# ─────────────────────────────────────────────────────────────────────────────
# Validation helpers
# ─────────────────────────────────────────────────────────────────────────────

# Comprehensive placeholder pattern that matches any unfilled credential value.
# Anchored (^...$) so it only fires when the *entire* value looks like a
# placeholder (e.g. "your_kraken_api_key_here"), not when a real key merely
# starts with a common word.
# Bracketed groups use negated char classes (e.g. [^>]+) to prevent backtracking.
# "none" / "null" only match when the entire credential is that exact word.
_PLACEHOLDER_RE = re.compile(
    r"^(your[_\-]?.*|replace[_\-]?.*|change[_\-]?me?|insert[_\-]?.*|fill[_\-]?.*|"
    r"xxx+|placeholder.*|example.*|sample.*|testkey|test[_\-]api|test[_\-]secret|"
    r"dummy.*|fake.*|todo.*|none|null|n/?a|"
    r"<[^>]+>|\[[^\]]+\]|\{[^}]+\}|api[_\-]?key|api[_\-]?secret|key[_\-]?here|"
    r"secret[_\-]?here|\*+)$",
    re.IGNORECASE,
)


def _is_placeholder(value: str) -> bool:
    """Return True if *value* looks like an unfilled placeholder."""
    return bool(_PLACEHOLDER_RE.match(value.strip()))


def _get(name: str) -> str:
    """Return stripped env-var value, or empty string if unset."""
    return os.getenv(name, "").strip()


def _check_pair(key_name: str, secret_name: str, label: str) -> tuple:
    """
    Validate a key/secret pair.

    Returns:
        (ok: bool, issues: list[str])
    """
    issues = []
    key    = _get(key_name)
    secret = _get(secret_name)

    if not key and not secret:
        return False, [f"{label} credentials not configured ({key_name} / {secret_name} are both unset)"]

    if not key:
        issues.append(f"{key_name} is missing or empty")
    if not secret:
        issues.append(f"{secret_name} is missing or empty")

    # Detect placeholder values that were never replaced
    if key and _is_placeholder(key):
        issues.append(f"{key_name} looks like a placeholder value: '{key}'")
    if secret and _is_placeholder(secret):
        issues.append(f"{secret_name} looks like a placeholder value")

    return len(issues) == 0, issues


def _validate_kraken_platform() -> dict:
    """
    Validate Kraken PLATFORM credentials.

    Kraken Classic API keys:
      - Key:    26-character alphanumeric string
      - Secret: Base64-encoded string (typically 88 characters)
    """
    result = {
        "broker": "Kraken (PLATFORM)",
        "configured": False,
        "valid": False,
        "issues": [],
        "warnings": [],
    }

    def get_kraken_creds() -> Tuple[str, str]:
        return (
            _get("KRAKEN_PLATFORM_API_KEY")
            or _get("KRAKEN_USER_TANIA_GILBERT_API_KEY")
            or _get("KRAKEN_API_KEY"),
            _get("KRAKEN_PLATFORM_API_SECRET")
            or _get("KRAKEN_USER_TANIA_GILBERT_API_SECRET")
            or _get("KRAKEN_API_SECRET"),
        )

    key, secret = get_kraken_creds()

    if not key and not secret:
        result["issues"].append(
            "KRAKEN_PLATFORM_API_KEY and KRAKEN_PLATFORM_API_SECRET are both unset"
        )
        result["issues"].append(
            "Set them in Railway → Variables or in your .env file"
        )
        return result

    result["configured"] = True

    if not key:
        result["issues"].append("KRAKEN_PLATFORM_API_KEY is missing or empty")
    if not secret:
        result["issues"].append("KRAKEN_PLATFORM_API_SECRET is missing or empty")

    if key and secret:
        # Detect placeholder values from .env templates (e.g. "your_kraken_api_key_here")
        if _is_placeholder(key):
            result["issues"].append(
                f"KRAKEN_PLATFORM_API_KEY looks like a placeholder ('{key}') — "
                "replace it with your real Kraken Classic API key from "
                "https://www.kraken.com/u/security/api"
            )
        if _is_placeholder(secret):
            result["issues"].append(
                "KRAKEN_PLATFORM_API_SECRET looks like a placeholder — "
                "replace it with your real Kraken API secret (88+ char Base64 string)"
            )

        if not result["issues"]:
            # Kraken Classic API key is 56 characters (alphanumeric + /+)
            # Accept a broad range to avoid false positives across key generations
            if len(key) < 20:
                result["warnings"].append(
                    f"KRAKEN_PLATFORM_API_KEY looks short ({len(key)} chars); "
                    "Classic API keys are typically 56 characters"
                )

            # Warn if it looks like an OAuth token (starts with "Bearer " or contains spaces)
            if " " in key:
                result["issues"].append(
                    "KRAKEN_PLATFORM_API_KEY contains spaces — must be a Classic API key, not OAuth"
                )

            # Warn if secret is suspiciously short
            if len(secret) < 40:
                result["warnings"].append(
                    f"KRAKEN_PLATFORM_API_SECRET looks short ({len(secret)} chars); "
                    "Classic API secrets are typically 88+ characters (Base64)"
                )

        result["valid"] = len(result["issues"]) == 0

    return result


def _validate_coinbase() -> dict:
    """
    Validate Coinbase Advanced Trade / CDP credentials.

    CDP Cloud API Key format:
      - Key:    "organizations/{org_id}/apiKeys/{key_id}"
      - Secret: EC private key in PEM format (-----BEGIN EC PRIVATE KEY-----)
    """
    result = {
        "broker": "Coinbase",
        "configured": False,
        "valid": False,
        "issues": [],
        "warnings": [],
    }

    key    = _get("COINBASE_API_KEY")
    secret = _get("COINBASE_API_SECRET")

    if not key and not secret:
        result["issues"].append(
            "COINBASE_API_KEY and COINBASE_API_SECRET are both unset"
        )
        return result

    result["configured"] = True

    if not key:
        result["issues"].append("COINBASE_API_KEY is missing or empty")
    if not secret:
        result["issues"].append("COINBASE_API_SECRET is missing or empty")

    if key and secret:
        # CDP key format: organizations/{uuid}/apiKeys/{uuid}
        # Legacy format: alphanumeric string
        is_cdp_format = key.startswith("organizations/") and "/apiKeys/" in key
        is_legacy_format = re.match(r'^[A-Za-z0-9_\-]{20,}$', key) is not None

        if not is_cdp_format and not is_legacy_format:
            result["warnings"].append(
                "COINBASE_API_KEY format is unexpected. "
                "CDP keys look like: organizations/{org_id}/apiKeys/{key_id}"
            )

        # Check for PEM-formatted secret (CDP format)
        if "BEGIN EC PRIVATE KEY" in secret or "BEGIN PRIVATE KEY" in secret:
            pass  # Valid PEM format
        elif len(secret) < 30:
            result["warnings"].append(
                f"COINBASE_API_SECRET looks short ({len(secret)} chars); "
                "CDP secrets are EC private keys in PEM format"
            )

        # Detect 401 root cause: secret with literal \\n instead of real newlines
        if "\\n" in secret and "\n" not in secret:
            result["issues"].append(
                "COINBASE_API_SECRET contains literal '\\\\n' instead of real newlines. "
                "This causes 401 Unauthorized errors. "
                "In Railway Variables, paste the PEM key with actual line breaks, "
                "or use $'...' quoting in shell."
            )

        result["valid"] = len(result["issues"]) == 0

    return result


def _validate_alpaca() -> dict:
    """Validate Alpaca credentials."""
    result = {
        "broker": "Alpaca",
        "configured": False,
        "valid": False,
        "issues": [],
        "warnings": [],
    }

    key    = _get("ALPACA_API_KEY")
    secret = _get("ALPACA_API_SECRET")

    if not key and not secret:
        result["issues"].append("ALPACA_API_KEY and ALPACA_API_SECRET are both unset")
        return result

    result["configured"] = True

    if not key:
        result["issues"].append("ALPACA_API_KEY is missing or empty")
    if not secret:
        result["issues"].append("ALPACA_API_SECRET is missing or empty")

    if key and secret:
        # Alpaca paper keys start with PK, live keys start with AK
        if not (key.startswith("PK") or key.startswith("AK")):
            result["warnings"].append(
                f"ALPACA_API_KEY prefix '{key[:2]}' is unexpected "
                "(paper keys start with PK, live keys with AK)"
            )

        paper_mode = _get("ALPACA_PAPER").lower() in ("true", "1", "yes")
        if not paper_mode:
            result["warnings"].append(
                "ALPACA_PAPER is not set to 'true' — bot will use LIVE Alpaca trading"
            )

        result["valid"] = len(result["issues"]) == 0

    return result


def _validate_binance() -> dict:
    """Validate Binance credentials."""
    result = {
        "broker": "Binance",
        "configured": False,
        "valid": False,
        "issues": [],
        "warnings": [],
    }

    key    = _get("BINANCE_API_KEY")
    secret = _get("BINANCE_API_SECRET")

    if not key and not secret:
        result["issues"].append("BINANCE_API_KEY and BINANCE_API_SECRET are both unset")
        return result

    result["configured"] = True

    if not key:
        result["issues"].append("BINANCE_API_KEY is missing or empty")
    if not secret:
        result["issues"].append("BINANCE_API_SECRET is missing or empty")

    if key and secret:
        # Binance API keys are 64-character alphanumeric strings
        if len(key) < 30:
            result["warnings"].append(
                f"BINANCE_API_KEY looks short ({len(key)} chars); "
                "Binance keys are typically 64 characters"
            )
        result["valid"] = len(result["issues"]) == 0

    return result


def _validate_okx() -> dict:
    """Validate OKX credentials (requires passphrase in addition to key/secret)."""
    result = {
        "broker": "OKX",
        "configured": False,
        "valid": False,
        "issues": [],
        "warnings": [],
    }

    key        = _get("OKX_API_KEY")
    secret     = _get("OKX_API_SECRET")
    passphrase = _get("OKX_PASSPHRASE")

    if not key and not secret and not passphrase:
        result["issues"].append(
            "OKX_API_KEY, OKX_API_SECRET, and OKX_PASSPHRASE are all unset"
        )
        return result

    result["configured"] = True

    if not key:
        result["issues"].append("OKX_API_KEY is missing or empty")
    if not secret:
        result["issues"].append("OKX_API_SECRET is missing or empty")
    if not passphrase:
        result["issues"].append(
            "OKX_PASSPHRASE is missing or empty — OKX requires a passphrase in addition to key/secret"
        )

    # Detect placeholder passphrase values
    _PLACEHOLDER_PASSPHRASES = {
        "your_passphrase", "your-passphrase", "passphrase",
        "your_password", "password", "changeme",
    }
    if passphrase and passphrase.lower() in _PLACEHOLDER_PASSPHRASES:
        result["issues"].append(
            f"OKX_PASSPHRASE looks like a placeholder: '{passphrase}'"
        )

    result["valid"] = len(result["issues"]) == 0
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Kraken nonce health check
# ─────────────────────────────────────────────────────────────────────────────

def _check_kraken_nonce_health() -> dict:
    """
    Check whether the global Kraken nonce manager is healthy.

    Returns a dict with 'ok' (bool) and 'message' (str).
    """
    try:
        from bot.global_kraken_nonce import get_global_nonce_manager, get_global_nonce_stats
        manager = get_global_nonce_manager()
        stats   = get_global_nonce_stats()

        # Generate two consecutive nonces and verify they are strictly increasing
        n1 = manager.get_nonce()
        n2 = manager.get_nonce()

        if n2 <= n1:
            return {
                "ok": False,
                "message": f"Nonce is NOT monotonically increasing: {n1} → {n2}",
            }

        return {
            "ok": True,
            "message": (
                f"Global nonce manager healthy — "
                f"last nonce: {stats['last_nonce']}, "
                f"total issued: {stats['total_nonces_issued']}"
            ),
        }
    except ImportError:
        return {
            "ok": False,
            "message": "bot.global_kraken_nonce module not found — nonce manager unavailable",
        }
    except Exception as exc:
        return {"ok": False, "message": f"Nonce health check error: {exc}"}


# ─────────────────────────────────────────────────────────────────────────────
# Live connection tests (optional — only run when --test-connections is passed)
# ─────────────────────────────────────────────────────────────────────────────

def _test_kraken_connection() -> dict:
    """
    Attempt a lightweight Kraken API call (public ticker) to verify network
    reachability without consuming a private nonce.
    """
    result = {"ok": False, "message": ""}
    try:
        import requests
        resp = requests.get(
            "https://api.kraken.com/0/public/Time",
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            server_time = data.get("result", {}).get("unixtime", 0)
            local_time  = int(time.time())
            drift_secs  = abs(local_time - server_time)
            if drift_secs > 30:
                result["message"] = (
                    f"Kraken server reachable but clock drift is {drift_secs}s "
                    "(>30s). Large drift causes 'EAPI:Invalid nonce' errors. "
                    "Sync your system clock with NTP."
                )
                result["ok"] = False
            else:
                result["ok"]      = True
                result["message"] = (
                    f"Kraken API reachable — server time OK, clock drift: {drift_secs}s"
                )
        else:
            result["message"] = f"Kraken API returned HTTP {resp.status_code}"
    except Exception as exc:
        result["message"] = f"Could not reach Kraken API: {exc}"
    return result


def _test_coinbase_connection() -> dict:
    """
    Attempt a lightweight Coinbase public API call to verify network reachability.
    """
    result = {"ok": False, "message": ""}
    try:
        import requests
        resp = requests.get(
            "https://api.coinbase.com/v2/time",
            timeout=10,
        )
        if resp.status_code == 200:
            result["ok"]      = True
            result["message"] = "Coinbase API reachable"
        else:
            result["message"] = f"Coinbase API returned HTTP {resp.status_code}"
    except Exception as exc:
        result["message"] = f"Could not reach Coinbase API: {exc}"
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Report rendering
# ─────────────────────────────────────────────────────────────────────────────

def _render_broker_result(r: dict) -> None:
    broker = r["broker"]
    if not r["configured"]:
        print(f"  {DIM('⚪')} {BOLD(broker):30s}  {DIM('not configured (skipped)')}")
        return

    if r["valid"]:
        print(f"  {OK('✅')} {BOLD(broker):30s}  {OK('credentials look valid')}")
    else:
        print(f"  {ERR('❌')} {BOLD(broker):30s}  {ERR('CREDENTIAL ERRORS FOUND')}")

    for issue in r["issues"]:
        print(f"       {ERR('→')} {issue}")
    for warn in r["warnings"]:
        print(f"       {WARN('⚠')}  {warn}")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main() -> int:
    test_connections = "--test-connections" in sys.argv

    print()
    print(BOLD("═" * 65))
    print(BOLD("  NIJA Trading Bot — Broker Credential Validator"))
    print(BOLD("═" * 65))
    print()

    # ── 1. Validate credentials ───────────────────────────────────────────────
    print(BOLD("1. Credential presence & format checks"))
    print("─" * 65)

    validators = [
        _validate_kraken_platform,
        _validate_coinbase,
        _validate_alpaca,
        _validate_binance,
        _validate_okx,
    ]

    results          = [v() for v in validators]
    configured_count = sum(1 for r in results if r["configured"])
    error_count      = sum(1 for r in results if r["configured"] and not r["valid"])

    for r in results:
        _render_broker_result(r)

    print()

    # ── 2. Nonce health ───────────────────────────────────────────────────────
    print(BOLD("2. Kraken nonce manager health"))
    print("─" * 65)
    nonce_health = _check_kraken_nonce_health()
    if nonce_health["ok"]:
        print(f"  {OK('✅')} {nonce_health['message']}")
    else:
        print(f"  {ERR('❌')} {nonce_health['message']}")
        error_count += 1
    print()

    # ── 3. Optional live connectivity tests ───────────────────────────────────
    if test_connections:
        print(BOLD("3. Live connectivity tests (--test-connections)"))
        print("─" * 65)

        kraken_r = _validate_kraken_platform()
        if kraken_r["configured"]:
            conn = _test_kraken_connection()
            icon = OK("✅") if conn["ok"] else ERR("❌")
            print(f"  {icon} Kraken network: {conn['message']}")
            if not conn["ok"]:
                error_count += 1

        coinbase_r = _validate_coinbase()
        if coinbase_r["configured"]:
            conn = _test_coinbase_connection()
            icon = OK("✅") if conn["ok"] else ERR("❌")
            print(f"  {icon} Coinbase network: {conn['message']}")
            if not conn["ok"]:
                error_count += 1

        print()

    # ── 4. Summary ────────────────────────────────────────────────────────────
    print(BOLD("Summary"))
    print("─" * 65)
    print(f"  Brokers configured : {configured_count} / {len(results)}")
    print(f"  Errors found       : {error_count}")
    print()

    if configured_count == 0:
        print(ERR("  ❌ FATAL: No broker credentials are configured."))
        print(ERR("     The bot cannot trade without at least one broker."))
        print()
        print("  Configure credentials in Railway → Variables or in .env:")
        print("    KRAKEN_PLATFORM_API_KEY=...")
        print("    KRAKEN_PLATFORM_API_SECRET=...")
        print("  See CREDENTIAL_SETUP.md for step-by-step instructions.")
        print()
        return 1

    if error_count > 0:
        print(ERR(f"  ❌ {error_count} error(s) found — fix them before deploying."))
        print()
        print("  Common fixes:")
        print("  • Kraken 'EAPI:Invalid nonce'  → run reset_kraken_nonce.py")
        print("  • Coinbase 401 Unauthorized    → check PEM newlines in secret")
        print("  • Missing credentials          → see CREDENTIAL_SETUP.md")
        print()
        return 1

    print(OK("  ✅ All configured broker credentials passed validation."))
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
def green(t):  return _c("32", t)
def red(t):    return _c("31", t)
def yellow(t): return _c("33", t)
def cyan(t):   return _c("36", t)
def bold(t):   return _c("1",  t)

# ── Pretty-print helpers ──────────────────────────────────────────────────────
def section(title: str):
    bar = "=" * 72
    print(f"\n{bold(bar)}")
    print(f"  {bold(title)}")
    print(bold(bar))

def ok(msg: str):   print(f"  {green('✅')} {msg}")
def warn(msg: str): print(f"  {yellow('⚠️ ')} {msg}")
def fail(msg: str): print(f"  {red('❌')} {msg}")
def info(msg: str): print(f"  {cyan('ℹ️ ')} {msg}")
def step(msg: str): print(f"\n  {bold('→')} {msg}")

# ── Credential presence check ─────────────────────────────────────────────────

def _env(name: str) -> str:
    """Return stripped env var value, or empty string."""
    return (os.getenv(name) or "").strip()

def _check_var(name: str, label: Optional[str] = None) -> Tuple[bool, str]:
    """
    Check whether an env var is set and non-empty.

    Returns (is_set, display_value) where display_value is a masked preview.
    """
    val = _env(name)
    display = label or name
    if not val:
        return False, ""
    # Show first 6 chars + masked tail so the user can confirm it's the right key
    preview = val[:6] + "*" * min(len(val) - 6, 20) if len(val) > 6 else "***"
    return True, preview

# ─────────────────────────────────────────────────────────────────────────────
# 1. CREDENTIAL PRESENCE VALIDATION
# ─────────────────────────────────────────────────────────────────────────────

def validate_credentials() -> dict:
    """
    Check all expected env vars and report which are set / missing.

    Returns a dict keyed by broker with True/False for each credential group.
    """
    section("STEP 1 — CREDENTIAL PRESENCE CHECK")

    results = {}

    # ── Kraken PLATFORM ───────────────────────────────────────────────────────
    step("Kraken PLATFORM (bot's own trading account)")
    kp_key_ok,    kp_key_prev    = _check_var("KRAKEN_PLATFORM_API_KEY")
    kp_secret_ok, kp_secret_prev = _check_var("KRAKEN_PLATFORM_API_SECRET")

    if kp_key_ok:
        ok(f"KRAKEN_PLATFORM_API_KEY     = {kp_key_prev}")
    else:
        fail("KRAKEN_PLATFORM_API_KEY     — NOT SET or empty")

    if kp_secret_ok:
        ok(f"KRAKEN_PLATFORM_API_SECRET  = {kp_secret_prev}")
    else:
        fail("KRAKEN_PLATFORM_API_SECRET  — NOT SET or empty")

    # Legacy fallback keys (backward compat)
    legacy_key_ok,    _ = _check_var("KRAKEN_API_KEY")
    legacy_secret_ok, _ = _check_var("KRAKEN_API_SECRET")
    if not kp_key_ok and legacy_key_ok:
        warn("KRAKEN_API_KEY found (legacy) — bot will fall back to this")
    if not kp_secret_ok and legacy_secret_ok:
        warn("KRAKEN_API_SECRET found (legacy) — bot will fall back to this")

    results["kraken_platform"] = kp_key_ok and kp_secret_ok

    # ── Coinbase ──────────────────────────────────────────────────────────────
    step("Coinbase Advanced Trade")
    cb_key_ok,    cb_key_prev    = _check_var("COINBASE_API_KEY")
    cb_secret_ok, cb_secret_prev = _check_var("COINBASE_API_SECRET")

    if cb_key_ok:
        ok(f"COINBASE_API_KEY     = {cb_key_prev}")
    else:
        fail("COINBASE_API_KEY     — NOT SET or empty")

    if cb_secret_ok:
        ok(f"COINBASE_API_SECRET  = {cb_secret_prev}")
    else:
        fail("COINBASE_API_SECRET  — NOT SET or empty")

    # Optional JWT fields (used by some Coinbase SDK versions)
    for var in ("COINBASE_ORG_ID", "COINBASE_JWT_ISSUER", "COINBASE_JWT_KID"):
        is_set, prev = _check_var(var)
        if is_set:
            info(f"{var} = {prev}  (optional — present)")
        else:
            info(f"{var} — not set (optional)")

    results["coinbase"] = cb_key_ok and cb_secret_ok

    # ── Kraken USER: daivon_frazier ───────────────────────────────────────────
    step("Kraken USER — daivon_frazier")
    ku_key_ok,    ku_key_prev    = _check_var("KRAKEN_USER_DAIVON_API_KEY")
    ku_secret_ok, ku_secret_prev = _check_var("KRAKEN_USER_DAIVON_API_SECRET")

    if ku_key_ok:
        ok(f"KRAKEN_USER_DAIVON_API_KEY     = {ku_key_prev}")
    else:
        fail("KRAKEN_USER_DAIVON_API_KEY     — NOT SET or empty")

    if ku_secret_ok:
        ok(f"KRAKEN_USER_DAIVON_API_SECRET  = {ku_secret_prev}")
    else:
        fail("KRAKEN_USER_DAIVON_API_SECRET  — NOT SET or empty")

    results["kraken_user_daivon"] = ku_key_ok and ku_secret_ok

    # ── Alpaca ────────────────────────────────────────────────────────────────
    step("Alpaca Trading")
    al_key_ok,    al_key_prev    = _check_var("ALPACA_API_KEY")
    al_secret_ok, al_secret_prev = _check_var("ALPACA_API_SECRET")
    al_paper_val = _env("ALPACA_PAPER") or "true (default)"

    if al_key_ok:
        ok(f"ALPACA_API_KEY     = {al_key_prev}")
    else:
        fail("ALPACA_API_KEY     — NOT SET or empty")

    if al_secret_ok:
        ok(f"ALPACA_API_SECRET  = {al_secret_prev}")
    else:
        fail("ALPACA_API_SECRET  — NOT SET or empty")

    info(f"ALPACA_PAPER       = {al_paper_val}")

    results["alpaca"] = al_key_ok and al_secret_ok

    # ── Binance (optional) ────────────────────────────────────────────────────
    step("Binance (optional)")
    bn_key_ok, _    = _check_var("BINANCE_API_KEY")
    bn_secret_ok, _ = _check_var("BINANCE_API_SECRET")
    if bn_key_ok and bn_secret_ok:
        ok("BINANCE_API_KEY + BINANCE_API_SECRET — both set")
    else:
        info("Binance credentials not configured (optional broker)")
    results["binance"] = bn_key_ok and bn_secret_ok

    # ── OKX (optional) ────────────────────────────────────────────────────────
    step("OKX (optional)")
    okx_key_ok, _        = _check_var("OKX_API_KEY")
    okx_secret_ok, _     = _check_var("OKX_API_SECRET")
    okx_passphrase_ok, _ = _check_var("OKX_PASSPHRASE")
    if okx_key_ok and okx_secret_ok and okx_passphrase_ok:
        ok("OKX_API_KEY + OKX_API_SECRET + OKX_PASSPHRASE — all set")
    else:
        info("OKX credentials not fully configured (optional broker)")
    results["okx"] = okx_key_ok and okx_secret_ok and okx_passphrase_ok

    return results

# ─────────────────────────────────────────────────────────────────────────────
# 2. KRAKEN PLATFORM CONNECTION TEST
# ─────────────────────────────────────────────────────────────────────────────

def _kraken_public_request(endpoint: str, timeout: int = 10) -> dict:
    """Make a public (unauthenticated) Kraken API request."""
    url = f"https://api.kraken.com/0/public/{endpoint}"
    req = urllib.request.Request(url, headers={"User-Agent": "NIJA-Validator/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())

def _kraken_private_request(
    endpoint: str,
    api_key: str,
    api_secret: str,
    data: Optional[dict] = None,
    timeout: int = 15,
) -> dict:
    """
    Make an authenticated Kraken private API request.

    Uses the global KrakenNonceManager so every nonce is strictly monotonic
    and consistent with the bot's nonce state.
    """
    try:
        from bot.global_kraken_nonce import get_kraken_nonce as _get_kraken_nonce
    except ImportError:
        try:
            from global_kraken_nonce import get_kraken_nonce as _get_kraken_nonce
        except ImportError:
            _get_kraken_nonce = lambda: int(time.time() * 1000)  # noqa: E731

    url_path = f"/0/private/{endpoint}"
    url = f"https://api.kraken.com{url_path}"

    nonce = str(_get_kraken_nonce())
    post_data = {"nonce": nonce}
    if data:
        post_data.update(data)

    encoded = urllib.parse.urlencode(post_data).encode()

    # Kraken signature: SHA-256(nonce + POST body) then HMAC-SHA-512 with decoded secret
    sha256_hash = hashlib.sha256((nonce + urllib.parse.urlencode(post_data)).encode()).digest()
    secret_decoded = base64.b64decode(api_secret)
    mac = hmac.new(secret_decoded, url_path.encode() + sha256_hash, hashlib.sha512)
    signature = base64.b64encode(mac.digest()).decode()

    headers = {
        "API-Key": api_key,
        "API-Sign": signature,
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": "NIJA-Validator/1.0",
    }

    req = urllib.request.Request(url, data=encoded, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())

def test_kraken_platform() -> bool:
    """
    Test Kraken PLATFORM connection:
      1. Fetch server time (public) — verifies network + clock skew
      2. Fetch account balance (private) — verifies credentials + nonce
    """
    section("STEP 2 — KRAKEN PLATFORM CONNECTION TEST")

    api_key    = _env("KRAKEN_PLATFORM_API_KEY") or _env("KRAKEN_API_KEY")
    api_secret = _env("KRAKEN_PLATFORM_API_SECRET") or _env("KRAKEN_API_SECRET")

    if not api_key or not api_secret:
        fail("Skipping — no Kraken PLATFORM credentials found")
        return False

    # ── 2a. Public: server time ───────────────────────────────────────────────
    step("Fetching Kraken server time (public endpoint)…")
    try:
        result = _kraken_public_request("Time", timeout=10)
        if result.get("error"):
            fail(f"Kraken server time error: {result['error']}")
        else:
            server_ts  = result["result"]["unixtime"]
            local_ts   = int(time.time())
            skew_secs  = abs(local_ts - server_ts)
            server_dt  = datetime.fromtimestamp(server_ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            ok(f"Kraken server time: {server_dt}")
            if skew_secs > 30:
                warn(
                    f"Clock skew is {skew_secs}s — this WILL cause 'Invalid nonce' errors!\n"
                    "     Fix: sync your system clock with NTP (e.g. 'ntpdate pool.ntp.org')"
                )
            else:
                ok(f"Clock skew: {skew_secs}s (within acceptable range)")
    except socket.timeout:
        fail("Timeout reaching Kraken public API (network issue)")
        return False
    except Exception as exc:
        fail(f"Could not reach Kraken public API: {exc}")
        return False

    # ── 2b. Private: balance ──────────────────────────────────────────────────
    step("Testing Kraken PLATFORM private API (Balance endpoint)…")
    try:
        result = _kraken_private_request("Balance", api_key, api_secret, timeout=15)
        errors = result.get("error", [])

        if not errors:
            balances = result.get("result", {})
            usd_keys = [k for k in balances if "USD" in k or "ZUSD" in k]
            usd_total = sum(float(balances[k]) for k in usd_keys)
            ok(f"Kraken PLATFORM authenticated successfully")
            ok(f"USD balance: ${usd_total:.2f}")
            if usd_total < 1.0:
                warn("Balance is very low — bot may not trade (minimum ~$25 required)")
            return True

        error_str = " | ".join(errors)

        if "EAPI:Invalid nonce" in error_str or "nonce" in error_str.lower():
            fail(f"Nonce error: {error_str}")
            warn(
                "The nonce stored in the bot's data directory is out of sync with Kraken.\n"
                "     This happens after a restart or if multiple processes share the same API key."
            )
            _suggest_nonce_fix()
            return False

        if "EAPI:Invalid key" in error_str or "Invalid key" in error_str:
            fail(f"Invalid API key: {error_str}")
            warn(
                "The API key or secret is wrong / revoked.\n"
                "     → Log in to https://www.kraken.com/u/security/api and regenerate the key.\n"
                "     → Update KRAKEN_PLATFORM_API_KEY and KRAKEN_PLATFORM_API_SECRET in Railway."
            )
            return False

        if "EAPI:Permission denied" in error_str or "permission" in error_str.lower():
            fail(f"Permission denied: {error_str}")
            warn(
                "The API key exists but lacks required permissions.\n"
                "     Required permissions: Query Funds, Create & Modify Orders, Cancel Orders.\n"
                "     → Edit the key at https://www.kraken.com/u/security/api"
            )
            return False

        fail(f"Kraken PLATFORM API error: {error_str}")
        return False

    except socket.timeout:
        fail("Timeout on Kraken private API call (15s) — possible network issue or API overload")
        warn(
            "If this happens repeatedly:\n"
            "     • Check Railway outbound network connectivity\n"
            "     • Kraken may be under maintenance — check https://status.kraken.com"
        )
        return False
    except Exception as exc:
        fail(f"Kraken PLATFORM connection failed: {exc}")
        return False

# ─────────────────────────────────────────────────────────────────────────────
# 3. COINBASE CONNECTION TEST
# ─────────────────────────────────────────────────────────────────────────────

def test_coinbase() -> bool:
    """
    Test Coinbase Advanced Trade connection by fetching accounts.
    Uses the coinbase-advanced-py SDK if available, otherwise falls back
    to a raw HTTPS request.
    """
    section("STEP 3 — COINBASE CONNECTION TEST")

    api_key    = _env("COINBASE_API_KEY")
    api_secret = _env("COINBASE_API_SECRET")

    if not api_key or not api_secret:
        fail("Skipping — COINBASE_API_KEY or COINBASE_API_SECRET not set")
        return False

    step("Attempting Coinbase Advanced Trade authentication…")

    # ── Try SDK first ─────────────────────────────────────────────────────────
    try:
        from coinbase.rest import RESTClient  # type: ignore

        # Normalise escaped newlines in PEM keys (common Railway env var issue)
        secret = api_secret.replace("\\n", "\n")

        client = RESTClient(api_key=api_key, api_secret=secret)
        resp = client.get_accounts()
        accounts = getattr(resp, "accounts", []) or []

        usd_total = 0.0
        for acct in accounts:
            currency = getattr(acct, "currency", "")
            if currency in ("USD", "USDC"):
                bal_obj = getattr(acct, "available_balance", None)
                usd_total += float(getattr(bal_obj, "value", 0) or 0)

        ok(f"Coinbase authenticated successfully ({len(accounts)} account(s) found)")
        ok(f"USD/USDC balance: ${usd_total:.2f}")

        if usd_total < 10.0:
            warn("Balance is very low — Coinbase requires ≥$10 to trade")

        return True

    except ImportError:
        warn("coinbase-advanced-py SDK not installed — falling back to raw HTTPS check")

    except Exception as exc:
        error_str = str(exc)

        if "401" in error_str or "Unauthorized" in error_str.lower():
            fail(f"Coinbase 401 Unauthorized: {error_str}")
            warn(
                "The API key or secret is invalid or has been revoked.\n"
                "     Common causes:\n"
                "       1. COINBASE_API_SECRET contains a PEM private key with literal '\\n' instead of real newlines.\n"
                "          Fix: In Railway, paste the key with actual line breaks, not '\\n' escape sequences.\n"
                "       2. The API key was created for Coinbase.com (consumer) instead of Coinbase Advanced Trade.\n"
                "          Fix: Create a new key at https://www.coinbase.com/settings/api\n"
                "       3. The key has been revoked or expired.\n"
                "          Fix: Regenerate at https://www.coinbase.com/settings/api and update Railway vars."
            )
            return False

        if "403" in error_str or "Forbidden" in error_str.lower():
            fail(f"Coinbase 403 Forbidden: {error_str}")
            warn(
                "The API key exists but lacks required permissions.\n"
                "     Required scopes: wallet:accounts:read, wallet:orders:create, wallet:orders:read\n"
                "     → Regenerate the key with correct permissions at https://www.coinbase.com/settings/api"
            )
            return False

        fail(f"Coinbase connection failed: {error_str}")
        return False

    # ── Raw HTTPS fallback (no SDK) ───────────────────────────────────────────
    step("Raw HTTPS connectivity check to Coinbase API…")
    try:
        url = "https://api.coinbase.com/v2/time"
        req = urllib.request.Request(url, headers={"User-Agent": "NIJA-Validator/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            epoch = data.get("data", {}).get("epoch", "?")
            ok(f"Coinbase API reachable (server epoch: {epoch})")
            info("SDK not installed — cannot verify credentials without coinbase-advanced-py")
            return False
    except Exception as exc:
        fail(f"Cannot reach Coinbase API: {exc}")
        return False

# ─────────────────────────────────────────────────────────────────────────────
# 4. KRAKEN NONCE FILE STATE
# ─────────────────────────────────────────────────────────────────────────────

def check_nonce_files():
    """
    Inspect all Kraken nonce files in the data/ directory and report their
    state.  A nonce that is far in the future (> 5 minutes ahead of now)
    is a likely cause of persistent 'Invalid nonce' errors.
    """
    section("STEP 4 — KRAKEN NONCE FILE STATE")

    # Determine data directory (mirrors bot/broker_manager.py logic)
    script_dir = Path(__file__).resolve().parent
    data_dir   = script_dir / "data"

    step(f"Looking for nonce files in: {data_dir}")

    if not data_dir.exists():
        warn(f"data/ directory does not exist at {data_dir}")
        info("This is normal on a fresh deployment — nonce files are created on first run")
        return

    nonce_files = list(data_dir.glob("kraken_nonce*.txt"))

    if not nonce_files:
        info("No Kraken nonce files found — bot will generate fresh nonces on startup")
        return

    now_ms = int(time.time() * 1000)

    for nf in sorted(nonce_files):
        mtime = datetime.fromtimestamp(nf.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        try:
            raw = nf.read_text().strip()
            if not raw:
                warn(f"{nf.name}: file is empty — will be regenerated on startup")
                continue

            nonce_val = int(raw)

            # Detect unit: nanoseconds (19 digits) vs milliseconds (13 digits)
            if nonce_val > 1e18:
                # Nanosecond nonce — convert to ms for comparison
                nonce_ms = nonce_val // 1_000_000
                unit = "ns"
            elif nonce_val > 1e12:
                nonce_ms = nonce_val
                unit = "ms"
            else:
                # Suspiciously small — probably seconds or corrupted
                warn(f"{nf.name}: nonce value {nonce_val} looks corrupted (too small)")
                info(f"  → Delete this file: rm {nf}")
                continue

            skew_ms   = nonce_ms - now_ms
            skew_secs = skew_ms / 1000

            if skew_secs > 300:
                fail(
                    f"{nf.name}: nonce is {skew_secs:.0f}s in the FUTURE "
                    f"(last modified: {mtime}, unit: {unit})"
                )
                warn(
                    f"This nonce is too far ahead — Kraken will reject it.\n"
                    f"     Fix: delete the file and restart the bot:\n"
                    f"       rm {nf}"
                )
            elif skew_secs < -300:
                warn(
                    f"{nf.name}: nonce is {abs(skew_secs):.0f}s in the PAST "
                    f"(last modified: {mtime}, unit: {unit})"
                )
                info(
                    "A past nonce is usually fine — the bot will advance it on startup.\n"
                    f"     If you see persistent nonce errors, delete: {nf}"
                )
            else:
                ok(
                    f"{nf.name}: nonce is current "
                    f"(skew: {skew_secs:+.1f}s, last modified: {mtime}, unit: {unit})"
                )

        except ValueError:
            fail(f"{nf.name}: contains non-numeric data — file is corrupted")
            info(f"  → Delete this file: rm {nf}")
        except PermissionError:
            warn(f"{nf.name}: permission denied — cannot read file")

def _suggest_nonce_fix():
    """Print nonce reset instructions."""
    script_dir = Path(__file__).resolve().parent
    data_dir   = script_dir / "data"
    print()
    print(f"  {bold('Nonce reset instructions:')}")
    print(f"    1. Stop the bot (Railway → your service → Stop)")
    print(f"    2. Delete nonce files:")
    print(f"         rm -f {data_dir}/kraken_nonce*.txt")
    print(f"    3. Restart the bot — it will generate fresh nonces automatically")
    print(f"    4. If errors persist, wait 60 seconds before restarting (Kraken nonce window)")

# ─────────────────────────────────────────────────────────────────────────────
# 5. SUMMARY & TROUBLESHOOTING GUIDE
# ─────────────────────────────────────────────────────────────────────────────

def print_summary(cred_results: dict, kraken_ok: bool, coinbase_ok: bool):
    section("SUMMARY & NEXT STEPS")

    any_broker_ok = kraken_ok or coinbase_ok

    print()
    print(f"  {'Broker':<30} {'Credentials':^14} {'Live Test':^12}")
    print(f"  {'-'*30} {'-'*14} {'-'*12}")

    def _row(name, cred_key, live_result):
        cred_icon = green("✅ SET") if cred_results.get(cred_key) else red("❌ MISSING")
        live_icon = (
            green("✅ PASS") if live_result is True
            else red("❌ FAIL") if live_result is False
            else yellow("⚠️  SKIPPED")
        )
        print(f"  {name:<30} {cred_icon:^22} {live_icon:^20}")

    _row("Kraken PLATFORM",        "kraken_platform",    kraken_ok)
    _row("Coinbase Advanced Trade", "coinbase",           coinbase_ok)
    _row("Kraken USER (daivon)",    "kraken_user_daivon", None)
    _row("Alpaca",                  "alpaca",             None)
    _row("Binance (optional)",      "binance",            None)
    _row("OKX (optional)",          "okx",                None)

    print()

    if any_broker_ok:
        ok("At least one broker is operational — the bot should be able to trade")
    else:
        fail("NO brokers passed the live connection test — bot will stay in monitor mode")

    # ── Actionable fix list ───────────────────────────────────────────────────
    fixes_needed = []

    if not cred_results.get("kraken_platform"):
        fixes_needed.append(
            "Set KRAKEN_PLATFORM_API_KEY and KRAKEN_PLATFORM_API_SECRET in Railway.\n"
            "     Create a Classic API key (NOT OAuth) at https://www.kraken.com/u/security/api\n"
            "     Required permissions: Query Funds, Create & Modify Orders, Cancel Orders"
        )
    elif not kraken_ok:
        fixes_needed.append(
            "Kraken credentials are set but the live test failed.\n"
            "     • If the error was 'Invalid nonce': delete data/kraken_nonce*.txt and restart\n"
            "     • If the error was 'Invalid key': regenerate the API key on Kraken\n"
            "     • If the error was a timeout: check Railway outbound network / Kraken status"
        )

    if not cred_results.get("coinbase"):
        fixes_needed.append(
            "Set COINBASE_API_KEY and COINBASE_API_SECRET in Railway.\n"
            "     Create an Advanced Trade API key at https://www.coinbase.com/settings/api\n"
            "     IMPORTANT: The secret is a PEM private key — paste it with real newlines,\n"
            "     not '\\\\n' escape sequences, in the Railway variable editor."
        )
    elif not coinbase_ok:
        fixes_needed.append(
            "Coinbase credentials are set but authentication failed (401).\n"
            "     • Check that COINBASE_API_SECRET is a valid PEM key with real newlines\n"
            "     • Verify the key has not been revoked at https://www.coinbase.com/settings/api\n"
            "     • Ensure the key was created for Advanced Trade (not the consumer app)"
        )

    if not cred_results.get("kraken_user_daivon"):
        fixes_needed.append(
            "Set KRAKEN_USER_DAIVON_API_KEY and KRAKEN_USER_DAIVON_API_SECRET in Railway.\n"
            "     daivon_frazier must create their own Kraken API key at:\n"
            "     https://www.kraken.com/u/security/api"
        )

    if not cred_results.get("alpaca"):
        fixes_needed.append(
            "Set ALPACA_API_KEY and ALPACA_API_SECRET in Railway (optional but recommended).\n"
            "     Create a key at https://alpaca.markets/\n"
            "     Set ALPACA_PAPER=false for live trading, ALPACA_PAPER=true for paper trading"
        )

    if fixes_needed:
        print()
        print(f"  {bold('Required fixes:')}")
        for i, fix in enumerate(fixes_needed, 1):
            print(f"\n  {bold(str(i) + '.')} {fix}")

    # ── Restart instructions ──────────────────────────────────────────────────
    print()
    print(f"  {bold('After fixing credentials:')}")
    print("    1. Update the Railway environment variables")
    print("    2. Trigger a redeploy (Railway → your service → Deploy)")
    print("    3. Watch the logs for '✅ Kraken PLATFORM connected' or '✅ Coinbase connected'")
    print("    4. If Kraken still shows nonce errors after redeploy:")
    print("       a. Open a Railway shell and run:  rm -f data/kraken_nonce*.txt")
    print("       b. Redeploy again")
    print()

# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main() -> int:
    print()
    print(bold("=" * 72))
    print(bold("  NIJA BROKER CREDENTIAL VALIDATOR"))
    print(f"  Run at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} local / "
          f"{datetime.now(timezone.utc).strftime('%H:%M:%S')} UTC")
    print(bold("=" * 72))

    # Step 1 — credential presence
    cred_results = validate_credentials()

    # Step 2 — Kraken live test
    kraken_ok = test_kraken_platform()

    # Step 3 — Coinbase live test
    coinbase_ok = test_coinbase()

    # Step 4 — nonce file inspection
    check_nonce_files()

    # Step 5 — summary
    print_summary(cred_results, kraken_ok, coinbase_ok)

    return 0 if (kraken_ok or coinbase_ok) else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\nValidation cancelled.")
        sys.exit(1)
    except Exception as exc:
        import traceback
        print(f"\n{red('Fatal error during validation:')}")
        traceback.print_exc()
        sys.exit(1)
