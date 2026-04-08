#!/usr/bin/env python3
"""
NIJA Trading Bot — Kraken Connection Test
==========================================

Test the Kraken API connection for one or all accounts.

Usage:
    python3 test_kraken_connection.py --user platform
    python3 test_kraken_connection.py --user tania_gilbert
    python3 test_kraken_connection.py --user daivon_frazier
    python3 test_kraken_connection.py --user all

Arguments:
    --user  Which account to test.
            Accepted values: platform, tania_gilbert, daivon_frazier, all
            Default: platform

    --timeout  HTTP timeout in seconds (default: 15)

Exit codes:
    0  All tested accounts connected successfully.
    1  One or more accounts failed or credentials are missing.
"""

import argparse
import os
import sys
import time
from datetime import datetime, timezone

# ── Load .env ─────────────────────────────────────────────────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Add bot/ to path so we can import the nonce manager
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "bot"))

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


def _head(title: str) -> None:
    bar = "─" * 60
    print(f"\n{_c('1', bar)}")
    print(f"{_c('1', title)}")
    print(_c('1', bar))


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── Credential resolution ──────────────────────────────────────────────────────

def _resolve_credentials(user_id: str) -> tuple:
    """
    Resolve (api_key, api_secret, label) for a given user_id.

    user_id == "platform" uses KRAKEN_PLATFORM_API_KEY / _SECRET
    (with legacy KRAKEN_API_KEY / _SECRET fallback).

    Other user_ids follow the same logic as KrakenBroker.connect():
      first try the first-word env name (KRAKEN_USER_DAIVON_API_KEY),
      then fall back to the full user_id (KRAKEN_USER_TANIA_GILBERT_API_KEY).
    """
    if user_id == "platform":
        key = (os.getenv("KRAKEN_PLATFORM_API_KEY", "") or
               os.getenv("KRAKEN_API_KEY", "")).strip()
        secret = (os.getenv("KRAKEN_PLATFORM_API_SECRET", "") or
                  os.getenv("KRAKEN_API_SECRET", "")).strip()
        label = "PLATFORM"
    else:
        # First-word lookup (e.g., tania_gilbert → KRAKEN_USER_TANIA_API_KEY)
        first_word = user_id.split("_")[0].upper() if "_" in user_id else user_id.upper()
        key = os.getenv(f"KRAKEN_USER_{first_word}_API_KEY", "").strip()
        secret = os.getenv(f"KRAKEN_USER_{first_word}_API_SECRET", "").strip()

        # Full user_id fallback (e.g., KRAKEN_USER_TANIA_GILBERT_API_KEY)
        full_upper = user_id.upper()
        if full_upper != first_word:
            if not key:
                key = os.getenv(f"KRAKEN_USER_{full_upper}_API_KEY", "").strip()
            if not secret:
                secret = os.getenv(f"KRAKEN_USER_{full_upper}_API_SECRET", "").strip()

        label = f"USER:{user_id}"

    return key, secret, label


# ── Single-account test ────────────────────────────────────────────────────────

def test_account(user_id: str, timeout: int = 15) -> bool:
    """
    Run a live Kraken Balance call for the given user_id.

    Returns True on success, False on failure.
    """
    _head(f"Testing Kraken connection — {user_id}")

    api_key, api_secret, label = _resolve_credentials(user_id)

    if not api_key or not api_secret:
        missing = []
        if not api_key:
            missing.append("API key")
        if not api_secret:
            missing.append("API secret")
        _fail(f"{label}: {' and '.join(missing)} not configured — skipping")
        _info("Set the required env vars in .env or your deployment platform:")
        if user_id == "platform":
            _info("  KRAKEN_PLATFORM_API_KEY=<your-key>")
            _info("  KRAKEN_PLATFORM_API_SECRET=<your-secret>")
        else:
            first_word = user_id.split("_")[0].upper() if "_" in user_id else user_id.upper()
            _info(f"  KRAKEN_USER_{first_word}_API_KEY=<your-key>")
            _info(f"  KRAKEN_USER_{first_word}_API_SECRET=<your-secret>")
            full_upper = user_id.upper()
            if full_upper != first_word:
                _info(f"  OR: KRAKEN_USER_{full_upper}_API_KEY=<your-key>")
                _info(f"      KRAKEN_USER_{full_upper}_API_SECRET=<your-secret>")
        return False

    _info(f"Credentials:  key=<{len(api_key)} chars>  secret=<{len(api_secret)} chars>")

    try:
        import krakenex
    except ImportError:
        _fail("krakenex not installed — run: pip install krakenex")
        return False

    try:
        import global_kraken_nonce as gnm
        nonce_mgr = gnm.KrakenNonceManager()
    except Exception as exc:
        _warn(f"Could not load nonce manager: {exc}")
        _info("Will use krakenex default nonce (less reliable)")
        nonce_mgr = None

    # Build API client
    k = krakenex.API(key=api_key, secret=api_secret)

    # Apply timeout to the underlying requests session
    try:
        import functools
        k.session.request = functools.partial(k.session.request, timeout=timeout)
    except AttributeError:
        pass  # Older krakenex versions — no session attribute

    # Override nonce generator with the global manager when available
    if nonce_mgr is not None:
        try:
            k._nonce = gnm.get_kraken_nonce  # type: ignore[attr-defined]
        except Exception:
            pass  # Non-critical — fall back to default nonce

    # Fire the Balance call
    _info(f"Calling Kraken Balance API for {label}...")
    t0 = time.monotonic()
    try:
        nonce = gnm.get_kraken_nonce() if nonce_mgr else None
        params = {"nonce": nonce} if nonce else {}
        result = k.query_private("Balance", params)
        elapsed_ms = int((time.monotonic() - t0) * 1000)
    except Exception as exc:
        _fail(f"Request raised an exception: {exc}")
        if nonce_mgr:
            try:
                gnm.record_kraken_nonce_error()
            except Exception:
                pass
        return False

    errors = result.get("error", [])
    if errors:
        _fail(f"Kraken API returned errors ({elapsed_ms} ms): {errors}")
        if any("nonce" in str(e).lower() for e in errors):
            _warn("Nonce error detected — run: python3 reset_kraken_nonce.py")
        if any("permission" in str(e).lower() for e in errors):
            _warn("Permission error — ensure your API key has 'Query Funds' permission")
        if nonce_mgr:
            try:
                gnm.record_kraken_nonce_error()
            except Exception:
                pass
        return False

    # Success
    if nonce_mgr:
        try:
            gnm.record_kraken_nonce_success()
        except Exception:
            pass

    _ok(f"Connected successfully in {elapsed_ms} ms  [{label}]")
    balances = result.get("result", {})
    non_zero = {a: float(b) for a, b in balances.items() if float(b) > 0}
    if non_zero:
        _info(f"Non-zero balances ({len(non_zero)}):")
        for asset, bal in sorted(non_zero.items()):
            _info(f"    {asset}: {bal:.6f}")
    else:
        _info("Balance result received (all zero or no assets)")

    return True


# ── NTP check ─────────────────────────────────────────────────────────────────

def check_clock() -> bool:
    """Run NTP clock check. Returns True when within Kraken ±1 s tolerance."""
    _head("NTP Clock Check  (Kraken requires ±1 s accuracy)")
    try:
        from global_kraken_nonce import check_ntp_sync
        r = check_ntp_sync()
    except Exception:
        r = _raw_ntp_check()

    if r["error"]:
        _warn(f"NTP query failed: {r['error']}")
        _info("Verify manually: date -u  OR  sudo ntpdate pool.ntp.org")
        _info(f"System UTC time: {_ts()}")
        return True  # unknown — don't block

    offset_ms = r["offset_s"] * 1000
    abs_s = abs(r["offset_s"])
    server = r["server"]

    if not r["ok"]:
        _fail(
            f"CLOCK DRIFT: system is {r['offset_s']:+.3f} s ({offset_ms:+.0f} ms) vs {server}"
        )
        _fail("Kraken requires ±1 s — nonce errors WILL occur on ALL accounts.")
        _info("Fix NOW: sudo ntpdate pool.ntp.org")
        _info("     OR: sudo systemctl start chronyd")
        return False
    elif abs_s > 0.5:
        _warn(f"Clock drift: {r['offset_s']:+.3f} s ({offset_ms:+.0f} ms) vs {server} — within tolerance but monitor closely.")
        _info("Recommend: sudo ntpdate pool.ntp.org")
    else:
        _ok(f"Clock OK: {r['offset_s']:+.3f} s vs {server}")

    _info(f"System UTC time: {_ts()}")
    return True


def _raw_ntp_check() -> dict:
    """Raw UDP NTP fallback — no external library needed."""
    import socket
    import struct
    result = {"ok": False, "offset_s": 0.0, "server": "pool.ntp.org", "error": ""}
    try:
        msg = b'\x1b' + 47 * b'\0'
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(3.0)
            s.sendto(msg, ("pool.ntp.org", 123))
            data, _ = s.recvfrom(1024)
        if len(data) >= 44:
            ntp_time = struct.unpack('!I', data[40:44])[0] - 2208988800
            offset = ntp_time - time.time()
            result["offset_s"] = offset
            result["ok"] = abs(offset) <= 1.0
    except Exception as exc:
        result["error"] = str(exc)
    return result


# ── Main ───────────────────────────────────────────────────────────────────────

_ALL_USERS = ["platform", "tania_gilbert", "daivon_frazier"]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Test Kraken API connection for one or all NIJA accounts.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python3 test_kraken_connection.py --user platform\n"
            "  python3 test_kraken_connection.py --user tania_gilbert\n"
            "  python3 test_kraken_connection.py --user all\n"
        ),
    )
    parser.add_argument(
        "--user",
        default="platform",
        metavar="USER",
        help=(
            "Account to test: platform, tania_gilbert, daivon_frazier, or all "
            "(default: platform)"
        ),
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=15,
        metavar="SECONDS",
        help="HTTP timeout for the Kraken API call (default: 15)",
    )
    parser.add_argument(
        "--skip-clock",
        action="store_true",
        help="Skip the NTP clock check",
    )
    args = parser.parse_args()

    print(_c("1", "\n" + "=" * 60))
    print(_c("1", "  NIJA — Kraken Connection Test"))
    print(_c("1", "=" * 60))

    clock_ok = True
    if not args.skip_clock:
        clock_ok = check_clock()

    users_to_test = _ALL_USERS if args.user.lower() == "all" else [args.user.lower()]

    results: dict = {}
    for user_id in users_to_test:
        results[user_id] = test_account(user_id, timeout=args.timeout)

    _head("Summary")
    all_ok = True
    for user_id, ok in results.items():
        if ok:
            _ok(f"{user_id}")
        else:
            _fail(f"{user_id}")
            all_ok = False

    if not clock_ok:
        _fail("System clock drift — fix with: sudo ntpdate pool.ntp.org")
        all_ok = False

    print()
    if all_ok:
        print(_c("32", _c("1", "✅  All tested accounts connected successfully.")))
        print()
        print("Next step:  ./start.sh")
    else:
        print(_c("31", _c("1", "❌  One or more accounts failed — fix the issues above.")))
        print()
        print("If nonce errors persist, run:  python3 reset_kraken_nonce.py")
        print("To check credentials, run:     python3 validate_all_env_vars.py")

    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
