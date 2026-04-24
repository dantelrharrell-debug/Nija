"""
NIJA Strategy Voter
====================

**Priority-3 gate** -- improves accuracy by requiring multi-strategy consensus
before allowing a trade entry.

Wraps :class:`HedgeFundStrategyRouter` and evaluates whether a sufficient
number of independent sub-strategies agree on the direction *and* that the
aggregate confidence clears a minimum threshold.

Gate logic
----------
* ``min_quorum``      -- number of strategies that must vote for the same
  direction (default 2).
* ``min_confidence``  -- minimum aggregate confidence score 0.0-1.0 (default
  0.55 = 55 %).

When ``df`` is ``None`` or the underlying router is unavailable, the voter
**passes through** (fail-open) so it does not block systems that use a
different signal source.

Usage
-----
::

    from bot.strategy_voter import get_strategy_voter

    voter = get_strategy_voter()

    result = voter.vote(
        df=df,
        symbol="BTC-USD",
        indicators=indicators,
        regime="TRENDING",
    )
    if not result.approved:
        logger.info("Strategy voter rejected: %s", result.reason)
        return

    side = result.action   # "long" or "short"
    confidence = result.confidence

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Dict, Optional

logger = logging.getLogger("nija.strategy_voter")


# ---------------------------------------------------------------------------
# Public result type
# ---------------------------------------------------------------------------


@dataclass
class VoteResult:
    """Decision returned by :class:`StrategyVoter.vote`."""

    approved: bool
    action: str            # "long", "short", or "no_trade"
    confidence: float      # 0.0 - 1.0
    vote_count: int        # how many strategies agreed
    reason: str
    symbol: str = ""
    metadata: Dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Voter
# ---------------------------------------------------------------------------


class StrategyVoter:
    """Priority-3 gate: multi-strategy consensus voting.

    Thread-safe singleton via ``get_strategy_voter()``.
    """

    def __init__(
        self,
        min_quorum: int = 2,
        min_confidence: float = 0.55,
    ) -> None:
        self._min_quorum = min_quorum
        self._min_confidence = min_confidence
        self._lock = threading.Lock()
        self._router = self._load_router()

        logger.info(
            "StrategyVoter initialised | min_quorum=%d | min_confidence=%.0f%%",
            min_quorum,
            min_confidence * 100,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def vote(
        self,
        df=None,
        symbol: str = "",
        indicators: Optional[Dict] = None,
        regime: str = "DEFAULT",
        df_pair=None,
        pair_symbol: Optional[str] = None,
    ) -> VoteResult:
        """Ask all registered sub-strategies to vote on the current bar.

        Parameters
        ----------
        df:
            OHLCV DataFrame for the primary symbol.  When ``None`` the voter
            passes through (fail-open) so systems without DataFrames are not
            blocked.
        symbol:
            Instrument identifier used for logging.
        indicators:
            Pre-computed indicator dict (e.g. from RSI/ATR calculation).
        regime:
            Current market regime string passed to regime-aware strategies.
        df_pair / pair_symbol:
            Optional second asset for statistical-arbitrage strategies.

        Returns
        -------
        VoteResult
            ``.approved`` is ``True`` when quorum AND confidence are met.
        """
        if df is None:
            return VoteResult(
                approved=True,
                action="no_signal",
                confidence=0.0,
                vote_count=0,
                reason="No DataFrame provided -- passing through (fail-open)",
                symbol=symbol,
            )

        router = self._router
        if router is None:
            return VoteResult(
                approved=True,
                action="no_signal",
                confidence=0.0,
                vote_count=0,
                reason="HedgeFundStrategyRouter unavailable -- passing through",
                symbol=symbol,
            )

        try:
            consensus = router.get_consensus_signal(
                df=df,
                symbol=symbol,
                indicators=indicators or {},
                regime=regime,
                df_pair=df_pair,
                pair_symbol=pair_symbol,
            )
        except Exception as exc:
            logger.warning("StrategyVoter: router error for %s: %s", symbol, exc)
            return VoteResult(
                approved=True,
                action="no_signal",
                confidence=0.0,
                vote_count=0,
                reason=f"Router error ({exc}) -- passing through",
                symbol=symbol,
            )

        return self._evaluate(consensus, symbol)

    def update_quorum(self, min_quorum: int, min_confidence: float) -> None:
        """Dynamically adjust gate thresholds (thread-safe)."""
        with self._lock:
            self._min_quorum = min_quorum
            self._min_confidence = min_confidence
        logger.info(
            "StrategyVoter thresholds updated | quorum=%d | confidence=%.0f%%",
            min_quorum, min_confidence * 100,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _evaluate(self, consensus: Dict, symbol: str) -> VoteResult:
        """Translate a HedgeFundStrategyRouter consensus dict into a VoteResult."""
        with self._lock:
            min_quorum = self._min_quorum
            min_confidence = self._min_confidence

        action = consensus.get("action", "no_trade")
        confidence = float(consensus.get("confidence", 0.0))
        vote_count = int(consensus.get("vote_count", consensus.get("active_votes", 0)))
        metadata = {k: v for k, v in consensus.items()
                    if k not in ("action", "confidence", "vote_count")}

        # Gate 1 -- quorum
        if vote_count < min_quorum:
            reason = (
                f"Strategy quorum not met: {vote_count}/{min_quorum} votes "
                f"(action={action}, confidence={confidence:.0%})"
            )
            logger.info("StrategyVoter REJECTED (quorum) | %s | %s", symbol, reason)
            return VoteResult(
                approved=False,
                action=action,
                confidence=confidence,
                vote_count=vote_count,
                reason=reason,
                symbol=symbol,
                metadata=metadata,
            )

        # Gate 2 -- confidence
        if confidence < min_confidence:
            reason = (
                f"Strategy confidence too low: {confidence:.0%} < {min_confidence:.0%} "
                f"({vote_count} votes for {action})"
            )
            logger.info("StrategyVoter REJECTED (confidence) | %s | %s", symbol, reason)
            return VoteResult(
                approved=False,
                action=action,
                confidence=confidence,
                vote_count=vote_count,
                reason=reason,
                symbol=symbol,
                metadata=metadata,
            )

        # Gate 3 -- direction must be actionable
        if action not in ("long", "short", "buy", "sell"):
            reason = (
                f"No actionable direction: action={action!r} "
                f"(confidence={confidence:.0%}, votes={vote_count})"
            )
            logger.debug("StrategyVoter REJECTED (no direction) | %s | %s", symbol, reason)
            return VoteResult(
                approved=False,
                action=action,
                confidence=confidence,
                vote_count=vote_count,
                reason=reason,
                symbol=symbol,
                metadata=metadata,
            )

        reason = (
            f"Consensus approved: {vote_count} votes for {action!r} "
            f"at {confidence:.0%} confidence"
        )
        logger.info("StrategyVoter APPROVED | %s | %s", symbol, reason)
        return VoteResult(
            approved=True,
            action=action,
            confidence=confidence,
            vote_count=vote_count,
            reason=reason,
            symbol=symbol,
            metadata=metadata,
        )

    @staticmethod
    def _load_router():
        """Load HedgeFundStrategyRouter singleton (graceful if absent)."""
        for mod_name in ("bot.hedge_fund_strategies", "hedge_fund_strategies"):
            try:
                mod = __import__(mod_name, fromlist=["HedgeFundStrategyRouter"])
                router = mod.HedgeFundStrategyRouter()
                logger.info("StrategyVoter: router loaded from %s", mod_name)
                return router
            except Exception as exc:
                logger.debug("StrategyVoter: could not load %s: %s", mod_name, exc)
        logger.warning(
            "StrategyVoter: HedgeFundStrategyRouter unavailable -- voter is pass-through"
        )
        return None


# ---------------------------------------------------------------------------
# Singleton factory
# ---------------------------------------------------------------------------

_instance: Optional[StrategyVoter] = None
_instance_lock = threading.Lock()


def get_strategy_voter(
    min_quorum: int = 2,
    min_confidence: float = 0.55,
) -> StrategyVoter:
    """Return the process-wide :class:`StrategyVoter` singleton.

    Parameters
    ----------
    min_quorum / min_confidence:
        Only used on the **first** call; ignored on subsequent calls.
    """
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = StrategyVoter(
                    min_quorum=min_quorum,
                    min_confidence=min_confidence,
                )
    return _instance
