"""
NIJA Master Strategy Router
============================

Orchestrates all active strategies for a given symbol and returns a single
consensus trade signal.  The **StrategyVoter** gate (Priority-3) is wired in
here: signals that do not achieve multi-strategy quorum + confidence are
rejected before they reach execution.

Provides a single authoritative trading signal shared across all registered
broker accounts so that every account reacts to ONE master decision rather
than each account running its own independent strategy.

Architecture
------------
::

    MasterStrategyRouter.get_signal(df, symbol, regime)
        |
        +-- (1) HedgeFundStrategyRouter  [existing strategies]
        |         TrendFollowing / MeanReversion / Momentum / Macro / StatArb
        |
        +-- (2) StrategyVoter gate  [Priority-3: quorum + confidence check]
        |         approved? -- YES --> return RouterSignal
        |                   -- NO  --> return no-trade RouterSignal
        |
        +-- (3) NIJA APEX dual-RSI strategy  [supplemental signal, optional]
        |
        +-- (4) Stored master signal  [broadcast from platform account via update()]

    ┌─────────────────────────────────────────────────────────┐
    │               MasterStrategyRouter (singleton)           │
    │                                                         │
    │  current_signal: dict | None                            │
    │                                                         │
    │  update(signal)   ← called by the MASTER/platform       │
    │                     account after analyze_market()       │
    │                                                         │
    │  get_signal(df, symbol, ...)  → evaluates via voter     │
    │  get_signal()                 → returns stored signal   │
    └─────────────────────────────────────────────────────────┘

Usage
-----
::

    from bot.master_strategy_router import get_master_strategy_router

    router = get_master_strategy_router()

    # ── Fresh consensus evaluation (platform account): ───────────────────
    signal = router.get_signal(df=df, symbol="BTC-USD", regime="TRENDING")
    if signal.approved:
        router.update(signal.metadata)   # broadcast to user accounts

    # ── User accounts read the stored master signal: ─────────────────────
    signal = router.get_signal()          # no df → returns stored signal
    action = signal.action if signal else "hold"

Author: NIJA Trading Systems
Version: 2.0
Date: March 2026
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional

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
    """Unified master strategy coordinator.

    Responsibilities
    ----------------
    1. **Consensus gate** – evaluates market data against all registered
       strategies via ``StrategyVoter``; blocks low-confidence signals.
    2. **Signal broadcast** – the platform account calls ``update()`` after
       its analysis; all user accounts then call ``get_signal()`` (without
       market data) to read the same master decision.
    3. **APEX tie-breaker** – APEX dual-RSI adds supplemental metadata when
       the StrategyVoter approves a signal.

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

        # Stored master signal — broadcast by the platform account and read
        # by all user accounts so every broker acts on ONE coordinated decision.
        self._current_signal: Optional[Dict[str, Any]] = None
        self._last_updated: Optional[str] = None

        logger.info(
            "MasterStrategyRouter initialised | StrategyVoter wired=%s | ApexRSI wired=%s",
            self._voter is not None,
            self._apex is not None,
        )

    # ------------------------------------------------------------------
    # Public API — consensus evaluation
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
        """Return a trading signal.

        Behaviour
        ---------
        * **With** ``df`` (market data) — runs the full StrategyVoter
          consensus evaluation and APEX supplemental analysis.
        * **Without** ``df`` — returns the most-recently stored master signal
          (set via ``update()``).  Returns a ``no_trade`` RouterSignal when no
          signal has been broadcast yet.

        Parameters
        ----------
        df:
            OHLCV DataFrame.  Pass ``None`` to retrieve the stored signal.
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
            ``approved=False`` means the caller should NOT enter a trade.
        """
        # ── Stored-signal path (no market data) ─────────────────────────
        if df is None:
            with self._lock:
                stored = self._current_signal
            if stored is None:
                return RouterSignal(
                    approved=False,
                    action="no_trade",
                    confidence=0.0,
                    vote_count=0,
                    reason="no master signal broadcast yet",
                    symbol=symbol,
                    regime=regime,
                )
            return RouterSignal(
                approved=stored.get("approved", True),
                action=stored.get("action", "no_trade"),
                confidence=stored.get("confidence", 0.0),
                vote_count=stored.get("vote_count", 0),
                reason=stored.get("reason", "stored master signal"),
                symbol=stored.get("symbol", symbol),
                regime=stored.get("regime", regime),
                metadata=stored.get("metadata", {}),
            )

        # ── Live-evaluation path ─────────────────────────────────────────
        # Priority-3: Strategy Voter
        voter = self._voter
        if voter is None:
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

        # Supplemental: APEX dual-RSI (optional tie-breaker)
        apex_meta: Dict = {}
        if self._apex is not None:
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

    # ------------------------------------------------------------------
    # Public API — signal broadcast (platform → all accounts)
    # ------------------------------------------------------------------

    def update(self, signal: Dict[str, Any]) -> None:
        """Store the latest signal from the master (platform) account.

        Called by the platform account after ``analyze_market()`` or after
        evaluating ``get_signal(df=df, ...)``.  All user accounts then call
        ``get_signal()`` (no args) to read this shared decision.

        Args:
            signal: Analysis dict containing at minimum ``{'action': str}``.
                    A ``RouterSignal`` can be passed directly (it will be
                    converted to a plain dict via its ``__dict__``).
        """
        if isinstance(signal, RouterSignal):
            payload: Dict[str, Any] = {
                "approved": signal.approved,
                "action": signal.action,
                "confidence": signal.confidence,
                "vote_count": signal.vote_count,
                "reason": signal.reason,
                "symbol": signal.symbol,
                "regime": signal.regime,
                "metadata": signal.metadata,
            }
        else:
            payload = dict(signal)

        with self._lock:
            self._current_signal = payload
            self._last_updated = datetime.now(timezone.utc).isoformat()
            action = payload.get("action", "hold")
            logger.debug(
                "[MasterRouter] signal updated → action=%s at %s",
                action, self._last_updated,
            )

    def clear(self) -> None:
        """Reset the stored signal (call at the start of each trading cycle)."""
        with self._lock:
            self._current_signal = None
            self._last_updated = None
        logger.debug("[MasterRouter] stored signal cleared")

    @property
    def current_signal(self) -> Optional[Dict[str, Any]]:
        """The most recently broadcast master signal dict, or ``None``."""
        with self._lock:
            return self._current_signal

    @property
    def last_updated(self) -> Optional[str]:
        """ISO-8601 UTC timestamp of the last ``update()`` call, or ``None``."""
        with self._lock:
            return self._last_updated

    def update_thresholds(
        self, min_quorum: int, min_confidence: float
    ) -> None:
        """Dynamically update the StrategyVoter quorum / confidence thresholds."""
        if self._voter is not None:
            self._voter.update_quorum(min_quorum, min_confidence)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _load_voter(min_quorum: int, min_confidence: float):
        """Load the StrategyVoter (Priority-3 gate)."""
        for mod_name in ("bot.strategy_voter", "strategy_voter"):
            try:
                mod = __import__(mod_name, fromlist=["get_strategy_voter"])
                return mod.get_strategy_voter(
                    min_quorum=min_quorum,
                    min_confidence=min_confidence,
                )
            except ImportError:
                continue
            except Exception as exc:
                logger.warning(
                    "MasterStrategyRouter: StrategyVoter load error (%s): %s -- trying next path",
                    mod_name, exc,
                )
                continue
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

_ROUTER: Optional[MasterStrategyRouter] = None
_ROUTER_LOCK = threading.Lock()


def get_master_strategy_router(
    min_quorum: int = 2,
    min_confidence: float = 0.55,
) -> MasterStrategyRouter:
    """Return the process-wide :class:`MasterStrategyRouter` singleton."""
    global _ROUTER
    if _ROUTER is None:
        with _ROUTER_LOCK:
            if _ROUTER is None:
                _ROUTER = MasterStrategyRouter(
                    min_quorum=min_quorum,
                    min_confidence=min_confidence,
                )
                logger.info(
                    "[MasterRouter] singleton created — one master signal for all accounts"
                )
    return _ROUTER
