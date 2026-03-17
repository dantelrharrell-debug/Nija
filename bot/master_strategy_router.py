"""
NIJA Master Strategy Router
============================

Orchestrates all active strategies for a given symbol and returns a single
consensus trade signal.  The **StrategyVoter** gate (Priority-3) is wired in
here: signals that do not achieve multi-strategy quorum + confidence are
rejected before they reach execution.

Architecture
------------
::

    MasterStrategyRouter.get_signal(df, symbol, regime)
        |
        +-- (1) HedgeFundStrategyRouter  [existing strategies]
        |         TrendFollowing / MeanReversion / Momentum / Macro / StatArb
        |
        +-- (2) StrategyVoter gate  [Priority-3: quorum + confidence check]
        |         approved? -- YES --> return VoteResult
        |                   -- NO  --> return no-trade signal
        |
        +-- (3) NIJA APEX dual-RSI strategy  [supplemental signal, optional]

The router is the canonical entry point called by everything upstream
(ExecutionPipeline, SignalBroadcaster, TradingStrategy).

Usage
-----
::

    from bot.master_strategy_router import get_master_strategy_router

    router = get_master_strategy_router()
    signal = router.get_signal(df=df, symbol="BTC-USD", regime="TRENDING")

    if signal.approved:
        # signal.action  -- "long" | "short"
        # signal.confidence  -- 0.0-1.0
        # proceed to ExecutionPipeline
        ...

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Dict, Optional

logger = logging.getLogger("nija.master_strategy_router")


# ---------------------------------------------------------------------------
# Public result type
# ---------------------------------------------------------------------------


@dataclass
class RouterSignal:
    """Unified signal returned by :class:`MasterStrategyRouter.get_signal`."""

    approved: bool          # False => do NOT enter a trade
    action: str             # "long", "short", or "no_trade"
    confidence: float       # 0.0 - 1.0
    vote_count: int
    reason: str
    symbol: str = ""
    regime: str = ""
    metadata: Dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


class MasterStrategyRouter:
    """Consensus strategy router with integrated StrategyVoter (Priority-3) gate.

    Thread-safe singleton via ``get_master_strategy_router()``.
    """

    def __init__(
        self,
        min_quorum: int = 2,
        min_confidence: float = 0.55,
    ) -> None:
        self._lock = threading.Lock()
        self._voter = self._load_voter(min_quorum, min_confidence)
        self._apex = self._load_apex()

        logger.info(
            "MasterStrategyRouter initialised | StrategyVoter wired=%s | ApexRSI wired=%s",
            self._voter is not None,
            self._apex is not None,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_signal(
        self,
        df=None,
        symbol: str = "",
        indicators: Optional[Dict] = None,
        regime: str = "DEFAULT",
        df_pair=None,
        pair_symbol: Optional[str] = None,
    ) -> RouterSignal:
        """Evaluate all strategies and return a consensus signal.

        Parameters
        ----------
        df:
            OHLCV DataFrame.  May be ``None`` when called without market data
            (vote result will pass through with ``approved=True``).
        symbol:
            Trading symbol, e.g. ``"BTC-USD"``.
        indicators:
            Pre-computed technical indicator dict (ATR, RSI, ADX, etc.).
        regime:
            Market regime string for regime-aware weighting.
        df_pair / pair_symbol:
            Second asset for StatArb voting (optional).

        Returns
        -------
        RouterSignal
            When ``approved`` is ``False`` the caller should NOT enter a trade.
        """
        # ── Priority-3: Strategy Voter ───────────────────────────────────
        voter = self._voter
        if voter is None:
            # No voter available -- pass through
            vote = _passthrough_vote(symbol)
        else:
            try:
                vote = voter.vote(
                    df=df,
                    symbol=symbol,
                    indicators=indicators,
                    regime=regime,
                    df_pair=df_pair,
                    pair_symbol=pair_symbol,
                )
            except Exception as exc:
                logger.warning(
                    "MasterStrategyRouter: StrategyVoter error for %s: %s -- passing through",
                    symbol, exc,
                )
                vote = _passthrough_vote(symbol)

        if not vote.approved:
            return RouterSignal(
                approved=False,
                action=vote.action,
                confidence=vote.confidence,
                vote_count=vote.vote_count,
                reason=vote.reason,
                symbol=symbol,
                regime=regime,
                metadata=vote.metadata,
            )

        # ── Supplemental: APEX dual-RSI (optional tie-breaker) ──────────
        apex_meta: Dict = {}
        if self._apex is not None and df is not None:
            try:
                apex_result = self._apex.analyze(df, symbol=symbol)
                if isinstance(apex_result, dict):
                    apex_meta = {
                        "apex_signal": apex_result.get("signal", ""),
                        "apex_rsi_9": apex_result.get("rsi_9"),
                        "apex_rsi_14": apex_result.get("rsi_14"),
                    }
            except Exception as exc:
                logger.debug("MasterStrategyRouter: APEX analysis skipped: %s", exc)

        return RouterSignal(
            approved=True,
            action=vote.action,
            confidence=vote.confidence,
            vote_count=vote.vote_count,
            reason=vote.reason,
            symbol=symbol,
            regime=regime,
            metadata={**vote.metadata, **apex_meta},
        )

    def update_thresholds(
        self, min_quorum: int, min_confidence: float
    ) -> None:
        """Dynamically update the StrategyVoter thresholds."""
        if self._voter is not None:
            self._voter.update_quorum(min_quorum, min_confidence)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _load_voter(min_quorum: int, min_confidence: float):
        """Load the StrategyVoter (Priority-3 gate)."""
        try:
            from bot.strategy_voter import get_strategy_voter  # type: ignore
            return get_strategy_voter(
                min_quorum=min_quorum,
                min_confidence=min_confidence,
            )
        except ImportError:
            pass
        try:
            from strategy_voter import get_strategy_voter  # type: ignore
            return get_strategy_voter(
                min_quorum=min_quorum,
                min_confidence=min_confidence,
            )
        except ImportError:
            logger.warning("MasterStrategyRouter: StrategyVoter not found -- voter gate disabled")
            return None

    @staticmethod
    def _load_apex():
        """Load the APEX dual-RSI strategy (optional tie-breaker)."""
        for mod_name, cls_name in [
            ("bot.nija_apex_strategy_v71", "NijaApexStrategyV71"),
            ("nija_apex_strategy_v71", "NijaApexStrategyV71"),
            ("bot.trading_strategy", "TradingStrategy"),
        ]:
            try:
                mod = __import__(mod_name, fromlist=[cls_name])
                cls = getattr(mod, cls_name, None)
                if cls is not None:
                    return cls()
            except Exception:
                pass
        return None


# ---------------------------------------------------------------------------
# Passthrough helper
# ---------------------------------------------------------------------------


def _passthrough_vote(symbol: str):
    """Return an approved VoteResult-like object (used when voter is absent)."""
    from types import SimpleNamespace
    return SimpleNamespace(
        approved=True,
        action="no_signal",
        confidence=0.0,
        vote_count=0,
        reason="no voter available -- passing through",
        metadata={},
    )


# ---------------------------------------------------------------------------
# Singleton factory
# ---------------------------------------------------------------------------

_instance: Optional[MasterStrategyRouter] = None
_instance_lock = threading.Lock()


def get_master_strategy_router(
    min_quorum: int = 2,
    min_confidence: float = 0.55,
) -> MasterStrategyRouter:
    """Return the process-wide :class:`MasterStrategyRouter` singleton."""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = MasterStrategyRouter(
                    min_quorum=min_quorum,
                    min_confidence=min_confidence,
                )
    return _instance
