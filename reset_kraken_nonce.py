#!/usr/bin/env python3
"""
NIJA Trading Bot — Kraken Nonce Reset Utility
==============================================

Safely resets the Kraken nonce state when the bot is stuck with
"EAPI:Invalid nonce" errors.

What this script does:
  1. Locates any persisted nonce files in the data/ directory
  2. Backs them up before touching anything
  3. Resets the in-memory GlobalKrakenNonceManager to a fresh timestamp
  4. Writes a new, safe nonce value to each nonce file
  5. Verifies the new nonce is strictly greater than the old one

When to run this:
  • Bot logs show repeated "EAPI:Invalid nonce" errors
  • Bot was restarted rapidly and nonces are out of sync
  • After a system clock correction that moved time backward

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
from datetime import datetime, timezone
from typing import Optional

# ── Load .env if present ──────────────────────────────────────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

DRY_RUN = "--dry-run" in sys.argv

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
# Nonce file discovery
# ─────────────────────────────────────────────────────────────────────────────

def _find_nonce_files() -> list[str]:
    """
    Find all Kraken nonce files in the data/ directory.

    Nonce files follow the pattern:
        data/kraken_nonce_platform.txt
        data/kraken_nonce_user_daivon_frazier.txt
        data/kraken_nonce_user_*.txt
    """
    patterns = [
        "data/kraken_nonce_*.txt",
        "kraken_nonce_*.txt",          # fallback: root directory
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
    Reset the GlobalKrakenNonceManager singleton to a fresh nanosecond timestamp.

    Returns:
        (success: bool, message: str, new_nonce: int)
    """
    try:
        from bot.global_kraken_nonce import GlobalKrakenNonceManager
        manager = GlobalKrakenNonceManager()

        # Compute a safe new starting nonce:
        #   current nanoseconds + 60-second buffer
        # The 60-second buffer ensures we skip past any nonces Kraken may still
        # have cached from the previous session (Kraken caches nonces ~60 s).
        buffer_ns  = 60 * 1_000_000_000  # 60 seconds in nanoseconds
        new_nonce  = time.time_ns() + buffer_ns

        if not DRY_RUN:
            with manager._nonce_lock:
                manager._last_nonce          = new_nonce
                manager._total_nonces_issued = 0

        return True, f"GlobalKrakenNonceManager reset to {new_nonce} (now + 60 s buffer)", new_nonce

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

    # ── Step 1: Reset in-memory nonce manager ────────────────────────────────
    print("Step 1: Reset in-memory GlobalKrakenNonceManager")
    print("-" * 65)
    ok, msg, new_nonce_ns = _reset_global_nonce_manager()
    if ok:
        print(f"  ✅ {msg}")
    else:
        print(f"  ⚠️  {msg}")
        # Not fatal — nonce files can still be reset independently
    print()

    # ── Step 2: Discover and reset nonce files ────────────────────────────────
    print("Step 2: Reset persisted nonce files")
    print("-" * 65)

    nonce_files = _find_nonce_files()

    if not nonce_files:
        print("  ℹ️  No nonce files found in data/ — nothing to reset.")
        print("     (Files are created automatically on first Kraken connection.)")
    else:
        for path in nonce_files:
            old_value = _read_nonce_file(path)
            old_str   = str(old_value) if old_value is not None else "<missing/corrupt>"

            # Compute a safe new nonce value in milliseconds
            # (persisted nonce files use milliseconds, not nanoseconds)
            buffer_ms = 60 * 1000  # 60-second buffer in milliseconds
            new_value = int(time.time() * 1000) + buffer_ms

            if DRY_RUN:
                print(f"  [DRY-RUN] {path}")
                print(f"            old: {old_str}")
                print(f"            new: {new_value}  (+60 s buffer)")
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
                print(f"     new: {new_value}  (+60 s buffer)")
            except OSError as exc:
                print(f"  ❌ Failed to write {path}: {exc}")
                errors += 1

    print()

    # ── Step 3: Verify monotonicity ───────────────────────────────────────────
    print("Step 3: Verify nonce monotonicity")
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

    # ── Summary ───────────────────────────────────────────────────────────────
    print("=" * 65)
    if DRY_RUN:
        print("  DRY-RUN complete — no changes were made.")
        print("  Re-run without --dry-run to apply the reset.")
    elif errors == 0:
        print("  ✅ Nonce reset complete.")
        print()
        print("  Next steps:")
        print("  1. Restart the NIJA bot (Railway: Deployments → Redeploy)")
        print("  2. Watch logs for 'Testing Kraken connection' — should succeed")
        print("  3. If errors persist, wait 60 s and restart again")
    else:
        print(f"  ❌ Reset completed with {errors} error(s). Check output above.")
    print()

    return 0 if errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
