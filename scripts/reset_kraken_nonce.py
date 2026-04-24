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
_NTP_SERVER = os.environ.get("NIJA_NTP_SERVER", "pool.ntp.org")

_STATE_FILE       = os.path.join(_DATA_DIR, "kraken_nonce.state")
_LOCK_FILE        = _STATE_FILE + ".lock"
# Process-lifetime lock: held open for the entire bot session by
# KrakenNonceManager._try_acquire_pid_lock().  Checking this file is more
# reliable than checking _LOCK_FILE (which is only held briefly during each
# nonce increment) — if the bot is running but not currently issuing a nonce,
# _LOCK_FILE would appear free even though the bot is alive.
_PID_LOCK_FILE    = _STATE_FILE + ".pid"
_TMP_FILE         = _STATE_FILE + ".tmp"
_OFFSETS_FILE     = os.path.join(_DATA_DIR, "kraken_nonce_offsets.json")
_OFFSETS_TMP_FILE = _OFFSETS_FILE + ".tmp"

# Env vars for deep-resync mode
_DEEP_PROBE_STEP_MS    = 600_000   # 10 min per probe step
_DEEP_PROBE_ATTEMPTS   = 12        # 12 × 10 min = 120 min of forward coverage
# Startup floor written to state file in --deep mode so the bot starts well
# above Kraken's high-water mark without relying solely on probe calibration.
_DEEP_FLOOR_AHEAD_MS   = 3_600_000  # 60 min ahead of wall-clock


def _check_ntp() -> bool:
    """Return True when system clock is within Kraken's ±1 s window."""
    try:
        import ntplib
        client = ntplib.NTPClient()
        resp = client.request(_NTP_SERVER, version=3, timeout=3.0)
        offset_s = resp.offset
        ok = abs(offset_s) <= 1.0
        status = "✅ OK" if ok else "❌ DRIFT"
        print(f"  NTP clock: {status}  offset={offset_s:+.3f} s vs {_NTP_SERVER}")
        if not ok:
            print(
                f"\n  ⚠️  Clock drift ({offset_s:+.3f} s) exceeds Kraken's ±1 s tolerance."
                f"\n  Fix first:  sudo ntpdate {_NTP_SERVER}"
                "\n              (or: sudo systemctl restart systemd-timesyncd)"
            )
        return ok
    except ImportError:
        print("  NTP check skipped (ntplib not installed — pip install ntplib)")
        return True   # unknown — don't block the reset
    except Exception as exc:
        print(f"  NTP check failed ({exc}) — skipping")
        return True


def _get_ntp_backward_drift_ms() -> int:
    """
    Return the backward-drift correction in milliseconds.

    When the host clock is *behind* NTP (system time < true UTC), any nonce
    floor computed from ``time.time()`` will be lower than what Kraken expects.
    Adding this correction ensures the written floor is safe even on a drifted
    clock.  Returns 0 when the clock is ahead, NTP is unavailable, or the
    measured lag is negligible (< 100 ms).
    """
    try:
        import ntplib
        client = ntplib.NTPClient()
        resp = client.request(_NTP_SERVER, version=3, timeout=3.0)
        if resp.offset >= 0.0:
            return 0   # clock is ahead of NTP — no under-count risk
        lag_ms = int(abs(resp.offset) * 1000)
        return lag_ms if lag_ms >= 100 else 0
    except Exception:
        return 0


def _check_duplicate_process() -> bool:
    """Return True if another NIJA process appears to be running.

    Checks ``_PID_LOCK_FILE`` (the process-lifetime lock held for the ENTIRE
    bot session) rather than ``_LOCK_FILE`` (only held briefly per nonce op).
    This gives a reliable answer even when the bot is idle between API calls.
    Falls back to checking ``_LOCK_FILE`` on platforms without fcntl.
    """
    try:
        import fcntl
        # Check the process-lifetime PID lock first — most reliable.
        for lock_path in (_PID_LOCK_FILE, _LOCK_FILE):
            try:
                # Append mode: never truncate a file the bot may have open.
                with open(lock_path, "a") as fh:
                    try:
                        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        fcntl.flock(fh, fcntl.LOCK_UN)
                        # This lock is free — try the next one.
                    except (BlockingIOError, OSError):
                        return True    # lock is held → bot is running
            except FileNotFoundError:
                pass   # file does not exist → definitely not locked
        return False   # neither lock is held
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


def _write_deep_floor(dry_run: bool) -> None:
    """
    Write a deep-floor nonce (now + 60 min + NTP backward-drift) to the state
    file so the bot starts well above Kraken's high-water mark on the next
    restart without relying solely on probe_and_resync() to find the floor.

    The NTP backward-drift correction is added so that hosts with a clock that
    is *behind* true UTC still produce a floor that is at or above Kraken's
    expected value.
    """
    ntp_corr_ms = _get_ntp_backward_drift_ms()
    floor_ms = int(time.time() * 1000) + _DEEP_FLOOR_AHEAD_MS + ntp_corr_ms
    lead_s = (_DEEP_FLOOR_AHEAD_MS + ntp_corr_ms) / 1000

    if dry_run:
        print(
            f"  [DRY RUN] Would write deep floor: nonce≈{floor_ms} "
            f"(lead=+{lead_s:.0f} s, NTP correction=+{ntp_corr_ms} ms)"
        )
        return

    try:
        os.makedirs(_DATA_DIR, exist_ok=True)
        tmp = _STATE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(str(floor_ms))
        os.replace(tmp, _STATE_FILE)
        print(
            f"  ✅ Deep floor written: nonce={floor_ms} "
            f"(lead=+{lead_s:.0f} s, NTP correction=+{ntp_corr_ms} ms)"
        )
    except Exception as exc:
        print(f"  ⚠️  Could not write deep floor: {exc}")


def _delete_files(dry_run: bool) -> None:
    """Delete nonce state and adaptive-offset files."""
    targets = [
        _STATE_FILE,
        _LOCK_FILE,
        _PID_LOCK_FILE,   # process-lifetime lock from the stopped bot
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
            "Deep reset: write a 60-min NTP-corrected startup floor to the state "
            "file and print restart command with 10 min × 12 = 120 min probe "
            "coverage.  Use when multiple nuclear resets have occurred or the "
            "probe calibration failed with the standard settings."
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
    total_steps = 5 if args.deep else 4
    if not args.skip_ntp:
        print(f"\n[1/{total_steps}] NTP clock check:")
        _check_ntp()
    else:
        print(f"\n[1/{total_steps}] NTP clock check: skipped (--skip-ntp)")

    # ── 2. Duplicate process check ────────────────────────────────────────
    print(f"\n[2/{total_steps}] Duplicate process check:")
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
    print(f"\n[3/{total_steps}] Current nonce state:")
    _show_current_state()

    # ── 4. Delete files ───────────────────────────────────────────────────
    action = "Would delete" if args.dry_run else "Deleting"
    print(f"\n[4/{total_steps}] {action} nonce state files:")
    _delete_files(dry_run=args.dry_run)

    # ── 5. Deep floor (--deep only) ───────────────────────────────────────
    # Write a 60-min NTP-corrected nonce to the state file so the bot starts
    # far above Kraken's high-water mark without needing many probe rounds.
    if args.deep:
        print(f"\n[5/{total_steps}] Writing NTP-corrected deep startup floor:")
        _write_deep_floor(dry_run=args.dry_run)

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
                "  Restart NIJA with the deep-resync env vars (120 min coverage):\n"
                f"\n    NIJA_DEEP_NONCE_RESET=1 \\\n"
                f"    NIJA_FORCE_NONCE_RESYNC=1 \\\n"
                "    python bot.py\n"
                "\n  On Railway: add the two env vars above in the service settings,\n"
                "  then redeploy.  They will be ignored on subsequent restarts once\n"
                "  the state file is healthy.\n"
                "\n  Advanced override (if 120 min is still insufficient):\n"
                f"    NIJA_NONCE_DEEP_STEP_MS={_DEEP_PROBE_STEP_MS} \\\n"
                f"    NIJA_NONCE_DEEP_MAX_ATTEMPTS={_DEEP_PROBE_ATTEMPTS} \\\n"
                "    python bot.py"
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
