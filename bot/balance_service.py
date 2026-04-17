"""
NIJA Balance Service — Materialized balance state.

Single source of truth for account balance across the entire bot.

Rules (non-negotiable)
----------------------
* Only the orchestrator (``run_cycle``) may call ``BalanceService.refresh()``.
* Every other read site calls ``BalanceService.get()`` — never the exchange.
* No module is allowed to call the exchange for balance outside of ``refresh()``.

Usage
-----
Orchestrator (once at the top of every cycle)::

    key = _broker_key(active_broker)
    account_balance = BalanceService.refresh(key, lambda: active_broker.get_account_balance(verbose=False))

All other code::

    balance = BalanceService.get("coinbase")
"""

import logging
import os
import time
from typing import Any, Callable, Dict

try:
    from capital_authority import get_capital_authority as _get_capital_authority
except ImportError:
    try:
        from bot.capital_authority import get_capital_authority as _get_capital_authority
    except ImportError:
        _get_capital_authority = None  # type: ignore[assignment]

logger = logging.getLogger("nija.balance_service")

# ---------------------------------------------------------------------------
# Latency-aware caching constants
# ---------------------------------------------------------------------------

# Exponential-moving-average smoothing factor for fetch latency.
# Higher → faster to react to sudden latency spikes; lower → smoother.
_LATENCY_EMA_ALPHA: float = 0.30

# Never let the effective TTL fall below this floor, regardless of latency.
_TTL_MIN_FLOOR_S: float = 5.0


class BalanceService:
    """
    Class-level materialized balance state.

    All state is stored as class attributes so there is exactly one copy per
    Python process — no instance needed, no singleton wiring required.
    """

    _cache: Dict[str, float] = {}           # scalar balance per broker key
    _cache_detailed: Dict[str, dict] = {}   # full detail dict per broker key
    _last_update: Dict[str, float] = {}     # unix timestamp of last successful refresh
    _refreshing: Dict[str, bool] = {}       # in-flight guard per broker key
    _ttl: float = float(os.environ.get("NIJA_BALANCE_TTL_S", "30"))  # override via env
    _last_logged: Dict[str, float] = {}     # last balance value that was INFO-logged per broker key

    # Latency tracking — updated on every successful refresh call
    _last_latency: Dict[str, float] = {}    # raw fetch duration (seconds) per broker key
    _latency_ema: Dict[str, float] = {}     # EMA-smoothed latency per broker key

    # ------------------------------------------------------------------
    # Read API — never calls the exchange
    # ------------------------------------------------------------------

    @classmethod
    def get(cls, broker_key: str) -> float:
        """Return cached scalar balance.  Returns 0.0 when not yet populated."""
        return cls._cache.get(broker_key, 0.0)

    @classmethod
    def get_detailed(cls, broker_key: str) -> dict:
        """Return cached detailed balance dict.  Returns ``{}`` when not yet populated."""
        return dict(cls._cache_detailed.get(broker_key, {}))

    @classmethod
    def get_latency(cls, broker_key: str) -> float:
        """Return the EMA-smoothed fetch latency (seconds) for *broker_key*.

        Returns 0.0 when no refresh has been completed yet for this key.
        """
        return cls._latency_ema.get(broker_key, 0.0)

    @classmethod
    def get_effective_ttl(cls, broker_key: str) -> float:
        """Return the effective cache TTL for *broker_key*.

        The effective TTL shrinks by the EMA fetch latency so that slow API
        calls do not let the cache appear fresher than it really is.  It is
        floored at ``_TTL_MIN_FLOOR_S`` to prevent thrashing.

        For example, with a base TTL of 30 s and a 4 s EMA latency the
        effective TTL becomes 26 s — the cache expires 4 seconds sooner to
        compensate for the staleness introduced by the slow fetch.
        """
        effective = cls._ttl - cls._latency_ema.get(broker_key, 0.0)
        return max(effective, _TTL_MIN_FLOOR_S)

    # ------------------------------------------------------------------
    # Write API — orchestrator only
    # ------------------------------------------------------------------

    @classmethod
    def refresh(cls, broker_key: str, fetch_fn: Callable[[], Any]) -> float:
        """
        Refresh balance for *broker_key* by calling *fetch_fn()*.

        Two guards prevent unnecessary exchange calls:

        TTL gate
            If the cached value is less than ``_ttl`` seconds old the cached
            value is returned immediately without calling ``fetch_fn``.

        In-flight guard
            If a refresh is already executing for this key the cached value is
            returned so that concurrent callers never pile up on the exchange.

        Parameters
        ----------
        broker_key : str
            Logical broker name, e.g. ``"coinbase"`` or ``"kraken"``.
        fetch_fn : callable
            Zero-argument callable that returns either a ``float`` or a
            ``dict`` with ``trading_balance`` / ``total_funds`` keys.

        Returns
        -------
        float
            Updated (or TTL-cached) scalar balance.
        """
        now = time.time()

        # ── Latency-aware TTL gate ─────────────────────────────────────────────
        # The effective TTL is shortened by the EMA fetch latency so that slow
        # API calls do not create the illusion of a "fresh" balance when the
        # data was already seconds old by the time it arrived.
        effective_ttl = cls.get_effective_ttl(broker_key)
        if now - cls._last_update.get(broker_key, 0.0) < effective_ttl:
            cached = cls._cache.get(broker_key, 0.0)
            logger.debug("[BalanceService] %s: TTL hit (eff=%.1fs) — $%.2f",
                         broker_key, effective_ttl, cached)
            return cached

        # ── In-flight guard ───────────────────────────────────────────────────
        if cls._refreshing.get(broker_key, False):
            cached = cls._cache.get(broker_key, 0.0)
            logger.debug("[BalanceService] %s: refresh in-flight — returning cached $%.2f",
                         broker_key, cached)
            return cached

        cls._refreshing[broker_key] = True
        try:
            fetch_start = time.time()
            raw = fetch_fn()
            fetch_elapsed = time.time() - fetch_start

            # ── Update latency EMA ────────────────────────────────────────────
            prior_ema = cls._latency_ema.get(broker_key, fetch_elapsed)
            cls._last_latency[broker_key] = fetch_elapsed
            cls._latency_ema[broker_key] = (
                _LATENCY_EMA_ALPHA * fetch_elapsed
                + (1.0 - _LATENCY_EMA_ALPHA) * prior_ema
            )
            logger.debug(
                "[BalanceService] %s: fetch %.3fs (EMA=%.3fs, eff_ttl=%.1fs)",
                broker_key, fetch_elapsed,
                cls._latency_ema[broker_key],
                cls.get_effective_ttl(broker_key),
            )

            scalar, detailed = cls._parse(raw)

            if scalar > 0:
                cls._cache[broker_key] = scalar
                if detailed:
                    cls._cache_detailed[broker_key] = detailed
                cls._last_update[broker_key] = now
                # Throttle: only emit INFO when balance moves by $1 or more
                _prev_logged = cls._last_logged.get(broker_key, -1.0)
                if abs(scalar - _prev_logged) >= 1.0:
                    logger.info("[BalanceService] %s → $%.2f", broker_key, scalar)
                    cls._last_logged[broker_key] = scalar
                else:
                    logger.debug("[BalanceService] %s → $%.2f (no significant change)", broker_key, scalar)
                # Deterministic bootstrap contract: IF (no snapshot exists) → ALWAYS seed.
                # The single-writer contract (CapitalRefreshCoordinator) is preserved
                # for steady-state; this path fires exactly when the CA has never
                # received a coordinator snapshot (_hydrated is False).  Once the
                # coordinator publishes its first snapshot (_hydrated → True), this
                # bypass is permanently closed and all updates flow through the
                # coordinator exclusively.
                try:
                    _ca = _get_capital_authority() if _get_capital_authority else None
                    if _ca is not None and not _ca.is_hydrated:
                        _ca.force_accept_feed(broker_key, scalar)
                        logger.info(
                            "[BalanceService] %s: bootstrap seed → CA $%.2f",
                            broker_key,
                            scalar,
                        )
                except Exception as _seed_exc:
                    # Non-critical: CA may not be initialised yet during very early
                    # startup.  The coordinator pipeline will seed it on its next run.
                    logger.debug(
                        "[BalanceService] %s: bootstrap CA seed skipped (%s)",
                        broker_key,
                        _seed_exc,
                    )
            else:
                # Still update the timestamp so the TTL gate prevents immediate retry
                # storms when the exchange legitimately returns $0 (e.g. unfunded account).
                cls._last_update[broker_key] = now
                logger.warning(
                    "[BalanceService] %s: fetch returned $0 — retaining cached $%.2f (TTL reset)",
                    broker_key, cls._cache.get(broker_key, 0.0),
                )

            return cls._cache.get(broker_key, 0.0)

        except Exception as exc:
            logger.warning(
                "[BalanceService] %s: refresh error (%s) — cached $%.2f retained",
                broker_key, exc, cls._cache.get(broker_key, 0.0),
            )
            return cls._cache.get(broker_key, 0.0)

        finally:
            cls._refreshing[broker_key] = False

    @classmethod
    def invalidate(cls, broker_key: str) -> None:
        """
        Force the next ``refresh()`` call to bypass the TTL gate.

        Call this after any operation that changes the exchange balance (order
        fill, cleanup run, position rotation) so the next cycle reads a fresh
        value instead of serving the now-stale cached amount.
        """
        cls._last_update.pop(broker_key, None)
        logger.debug("[BalanceService] %s: invalidated", broker_key)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @classmethod
    def _parse(cls, raw: Any):
        """Return ``(scalar_float, detailed_dict)`` from a broker return value."""
        if isinstance(raw, dict):
            scalar = float(
                raw.get("total_funds")
                or raw.get("trading_balance")
                or raw.get("total_balance")
                or 0.0
            )
            return scalar, raw
        try:
            return float(raw), {}
        except (TypeError, ValueError):
            return 0.0, {}
