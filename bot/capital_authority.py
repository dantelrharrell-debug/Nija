"""
NIJA Capital Authority
=======================

Single source of truth for all capital figures consumed by every live
trading module.  No module may invent its own capital baseline; all must
read from this singleton.

Contract
--------
::

    from bot.capital_authority import get_capital_authority

    # At startup (after brokers connect):
    authority = get_capital_authority()
    authority.refresh(broker_map)           # pulls real balances

    # Anywhere inside the trading pipeline:
    real     = authority.get_real_capital()     # gross USD+USDC equity
    usable   = authority.get_usable_capital()   # real minus reserve dust
    risk_cap = authority.get_risk_capital()     # usable minus open exposure
    per_b    = authority.get_per_broker("kraken")

    if authority.is_stale(ttl_s=90):
        authority.refresh(broker_map)

Normalization contract
----------------------
* ``reserve_pct``   — fraction of real capital held back as reserve dust.
                      Default 0.02 (2 %).  Override via env
                      ``NIJA_CAPITAL_RESERVE_PCT``.
* ``get_usable_capital()`` = real * (1 - reserve_pct)
* ``get_risk_capital()``   = usable - registered open-position exposure
                             (call ``register_open_exposure(usd)`` each
                              cycle before reading risk_capital)

Thread-safety
-------------
All public methods are protected by a single ``threading.RLock``.
``refresh()`` captures the lock for the duration of state updates; because
``get_real_capital()`` (and similar read helpers) also acquire the same lock
we use an ``RLock`` so the same thread can re-enter without deadlocking.

Author: NIJA Trading Systems
Version: 1.0
Date: April 2026
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import time
from collections.abc import Mapping
from contextlib import contextmanager
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("nija.capital_authority")

# ---------------------------------------------------------------------------
# CapitalIntegrityError — raised by wait_for_hydration on timeout
# ---------------------------------------------------------------------------
# Imported here from exceptions so capital_authority remains the canonical
# import path for callers that need both the barrier and the error type.
try:
    from bot.exceptions import CapitalIntegrityError
except ImportError:
    try:
        from exceptions import CapitalIntegrityError  # type: ignore[import]
    except ImportError:
        # Inline fallback so this module never hard-fails on import.
        class CapitalIntegrityError(RuntimeError):  # type: ignore[no-redef]
            """
            Raised when the capital hydration barrier times out or capital pipeline
            integrity cannot be confirmed before the trading loop starts.

            This exception is a hard stop: the trading loop must not proceed until
            CapitalAuthority has received at least one broker balance snapshot.

            Root causes that trigger this exception:
            - Broker connection failed before the hydration timeout (default 30 s)
            - CapitalAuthority was never refreshed (coordinator not running)
            - Bootstrap sequence did not complete in time

            Callers that catch this exception should log it as CRITICAL and either
            retry with back-off or abort the trading loop entirely.
            """
            pass

# ---------------------------------------------------------------------------
# Module-level constants (all overridable via environment variables)
# ---------------------------------------------------------------------------

_DEFAULT_RESERVE_PCT: float = 0.02  # 2 % held back as reserve dust

# ---------------------------------------------------------------------------
# CSM v3 — persistent capital state recovery
# ---------------------------------------------------------------------------

# Directory where the on-disk capital state is stored (mirrors CompoundingEngine
# convention: <repo_root>/data/).
_STATE_DIR: Path = Path(__file__).parent.parent / "data"
_STATE_FILE: Path = _STATE_DIR / "capital_authority_state.json"

# Maximum age (seconds) of a saved state that can be used for warm-start.
# Saved state older than this is ignored and the authority starts cold.
# Override via env var NIJA_CAPITAL_STATE_MAX_AGE_S (e.g. "3600").
_DEFAULT_STATE_MAX_AGE_S: float = 3600.0

# Schema version — increment whenever the saved-state format changes in a
# backward-incompatible way so stale files from older deployments are rejected.
_STATE_SCHEMA_VERSION: int = 1

# ---------------------------------------------------------------------------
# Broker role constants — determines which brokers count as "authoritative"
# for global-minimum and AI-capital checks.
# ---------------------------------------------------------------------------

#: Kraken and other primary execution brokers.  Capital from these accounts
#: is authoritative for global minimum checks and AI capital allocation.
BROKER_ROLE_PRIMARY = "primary"

#: Coinbase (and any NANO/sandbox broker).  Capital is real but isolated:
#: it cannot block startup, and it must never inflate the global capital figure
#: seen by the AI hub, portfolio intelligence, or the FATAL minimum check.
BROKER_ROLE_ISOLATED = "isolated"

#: Default role when a broker is registered without an explicit role.
BROKER_ROLE_UNKNOWN = "unknown"

# Maximum acceptable age of a CA snapshot before is_fresh() returns False.
# Must match (or be shorter than) the per-cycle refresh cadence in
# trading_strategy.py so a missed refresh is caught before the next trade.
_DEFAULT_FRESHNESS_TTL_S: float = 90.0

# ---------------------------------------------------------------------------
# Capital System Gate — process-wide readiness event
# ---------------------------------------------------------------------------

# Set exactly once, the first time CapitalAuthority confirms it holds a valid
# snapshot from the MABM coordinator (is_hydrated → True).  Dependent systems
# check this event to distinguish "not yet initialised" from "confirmed capital
# state" without polling or blocking.
#
# Usage (in any dependent module):
#
#     from capital_authority import get_capital_system_gate
#
#     if not get_capital_system_gate().is_set():
#         return "INITIALIZING"
#
CAPITAL_SYSTEM_READY: threading.Event = threading.Event()

# ---------------------------------------------------------------------------
# Capital Hydrated Event — fires on first snapshot (even zero-balance)
# ---------------------------------------------------------------------------
#
# Set exactly once by CapitalAuthority.publish_snapshot() the first time
# _hydrated transitions False → True.  Unlike CAPITAL_SYSTEM_READY, this
# event does NOT require real_capital > 0 — it only confirms that the
# coordinator has run at least once and the authority holds real data.
#
# Use this gate (FIX 4) when a subsystem needs to know that balance has
# been *fetched* (even if zero) rather than that capital is *positive*.
#
CAPITAL_HYDRATED_EVENT: threading.Event = threading.Event()

# ---------------------------------------------------------------------------
# Global Startup Lock — process-wide "NO EVALUATION BEFORE READY" latch
# ---------------------------------------------------------------------------
#
# SEPARATE from broker registration.  Set exactly once via
# finalize_bootstrap_ready() ONLY after ALL of the following are confirmed:
#   1. All expected brokers have been registered.
#   2. The broker list is reflected in CapitalAuthority (finalize_broker_registration
#      has been called and any pending feeds have been flushed).
#   3. The first feed batch has been processed (or confirmed empty-safe).
#   4. The capital bootstrap FSM has been initialized.
#
# Nothing is permitted to evaluate capital (trigger refreshes, create
# allocation plans) until this event is set.
#
# Usage:
#     from capital_authority import get_startup_lock
#
#     if not get_startup_lock().is_set():
#         return  # HARD BLOCK — system not yet fully synced
#
STARTUP_LOCK: threading.Event = threading.Event()

# Maximum seconds to wait for CapitalAuthority to reach ACTIVE_CAPITAL during
# bootstrap.  Increase this value if the broker connection is slow to confirm
# balances (e.g. on cold-start or high-latency environments).
CAPITAL_READY_TIMEOUT: float = 60.0


# ---------------------------------------------------------------------------
# Capital lifecycle state machine — explicit 3-phase enum
# ---------------------------------------------------------------------------


class CapitalLifecycleState(str, Enum):
    """Explicit 3-phase capital lifecycle state consumed by allocation decisions.

    Phases
    ------
    INITIALIZING
        No snapshot has been published yet.  ``total_capital`` is ``0.0`` but
        is meaningless — the authority has not seen real broker data.

    HYDRATED_ZERO_CAPITAL
        At least one snapshot has been published by the coordinator, but the
        confirmed balance is zero.  The system is initialised and the data is
        real; the account is simply empty.

    ACTIVE_CAPITAL
        The coordinator has published at least one snapshot with a positive
        ``real_capital`` value **and** all expected brokers have contributed
        (no partial aggregation in flight).  Trading decisions may proceed.
    """

    INITIALIZING = "INITIALIZING"
    HYDRATED_ZERO_CAPITAL = "HYDRATED_ZERO_CAPITAL"
    ACTIVE_CAPITAL = "ACTIVE_CAPITAL"


def get_capital_system_gate() -> threading.Event:
    """Return the process-wide ``CAPITAL_SYSTEM_READY`` :class:`threading.Event`.

    The event transitions from *unset* to *set* exactly once: the first time
    :meth:`CapitalAuthority.publish_snapshot` receives a snapshot whose
    ``real_capital > 0`` **and** whose ``broker_count`` meets or exceeds
    ``expected_brokers`` (confirming no partial broker aggregation is in
    flight).  It is **never** cleared after being set.

    This means the event corresponds to the
    :attr:`CapitalLifecycleState.ACTIVE_CAPITAL` state, not merely to the
    first hydration.  Callers that need to detect the earlier
    :attr:`CapitalLifecycleState.HYDRATED_ZERO_CAPITAL` state should check
    :attr:`CapitalAuthority.is_hydrated` directly.

    Callers that only need a non-blocking check should use::

        if not get_capital_system_gate().is_set():
            return CapitalLifecycleState.INITIALIZING

    Callers that want to block until active capital is confirmed::

        get_capital_system_gate().wait(timeout=30)
    """
    return CAPITAL_SYSTEM_READY


def get_capital_hydrated_gate() -> threading.Event:
    """Return the process-wide ``CAPITAL_HYDRATED_EVENT`` :class:`threading.Event`.

    The event transitions from *unset* to *set* exactly once: the first time
    :meth:`CapitalAuthority.publish_snapshot` sets ``_hydrated = True``.
    Unlike :data:`CAPITAL_SYSTEM_READY` this does **not** require a positive
    balance — it fires as soon as the coordinator has published any snapshot
    (including a zero-balance one), confirming that balance has been fetched.

    Use this gate when you need to know that the capital pipeline has run at
    least once (FIX 4), rather than that it has confirmed positive capital.
    """
    return CAPITAL_HYDRATED_EVENT


def get_startup_lock() -> threading.Event:
    """Return the process-wide ``STARTUP_LOCK`` :class:`threading.Event`.

    The event transitions from *unset* to *set* exactly once, via
    :func:`finalize_bootstrap_ready` / :meth:`CapitalAuthority.finalize_bootstrap_ready`,
    and is **never** cleared after being set.

    It is SEPARATE from the broker-registration gate
    (:attr:`CapitalAuthority._broker_registration_complete`) and from
    :data:`CAPITAL_SYSTEM_READY`.  This lock ensures that **no capital
    evaluation** (allocation plans, authority refreshes triggered by consumers)
    can proceed during the broker-stabilization window — i.e. the period
    between broker registration completing and the first confirmed stable
    capital snapshot being published.

    Usage::

        from capital_authority import get_startup_lock

        if not get_startup_lock().is_set():
            return  # HARD BLOCK — startup not complete
    """
    return STARTUP_LOCK


def wait_for_hydration(timeout_s: float = 30.0) -> None:
    """Block until CapitalAuthority confirms at least one broker snapshot.

    This is the canonical **capital hydration barrier** — call it once at
    startup *before* entering the AUTO trading loop.  It guarantees that
    :attr:`CapitalAuthority.is_hydrated` is ``True`` (and therefore
    :data:`CAPITAL_HYDRATED_EVENT` is set) before any downstream
    capital-dependent logic runs, eliminating the race condition where the
    strategy loop evaluates capital before any broker balance has been fetched.

    Parameters
    ----------
    timeout_s:
        Maximum seconds to block.  Default: 30 s (matches the bootstrap
        barrier used elsewhere in the pipeline).

    Raises
    ------
    CapitalIntegrityError
        If :data:`CAPITAL_HYDRATED_EVENT` is not set within *timeout_s*
        seconds.  The trading loop must not start until this barrier clears.
    """
    acquired = CAPITAL_HYDRATED_EVENT.wait(timeout=timeout_s)
    if not acquired:
        raise CapitalIntegrityError(
            f"Capital hydration barrier timed out after {timeout_s}s — "
            "CapitalAuthority has not received a broker snapshot. "
            "Check broker connectivity and credentials, then restart."
        )
    logger.info(
        "[CapitalAuthority] wait_for_hydration: barrier cleared — "
        "CAPITAL_HYDRATED_EVENT is set, is_hydrated confirmed."
    )


# ---------------------------------------------------------------------------
# Singleton state
# ---------------------------------------------------------------------------

_authority_instance: Optional["CapitalAuthority"] = None
_authority_lock = threading.Lock()

# Identity guard — set to id() of the first CapitalAuthority created so that
# any accidental second instantiation can be detected immediately.
_EXPECTED_ID: Optional[int] = None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _ensure_utc(dt: datetime) -> datetime:
    """Return *dt* as a timezone-aware UTC datetime.

    Timezone-naive datetimes are assumed to already represent UTC and are
    given an explicit ``timezone.utc`` tzinfo.  Aware datetimes are returned
    unchanged.
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


# ---------------------------------------------------------------------------
# Public classes
# ---------------------------------------------------------------------------


class CapitalAuthority:
    """
    Process-wide authority for all capital figures.

    Callers should obtain the singleton via :func:`get_capital_authority`
    rather than instantiating this class directly.
    """

    def __init__(self) -> None:
        # RLock allows the same thread to re-acquire (e.g. refresh() holds the
        # lock and calls get_real_capital() which also acquires it).
        self._lock = threading.RLock()
        self.broker_manager: Optional[Any] = None
        self._reserve_pct: float = float(
            os.environ.get("NIJA_CAPITAL_RESERVE_PCT", str(_DEFAULT_RESERVE_PCT))
        )
        # Per-broker raw balances: broker_id → USD balance
        self._broker_balances: Dict[str, float] = {}
        # Per-broker roles: broker_id → BROKER_ROLE_* constant
        # "primary"  = authoritative (Kraken, etc.) — counts for global minimum
        # "isolated" = NANO/sandbox (Coinbase) — cannot block startup or AI hub
        self._broker_roles: Dict[str, str] = {}
        # Registered open-position exposure in USD (updated by callers)
        self._open_exposure_usd: float = 0.0
        # Last total explicitly provided through update(total_capital).
        self._last_updated_total: float = 0.0
        # Timestamp of most-recent successful refresh
        self.last_updated: Optional[datetime] = None
        # Minimum number of brokers that must have contributed a non-zero balance
        # for the snapshot to be considered complete.  Automatically raised by
        # refresh() to match the largest broker map seen so far.  Can also be set
        # explicitly at startup via set_expected_brokers() once the broker map is
        # known.  The env var NIJA_CAPITAL_EXPECTED_BROKERS is an advanced override
        # intended for multi-process deployments; in normal operation the value is
        # derived at runtime and this env var should not be needed.
        # Default: require at least 2 brokers before signalling ACTIVE_CAPITAL,
        # preventing a false-positive READY when only one broker has connected.
        # Override: set NIJA_SINGLE_BROKER_MODE=true (or NIJA_CAPITAL_EXPECTED_BROKERS=1)
        # to allow a single-broker deployment to reach READY.
        _single_broker_mode: bool = os.environ.get(
            "NIJA_SINGLE_BROKER_MODE", ""
        ).strip().lower() in {"1", "true", "yes", "on"}
        _explicit_expected: str = os.environ.get("NIJA_CAPITAL_EXPECTED_BROKERS", "").strip()
        if _explicit_expected:
            self._expected_brokers: int = int(_explicit_expected)
        elif _single_broker_mode:
            self._expected_brokers: int = 1
        else:
            self._expected_brokers: int = 2
        # Opportunistic mode: when True, ACTIVE_CAPITAL is reached (and
        # CAPITAL_SYSTEM_READY is set) as soon as ≥1 broker reports a positive
        # balance, without waiting for all expected_brokers to connect.
        # Useful when broker connectivity is unreliable at startup — trading
        # begins with a partial (but positive) capital picture.
        # Set via env var NIJA_CAPITAL_OPPORTUNISTIC (accepted: "1", "true", "yes")
        # or programmatically via set_opportunistic().
        self._opportunistic: bool = os.environ.get(
            "NIJA_CAPITAL_OPPORTUNISTIC", "false"
        ).strip().lower() in ("1", "true", "yes")
        # Maximum age for retaining a previous non-zero balance when a refresh
        # call returns zero/errors (prevents indefinite stale-capital retention).
        self._preserve_nonzero_ttl_s: float = float(
            os.environ.get("NIJA_CAPITAL_PRESERVE_TTL_S", "180.0")
        )
        # Last typed snapshot published via publish_snapshot().  None until
        # the coordinator has run at least once.
        self._last_typed_snapshot: Optional[Any] = None
        # Hydration flag — set to True after the first valid snapshot is
        # published via publish_snapshot().  Callers that need to distinguish
        # "authority not yet initialised" from "authority initialised with a
        # zero balance" should check this flag before reading total_capital.
        self._hydrated: bool = False
        # Per-broker timestamps for the feed_broker_balance push path.
        # Monotonic guard: only advance a broker's balance when the incoming
        # feed timestamp is strictly newer than the recorded one.
        self._broker_feed_timestamps: Dict[str, datetime] = {}
        # Registered balance-feed callables: broker_id → callable() → float|dict
        # Populated by register_source() at broker-ready time.
        self._balance_feeds: Dict[str, Callable[[], Any]] = {}
        # ── Broker registration hard gate ─────────────────────────────────────
        # Mirrors the event on MultiAccountBrokerManager.  Set exactly once via
        # finalize_broker_registration() (called by MABM.finalize_broker_registration).
        # feed_broker_balance() is hard-gated and requires both:
        #   1) broker registration complete event is set
        #   2) broker_key was registered via register_source()
        self._broker_registration_complete: threading.Event = threading.Event()
        # ── Global startup lock — "NO EVALUATION BEFORE READY" ────────────────
        # References the module-level STARTUP_LOCK event.  Set exactly once via
        # finalize_bootstrap_ready() AFTER all of the following are confirmed:
        # brokers registered, broker list stable in CA, first feed batch
        # processed, FSM initialized.  Nothing is allowed to evaluate capital
        # (trigger refreshes, produce allocation plans) until this is set.
        self._startup_lock: threading.Event = STARTUP_LOCK
        # Legacy queue retained only for backward-compatibility with callers
        # that inspect the field. New flow is hard-gated (no pre-registration queue).
        self._pending_feeds: List[Tuple[str, float, datetime]] = []
        # ── CSM v3 — warm-start flag ───────────────────────────────────────────
        # True when this instance was pre-populated from the on-disk state cache
        # (i.e. no live API call was needed to reach HYDRATED / ACTIVE_CAPITAL).
        # Cleared to False the first time a live snapshot is published via
        # publish_snapshot() or a live refresh completes successfully.
        self._warm_start: bool = False
        # Maximum age (seconds) of a saved state file accepted for warm-start.
        # Override with NIJA_CAPITAL_STATE_MAX_AGE_S env var.
        self._state_max_age_s: float = float(
            os.environ.get("NIJA_CAPITAL_STATE_MAX_AGE_S", str(_DEFAULT_STATE_MAX_AGE_S))
        )
        # Register this instance in the module-level identity guard so that any
        # accidental second instantiation is detected by assert_singleton().
        global _EXPECTED_ID
        if _EXPECTED_ID is None:
            _EXPECTED_ID = id(self)
        logger.info("[CapitalAuthority] instance_id=%d", id(self))

        # ── CSM v3 — attempt warm-start from persisted state ──────────────────
        self._load_cached_state()

    # ------------------------------------------------------------------
    # Lock helper
    # ------------------------------------------------------------------

    @contextmanager
    def _timed_lock(self, timeout: float = 5.0):
        """Acquire ``self._lock`` with a deadline.

        Raises :class:`RuntimeError` if the lock cannot be obtained within
        *timeout* seconds, which surfaces potential deadlock conditions rather
        than blocking indefinitely.
        """
        acquired = self._lock.acquire(timeout=timeout)
        if not acquired:
            raise RuntimeError(
                f"CapitalAuthority lock acquisition timed out after {timeout}s — possible deadlock"
            )
        try:
            yield
        finally:
            self._lock.release()

    # ------------------------------------------------------------------
    # Singleton identity guard
    # ------------------------------------------------------------------

    def assert_singleton(self) -> None:
        """Raise RuntimeError if this instance is not the registered singleton.

        Call this at the top of any write path (``refresh``, ``publish_snapshot``)
        to detect silent divergence caused by accidental second instantiation.
        """
        global _EXPECTED_ID
        if _EXPECTED_ID is None:
            _EXPECTED_ID = id(self)
        elif _EXPECTED_ID != id(self):
            raise RuntimeError(
                f"CapitalAuthority instance mismatch detected — "
                f"expected id={_EXPECTED_ID}, got id={id(self)}"
            )

    # ------------------------------------------------------------------
    # CSM v3 — persistent capital state (warm-start)
    # ------------------------------------------------------------------

    @property
    def warm_start(self) -> bool:
        """``True`` when this instance was pre-populated from the on-disk state
        cache at startup (CSM v3 warm-start).  Transitions to ``False`` the
        first time a live snapshot is successfully published or a live
        ``refresh()`` completes, confirming the authority now holds
        broker-validated data.

        Callers may use this flag to differentiate cached startup capital from
        live-confirmed capital, e.g. to emit a warning in dashboards.
        """
        return self._warm_start

    def _save_cached_state(self) -> None:
        """Persist the current broker balances and metadata to disk.

        Called automatically after every successful :meth:`publish_snapshot`
        and :meth:`refresh`.  The file is written atomically (write to a
        temporary file then rename) to avoid partial-write corruption.

        Silently swallows all errors — a failed save must never interrupt the
        trading pipeline.
        """
        try:
            _STATE_DIR.mkdir(parents=True, exist_ok=True)
            with self._lock:
                balances = dict(self._broker_balances)
                roles = dict(self._broker_roles)
                last_updated_iso = (
                    self.last_updated.isoformat() if self.last_updated is not None else None
                )
                expected = self._expected_brokers

            if not balances:
                return

            payload = {
                "schema_version": _STATE_SCHEMA_VERSION,
                "broker_balances": balances,
                "broker_roles": roles,
                "last_updated": last_updated_iso,
                "expected_brokers": expected,
                "saved_at": datetime.now(timezone.utc).isoformat(),
            }
            # Use a unique temp file per save call to avoid cross-thread races
            # when multiple snapshots are persisted in quick succession.
            fd, tmp_path = tempfile.mkstemp(
                dir=str(_STATE_DIR),
                prefix="capital_authority_state.",
                suffix=".tmp",
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    json.dump(payload, fh, indent=2)
                    fh.flush()
                    os.fsync(fh.fileno())
                os.replace(tmp_path, _STATE_FILE)
            finally:
                # If replace() failed, remove the temp file best-effort.
                if os.path.exists(tmp_path):
                    try:
                        os.remove(tmp_path)
                    except Exception:
                        pass
            logger.debug(
                "[CapitalAuthority] CSM v3 state saved — brokers=%s real=$%.2f",
                sorted(balances.keys()),
                sum(balances.values()),
            )
        except Exception as exc:
            logger.warning("[CapitalAuthority] CSM v3 state save failed (non-fatal): %s", exc)

    def _load_cached_state(self) -> bool:
        """Attempt to restore the last valid capital state from disk.

        Called once from :meth:`__init__`.  On success:

        * ``_broker_balances`` is pre-populated with the saved figures.
        * ``_broker_roles`` is restored so role-gated capital accessors work
          immediately.
        * ``_hydrated`` is set to ``True`` and :data:`CAPITAL_HYDRATED_EVENT`
          is fired so ``block_until_hydrated()`` returns without blocking.
        * When the restored capital is positive and the broker threshold is met,
          :data:`CAPITAL_SYSTEM_READY` is also set, allowing
          ``wait_for_capital_ready()`` to return instantly.
        * ``_warm_start`` is set to ``True`` to mark that data came from cache.

        The monotonic-timestamp guard in :meth:`publish_snapshot` and
        :meth:`feed_broker_balance` ensures that live data arriving shortly
        after startup always overwrites the cached figures because the live
        timestamp is strictly newer than the stored ``last_updated``.

        Returns
        -------
        bool
            ``True`` if warm-start succeeded; ``False`` otherwise (cold start).
        """
        if self._state_max_age_s <= 0.0:
            logger.debug("[CapitalAuthority] CSM v3 warm-start disabled (max_age=0)")
            return False

        if not _STATE_FILE.exists():
            logger.debug("[CapitalAuthority] CSM v3 no state file found — cold start")
            return False

        try:
            with open(_STATE_FILE, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception as exc:
            logger.warning("[CapitalAuthority] CSM v3 state file unreadable — cold start: %s", exc)
            return False

        # Schema version guard — reject files from incompatible older releases.
        if data.get("schema_version", 0) != _STATE_SCHEMA_VERSION:
            logger.warning(
                "[CapitalAuthority] CSM v3 state file schema mismatch "
                "(file=%s expected=%d) — cold start",
                data.get("schema_version"),
                _STATE_SCHEMA_VERSION,
            )
            return False

        # Age check — reject state older than _state_max_age_s.
        saved_at_raw = data.get("saved_at")
        if saved_at_raw is None:
            logger.warning("[CapitalAuthority] CSM v3 state file missing 'saved_at' — cold start")
            return False

        try:
            saved_at = _ensure_utc(datetime.fromisoformat(saved_at_raw))
        except Exception as exc:
            logger.warning("[CapitalAuthority] CSM v3 invalid 'saved_at' — cold start: %s", exc)
            return False

        age_s = (datetime.now(timezone.utc) - saved_at).total_seconds()
        if age_s > self._state_max_age_s:
            logger.info(
                "[CapitalAuthority] CSM v3 state file expired (age=%.0fs > max=%.0fs) — cold start",
                age_s,
                self._state_max_age_s,
            )
            return False

        # Validate broker balances — skip any entry whose value cannot be
        # safely converted to float (guards against corrupted or hand-edited files).
        broker_balances: Dict[str, float] = {}
        for k, v in data.get("broker_balances", {}).items():
            if v is None:
                continue
            try:
                broker_balances[str(k)] = float(v)
            except (TypeError, ValueError):
                logger.warning(
                    "[CapitalAuthority] CSM v3 skipping invalid balance for broker=%s value=%r",
                    k,
                    v,
                )
        if not broker_balances:
            logger.info("[CapitalAuthority] CSM v3 state file has no broker balances — cold start")
            return False

        broker_roles: Dict[str, str] = {
            str(k): str(v)
            for k, v in data.get("broker_roles", {}).items()
        }

        last_updated_raw = data.get("last_updated")
        last_updated: Optional[datetime] = None
        if last_updated_raw:
            try:
                last_updated = _ensure_utc(datetime.fromisoformat(last_updated_raw))
            except Exception:
                last_updated = None

        saved_expected_brokers: int = int(data.get("expected_brokers", 1))

        # All checks passed — apply cached state under the lock.
        with self._lock:
            self._broker_balances = broker_balances
            self._broker_roles = broker_roles
            if last_updated is not None:
                self.last_updated = last_updated
                # Stamp feed timestamps with the same value so the monotonic
                # guard in feed_broker_balance rejects feeds older than cache.
                for bk in broker_balances:
                    self._broker_feed_timestamps[bk] = last_updated
            if saved_expected_brokers > self._expected_brokers:
                self._expected_brokers = saved_expected_brokers
            self._hydrated = True
            self._warm_start = True

        # Fire CAPITAL_HYDRATED_EVENT so block_until_hydrated() returns instantly.
        CAPITAL_HYDRATED_EVENT.set()

        # Fire CAPITAL_SYSTEM_READY if the restored capital meets ACTIVE_CAPITAL
        # conditions (positive balance + broker threshold).
        real_capital = sum(broker_balances.values())
        broker_threshold = 1 if self._opportunistic else max(1, self._expected_brokers)
        if real_capital > 0.0 and len(broker_balances) >= broker_threshold:
            CAPITAL_SYSTEM_READY.set()
            logger.info(
                "⚡ [CapitalAuthority] CSM v3 WARM START — "
                "restored real=$%.2f from cache (age=%.1fs, brokers=%s)",
                real_capital,
                age_s,
                sorted(broker_balances.keys()),
            )
        else:
            logger.info(
                "[CapitalAuthority] CSM v3 warm start (zero capital) — "
                "brokers=%s age=%.1fs",
                sorted(broker_balances.keys()),
                age_s,
            )

        return True

    def clear_cached_state(self) -> None:
        """Delete the on-disk capital state file (if it exists).

        Use this in tests or after a deliberate balance reset to prevent the
        next startup from loading stale cached data.  This method is safe to
        call at any time — it silently ignores the case where the file does not
        exist.
        """
        try:
            if _STATE_FILE.exists():
                _STATE_FILE.unlink()
                logger.info("[CapitalAuthority] CSM v3 state cache cleared")
        except Exception as exc:
            logger.warning("[CapitalAuthority] CSM v3 failed to clear state cache: %s", exc)

    # ------------------------------------------------------------------
    # Broker registration hard gate
    # ------------------------------------------------------------------

    def finalize_broker_registration(self) -> None:
        """Lift the broker-registration gate.

        Called automatically by
        :meth:`~bot.multi_account_broker_manager.MultiAccountBrokerManager.finalize_broker_registration`
        once all platform and user brokers have been registered.  May also be
        called directly in test scenarios.

                After this method returns, :meth:`feed_broker_balance` accepts live
                feeds only for sources already registered via :meth:`register_source`.
        """
        if self._broker_registration_complete.is_set():
            logger.debug("[CapitalAuthority] finalize_broker_registration: already complete — no-op")
            return
        self._broker_registration_complete.set()
        with self._lock:
            self._pending_feeds.clear()
        logger.info("[CapitalAuthority] Broker registration gate lifted")

    def is_registered(self, broker_id: str) -> bool:
        """Return True when *broker_id* has been registered via register_source()."""
        key = str(broker_id)
        with self._lock:
            return key in self._balance_feeds

    def wait_until_registered(self, broker_id: str, timeout_s: float = 5.0) -> bool:
        """Wait briefly for broker registration to complete and include *broker_id*."""
        key = str(broker_id)
        deadline = time.monotonic() + max(0.1, float(timeout_s))
        while time.monotonic() < deadline:
            if self._broker_registration_complete.is_set() and self.is_registered(key):
                return True
            time.sleep(0.05)
        return self._broker_registration_complete.is_set() and self.is_registered(key)

    # ------------------------------------------------------------------
    # Global startup lock — full system sync gate
    # ------------------------------------------------------------------

    def finalize_bootstrap_ready(self) -> None:
        """Release the global startup lock to permit capital evaluation.

        This is the **final** step in the bootstrap sequence.  It must be
        called ONLY after ALL of the following are confirmed:

        1. All expected brokers have been registered
           (:meth:`finalize_broker_registration` has been called).
        2. The broker list is reflected in this :class:`CapitalAuthority`
           (pending feeds have been flushed).
        3. The first feed batch has been processed (or confirmed empty-safe).
        4. The capital bootstrap FSM has been initialised.

        Calling this method sets :data:`STARTUP_LOCK` which allows
        :meth:`refresh` and :class:`~bot.capital_allocation_brain.CapitalAllocationBrain`
        evaluation paths to proceed.  The event is a one-way latch — it is
        **never** cleared after being set.

        The canonical caller is
        :meth:`~bot.multi_account_broker_manager.MultiAccountBrokerManager.finalize_bootstrap_ready`,
        which verifies the above conditions before delegating here.  This
        method may also be called directly in test scenarios.
        """
        if self._startup_lock.is_set():
            logger.debug(
                "[CapitalAuthority] finalize_bootstrap_ready: startup lock already set — no-op"
            )
            return
        self._startup_lock.set()
        logger.warning(
            "✅ [CapitalAuthority] STARTUP LOCK RELEASED — full system sync confirmed, "
            "capital evaluation now permitted"
        )

    # ------------------------------------------------------------------
    # Core refresh
    # ------------------------------------------------------------------

    def refresh(
        self,
        broker_map: Dict[str, Any],
        open_exposure_usd: float = 0.0,
        _bypass_startup_lock: bool = False,
    ) -> None:
        """
        Pull live balances from all brokers in *broker_map* and update the
        internal snapshot.

        Parameters
        ----------
        broker_map:
            ``{broker_id: broker_instance}`` for every connected broker.
            Each broker must expose ``get_account_balance()`` which returns
            either a ``float`` (preferred) or a ``dict`` containing a
            ``"trading_balance"`` key.
        open_exposure_usd:
            Sum of all open-position notional values in USD.  Pass 0.0 (or
            omit) when the caller does not yet have position data.
        _bypass_startup_lock:
            Internal bootstrap escape hatch.  Pass ``True`` ONLY from
            :meth:`MultiAccountBrokerManager.refresh_capital_authority`'s
            coordinator-unavailable fallback path, where the coordinator
            cannot use :meth:`publish_snapshot` and must fall back to direct
            refresh to build the initial snapshot.  All external callers must
            leave this ``False`` (the default).
        """
        self.assert_singleton()
        if not self._startup_lock.is_set() and not _bypass_startup_lock:
            logger.warning(
                "[CapitalAuthority] Startup lock not released — allowing refresh, blocking decisions"
            )
        try:
            from bot.multi_account_broker_manager import get_broker_manager
        except ImportError:
            try:
                from multi_account_broker_manager import get_broker_manager  # type: ignore
            except Exception as exc:
                raise RuntimeError(
                    "CapitalAuthority refresh requires get_broker_manager() for broker registry integrity"
                ) from exc
        except Exception as exc:
            raise RuntimeError(
                "CapitalAuthority refresh failed while resolving get_broker_manager() (unexpected import error)"
            ) from exc

        canonical_broker_manager = get_broker_manager()
        if self.broker_manager is None:
            self.broker_manager = canonical_broker_manager
        if self.broker_manager is not canonical_broker_manager:
            raise RuntimeError("BROKER MANAGER INSTANCE MISMATCH (CRITICAL)")
        assert self.broker_manager is canonical_broker_manager, \
            "BROKER MANAGER INSTANCE MISMATCH (CRITICAL)"
        has_registered_sources = False
        if hasattr(self.broker_manager, "has_registered_sources"):
            try:
                has_registered_sources = bool(self.broker_manager.has_registered_sources())
            except Exception as exc:
                logger.warning("CapitalAuthority could not verify broker registry source hydration: %s", exc)
        used_hydration_fallback = False
        if not has_registered_sources:
            try:
                self.broker_manager.refresh_registry()
                used_hydration_fallback = True
            except Exception as exc:
                raise RuntimeError(
                    "CapitalAuthority refresh could not rehydrate broker registry (CRITICAL)"
                ) from exc

        startup_barrier_started_at = getattr(
            self.broker_manager,
            "_capital_bootstrap_barrier_started_at",
            None,
        )
        startup_timeout_s = float(
            getattr(self.broker_manager, "capital_startup_invariant_timeout_s", 0.0) or 0.0
        )
        startup_window_open = False
        if startup_barrier_started_at is not None and startup_timeout_s > 0.0:
            startup_window_open = (
                (time.monotonic() - float(startup_barrier_started_at)) < startup_timeout_s
            )

        if hasattr(self.broker_manager, "has_registered_sources"):
            registry_hydrated = bool(self.broker_manager.has_registered_sources())
        else:
            registry_hydrated = has_registered_sources or bool(broker_map)
        if used_hydration_fallback:
            logger.warning("⚠️ CapitalAuthority using fallback hydration — registry pipeline broken")
            if not startup_window_open:
                raise AssertionError(
                    "FATAL: CapitalAuthority fallback hydration invoked after startup window"
                )
        if not startup_window_open:
            assert registry_hydrated, \
                "FATAL: Broker registry not hydrated via primary pipeline"
        if not broker_map:
            if startup_window_open:
                logger.warning(
                    "⏳ CapitalAuthority refresh deferred during startup: no registered broker payload sources yet"
                )
                return
            raise AssertionError(
                "FATAL: CapitalAuthority refresh called with empty broker_map after startup window"
            )

        def normalize_broker_identifier(identifier: Any) -> str:
            """Normalize enum-backed or string broker identifiers to plain strings."""
            if hasattr(identifier, "value"):
                return str(identifier.value)
            return str(identifier)

        effective_broker_map: Dict[str, Any] = dict(broker_map or {})
        if not effective_broker_map:
            try:
                platform_brokers = getattr(canonical_broker_manager, "platform_brokers", None) or {}
                if isinstance(platform_brokers, Mapping):
                    for broker_identifier, broker in platform_brokers.items():
                        if broker is None:
                            continue
                        broker_key = normalize_broker_identifier(broker_identifier)
                        effective_broker_map[broker_key] = broker
                if effective_broker_map:
                    logger.info(
                        "[CapitalAuthority] refresh hydrated source graph from broker registry: brokers=%s",
                        sorted(effective_broker_map.keys()),
                    )
            except Exception as exc:
                logger.warning(
                    "[CapitalAuthority] refresh failed to hydrate broker sources from registry: %s",
                    exc,
                )

        new_balances: Dict[str, float] = {}

        for broker_id, broker in effective_broker_map.items():
            if broker is None:
                continue
            broker_key = normalize_broker_identifier(broker_id)
            with self._timed_lock():
                previous = float(self._broker_balances.get(broker_key, 0.0))
                if self.last_updated is not None:
                    previous_age_s = (
                        datetime.now(timezone.utc) - self.last_updated
                    ).total_seconds()
                else:
                    # First refresh (or explicit reset): without a timestamp we
                    # cannot prove freshness, so preservation is intentionally
                    # disabled to avoid carrying unknown stale balances.
                    previous_age_s = float("inf")
            can_preserve_previous = (
                previous > 0.0 and previous_age_s <= self._preserve_nonzero_ttl_s
            )
            try:
                logger.info("[CapitalAuthority] Fetching balance for broker=%s", broker_id)
                raw = broker.get_account_balance()
                if isinstance(raw, dict):
                    logger.info(
                        "[CapitalAuthority] broker=%s raw balance fetched (dict keys=%s)",
                        broker_id,
                        sorted(raw.keys()),
                    )
                else:
                    logger.info(
                        "[CapitalAuthority] broker=%s raw balance fetched (scalar=%s)",
                        broker_id,
                        raw,
                    )
                if isinstance(raw, dict):
                    # Prefer trading_balance; fall back to usd + usdc
                    balance = float(
                        raw.get("trading_balance")
                        or raw.get("total_funds")
                        or (raw.get("usd", 0.0) + raw.get("usdc", 0.0))
                        or 0.0
                    )
                elif raw is not None:
                    balance = float(raw)
                else:
                    balance = 0.0
                logger.info(
                    "[CapitalAuthority] broker=%s parsed balance=$%.2f",
                    broker_id,
                    balance,
                )

                if balance > 0.0:
                    new_balances[broker_key] = balance
                    logger.debug(
                        "[CapitalAuthority] broker=%s balance=$%.2f",
                        broker_id,
                        balance,
                    )
                elif can_preserve_previous:
                    # Hard capital-truth contract: never let a transient zero read
                    # wipe an already-validated non-zero balance snapshot.
                    new_balances[broker_key] = previous
                    logger.warning(
                        "[CapitalAuthority] broker=%s returned non-positive balance (%.2f) — "
                        "preserving previous non-zero balance=$%.2f",
                        broker_id,
                        balance,
                        previous,
                    )
                else:
                    # FIX 3: store zero instead of skipping — zero is a valid
                    # confirmed balance (empty account is not an error).  This
                    # ensures the broker appears in the snapshot so that
                    # is_hydrated / CAPITAL_HYDRATED_EVENT fire correctly.
                    new_balances[broker_key] = 0.0
                    logger.debug(
                        "[CapitalAuthority] broker=%s confirmed at $0.00 — stored as zero balance",
                        broker_id,
                    )
            except Exception as exc:
                if can_preserve_previous:
                    # Contract fail-closed path: retain last known good capital on
                    # fetch errors to avoid phantom-zero state transitions.
                    new_balances[broker_key] = previous
                    logger.warning(
                        "[CapitalAuthority] Failed to fetch balance for broker=%s (%s) — "
                        "preserving previous non-zero balance=$%.2f",
                        broker_id,
                        exc,
                        previous,
                    )
                else:
                    logger.warning(
                        "[CapitalAuthority] Failed to fetch balance for broker=%s: %s",
                        broker_id,
                        exc,
                    )

        if not new_balances:
            logger.warning(
                "[CapitalAuthority] refresh produced no broker balances; keeping prior state and staying stale"
            )
            return

        with self._timed_lock():
            self._broker_balances = new_balances
            self._open_exposure_usd = max(0.0, float(open_exposure_usd))
            self.last_updated = datetime.now(timezone.utc)
            # Auto-raise expected_brokers to match the largest map we have seen
            # so that a future refresh with fewer brokers fails the is_fresh() check.
            if len(new_balances) > self._expected_brokers:
                self._expected_brokers = len(new_balances)

            # First successful refresh should hydrate the authority so that
            # CA_READY checks can distinguish "snapshot not yet received"
            # from "snapshot received with zero capital".
            if not self._hydrated and len(new_balances) > 0:
                self._hydrated = True
                CAPITAL_HYDRATED_EVENT.set()
                logger.info(
                    "[CapitalAuthority] refresh committed hydration — "
                    "is_hydrated=%s",
                    self._hydrated,
                )

            # Signal ACTIVE_CAPITAL readiness when the refreshed state meets
            # the same conditions used by publish_snapshot().
            snapshot_real_capital = self.get_real_capital()
            snapshot_broker_count = len(new_balances)
            broker_threshold = 1 if self._opportunistic else max(1, self._expected_brokers)
            if snapshot_real_capital > 0.0 and snapshot_broker_count >= broker_threshold:
                CAPITAL_SYSTEM_READY.set()
                logger.info(
                    "[CapitalAuthority] refresh reached ACTIVE_CAPITAL; "
                    "CAPITAL_SYSTEM_READY=%s",
                    CAPITAL_SYSTEM_READY.is_set(),
                )

        logger.info(
            "[CapitalAuthority] refreshed — real=$%.2f usable=$%.2f risk=$%.2f "
            "(brokers=%d reserve=%.0f%%)",
            self.get_real_capital(),
            self.get_usable_capital(),
            self.get_risk_capital(),
            len(new_balances),
            self._reserve_pct * 100,
        )
        # ── Validation snapshot — exposes feed / aggregation issues instantly ──
        logger.info(
            "[CA VALIDATION] total=$%.2f | brokers=%d | values=%s",
            self.get_real_capital(),
            len(new_balances),
            dict(new_balances),
        )
        # CSM v3 — persist live-refreshed state to disk.
        self._warm_start = False
        self._save_cached_state()

    def update(self, total_capital: float) -> None:
        """
        Explicitly update the aggregate capital snapshot.

        Parameters
        ----------
        total_capital:
            Aggregate account capital in USD after broker-level balance refresh
            and conversion.
        """
        total = max(0.0, float(total_capital))
        with self._lock:
            self._last_updated_total = total
            self.last_updated = datetime.now(timezone.utc)
        logger.info("CapitalAuthority updated: $%.2f", total)

    # ------------------------------------------------------------------
    # Open-exposure registry (call each cycle before reading risk_capital)
    # ------------------------------------------------------------------

    def register_open_exposure(self, open_exposure_usd: float) -> None:
        """Update the total open-position exposure without triggering a full refresh."""
        with self._lock:
            self._open_exposure_usd = max(0.0, float(open_exposure_usd))

    def feed_broker_balance(
        self,
        broker_key: str,
        balance: float,
        timestamp: Optional[datetime] = None,
    ) -> None:
        """
        Inject a freshly-fetched balance for a single broker directly into the
        authority without issuing an additional broker API call.

        This is the lightweight push-path used by :class:`BalanceService` so
        that every successful ``BalanceService.refresh()`` automatically keeps
        the authority current.  The authority's ``last_updated`` timestamp is
        refreshed on every call so ``is_stale()`` reflects the most recent feed.

        Concurrency contract
        --------------------
        To prevent flicker under concurrent feeds the method enforces a
        per-broker monotonic-timestamp rule:

        * **New broker** (key not yet registered): the balance is stored
          unconditionally and the feed timestamp is recorded.
        * **Existing broker**: the balance is updated **only** when
          *timestamp* is strictly newer than the stored feed timestamp.
          Out-of-order or duplicate feeds are silently dropped.

        Parameters
        ----------
        broker_key:
            Logical broker identifier (e.g. ``"coinbase"`` or ``"kraken"``).
        balance:
            Raw USD balance for this broker (positive values only; zero and
            negative values are silently ignored so a bad API response cannot
            wipe out a previously valid balance).
        timestamp:
            Wall-clock time at which the balance was observed.  Defaults to
            ``datetime.now(timezone.utc)`` when omitted.
        """
        key = str(broker_key)
        balance = float(balance)
        if balance <= 0.0:
            logger.debug(
                "[CapitalAuthority] feed_broker_balance: broker=%s balance=$%.2f — ignored",
                key,
                balance,
            )
            return
        # Normalize to UTC to prevent TypeError on comparison with existing
        # timestamps (which are always timezone-aware).
        if timestamp is not None:
            ts: datetime = _ensure_utc(timestamp)
        else:
            ts = datetime.now(timezone.utc)

        # ── Broker registration hard gate ─────────────────────────────────────
        # Feed order is strict: register_source() must happen first.
        if not self._broker_registration_complete.is_set():
            raise RuntimeError(
                f"CapitalAuthority feed rejected for broker={key}: broker registration gate not complete"
            )
        if not self.is_registered(key):
            raise RuntimeError(
                f"CapitalAuthority feed rejected for broker={key}: source not registered"
            )

        with self._lock:
            existing_ts = self._broker_feed_timestamps.get(key)
            if existing_ts is not None and ts <= existing_ts:
                # Out-of-order or duplicate feed — drop.
                # Equal timestamps are treated as duplicates: clock jitter or
                # a rapid double-write of the same observation is not an
                # authoritative update and should not overwrite the recorded value.
                logger.debug(
                    "[CapitalAuthority] feed DROPPED broker=%s ts=%s existing_ts=%s",
                    key,
                    ts.isoformat(),
                    existing_ts.isoformat(),
                )
                return
            is_new = key not in self._broker_balances
            self._broker_balances[key] = balance
            self._broker_feed_timestamps[key] = ts
            self.last_updated = datetime.now(timezone.utc)
        logger.debug(
            "[CapitalAuthority] feed ACCEPTED broker=%s balance=$%.2f ts=%s (real=$%.2f)",
            key,
            balance,
            ts.isoformat(),
            sum(self._broker_balances.values()),
        )

    def force_accept_feed(
        self,
        broker_key: str,
        balance: float,
        timestamp: Optional[datetime] = None,
    ) -> None:
        """
        Force-accept a balance feed during bootstrap, bypassing the
        monotonic-timestamp guard in :meth:`feed_broker_balance`.

        FIX 2 / FIX 4 — Bootstrap bypass
        ------------------------------------
        The single-writer contract (``CapitalRefreshCoordinator``) is preserved
        for steady-state operation.  This method is *only* called by
        :class:`~bot.balance_service.BalanceService` during the bootstrap phase
        (i.e. when ``get_raw_per_broker(broker_key) == 0.0``) to guarantee that
        the very first successful balance fetch ALWAYS seeds the authority,
        regardless of coordinator readiness or FSM gate ordering.

        Parameters
        ----------
        broker_key:
            Logical broker identifier (same key used in feed_broker_balance).
        balance:
            Raw USD balance.  During bootstrap (before first hydration) a zero
            balance is accepted so that an unfunded but connected broker can
            still seed the authority and unblock the hydration gate.  Negative
            values are always ignored.
        timestamp:
            Wall-clock time of the observation.  Defaults to ``now(UTC)``.
        """
        key = str(broker_key)
        balance = float(balance)
        if balance < 0.0:
            logger.debug(
                "[CapitalAuthority] force_accept_feed: broker=%s balance=$%.2f — negative, ignored",
                key,
                balance,
            )
            return
        # After the authority is already hydrated, keep the positive-only contract
        # so that a transient zero read from a funded broker cannot wipe a valid
        # non-zero balance via this bypass path.  Before hydration, zero is a
        # legitimate "confirmed empty account" state and must be accepted so the
        # CAPITAL_HYDRATED_EVENT fires and downstream gates unblock.
        if balance == 0.0 and self._hydrated:
            logger.debug(
                "[CapitalAuthority] force_accept_feed: broker=%s balance=$0.00 — "
                "ignored post-hydration (use coordinator path for zero-balance updates)",
                key,
            )
            return
        ts = _ensure_utc(timestamp) if timestamp is not None else datetime.now(timezone.utc)
        with self._lock:
            self._broker_balances[key] = balance
            self._broker_feed_timestamps[key] = ts
            self.last_updated = datetime.now(timezone.utc)
        logger.info(
            "[CapitalAuthority] force_accept_feed ACCEPTED broker=%s balance=$%.2f "
            "(bootstrap bypass, real=$%.2f)",
            key,
            balance,
            sum(self._broker_balances.values()),
        )

    def register_source(self, broker_id: str, balance_feed: Callable[[], Any]) -> None:
        """Register a live balance-feed callable for *broker_id*.

        This is the single deterministic hook that must be called **exactly once
        per broker** as soon as that broker's connection is confirmed (i.e. the
        "broker-ready" event).  It records the feed so the authority can re-poll
        it on demand, and it immediately seeds the broker's initial balance by
        calling the feed once — guaranteeing that :meth:`has_registered_sources`
        returns ``True`` from this point forward.

        Duplicate calls (same *broker_id*) are safe and idempotent: the feed
        callable is simply overwritten with the new one and the balance is
        re-seeded.  This matches reconnect semantics where a fresh broker object
        replaces a stale one.

        Parameters
        ----------
        broker_id:
            Logical broker key (e.g. ``"kraken"`` or ``"alpaca"``).
        balance_feed:
            Zero-argument callable that returns the current balance for this
            broker.  The return value follows the same contract as
            ``broker.get_account_balance()``: either a ``float`` or a ``dict``
            containing a ``"trading_balance"`` / ``"usd"`` / ``"usdc"`` key.
            All broker implementations in ``broker_integration.py`` expose
            ``get_account_balance()``; pass it as ``broker.get_account_balance``
            (without parentheses).

        Usage
        -----
        ::

            authority.register_source("kraken", kraken_broker.get_account_balance)
            authority.register_source("alpaca", alpaca_broker.get_account_balance)
        """
        key = str(broker_id)
        with self._lock:
            self._balance_feeds[key] = balance_feed
        assert self.is_registered(key), f"CapitalAuthority source registration failed for broker={key}"
        logger.info("[CapitalAuthority] register_source: broker=%s feed registered", key)

        # Seed the initial balance immediately so downstream gates do not wait
        # for the next coordinator cycle.
        try:
            raw = balance_feed()
            if isinstance(raw, dict):
                balance = float(
                    raw.get("trading_balance")
                    or raw.get("total_funds")
                    or (raw.get("usd", 0.0) + raw.get("usdc", 0.0))
                    or 0.0
                )
            elif raw is not None:
                balance = float(raw)
            else:
                balance = 0.0
            seeded_now = False
            if self._broker_registration_complete.is_set():
                # FIX 3: seed even for zero balance — zero confirms balance was fetched.
                # The previous guard (if balance > 0) incorrectly blocked hydration
                # for accounts that are genuinely empty at startup.
                self.feed_broker_balance(key, balance)
                seeded_now = True
            else:
                logger.info(
                    "[CapitalAuthority] register_source: broker=%s registered; seed deferred until registration gate opens",
                    key,
                )
            if seeded_now and balance > 0.0:
                logger.info(
                    "[CapitalAuthority] register_source: broker=%s seeded balance=$%.2f",
                    key,
                    balance,
                )
            elif seeded_now:
                logger.info(
                    "[CapitalAuthority] register_source: broker=%s seeded with zero balance "
                    "(confirmed fetch — account empty at registration time)",
                    key,
                )
        except Exception as exc:
            logger.warning(
                "[CapitalAuthority] register_source: broker=%s initial balance fetch failed: %s "
                "— source registered without seeding",
                key,
                exc,
            )

    def set_broker_role(self, broker_id: str, role: str) -> None:
        """
        Tag a broker as ``"primary"`` (Kraken/authoritative) or
        ``"isolated"`` (Coinbase NANO / sandbox).

        This is the single chokepoint that prevents isolated broker capital
        from leaking into the global minimum check, the AI hub, and portfolio
        intelligence.  Call this once at startup after connecting each broker.

        Parameters
        ----------
        broker_id:
            The same key used in :meth:`feed_broker_balance` / :meth:`refresh`.
        role:
            :data:`BROKER_ROLE_PRIMARY` or :data:`BROKER_ROLE_ISOLATED`.
        """
        with self._lock:
            self._broker_roles[str(broker_id)] = role
        logger.info(
            "[CapitalAuthority] broker=%s role set to '%s'",
            broker_id,
            role,
        )

    # ------------------------------------------------------------------
    # Capital accessors
    # ------------------------------------------------------------------

    @property
    def total_capital(self) -> float:
        """
        Total observed equity across all registered brokers.

        When the coordinator has published at least one snapshot, returns
        ``_last_typed_snapshot.real_capital`` — the authoritative value
        computed by the coordinator at publish time — so this property and
        the snapshot are always in sync.  Before the first
        :meth:`publish_snapshot` call (i.e. while ``_hydrated`` is ``False``)
        it returns ``0.0``.

        Callers that need to distinguish an uninitialised authority (balance
        truly unknown) from an initialised-but-empty account should check
        :attr:`_hydrated` before reading this value.

        This makes the snapshot the single source of truth and eliminates
        any drift that could arise when
        :meth:`feed_broker_balance` updates ``_broker_balances`` between
        coordinator cycles.
        """
        with self._lock:
            if self._last_typed_snapshot is None:
                return 0.0
            return float(getattr(self._last_typed_snapshot, "real_capital", 0.0))

    def has_registered_sources(self) -> bool:
        """
        Return ``True`` when at least one broker has been registered with
        this authority (i.e. its balance — even $0 — has been observed).

        A zero balance is a valid registered source: it means the broker
        connected and confirmed an empty account, which is distinct from
        the authority's initial state where no broker has reported at all.
        Callers that specifically need a positive capital total should use
        :meth:`is_ready` or check :attr:`total_capital` directly.
        """
        with self._lock:
            return len(self._broker_balances) > 0

    def is_ready(self) -> bool:
        """
        Return ``True`` when the authority holds at least one usable broker
        balance entry **and** the sum of those balances is positive.

        This is the canonical readiness invariant used by
        :func:`wait_for_capital_ready`.  It is stricter than
        :meth:`has_registered_sources` because it requires both a non-empty
        ``_broker_balances`` dict (broker was registered **and** its payload
        was ingested) **and** a strictly positive real-capital sum (the
        registered balance is non-zero and therefore usable).

        The dual check eliminates the "empty-but-registered" state that
        :meth:`has_registered_sources` cannot detect: a broker entry with a
        zero balance increments ``len(_broker_balances)`` but does not pass
        the ``get_real_capital() > 0`` guard, so the authority stays "not
        ready" until at least one source reports real funds.
        """
        with self._lock:
            # FIX 3: any broker observation (even zero balance) means sources are
            # registered.  The previous sum > 0 guard incorrectly blocked hydration
            # for accounts that have been fetched but are genuinely empty.
            return len(self._broker_balances) > 0

    @property
    def is_hydrated(self) -> bool:
        """Return ``True`` after the first valid snapshot has been published.

        Unlike :meth:`is_ready`, this does **not** require a positive balance.
        It only confirms that the coordinator has run at least once so the
        authority holds real (post-refresh) data rather than its empty initial
        state.  Use this flag to distinguish "not yet initialised" from
        "initialised with a zero balance" without inspecting :attr:`total_capital`.

        Thread-safety: ``_hydrated`` transitions from ``False`` to ``True``
        exactly once (inside ``self._lock`` in :meth:`publish_snapshot`).
        In CPython, reading a bool attribute is atomic, so no lock is acquired
        here.  The property is intentionally lock-free for callers that poll it
        in hot paths.
        """
        return self._hydrated

    def block_until_hydrated(self, timeout: float = 30.0) -> bool:
        """Block the calling thread until this authority is hydrated.

        Hydration means the coordinator has published at least one snapshot —
        the balance may be zero (HYDRATED_ZERO_CAPITAL) or positive
        (ACTIVE_CAPITAL).  This is the correct gate for subsystems (FIX 4)
        that must not start before the balance pipeline has run once.

        Parameters
        ----------
        timeout:
            Maximum seconds to wait before giving up.  Default 30 s.

        Returns
        -------
        bool
            ``True`` if already hydrated or hydration confirmed within timeout.
            ``False`` if the timeout elapsed without hydration.
        """
        if self._hydrated:
            return True
        return CAPITAL_HYDRATED_EVENT.wait(timeout=timeout)

    @property
    def state(self) -> CapitalLifecycleState:
        """Capital lifecycle state — explicit 3-phase enum.

        Returns
        -------
        CapitalLifecycleState.INITIALIZING
            No snapshot received yet (``_hydrated`` is ``False``);
            :attr:`total_capital` returns ``0.0`` but is meaningless.
        CapitalLifecycleState.HYDRATED_ZERO_CAPITAL
            At least one snapshot received; confirmed balance is zero.
        CapitalLifecycleState.ACTIVE_CAPITAL
            Hydrated **and** ``total_capital > 0``; allocation decisions may
            proceed.

        Because :class:`CapitalLifecycleState` inherits from ``str``, existing
        code that compares the return value as a string continues to work
        (e.g. ``authority.state == "ACTIVE_CAPITAL"``).

        Callers that only need a boolean gate should prefer :attr:`is_hydrated`
        (phase ≥ HYDRATED_ZERO_CAPITAL) or :meth:`is_ready` (ACTIVE_CAPITAL)
        over inspecting this property directly.
        """
        if not self._hydrated:
            return CapitalLifecycleState.INITIALIZING
        with self._lock:
            if sum(self._broker_balances.values()) > 0:
                return CapitalLifecycleState.ACTIVE_CAPITAL
        return CapitalLifecycleState.HYDRATED_ZERO_CAPITAL

    @property
    def registered_broker_count(self) -> int:
        """Number of brokers that have posted at least one balance feed.

        Unlike :meth:`has_registered_sources`, this is a simple count that
        does not re-evaluate individual balance magnitudes, making it suitable
        as a registration-only readiness gate when ``total_capital`` is used
        separately to guard the capital-magnitude requirement.
        """
        with self._lock:
            return len(self._broker_balances)

    def get_real_capital(self) -> float:
        """
        Gross observed equity across all registered brokers (USD + USDC).

        Returns 0.0 before the first successful :meth:`refresh` call.
        """
        with self._lock:
            return sum(self._broker_balances.values())

    def get_usable_capital(self) -> float:
        """
        Capital available for trading after deducting the reserve fraction.

        ``usable = real * (1 - reserve_pct)``
        """
        with self._lock:
            real = sum(self._broker_balances.values())
            return real * (1.0 - self._reserve_pct)

    def get_risk_capital(self) -> float:
        """
        Capital available for *new* risk after subtracting currently open
        position exposure.

        ``risk = usable - open_exposure_usd``
        """
        with self._lock:
            real = sum(self._broker_balances.values())
            usable = real * (1.0 - self._reserve_pct)
            return max(0.0, usable - self._open_exposure_usd)

    def get_primary_capital(self) -> float:
        """
        Capital from *primary* (authoritative) brokers only — i.e. those tagged
        with :data:`BROKER_ROLE_PRIMARY` via :meth:`set_broker_role`.

        Use this figure for:
          • Global minimum-capital checks at startup
          • AI hub ``portfolio_value`` calculations
          • Portfolio intelligence ``effective_capital``

        Isolated (Coinbase NANO) brokers are intentionally excluded so a tiny
        sandbox balance can never block startup or distort AI allocation math.

        Falls back to :meth:`get_real_capital` when no roles have been
        registered yet (backward-compatible with callers that do not call
        ``set_broker_role``).
        """
        with self._lock:
            if not self._broker_roles:
                # No role info yet — fall back to full sum (safe default)
                return sum(self._broker_balances.values())
            total = sum(
                bal
                for bid, bal in self._broker_balances.items()
                if self._broker_roles.get(bid, BROKER_ROLE_UNKNOWN) == BROKER_ROLE_PRIMARY
            )
            return total

    def get_isolated_capital(self) -> float:
        """
        Capital from *isolated* brokers only (e.g. Coinbase NANO / sandbox).

        Useful for sizing trades that execute exclusively within an isolated
        account, or for reporting the sandbox balance separately from the
        authoritative Kraken balance.

        Returns 0.0 when no brokers have been tagged as isolated.
        """
        with self._lock:
            return sum(
                bal
                for bid, bal in self._broker_balances.items()
                if self._broker_roles.get(bid, BROKER_ROLE_UNKNOWN) == BROKER_ROLE_ISOLATED
            )

    def get_usable_primary_capital(self) -> float:
        """
        Reserve-reduced capital from *primary* (authoritative) brokers only.

        This is the correct value for AI hub ``portfolio_value`` calculations
        and replaces the pattern ``get_primary_capital() * (1 - _reserve_pct)``
        that would require callers to access the private ``_reserve_pct``.

        Falls back to :meth:`get_usable_capital` when no broker roles have
        been set (backward-compatible default).
        """
        with self._lock:
            if not self._broker_roles:
                # No role info yet — fall back to full usable capital
                real = sum(self._broker_balances.values())
                return max(0.0, real * (1.0 - self._reserve_pct) - self._open_exposure_usd)
            primary_raw = sum(
                bal
                for bid, bal in self._broker_balances.items()
                if self._broker_roles.get(bid, BROKER_ROLE_UNKNOWN) == BROKER_ROLE_PRIMARY
            )
            return max(0.0, primary_raw * (1.0 - self._reserve_pct) - self._open_exposure_usd)

    def get_per_broker(self, broker_id: str) -> float:
        """
        Usable capital attributed to a single broker.

        Returns 0.0 when *broker_id* is not registered or has a $0 balance.
        """
        with self._lock:
            raw = self._broker_balances.get(str(broker_id), 0.0)
            return raw * (1.0 - self._reserve_pct)

    def get_raw_per_broker(self, broker_id: str) -> float:
        """
        Raw (non-reserve-reduced) balance for a single broker as last reported
        by :meth:`refresh` or :meth:`feed_broker_balance`.

        Use this when you need the gross account balance for position-sizing
        routines that apply their own reserve / risk logic internally.

        Returns 0.0 when *broker_id* is not registered or has a $0 balance.
        """
        with self._lock:
            return self._broker_balances.get(str(broker_id), 0.0)

    # ------------------------------------------------------------------
    # Staleness helper
    # ------------------------------------------------------------------

    def is_stale(self, ttl_s: float = 60.0) -> bool:
        """
        Return ``True`` when the authority has never been refreshed **or**
        the last refresh is older than *ttl_s* seconds.

        Parameters
        ----------
        ttl_s:
            Maximum acceptable age of the cached balances in seconds.
            Default 60 s.  Pass ``float('inf')`` to check only whether a
            refresh has ever occurred.
        """
        with self._lock:
            if self.last_updated is None:
                return True
            age = (datetime.now(timezone.utc) - self.last_updated).total_seconds()
            return age > ttl_s

    def is_fresh(self, ttl_s: float = _DEFAULT_FRESHNESS_TTL_S) -> bool:
        """
        Return ``True`` only when **both** conditions hold:

        1. The last refresh occurred within *ttl_s* seconds.
        2. At least ``_expected_brokers`` brokers contributed a non-zero
           balance (prevents partial-aggregation silently passing as valid).

        When :attr:`opportunistic` mode is active, condition 2 is relaxed to
        require only **1** broker with a non-zero balance, allowing trading to
        start faster when not all expected brokers have connected yet.

        This is the preferred freshness gate for live-trading code paths.
        Unlike ``is_stale(ttl_s=float('inf'))``, a snapshot that was once
        populated but has since gone stale will correctly return ``False``.

        Parameters
        ----------
        ttl_s:
            Maximum acceptable age of the cached snapshot in seconds.
            Default 90 s (matches the per-cycle refresh cadence).
        """
        with self._lock:
            if self.last_updated is None:
                return False
            age = (datetime.now(timezone.utc) - self.last_updated).total_seconds()
            if age > ttl_s:
                return False
            min_brokers = 1 if self._opportunistic else self._expected_brokers
            if len(self._broker_balances) < min_brokers:
                return False
            return True

    def set_expected_brokers(self, count: int) -> None:
        """
        Set the minimum number of brokers whose balances must be present for
        :meth:`is_fresh` to return ``True``.

        Call this at startup once the broker map is known, e.g.::

            authority.set_expected_brokers(len(connected_broker_map))

        Parameters
        ----------
        count:
            Minimum broker count.  Values < 1 are silently clamped to 1.
        """
        with self._lock:
            self._expected_brokers = max(1, int(count))
        logger.debug(
            "[CapitalAuthority] expected_brokers set to %d", self._expected_brokers
        )

    # ------------------------------------------------------------------
    # Read-only properties for the coordinator (avoid accessing privates)
    # ------------------------------------------------------------------

    @property
    def reserve_pct(self) -> float:
        """The configured capital reserve fraction (e.g. 0.02 = 2 %)."""
        with self._lock:
            return self._reserve_pct

    @property
    def expected_brokers(self) -> int:
        """Minimum broker count required for :meth:`is_fresh` to return ``True``."""
        with self._lock:
            return self._expected_brokers

    @property
    def opportunistic(self) -> bool:
        """Whether opportunistic mode is active.

        When ``True``, :attr:`CAPITAL_SYSTEM_READY` is set (and
        :meth:`is_fresh` returns ``True``) as soon as **at least one** broker
        reports a positive balance, regardless of ``expected_brokers``.

        This allows trading to start faster when some brokers are slow to
        connect, at the cost of a less complete initial capital picture.
        """
        return self._opportunistic

    def set_opportunistic(self, enabled: bool) -> None:
        """Enable or disable opportunistic mode at runtime.

        Parameters
        ----------
        enabled:
            Pass ``True`` to allow :attr:`~CapitalLifecycleState.ACTIVE_CAPITAL`
            with only 1 connected broker; ``False`` to restore strict
            ``expected_brokers`` enforcement.
        """
        self._opportunistic = bool(enabled)
        logger.info(
            "[CapitalAuthority] opportunistic mode %s",
            "ENABLED" if self._opportunistic else "DISABLED",
        )

    # ------------------------------------------------------------------
    # Single-writer publish gate
    # ------------------------------------------------------------------

    #: The only writer_id that publish_snapshot() accepts.
    #: Must match ``capital_flow_state_machine.WRITER_ID``.
    _AUTHORIZED_WRITER_ID: str = "mabm_capital_refresh_coordinator"

    def publish_snapshot(self, snapshot: Any, writer_id: str) -> bool:
        """
        Atomically replace the internal capital state with data from *snapshot*.

        This is the **only** write path accepted after the coordinator is active.
        Any call whose *writer_id* does not match :attr:`_AUTHORIZED_WRITER_ID`
        is rejected and returns ``False`` — the authority state is unchanged.

        Parameters
        ----------
        snapshot:
            A :class:`~capital_flow_state_machine.CapitalSnapshot` instance
            (duck-typed to avoid circular imports).
        writer_id:
            Must equal ``"mabm_capital_refresh_coordinator"``.

        Returns
        -------
        bool
            ``True`` if the snapshot was accepted and applied.
            ``False`` in any of these cases (authority state is **not** changed):

            * *writer_id* does not match :attr:`_AUTHORIZED_WRITER_ID`.
            * The snapshot's ``computed_at`` timestamp is not strictly newer
              than the authority's current ``last_updated`` timestamp
              (monotonic guard — prevents a slow in-flight coordinator run
              from clobbering a more-recent snapshot).
        """
        self.assert_singleton()
        if writer_id != self._AUTHORIZED_WRITER_ID:
            logger.error(
                "[CapitalAuthority] publish_snapshot REJECTED — "
                "unauthorized writer_id=%r (expected %r)",
                writer_id,
                self._AUTHORIZED_WRITER_ID,
            )
            return False

        # Guard: reject snapshots that carry no broker data at all.  An empty
        # broker_balances map means the snapshot is a hollow bootstrap artefact
        # with no real data.  Accepting it would set _hydrated=True while the
        # authority holds no meaningful state, causing dependent systems to
        # believe the capital pipeline is initialised when it is not.
        # NOTE: a snapshot with broker_balances present but real_capital == 0 is
        # deliberately allowed — that represents a legitimate
        # HYDRATED_ZERO_CAPITAL state (all brokers confirmed at zero balance).
        _snap_broker_balances = getattr(snapshot, "broker_balances", {})
        if not _snap_broker_balances:
            logger.error(
                "EMPTY SNAPSHOT REJECTED: publish_snapshot received snapshot "
                "with no broker data (writer_id=%r). "
                "Returning False to prevent hollow hydration.",
                writer_id,
            )
            return False

        new_balances = dict(_snap_broker_balances)
        open_exp = float(getattr(snapshot, "open_exposure_usd", 0.0))
        _raw_computed_at = getattr(snapshot, "computed_at", None)
        computed_at: datetime = (
            _ensure_utc(_raw_computed_at)
            if isinstance(_raw_computed_at, datetime)
            else datetime.now(timezone.utc)
        )

        with self._lock:
            # Monotonic-timestamp guard: reject snapshots whose computed_at is
            # not strictly newer than the current authority state.  This prevents
            # an in-flight coordinator run that started *before* a faster one from
            # clobbering the more-recent snapshot once it finishes.
            # Equal timestamps are treated as duplicates (same reasoning as in
            # feed_broker_balance) and are also rejected.
            # This is expected concurrent-operation behaviour, not an error, so
            # we log at debug level to avoid spurious WARNING noise.
            if self.last_updated is not None and computed_at <= self.last_updated:
                logger.debug(
                    "[CapitalAuthority] publish_snapshot skipped — "
                    "snapshot not newer (computed_at=%s <= last_updated=%s)",
                    computed_at.isoformat(),
                    self.last_updated.isoformat(),
                )
                return False

            self._broker_balances = new_balances
            self._open_exposure_usd = max(0.0, open_exp)
            self.last_updated = computed_at
            # Auto-raise expected_brokers if the new snapshot brought more brokers.
            if len(new_balances) > self._expected_brokers:
                self._expected_brokers = len(new_balances)
            self._last_typed_snapshot = snapshot
            # Mark the authority as hydrated on the first successful publish so
            # that callers can distinguish "not yet initialised" from "initialised
            # with a zero balance" without relying on total_capital == 0.
            _first_hydration = not self._hydrated
            self._hydrated = True
            # FIX 4: signal CAPITAL_HYDRATED_EVENT on first hydration (even zero
            # balance) so subsystems gated on is_hydrated can proceed immediately.
            if _first_hydration:
                CAPITAL_HYDRATED_EVENT.set()
            # Signal CAPITAL_SYSTEM_READY when the lifecycle reaches
            # ACTIVE_CAPITAL — i.e. the following conditions are satisfied:
            #   1. hydrated       — guaranteed by reaching this branch
            #   2. real_capital > 0 — confirmed non-zero balance
            #   3. broker threshold met — in normal mode: broker_count >=
            #      expected_brokers (no partial aggregation in flight); in
            #      opportunistic mode: broker_count >= 1 (trading may start
            #      with a partial capital picture).
            #
            # set() is idempotent and thread-safe so calling it on every
            # subsequent healthy snapshot is harmless.
            snapshot_broker_count = int(getattr(snapshot, "broker_count", 0))
            snapshot_real_capital = float(getattr(snapshot, "real_capital", 0.0))
            broker_threshold = 1 if self._opportunistic else max(1, self._expected_brokers)
            if (
                snapshot_real_capital > 0.0
                and snapshot_broker_count >= broker_threshold
            ):
                if self._opportunistic and snapshot_broker_count < self._expected_brokers:
                    logger.warning(
                        "[CapitalAuthority] opportunistic ACTIVE_CAPITAL — "
                        "only %d/%d brokers connected; capital picture is partial",
                        snapshot_broker_count,
                        self._expected_brokers,
                    )
                CAPITAL_SYSTEM_READY.set()
            # MONOTONIC SNAPSHOT PROGRESSION (no-failure activation contract).
            # Stamp _broker_feed_timestamps with computed_at for every broker
            # present in the accepted snapshot.  This closes the race where the
            # push path (feed_broker_balance) had no prior timestamp entry for a
            # broker (e.g. on first boot or after a coordinator-only cycle), so
            # any stale feed arriving after publish would be silently accepted
            # and would overwrite the coordinator's freshly-published balances.
            #
            # By setting a floor of computed_at in _broker_feed_timestamps the
            # per-broker monotonic guard in feed_broker_balance will reject any
            # feed whose timestamp is not strictly newer than the coordinator's
            # publish time.
            #
            # Only ABSENT or STALE entries are stamped; if a broker already has
            # a feed timestamp that is strictly newer than computed_at (a T2 feed
            # that arrived after the coordinator fetched at T1 but before the T3
            # publish), that newer timestamp is preserved rather than rolled back.
            for _broker_key in new_balances:
                _existing_feed_ts = self._broker_feed_timestamps.get(_broker_key)
                # Only stamp absent or stale entries; a newer T2 feed timestamp
                # (T2 > computed_at) that arrived between the coordinator's T1
                # fetch and this T3 publish is preserved rather than rolled back.
                if _existing_feed_ts is None or _existing_feed_ts < computed_at:
                    self._broker_feed_timestamps[_broker_key] = computed_at

            # Invariant: _last_typed_snapshot.real_capital must equal the value
            # that total_capital will now return.  Checked while the lock is still
            # held so no concurrent publish can invalidate the comparison.
            snapshot_real = float(snapshot.real_capital)
            assert abs(float(self._last_typed_snapshot.real_capital) - snapshot_real) < 1e-6, (
                f"CapitalAuthority state divergence detected — "
                f"stored real_capital={self._last_typed_snapshot.real_capital} "
                f"!= snapshot.real_capital={snapshot_real}"
            )

        logger.debug(
            "[CA DEBUG] snapshot.real_capital=$%.6f  total_capital=$%.6f",
            snapshot_real,
            self.total_capital,
        )
        logger.info(
            "[CapitalAuthority] snapshot published — real=$%.2f  "
            "confidence=%.3f(%s)  brokers=%d",
            snapshot_real,
            getattr(
                getattr(snapshot, "confidence", None),
                "confidence_score",
                float("nan"),
            ),
            getattr(
                getattr(snapshot, "confidence", None),
                "band",
                "?",
            ),
            len(new_balances),
        )
        # CSM v3 — persist state immediately after a live publish.
        self._warm_start = False
        self._save_cached_state()
        return True

    def get_typed_snapshot(self) -> Optional[Any]:
        """
        Return the most-recently published
        :class:`~capital_flow_state_machine.CapitalSnapshot`, or ``None``
        if the coordinator has not yet run.
        """
        with self._lock:
            return self._last_typed_snapshot

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def get_snapshot(self) -> dict:
        """Return a plain-dict snapshot suitable for dashboards and logging."""
        with self._lock:
            real = sum(self._broker_balances.values())
            age = (
                (datetime.now(timezone.utc) - self.last_updated).total_seconds()
                if self.last_updated is not None
                else float("inf")
            )
            # Compute lifecycle state inline (lock already held).
            if not self._hydrated:
                lifecycle = CapitalLifecycleState.INITIALIZING
            elif real > 0:
                lifecycle = CapitalLifecycleState.ACTIVE_CAPITAL
            else:
                lifecycle = CapitalLifecycleState.HYDRATED_ZERO_CAPITAL
            return {
                "real_capital": real,
                "usable_capital": real * (1.0 - self._reserve_pct),
                "risk_capital": max(
                    0.0,
                    real * (1.0 - self._reserve_pct) - self._open_exposure_usd,
                ),
                "open_exposure_usd": self._open_exposure_usd,
                "reserve_pct": self._reserve_pct,
                "broker_balances": dict(self._broker_balances),
                "broker_count": len(self._broker_balances),
                "expected_brokers": self._expected_brokers,
                "capital_completeness": (
                    len(self._broker_balances) / self._expected_brokers
                    if self._expected_brokers > 0 else 0.0
                ),
                "updated_total_capital": self._last_updated_total,
                "last_updated": self.last_updated.isoformat()
                if self.last_updated
                else None,
                "age_s": age,
                "is_fresh": self.is_fresh(),  # uses _DEFAULT_FRESHNESS_TTL_S
                # kept for backwards-compat with any existing dashboard consumers
                "is_stale_60s": age > 60.0,
                # explicit lifecycle state — consumers should read this instead
                # of inferring the economic condition from individual fields
                "capital_lifecycle_state": lifecycle.value,
            }


# ---------------------------------------------------------------------------
# Singleton accessor (matches pattern of get_global_nonce_manager() etc.)
# ---------------------------------------------------------------------------


def get_capital_authority() -> CapitalAuthority:
    """
    Return the process-wide :class:`CapitalAuthority` singleton.

    The instance is created lazily on the first call and is never replaced.
    This is safe to call from any module at import time; the instance will
    be empty (``is_stale()`` → ``True``) until :meth:`CapitalAuthority.refresh`
    is called by the trading-strategy startup sequence.
    """
    global _authority_instance
    if _authority_instance is None:
        with _authority_lock:
            if _authority_instance is None:
                _authority_instance = CapitalAuthority()
                logger.debug("[CapitalAuthority] singleton created")
    return _authority_instance


def reset_capital_authority_singleton(clear_disk_cache: bool = False) -> None:
    """Clear the cached CapitalAuthority singleton (cold-start helper).

    Also clears :data:`STARTUP_LOCK` and :data:`CAPITAL_SYSTEM_READY` so that
    the next singleton creation starts from a clean bootstrap state.  Intended
    for use in tests and cold-start recovery only — never call this during
    live trading.

    Parameters
    ----------
    clear_disk_cache:
        When ``True``, also deletes the CSM v3 on-disk state file so that the
        next singleton creation performs a full cold start rather than a
        warm start from cached data.  Pass ``True`` in tests that assert
        ``INITIALIZING`` lifecycle state at startup.  Defaults to ``False``
        to preserve backward compatibility with existing callers.
    """
    global _authority_instance, _EXPECTED_ID
    with _authority_lock:
        _authority_instance = None
        _EXPECTED_ID = None
    STARTUP_LOCK.clear()
    CAPITAL_SYSTEM_READY.clear()
    CAPITAL_HYDRATED_EVENT.clear()
    logger.warning("[CapitalAuthority] singleton cache cleared (STARTUP_LOCK + CAPITAL_SYSTEM_READY + CAPITAL_HYDRATED_EVENT reset)")
    if clear_disk_cache:
        try:
            if _STATE_FILE.exists():
                _STATE_FILE.unlink()
                logger.info("[CapitalAuthority] CSM v3 on-disk state cache cleared")
        except Exception as exc:
            logger.warning("[CapitalAuthority] CSM v3 failed to clear on-disk state cache: %s", exc)


def wait_for_capital_ready(timeout: float = CAPITAL_READY_TIMEOUT) -> bool:
    """
    Block the calling thread until :class:`CapitalAuthority` reaches
    :attr:`~CapitalLifecycleState.ACTIVE_CAPITAL`.

    "Active" means the coordinator has published at least one snapshot where:

    * ``real_capital > 0`` — at least one broker reports a positive balance.
    * Broker threshold met — in **normal** mode: ``broker_count >= expected_brokers``
      (all expected brokers contributed; no partial aggregation in flight).
      In **opportunistic** mode (see :attr:`CapitalAuthority.opportunistic`):
      ``broker_count >= 1``, allowing trading to start with a partial capital
      picture when not all expected brokers have connected yet.

    Implementation note: blocks on :data:`CAPITAL_SYSTEM_READY`, which is set
    by :meth:`CapitalAuthority.publish_snapshot` when the conditions above are
    satisfied.  Because the event maps directly to
    :attr:`CapitalLifecycleState.ACTIVE_CAPITAL`, no additional polling is
    required after the event fires.

    Parameters
    ----------
    timeout:
        Maximum seconds to wait before giving up.  Default 60 s.

    Returns
    -------
    bool
        Always ``True`` when the function returns normally.

    Raises
    ------
    RuntimeError
        When *timeout* elapses without the authority reaching ACTIVE_CAPITAL.
        Callers that treat :class:`~bot.capital_allocation_brain.CapitalAllocationBrain`
        as optional (e.g. advisory use in ``capital_decision_engine``) should
        wrap the call in a try/except and handle the failure gracefully.

    Example
    -------
    ::

        from bot.capital_authority import wait_for_capital_ready
        from bot.capital_allocation_brain import CapitalAllocationBrain

        wait_for_capital_ready()          # blocks up to 30 s
        brain = CapitalAllocationBrain()  # guaranteed non-zero capital
    """
    # Block on the event; it is set when capital is confirmed active
    # (real_capital > 0 AND broker threshold met), so once the event fires
    # we are already in ACTIVE_CAPITAL — no polling required.
    if not CAPITAL_SYSTEM_READY.wait(timeout=timeout):
        raise RuntimeError(
            f"❌ CapitalAuthority never reached ACTIVE_CAPITAL after {timeout:.0f}s "
            "(real capital is zero or broker aggregation is incomplete)"
        )
    logger.info("✅ CapitalAuthority ACTIVE_CAPITAL confirmed — proceeding")
    return True


def wait_for_capital_hydrated(timeout: float = 30.0) -> bool:
    """Block until :class:`CapitalAuthority` is hydrated (any snapshot received).

    Unlike :func:`wait_for_capital_ready`, this does **not** require
    ``real_capital > 0``.  It unblocks as soon as the coordinator has
    published its first snapshot — even if the balance is zero.  This is the
    correct gate for subsystems (e.g. Capital Brain) that need to know the
    balance has been *fetched* rather than that it is *positive*.

    Parameters
    ----------
    timeout:
        Maximum seconds to wait.  Default 30 s.

    Returns
    -------
    bool
        Always ``True`` when the function returns normally.

    Raises
    ------
    RuntimeError
        When *timeout* elapses without hydration (coordinator never ran).
    """
    if not CAPITAL_HYDRATED_EVENT.wait(timeout=timeout):
        raise RuntimeError(
            f"❌ CapitalAuthority never reached HYDRATED state after {timeout:.0f}s "
            "(coordinator has not published any snapshot yet)"
        )
    logger.info("✅ CapitalAuthority HYDRATED confirmed — proceeding")
    return True

