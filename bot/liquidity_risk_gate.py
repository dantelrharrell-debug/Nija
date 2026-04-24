"""
NIJA Liquidity Risk Gate
=========================

Pre-trade liquidity guardrail that enforces a strict cap on how large any
single trade can be relative to the market's recent daily trading volume.

Rule
----
::

    trade_size_usd / daily_volume_usd  ≤  MAX_TRADE_SIZE_RATIO  (default 1 %)

Why 1 %?
~~~~~~~~
Trading more than 1 % of a market's daily volume causes:

* **Slippage** — the order walks the book and fills at increasingly worse prices.
* **Liquidity traps** — position can't be exited without moving the market.
* **Small-market blowups** — micro-cap crypto and thin altcoins can be gamed
  or manipulated by any single large participant.

Architecture
------------
::

  ┌───────────────────────────────────────────────────────────┐
  │                   LiquidityRiskGate                        │
  │                                                            │
  │  Inputs                                                    │
  │  ├── symbol          (str)                                 │
  │  ├── trade_size_usd  (float)                               │
  │  └── daily_volume_usd (float)                              │
  │                                                            │
  │  Logic                                                     │
  │  ├── ratio = trade_size_usd / daily_volume_usd             │
  │  ├── ratio > warn_ratio  → WARN + proportional reduction   │
  │  ├── ratio > max_ratio   → BLOCK  (hard fail)              │
  │  └── ratio ≤ warn_ratio  → PASS                            │
  │                                                            │
  │  Outputs                                                   │
  │  ├── LiquidityGateDecision                                 │
  │  │   ├── allowed           (bool)                          │
  │  │   ├── adjusted_size_usd (float)                         │
  │  │   ├── ratio             (float)  trade/volume           │
  │  │   ├── reason            (str)                           │
  │  │   └── size_multiplier   (float)  0.0 – 1.0             │
  │  └── JSON-lines audit log                                  │
  │      data/liquidity_risk_gate_decisions.jsonl              │
  └───────────────────────────────────────────────────────────┘

Usage
-----
    from bot.liquidity_risk_gate import get_liquidity_risk_gate

    gate = get_liquidity_risk_gate()

    decision = gate.approve_trade(
        symbol="DOGE-USD",
        trade_size_usd=500.0,
        daily_volume_usd=50_000.0,
    )
    if not decision.allowed:
        logger.warning("Liquidity gate blocked: %s", decision.reason)
        return

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger("nija.liquidity_risk_gate")

# ---------------------------------------------------------------------------
# Constants – overridable via constructor kwargs
# ---------------------------------------------------------------------------

DEFAULT_MAX_TRADE_RATIO: float = 0.01   # hard block above 1% of daily volume
DEFAULT_WARN_TRADE_RATIO: float = 0.005 # soft warning above 0.5% of daily volume

DATA_DIR = Path(__file__).parent.parent / "data"


# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------

@dataclass
class LiquidityGateDecision:
    """
    Result returned by :meth:`LiquidityRiskGate.approve_trade`.

    Attributes
    ----------
    allowed : bool
        ``True`` when the trade may proceed (possibly with a reduced size).
    symbol : str
        Instrument identifier.
    trade_size_usd : float
        Originally proposed position size in USD.
    daily_volume_usd : float
        24-hour market volume in USD used for the check.
    ratio : float
        ``trade_size_usd / daily_volume_usd`` (0.0 – ∞).  Values above
        ``max_trade_ratio`` will block; values above ``warn_trade_ratio``
        trigger a proportional size reduction.
    adjusted_size_usd : float
        Size after any gate-imposed reduction.  Equal to ``trade_size_usd``
        when no reduction is applied.
    size_multiplier : float
        ``adjusted_size_usd / trade_size_usd`` (0.0 – 1.0).
    reason : str
        Human-readable explanation of the decision.
    timestamp : str
        ISO-8601 UTC timestamp of the decision.
    """

    allowed: bool
    symbol: str
    trade_size_usd: float
    daily_volume_usd: float
    ratio: float
    adjusted_size_usd: float
    size_multiplier: float
    reason: str
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class LiquidityRiskGate:
    """
    Enforces a hard cap: ``trade_size_usd / daily_volume_usd ≤ max_trade_ratio``.

    Thread-safe; designed to be used as a process-wide singleton via
    :func:`get_liquidity_risk_gate`.

    Parameters
    ----------
    max_trade_ratio : float
        Hard limit — trades above this ratio are blocked entirely (default 0.01
        → 1 % of daily volume).
    warn_trade_ratio : float
        Soft limit — trades above this ratio are allowed but have their size
        proportionally reduced to the warn threshold (default 0.005 → 0.5 %).
    """

    def __init__(
        self,
        max_trade_ratio: float = DEFAULT_MAX_TRADE_RATIO,
        warn_trade_ratio: float = DEFAULT_WARN_TRADE_RATIO,
    ) -> None:
        if warn_trade_ratio >= max_trade_ratio:
            raise ValueError(
                f"warn_trade_ratio ({warn_trade_ratio}) must be < max_trade_ratio ({max_trade_ratio})"
            )
        self.max_trade_ratio = max_trade_ratio
        self.warn_trade_ratio = warn_trade_ratio
        self._lock = threading.Lock()

        # Audit log
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._log_path = DATA_DIR / "liquidity_risk_gate_decisions.jsonl"

        logger.info(
            "LiquidityRiskGate ready | max=%.1f%% of daily volume | warn=%.1f%%",
            max_trade_ratio * 100,
            warn_trade_ratio * 100,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def approve_trade(
        self,
        symbol: str,
        trade_size_usd: float,
        daily_volume_usd: float,
    ) -> LiquidityGateDecision:
        """
        Evaluate whether the proposed trade size is acceptable relative to the
        market's daily trading volume.

        Parameters
        ----------
        symbol : str
            Instrument identifier (e.g. ``"DOGE-USD"``).
        trade_size_usd : float
            Proposed position size in USD.
        daily_volume_usd : float
            Market's 24-hour trading volume in USD.  Must be > 0.

        Returns
        -------
        LiquidityGateDecision
            ``allowed=True`` when the trade may proceed.  The
            ``adjusted_size_usd`` field contains the gate-approved size
            (may be smaller than ``trade_size_usd``).

        Notes
        -----
        When ``daily_volume_usd`` is zero or negative the gate **fails open**
        (allows the trade unchanged) but logs a warning, because blocking all
        trades due to missing data would be too conservative.
        """
        with self._lock:
            # Guard against missing volume data
            if daily_volume_usd <= 0:
                logger.warning(
                    "LiquidityRiskGate: daily_volume_usd=%.2f for %s — gate fails open",
                    daily_volume_usd,
                    symbol,
                )
                decision = LiquidityGateDecision(
                    allowed=True,
                    symbol=symbol,
                    trade_size_usd=trade_size_usd,
                    daily_volume_usd=daily_volume_usd,
                    ratio=0.0,
                    adjusted_size_usd=trade_size_usd,
                    size_multiplier=1.0,
                    reason="volume data unavailable — gate fails open",
                )
                self._log_decision(decision)
                return decision

            ratio = trade_size_usd / daily_volume_usd

            # Hard block — trade exceeds max ratio
            if ratio > self.max_trade_ratio:
                reason = (
                    f"trade_size ({trade_size_usd:,.2f} USD) is "
                    f"{ratio:.2%} of daily_volume ({daily_volume_usd:,.0f} USD), "
                    f"exceeding max {self.max_trade_ratio:.1%}"
                )
                decision = LiquidityGateDecision(
                    allowed=False,
                    symbol=symbol,
                    trade_size_usd=trade_size_usd,
                    daily_volume_usd=daily_volume_usd,
                    ratio=round(ratio, 6),
                    adjusted_size_usd=0.0,
                    size_multiplier=0.0,
                    reason=reason,
                )
                logger.warning("LiquidityRiskGate BLOCKED %s: %s", symbol, reason)
                self._log_decision(decision)
                return decision

            # Soft warning — reduce size to the warn threshold
            if ratio > self.warn_trade_ratio:
                # Cap the trade size at warn_trade_ratio × daily_volume
                capped_size = self.warn_trade_ratio * daily_volume_usd
                multiplier = capped_size / trade_size_usd if trade_size_usd > 0 else 1.0
                reason = (
                    f"trade_size ({trade_size_usd:,.2f} USD) is "
                    f"{ratio:.2%} of daily_volume — reduced to "
                    f"{self.warn_trade_ratio:.1%} cap ({capped_size:,.2f} USD)"
                )
                decision = LiquidityGateDecision(
                    allowed=True,
                    symbol=symbol,
                    trade_size_usd=trade_size_usd,
                    daily_volume_usd=daily_volume_usd,
                    ratio=round(ratio, 6),
                    adjusted_size_usd=round(capped_size, 2),
                    size_multiplier=round(multiplier, 4),
                    reason=reason,
                )
                logger.info("LiquidityRiskGate REDUCED %s: %s", symbol, reason)
                self._log_decision(decision)
                return decision

            # Pass — within limits
            reason = (
                f"trade_size ({trade_size_usd:,.2f} USD) is "
                f"{ratio:.3%} of daily_volume ({daily_volume_usd:,.0f} USD) — within "
                f"{self.max_trade_ratio:.1%} limit"
            )
            decision = LiquidityGateDecision(
                allowed=True,
                symbol=symbol,
                trade_size_usd=trade_size_usd,
                daily_volume_usd=daily_volume_usd,
                ratio=round(ratio, 6),
                adjusted_size_usd=trade_size_usd,
                size_multiplier=1.0,
                reason=reason,
            )
            logger.debug("LiquidityRiskGate PASSED %s: %s", symbol, reason)
            self._log_decision(decision)
            return decision

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def max_safe_trade_usd(self, daily_volume_usd: float) -> float:
        """
        Return the maximum trade size (USD) that will pass the hard limit for
        a market with the given ``daily_volume_usd``.
        """
        return self.max_trade_ratio * daily_volume_usd

    def warn_safe_trade_usd(self, daily_volume_usd: float) -> float:
        """
        Return the trade size (USD) below which no size reduction will be
        applied for a market with the given ``daily_volume_usd``.
        """
        return self.warn_trade_ratio * daily_volume_usd

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _log_decision(self, decision: LiquidityGateDecision) -> None:
        """Append the decision as a JSON-lines record to the audit log."""
        try:
            record = {
                "timestamp": decision.timestamp,
                "symbol": decision.symbol,
                "allowed": decision.allowed,
                "trade_size_usd": decision.trade_size_usd,
                "daily_volume_usd": decision.daily_volume_usd,
                "ratio": decision.ratio,
                "adjusted_size_usd": decision.adjusted_size_usd,
                "size_multiplier": decision.size_multiplier,
                "reason": decision.reason,
            }
            with self._log_path.open("a") as fh:
                fh.write(json.dumps(record) + "\n")
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_gate_instance: Optional[LiquidityRiskGate] = None
_gate_lock = threading.Lock()


def get_liquidity_risk_gate(
    max_trade_ratio: float = DEFAULT_MAX_TRADE_RATIO,
    warn_trade_ratio: float = DEFAULT_WARN_TRADE_RATIO,
) -> LiquidityRiskGate:
    """
    Return the process-wide :class:`LiquidityRiskGate` singleton.

    Parameters are only applied on first creation; subsequent calls return the
    existing instance regardless of the arguments passed.
    """
    global _gate_instance
    with _gate_lock:
        if _gate_instance is None:
            _gate_instance = LiquidityRiskGate(
                max_trade_ratio=max_trade_ratio,
                warn_trade_ratio=warn_trade_ratio,
            )
            logger.info("LiquidityRiskGate singleton created")
    return _gate_instance


__all__ = [
    "LiquidityGateDecision",
    "LiquidityRiskGate",
    "get_liquidity_risk_gate",
    "DEFAULT_MAX_TRADE_RATIO",
    "DEFAULT_WARN_TRADE_RATIO",
]
