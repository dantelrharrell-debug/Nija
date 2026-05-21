"""
NIJA Downstream Execution Blocker Guard
========================================

Provides structured classification and gating for the 10 downstream
execution blockers that can prevent live order fulfilment.

Blockers handled
----------------
1.  broker_auth          – 401/403/ECDSA/signature errors from exchange
2.  order_sizing         – step-size, precision, min-qty violations
3.  insufficient_balance – live balance below effective order cost
4.  slippage_spread      – spread/slippage wider than configured threshold
5.  post_only_reject     – post-only limit would immediately cross book
6.  min_notional         – below exchange minimum order value
7.  risk_governor        – GlobalRiskGovernor RED gate fires
8.  adapter_exception    – unhandled broker-adapter exception
9.  ack_timeout          – exchange did not acknowledge within timeout
10. reconciliation       – reconciliation failure blocks new orders

Design
------
* ``ExchangeErrorClassifier.classify(error)`` maps raw exchange error
  strings to a :class:`BlockerType` value, enabling the pipeline to
  distinguish *expected soft rejections* (auth, post-only, ACK timeout,
  reconciliation) from *hard ECEL-bypass errors* that must raise
  ``SystemError``.

* ``DownstreamBlockerGuard`` aggregates the two pre-dispatch gates that
  are NOT already part of the ECEL compile path:
  - :class:`GlobalRiskGovernor` (portfolio-wide circuit breaker)
  - :class:`SlippageProtector`   (spread/slippage cost gate)

  Both are loaded lazily at first use so the guard has zero hard
  dependencies and degrades gracefully when those modules are absent.

Usage
-----
::

    from bot.downstream_blocker_guard import (
        DownstreamBlockerGuard,
        BlockerType,
        ExchangeErrorClassifier,
    )

    guard = DownstreamBlockerGuard()

    # Pre-dispatch gates
    ok, reason, blocker = guard.check_risk_governor("BTC-USD", 250.0)
    if not ok:
        ...

    ok, reason, blocker = guard.check_slippage(
        "BTC-USD", "buy", 500.0, bid=50_000, ask=50_020
    )
    if not ok:
        ...

    # Post-dispatch error classification
    blocker = ExchangeErrorClassifier.classify(exchange_error_string)
    is_soft = ExchangeErrorClassifier.is_soft_blocker(blocker)

Author: NIJA Trading Systems
Version: 1.0
Date: May 2026
"""

from __future__ import annotations

import logging
import os
from enum import Enum
from typing import Optional, Tuple

logger = logging.getLogger("nija.downstream_blocker_guard")


# ---------------------------------------------------------------------------
# BlockerType – canonical names for all 10 downstream blockers
# ---------------------------------------------------------------------------

class BlockerType(str, Enum):
    """Canonical identifier for each downstream execution blocker."""
    BROKER_AUTH          = "broker_auth"
    ORDER_SIZING         = "order_sizing"
    INSUFFICIENT_BALANCE = "insufficient_balance"
    SLIPPAGE_SPREAD      = "slippage_spread"
    POST_ONLY_REJECT     = "post_only_reject"
    MIN_NOTIONAL         = "min_notional"
    RISK_GOVERNOR        = "risk_governor"
    ADAPTER_EXCEPTION    = "adapter_exception"
    ACK_TIMEOUT          = "ack_timeout"
    RECONCILIATION       = "reconciliation"
    UNKNOWN              = "unknown"


# ---------------------------------------------------------------------------
# Soft vs Hard blocker set
# ---------------------------------------------------------------------------

# Soft blockers are expected exchange responses or pre-dispatch gates.
# The pipeline should log and return a graceful PipelineResult for these.
# Hard blockers indicate a bug (e.g. an order bypassed ECEL) and should
# raise a SystemError so the anomaly circuit breaker catches it.
_SOFT_BLOCKERS: frozenset[BlockerType] = frozenset({
    BlockerType.BROKER_AUTH,
    BlockerType.ORDER_SIZING,
    BlockerType.SLIPPAGE_SPREAD,
    BlockerType.POST_ONLY_REJECT,
    BlockerType.MIN_NOTIONAL,
    BlockerType.RISK_GOVERNOR,
    BlockerType.ADAPTER_EXCEPTION,
    BlockerType.ACK_TIMEOUT,
    BlockerType.RECONCILIATION,
    BlockerType.INSUFFICIENT_BALANCE,
})


# ---------------------------------------------------------------------------
# Exchange error keyword tables
# ---------------------------------------------------------------------------

# Auth-related error strings returned by Coinbase and Kraken.
_AUTH_KEYWORDS = (
    "invalid api key",
    "api key not found",
    "invalid signature",
    "signature mismatch",
    "authentication failed",
    "authentication_error",
    "unauthorized",
    "forbidden",
    "401",
    "403",
    "ecdsa",
    "hmac",
    "api_key_invalid",
    "bad api key",
    "key_not_found",
    "permission_denied",
    "ip not whitelisted",
    "ip address not permitted",
    "access denied",
)

# Post-only reject error strings.
_POST_ONLY_KEYWORDS = (
    "post_only",
    "post-only",
    "postonly",
    "would immediately match",
    "would trade against resting",
    "maker only",
    "maker_only",
    "econnrefused post",
    "post only",
    "err:esome",                  # Kraken post-only
    "order_would_immediately",
)

# ACK-timeout / order-not-found strings.
_ACK_TIMEOUT_KEYWORDS = (
    "ack timeout",
    "ack_timeout",
    "order not found",
    "order_not_found",
    "no order id returned",
    "no txid",
    "timeout waiting for ack",
    "order acknowledgement timeout",
    "order_timeout",
    "gateway timeout",
    "504",
    "request timeout",
    "read timeout",
)

# Min-notional error strings.
_MIN_NOTIONAL_KEYWORDS = (
    "min notional",
    "min_notional",
    "below minimum",
    "below_min",
    "minimum order size",
    "minimum notional",
    "order value too small",
    "cost too low",
    "order is too small",
    "eordermin",
    "insufficient amount",
    "err:order_too_small",
)

# Insufficient-balance strings.
_BALANCE_KEYWORDS = (
    "insufficient funds",
    "insufficient balance",
    "insufficient_funds",
    "not enough funds",
    "balance too low",
    "ebalance",
    "insufficient volume",
)

# Order-sizing / precision strings.
_SIZING_KEYWORDS = (
    "invalid base size",
    "invalid_base_size",
    "base_step",
    "invalid size",
    "precision",
    "lot size",
    "lot_size",
    "quantity precision",
    "invalid qty",
    "eapi:invalid orders",
)

# Reconciliation / position-state strings.
_RECONCILIATION_KEYWORDS = (
    "reconciliation",
    "reconcil",
    "position mismatch",
    "ghost position",
    "orphaned position",
    "discrepancy",
    "integrity failure",
)

# Adapter / transport-layer exception strings.
_ADAPTER_KEYWORDS = (
    "connectionerror",
    "connection error",
    "connection refused",
    "connection reset",
    "broken pipe",
    "network error",
    "ssl error",
    "sslerror",
    "certificate",
    "timeout",          # catch-all after ACK_TIMEOUT check
    "socket",
    "eof",
)


# ---------------------------------------------------------------------------
# ExchangeErrorClassifier
# ---------------------------------------------------------------------------

class ExchangeErrorClassifier:
    """
    Maps raw exchange error strings to :class:`BlockerType` values.

    Classification is applied in a fixed priority order to prevent, for
    example, a generic "timeout" keyword match from shadowing an
    explicit "ack_timeout" match.
    """

    # (keyword_tuple, BlockerType) in priority order – first match wins.
    _RULES: tuple = (
        (_AUTH_KEYWORDS,          BlockerType.BROKER_AUTH),
        (_POST_ONLY_KEYWORDS,     BlockerType.POST_ONLY_REJECT),
        (_ACK_TIMEOUT_KEYWORDS,   BlockerType.ACK_TIMEOUT),
        (_MIN_NOTIONAL_KEYWORDS,  BlockerType.MIN_NOTIONAL),
        (_BALANCE_KEYWORDS,       BlockerType.INSUFFICIENT_BALANCE),
        (_SIZING_KEYWORDS,        BlockerType.ORDER_SIZING),
        (_RECONCILIATION_KEYWORDS,BlockerType.RECONCILIATION),
        (_ADAPTER_KEYWORDS,       BlockerType.ADAPTER_EXCEPTION),
    )

    @classmethod
    def classify(cls, error: str) -> BlockerType:
        """Return the :class:`BlockerType` that best describes *error*.

        Parameters
        ----------
        error:
            Raw error string from the exchange or broker adapter.

        Returns
        -------
        BlockerType
            ``UNKNOWN`` when no keyword matches.
        """
        if not error:
            return BlockerType.UNKNOWN
        low = error.lower()
        for keywords, blocker_type in cls._RULES:
            if any(kw in low for kw in keywords):
                return blocker_type
        return BlockerType.UNKNOWN

    @classmethod
    def is_soft_blocker(cls, blocker: BlockerType) -> bool:
        """Return True when *blocker* represents an expected soft rejection.

        Soft blockers should be logged and returned as a graceful
        ``PipelineResult``.  Hard blockers (anything not in the soft set)
        indicate a bug that should trigger the anomaly circuit breaker.
        """
        return blocker in _SOFT_BLOCKERS


# ---------------------------------------------------------------------------
# DownstreamBlockerGuard
# ---------------------------------------------------------------------------

class DownstreamBlockerGuard:
    """
    Pre-dispatch gate aggregator for the two checks that live *after* ECEL
    but *before* the broker API call: GlobalRiskGovernor and SlippageProtector.

    Both dependencies are loaded lazily; failures degrade to pass-through
    so the execution pipeline is never hard-blocked by a missing module.

    Environment flags
    -----------------
    ``NIJA_RISK_GOVERNOR_ENABLED``  – set to ``"false"`` to disable governor gate
    ``NIJA_SLIPPAGE_GUARD_ENABLED`` – set to ``"false"`` to disable slippage gate
    """

    def __init__(self) -> None:
        self._governor_enabled = (
            os.getenv("NIJA_RISK_GOVERNOR_ENABLED", "true").strip().lower()
            not in ("0", "false", "no", "off")
        )
        self._slippage_enabled = (
            os.getenv("NIJA_SLIPPAGE_GUARD_ENABLED", "true").strip().lower()
            not in ("0", "false", "no", "off")
        )

        self._governor = None
        self._slippage = None

        if self._governor_enabled:
            self._governor = self._load_governor()
        if self._slippage_enabled:
            self._slippage = self._load_slippage()

        logger.info(
            "DownstreamBlockerGuard ready | risk_governor=%s | slippage_guard=%s",
            "on" if self._governor is not None else "off",
            "on" if self._slippage is not None else "off",
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check_risk_governor(
        self,
        symbol: str,
        proposed_risk_usd: float,
        portfolio_value: float = 0.0,
        volatility_ratio: float = 1.0,
    ) -> Tuple[bool, str, BlockerType]:
        """Consult GlobalRiskGovernor before dispatching an order.

        Returns
        -------
        (allowed, reason, blocker_type)
            *allowed* is True when the order may proceed.  On denial
            *blocker_type* is ``RISK_GOVERNOR``.
        """
        if self._governor is None:
            return True, "risk_governor_unavailable (pass-through)", BlockerType.RISK_GOVERNOR

        try:
            decision = self._governor.approve_entry(
                symbol=symbol,
                proposed_risk_usd=proposed_risk_usd,
                current_portfolio_value=portfolio_value,
                current_volatility_ratio=volatility_ratio,
            )
            if not decision.allowed:
                return False, decision.reason, BlockerType.RISK_GOVERNOR
            return True, decision.reason, BlockerType.RISK_GOVERNOR
        except Exception as exc:
            logger.warning("DownstreamBlockerGuard: risk governor check error: %s", exc)
            return True, f"risk_governor_error: {exc} (pass-through)", BlockerType.RISK_GOVERNOR

    def check_slippage(
        self,
        symbol: str,
        side: str,
        order_size_usd: float,
        bid: float = 0.0,
        ask: float = 0.0,
        volume_24h_usd: float = 0.0,
        volatility_pct: float = 0.02,
    ) -> Tuple[bool, str, BlockerType]:
        """Consult SlippageProtector before dispatching an order.

        Returns
        -------
        (allowed, reason, blocker_type)
            *allowed* is True when slippage is within configured limits.
            On denial *blocker_type* is ``SLIPPAGE_SPREAD``.
        """
        if self._slippage is None:
            return True, "slippage_guard_unavailable (pass-through)", BlockerType.SLIPPAGE_SPREAD

        # Without valid bid/ask prices the check cannot run.
        if bid <= 0 or ask <= 0:
            return True, "slippage_guard_skipped: no bid/ask (pass-through)", BlockerType.SLIPPAGE_SPREAD

        try:
            result = self._slippage.check(
                symbol=symbol,
                side=side,
                order_size_usd=order_size_usd,
                bid=bid,
                ask=ask,
                volume_24h_usd=volume_24h_usd,
                volatility_pct=volatility_pct,
            )
            if not result.approved:
                return False, result.reason, BlockerType.SLIPPAGE_SPREAD
            return True, result.reason, BlockerType.SLIPPAGE_SPREAD
        except Exception as exc:
            logger.warning("DownstreamBlockerGuard: slippage guard check error: %s", exc)
            return True, f"slippage_guard_error: {exc} (pass-through)", BlockerType.SLIPPAGE_SPREAD

    def notify_fill(
        self,
        symbol: str,
        side: str,
        expected_price: float,
        actual_fill_price: float,
    ) -> None:
        """Inform the slippage model about an observed fill for self-improvement."""
        if self._slippage is None:
            return
        try:
            self._slippage.record_fill(
                symbol=symbol,
                side=side,
                expected_price=expected_price,
                actual_fill_price=actual_fill_price,
            )
        except Exception as exc:
            logger.debug("DownstreamBlockerGuard: notify_fill error: %s", exc)

    def notify_trade_result(
        self,
        pnl_usd: float,
        is_win: bool,
        portfolio_value: float = 0.0,
    ) -> None:
        """Propagate trade outcomes to the GlobalRiskGovernor."""
        if self._governor is None:
            return
        try:
            self._governor.record_trade_result(
                pnl_usd=pnl_usd,
                is_win=is_win,
                portfolio_value=portfolio_value or None,
            )
        except Exception as exc:
            logger.debug("DownstreamBlockerGuard: notify_trade_result error: %s", exc)

    # ------------------------------------------------------------------
    # Loader helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _load_governor():
        for mod_name in ("bot.global_risk_governor", "global_risk_governor"):
            try:
                import importlib
                mod = importlib.import_module(mod_name)
                factory = getattr(mod, "get_global_risk_governor", None)
                if factory is not None:
                    gov = factory()
                    logger.info("DownstreamBlockerGuard: GlobalRiskGovernor loaded from %s", mod_name)
                    return gov
            except Exception as exc:
                logger.debug("DownstreamBlockerGuard: could not load %s: %s", mod_name, exc)
        logger.warning("DownstreamBlockerGuard: GlobalRiskGovernor unavailable — risk gate disabled")
        return None

    @staticmethod
    def _load_slippage():
        for mod_name in ("bot.slippage_protection", "slippage_protection"):
            try:
                import importlib
                mod = importlib.import_module(mod_name)
                factory = getattr(mod, "get_slippage_protector", None)
                if factory is not None:
                    prot = factory()
                    logger.info("DownstreamBlockerGuard: SlippageProtector loaded from %s", mod_name)
                    return prot
            except Exception as exc:
                logger.debug("DownstreamBlockerGuard: could not load %s: %s", mod_name, exc)
        logger.warning("DownstreamBlockerGuard: SlippageProtector unavailable — slippage gate disabled")
        return None


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_GUARD_INSTANCE: Optional[DownstreamBlockerGuard] = None


def get_downstream_blocker_guard() -> DownstreamBlockerGuard:
    """Return the process-wide DownstreamBlockerGuard singleton."""
    global _GUARD_INSTANCE
    if _GUARD_INSTANCE is None:
        _GUARD_INSTANCE = DownstreamBlockerGuard()
    return _GUARD_INSTANCE
