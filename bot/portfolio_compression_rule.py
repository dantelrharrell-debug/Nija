"""
NIJA Portfolio Compression Rule
=================================
Fires whenever the live portfolio exceeds a configurable position-count ceiling
and selects the weakest positions for closure until the portfolio is back within
budget.

Problem It Solves
-----------------
As the bot generates new signals across 732+ markets it is possible to
accumulate far more open positions than an account's capital can support
profitably.  Many small positions → high aggregate fee cost, diluted attention
from the risk systems, and reduced average size per winner.

The Portfolio Compression Rule enforces a hard ceiling and, when breached,
executes a controlled *compression* – closing the lowest-scoring positions first
while preserving the bot's strongest open trades.

Position Scoring (0–100)
------------------------
Each open position receives a composite score based on four pillars:

1. **P&L momentum** (40 pts): Unrealised P&L as a fraction of entry.
   Strong profit = high score; strong loss = low score.
2. **Position age** (20 pts): Very old stagnant positions score lower.
3. **Size contribution** (20 pts): Larger positions (higher USD value) are more
   capital-efficient and score higher.
4. **Recency of entry** (20 pts): Very fresh positions get a grace period before
   they are eligible for compression.

Compression Modes
-----------------
SOFT:  Portfolio is 10–25 % over ceiling.  Flag the bottom N positions as
       candidates; emit recommendations but do not force immediate action.
HARD:  Portfolio is > 25 % over ceiling.  Emit mandatory CLOSE orders.
EMERGENCY: Portfolio is > 2× ceiling.  Close half the portfolio immediately
       (worst-scoring half).

Architecture
------------
::

  ┌──────────────────────────────────────────────────────────┐
  │              PortfolioCompressionRule                     │
  │                                                          │
  │  evaluate(positions) → CompressionDecision               │
  │    ├─ score_positions(positions)                         │
  │    ├─ determine_mode(count, ceiling)                     │
  │    └─ select_closures(scored, mode, excess)              │
  │                                                          │
  │  get_status() → Dict  (dashboard / health check)         │
  └──────────────────────────────────────────────────────────┘

Usage
-----
    from bot.portfolio_compression_rule import get_portfolio_compression_rule

    rule = get_portfolio_compression_rule()

    # Called before opening any new position:
    decision = rule.evaluate(open_positions)
    if decision.compression_required:
        for sym in decision.positions_to_close:
            broker.close_position(sym)

    # After a position closes:
    rule.record_compression_executed(symbol, recovered_usd)

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("nija.portfolio_compression")


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class CompressionMode(str, Enum):
    """Severity of the compression trigger."""
    NONE = "NONE"            # Within ceiling – no action
    SOFT = "SOFT"            # 10–25 % over ceiling – flag candidates
    HARD = "HARD"            # >25 % over ceiling – mandatory close
    EMERGENCY = "EMERGENCY"  # >2× ceiling – halve the portfolio


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ScoredPosition:
    """An open position augmented with its compression score."""
    symbol: str
    size_usd: float
    pnl_pct: float       # Unrealised P&L as a fraction (0.05 = +5 %)
    age_hours: float
    score: float         # 0–100; higher = keep, lower = close first
    score_breakdown: Dict[str, float]  # Pillar-level scores for diagnostics


@dataclass
class CompressionDecision:
    """Full output of a single portfolio evaluation."""
    timestamp: str
    mode: CompressionMode
    total_positions: int
    position_ceiling: int
    excess_positions: int        # How many over ceiling
    compression_required: bool
    positions_to_close: List[str]  # Symbols that should be closed (ordered: worst first)
    scored_positions: List[ScoredPosition]
    message: str

    # Session accumulators (copied from engine state)
    session_compressions: int = 0
    session_recovered_usd: float = 0.0


@dataclass
class CompressionConfig:
    """Tunable parameters for the Portfolio Compression Rule."""
    position_ceiling: int = 20           # Hard max open positions
    soft_breach_pct: float = 0.10        # +10 % above ceiling → SOFT mode
    hard_breach_pct: float = 0.25        # +25 % above ceiling → HARD mode
    emergency_multiplier: float = 2.0    # 2× ceiling → EMERGENCY mode
    grace_period_hours: float = 1.0      # Positions younger than this get a score bonus
    max_age_hours: float = 168.0         # 7 days; older = lower age score
    # Pillar weights (must sum to 1.0)
    weight_pnl: float = 0.40
    weight_age: float = 0.20
    weight_size: float = 0.20
    weight_recency: float = 0.20
    # Soft-mode: only flag bottom N % of positions
    soft_flag_bottom_pct: float = 0.30
    dry_run: bool = False                # If True, log but don't mark compression_required


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class PortfolioCompressionRule:
    """
    Evaluates the live portfolio against its position ceiling and selects
    the weakest positions for controlled closure.

    Thread-safe; use the singleton accessor ``get_portfolio_compression_rule()``.
    """

    def __init__(self, config: Optional[CompressionConfig] = None) -> None:
        self._config = config or CompressionConfig()
        self._lock = threading.Lock()

        # Session accumulators
        self._session_compressions: int = 0
        self._session_recovered_usd: float = 0.0
        self._last_decision: Optional[CompressionDecision] = None

        logger.info("📦 PortfolioCompressionRule initialised")
        logger.info("   position_ceiling     : %d", self._config.position_ceiling)
        logger.info("   soft_breach_pct      : %.0f %%", self._config.soft_breach_pct * 100)
        logger.info("   hard_breach_pct      : %.0f %%", self._config.hard_breach_pct * 100)
        logger.info("   emergency_multiplier : %.1f×", self._config.emergency_multiplier)
        logger.info("   dry_run              : %s", self._config.dry_run)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate(self, positions: List[Dict]) -> CompressionDecision:
        """
        Evaluate the portfolio and return a CompressionDecision.

        Args:
            positions: List of position dicts.  Each dict should contain at
                       minimum ``symbol``.  Optional keys that improve scoring:
                       ``size_usd`` / ``usd_value``, ``pnl_pct``,
                       ``age_hours``, ``entry_price``, ``current_price``.

        Returns:
            CompressionDecision describing the mode, which symbols to close,
            and complete scored-position data.
        """
        with self._lock:
            scored = self._score_positions(positions)
            mode, excess = self._determine_mode(len(positions))
            to_close = self._select_closures(scored, mode, excess)
            compression_required = (
                mode != CompressionMode.NONE and not self._config.dry_run
            )

            msg = self._build_message(mode, len(positions), excess, to_close)
            self._log_decision(mode, len(positions), excess, to_close, scored)

            decision = CompressionDecision(
                timestamp=datetime.now(timezone.utc).isoformat(),
                mode=mode,
                total_positions=len(positions),
                position_ceiling=self._config.position_ceiling,
                excess_positions=excess,
                compression_required=compression_required,
                positions_to_close=to_close,
                scored_positions=scored,
                message=msg,
                session_compressions=self._session_compressions,
                session_recovered_usd=self._session_recovered_usd,
            )
            self._last_decision = decision
            return decision

    def record_compression_executed(self, symbol: str, recovered_usd: float = 0.0) -> None:
        """
        Record that a recommended compression closure was carried out.

        Args:
            symbol: Symbol that was closed.
            recovered_usd: Capital recovered (mark-to-market value freed).
        """
        with self._lock:
            self._session_compressions += 1
            self._session_recovered_usd += recovered_usd
            logger.info(
                "✅ Compression executed: %s  recovered $%.2f  "
                "(session: %d compressions, $%.2f recovered)",
                symbol, recovered_usd,
                self._session_compressions, self._session_recovered_usd,
            )

    def get_last_decision(self) -> Optional[CompressionDecision]:
        """Return the most recent CompressionDecision, or None if not yet evaluated."""
        return self._last_decision

    def get_status(self) -> Dict:
        """Return a lightweight status dict suitable for health-check endpoints."""
        last = self._last_decision
        return {
            "position_ceiling": self._config.position_ceiling,
            "last_mode": last.mode.value if last else None,
            "last_total_positions": last.total_positions if last else None,
            "last_excess": last.excess_positions if last else None,
            "last_evaluated": last.timestamp if last else None,
            "session_compressions": self._session_compressions,
            "session_recovered_usd": self._session_recovered_usd,
            "dry_run": self._config.dry_run,
        }

    def update_config(self, **kwargs) -> None:
        """
        Update configuration at runtime.

        Accepted keyword arguments match fields of CompressionConfig:
        position_ceiling, soft_breach_pct, hard_breach_pct, dry_run, etc.
        """
        with self._lock:
            for key, value in kwargs.items():
                if hasattr(self._config, key):
                    setattr(self._config, key, value)
                    logger.info(
                        "⚙️  PortfolioCompressionRule config updated: %s = %s", key, value
                    )
                else:
                    logger.warning("⚠️  Unknown config key ignored: %s", key)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _score_positions(self, positions: List[Dict]) -> List[ScoredPosition]:
        """Score every position on 0–100 scale; return sorted best→worst."""
        scored: List[ScoredPosition] = []
        cfg = self._config

        # Pre-compute the largest USD value for relative size scoring
        sizes = [float(p.get("size_usd", 0) or p.get("usd_value", 0)) for p in positions]
        max_size = max(sizes) if sizes else 1.0

        for pos in positions:
            symbol = pos.get("symbol", "UNKNOWN")
            size_usd = float(pos.get("size_usd", 0) or pos.get("usd_value", 0))
            pnl_pct = float(pos.get("pnl_pct", 0) or pos.get("unrealized_pnl_pct", 0))
            age_hours = float(pos.get("age_hours", 0))

            # -- Pillar 1: P&L momentum (0–40) --
            # Map pnl_pct from [-0.20, +0.20] linearly to [0, 40]
            clamped_pnl = max(-0.20, min(0.20, pnl_pct))
            pnl_score = ((clamped_pnl + 0.20) / 0.40) * 40.0

            # -- Pillar 2: Age score (0–20) --
            # Brand-new positions get near-max; very old stagnant ones get low score
            if age_hours <= cfg.grace_period_hours:
                age_score = 20.0  # Grace period – don't compress fresh entries
            else:
                fraction_aged = min(1.0, (age_hours - cfg.grace_period_hours) / cfg.max_age_hours)
                age_score = 20.0 * (1.0 - fraction_aged)

            # -- Pillar 3: Size contribution (0–20) --
            size_score = (size_usd / max_size) * 20.0 if max_size > 0 else 10.0

            # -- Pillar 4: Recency / freshness bonus (0–20) --
            if age_hours <= cfg.grace_period_hours:
                recency_score = 20.0
            else:
                recency_score = max(0.0, 20.0 - (age_hours / cfg.max_age_hours) * 20.0)

            composite = (
                pnl_score * cfg.weight_pnl / 0.40
                + age_score * cfg.weight_age / 0.20
                + size_score * cfg.weight_size / 0.20
                + recency_score * cfg.weight_recency / 0.20
            )
            # composite is already in [0, 100] because each pillar max contribution
            # equals its weight × 100.
            composite = min(100.0, max(0.0, composite))

            scored.append(ScoredPosition(
                symbol=symbol,
                size_usd=size_usd,
                pnl_pct=pnl_pct,
                age_hours=age_hours,
                score=composite,
                score_breakdown={
                    "pnl_score": round(pnl_score, 2),
                    "age_score": round(age_score, 2),
                    "size_score": round(size_score, 2),
                    "recency_score": round(recency_score, 2),
                    "composite": round(composite, 2),
                },
            ))

        # Sort best → worst (highest score first)
        scored.sort(key=lambda s: s.score, reverse=True)
        return scored

    def _determine_mode(self, count: int) -> Tuple[CompressionMode, int]:
        """Return the compression mode and number of excess positions."""
        ceiling = self._config.position_ceiling
        if count <= ceiling:
            return CompressionMode.NONE, 0

        excess = count - ceiling
        over_pct = excess / ceiling

        if count >= ceiling * self._config.emergency_multiplier:
            return CompressionMode.EMERGENCY, excess
        if over_pct > self._config.hard_breach_pct:
            return CompressionMode.HARD, excess
        if over_pct >= self._config.soft_breach_pct:
            return CompressionMode.SOFT, excess

        # Fractionally above but below soft threshold – treat as SOFT
        return CompressionMode.SOFT, excess

    def _select_closures(
        self,
        scored: List[ScoredPosition],
        mode: CompressionMode,
        excess: int,
    ) -> List[str]:
        """Pick which symbols to close based on mode and excess count."""
        if mode == CompressionMode.NONE or not scored:
            return []

        # Positions are sorted best→worst; take from the tail
        worst_first = list(reversed(scored))

        if mode == CompressionMode.EMERGENCY:
            # Close the bottom half of the portfolio
            n = max(1, len(scored) // 2)
        elif mode == CompressionMode.HARD:
            n = excess  # Close exactly the excess
        else:  # SOFT
            # Flag the bottom soft_flag_bottom_pct of the full portfolio
            n = max(1, int(len(scored) * self._config.soft_flag_bottom_pct))
            # But cap at the excess to avoid flagging positions we don't need to
            n = min(n, max(1, excess))

        return [sp.symbol for sp in worst_first[:n]]

    @staticmethod
    def _build_message(
        mode: CompressionMode, total: int, excess: int, to_close: List[str]
    ) -> str:
        if mode == CompressionMode.NONE:
            return f"Portfolio is within ceiling ({total} positions). No compression needed."
        return (
            f"[{mode.value}] Portfolio has {total} positions ({excess} over ceiling). "
            f"Recommend closing {len(to_close)} position(s): {', '.join(to_close) or 'none'}."
        )

    def _log_decision(
        self,
        mode: CompressionMode,
        total: int,
        excess: int,
        to_close: List[str],
        scored: List[ScoredPosition],
    ) -> None:
        if mode == CompressionMode.NONE:
            logger.info(
                "✅ Portfolio compression check passed – %d positions (ceiling: %d)",
                total, self._config.position_ceiling,
            )
            return

        level = logging.WARNING if mode in (CompressionMode.HARD, CompressionMode.EMERGENCY) else logging.INFO
        logger.log(
            level,
            "📦 PORTFOLIO COMPRESSION [%s] – %d positions, %d over ceiling (%d)",
            mode.value, total, excess, self._config.position_ceiling,
        )
        logger.log(level, "   Positions to close (%d):", len(to_close))
        for sym in to_close:
            sp = next((s for s in scored if s.symbol == sym), None)
            if sp:
                logger.log(
                    level,
                    "      ❌ %-20s score=%5.1f  $%.2f  PnL %+.1f%%  age %.0fh",
                    sp.symbol, sp.score, sp.size_usd, sp.pnl_pct * 100, sp.age_hours,
                )
            else:
                logger.log(level, "      ❌ %s", sym)

        logger.log(level, "   Positions to keep (top %d):", total - len(to_close))
        keep = [s for s in scored if s.symbol not in to_close]
        for sp in keep[:5]:  # Log only top 5 to avoid log spam
            logger.log(
                level,
                "      ✅ %-20s score=%5.1f  $%.2f  PnL %+.1f%%",
                sp.symbol, sp.score, sp.size_usd, sp.pnl_pct * 100,
            )
        if len(keep) > 5:
            logger.log(level, "      … and %d more", len(keep) - 5)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_rule_instance: Optional[PortfolioCompressionRule] = None
_rule_lock = threading.Lock()


def get_portfolio_compression_rule(
    config: Optional[CompressionConfig] = None,
) -> PortfolioCompressionRule:
    """
    Return the process-wide PortfolioCompressionRule singleton.

    Thread-safe.  Pass *config* only on the first call; subsequent calls
    ignore it and return the already-created instance.
    """
    global _rule_instance
    if _rule_instance is None:
        with _rule_lock:
            if _rule_instance is None:
                _rule_instance = PortfolioCompressionRule(config)
    return _rule_instance


# ---------------------------------------------------------------------------
# CLI self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(message)s",
    )

    logger.info("=== PortfolioCompressionRule self-test ===")

    # Small ceiling so we can trigger HARD mode easily
    cfg = CompressionConfig(position_ceiling=5, dry_run=False)
    rule = get_portfolio_compression_rule(cfg)

    positions = [
        {"symbol": "BTC-USD",   "size_usd": 500.00, "pnl_pct": 0.08,  "age_hours": 4},
        {"symbol": "ETH-USD",   "size_usd": 300.00, "pnl_pct": 0.03,  "age_hours": 12},
        {"symbol": "SOL-USD",   "size_usd": 150.00, "pnl_pct": -0.01, "age_hours": 30},
        {"symbol": "ADA-USD",   "size_usd": 50.00,  "pnl_pct": -0.05, "age_hours": 72},
        {"symbol": "DOGE-USD",  "size_usd": 20.00,  "pnl_pct": -0.12, "age_hours": 120},
        {"symbol": "SHIB-USD",  "size_usd": 5.00,   "pnl_pct": -0.18, "age_hours": 150},
        {"symbol": "AVAX-USD",  "size_usd": 80.00,  "pnl_pct": 0.01,  "age_hours": 8},
        {"symbol": "MATIC-USD", "size_usd": 12.00,  "pnl_pct": -0.03, "age_hours": 48},
    ]

    decision = rule.evaluate(positions)

    print("\n=== COMPRESSION DECISION ===")
    print(f"  Mode              : {decision.mode.value}")
    print(f"  Total positions   : {decision.total_positions}")
    print(f"  Ceiling           : {decision.position_ceiling}")
    print(f"  Excess            : {decision.excess_positions}")
    print(f"  Compression req   : {decision.compression_required}")
    print(f"  Positions to close: {decision.positions_to_close}")
    print(f"\n  Message: {decision.message}")

    print("\n=== SCORED POSITIONS (best → worst) ===")
    for sp in decision.scored_positions:
        print(
            f"  {sp.symbol:20s}  score={sp.score:5.1f}  ${'%.2f' % sp.size_usd:>8}  "
            f"PnL {'%+.1f' % (sp.pnl_pct*100)}%  age={sp.age_hours:.0f}h"
        )

    # Simulate executing some compressions
    for sym in decision.positions_to_close:
        sp = next(s for s in decision.scored_positions if s.symbol == sym)
        rule.record_compression_executed(sym, sp.size_usd)

    status = rule.get_status()
    print("\n=== STATUS ===")
    for k, v in status.items():
        print(f"  {k}: {v}")

    logger.info("=== Self-test complete ===")
    sys.exit(0)
