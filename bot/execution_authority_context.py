"""
Execution authority context
===========================

Provides a thread/task-safe context marker used to assert that broker order
submission is happening through the canonical ExecutionPipeline path.
"""

from __future__ import annotations

import os
import threading
import time
import logging
import importlib
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

from bot.instance_identity import (
    current_instance_identity,
    inspect_lock_holder,
    parse_distributed_lock_holder,
    parse_writer_lock_metadata,
)
from bot.redis_env import get_redis_url


_EXECUTION_AUTHORITY_ACTIVE: ContextVar[bool] = ContextVar(
    "nija_execution_authority_active",
    default=False,
)

_FENCE_VERIFY_LOCK = threading.Lock()
_FENCE_LAST_CHECK_TS: float = 0.0
_FENCE_LAST_OK: bool = False
_FENCE_LAST_ERR: str = ""

logger = logging.getLogger("nija.execution_authority")


def _env_truthy(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "enabled", "on"}


def assert_distributed_writer_authority() -> None:
    """Fail closed when this process no longer owns the distributed writer lock.

    Validation source:
    - ``NIJA_WRITER_FENCING_TOKEN`` (set at startup when lock acquired)
    - ``NIJA_WRITER_LOCK_KEY`` (or scoped default)
    - Redis value at lock key must begin with the same token

    Runtime cost is bounded by a short verification cache to avoid a Redis
    round-trip on every order.
    """
    global _FENCE_LAST_CHECK_TS, _FENCE_LAST_OK, _FENCE_LAST_ERR

    live_mode = _env_truthy("LIVE_CAPITAL_VERIFIED")
    unsafe_bypass = _env_truthy("NIJA_UNSAFE_BYPASS_DISTRIBUTED_LOCK")
    strict_required = (_env_truthy("NIJA_REQUIRE_DISTRIBUTED_LOCK") or live_mode) and not unsafe_bypass

    token = os.getenv("NIJA_WRITER_FENCING_TOKEN", "").strip()
    if not token:
        if strict_required:
            raise RuntimeError("distributed writer fencing token missing in strict/live mode")
        return

    try:
        verify_ttl_s = max(0.0, float(os.getenv("NIJA_WRITER_RUNTIME_VERIFY_TTL_S", "1.5") or 1.5))
    except (TypeError, ValueError):
        verify_ttl_s = 1.5
        logger.warning(
            "Invalid NIJA_WRITER_RUNTIME_VERIFY_TTL_S value; using default %.1fs",
            verify_ttl_s,
        )
    now = time.monotonic()
    with _FENCE_VERIFY_LOCK:
        if verify_ttl_s > 0 and (now - _FENCE_LAST_CHECK_TS) <= verify_ttl_s:
            if _FENCE_LAST_OK:
                return
            raise RuntimeError(_FENCE_LAST_ERR or "distributed writer fence verification cached failure")

    redis_url = get_redis_url()
    scope = os.getenv("NIJA_WRITER_LOCK_SCOPE", "").strip()
    if not scope:
        raw = (
            os.environ.get("KRAKEN_PLATFORM_API_KEY", "").strip()
            or os.environ.get("KRAKEN_API_KEY", "").strip()
            or "default"
        )
        # Keep parity with startup lock scope derivation shape when explicit key isn't set.
        import hashlib
        scope = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    lock_key = os.getenv("NIJA_WRITER_LOCK_KEY", "").strip() or f"nija:writer_lock:{scope}"
    meta_key = os.getenv("NIJA_WRITER_LOCK_META_KEY", "").strip() or f"nija:writer_lock_meta:{scope}"

    fail_closed_verify = _env_truthy("NIJA_WRITER_RUNTIME_VERIFY_FAIL_CLOSED") or strict_required
    if not redis_url:
        if fail_closed_verify:
            _err = "redis url missing for distributed writer runtime verification"
            with _FENCE_VERIFY_LOCK:
                _FENCE_LAST_CHECK_TS = time.monotonic()
                _FENCE_LAST_OK = False
                _FENCE_LAST_ERR = _err
            raise RuntimeError(_err)
        return

    try:
        redis_mod = importlib.import_module("redis")

        client = redis_mod.Redis.from_url(
            redis_url,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
        current = client.get(lock_key)
        current_token = ""
        if isinstance(current, str) and current:
            current_token = current.split(":", 1)[0]

        ok = (current_token == token)
        err = ""
        if not ok:
            err = (
                "distributed writer fencing mismatch: "
                f"expected_token={token} current_token={current_token or '<missing>'}"
            )

        with _FENCE_VERIFY_LOCK:
            _FENCE_LAST_CHECK_TS = time.monotonic()
            _FENCE_LAST_OK = ok
            _FENCE_LAST_ERR = err

        if not ok:
            raise RuntimeError(err)
    except Exception as exc:
        if fail_closed_verify:
            with _FENCE_VERIFY_LOCK:
                _FENCE_LAST_CHECK_TS = time.monotonic()
                _FENCE_LAST_OK = False
                _FENCE_LAST_ERR = str(exc)
            raise RuntimeError(str(exc)) from exc
        logger.warning("distributed writer runtime verification degraded (fail-open): %s", exc)


def get_distributed_writer_authority_status(force_refresh: bool = False) -> dict:
    """Return current distributed-writer ownership status for diagnostics.

    This helper never raises; it is safe to call from health/status endpoints.
    """
    global _FENCE_LAST_CHECK_TS

    live_mode = _env_truthy("LIVE_CAPITAL_VERIFIED")
    unsafe_bypass = _env_truthy("NIJA_UNSAFE_BYPASS_DISTRIBUTED_LOCK")
    strict_required = (_env_truthy("NIJA_REQUIRE_DISTRIBUTED_LOCK") or live_mode) and not unsafe_bypass
    redis_url = get_redis_url()
    token = os.getenv("NIJA_WRITER_FENCING_TOKEN", "").strip()
    scope = os.getenv("NIJA_WRITER_LOCK_SCOPE", "").strip()
    if not scope:
        raw = (
            os.environ.get("KRAKEN_PLATFORM_API_KEY", "").strip()
            or os.environ.get("KRAKEN_API_KEY", "").strip()
            or "default"
        )
        import hashlib
        scope = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    lock_key = os.getenv("NIJA_WRITER_LOCK_KEY", "").strip() or f"nija:writer_lock:{scope}"
    meta_key = os.getenv("NIJA_WRITER_LOCK_META_KEY", "").strip() or f"nija:writer_lock_meta:{scope}"

    if force_refresh:
        with _FENCE_VERIFY_LOCK:
            _FENCE_LAST_CHECK_TS = 0.0

    ok = True
    err = ""
    try:
        assert_distributed_writer_authority()
    except Exception as exc:
        ok = False
        err = str(exc)

    with _FENCE_VERIFY_LOCK:
        last_check_ts = _FENCE_LAST_CHECK_TS
        last_ok = _FENCE_LAST_OK
        last_err = _FENCE_LAST_ERR

    current_holder_raw = ""
    current_holder = parse_distributed_lock_holder("")
    current_holder_meta = parse_writer_lock_metadata("")
    current_instance = current_instance_identity()
    holder_inspection = inspect_lock_holder(current_instance, current_holder)
    if redis_url:
        try:
            redis_mod = importlib.import_module("redis")
            client = redis_mod.Redis.from_url(
                redis_url,
                decode_responses=True,
                socket_connect_timeout=2,
                socket_timeout=2,
            )
            current_holder_raw = str(client.get(lock_key) or "")
            current_holder_meta = parse_writer_lock_metadata(str(client.get(meta_key) or ""))
            current_holder = parse_distributed_lock_holder(current_holder_raw)
            holder_inspection = inspect_lock_holder(current_instance, current_holder)
        except Exception as exc:
            current_holder = {
                "raw": current_holder_raw,
                "display": "<unavailable>",
                "error": str(exc),
            }
            current_holder_meta = {
                "raw": "",
                "display": "<unavailable>",
                "error": str(exc),
            }
            holder_inspection = inspect_lock_holder(current_instance, current_holder)

    return {
        "ok": bool(ok),
        "error": err,
        "strict_required": bool(strict_required),
        "unsafe_bypass_enabled": bool(unsafe_bypass),
        "live_mode": bool(live_mode),
        "redis_configured": bool(redis_url),
        "token_present": bool(token),
        "token_prefix": token[:8] if token else "",
        "lock_key": lock_key,
        "meta_key": meta_key,
        "current_instance": current_instance,
        "current_holder": current_holder,
        "current_holder_meta": current_holder_meta,
        "holder_inspection": holder_inspection,
        "cache": {
            "last_check_monotonic": float(last_check_ts),
            "last_ok": bool(last_ok),
            "last_error": last_err,
        },
    }


@contextmanager
def execution_authority_scope() -> Iterator[None]:
    """Mark the current context as execution-authorized for broker submits."""
    token = _EXECUTION_AUTHORITY_ACTIVE.set(True)
    try:
        yield
    finally:
        _EXECUTION_AUTHORITY_ACTIVE.reset(token)


def has_execution_authority() -> bool:
    """Return True when the current context is authorized for order submit."""
    return bool(_EXECUTION_AUTHORITY_ACTIVE.get())
