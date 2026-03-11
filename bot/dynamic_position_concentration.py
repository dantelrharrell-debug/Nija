"""
NIJA Dynamic Position Concentration
======================================

Enforces portfolio-level diversification by dynamically capping how much any
single position (or sector/cluster) can represent relative to overall exposure.
Uses the Herfindahl-Hirschman Index (HHI) as the primary concentration metric.

Architecture
------------
::

  ┌───────────────────────────────────────────────────────────────────┐
  │                  DynamicPositionConcentration                      │
  │                                                                    │
  │  Metrics computed from current position snapshot:                  │
  │                                                                    │
  │  • Herfindahl Index (HHI) – sum of squared portfolio weights       │
  │    0 = perfectly diversified, 1 = fully concentrated              │
  │                                                                    │
  │  • Max Single Weight – largest position / total exposure           │
  │                                                                    │
  │  • Effective N – 1/HHI; number of equal-risk positions implied    │
  │                                                                    │
  │  Capital-Tier Base Cap (scales with account balance):             │
  │    Balance < $100    → 25% (micro-cap)                            │
  │    Balance $100–$500 → 20%                                        │
  │    Balance $500–$2k  → 15%                                        │
  │    Balance $2k+      → 10% (mature account)                       │
  │                                                                    │
  │  Dynamic Caps (scale with HHI, applied on top of tier cap):      │
  │    HHI ≤ 0.10  → tier_cap (e.g. 25% for micro accounts)          │
  │    0.10–0.20   → tier_cap × 0.85                                  │
  │    0.20–0.30   → tier_cap × 0.70                                  │
  │    0.30–0.50   → tier_cap × 0.50                                  │
  │    HHI > 0.50  → tier_cap × 0.30 (high concentration penalty)    │
  │                                                                    │
  │  approve_entry() returns ConcentrationDecision with               │
  │  allowed flag, max_allowed_usd, adjusted_size, and explanation    │
  │                                                                    │
  │  Audit: data/concentration_decisions.jsonl                        │
  └───────────────────────────────────────────────────────────────────┘

Usage
-----
    from bot.dynamic_position_concentration import get_dynamic_position_concentration

    dpc = get_dynamic_position_concentration()

    decision = dpc.approve_entry(
        symbol="SOL-USD",
        proposed_size_usd=1_500.0,
        current_positions={"BTC-USD": 3_000.0, "ETH-USD": 2_000.0},
        portfolio_value=10_000.0,
    )

    if not decision.allowed:
        logger.warning("Concentration blocked: %s", decision.reason)
        return

    execute_order(size_usd=decision.adjusted_size_usd)

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
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("nija.dynamic_position_concentration")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_BASE_CAP_PCT: float = 0.25         # single-position hard cap (% of portfolio)
DEFAULT_MAX_HHI: float = 0.40             # block if portfolio HHI exceeds this
DEFAULT_MAX_SINGLE_WEIGHT: float = 0.35   # block if any position weight > this

# Capital-tier base caps: (upper_balance_bound, max_position_pct)
# The first tier whose upper bound exceeds the portfolio value is used.
_CAPITAL_TIER_CAPS: List[Tuple[float, float]] = [
    (100.0,         0.25),   # balance < $100   → 25% (micro-cap, max aggressiveness)
    (500.0,         0.20),   # $100 – $500       → 20%
    (2_000.0,       0.15),   # $500 – $2 000     → 15%
    (float("inf"),  0.10),   # $2 000+           → 10% (mature account, risk-reduced)
]

# HHI bands → cap multipliers
_HHI_BANDS: List[Tuple[float, float]] = [
    (0.10, 1.00),
    (0.20, 0.85),
    (0.30, 0.70),
    (0.50, 0.50),
    (1.00, 0.30),
]

DATA_DIR = Path(__file__).parent.parent / "data"


# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------

@dataclass
class ConcentrationMetrics:
    """Current portfolio concentration snapshot."""

    hhi: float                      # 0–1, lower = more diversified
    effective_n: float              # implied number of equal-risk positions
    max_single_weight: float        # largest position weight (0–1)
    max_single_symbol: str          # symbol with highest weight
    total_exposure_usd: float
    num_positions: int
    concentration_level: str        # LOW / MODERATE / HIGH / EXTREME
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class ConcentrationDecision:
    """Result returned by :meth:`DynamicPositionConcentration.approve_entry`."""

    allowed: bool
    reason: str
    symbol: str
    proposed_size_usd: float
    adjusted_size_usd: float
    max_allowed_usd: float
    current_hhi: float
    current_metrics: ConcentrationMetrics
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class DynamicPositionConcentration:
    """
    Dynamically caps position size based on portfolio Herfindahl concentration
    and the current capital tier.

    Parameters
    ----------
    base_cap_pct : float or None
        Override the capital-tier cap with a fixed fraction of portfolio value.
        When ``None`` (default), the cap is derived automatically from the
        portfolio value using :attr:`_CAPITAL_TIER_CAPS`:

        ============  ===============
        Balance       Max position %
        ============  ===============
        < $100        25% (micro-cap)
        $100 – $500   20%
        $500 – $2 000 15%
        $2 000+       10%
        ============  ===============

        This reduces risk as the account grows while remaining aggressive for
        small accounts where a 25 % cap is appropriate.
    max_hhi : float
        Portfolio HHI ceiling; new entries blocked when HHI would exceed this
        (default 0.40).
    max_single_weight : float
        Hard cap on any single position weight relative to total exposure
        (default 0.35 = 35%).
    """

    def __init__(
        self,
        base_cap_pct: Optional[float] = None,
        max_hhi: float = DEFAULT_MAX_HHI,
        max_single_weight: float = DEFAULT_MAX_SINGLE_WEIGHT,
    ) -> None:
        # None means "use capital-tier auto-scaling"; a float is a fixed override.
        self.base_cap_pct = base_cap_pct
        self.max_hhi = max_hhi
        self.max_single_weight = max_single_weight

        self._lock = threading.RLock()

        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._log_path = DATA_DIR / "concentration_decisions.jsonl"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def approve_entry(
        self,
        symbol: str,
        proposed_size_usd: float,
        current_positions: Dict[str, float],
        portfolio_value: float,
    ) -> ConcentrationDecision:
        """
        Decide whether *proposed_size_usd* for *symbol* is acceptable given
        current portfolio concentration.

        Parameters
        ----------
        symbol : str
            Candidate symbol.
        proposed_size_usd : float
            Desired position size in USD.
        current_positions : Dict[str, float]
            {symbol: size_usd} for all currently open positions.
        portfolio_value : float
            Total portfolio value in USD (cash + open positions).

        Returns
        -------
        ConcentrationDecision
            Rich result with ``allowed`` flag, adjusted size, and diagnostics.
        """
        with self._lock:
            if portfolio_value <= 0:
                return self._deny(
                    symbol, proposed_size_usd, "portfolio_value <= 0",
                    self._compute_metrics({}, 1.0),
                )

            metrics = self._compute_metrics(current_positions, portfolio_value)
            tier_cap = self._effective_base_cap(portfolio_value)
            dynamic_cap = self._dynamic_cap(metrics.hhi, tier_cap)
            max_allowed_usd = portfolio_value * dynamic_cap

            # Simulate post-entry positions
            simulated = dict(current_positions)
            existing = simulated.get(symbol, 0.0)
            simulated[symbol] = existing + proposed_size_usd
            post_metrics = self._compute_metrics(simulated, portfolio_value)

            allowed = True
            reason_parts: List[str] = []

            # Gate 1: HHI ceiling
            if post_metrics.hhi > self.max_hhi:
                allowed = False
                reason_parts.append(
                    f"post_hhi={post_metrics.hhi:.3f} > limit={self.max_hhi:.3f}"
                )

            # Gate 2: single-position weight
            proposed_weight = (existing + proposed_size_usd) / portfolio_value
            if proposed_weight > self.max_single_weight:
                allowed = False
                reason_parts.append(
                    f"position_weight={proposed_weight:.2%} > limit={self.max_single_weight:.2%}"
                )

            # Adjust size to fit within dynamic cap
            adjusted = min(proposed_size_usd, max_allowed_usd - existing)
            adjusted = max(adjusted, 0.0)

            if allowed and adjusted < proposed_size_usd:
                reason_parts.append(
                    f"size trimmed from ${proposed_size_usd:.2f} to ${adjusted:.2f} "
                    f"(dynamic_cap={dynamic_cap:.2%})"
                )

            reason = (
                " | ".join(reason_parts)
                if reason_parts
                else f"concentration gate passed (hhi={metrics.hhi:.3f})"
            )

            decision = ConcentrationDecision(
                allowed=allowed,
                reason=reason,
                symbol=symbol,
                proposed_size_usd=proposed_size_usd,
                adjusted_size_usd=round(adjusted, 2) if allowed else 0.0,
                max_allowed_usd=round(max_allowed_usd, 2),
                current_hhi=metrics.hhi,
                current_metrics=metrics,
            )

            self._log_decision(decision)

            if not allowed:
                logger.warning("DPC blocked %s: %s", symbol, reason)
            else:
                logger.debug("DPC approved %s: %s", symbol, reason)

            return decision

    def get_metrics(
        self,
        current_positions: Dict[str, float],
        portfolio_value: float,
    ) -> ConcentrationMetrics:
        """Compute current concentration metrics without gating a trade."""
        with self._lock:
            return self._compute_metrics(current_positions, portfolio_value)

    def dynamic_cap_pct(self, current_hhi: float, portfolio_value: float = 0.0) -> float:
        """Return the effective single-position cap % for a given HHI.

        Parameters
        ----------
        current_hhi : float
            Current portfolio HHI (0–1).
        portfolio_value : float, optional
            Portfolio value used to resolve the capital-tier base cap.  When
            ``0`` or omitted the fixed :attr:`base_cap_pct` override is used if
            set, otherwise the micro-cap tier (25%) is applied as the base.
        """
        return self._dynamic_cap(current_hhi, self._effective_base_cap(portfolio_value))

    def capital_tier_cap_pct(self, portfolio_value: float) -> float:
        """Return the raw capital-tier cap (before HHI adjustment) for *portfolio_value*.

        This is a diagnostic helper that shows which tier cap would be applied
        given the current account balance, ignoring HHI adjustment.

        Parameters
        ----------
        portfolio_value : float
            Total portfolio value in USD.

        Returns
        -------
        float
            Maximum single-position fraction (e.g. ``0.15`` for 15%).
        """
        return self._effective_base_cap(portfolio_value)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _compute_metrics(
        self, positions: Dict[str, float], portfolio_value: float
    ) -> ConcentrationMetrics:
        """Calculate HHI and related metrics from position snapshot."""
        if not positions or portfolio_value <= 0:
            return ConcentrationMetrics(
                hhi=0.0,
                effective_n=float("inf"),
                max_single_weight=0.0,
                max_single_symbol="",
                total_exposure_usd=0.0,
                num_positions=0,
                concentration_level="LOW",
            )

        total_exposure = sum(positions.values())
        if total_exposure <= 0:
            return ConcentrationMetrics(
                hhi=0.0,
                effective_n=float("inf"),
                max_single_weight=0.0,
                max_single_symbol="",
                total_exposure_usd=0.0,
                num_positions=len(positions),
                concentration_level="LOW",
            )

        weights = {sym: size / total_exposure for sym, size in positions.items()}
        hhi = sum(w ** 2 for w in weights.values())
        effective_n = 1.0 / hhi if hhi > 0 else float("inf")

        max_sym = max(weights, key=lambda k: weights[k])
        max_weight = weights[max_sym]

        if hhi <= 0.10:
            level = "LOW"
        elif hhi <= 0.25:
            level = "MODERATE"
        elif hhi <= 0.40:
            level = "HIGH"
        else:
            level = "EXTREME"

        return ConcentrationMetrics(
            hhi=round(hhi, 4),
            effective_n=round(effective_n, 2),
            max_single_weight=round(max_weight, 4),
            max_single_symbol=max_sym,
            total_exposure_usd=round(total_exposure, 2),
            num_positions=len(positions),
            concentration_level=level,
        )

    def _effective_base_cap(self, portfolio_value: float) -> float:
        """Return the capital-tier base cap for *portfolio_value*.

        If :attr:`base_cap_pct` is set (i.e. not ``None``), that fixed value is
        returned regardless of portfolio size (backward-compatible override).
        Otherwise the appropriate tier is selected from :attr:`_CAPITAL_TIER_CAPS`.
        """
        if self.base_cap_pct is not None:
            return self.base_cap_pct

        for upper_bound, cap_pct in _CAPITAL_TIER_CAPS:
            if portfolio_value < upper_bound:
                return cap_pct

        # Unreachable when _CAPITAL_TIER_CAPS contains a float("inf") sentinel,
        # but guard against accidental misconfiguration.
        raise RuntimeError(  # pragma: no cover
            "_CAPITAL_TIER_CAPS is missing the required float('inf') sentinel entry"
        )

    def _dynamic_cap(self, hhi: float, effective_base: Optional[float] = None) -> float:
        """Map HHI to a single-position cap fraction using the band table.

        Parameters
        ----------
        hhi : float
            Current portfolio HHI.
        effective_base : float, optional
            Base cap to scale.  When omitted, falls back to
            :meth:`_effective_base_cap` with a zero portfolio value (returns the
            fixed :attr:`base_cap_pct` or the micro-cap tier default).
        """
        base = effective_base if effective_base is not None else self._effective_base_cap(0.0)
        cap = base
        for band_max, multiplier in _HHI_BANDS:
            if hhi <= band_max:
                cap = base * multiplier
                break
        return round(cap, 4)

    def _deny(
        self,
        symbol: str,
        proposed: float,
        reason: str,
        metrics: ConcentrationMetrics,
    ) -> ConcentrationDecision:
        return ConcentrationDecision(
            allowed=False,
            reason=reason,
            symbol=symbol,
            proposed_size_usd=proposed,
            adjusted_size_usd=0.0,
            max_allowed_usd=0.0,
            current_hhi=metrics.hhi,
            current_metrics=metrics,
        )

    def _log_decision(self, decision: ConcentrationDecision) -> None:
        try:
            record = {
                "timestamp": decision.timestamp,
                "symbol": decision.symbol,
                "allowed": decision.allowed,
                "reason": decision.reason,
                "proposed_size_usd": decision.proposed_size_usd,
                "adjusted_size_usd": decision.adjusted_size_usd,
                "max_allowed_usd": decision.max_allowed_usd,
                "current_hhi": decision.current_hhi,
                "concentration_level": decision.current_metrics.concentration_level,
                "num_positions": decision.current_metrics.num_positions,
            }
            with self._log_path.open("a") as fh:
                fh.write(json.dumps(record) + "\n")
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_dpc_instance: Optional[DynamicPositionConcentration] = None
_dpc_lock = threading.Lock()


def get_dynamic_position_concentration(**kwargs) -> DynamicPositionConcentration:
    """Return the process-wide :class:`DynamicPositionConcentration` singleton."""
    global _dpc_instance
    with _dpc_lock:
        if _dpc_instance is None:
            _dpc_instance = DynamicPositionConcentration(**kwargs)
            logger.info("DynamicPositionConcentration singleton created")
    return _dpc_instance
