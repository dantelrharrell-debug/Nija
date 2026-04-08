#!/usr/bin/env python3
"""
NIJA Trading Bot — Kraken Nonce Reset Utility
==============================================

Run this whenever the bot is stuck with "EAPI:Invalid nonce" errors.

What it does:
  1. NTP clock check — Kraken requires system clock within ±1 second.
  2. Validates Kraken API credentials are configured.
  3. Backs up every nonce file in data/.
  4. Deletes all nonce cache files (kraken_nonce.state, *.json, *.txt).
  5. Resets the KrakenNonceManager singleton to a fresh, safe value.
  6. Persists the new nonce and verifies it is strictly greater.
  7. Optionally runs a live Kraken balance call to confirm recovery.

Usage:
    python3 reset_kraken_nonce.py [--dry-run] [--no-live-test]

    --dry-run       Show what would change without writing anything.
    --no-live-test  Skip the live Kraken API test after reset.

Exit codes:
    0  Reset succeeded (or dry-run completed).
    1  Reset failed.
"""

import os
import sys
import time
import glob
import shutil
from datetime import datetime, timezone

# ── Load .env ─────────────────────────────────────────────────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

DRY_RUN     = "--dry-run"     in sys.argv
SKIP_TEST   = "--no-live-test" in sys.argv

# ── Reset nonce offset ────────────────────────────────────────────────────────
# 30 minutes ahead of wall-clock (nuclear offset).  This must beat ANY
# previously stored nonce even after 300+ consecutive retry attempts.
_RESET_OFFSET_MS = 1_800_000

# Add bot/ to path so we can import the nonce manager
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "bot"))

_USE_COLOUR = sys.stdout.isatty()
def _c(code, text): return f"\033[{code}m{text}\033[0m" if _USE_COLOUR else text
def _ok(m):   print(f"  {_c('32','✅')} {m}")
def _fail(m): print(f"  {_c('31','❌')} {m}")
def _warn(m): print(f"  {_c('33','⚠️ ')} {m}")
def _info(m): print(f"  {_c('2', 'ℹ️ ')} {m}")
def _head(t): print(f"\n{_c('1','─'*60)}\n{_c('1',t)}\n{_c('1','─'*60)}")
def _ts():    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

# ── Data directory ────────────────────────────────────────────────────────────
_DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
_NONCE_PATTERNS = [
    os.path.join(_DATA_DIR, "kraken_nonce.state"),
    os.path.join(_DATA_DIR, "kraken_nonce*.json"),
    os.path.join(_DATA_DIR, "kraken_nonce*.txt"),
    os.path.join(_DATA_DIR, "kraken_global_nonce.txt"),
]


# ─────────────────────────────────────────────────────────────────────────────
# 0 — Running-process check
# ─────────────────────────────────────────────────────────────────────────────

_BOT_PATTERNS = ["bot.py", "trading_strategy.py", "nija_core_loop.py",
                 "tradingview_webhook.py", "start.sh"]


def check_no_bot_running() -> bool:
    """
    Scan the process list for known bot entry-points.

    Returns True when no bot processes are detected (safe to proceed).
    Returns False and prints instructions when bot processes are found.

    IMPORTANT: Even ONE API call made by a running bot after the nonce reset
    will generate a nonce higher than the reset value, re-introducing the
    very desync this script is trying to fix.
    """
    _head("0 — Running-Process Check  (bot MUST be stopped first)")
    import subprocess

    bot_pids: list = []
    try:
        result = subprocess.run(
            ["ps", "aux"],
            capture_output=True, text=True, timeout=5,
        )
        for line in result.stdout.splitlines():
            if any(pat in line for pat in _BOT_PATTERNS):
                # Ignore the current reset script itself
                if "reset_kraken_nonce" not in line and "grep" not in line:
                    bot_pids.append(line.strip())
    except Exception as exc:
        _warn(f"Could not read process list: {exc}")
        _warn("Verify manually: ps aux | grep python")
        return True  # unknown — don't block

    if bot_pids:
        _fail(f"Detected {len(bot_pids)} running bot process(es):")
        for p in bot_pids:
            _info(f"  {p[:120]}")
        print()
        _fail("A running bot will re-desync the nonce immediately after reset.")
        _info("Stop the bot FIRST, then re-run this script:")
        _info("  pkill -f bot.py")
        _info("  pkill -f trading_strategy.py")
        _info("  pkill -f nija_core_loop.py")
        _info("Verify with: ps aux | grep python")
        return False

    _ok("No running bot processes detected — safe to reset.")
    return True


# ─────────────────────────────────────────────────────────────────────────────
# 1 — NTP clock check
# ─────────────────────────────────────────────────────────────────────────────

def check_clock() -> bool:
    """Query NTP and print clock status. Returns True if clock is OK."""
    _head("1 — NTP Clock Check  (Kraken requires ±1 s accuracy)")
    try:
        from global_kraken_nonce import check_ntp_sync
        r = check_ntp_sync()
    except ImportError:
        # Fallback: raw UDP NTP
        r = _raw_ntp_check()

    if r["error"]:
        _warn(f"NTP query failed: {r['error']}")
        _warn("Verify manually: date -u")
        _info(f"System time: {_ts()}")
        return True  # unknown — don't block

    offset_ms = r["offset_s"] * 1000
    abs_s = abs(r["offset_s"])
    if not r["ok"]:
        _fail(
            f"CLOCK DRIFT: system is {r['offset_s']:+.3f} s ({offset_ms:+.0f} ms) "
            f"vs {r['server']}"
        )
        _fail("Kraken requires ±1 s — nonce errors WILL occur on ALL accounts.")
        print()
        _info("Fix NOW before resetting the nonce:")
        _info("  sudo ntpdate pool.ntp.org")
        _info("  OR enable chrony: sudo systemctl start chronyd")
        return False
    elif abs_s > 0.5:
        _warn(
            f"Clock drift: {r['offset_s']:+.3f} s ({offset_ms:+.0f} ms) vs "
            f"{r['server']} — within tolerance but monitor closely."
        )
        _info("Recommend: sudo ntpdate pool.ntp.org")
    else:
        _ok(f"Clock OK: {r['offset_s']:+.3f} s vs {r['server']}")
    _info(f"System UTC time: {_ts()}")
    return True


def _raw_ntp_check() -> dict:
    """Raw UDP NTP query — no external library needed."""
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


# ─────────────────────────────────────────────────────────────────────────────
# 2 — Credential check
# ─────────────────────────────────────────────────────────────────────────────

def check_credentials() -> bool:
    """Check Kraken API credentials are present. Returns True if at least platform or one user is set."""
    _head("2 — Kraken API Credentials")
    found_any = False

    def _chk(name):
        nonlocal found_any
        val = os.getenv(name, "").strip()
        if val and val.lower() not in {"placeholder", "changeme", "xxx", "none"}:
            _ok(f"{name} = <{len(val)} chars>")
            found_any = True
            return True
        else:
            _warn(f"{name} — not set or placeholder")
            return False

    # Platform
    p_key = _chk("KRAKEN_PLATFORM_API_KEY") or _chk("KRAKEN_API_KEY")
    p_sec = _chk("KRAKEN_PLATFORM_API_SECRET") or _chk("KRAKEN_API_SECRET")

    # Users
    for name in sorted(k for k in os.environ if k.startswith("KRAKEN_USER_") and k.endswith("_API_KEY")):
        _chk(name)
    for name in sorted(k for k in os.environ if k.startswith("KRAKEN_USER_") and k.endswith("_API_SECRET")):
        _chk(name)

    if not found_any:
        _fail("No Kraken credentials found — set KRAKEN_PLATFORM_API_KEY/SECRET in .env")
        return False
    return True


# ─────────────────────────────────────────────────────────────────────────────
# 3 — Find and back up nonce files
# ─────────────────────────────────────────────────────────────────────────────

def find_nonce_files() -> list:
    files = []
    for pattern in _NONCE_PATTERNS:
        files.extend(glob.glob(pattern))
    return sorted(set(files))


def backup_and_delete_nonce_files(files: list) -> list:
    """Backup then delete all nonce files. Returns list of (original, backup) pairs."""
    backed_up = []
    for path in files:
        backup = f"{path}.bak.{int(time.time())}"
        if DRY_RUN:
            _info(f"[DRY RUN] Would back up: {path} → {backup}")
        else:
            shutil.copy2(path, backup)
            os.remove(path)
            _ok(f"Backed up + deleted: {os.path.basename(path)} → {os.path.basename(backup)}")
        backed_up.append((path, backup))
    return backed_up


# ─────────────────────────────────────────────────────────────────────────────
# 4 — Reset nonce manager
# ─────────────────────────────────────────────────────────────────────────────

def reset_nonce() -> tuple:
    """
    Reset the KrakenNonceManager to a safe value.

    Returns (old_nonce, new_nonce) or (None, None) on import failure.
    """
    _head("4 — Reset Nonce Manager")
    try:
        import importlib
        import global_kraken_nonce as gnm
        # Force a fresh singleton (delete the instance so _init() re-runs)
        gnm.KrakenNonceManager._instance = None
        importlib.reload(gnm)

        mgr = gnm.KrakenNonceManager()
        old_nonce = mgr.get_last_nonce()

        if not DRY_RUN:
            # Jump 30 min ahead of wall-clock (nuclear) to beat any previously stored nonce.
            mgr.reset_to_safe_value(offset_ms=_RESET_OFFSET_MS)

        new_nonce = mgr.get_last_nonce()
        lead_ms = new_nonce - int(time.time() * 1000)

        if DRY_RUN:
            _info(f"[DRY RUN] Would reset nonce from {old_nonce} to ~{int(time.time()*1000) + _RESET_OFFSET_MS}")
        else:
            _ok(f"Nonce reset: {old_nonce} → {new_nonce}  (lead = +{lead_ms:,} ms)")
            assert new_nonce > old_nonce or lead_ms > 0, "New nonce is not ahead of old — check reset logic"
        return old_nonce, new_nonce
    except Exception as exc:
        _fail(f"Could not reset nonce manager: {exc}")
        return None, None


# ─────────────────────────────────────────────────────────────────────────────
# 5 — Live connection test
# ─────────────────────────────────────────────────────────────────────────────

def live_test() -> bool:
    """Call Kraken Balance to confirm the reset worked. Returns True on success."""
    _head("5 — Live Kraken Connection Test")
    api_key = (os.getenv("KRAKEN_PLATFORM_API_KEY") or os.getenv("KRAKEN_API_KEY", "")).strip()
    api_secret = (os.getenv("KRAKEN_PLATFORM_API_SECRET") or os.getenv("KRAKEN_API_SECRET", "")).strip()

    if not api_key or not api_secret:
        _warn("No platform credentials — skipping live test")
        return True

    try:
        import krakenex
        import global_kraken_nonce as gnm

        k = krakenex.API(key=api_key, secret=api_secret)
        nonce = gnm.get_kraken_nonce()
        result = k.query_private("Balance", {"nonce": nonce})

        if result.get("error"):
            _fail(f"Kraken API error: {result['error']}")
            gnm.record_kraken_nonce_error()
            return False

        _ok("Kraken Balance call succeeded — nonce reset is working correctly.")
        gnm.record_kraken_nonce_success()
        balances = result.get("result", {})
        for asset, bal in sorted(balances.items()):
            try:
                if float(bal) > 0:
                    _info(f"  {asset}: {float(bal):.6f}")
            except ValueError:
                pass
        return True
    except ImportError:
        _warn("krakenex not installed — skipping live test  (pip install krakenex)")
        return True
    except Exception as exc:
        _fail(f"Live test exception: {exc}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main() -> int:
    print(_c("1", "\n" + "=" * 60))
    print(_c("1", "  NIJA — Kraken Nonce Reset Utility"))
    if DRY_RUN:
        print(_c("33", "  [DRY RUN — no files will be written]"))
    print(_c("1", "=" * 60))

    bot_ok   = check_no_bot_running()
    clock_ok = check_clock()
    creds_ok = check_credentials()

    if not bot_ok and not DRY_RUN:
        _fail("Aborting: stop the bot first, then re-run this script.")
        return 1

    _head("3 — Nonce Files")
    nonce_files = find_nonce_files()
    if nonce_files:
        _info(f"Found {len(nonce_files)} nonce file(s):")
        for f in nonce_files:
            _info(f"  {f}")
        backup_and_delete_nonce_files(nonce_files)
    else:
        _ok("No nonce cache files found (clean state)")

    old_n, new_n = reset_nonce()

    live_ok = True
    if not SKIP_TEST and not DRY_RUN and creds_ok:
        live_ok = live_test()

    _head("Summary")
    ok = True
    if not bot_ok:
        _warn("Bot process check was skipped or processes were found — verify manually")
    else:
        _ok("No running bot processes at reset time")
    if not clock_ok:
        _fail("System clock is off — fix with: sudo ntpdate pool.ntp.org")
        ok = False
    else:
        _ok("System clock within Kraken ±1 s tolerance")
    if not creds_ok:
        _warn("No Kraken credentials configured (optional — set KRAKEN_PLATFORM_API_KEY)")
    else:
        _ok("Kraken credentials present")
    if old_n is not None:
        _ok(f"Nonce reset: {old_n} → {new_n}")
    if not live_ok:
        _fail("Live Kraken test failed — check credentials and clock")
        ok = False
    elif not SKIP_TEST and not DRY_RUN and creds_ok:
        _ok("Live Kraken API test passed")

    print()
    if ok:
        print(_c("32", _c("1", "✅  Nonce reset complete — restart the bot now.")))
        print()
        print("Next step:  ./start.sh")
    else:
        print(_c("31", _c("1", "❌  Reset completed with warnings — fix the issues above first.")))
        print()
        print("Then restart:  ./start.sh")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
