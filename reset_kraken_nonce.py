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

# Buffer applied to the nonce on reset.  Must match GlobalKrakenNonceManager's
# _STARTUP_JUMP_NS (10 s) so the post-restart nonce lead stays well under the
# 60 s HARD RESET threshold.
_NONCE_BUFFER_NS = 10 * 1_000_000_000  # 10 seconds in nanoseconds
_NONCE_BUFFER_MS = _NONCE_BUFFER_NS // 1_000_000  # same buffer for legacy ms files

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
            new_nonce = time.time_ns() + 10 * 1_000_000_000  # preview only
            return True, f"[DRY-RUN] Would reset GlobalKrakenNonceManager to ~{new_nonce} (now + 10 s)", new_nonce

        # reset_to_safe_value() updates _last_nonce AND persists to disk atomically.
        new_nonce = manager.reset_to_safe_value()
        return True, f"GlobalKrakenNonceManager reset to {new_nonce} (now + 10 s, persisted to disk)", new_nonce

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
