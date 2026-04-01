#!/usr/bin/env python3
"""
NIJA Trading Bot — Broker Credential Validator
===============================================

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
"""

import os
import sys
import re
import time

# ── Load .env if present ──────────────────────────────────────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv not installed; rely on platform-injected env vars

# ── Colour helpers (graceful fallback when terminal has no colour support) ────
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
    _PLACEHOLDERS = {
        "your_api_key", "your-api-key", "api_key", "apikey",
        "your_api_secret", "your-api-secret", "api_secret", "apisecret",
        "changeme", "replace_me", "placeholder", "xxx", "yyy",
        "<your-api-key>", "<your-api-secret>",
    }
    if key.lower() in _PLACEHOLDERS:
        issues.append(f"{key_name} looks like a placeholder value: '{key}'")
    if secret.lower() in _PLACEHOLDERS:
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

    key    = _get("KRAKEN_PLATFORM_API_KEY")    or _get("KRAKEN_API_KEY")
    secret = _get("KRAKEN_PLATFORM_API_SECRET") or _get("KRAKEN_API_SECRET")

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
