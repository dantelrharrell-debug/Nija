#!/usr/bin/env python3
"""
reset_kraken_nonce.py — Force-sync NIJA's Kraken nonce to Kraken's server floor
================================================================================

Use this script whenever NIJA cannot connect to Kraken because of persistent
"EAPI:Invalid nonce" errors that survive normal restart attempts.

Root causes this fixes
──────────────────────
  1. Another process was running alongside NIJA and advanced Kraken's expected
     nonce server-side — the state file is now behind.
  2. The container filesystem was wiped (Railway / Heroku / Render) so the
     state file is gone; Kraken's floor is far ahead of wall-clock time.
  3. The adaptive-offset EMA in kraken_nonce_offsets.json became stale after
     multiple nuclear resets, causing the startup jump to undershoot.
  4. Data corruption — the persisted nonce is more than 24 h ahead of
     wall-clock time.

What this script does
─────────────────────
  1. Verifies the NTP clock offset (Kraken requires ±1 s accuracy).
  2. Checks whether another NIJA process appears to still be running.
  3. Deletes:
       • data/kraken_nonce.state          (force fresh-start in _load_last_nonce)
       • data/kraken_nonce.state.lock     (release any stale advisory lock)
       • data/kraken_nonce.state.tmp      (remove any partial write)
       • data/kraken_nonce_offsets.json   (reset adaptive EMA to conservative floor)
       • data/kraken_nonce*.txt           (legacy files from older NIJA versions)
  4. Prints the recommended restart command with the safe env vars.

Usage
─────
  # Stop NIJA first, then:
  python scripts/reset_kraken_nonce.py

  # Dry-run (show what would be deleted, don't actually delete):
  python scripts/reset_kraken_nonce.py --dry-run

  # Worst-case: known multiple prior nuclear resets (gaps > 30 min):
  python scripts/reset_kraken_nonce.py --deep

  # Skip the NTP check (e.g. ntplib not installed in this venv):
  python scripts/reset_kraken_nonce.py --skip-ntp

After running, start NIJA with:
  NIJA_FORCE_NONCE_RESYNC=1 python bot.py       # redundant but harmless
  # or just restart normally — the wiped files trigger fresh calibration.
"""

import argparse
import glob
import json
import os
import sys
import time

# ── Resolve data directory ────────────────────────────────────────────────────
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
_DATA_DIR = os.environ.get(
    "NIJA_DATA_DIR",
    os.path.join(_REPO_ROOT, "data"),
)

_STATE_FILE       = os.path.join(_DATA_DIR, "kraken_nonce.state")
_LOCK_FILE        = _STATE_FILE + ".lock"
_TMP_FILE         = _STATE_FILE + ".tmp"
_OFFSETS_FILE     = os.path.join(_DATA_DIR, "kraken_nonce_offsets.json")
_OFFSETS_TMP_FILE = _OFFSETS_FILE + ".tmp"

# Env vars for deep-resync mode
_DEEP_PROBE_STEP_MS    = 600_000   # 10 min per probe step
_DEEP_PROBE_ATTEMPTS   = 8         # 8 × 10 min = 80 min of forward coverage


def _check_ntp() -> bool:
    """Return True when system clock is within Kraken's ±1 s window."""
    try:
        import ntplib
        client = ntplib.NTPClient()
        resp = client.request("pool.ntp.org", version=3, timeout=3.0)
        offset_s = resp.offset
        ok = abs(offset_s) <= 1.0
        status = "✅ OK" if ok else "❌ DRIFT"
        print(f"  NTP clock: {status}  offset={offset_s:+.3f} s vs pool.ntp.org")
        if not ok:
            print(
                f"\n  ⚠️  Clock drift ({offset_s:+.3f} s) exceeds Kraken's ±1 s tolerance."
                "\n  Fix first:  sudo ntpdate pool.ntp.org"
                "\n              (or: sudo systemctl restart systemd-timesyncd)"
            )
        return ok
    except ImportError:
        print("  NTP check skipped (ntplib not installed — pip install ntplib==0.4.0)")
        return True   # unknown — don't block the reset
    except Exception as exc:
        print(f"  NTP check failed ({exc}) — skipping")
        return True


def _check_duplicate_process() -> bool:
    """Return True if another NIJA process appears to be running."""
    try:
        import fcntl
        with open(_LOCK_FILE, "w") as fh:
            try:
                fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(fh, fcntl.LOCK_UN)
                return False   # lock is free — no other process
            except (BlockingIOError, OSError):
                return True    # lock is held
    except Exception:
        return False


def _show_current_state() -> None:
    """Print the current persisted nonce and adaptive EMA for context."""
    now_ms = int(time.time() * 1000)

    # State file
    try:
        with open(_STATE_FILE, encoding="utf-8") as fh:
            nonce = int(fh.read().strip())
        lead_ms = nonce - now_ms
        lead_s  = lead_ms / 1000
        print(f"  Current nonce:  {nonce}  (lead={lead_s:+.1f} s vs wall-clock)")
    except FileNotFoundError:
        print("  Current nonce:  <no state file>")
    except Exception as exc:
        print(f"  Current nonce:  <unreadable — {exc}>")

    # Adaptive offsets file
    try:
        with open(_OFFSETS_FILE, encoding="utf-8") as fh:
            data = json.load(fh)
        ema = data.get("ema_gap_ms", 0)
        obs = len(data.get("history", []))
        print(f"  Adaptive EMA:   {ema:.0f} ms ({ema/60000:.1f} min),  {obs} observations")
    except FileNotFoundError:
        print("  Adaptive EMA:   <no offsets file>")
    except Exception as exc:
        print(f"  Adaptive EMA:   <unreadable — {exc}>")


def _delete_files(dry_run: bool) -> None:
    """Delete nonce state and adaptive-offset files."""
    targets = [
        _STATE_FILE,
        _LOCK_FILE,
        _TMP_FILE,
        _OFFSETS_FILE,
        _OFFSETS_TMP_FILE,
    ]
    # Also remove any legacy nonce .txt files
    targets += glob.glob(os.path.join(_DATA_DIR, "kraken_nonce*.txt"))

    removed = []
    skipped = []
    for path in targets:
        if not os.path.exists(path):
            continue
        if dry_run:
            skipped.append(path)
        else:
            try:
                os.remove(path)
                removed.append(path)
            except Exception as exc:
                print(f"  ⚠️  Could not remove {path}: {exc}")

    if removed:
        print("\n  Deleted:")
        for p in removed:
            print(f"    {p}")
    if skipped:
        print("\n  Would delete (dry-run):")
        for p in skipped:
            print(f"    {p}")
    if not removed and not skipped:
        print("\n  Nothing to delete (files already absent).")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Force-reset NIJA Kraken nonce state for a guaranteed clean sync.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would be deleted without making any changes.",
    )
    parser.add_argument(
        "--deep", action="store_true",
        help=(
            "Print restart command with larger probe step (10 min × 8 = 80 min "
            "coverage) — use when multiple nuclear resets have occurred."
        ),
    )
    parser.add_argument(
        "--skip-ntp", action="store_true",
        help="Skip the NTP clock-drift check.",
    )
    args = parser.parse_args()

    print("=" * 70)
    print("  NIJA Kraken Nonce Force-Sync")
    print("=" * 70)

    # ── 1. NTP check ──────────────────────────────────────────────────────
    if not args.skip_ntp:
        print("\n[1/4] NTP clock check:")
        _check_ntp()
    else:
        print("\n[1/4] NTP clock check: skipped (--skip-ntp)")

    # ── 2. Duplicate process check ────────────────────────────────────────
    print("\n[2/4] Duplicate process check:")
    if _check_duplicate_process():
        print(
            "  ⚠️  Another NIJA process appears to be holding the nonce lock!\n"
            "  Stop all NIJA processes before running this script, otherwise\n"
            "  the running process will overwrite the files you delete."
        )
        if not args.dry_run:
            ans = input("  Continue anyway? [y/N] ").strip().lower()
            if ans != "y":
                print("  Aborted.")
                return 1
    else:
        print("  ✅ No other NIJA process detected.")

    # ── 3. Show current state ─────────────────────────────────────────────
    print("\n[3/4] Current nonce state:")
    _show_current_state()

    # ── 4. Delete files ───────────────────────────────────────────────────
    action = "Would delete" if args.dry_run else "Deleting"
    print(f"\n[4/4] {action} nonce state files:")
    _delete_files(dry_run=args.dry_run)

    # ── Done ──────────────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    if args.dry_run:
        print("  Dry-run complete — no files were modified.")
        print("  Run without --dry-run to apply the changes.")
    else:
        print("  ✅ Nonce state wiped.")
        print()
        if args.deep:
            print(
                "  Restart NIJA with the deep-resync env vars (80 min coverage):\n"
                f"\n    NIJA_FORCE_NONCE_RESYNC=1 \\\n"
                f"    NIJA_NONCE_PROBE_STEP_MS={_DEEP_PROBE_STEP_MS} \\\n"
                f"    NIJA_NONCE_PROBE_MAX_ATTEMPTS={_DEEP_PROBE_ATTEMPTS} \\\n"
                "    python bot.py\n"
                "\n  On Railway: add the three env vars above in the service settings,\n"
                "  then redeploy."
            )
        else:
            print(
                "  Restart NIJA normally — the wiped files trigger fresh probe\n"
                "  calibration automatically on the next connect().\n"
                "\n  Optional: set NIJA_FORCE_NONCE_RESYNC=1 for an extra safety\n"
                "  wipe at startup (harmless when the files are already absent).\n"
                "\n  For worst-case gaps (multiple prior nuclear resets) rerun with --deep."
            )
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
