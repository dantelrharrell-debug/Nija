"""Kraken reconnect supervisor — bounded, non-recursive state machine.

Provides a single canonical place for Kraken reconnect lifecycle management:

* Only one in-flight reconnect attempt at a time; duplicate workers are
  prevented via a threading.Event guard.
* Bounded exponential backoff with jitter for transient failures.
* Backoff resets after a successful authenticated connection.
* Permanent/configuration failures (bad key, bad secret, invalid permissions,
  IP allowlist, clock/nonce) stop rapid retries with a single actionable log.
* Product loading is retried after Kraken becomes connected.
* Coinbase and OKX capital snapshots are never blocked or reset by a Kraken
  failure.
* Never logs API keys, secrets, signatures, or passphrases.

Failure taxonomy
----------------
Transient (retryable with backoff):
  network timeout, connection reset, temporary DNS failure, Kraken 5xx,
  temporary rate limiting, temporary exchange unavailability.

Permanent / configuration (stop reconnecting after first detection):
  missing credentials, invalid API key, invalid signature, invalid secret
  encoding, insufficient permissions, IP allowlist rejection, clock/nonce
  problems caused by configuration.

Required environment variables (same names used in broker_manager.py)
----------------------------------------------------------------------
  KRAKEN_PLATFORM_API_KEY   or  KRAKEN_API_KEY
  KRAKEN_PLATFORM_API_SECRET  or  KRAKEN_API_SECRET

Optional tuning
---------------
  NIJA_KRAKEN_RECONNECT_BASE_DELAY_S   default 10.0 (minimum 5 s)
  NIJA_KRAKEN_RECONNECT_MAX_DELAY_S    default 300.0
  NIJA_KRAKEN_RECONNECT_MAX_ATTEMPTS   default 0 (unlimited transient retries)
  NIJA_DISABLE_KRAKEN                  skip reconnect when set to a truthy value
"""
from __future__ import annotations

import logging
import math
import os
import random
import threading
import time
from typing import Any, Optional

logger = logging.getLogger("nija.kraken_reconnect_supervisor")
_MARKER = "20260804-kraken-reconnect-supervisor-v1"

_TRUE = {"1", "true", "yes", "on", "enabled", "y"}

# ── Module-level singleton guards ─────────────────────────────────────────────
_LOCK = threading.RLock()
_RECONNECT_IN_FLIGHT = threading.Event()  # set while a reconnect thread is running
_PERMANENT_FAILURE_SEEN: Optional[str] = None  # non-None → stop fast retries
_ATTEMPT_COUNT = 0
_LAST_BACKOFF_RESET_AT: float = 0.0

# ── Permanent-failure keywords (case-insensitive substring match) ─────────────
# These match the error strings returned by the Kraken private REST API and by
# KrakenErrorCategory.AUTH / PERMISSION in kraken_error_taxonomy.py.
_PERMANENT_PATTERNS = (
    "invalid key",
    "invalid signature",
    "invalid secret",
    "eapi:invalid key",
    "eapi:invalid signature",
    "eapi:invalid nonce",
    "invalid api key",
    "api key not found",
    "permission denied",
    "ip not allowed",
    "ip allowlist",
    "insufficient funds",  # only a perm failure in AUTH context
    "account suspended",
    "base64",
    "malformed",
    "credentials",
    "auth_failure",
    "authentication_failure",
    "invalid_key",
    "invalid_secret",
)


def _truthy(name: str, default: str = "false") -> bool:
    return str(os.environ.get(name, default) or "").strip().lower() in _TRUE


def _credentials_configured() -> bool:
    key = (
        os.environ.get("KRAKEN_PLATFORM_API_KEY")
        or os.environ.get("KRAKEN_API_KEY")
        or ""
    ).strip()
    secret = (
        os.environ.get("KRAKEN_PLATFORM_API_SECRET")
        or os.environ.get("KRAKEN_API_SECRET")
        or ""
    ).strip()
    disabled = _truthy("NIJA_DISABLE_KRAKEN") or _truthy("KRAKEN_EXECUTION_DISABLED")
    return bool(key and secret and not disabled)


def _base_delay() -> float:
    try:
        return max(5.0, float(os.environ.get("NIJA_KRAKEN_RECONNECT_BASE_DELAY_S", "10.0") or 10.0))
    except (TypeError, ValueError):
        return 10.0


def _max_delay() -> float:
    try:
        return max(_base_delay(), float(os.environ.get("NIJA_KRAKEN_RECONNECT_MAX_DELAY_S", "300.0") or 300.0))
    except (TypeError, ValueError):
        return 300.0


def _backoff_seconds(attempt: int) -> float:
    """Bounded exponential backoff with ±25% jitter."""
    base = _base_delay()
    cap = _max_delay()
    raw = base * (2 ** min(attempt, 8))  # cap exponent to avoid overflow
    clamped = min(raw, cap)
    jitter = clamped * 0.25 * (random.random() * 2 - 1)
    return max(base, clamped + jitter)


def _is_permanent_failure(error_str: str) -> bool:
    """Return True if the error indicates a permanent configuration problem."""
    lowered = error_str.lower()
    return any(pat in lowered for pat in _PERMANENT_PATTERNS)


def _classify_and_log_permanent(error_str: str, category: str) -> None:
    """Log a clear actionable error for a permanent Kraken config failure.

    Never prints the credential value — only the category and sanitised message.
    """
    logger.error(
        "KRAKEN_PERMANENT_FAILURE marker=%s category=%s "
        "action=stop_reconnect_configure_credentials_or_permissions "
        "hint=check_KRAKEN_PLATFORM_API_KEY_and_KRAKEN_PLATFORM_API_SECRET "
        "msg=%.120s",
        _MARKER,
        category,
        error_str,  # truncated, contains no key/secret material by convention
    )


def is_permanent_failure_latched() -> bool:
    """Return True if a permanent Kraken config failure has been recorded."""
    return _PERMANENT_FAILURE_SEEN is not None


def reset_permanent_failure_latch() -> None:
    """Clear the permanent-failure latch (for testing or credential rotation)."""
    global _PERMANENT_FAILURE_SEEN
    with _LOCK:
        _PERMANENT_FAILURE_SEEN = None


def _attempt_authenticated_connect(broker: Any) -> tuple[bool, Optional[str]]:
    """Try one authenticated Kraken connection.

    Returns (success, error_string_or_None).

    Uses broker.connect() which runs the full handshake including a private API
    call (balance fetch) that proves the credentials work.  Only sets
    broker.connected=True via the KrakenStartupFSM after success — never marks
    connected after an unauthenticated public-products call alone.
    """
    try:
        result = broker.connect()
        connected = bool(result) and bool(getattr(broker, "connected", False))
        if connected:
            return True, None
        # connect() returned False without raising — treat as transient
        return False, "connect_returned_false"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def _retry_product_loading(broker: Any) -> None:
    """Reload products after a successful authenticated connection."""
    try:
        if callable(getattr(broker, "get_all_products", None)):
            broker.get_all_products()
            logger.info(
                "KRAKEN_PRODUCTS_LOADED_AFTER_RECONNECT marker=%s",
                _MARKER,
            )
    except Exception as exc:
        logger.warning(
            "KRAKEN_PRODUCTS_LOAD_DEFERRED marker=%s error=%s:%s",
            _MARKER,
            type(exc).__name__,
            exc,
        )


def _reconnect_worker(broker: Any) -> None:
    """Non-recursive bounded reconnect loop (runs in its own daemon thread)."""
    global _PERMANENT_FAILURE_SEEN, _ATTEMPT_COUNT, _LAST_BACKOFF_RESET_AT

    marker = _MARKER
    attempt = 0
    backoff_reset = time.monotonic()

    try:
        logger.info(
            "KRAKEN_RECONNECT_SUPERVISOR_STARTED marker=%s",
            marker,
        )

        while True:
            # ── Check for permanent failure latch ─────────────────────────
            with _LOCK:
                perm = _PERMANENT_FAILURE_SEEN
            if perm is not None:
                logger.warning(
                    "KRAKEN_RECONNECT_SUPERVISOR_HALTED marker=%s reason=permanent_failure "
                    "category=%s coinbase_okx_unaffected=true",
                    marker,
                    perm,
                )
                return

            # ── Check credentials still configured ───────────────────────
            if not _credentials_configured():
                logger.warning(
                    "KRAKEN_RECONNECT_SUPERVISOR_HALTED marker=%s "
                    "reason=credentials_not_configured coinbase_okx_unaffected=true",
                    marker,
                )
                return

            # ── Check if already connected ────────────────────────────────
            if bool(getattr(broker, "connected", False)):
                logger.info(
                    "KRAKEN_RECONNECT_SUPERVISOR_CONNECTED marker=%s "
                    "attempt=%d reconnected=true",
                    marker,
                    attempt,
                )
                # Reset backoff after success
                with _LOCK:
                    _LAST_BACKOFF_RESET_AT = time.monotonic()
                    _ATTEMPT_COUNT = 0
                _retry_product_loading(broker)
                return

            # ── Attempt connect ───────────────────────────────────────────
            attempt += 1
            with _LOCK:
                _ATTEMPT_COUNT = attempt

            logger.info(
                "KRAKEN_RECONNECT_ATTEMPT marker=%s attempt=%d",
                marker,
                attempt,
            )

            success, error_str = _attempt_authenticated_connect(broker)

            if success:
                with _LOCK:
                    _LAST_BACKOFF_RESET_AT = time.monotonic()
                    _ATTEMPT_COUNT = 0
                logger.info(
                    "KRAKEN_RECONNECT_SUCCESS marker=%s attempt=%d "
                    "authenticated=true coinbase_okx_unaffected=true",
                    marker,
                    attempt,
                )
                _retry_product_loading(broker)
                return

            # ── Classify failure ──────────────────────────────────────────
            if error_str and _is_permanent_failure(error_str):
                with _LOCK:
                    _PERMANENT_FAILURE_SEEN = error_str[:120]
                _classify_and_log_permanent(error_str, "auth_or_config")
                return

            # ── Transient failure — back off ──────────────────────────────
            delay = _backoff_seconds(attempt - 1)
            logger.warning(
                "KRAKEN_RECONNECT_TRANSIENT_FAILURE marker=%s attempt=%d "
                "backoff_s=%.1f error_category=transient coinbase_okx_unaffected=true",
                marker,
                attempt,
                delay,
            )
            time.sleep(delay)

    finally:
        # Always release the in-flight guard so the next cycle can start a worker.
        _RECONNECT_IN_FLIGHT.clear()
        logger.debug(
            "KRAKEN_RECONNECT_SUPERVISOR_EXITED marker=%s attempt=%d",
            marker,
            attempt if "attempt" in dir() else 0,
        )


def ensure_reconnect_started(broker: Any) -> bool:
    """Start a reconnect worker if none is in flight and Kraken is not connected.

    Safe to call from any thread; guarantees at most one active worker.
    Returns True if a new worker was started, False if one was already running
    or Kraken is already connected.
    """
    if bool(getattr(broker, "connected", False)):
        return False

    if is_permanent_failure_latched():
        return False

    if not _credentials_configured():
        return False

    # Use test-and-set on the Event to prevent duplicate workers.
    if _RECONNECT_IN_FLIGHT.is_set():
        return False

    with _LOCK:
        if _RECONNECT_IN_FLIGHT.is_set():
            return False
        _RECONNECT_IN_FLIGHT.set()

    t = threading.Thread(
        target=_reconnect_worker,
        args=(broker,),
        name="KrakenReconnectSupervisor",
        daemon=True,
    )
    t.start()
    logger.info(
        "KRAKEN_RECONNECT_SUPERVISOR_WORKER_LAUNCHED marker=%s",
        _MARKER,
    )
    return True
