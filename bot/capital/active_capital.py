"""
ActiveCapital — Single Source of Truth for Trading Capital
===========================================================

This module exposes a thin, stable API for every module that needs to know
how much capital is available.  All capital reads MUST go through
``ActiveCapital.get_total_available_balance()``; direct broker balance reads
are prohibited.

Design:
- ``ActiveCapital`` wraps ``CapitalAuthority`` (the existing singleton) and
  delegates all real work to it.
- If the authority has not been hydrated (no balance snapshot received yet),
  ``get_total_available_balance()`` raises ``CapitalIntegrityError`` instead
  of silently returning a fallback value that could cause the rest of the
  pipeline to use a wrong capital figure.
- A process-level singleton is provided via ``get_active_capital()``.

Usage::

    from bot.capital.active_capital import get_active_capital
    from bot.exceptions import CapitalIntegrityError

    try:
        balance = get_active_capital().get_total_available_balance()
    except CapitalIntegrityError as exc:
        logger.error("Capital source invalid — trading halted: %s", exc)
        return  # DO NOT TRADE

Author: NIJA Trading Systems
"""

from __future__ import annotations

import logging
import threading
from typing import Optional

logger = logging.getLogger("nija.capital.active_capital")


class ActiveCapital:
    """
    Single source of truth for trading capital across all brokers.

    Wraps :class:`~bot.capital_authority.CapitalAuthority` and exposes a
    stable, simple API.  All callers that previously read broker balances
    directly (``broker.balance``, ``get_account_balance()``, etc.) should
    be migrated to use :meth:`get_total_available_balance` instead.

    Parameters
    ----------
    broker_manager:
        Optional broker manager instance.  When ``None`` the singleton
        ``CapitalAuthority`` is resolved lazily on first use.
    """

    def __init__(self, broker_manager=None) -> None:
        self._broker_manager = broker_manager
        self._authority = None  # resolved lazily via _get_authority()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_authority(self):
        """Return the process-wide CapitalAuthority singleton."""
        if self._authority is None:
            try:
                from bot.capital_authority import get_capital_authority
            except ImportError:
                from capital_authority import get_capital_authority  # type: ignore
            self._authority = get_capital_authority()
        return self._authority

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_total_available_balance(self) -> float:
        """
        Return the total available trading capital across all brokers (USD).

        Reads from :class:`~bot.capital_authority.CapitalAuthority` (the
        process-wide singleton).  Applies the standard 2 % reserve deduction
        so the returned value represents the capital that is safe to risk.

        Raises
        ------
        CapitalIntegrityError
            If the authority has not yet been hydrated (no balance snapshot
            received) — i.e. the capital pipeline has not run at all.
            **Trading MUST NOT proceed when this exception is raised.**
            Do NOT catch it silently and fall back to a default value; that
            is exactly the "fake STARTER fallback bug" this class exists to
            prevent.

        Returns
        -------
        float
            Total usable capital in USD (≥ 0.0).  Zero means the account
            is empty; a negative value will never be returned.
        """
        try:
            from bot.exceptions import CapitalIntegrityError
        except ImportError:
            from exceptions import CapitalIntegrityError  # type: ignore

        authority = self._get_authority()

        if not authority.is_hydrated:
            raise CapitalIntegrityError(
                "CAPITAL SOURCE INVALID — CapitalAuthority has not been hydrated. "
                "No broker balance has been fetched yet.  DO NOT TRADE."
            )

        balances = []
        failed_brokers = []

        # Collect per-broker balances with individual error isolation
        with authority._lock:
            broker_balances = dict(authority._broker_balances)

        if not broker_balances:
            raise CapitalIntegrityError(
                "CAPITAL SOURCE INVALID — CapitalAuthority is hydrated but holds "
                "no broker balance entries.  DO NOT TRADE."
            )

        for broker_key, raw_balance in broker_balances.items():
            try:
                bal = float(raw_balance)
                balances.append(bal)
            except Exception as exc:
                failed_brokers.append(broker_key)
                logger.warning(
                    "[ActiveCapital] Failed to read balance for broker=%s: %s",
                    broker_key,
                    exc,
                )

        if not balances and failed_brokers:
            raise CapitalIntegrityError(
                f"CAPITAL SOURCE INVALID — All broker balance reads failed "
                f"(brokers={failed_brokers}).  DO NOT TRADE."
            )

        # Use the authority's reserve-reduced figure (consistent with the rest of the system)
        total = authority.get_usable_capital()

        logger.info("💰 Aggregated capital across brokers: $%.2f", total)
        return total

    def is_capital_available(self) -> bool:
        """
        Return ``True`` when capital has been confirmed and is positive.

        Safe to call without catching ``CapitalIntegrityError`` — returns
        ``False`` instead of raising when the authority is not hydrated.
        """
        try:
            return self.get_total_available_balance() > 0.0
        except Exception:
            return False

    # Alias used in diagnostic log calls (problem-statement §4 quick test)
    def get_available_balance(self) -> float:
        """Alias for :meth:`get_total_available_balance`.

        Provided so callers can use the name suggested in the diagnostic
        guide::

            logger.critical("💰 EXECUTION CAPITAL: %s",
                            active_capital.get_available_balance())

        Raises
        ------
        CapitalIntegrityError
            Same conditions as :meth:`get_total_available_balance`.
        """
        return self.get_total_available_balance()


# ---------------------------------------------------------------------------
# Process-level singleton
# ---------------------------------------------------------------------------

_instance: Optional[ActiveCapital] = None
_instance_lock = threading.Lock()


def get_active_capital(broker_manager=None) -> ActiveCapital:
    """
    Return the process-wide :class:`ActiveCapital` singleton.

    Thread-safe.  The optional *broker_manager* argument is only used on the
    very first call; subsequent calls ignore it and return the already-created
    instance.
    """
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = ActiveCapital(broker_manager=broker_manager)
    return _instance
