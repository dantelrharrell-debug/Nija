"""
NIJA Production Pre-Flight
==========================

Executes the five mandatory checks before the bot enters live mode:

  Step 1 — Redis PING confirmation
  Step 2 — Lock acquisition logging
  Step 3 — Single-instance enforcement
  Step 4 — Stale lock clearance
  Step 5 — Live-mode verification

Run directly::

    python -m bot.production_preflight

Or import and call from your entry-point::

    from bot.production_preflight import run_preflight
    run_preflight()           # raises SystemExit(1) on any hard failure

Exit codes
----------
0 — all checks passed, safe to start the bot in live mode
1 — hard failure; do NOT start the bot
"""

from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path

# ── logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
log = logging.getLogger("nija.preflight")


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

SEPARATOR = "=" * 72


def _step(n: int, title: str) -> None:
    log.info(SEPARATOR)
    log.info("STEP %d — %s", n, title)
    log.info(SEPARATOR)


def _ok(msg: str) -> None:
    log.info("✅  %s", msg)


def _fail(msg: str) -> None:
    log.critical("❌  %s", msg)


# ─────────────────────────────────────────────────────────────────────────────
# Step 1 — Redis PING
# ─────────────────────────────────────────────────────────────────────────────

def _step1_redis_ping() -> "redis.Redis":  # type: ignore[name-defined]
    """Connect to Redis and confirm PONG response.

    Returns the live Redis client for use in subsequent steps.
    Calls sys.exit(1) on failure.
    """
    _step(1, "Redis PING confirmation")

    try:
        from bot.redis_env import get_redis_url, get_redis_url_source
        from bot.redis_runtime import connect_redis_with_fallback
    except ImportError as exc:
        _fail(f"Cannot import Redis helpers: {exc}")
        sys.exit(1)

    url = get_redis_url()
    source = get_redis_url_source()

    if not url:
        _fail("No Redis URL configured.  Set NIJA_REDIS_URL (or REDIS_URL) and retry.")
        sys.exit(1)

    log.info("Redis URL source : %s", source)
    # Redact credentials for logging
    try:
        from urllib.parse import urlparse, urlunparse
        p = urlparse(url)
        safe = urlunparse(p._replace(netloc=f"****:****@{p.hostname}:{p.port}"))
        log.info("Redis URL        : %s", safe)
    except Exception:
        log.info("Redis URL        : <redacted>")

    # CRITICAL FIX: Implement aggressive retry loop with exponential backoff
    max_retries = 10
    base_delay = 1.0
    last_exc = None
    
    for attempt in range(max_retries):
        try:
            client, used_url = connect_redis_with_fallback(
                url=url,
                retries=3,
                delay_s=1.0,
                log=log.info,
            )
            
            # Test PING
            try:
                pong = client.ping()
                if pong:
                    _ok("✅ Redis responded PONG — connection healthy")
                    return client
                else:
                    raise RuntimeError("PING returned falsy response")
            except Exception as ping_exc:
                last_exc = ping_exc
                if attempt < max_retries - 1:
                    delay = min(base_delay * (2 ** attempt), 10.0)
                    log.warning(
                        "PING attempt %d/%d failed: %s. Retrying in %.1fs...",
                        attempt + 1, max_retries, ping_exc, delay
                    )
                    time.sleep(delay)
                else:
                    log.error("PING failed after %d attempts", max_retries)
                    raise
                    
        except Exception as exc:
            last_exc = exc
            if attempt < max_retries - 1:
                delay = min(base_delay * (2 ** attempt), 10.0)
                log.warning(
                    "Redis connection attempt %d/%d failed: %s. Retrying in %.1fs...",
                    attempt + 1, max_retries, exc, delay
                )
                time.sleep(delay)
            else:
                log.error("Redis connection failed after %d attempts", max_retries)
    
    # All retries exhausted
    _fail(f"❌ Redis connection failed after {max_retries} attempts: {last_exc}")
    sys.exit(1)


# ─────────────────────────────────────────────────────────────────────────────
# Step 2 — Confirm lock acquisition logging
# ─────────────────────────────────────────────────────────────────────────────

def _step2_lock_logging(redis_client: "redis.Redis") -> None:  # type: ignore[name-defined]
    """Verify the distributed writer-lock path is reachable and logs correctly."""
    _step(2, "Lock acquisition logging")

    lock_key = os.getenv("NIJA_WRITER_LOCK_KEY", "nija:writer_lock")
    ttl_ms   = int(os.getenv("NIJA_REDIS_LEASE_TTL_MS", "30000"))

    log.info("Writer-lock Redis key : %s", lock_key)
    log.info("Writer-lock TTL       : %d ms", ttl_ms)

    # Non-destructive probe: check whether the key already exists.
    try:
        existing_ttl = redis_client.pttl(lock_key)   # -2 = absent, -1 = no TTL, N = ms remaining
        if existing_ttl == -2:
            log.info("Lock key is absent — no active writer lease found")
        elif existing_ttl == -1:
            log.warning(
                "⚠️  Lock key '%s' exists with NO expiry — this may be a stale permanent lock.  "
                "Step 4 will clear it.",
                lock_key,
            )
        else:
            log.info("Lock key active, TTL remaining: %d ms", existing_ttl)
    except Exception as exc:
        _fail(f"Unable to probe lock key: {exc}")
        sys.exit(1)

    _ok("Lock acquisition logging path confirmed")


# ─────────────────────────────────────────────────────────────────────────────
# Step 3 — Single instance enforcement (file-based bootstrap guard)
# ─────────────────────────────────────────────────────────────────────────────

def _step3_single_instance() -> None:
    """Acquire the bootstrap guard to enforce single-instance operation."""
    _step(3, "Single-instance enforcement")

    try:
        from bot.bootstrap_guard import acquire_bootstrap_guard, is_guard_held
    except ImportError as exc:
        _fail(f"Cannot import bootstrap_guard: {exc}")
        sys.exit(1)

    if is_guard_held():
        log.info("Bootstrap guard already held by this process — idempotent OK")
    else:
        acquire_bootstrap_guard()       # calls sys.exit(1) if another process holds it

    _ok("Bootstrap guard acquired — this is the only running NIJA instance")


# ─────────────────────────────────────────────────────────────────────────────
# Step 4 — Clear stale locks
# ─────────────────────────────────────────────────────────────────────────────

def _step4_clear_stale_locks(redis_client: "redis.Redis") -> None:  # type: ignore[name-defined]
    """Remove Redis keys that have no TTL (permanent/stale) from the lock namespace."""
    _step(4, "Stale lock clearance")

    lock_key      = os.getenv("NIJA_WRITER_LOCK_KEY",  "nija:writer_lock")
    nonce_key     = os.getenv("NIJA_REDIS_NONCE_KEY",  "nija:kraken:nonce")
    lock_patterns = [lock_key, nonce_key]

    cleared = 0
    # CRITICAL FIX: Aggressively clear lock keys to prevent contention
    for key in lock_patterns:
        for attempt in range(3):
            try:
                ttl = redis_client.pttl(key)
                if ttl == -2:
                    log.info("Key '%s' absent — nothing to clear", key)
                    break
                if ttl == -1:
                    # Key exists but has no expiry — treat as stale
                    deleted = redis_client.delete(key)
                    if deleted:
                        log.warning("🗑️  Cleared stale (no-TTL) key: %s", key)
                        cleared += 1
                        break
                    else:
                        log.info("Key '%s' vanished before delete (race) — OK", key)
                        break
                else:
                    log.info("Key '%s' is active (TTL %d ms) — leaving untouched", key, ttl)
                    break
            except Exception as exc:
                if attempt < 2:
                    log.warning("Clear attempt %d failed for '%s': %s. Retrying...", attempt + 1, key, exc)
                    time.sleep(1)
                else:
                    log.warning("Could not inspect key '%s' after 3 attempts: %s", key, exc)

    # Additionally scan for any nija:* keys with no expiry using bounded scan
    stale_pattern = "nija:*"
    scanned = 0
    try:
        from bot.redis_runtime import safe_scan
        for k in safe_scan(redis_client, match=stale_pattern, max_iters=20):
            scanned += 1
            try:
                t = redis_client.pttl(k)
                if t == -1:
                    redis_client.delete(k)
                    log.warning("🗑️  Cleared stale no-TTL key discovered via scan: %s", k)
                    cleared += 1
            except Exception as scan_exc:
                log.debug("Could not clear scanned key '%s': %s", k, scan_exc)
    except Exception as exc:
        log.warning("Bounded scan for stale keys failed: %s", exc)

    log.info("Stale lock scan complete — scanned %d key(s), cleared %d", scanned, cleared)
    _ok("✅ Stale lock clearance complete (%d keys cleared)" % cleared)


# ─────────────────────────────────────────────────────────────────────────────
# Step 5 — Live-mode verification
# ─────────────────────────────────────────────────────────────────────────────

def _step5_live_mode_check() -> None:
    """Confirm that the environment is correctly configured for live trading."""
    _step(5, "Live-mode verification")

    dry_run   = os.getenv("DRY_RUN_MODE",         "false").strip().lower() in {"1", "true", "yes", "on"}
    paper     = os.getenv("PAPER_MODE",            "false").strip().lower() in {"1", "true", "yes", "on"}
    verified  = os.getenv("LIVE_CAPITAL_VERIFIED", "false").strip().lower() in {"1", "true", "yes", "on"}

    log.info("DRY_RUN_MODE         : %s", dry_run)
    log.info("PAPER_MODE           : %s", paper)
    log.info("LIVE_CAPITAL_VERIFIED: %s", verified)

    if dry_run:
        _fail(
            "DRY_RUN_MODE=true — bot will NOT execute real trades.  "
            "Set DRY_RUN_MODE=false to enable live mode."
        )
        sys.exit(1)

    if paper:
        _fail(
            "PAPER_MODE=true — bot will NOT execute real trades.  "
            "Set PAPER_MODE=false to enable live mode."
        )
        sys.exit(1)

    if not verified:
        _fail(
            "LIVE_CAPITAL_VERIFIED is not set.  "
            "Set LIVE_CAPITAL_VERIFIED=true to confirm live trading intent."
        )
        sys.exit(1)

    # Confirm required API credentials are present (values are not logged)
    missing = [
        name for name in ("COINBASE_API_KEY", "COINBASE_API_SECRET")
        if not os.getenv(name, "").strip()
    ]
    if missing:
        _fail(f"Missing Coinbase credentials: {', '.join(missing)}")
        sys.exit(1)

    _ok("Live mode confirmed — DRY_RUN_MODE=false, PAPER_MODE=false, LIVE_CAPITAL_VERIFIED=true")


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────────────

def run_preflight() -> None:
    """Execute all five pre-flight checks.  Exits with code 1 on any failure."""
    log.info(SEPARATOR)
    log.info("NIJA PRODUCTION PRE-FLIGHT")
    log.info(SEPARATOR)
    start = time.monotonic()

    redis_client = _step1_redis_ping()
    _step2_lock_logging(redis_client)
    _step3_single_instance()
    _step4_clear_stale_locks(redis_client)
    _step5_live_mode_check()

    elapsed = time.monotonic() - start
    log.info(SEPARATOR)
    log.info("✅  ALL PRE-FLIGHT CHECKS PASSED  (%.2f s)", elapsed)
    log.info("    Safe to start the bot in live mode.")
    log.info(SEPARATOR)


if __name__ == "__main__":
    run_preflight()
