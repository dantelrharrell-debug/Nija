"""
NIJA Adaptive Minimum Sizing Engine
=====================================

Implements: min_order = max(broker_min, strategy_min_based_on_edge)

Key principles:
  - Strong executable signals  → allow position sizes to bump to broker_minimum
  - Weak signals              → require a larger adaptive minimum

This prevents weak trades from sneaking through just because they technically
satisfy the broker's raw order-size floor, while avoiding the live-runtime
problem where a valid OKX signal is blocked because 2% sizing lands slightly
below a $5 broker minimum.

Three related optimisations are also bundled here:

1. Trade frequency vs minimum balance
   • Prevents small accounts from sitting idle.
   • Returns the maximum meaningful number of concurrent minimum-size positions
     and flags "idle risk" when the account cannot open even one more trade.

2. Position sizing tuned to hit minimums more often
   • For executable signals whose calculated size lands slightly below the
     broker minimum, the engine recommends bumping to exactly broker_min rather
     than skipping the trade entirely, if the bump fits the max-fraction guard.

3. Capital distribution across brokers
   • For a small account, recommends an allocation that maximises the ratio of
     available capital to each broker's minimum order size.

Author: NIJA Trading Systems
Version: 1.1 – Micro-cap minimum-notional bump repair
Date: July 2026
"""

import logging
import math
import os
from typing import Dict, List, Optional

logger = logging.getLogger("nija.adaptive_minimum_sizing")

# ──────────────────────────────────────────────────────────────────────────────
# Broker minimum order sizes (USD) – single source of truth for this module
# Keep in sync with BROKER_MIN_ORDER_USD in nija_apex_strategy_v71.py
# ──────────────────────────────────────────────────────────────────────────────
BROKER_MIN_ORDER_USD: Dict[str, float] = {
    "coinbase": float(os.getenv("COINBASE_MIN_NOTIONAL_USD", "1.0")),
    "kraken": float(os.getenv("KRAKEN_MIN_NOTIONAL_USD", "10.0")),
    "binance": float(os.getenv("BINANCE_MIN_NOTIONAL_USD", "10.0")),
    "okx": float(os.getenv("OKX_MIN_NOTIONAL_USD", "5.0")),
    "alpaca": float(os.getenv("ALPACA_MIN_NOTIONAL_USD", "1.0")),
}
_DEFAULT_BROKER_MIN = float(os.getenv("NIJA_DEFAULT_MIN_NOTIONAL_USD", "5.0"))

# ──────────────────────────────────────────────────────────────────────────────
# Adaptive sizing tunables
# ──────────────────────────────────────────────────────────────────────────────
DEFAULT_EDGE_MULTIPLIER = float(os.getenv("NIJA_ADAPTIVE_EDGE_MULTIPLIER", "0.25"))

# The live AI score is already quality-gated before this module. A 44/100 BTC
# OKX signal should not be treated as zero-confidence and blocked when the only
# gap is $4.45 vs a $5 minimum. Keep env override available.
HIGH_CONFIDENCE_THRESHOLD = float(os.getenv("NIJA_MIN_BUMP_CONFIDENCE", "0.30"))

# Maximum allowed fraction of account balance that a bumped position may consume.
# $5 on a $48.75 OKX account is ~10.3%, safely below this cap.
MAX_BUMP_FRACTION = float(os.getenv("NIJA_MAX_MIN_NOTIONAL_BUMP_FRACTION", "0.30"))
MIN_EXECUTABLE_SCORE = float(os.getenv("NIJA_MIN_BUMP_SCORE", "12.0"))

# ──────────────────────────────────────────────────────────────────────────────
# Capital distribution tunables
# ──────────────────────────────────────────────────────────────────────────────
MIN_RESERVE_FRACTION = 0.10


class AdaptiveMinimumSizer:
    """
    Calculates adaptive minimum order sizes based on signal confidence.

    Core formula::

        strategy_min = broker_min × (1 + (1 – confidence) × edge_multiplier)
        min_order    = max(broker_min, strategy_min)

    For executable micro-cap signals, `get_minimum_bump_recommendation` can bump
    a slightly undersized position to the broker minimum if it remains inside the
    max-bump-fraction guard.
    """

    def __init__(
        self,
        edge_multiplier: float = DEFAULT_EDGE_MULTIPLIER,
        high_confidence_threshold: float = HIGH_CONFIDENCE_THRESHOLD,
        max_bump_fraction: float = MAX_BUMP_FRACTION,
    ):
        self.edge_multiplier = edge_multiplier
        self.high_confidence_threshold = high_confidence_threshold
        self.max_bump_fraction = max_bump_fraction

        logger.info("=" * 70)
        logger.info("🎯 Adaptive Minimum Sizer initialised")
        logger.info("=" * 70)
        logger.info("   edge_multiplier        : %s", self.edge_multiplier)
        logger.info("   high_confidence_thresh : %s", self.high_confidence_threshold)
        logger.info("   max_bump_fraction      : %s", self.max_bump_fraction)
        logger.info("=" * 70)

    def get_adaptive_minimum(self, broker_min: float, confidence: float) -> float:
        confidence = max(0.0, min(1.0, confidence))
        strategy_min = broker_min * (1.0 + (1.0 - confidence) * self.edge_multiplier)
        return max(broker_min, strategy_min)

    def get_broker_minimum(self, broker_name: str) -> float:
        return BROKER_MIN_ORDER_USD.get(str(broker_name or "").lower(), _DEFAULT_BROKER_MIN)

    def _normalized_confidence(self, confidence: float, score: float | None = None, max_entry_score: float | None = None) -> float:
        try:
            conf = float(confidence)
        except Exception:
            conf = 0.0
        # Some runtime callers pass a 0-100 score as "confidence". Normalize it.
        if conf > 1.0:
            conf = conf / 100.0
        if conf <= 0.0 and score is not None:
            try:
                score_f = float(score)
                if max_entry_score and max_entry_score > 0:
                    conf = score_f / float(max_entry_score)
                elif score_f > 1.0:
                    conf = score_f / 100.0
                else:
                    conf = score_f
            except Exception:
                pass
        return max(0.0, min(1.0, conf))

    def get_minimum_bump_recommendation(
        self,
        position_size_usd: float,
        broker_min: float,
        confidence: float,
        account_balance: float,
        *,
        score: float | None = None,
        max_entry_score: float | None = None,
    ) -> Dict:
        """
        Decide whether an undersized position should be bumped to broker_min.

        Safety contract:
        * Never bump if broker_min exceeds `max_bump_fraction × account_balance`.
        * Never reduce the broker minimum.
        * Only bump if confidence/score shows this is an executable signal.
        """
        confidence = self._normalized_confidence(confidence, score=score, max_entry_score=max_entry_score)
        adaptive_min = self.get_adaptive_minimum(broker_min, confidence)
        max_allowed = float(account_balance or 0.0) * self.max_bump_fraction
        executable_score = False
        try:
            executable_score = score is not None and float(score) >= MIN_EXECUTABLE_SCORE
        except Exception:
            executable_score = False
        is_bump_eligible = confidence >= self.high_confidence_threshold or executable_score

        if position_size_usd >= broker_min and (position_size_usd >= adaptive_min or is_bump_eligible):
            return {
                "valid": True,
                "bumped": False,
                "recommended_size": position_size_usd,
                "adaptive_min": adaptive_min,
                "reason": f"Position ${position_size_usd:.2f} is executable at confidence {confidence:.2f}",
            }

        if position_size_usd < broker_min and is_bump_eligible:
            can_afford_bump = account_balance > 0 and broker_min <= max_allowed
            if can_afford_bump:
                logger.warning(
                    "MIN_NOTIONAL_BUMP_APPLIED marker=20260703g size=%.2f -> %.2f confidence=%.3f score=%s balance=%.2f max_allowed=%.2f",
                    position_size_usd,
                    broker_min,
                    confidence,
                    score,
                    account_balance,
                    max_allowed,
                )
                print(
                    f"[NIJA-PRINT] MIN_NOTIONAL_BUMP_APPLIED marker=20260703g size=${position_size_usd:.2f} -> ${broker_min:.2f}",
                    flush=True,
                )
                return {
                    "valid": True,
                    "bumped": True,
                    "recommended_size": broker_min,
                    "adaptive_min": adaptive_min,
                    "reason": f"Executable signal bumped ${position_size_usd:.2f} → broker minimum ${broker_min:.2f}",
                }
            return {
                "valid": False,
                "bumped": False,
                "recommended_size": position_size_usd,
                "adaptive_min": adaptive_min,
                "reason": f"Broker minimum ${broker_min:.2f} exceeds bump cap ${max_allowed:.2f}",
            }

        if position_size_usd >= adaptive_min:
            return {
                "valid": True,
                "bumped": False,
                "recommended_size": position_size_usd,
                "adaptive_min": adaptive_min,
                "reason": f"Position ${position_size_usd:.2f} ≥ adaptive minimum ${adaptive_min:.2f}",
            }

        return {
            "valid": False,
            "bumped": False,
            "recommended_size": position_size_usd,
            "adaptive_min": adaptive_min,
            "reason": f"Trade rejected: ${position_size_usd:.2f} < adaptive minimum ${adaptive_min:.2f} (confidence {confidence:.2f})",
        }

    def get_trade_capacity(self, account_balance: float, broker_min: float, confidence: float = 1.0) -> Dict:
        adaptive_min = self.get_adaptive_minimum(broker_min, confidence)
        max_concurrent = int(account_balance / adaptive_min) if adaptive_min > 0 else 0
        idle_risk = max_concurrent < 1
        if idle_risk:
            recommendation = f"⚠️  Account balance ${account_balance:.2f} is too low to open even one trade at ${adaptive_min:.2f}."
        elif max_concurrent == 1:
            recommendation = f"Account can support 1 concurrent trade (${adaptive_min:.2f} each)."
        else:
            recommendation = f"Account can support up to {max_concurrent} concurrent minimum-size trades of ${adaptive_min:.2f}."
        return {
            "adaptive_min": adaptive_min,
            "max_concurrent": max_concurrent,
            "idle_risk": idle_risk,
            "utilisation_pct": (broker_min / account_balance * 100) if account_balance > 0 else 0,
            "recommendation": recommendation,
        }

    def get_scan_interval_adjustment(self, account_balance: float, broker_name: str, base_interval_seconds: int = 150) -> Dict:
        broker_min = self.get_broker_minimum(broker_name)
        if broker_min <= 0 or account_balance <= 0:
            return {"multiplier": 1.0, "adjusted_interval": base_interval_seconds, "reason": "Cannot compute ratio; using base interval."}
        ratio = account_balance / broker_min
        multiplier = max(0.50, min(2.00, 1.0 / math.sqrt(ratio)))
        adjusted = max(30, min(300, int(base_interval_seconds * multiplier)))
        return {"multiplier": multiplier, "adjusted_interval": adjusted, "reason": f"balance/broker_min ratio={ratio:.1f}"}

    def get_capital_distribution(self, total_balance: float, broker_names: Optional[List[str]] = None, performance_weights: Optional[Dict[str, float]] = None) -> Dict:
        if broker_names is None:
            broker_names = ["coinbase", "kraken", "okx"]
        performance_weights = performance_weights or {}
        reserve_usd = total_balance * MIN_RESERVE_FRACTION
        deployable = total_balance - reserve_usd
        scores: Dict[str, float] = {}
        for broker in broker_names:
            bmin = self.get_broker_minimum(broker)
            scores[broker] = (deployable / bmin if bmin > 0 else 0.0) * performance_weights.get(broker, 1.0)
        total_score = sum(scores.values())
        allocations: Dict[str, Dict] = {}
        recommendations: List[str] = []
        for broker in broker_names:
            bmin = self.get_broker_minimum(broker)
            alloc_usd = deployable * (scores[broker] / total_score) if total_score > 0 else deployable / len(broker_names)
            max_concurrent = int(alloc_usd / bmin) if bmin > 0 else 0
            viable = alloc_usd >= bmin
            allocations[broker] = {"allocated_usd": round(alloc_usd, 2), "broker_min": bmin, "max_concurrent_trades": max_concurrent, "viable": viable}
            recommendations.append(f"  {broker.upper():12s}: ${alloc_usd:.2f} → {max_concurrent} min trades" if viable else f"  {broker.upper():12s}: ${alloc_usd:.2f} – NOT VIABLE")
        return {"total_balance": total_balance, "reserve_usd": round(reserve_usd, 2), "deployable_usd": round(deployable, 2), "allocations": allocations, "recommendations": "\n".join(recommendations)}

    def validate_trade(self, position_size_usd: float, score: float, max_entry_score: float, broker_name: str, account_balance: float) -> Dict:
        # Handle both 0-5 legacy scores and 0-100 AI scores.
        if max_entry_score and max_entry_score <= 5.0 and score > max_entry_score:
            confidence = min(float(score) / 100.0, 1.0)
        else:
            confidence = min(float(score) / float(max_entry_score), 1.0) if max_entry_score > 0 else 0.0
        broker_min = self.get_broker_minimum(broker_name)
        bump_result = self.get_minimum_bump_recommendation(
            position_size_usd=position_size_usd,
            broker_min=broker_min,
            confidence=confidence,
            account_balance=account_balance,
            score=score,
            max_entry_score=max_entry_score,
        )
        return {
            "valid": bump_result["valid"],
            "confidence": confidence,
            "recommended_size": bump_result["recommended_size"],
            "adaptive_min": bump_result["adaptive_min"],
            "reason": bump_result["reason"],
            "bumped": bump_result["bumped"],
        }


_sizer_instance: Optional[AdaptiveMinimumSizer] = None
_sizer_lock = __import__("threading").Lock()


def get_adaptive_minimum_sizer(edge_multiplier: float = DEFAULT_EDGE_MULTIPLIER, high_confidence_threshold: float = HIGH_CONFIDENCE_THRESHOLD, max_bump_fraction: float = MAX_BUMP_FRACTION) -> AdaptiveMinimumSizer:
    global _sizer_instance
    if _sizer_instance is None:
        with _sizer_lock:
            if _sizer_instance is None:
                _sizer_instance = AdaptiveMinimumSizer(edge_multiplier=edge_multiplier, high_confidence_threshold=high_confidence_threshold, max_bump_fraction=max_bump_fraction)
    return _sizer_instance


if __name__ == "__main__":
    import logging as _logging
    _logging.basicConfig(level=_logging.INFO, format="%(levelname)s - %(message)s")
    sizer = AdaptiveMinimumSizer()
    for conf in [1.0, 0.90, 0.44, 0.30, 0.0]:
        print(conf, sizer.get_minimum_bump_recommendation(4.45, 5.0, conf, 48.75, score=44.0))
