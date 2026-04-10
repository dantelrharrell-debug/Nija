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

logger = logging.getLogger("nija.balance_service")


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

        # ── TTL gate ──────────────────────────────────────────────────────────
        if now - cls._last_update.get(broker_key, 0.0) < cls._ttl:
            cached = cls._cache.get(broker_key, 0.0)
            logger.debug("[BalanceService] %s: TTL hit — $%.2f", broker_key, cached)
            return cached

        # ── In-flight guard ───────────────────────────────────────────────────
        if cls._refreshing.get(broker_key, False):
            cached = cls._cache.get(broker_key, 0.0)
            logger.debug("[BalanceService] %s: refresh in-flight — returning cached $%.2f",
                         broker_key, cached)
            return cached

        cls._refreshing[broker_key] = True
        try:
            raw = fetch_fn()
            scalar, detailed = cls._parse(raw)

            if scalar > 0:
                cls._cache[broker_key] = scalar
                if detailed:
                    cls._cache_detailed[broker_key] = detailed
                cls._last_update[broker_key] = now
                logger.info("[BalanceService] %s → $%.2f", broker_key, scalar)
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
