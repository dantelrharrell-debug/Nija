#!/usr/bin/env python3
"""
🔥 CRITICAL: Clear stale Redis locks and verify connectivity

Usage:
    python scripts/clear_redis_locks.py        # Check lock status
    python scripts/clear_redis_locks.py --clear # Delete stale locks

This is the immediate fix for Redis lock contention issues.
"""

import os
import sys
import logging
import argparse
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
log = logging.getLogger("redis-lock-clear")


def main():
    parser = argparse.ArgumentParser(
        description="Clear stale Redis locks and verify connectivity"
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Delete stale locks (otherwise just check status)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force delete all nija:* locks (⚠️ dangerous)",
    )
    args = parser.parse_args()

    try:
        from bot.redis_env import get_redis_url, get_redis_url_source
        from bot.redis_runtime import connect_redis_with_fallback
    except ImportError as exc:
        log.error("❌ Cannot import Redis helpers: %s", exc)
        sys.exit(1)

    # Get Redis URL
    url = get_redis_url()
    source = get_redis_url_source()

    if not url:
        log.error("❌ No Redis URL configured. Set NIJA_REDIS_URL (or REDIS_URL)")
        sys.exit(1)

    log.info("📍 Redis URL source: %s", source)
    try:
        from urllib.parse import urlparse
        p = urlparse(url)
        safe_url = f"{p.scheme}://****:****@{p.hostname}:{p.port}"
        log.info("🔗 Redis URL: %s", safe_url)
    except Exception:
        log.info("🔗 Redis URL: <redacted>")

    # Connect to Redis
    log.info("🔄 Connecting to Redis...")
    try:
        client, used_url = connect_redis_with_fallback(
            url=url,
            retries=5,
            delay_s=1.0,
            log=log.info,
        )
        log.info("✅ Connected successfully")
    except Exception as exc:
        log.error("❌ Redis connection failed: %s", exc)
        sys.exit(1)

    # Test PING
    try:
        pong = client.ping()
        log.info("✅ Redis PING successful")
    except Exception as exc:
        log.error("❌ Redis PING failed: %s", exc)
        sys.exit(1)

    # Get lock configuration
    lock_key = os.getenv("NIJA_WRITER_LOCK_KEY", "nija:writer_lock")
    meta_key = os.getenv("NIJA_WRITER_LOCK_META_KEY", "nija:writer_lock_meta")
    nonce_key = os.getenv("NIJA_REDIS_NONCE_KEY", "nija:kraken:nonce")
    fence_key = os.getenv("NIJA_WRITER_FENCING_KEY", "nija:writer_fence")

    log.info("\n📋 Lock Configuration:")
    log.info("   Lock key: %s", lock_key)
    log.info("   Meta key: %s", meta_key)
    log.info("   Nonce key: %s", nonce_key)
    log.info("   Fence key: %s", fence_key)

    # Check lock status
    log.info("\n🔍 Scanning Redis for nija:* keys...")
    try:
        from bot.redis_runtime import safe_scan
        all_keys = list(safe_scan(client, match="nija:*", max_iters=50))
        log.info("Found %d nija:* keys", len(all_keys))

        stale_keys = []
        active_keys = []

        for key in all_keys:
            try:
                ttl = client.pttl(key)
                holder_display = ""
                try:
                    val = client.get(key)
                    if val:
                        # Truncate value for display
                        holder_display = f" (holder: {str(val)[:50]}...)"
                except Exception:
                    pass

                if ttl == -2:
                    log.info("   ○ %s - absent", key)
                elif ttl == -1:
                    log.warning("   ⚠️  %s - NO TTL (STALE)%s", key, holder_display)
                    stale_keys.append(key)
                else:
                    log.info("   ✓ %s - active (TTL %dms)", key, ttl)
                    active_keys.append((key, ttl))
            except Exception as exc:
                log.error("   ✗ %s - error reading: %s", key, exc)

        log.info("\n📊 Summary:")
        log.info("   Active keys: %d", len(active_keys))
        log.info("   Stale keys: %d", len(stale_keys))

        if stale_keys:
            log.warning("\n🔓 Stale keys requiring cleanup:")
            for key in stale_keys:
                log.warning("      - %s", key)

        if not args.clear and not args.force:
            log.info("\n💡 To delete stale locks: python scripts/clear_redis_locks.py --clear")
            log.info("   Or force-delete all nija:* locks: python scripts/clear_redis_locks.py --force")
            sys.exit(0)

        # Clear locks if requested
        if args.clear or args.force:
            cleared = 0
            if args.clear and stale_keys:
                log.info("\n🗑️  Deleting %d stale keys...", len(stale_keys))
                for key in stale_keys:
                    try:
                        deleted = client.delete(key)
                        if deleted:
                            log.warning("   ✓ Deleted: %s", key)
                            cleared += 1
                        else:
                            log.info("   - Already gone: %s", key)
                    except Exception as exc:
                        log.error("   ✗ Failed to delete %s: %s", key, exc)

            if args.force:
                log.warning("\n🔥 Force-deleting ALL nija:* keys...")
                for key in all_keys:
                    try:
                        deleted = client.delete(key)
                        if deleted:
                            log.warning("   ✓ Force-deleted: %s", key)
                            cleared += 1
                    except Exception as exc:
                        log.error("   ✗ Failed to delete %s: %s", key, exc)

            log.info("\n✅ Cleared %d keys total", cleared)
            if cleared > 0:
                log.info("   ✓ Preflight can now run successfully")

    except Exception as exc:
        log.error("❌ Scan failed: %s", exc)
        sys.exit(1)

    log.info("\n" + "=" * 72)
    log.info("✅ Redis lock diagnostic complete")
    log.info("=" * 72)


if __name__ == "__main__":
    main()
