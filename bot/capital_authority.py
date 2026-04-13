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
All public methods are protected by a single ``threading.Lock``.
``refresh()`` captures the lock for the duration of the API calls so a
concurrent ``get_usable_capital()`` call always returns a consistent
snapshot rather than a partially-written intermediate state.

Author: NIJA Trading Systems
Version: 1.0
Date: April 2026
"""

from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger("nija.capital_authority")

# ---------------------------------------------------------------------------
# Module-level constants (all overridable via environment variables)
# ---------------------------------------------------------------------------

_DEFAULT_RESERVE_PCT: float = 0.02  # 2 % held back as reserve dust

# Maximum acceptable age of a CA snapshot before is_fresh() returns False.
# Must match (or be shorter than) the per-cycle refresh cadence in
# trading_strategy.py so a missed refresh is caught before the next trade.
_DEFAULT_FRESHNESS_TTL_S: float = 90.0

# ---------------------------------------------------------------------------
# Singleton state
# ---------------------------------------------------------------------------

_authority_instance: Optional["CapitalAuthority"] = None
_authority_lock = threading.Lock()


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
        self._lock = threading.Lock()
        self._reserve_pct: float = float(
            os.environ.get("NIJA_CAPITAL_RESERVE_PCT", str(_DEFAULT_RESERVE_PCT))
        )
        # Per-broker raw balances: broker_id → USD balance
        self._broker_balances: Dict[str, float] = {}
        # Registered open-position exposure in USD (updated by callers)
        self._open_exposure_usd: float = 0.0
        # Timestamp of most-recent successful refresh
        self.last_updated: Optional[datetime] = None
        # Minimum number of brokers that must have contributed a non-zero balance
        # for the snapshot to be considered complete.  Automatically raised by
        # refresh() to match the largest broker map seen so far.  Can also be set
        # explicitly at startup via set_expected_brokers() once the broker map is
        # known.  The env var NIJA_CAPITAL_EXPECTED_BROKERS is an advanced override
        # intended for multi-process deployments; in normal operation the value is
        # derived at runtime and this env var should not be needed.
        self._expected_brokers: int = int(
            os.environ.get("NIJA_CAPITAL_EXPECTED_BROKERS", "1")
        )

    # ------------------------------------------------------------------
    # Core refresh
    # ------------------------------------------------------------------

    def refresh(
        self,
        broker_map: Dict[str, Any],
        open_exposure_usd: float = 0.0,
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
        """
        new_balances: Dict[str, float] = {}

        for broker_id, broker in broker_map.items():
            if broker is None:
                continue
            try:
                raw = broker.get_account_balance()
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

                if balance > 0.0:
                    new_balances[str(broker_id)] = balance
                    logger.debug(
                        "[CapitalAuthority] broker=%s balance=$%.2f",
                        broker_id,
                        balance,
                    )
                else:
                    logger.debug(
                        "[CapitalAuthority] broker=%s returned $0 — skipping",
                        broker_id,
                    )
            except Exception as exc:
                logger.warning(
                    "[CapitalAuthority] Failed to fetch balance for broker=%s: %s",
                    broker_id,
                    exc,
                )

        with self._lock:
            self._broker_balances = new_balances
            self._open_exposure_usd = max(0.0, float(open_exposure_usd))
            self.last_updated = datetime.now(timezone.utc)
            # Auto-raise expected_brokers to match the largest map we have seen
            # so that a future refresh with fewer brokers fails the is_fresh() check.
            if len(new_balances) > self._expected_brokers:
                self._expected_brokers = len(new_balances)

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

    # ------------------------------------------------------------------
    # Open-exposure registry (call each cycle before reading risk_capital)
    # ------------------------------------------------------------------

    def register_open_exposure(self, open_exposure_usd: float) -> None:
        """Update the total open-position exposure without triggering a full refresh."""
        with self._lock:
            self._open_exposure_usd = max(0.0, float(open_exposure_usd))

    def feed_broker_balance(self, broker_key: str, balance: float) -> None:
        """
        Inject a freshly-fetched balance for a single broker directly into the
        authority without issuing an additional broker API call.

        This is the lightweight push-path used by :class:`BalanceService` so
        that every successful ``BalanceService.refresh()`` automatically keeps
        the authority current.  The authority's ``last_updated`` timestamp is
        refreshed on every call so ``is_stale()`` reflects the most recent feed.

        Parameters
        ----------
        broker_key:
            Logical broker identifier (e.g. ``"coinbase"`` or ``"kraken"``).
        balance:
            Raw USD balance for this broker (positive values only; zero and
            negative values are silently ignored so a bad API response cannot
            wipe out a previously valid balance).
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
        with self._lock:
            self._broker_balances[key] = balance
            self.last_updated = datetime.now(timezone.utc)
        logger.debug(
            "[CapitalAuthority] fed broker=%s balance=$%.2f (real=$%.2f)",
            key,
            balance,
            sum(self._broker_balances.values()),
        )

    # ------------------------------------------------------------------
    # Capital accessors
    # ------------------------------------------------------------------

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
            if len(self._broker_balances) < self._expected_brokers:
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
                "last_updated": self.last_updated.isoformat()
                if self.last_updated
                else None,
                "age_s": age,
                "is_fresh": self.is_fresh(),  # uses _DEFAULT_FRESHNESS_TTL_S
                # kept for backwards-compat with any existing dashboard consumers
                "is_stale_60s": age > 60.0,
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
