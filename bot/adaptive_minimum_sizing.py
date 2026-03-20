"""
NIJA Adaptive Minimum Sizing Engine
=====================================

Implements: min_order = max(broker_min, strategy_min_based_on_edge)

Key principles:
  - High confidence signals  → allow position sizes down to broker_minimum
  - Low  confidence signals  → require *larger* minimum to be worth executing

This prevents weak trades from sneaking through just because they technically
satisfy the broker's raw order-size floor.

Three related optimisations are also bundled here:

1. Trade frequency vs minimum balance
   • Prevents Coinbase accounts from sitting idle.
   • Returns the maximum meaningful number of concurrent minimum-size positions
     and flags "idle risk" when the account cannot open even one more trade.

2. Position sizing tuned to hit minimums more often
   • For HIGH-confidence signals whose calculated size lands slightly below
     the broker minimum, the engine recommends bumping to exactly broker_min
     rather than skipping the trade entirely.

3. Capital distribution across brokers
   • For a small account (e.g. $250), recommends an allocation that maximises
     the ratio of available capital to each broker's minimum order size.

Author: NIJA Trading Systems
Version: 1.0 – Adaptive Minimum Sizing
Date: March 2026
"""

import logging
import math
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("nija.adaptive_minimum_sizing")

# ──────────────────────────────────────────────────────────────────────────────
# Broker minimum order sizes (USD) – single source of truth for this module
# Keep in sync with BROKER_MIN_ORDER_USD in nija_apex_strategy_v71.py
# ──────────────────────────────────────────────────────────────────────────────
BROKER_MIN_ORDER_USD: Dict[str, float] = {
    "coinbase": 25.0,   # High fees make <$25 unprofitable
    "kraken":   10.0,   # Kraken exchange requirement
    "binance":  10.0,   # Binance minimum notional
    "okx":      10.0,   # OKX minimum notional
    "alpaca":    1.0,   # Alpaca (stocks/crypto) minimum
}
_DEFAULT_BROKER_MIN = 10.0  # Conservative fallback

# ──────────────────────────────────────────────────────────────────────────────
# Adaptive sizing tunables
# ──────────────────────────────────────────────────────────────────────────────
# How much larger the strategy minimum becomes at *zero* confidence relative to
# the broker minimum.
#   edge_multiplier = 2.0 → at confidence 0.0 : strategy_min = 3 × broker_min
#                           at confidence 0.5  : strategy_min = 2 × broker_min
#                           at confidence 1.0  : strategy_min = 1 × broker_min
DEFAULT_EDGE_MULTIPLIER = 2.0

# A high-confidence signal is allowed to have its calculated size bumped UP to
# the broker minimum instead of being skipped outright.
# "High confidence" threshold (0–1 normalised score)
HIGH_CONFIDENCE_THRESHOLD = 0.80

# Maximum allowed fraction of account balance that a bumped position may consume
# (prevents a near-zero balance account from over-committing on a single trade)
MAX_BUMP_FRACTION = 0.30  # 30 % of balance

# ──────────────────────────────────────────────────────────────────────────────
# Capital distribution tunables
# ──────────────────────────────────────────────────────────────────────────────
# Minimum reserve that should always remain uninvested (as a fraction of total)
MIN_RESERVE_FRACTION = 0.10  # 10 % reserve


class AdaptiveMinimumSizer:
    """
    Calculates adaptive minimum order sizes based on signal confidence.

    Core formula::

        strategy_min = broker_min × (1 + (1 – confidence) × edge_multiplier)
        min_order    = max(broker_min, strategy_min)

    At confidence = 1.0 : min_order == broker_min  (allow minimum)
    At confidence = 0.5 : min_order == broker_min × 2.0  (need 2× min)
    At confidence = 0.0 : min_order == broker_min × 3.0  (need 3× min)
    """

    def __init__(
        self,
        edge_multiplier: float = DEFAULT_EDGE_MULTIPLIER,
        high_confidence_threshold: float = HIGH_CONFIDENCE_THRESHOLD,
        max_bump_fraction: float = MAX_BUMP_FRACTION,
    ):
        """
        Args:
            edge_multiplier: Controls how aggressively the minimum scales with
                             falling confidence (default 2.0).
            high_confidence_threshold: Confidence level above which a position
                                       may be bumped to broker_min (default 0.80).
            max_bump_fraction: Maximum fraction of account balance allowed for
                               a bumped position (default 0.30).
        """
        self.edge_multiplier = edge_multiplier
        self.high_confidence_threshold = high_confidence_threshold
        self.max_bump_fraction = max_bump_fraction

        logger.info("=" * 70)
        logger.info("🎯 Adaptive Minimum Sizer initialised")
        logger.info("=" * 70)
        logger.info(f"   edge_multiplier        : {self.edge_multiplier}")
        logger.info(f"   high_confidence_thresh : {self.high_confidence_threshold}")
        logger.info(f"   max_bump_fraction      : {self.max_bump_fraction}")
        logger.info("=" * 70)

    # ──────────────────────────────────────────────────────────────────────
    # 1. Adaptive minimum
    # ──────────────────────────────────────────────────────────────────────

    def get_adaptive_minimum(self, broker_min: float, confidence: float) -> float:
        """
        Return the adaptive minimum order size for a given confidence level.

        Args:
            broker_min:  Raw broker / exchange minimum order size (USD).
            confidence:  Normalised signal confidence in [0.0, 1.0].

        Returns:
            Adaptive minimum order size (always ≥ broker_min).
        """
        confidence = max(0.0, min(1.0, confidence))
        strategy_min = broker_min * (1.0 + (1.0 - confidence) * self.edge_multiplier)
        return max(broker_min, strategy_min)

    def get_broker_minimum(self, broker_name: str) -> float:
        """Return the known minimum order size for a broker (USD)."""
        return BROKER_MIN_ORDER_USD.get(broker_name.lower(), _DEFAULT_BROKER_MIN)

    # ──────────────────────────────────────────────────────────────────────
    # 2. Position sizing tuned to hit minimums more often
    # ──────────────────────────────────────────────────────────────────────

    def get_minimum_bump_recommendation(
        self,
        position_size_usd: float,
        broker_min: float,
        confidence: float,
        account_balance: float,
    ) -> Dict:
        """
        Decide whether a position that falls below the adaptive minimum should
        be bumped up to the broker minimum (for high-confidence signals) or
        skipped (for low-confidence signals).

        Effective minimums
        ------------------
        * **High confidence** (≥ ``high_confidence_threshold``):
          effective_min = broker_min.
          – If position ≥ broker_min → valid as-is.
          – If position < broker_min AND broker_min ≤ max_bump_fraction × balance
            → bump to broker_min (valid with bump).
          – If broker_min > max_bump_fraction × balance → reject (can't afford).

        * **Low confidence** (< ``high_confidence_threshold``):
          effective_min = adaptive_min = broker_min × (1 + (1–conf) × edge_multiplier).
          – If position ≥ adaptive_min → valid as-is.
          – Otherwise → reject.

        This ensures:
        * Strong signals are never silently skipped due to a slightly-too-small
          position size (they get bumped to broker_min instead).
        * Weak signals face a meaningfully higher bar, preventing marginal trades
          that technically clear the raw exchange floor.

        Args:
            position_size_usd: Calculated position size before bump (USD).
            broker_min:        Broker's raw minimum order size (USD).
            confidence:        Normalised signal confidence in [0.0, 1.0].
            account_balance:   Current account cash balance (USD).

        Returns:
            Dict with keys:
                ``valid``              – bool: whether trade should proceed
                ``bumped``             – bool: whether size was bumped to broker_min
                ``recommended_size``   – float: final recommended size
                ``adaptive_min``       – float: adaptive minimum for this confidence
                ``reason``             – str: human-readable explanation
        """
        confidence = max(0.0, min(1.0, confidence))
        adaptive_min = self.get_adaptive_minimum(broker_min, confidence)
        is_high_confidence = confidence >= self.high_confidence_threshold
        max_allowed = account_balance * self.max_bump_fraction

        # ── High-confidence path: effective minimum = broker_min ────────────
        if is_high_confidence:
            if position_size_usd >= broker_min:
                return {
                    "valid": True,
                    "bumped": False,
                    "recommended_size": position_size_usd,
                    "adaptive_min": adaptive_min,
                    "reason": (
                        f"High-confidence signal ({confidence:.2f}): "
                        f"position ${position_size_usd:.2f} ≥ broker_min ${broker_min:.2f}"
                    ),
                }

            # Position is below broker_min — can we afford to bump?
            can_afford_bump = account_balance > 0 and broker_min <= max_allowed
            if can_afford_bump:
                return {
                    "valid": True,
                    "bumped": True,
                    "recommended_size": broker_min,
                    "adaptive_min": adaptive_min,
                    "reason": (
                        f"High-confidence signal ({confidence:.2f} ≥ {self.high_confidence_threshold}): "
                        f"bumped ${position_size_usd:.2f} → broker minimum ${broker_min:.2f}"
                    ),
                }
            else:
                return {
                    "valid": False,
                    "bumped": False,
                    "recommended_size": position_size_usd,
                    "adaptive_min": adaptive_min,
                    "reason": (
                        f"High-confidence signal but balance ${account_balance:.2f} too low – "
                        f"broker_min ${broker_min:.2f} > "
                        f"{self.max_bump_fraction*100:.0f}% × ${account_balance:.2f} = ${max_allowed:.2f}"
                    ),
                }

        # ── Low-confidence path: effective minimum = adaptive_min ───────────
        if position_size_usd >= adaptive_min:
            return {
                "valid": True,
                "bumped": False,
                "recommended_size": position_size_usd,
                "adaptive_min": adaptive_min,
                "reason": (
                    f"Position ${position_size_usd:.2f} ≥ adaptive minimum "
                    f"${adaptive_min:.2f} (confidence {confidence:.2f})"
                ),
            }

        return {
            "valid": False,
            "bumped": False,
            "recommended_size": position_size_usd,
            "adaptive_min": adaptive_min,
            "reason": (
                f"Low-confidence trade rejected: ${position_size_usd:.2f} < "
                f"adaptive minimum ${adaptive_min:.2f} "
                f"(confidence {confidence:.2f} < threshold {self.high_confidence_threshold})"
            ),
        }

    # ──────────────────────────────────────────────────────────────────────
    # 3. Trade frequency vs minimum balance
    # ──────────────────────────────────────────────────────────────────────

    def get_trade_capacity(
        self,
        account_balance: float,
        broker_min: float,
        confidence: float = 1.0,
    ) -> Dict:
        """
        How many minimum-size trades can this account support concurrently?

        Args:
            account_balance: Available cash balance (USD).
            broker_min:      Broker's raw minimum order size (USD).
            confidence:      Expected signal confidence (used to compute adaptive_min).

        Returns:
            Dict with:
                ``adaptive_min``       – float
                ``max_concurrent``     – int: floor(balance / adaptive_min)
                ``idle_risk``          – bool: True if account cannot open even one trade
                ``utilisation_pct``    – float: broker_min / balance * 100
                ``recommendation``     – str
        """
        adaptive_min = self.get_adaptive_minimum(broker_min, confidence)
        max_concurrent = int(account_balance / adaptive_min) if adaptive_min > 0 else 0
        idle_risk = max_concurrent < 1

        if idle_risk:
            recommendation = (
                f"⚠️  Account balance ${account_balance:.2f} is too low to open "
                f"even one trade at the adaptive minimum of ${adaptive_min:.2f}. "
                f"Deposit more funds or reduce broker minimum."
            )
        elif max_concurrent == 1:
            recommendation = (
                f"Account can support 1 concurrent trade (${adaptive_min:.2f} each). "
                f"Consider consolidating to a single broker for better utilisation."
            )
        else:
            recommendation = (
                f"Account can support up to {max_concurrent} concurrent "
                f"minimum-size trades of ${adaptive_min:.2f}."
            )

        return {
            "adaptive_min": adaptive_min,
            "max_concurrent": max_concurrent,
            "idle_risk": idle_risk,
            "utilisation_pct": (broker_min / account_balance * 100) if account_balance > 0 else 0,
            "recommendation": recommendation,
        }

    def get_scan_interval_adjustment(
        self,
        account_balance: float,
        broker_name: str,
        base_interval_seconds: int = 150,
    ) -> Dict:
        """
        Recommend a scan-interval adjustment so that accounts with very limited
        capacity are not over-scanned (wasted CPU / API calls) and rich accounts
        are scanned more aggressively.

        The multiplier is calibrated against the ratio of available capital to
        broker minimum:
            ratio = balance / broker_min
            multiplier ≈ 1 / sqrt(ratio) clamped to [0.50, 2.00]

        Args:
            account_balance:      Available cash balance (USD).
            broker_name:          Exchange / broker name (e.g. 'coinbase').
            base_interval_seconds: Default scan interval in seconds (default 150 s).

        Returns:
            Dict with ``multiplier``, ``adjusted_interval``, and ``reason``.
        """
        broker_min = self.get_broker_minimum(broker_name)
        if broker_min <= 0 or account_balance <= 0:
            return {
                "multiplier": 1.0,
                "adjusted_interval": base_interval_seconds,
                "reason": "Cannot compute ratio; using base interval.",
            }

        ratio = account_balance / broker_min
        multiplier = 1.0 / math.sqrt(ratio)
        multiplier = max(0.50, min(2.00, multiplier))
        adjusted = int(base_interval_seconds * multiplier)
        adjusted = max(30, min(300, adjusted))

        reason = (
            f"balance/broker_min ratio={ratio:.1f} → "
            f"multiplier={multiplier:.2f} → "
            f"interval={adjusted}s (base={base_interval_seconds}s)"
        )

        return {
            "multiplier": multiplier,
            "adjusted_interval": adjusted,
            "reason": reason,
        }

    # ──────────────────────────────────────────────────────────────────────
    # 4. Capital distribution across brokers
    # ──────────────────────────────────────────────────────────────────────

    def get_capital_distribution(
        self,
        total_balance: float,
        broker_names: Optional[List[str]] = None,
        performance_weights: Optional[Dict[str, float]] = None,
    ) -> Dict:
        """
        Recommend how to split *total_balance* across the given brokers so that
        each receives at least enough capital to support a meaningful number of
        minimum-size trades, with a 10 % cash reserve.

        Allocation logic
        ----------------
        1. Reserve 10 % of total_balance as uninvested cash.
        2. Score each broker as deployable_capital / broker_min (i.e. how many
           minimum trades it can support).
        3. Weight the remaining 90 % proportionally to each broker's
           (score × optional performance_weight).
        4. Ensure each broker receives at least 1 × broker_min; remove brokers
           that cannot be adequately funded given the total capital.

        Args:
            total_balance:       Total capital to distribute (USD).
            broker_names:        List of broker names (default: coinbase + kraken).
            performance_weights: Optional {broker: multiplier} to boost preferred
                                 brokers (e.g. {"coinbase": 1.2, "kraken": 1.0}).

        Returns:
            Dict with ``reserve_usd``, ``allocations`` (per broker), and
            ``recommendations`` (human-readable summary).
        """
        if broker_names is None:
            broker_names = ["coinbase", "kraken"]

        performance_weights = performance_weights or {}
        reserve_usd = total_balance * MIN_RESERVE_FRACTION
        deployable = total_balance - reserve_usd

        # Compute broker scores
        scores: Dict[str, float] = {}
        for broker in broker_names:
            bmin = self.get_broker_minimum(broker)
            score = deployable / bmin if bmin > 0 else 0.0
            perf_w = performance_weights.get(broker, 1.0)
            scores[broker] = score * perf_w

        total_score = sum(scores.values())

        # Build allocations
        allocations: Dict[str, Dict] = {}
        recommendations: List[str] = []

        for broker in broker_names:
            bmin = self.get_broker_minimum(broker)
            if total_score > 0:
                alloc_usd = deployable * (scores[broker] / total_score)
            else:
                alloc_usd = deployable / len(broker_names)

            max_concurrent = int(alloc_usd / bmin) if bmin > 0 else 0
            viable = alloc_usd >= bmin

            allocations[broker] = {
                "allocated_usd": round(alloc_usd, 2),
                "broker_min": bmin,
                "max_concurrent_trades": max_concurrent,
                "viable": viable,
            }

            if viable:
                recommendations.append(
                    f"  {broker.upper():12s}: ${alloc_usd:.2f} "
                    f"→ up to {max_concurrent} concurrent trades "
                    f"(min ${bmin:.2f} each)"
                )
            else:
                recommendations.append(
                    f"  {broker.upper():12s}: ${alloc_usd:.2f} – NOT VIABLE "
                    f"(below ${bmin:.2f} minimum; consider removing)"
                )

        return {
            "total_balance": total_balance,
            "reserve_usd": round(reserve_usd, 2),
            "deployable_usd": round(deployable, 2),
            "allocations": allocations,
            "recommendations": "\n".join(recommendations),
        }

    # ──────────────────────────────────────────────────────────────────────
    # Convenience: full validation (replaces the two-step check in v71)
    # ──────────────────────────────────────────────────────────────────────

    def validate_trade(
        self,
        position_size_usd: float,
        score: float,
        max_entry_score: float,
        broker_name: str,
        account_balance: float,
    ) -> Dict:
        """
        Full adaptive trade validation combining:
          • Adaptive minimum size check
          • High-confidence bump to broker_min
          • Confidence threshold gate

        This is the single entry point intended to replace the multi-step
        validation in ``_validate_trade_quality`` of the APEX strategy.

        Args:
            position_size_usd: Calculated position size (USD).
            score:             Raw entry signal score (0 – max_entry_score).
            max_entry_score:   Maximum possible entry score (normalisation factor).
            broker_name:       Broker name (e.g. 'coinbase').
            account_balance:   Current account balance (USD).

        Returns:
            Dict with:
                ``valid``              – bool
                ``confidence``         – float (0–1)
                ``recommended_size``   – float (may differ from input after bump)
                ``adaptive_min``       – float
                ``reason``             – str
                ``bumped``             – bool
        """
        confidence = min(score / max_entry_score, 1.0) if max_entry_score > 0 else 0.0
        broker_min = self.get_broker_minimum(broker_name)
        bump_result = self.get_minimum_bump_recommendation(
            position_size_usd=position_size_usd,
            broker_min=broker_min,
            confidence=confidence,
            account_balance=account_balance,
        )

        return {
            "valid": bump_result["valid"],
            "confidence": confidence,
            "recommended_size": bump_result["recommended_size"],
            "adaptive_min": bump_result["adaptive_min"],
            "reason": bump_result["reason"],
            "bumped": bump_result["bumped"],
        }


# ──────────────────────────────────────────────────────────────────────────────
# Singleton
# ──────────────────────────────────────────────────────────────────────────────
_sizer_instance: Optional[AdaptiveMinimumSizer] = None
_sizer_lock = __import__("threading").Lock()


def get_adaptive_minimum_sizer(
    edge_multiplier: float = DEFAULT_EDGE_MULTIPLIER,
    high_confidence_threshold: float = HIGH_CONFIDENCE_THRESHOLD,
    max_bump_fraction: float = MAX_BUMP_FRACTION,
) -> AdaptiveMinimumSizer:
    """Return the singleton ``AdaptiveMinimumSizer`` instance."""
    global _sizer_instance
    if _sizer_instance is None:
        with _sizer_lock:
            if _sizer_instance is None:
                _sizer_instance = AdaptiveMinimumSizer(
                    edge_multiplier=edge_multiplier,
                    high_confidence_threshold=high_confidence_threshold,
                    max_bump_fraction=max_bump_fraction,
                )
    return _sizer_instance


# ──────────────────────────────────────────────────────────────────────────────
# Self-test / demo
# ──────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import logging as _logging

    _logging.basicConfig(level=_logging.INFO, format="%(levelname)s - %(message)s")

    sizer = AdaptiveMinimumSizer()

    print("\n" + "=" * 70)
    print("ADAPTIVE MINIMUM SIZING – DEMO")
    print("=" * 70)

    # 1. Adaptive minimum by confidence
    broker_min = 25.0  # Coinbase
    print(f"\n1. Adaptive minimum (broker_min=${broker_min})")
    for conf in [1.0, 0.90, 0.80, 0.75, 0.60, 0.50, 0.25, 0.0]:
        amin = sizer.get_adaptive_minimum(broker_min, conf)
        print(f"   confidence={conf:.2f} → adaptive_min=${amin:.2f}")

    # 2. Bump recommendations for a $250 account
    balance = 250.0
    print(f"\n2. Bump recommendations (balance=${balance})")
    for conf, size in [(0.90, 22.0), (0.85, 24.5), (0.70, 24.0), (0.50, 24.0)]:
        result = sizer.get_minimum_bump_recommendation(size, broker_min, conf, balance)
        print(f"   conf={conf:.2f} size=${size} → valid={result['valid']} "
              f"bumped={result['bumped']} rec=${result['recommended_size']:.2f}")

    # 3. Trade capacity
    print(f"\n3. Trade capacity (balance=${balance}, broker_min=${broker_min})")
    capacity = sizer.get_trade_capacity(balance, broker_min, confidence=0.80)
    print(f"   max_concurrent={capacity['max_concurrent']}, "
          f"idle_risk={capacity['idle_risk']}")
    print(f"   {capacity['recommendation']}")

    # 4. Scan interval adjustment
    print("\n4. Scan interval adjustments")
    for bal in [30, 75, 150, 250, 500]:
        adj = sizer.get_scan_interval_adjustment(bal, "coinbase")
        print(f"   balance=${bal:>5}  → interval={adj['adjusted_interval']}s  "
              f"({adj['reason']})")

    # 5. Capital distribution
    print(f"\n5. Capital distribution (total=${balance})")
    dist = sizer.get_capital_distribution(balance, ["coinbase", "kraken"])
    print(f"   Reserve: ${dist['reserve_usd']:.2f}")
    print(dist["recommendations"])
