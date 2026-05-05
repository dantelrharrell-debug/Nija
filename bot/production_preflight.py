"""
NIJA Production Pre-Flight
==========================

Executes the mandatory checks before the bot enters live mode:

  Step 1 — Redis PING confirmation
  Step 2 — Lock acquisition logging
  Step 3 — Redis persistence + fencing health
  Step 4 — Single-instance enforcement
  Step 5 — Stale lock clearance
  Step 6 — Live-mode verification
  Step 7 — Adversarial validation (optional: multi-instance + failure injection)

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

import hashlib
import json
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
_TRUTHY = {"1", "true", "yes", "on", "enabled"}
_RECOMMENDED_LEASE_TTL_MS = 20_000  # Aligns with clamped 10-30s lease TTL range (20s default).


def _env_truthy(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in _TRUTHY


def _redis_health_state_path() -> Path:
    raw = os.getenv("NIJA_REDIS_HEALTH_STATE_PATH", "").strip()
    if raw:
        return Path(raw)
    return Path(__file__).resolve().parents[1] / "data" / "redis_health_state.json"


def _load_health_state(path: Path) -> dict:
    try:
        if path.exists():
            return json.loads(path.read_text())
    except Exception:
        pass
    return {}


def _write_health_state(path: Path, payload: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True))
        tmp_path.replace(path)
    except Exception as exc:
        log.warning("Could not persist Redis health state: %s", exc)


def _mark_safe_start_required(reason: str) -> None:
    """Flag that startup must enter safe-start mode until reconciliation/ack."""
    os.environ["NIJA_SAFE_START_REQUIRED"] = "true"
    os.environ.setdefault("NIJA_SAFE_START_REASON", reason)
    log.critical("SAFE START REQUIRED — %s", reason)


def _resolve_platform_key() -> str:
    return (
        os.environ.get("KRAKEN_PLATFORM_API_KEY", "").strip()
        or os.environ.get("KRAKEN_API_KEY", "").strip()
    )


def _resolve_writer_lock_scope() -> str:
    raw = _resolve_platform_key() or "default"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _resolve_writer_lock_key() -> str:
    return os.getenv("NIJA_WRITER_LOCK_KEY", "").strip() or f"nija:writer_lock:{_resolve_writer_lock_scope()}"


def _parse_lock_token(raw_value: str) -> int:
    if not raw_value:
        return 0
    token = str(raw_value).split(":", 1)[0]
    try:
        return int(token)
    except (TypeError, ValueError):
        return 0


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
    ttl_ms   = int(os.getenv("NIJA_REDIS_LEASE_TTL_MS", str(_RECOMMENDED_LEASE_TTL_MS)))

    log.info("Writer-lock Redis key : %s", lock_key)
    log.info("Writer-lock TTL       : %d ms", ttl_ms)
    if ttl_ms < _RECOMMENDED_LEASE_TTL_MS:
        log.warning(
            "⚠️  Lease TTL below recommended minimum (%d ms < %d ms). "
            "Increase NIJA_REDIS_LEASE_TTL_MS to reduce premature lease expiry.",
            ttl_ms,
            _RECOMMENDED_LEASE_TTL_MS,
        )

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
# Step 3 — Redis health, persistence, and monotonicity guard
# ─────────────────────────────────────────────────────────────────────────────

def _step3_redis_health(redis_client: "redis.Redis") -> None:  # type: ignore[name-defined]
    """Validate Redis persistence, writer lock ownership, and nonce continuity.

    This gate fail-closes live-mode startup when persistence cannot be verified,
    when writer fencing ownership is missing, or when a reset is detected without
    explicit operator acknowledgement. It prevents split-brain trading.
    """
    _step(3, "Redis persistence + fencing health")

    dry_run = _env_truthy("DRY_RUN_MODE", "false")
    paper = _env_truthy("PAPER_MODE", "false")
    live_mode = not dry_run and not paper
    unsafe_bypass = _env_truthy("NIJA_UNSAFE_BYPASS_DISTRIBUTED_LOCK", "false")
    strict_lock_required = (live_mode or _env_truthy("NIJA_REQUIRE_DISTRIBUTED_LOCK", "false")) and not unsafe_bypass
    # Strict nonce lease enforcement mirrors startup lock requirements.
    strict_lease = _env_truthy("NIJA_STRICT_REDIS_LEASE", "true") and not unsafe_bypass
    persistence_required = live_mode and _env_truthy("NIJA_REDIS_PERSISTENCE_REQUIRED", "true")
    reset_policy = os.getenv("NIJA_REDIS_RESET_POLICY", "require_confirmation").strip().lower()
    if reset_policy not in {"auto_reinit", "require_confirmation"}:
        log.warning(
            "Invalid NIJA_REDIS_RESET_POLICY=%r; defaulting to require_confirmation",
            reset_policy,
        )
        reset_policy = "require_confirmation"

    persistence_info = {}
    server_info = {}
    try:
        persistence_info = redis_client.info("persistence")
    except Exception as exc:
        log.warning("Could not read Redis persistence info: %s", exc)
    try:
        server_info = redis_client.info()
    except Exception as exc:
        log.warning("Could not read Redis server info: %s", exc)

    aof_enabled = int(persistence_info.get("aof_enabled", 0) or 0)
    aof_write_status = str(persistence_info.get("aof_last_write_status", "") or "").lower()
    aof_write_errno = int(persistence_info.get("aof_last_write_errno", 0) or 0)
    rdb_status = str(persistence_info.get("rdb_last_bgsave_status", "") or "").lower()
    rdb_in_progress = int(persistence_info.get("rdb_bgsave_in_progress", 0) or 0)
    rdb_configured = "rdb_last_bgsave_status" in persistence_info
    rdb_enabled = bool(rdb_configured and (rdb_status == "ok" or rdb_in_progress == 1))
    persistence_ok = bool(aof_enabled == 1 or rdb_enabled)
    loading = int(server_info.get("loading", 0) or 0)

    if not persistence_info:
        msg = (
            "Redis persistence info unavailable — verify Redis connection and INFO permissions "
            "to confirm AOF/RDB durability"
        )
        if persistence_required:
            _fail(msg)
            sys.exit(1)
        log.warning("⚠️  %s (set NIJA_REDIS_PERSISTENCE_REQUIRED=true to enforce)", msg)
    elif not persistence_ok:
        msg = "Redis persistence not confirmed or disabled — enable AOF or RDB snapshots"
        if persistence_required:
            _fail(msg)
            sys.exit(1)
        log.warning("⚠️  %s", msg)
    elif aof_enabled and aof_write_status and aof_write_status != "ok":
        msg = f"Redis AOF last write status not ok (status={aof_write_status})"
        if persistence_required:
            _fail(msg)
            sys.exit(1)
        log.warning("⚠️  %s", msg)
    elif aof_enabled and aof_write_errno != 0:
        msg = f"Redis AOF last write errno non-zero (errno={aof_write_errno})"
        if persistence_required:
            _fail(msg)
            sys.exit(1)
        log.warning("⚠️  %s", msg)
    elif rdb_configured and rdb_status and rdb_status != "ok":
        msg = f"Redis RDB last bgsave status not ok (status={rdb_status})"
        if persistence_required:
            _fail(msg)
            sys.exit(1)
        log.warning("⚠️  %s", msg)
    elif loading == 1:
        msg = "Redis is still loading data — wait for persistence load to complete"
        if persistence_required:
            _fail(msg)
            sys.exit(1)
        log.warning("⚠️  %s", msg)
    else:
        _ok("Redis persistence confirmed (AOF or RDB enabled)")

    lock_key = _resolve_writer_lock_key()
    expected_token_raw = os.getenv("NIJA_WRITER_FENCING_TOKEN", "").strip()
    try:
        expected_token = int(expected_token_raw)
    except (TypeError, ValueError):
        expected_token = 0
    current_raw = ""
    current_token = 0
    try:
        current_raw = str(redis_client.get(lock_key) or "")
        current_token = _parse_lock_token(current_raw)
    except Exception as exc:
        log.warning("Could not read writer lock key %s: %s", lock_key, exc)

    if strict_lock_required and not expected_token:
        _fail("Distributed writer fencing token missing in strict/live mode")
        sys.exit(1)
    if expected_token and current_token != expected_token:
        _fail(
            "Distributed writer lock token mismatch "
            f"(expected={expected_token}, current={current_token or '<missing>'})"
        )
        sys.exit(1)

    platform_key = _resolve_platform_key()
    lease_version = 0
    nonce_value = 0
    key_id = ""
    if platform_key:
        try:
            from bot.distributed_nonce_manager import make_api_key_id
        except (ImportError, AttributeError):
            from distributed_nonce_manager import make_api_key_id  # type: ignore[import]

        key_id = make_api_key_id(platform_key)
        lease_key = f"nija:kraken:writer:lease_version:{key_id}"
        nonce_key = f"nija:kraken:nonce:{key_id}"
        try:
            lease_version = int(redis_client.get(lease_key) or 0)
            nonce_value = int(redis_client.get(nonce_key) or 0)
        except Exception as exc:
            log.warning(
                "Could not read nonce keys %s / %s: %s",
                lease_key,
                nonce_key,
                exc,
            )

        if strict_lease and lease_version <= 0:
            _fail("Redis nonce writer lease missing in strict mode")
            sys.exit(1)
    else:
        log.warning("Kraken platform key not configured — skipping nonce continuity check")

    state_path = _redis_health_state_path()
    previous = _load_health_state(state_path)
    prev_token = int(previous.get("writer_fence_token", 0) or 0)
    prev_lease = int(previous.get("nonce_lease_version", 0) or 0)
    prev_nonce = int(previous.get("nonce_value", 0) or 0)
    prev_run_id = str(previous.get("redis_run_id", "") or "")

    reset_reasons = []
    if prev_token and current_token and current_token < prev_token:
        reset_reasons.append(
            f"writer lock token decreased (prev={prev_token}, current={current_token})"
        )
    if prev_lease and lease_version and lease_version < prev_lease:
        reset_reasons.append(
            f"nonce lease version decreased (prev={prev_lease}, current={lease_version})"
        )
    if prev_nonce and nonce_value and nonce_value < prev_nonce:
        reset_reasons.append(
            f"nonce value decreased (prev={prev_nonce}, current={nonce_value})"
        )

    try:
        run_id = str(server_info.get("run_id", "") or "")
    except Exception:
        run_id = ""

    if prev_run_id and run_id and prev_run_id != run_id:
        log.warning(
            "⚠️  Redis run_id changed since last boot (prev=%s, current=%s). "
            "Treating as a restart signal; persistence checks enforce durability.",
            prev_run_id,
            run_id,
        )

    if _env_truthy("NIJA_UNCLEAN_SHUTDOWN", "false"):
        _mark_safe_start_required("unclean shutdown detected")

    if reset_reasons:
        _mark_safe_start_required("redis reset detected")
        policy = reset_policy
        ack = _env_truthy("NIJA_REDIS_RESET_ACK", "false")
        reconciled = _env_truthy("NIJA_REDIS_RESET_RECONCILED", "false")
        message = "; ".join(reset_reasons)
        if policy == "auto_reinit":
            if not reconciled:
                _fail(
                    "Redis reset detected — auto-reinit requires reconciliation: "
                    f"{message}. Set NIJA_REDIS_RESET_RECONCILED=true after exchange state is verified."
                )
                sys.exit(1)
            log.critical("Redis reset detected (%s) — auto-reinit allowed after reconciliation", message)
        elif not ack:
            _fail(
                "Redis reset detected — manual confirmation required: "
                f"{message}. Set NIJA_REDIS_RESET_ACK=true and redeploy to proceed."
            )
            sys.exit(1)
        else:
            log.critical("Redis reset detected (%s) — manual confirmation acknowledged", message)

    if platform_key:
        _ok(
            "Redis nonce continuity verified "
            f"(lease_version={lease_version}, nonce={nonce_value}, key_id={key_id})"
        )

    _write_health_state(
        state_path,
        {
            "checked_at": time.time(),
            "redis_run_id": run_id,
            "writer_fence_token": current_token,
            "nonce_lease_version": lease_version,
            "nonce_value": nonce_value,
        },
    )

    _ok("Redis fencing health verified")


# ─────────────────────────────────────────────────────────────────────────────
# Step 4 — Single instance enforcement (file-based bootstrap guard)
# ─────────────────────────────────────────────────────────────────────────────

def _step4_single_instance() -> None:
    """Acquire the bootstrap guard to enforce single-instance operation."""
    _step(4, "Single-instance enforcement")

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
# Step 5 — Clear stale locks
# ─────────────────────────────────────────────────────────────────────────────

def _step5_clear_stale_locks(redis_client: "redis.Redis") -> None:  # type: ignore[name-defined]
    """Remove Redis keys that have no TTL (permanent/stale) from the lock namespace."""
    _step(5, "Stale lock clearance")

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
# Step 6 — Live-mode verification
# ─────────────────────────────────────────────────────────────────────────────

def _step6_live_mode_check() -> None:
    """Confirm that the environment is correctly configured for live trading."""
    _step(6, "Live-mode verification")

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
# Step 7 — Adversarial validation (optional)
# ─────────────────────────────────────────────────────────────────────────────

def _step7_adversarial_validation() -> None:
    """Run optional adversarial validation (multi-instance + failure injection)."""
    if not _env_truthy("NIJA_ADVERSARIAL_VALIDATION", "false"):
        log.info("ℹ️  Adversarial validation disabled (NIJA_ADVERSARIAL_VALIDATION=false)")
        return

    _step(7, "Adversarial validation (multi-instance + failure injection)")

    try:
        from bot.execution_authority_context import (
            get_distributed_writer_authority_status,
            assert_distributed_writer_authority,
        )
        from bot.instance_identity import inspect_lock_holder
    except ImportError as exc:
        _fail(f"Cannot import adversarial validation helpers: {exc}")
        sys.exit(1)

    status = get_distributed_writer_authority_status(force_refresh=True)
    if not status.get("ok"):
        _fail(f"Distributed writer authority check failed: {status.get('error')}")
        sys.exit(1)

    holder = status.get("current_holder") or {}
    current = status.get("current_instance") or {}
    inspection = inspect_lock_holder(current, holder)
    if inspection.get("relationship") == "other-instance":
        _fail(f"Writer lock held by another instance — {inspection.get('summary')}")
        sys.exit(1)

    _ok(f"Writer lock holder validated ({inspection.get('relationship')})")

    token = os.getenv("NIJA_WRITER_FENCING_TOKEN", "").strip()
    strict_required = bool(status.get("effective_strict_required"))
    if not token:
        log.warning("⚠️  Skipping failure injection: NIJA_WRITER_FENCING_TOKEN not set")
        return
    if not strict_required:
        log.warning("⚠️  Skipping failure injection: strict distributed lock not required")
        return

    invalid_token = f"invalid-{token[:6]}"
    os.environ["NIJA_WRITER_FENCING_TOKEN"] = invalid_token
    try:
        try:
            assert_distributed_writer_authority()
            _fail("Failure injection did not block invalid writer fence token")
            sys.exit(1)
        except Exception as exc:
            _ok(f"Failure injection blocked as expected ({exc})")
    finally:
        os.environ["NIJA_WRITER_FENCING_TOKEN"] = token


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────────────

def run_preflight() -> None:
    """Execute all pre-flight checks.  Exits with code 1 on any failure."""
    log.info(SEPARATOR)
    log.info("NIJA PRODUCTION PRE-FLIGHT")
    log.info(SEPARATOR)
    start = time.monotonic()

    redis_client = _step1_redis_ping()
    _step2_lock_logging(redis_client)
    _step3_redis_health(redis_client)
    _step4_single_instance()
    _step5_clear_stale_locks(redis_client)
    _step6_live_mode_check()
    _step7_adversarial_validation()

    elapsed = time.monotonic() - start
    log.info(SEPARATOR)
    log.info("✅  ALL PRE-FLIGHT CHECKS PASSED  (%.2f s)", elapsed)
    log.info("    Safe to start the bot in live mode.")
    log.info(SEPARATOR)


if __name__ == "__main__":
    run_preflight()
