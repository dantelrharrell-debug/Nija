#!/usr/bin/env python3
"""
NIJA Trading Bot — Kraken Nonce Reset Utility
==============================================

Safely resets the Kraken nonce state when the bot is stuck with
"EAPI:Invalid nonce" errors, and diagnoses common root causes.

What this script does:
  0. Checks system clock skew against an NTP server
  1. Validates Kraken API key and secret configuration
  2. Locates any persisted nonce files in the data/ directory
  3. Backs them up before touching anything
  4. Resets the in-memory GlobalKrakenNonceManager to a fresh timestamp
  5. Writes a new, safe nonce value to each nonce file
  6. Verifies the new nonce is strictly greater than the old one
  7. Runs a live Kraken connectivity test to confirm the reset worked

When to run this:
  • Bot logs show repeated "EAPI:Invalid nonce" errors
  • Bot was restarted rapidly and nonces are out of sync
  • After a system clock correction that moved time backward
  • After regenerating API keys

Usage:
    python reset_kraken_nonce.py [--dry-run]

    --dry-run   Show what would be changed without writing anything

Exit codes:
    0 — reset completed successfully (or dry-run completed)
    1 — reset failed
"""

import os
import sys
import time
import glob
import shutil
import socket
import struct
from datetime import datetime, timezone
from typing import Optional

# ── Load .env if present ──────────────────────────────────────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

DRY_RUN = "--dry-run" in sys.argv

# Buffer applied to the nonce on reset.  Matches GlobalKrakenNonceManager's
# _STARTUP_LEAD_NS (25 s) — the same value used by reset_to_safe_value() —
# so both the in-memory manager and the persisted file start at now + 25 s.
# This keeps the lead safely under the 60 s HARD-RESET threshold while
# providing enough headroom for escalating error-recovery jumps (10s + 20s).
_NONCE_BUFFER_NS = 25 * 1_000_000_000  # 25 seconds in nanoseconds
_NONCE_BUFFER_MS = _NONCE_BUFFER_NS // 1_000_000  # same buffer for legacy ms files

# NTP parameters used by the clock-skew check.
_NTP_HOST = "pool.ntp.org"
_NTP_PORT = 123
_NTP_TIMEOUT = 3.0  # seconds
# Acceptable clock offset thresholds
_NTP_WARN_OFFSET_S = 2.0   # warn if |offset| > 2 s
_NTP_ERROR_OFFSET_S = 10.0  # fail if |offset| > 10 s (Kraken will reject nonces)

# Basename of the primary global nonce file — defined once to avoid duplication.
_GLOBAL_NONCE_FILENAME = "kraken_global_nonce.txt"

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_nonce_file(path: str) -> Optional[int]:
    """Read a nonce value from a file. Returns None if file is missing or corrupt."""
    try:
        with open(path) as f:
            raw = f.read().strip()
        return int(raw) if raw else None
    except (OSError, ValueError):
        return None


def _write_nonce_file(path: str, value: int) -> None:
    """Write a nonce value to a file (creates parent dirs if needed)."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as f:
        f.write(str(value))


def _backup_nonce_file(path: str) -> Optional[str]:
    """
    Create a timestamped backup of a nonce file.

    Returns the backup path, or None if the source file doesn't exist.
    """
    if not os.path.exists(path):
        return None
    backup_path = f"{path}.bak.{int(time.time())}"
    shutil.copy2(path, backup_path)
    return backup_path


# ─────────────────────────────────────────────────────────────────────────────
# NTP clock-skew check
# ─────────────────────────────────────────────────────────────────────────────

def _query_ntp_offset(host: str = _NTP_HOST, timeout: float = _NTP_TIMEOUT) -> tuple:
    """
    Query an NTP server and return the system clock offset in seconds.

    Uses a raw UDP NTP v3 packet — no external library required.

    Returns:
        (offset_seconds: float | None, error_message: str | None)
        offset > 0 means local clock is ahead; offset < 0 means behind.
    """
    # Minimal NTP request: LI=0, VN=3, Mode=3 (client), all other fields zero.
    ntp_request = b'\x1b' + b'\x00' * 47
    # NTP epoch is 1900-01-01; Unix epoch is 1970-01-01 — delta is 70 years.
    _NTP_EPOCH_DELTA = 2_208_988_800

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(timeout)
        sock.sendto(ntp_request, (host, _NTP_PORT))
        data, _ = sock.recvfrom(1024)
        sock.close()
    except OSError as exc:
        return None, f"NTP socket error: {exc}"

    if len(data) < 48:
        return None, f"NTP response too short ({len(data)} bytes)"

    # The Transmit Timestamp starts at byte 40: 4 bytes integer + 4 bytes fraction.
    int_part  = struct.unpack("!I", data[40:44])[0]
    frac_part = struct.unpack("!I", data[44:48])[0]
    ntp_time  = int_part - _NTP_EPOCH_DELTA + frac_part / 2**32
    offset    = time.time() - ntp_time
    return offset, None


def _check_system_clock() -> tuple:
    """
    Verify system clock against NTP.

    Returns:
        (ok: bool, message: str)
    """
    offset, err = _query_ntp_offset()
    if err:
        return True, f"NTP check skipped ({err}) — ensure system clock is synced via NTP/chrony"

    abs_offset = abs(offset)
    direction  = "ahead" if offset > 0 else "behind"
    offset_str = f"{abs_offset:.2f} s {direction} of NTP"

    if abs_offset > _NTP_ERROR_OFFSET_S:
        return False, (
            f"CLOCK SKEW TOO LARGE: {offset_str}. "
            f"Kraken will reject nonces until clock is resynced. "
            f"Run: sudo ntpdate pool.ntp.org  (or: timedatectl set-ntp true)"
        )
    if abs_offset > _NTP_WARN_OFFSET_S:
        return True, (
            f"Clock skew detected: {offset_str}. "
            f"Nonce reset may still fail — consider syncing with NTP."
        )
    return True, f"System clock OK (offset {offset_str})"


# ─────────────────────────────────────────────────────────────────────────────
# API key / secret validation
# ─────────────────────────────────────────────────────────────────────────────

# Placeholder values that indicate unconfigured credentials.
_PLACEHOLDER_PATTERNS = (
    "your_api_key", "your_api_secret", "xxx", "changeme",
    "your-key", "your-secret", "placeholder", "api_key_here",
)

def _check_kraken_credentials() -> tuple:
    """
    Verify that Kraken API key and secret are set and pass basic format checks.

    Checks both platform-level and legacy env-var names.

    Returns:
        (ok: bool, message: str, issues: list[str])
    """
    api_key = (os.environ.get("KRAKEN_PLATFORM_API_KEY") or
               os.environ.get("KRAKEN_API_KEY", "")).strip()
    api_secret = (os.environ.get("KRAKEN_PLATFORM_API_SECRET") or
                  os.environ.get("KRAKEN_API_SECRET", "")).strip()

    issues: list[str] = []

    # ── Key ──────────────────────────────────────────────────────────────────
    if not api_key:
        issues.append("KRAKEN_PLATFORM_API_KEY / KRAKEN_API_KEY is not set or empty")
    elif any(p in api_key.lower() for p in _PLACEHOLDER_PATTERNS):
        issues.append(f"API key looks like a placeholder: {api_key[:20]}…")
    elif len(api_key) < 20:
        issues.append(f"API key appears too short ({len(api_key)} chars — expected 26+)")

    # ── Secret ───────────────────────────────────────────────────────────────
    if not api_secret:
        issues.append("KRAKEN_PLATFORM_API_SECRET / KRAKEN_API_SECRET is not set or empty")
    elif any(p in api_secret.lower() for p in _PLACEHOLDER_PATTERNS):
        issues.append("API secret looks like a placeholder")
    elif len(api_secret) < 40:
        issues.append(f"API secret appears too short ({len(api_secret)} chars — expected 88+)")

    if issues:
        return False, "Credential issues found", issues
    return True, "Kraken API credentials are configured", []


# ─────────────────────────────────────────────────────────────────────────────
# Live Kraken connectivity test
# ─────────────────────────────────────────────────────────────────────────────

def _test_kraken_connectivity() -> tuple:
    """
    Make a lightweight authenticated Kraken API call (GetBalance) to confirm
    that the reset nonce is accepted.

    Returns:
        (ok: bool, message: str)
    """
    try:
        import krakenex  # type: ignore
    except ImportError:
        return True, "krakenex not available — skipping live connectivity test"

    api_key    = (os.environ.get("KRAKEN_PLATFORM_API_KEY")    or
                  os.environ.get("KRAKEN_API_KEY",    "")).strip()
    api_secret = (os.environ.get("KRAKEN_PLATFORM_API_SECRET") or
                  os.environ.get("KRAKEN_API_SECRET", "")).strip()

    if not api_key or not api_secret:
        return True, "Credentials not set — skipping live connectivity test"

    try:
        from bot.global_kraken_nonce import get_global_nonce_manager
        manager = get_global_nonce_manager()

        api = krakenex.API(key=api_key, secret=api_secret)

        def _nonce() -> str:  # noqa: WPS430
            return str(manager.get_nonce())

        # krakenex does not expose a public nonce-override API; assigning to
        # _nonce is the documented workaround used throughout broker_manager.py.
        api._nonce = _nonce

        resp = api.query_private("Balance")
        if resp is None:
            return False, "Kraken Balance call returned None"
        errors = resp.get("error", [])
        if errors:
            # Distinguish nonce errors from auth errors
            nonce_errors = [e for e in errors if "nonce" in e.lower()]
            auth_errors  = [e for e in errors if "invalid key" in e.lower() or "permission" in e.lower()]
            if nonce_errors:
                return False, f"Nonce still rejected after reset: {nonce_errors}"
            if auth_errors:
                return False, f"API key/secret rejected by Kraken: {auth_errors}"
            return False, f"Kraken returned errors: {errors}"

        # Record success so escalation counter resets
        try:
            from bot.global_kraken_nonce import record_kraken_nonce_success
            record_kraken_nonce_success()
        except Exception:
            pass

        return True, "Kraken connectivity test passed — nonce accepted"

    except Exception as exc:
        return False, f"Connectivity test error: {exc}"


# ─────────────────────────────────────────────────────────────────────────────
# Nonce file discovery
# ─────────────────────────────────────────────────────────────────────────────

def _find_nonce_files() -> list[str]:
    """
    Find all Kraken nonce files in the data/ directory.

    Includes:
        data/kraken_global_nonce.txt   — primary global nonce file
        data/kraken_nonce_platform.txt — legacy per-account files
        data/kraken_nonce_user_*.txt   — legacy per-account files
    """
    patterns = [
        f"data/{_GLOBAL_NONCE_FILENAME}",  # primary global nonce (nanoseconds)
        "data/kraken_nonce_*.txt",          # legacy per-account files (milliseconds)
        "kraken_nonce_*.txt",               # fallback: root directory
    ]
    found = []
    for pattern in patterns:
        found.extend(glob.glob(pattern))
    # Deduplicate while preserving order
    seen = set()
    unique = []
    for p in found:
        if p not in seen:
            seen.add(p)
            unique.append(p)
    return unique


# ─────────────────────────────────────────────────────────────────────────────
# In-memory nonce manager reset
# ─────────────────────────────────────────────────────────────────────────────

def _reset_global_nonce_manager() -> tuple:
    """
    Reset the GlobalKrakenNonceManager singleton to a fresh nanosecond timestamp
    and persist the new value to disk.

    Uses reset_to_safe_value() which atomically sets _last_nonce = now + 10 s
    and writes it to data/kraken_global_nonce.txt.

    Returns:
        (success: bool, message: str, new_nonce: int)
    """
    try:
        from bot.global_kraken_nonce import GlobalKrakenNonceManager
        manager = GlobalKrakenNonceManager()

        if DRY_RUN:
            new_nonce = time.time_ns() + _NONCE_BUFFER_NS  # preview only
            return True, f"[DRY-RUN] Would reset GlobalKrakenNonceManager to ~{new_nonce} (now + 25 s)", new_nonce

        # reset_to_safe_value() updates _last_nonce AND persists to disk atomically.
        new_nonce = manager.reset_to_safe_value()
        return True, f"GlobalKrakenNonceManager reset to {new_nonce} (now + 25 s, persisted to disk)", new_nonce

    except ImportError:
        return False, "bot.global_kraken_nonce not found — skipping in-memory reset", 0
    except Exception as exc:
        return False, f"Failed to reset GlobalKrakenNonceManager: {exc}", 0


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main() -> int:
    print()
    print("=" * 65)
    print("  NIJA Trading Bot — Kraken Nonce Reset Utility")
    if DRY_RUN:
        print("  *** DRY-RUN MODE — no files will be written ***")
    print("=" * 65)
    print(f"  Timestamp: {_ts()}")
    print()

    errors = 0

    # ── Step 0: System clock / NTP check ─────────────────────────────────────
    print("Step 0: Check system clock (NTP sync)")
    print("-" * 65)
    if DRY_RUN:
        print("  [DRY-RUN] Would query pool.ntp.org for clock skew")
    else:
        clock_ok, clock_msg = _check_system_clock()
        if clock_ok:
            if "skew" in clock_msg.lower() or "skipped" in clock_msg.lower():
                print(f"  ⚠️  {clock_msg}")
            else:
                print(f"  ✅ {clock_msg}")
        else:
            print(f"  ❌ {clock_msg}")
            errors += 1
    print()

    # ── Step 1: API key / secret validation ───────────────────────────────────
    print("Step 1: Validate Kraken API key and secret")
    print("-" * 65)
    if DRY_RUN:
        print("  [DRY-RUN] Would check KRAKEN_PLATFORM_API_KEY / KRAKEN_API_KEY env vars")
    else:
        cred_ok, cred_msg, cred_issues = _check_kraken_credentials()
        if cred_ok:
            print(f"  ✅ {cred_msg}")
        else:
            print(f"  ❌ {cred_msg}:")
            for issue in cred_issues:
                print(f"     • {issue}")
            errors += 1
            print()
            print("  ℹ️  Fix the API key/secret issues before proceeding.")
            print("     The nonce reset will continue but the bot will not trade")
            print("     until valid credentials are provided in the .env file.")
    print()

    # ── Step 2: Reset in-memory nonce manager ────────────────────────────────
    print("Step 2: Reset in-memory GlobalKrakenNonceManager")
    print("-" * 65)
    ok, msg, new_nonce_ns = _reset_global_nonce_manager()
    if ok:
        print(f"  ✅ {msg}")
    else:
        print(f"  ⚠️  {msg}")
        # Not fatal — nonce files can still be reset independently
    print()

    # ── Step 3: Discover and reset nonce files ────────────────────────────────
    print("Step 3: Reset persisted nonce files")
    print("-" * 65)

    nonce_files = _find_nonce_files()

    if not nonce_files:
        print("  ℹ️  No nonce files found in data/ — nothing to reset.")
        print("     (Files are created automatically on first Kraken connection.)")
    else:
        for path in nonce_files:
            old_value = _read_nonce_file(path)
            old_str   = str(old_value) if old_value is not None else "<missing/corrupt>"

            # The global nonce file uses nanosecond precision (19-digit values).
            # Legacy per-account files used millisecond precision (13-digit values).
            is_global = os.path.basename(path) == _GLOBAL_NONCE_FILENAME
            if is_global:
                new_value = time.time_ns() + _NONCE_BUFFER_NS
                unit_label = f"+{_NONCE_BUFFER_NS // 1_000_000_000} s buffer (nanoseconds)"
            else:
                new_value = int(time.time() * 1000) + _NONCE_BUFFER_MS
                unit_label = f"+{_NONCE_BUFFER_MS // 1000} s buffer (milliseconds)"

            if DRY_RUN:
                print(f"  [DRY-RUN] {path}")
                print(f"            old: {old_str}")
                print(f"            new: {new_value}  ({unit_label})")
                continue

            # Backup first
            backup = _backup_nonce_file(path)
            if backup:
                print(f"  📦 Backed up: {path} → {os.path.basename(backup)}")

            # Write new value
            try:
                _write_nonce_file(path, new_value)
                print(f"  ✅ Reset: {path}")
                print(f"     old: {old_str}")
                print(f"     new: {new_value}  ({unit_label})")
            except OSError as exc:
                print(f"  ❌ Failed to write {path}: {exc}")
                errors += 1

    print()

    # ── Step 4: Verify monotonicity ───────────────────────────────────────────
    print("Step 4: Verify nonce monotonicity")
    print("-" * 65)
    try:
        from bot.global_kraken_nonce import get_global_nonce_manager
        manager = get_global_nonce_manager()
        n1 = manager.get_nonce()
        n2 = manager.get_nonce()
        if n2 > n1:
            print(f"  ✅ Nonce is monotonically increasing: {n1} → {n2}")
        else:
            print(f"  ❌ Nonce is NOT monotonically increasing: {n1} → {n2}")
            errors += 1
    except Exception as exc:
        print(f"  ⚠️  Could not verify nonce monotonicity: {exc}")
    print()

    # ── Step 5: Live Kraken connectivity test ─────────────────────────────────
    print("Step 5: Live Kraken connectivity test")
    print("-" * 65)
    if DRY_RUN:
        print("  [DRY-RUN] Would call Kraken Balance API to confirm nonce is accepted")
    else:
        conn_ok, conn_msg = _test_kraken_connectivity()
        if conn_ok:
            print(f"  ✅ {conn_msg}")
        else:
            print(f"  ❌ {conn_msg}")
            # Connectivity failures are informational at this stage — the bot
            # may not be running yet.  Do not increment errors so a failed live
            # test doesn't mask a successful nonce reset.
            print("     ℹ️  If the bot is not yet running, ignore this result.")
            print("        Restart the bot and check its logs.")
    print()

    # ── Summary ───────────────────────────────────────────────────────────────
    print("=" * 65)
    if DRY_RUN:
        print("  DRY-RUN complete — no changes were made.")
        print("  Re-run without --dry-run to apply the reset.")
    elif errors == 0:
        print("  ✅ Nonce reset complete.")
        print()
        print("  Next steps:")
        print("  1. Ensure KRAKEN_PLATFORM_API_KEY / KRAKEN_API_KEY and matching secret are correct in .env")
        print("  2. Confirm server clock is NTP-synced (timedatectl set-ntp true)")
        print("  3. Restart the NIJA bot (Railway: Deployments → Redeploy)")
        print("  4. Watch logs for 'Testing Kraken connection' — should succeed")
        print("  5. If nonce errors persist, wait 60 s and restart again")
    else:
        print(f"  ❌ Reset completed with {errors} error(s). Check output above.")
        print()
        print("  Common fixes:")
        print("  • Clock skew   → sudo ntpdate pool.ntp.org")
        print("  • Invalid key  → regenerate in Kraken → Security → API and update .env")
        print("  • Permissions  → ensure API key has 'Query Funds' + 'Create & Modify Orders'")
    print()

    return 0 if errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
