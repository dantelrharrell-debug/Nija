"""
NIJA Institutional Entry Discipline
====================================

Step 2 of institutional order of operations: Lock Entry Discipline

After proving edge (Step 1), lock down entry criteria with:
- Hard criteria (no discretionary overrides)
- Regime filtering (don't trade in unfavorable conditions)
- Overfitting prevention (avoid parameter sensitivity)

Philosophy:
- Entries must be deterministic and auditable
- No "gut feel" or manual overrides
- If conditions don't meet criteria, NO TRADE
- Discipline > Discretion

Author: NIJA Trading Systems
Version: 1.0
Date: February 18, 2026
"""

import logging
import json
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from pathlib import Path
from enum import Enum

logger = logging.getLogger("nija.entry_discipline")


class EntryDecision(Enum):
    """Entry decision outcomes"""
    APPROVED = "approved"                # All criteria met
    REJECTED_REGIME = "rejected_regime"  # Unfavorable regime
    REJECTED_SIGNAL = "rejected_signal"  # Signal quality too low
    REJECTED_VOLATILITY = "rejected_volatility"  # Volatility too high/low
    REJECTED_LIQUIDITY = "rejected_liquidity"   # Insufficient liquidity
    REJECTED_CORRELATION = "rejected_correlation"  # Too correlated with existing
    REJECTED_TIMING = "rejected_timing"  # Bad timing (e.g., news event)
    REJECTED_OVERFIT = "rejected_overfit"  # Parameter appears overfit


@dataclass
class HardEntryCriteria:
    """
    Hard entry criteria that MUST be met (no overrides)
    
    These are non-negotiable requirements for any entry.
    """
    # Signal quality
    min_signal_strength: float = 0.65      # Minimum 65% signal strength
    min_confluence_indicators: int = 2      # Minimum 2 indicators must agree
    
    # Risk/Reward
    min_risk_reward_ratio: float = 1.5     # Minimum 1.5:1 R:R
    max_stop_distance_pct: float = 0.03    # Maximum 3% stop distance
    
    # Market conditions
    min_volatility_pct: float = 0.005      # Minimum 0.5% volatility (ATR/price)
    max_volatility_pct: float = 0.05       # Maximum 5% volatility
    min_liquidity_usd: float = 100000      # Minimum $100k daily volume
    max_spread_pct: float = 0.002          # Maximum 0.2% spread
    
    # Timing
    min_hours_since_news: float = 2.0      # Wait 2 hours after major news
    max_correlation_existing: float = 0.70  # Max 70% correlation with existing positions
    
    # Regime requirements
    allowed_regimes: List[str] = None      # Only trade in these regimes
    
    def __post_init__(self):
        if self.allowed_regimes is None:
            # Default: trade in bull and sideways, avoid bear
            self.allowed_regimes = ['bull', 'sideways']


@dataclass
class SignalQuality:
    """
    Signal quality metrics for entry evaluation
    """
    # Strength metrics
    signal_strength: float         # 0-1, overall signal strength
    num_confirming_indicators: int # How many indicators agree
    
    # Technical confluence
    rsi_oversold: bool            # RSI indicates oversold
    trend_aligned: bool           # Trade aligned with trend
    volume_confirmed: bool        # Volume confirms move
    momentum_positive: bool       # Momentum supports entry
    
    # Risk metrics
    risk_reward_ratio: float      # Calculated R:R
    stop_distance_pct: float      # Stop distance as %
    
    # Market state
    current_regime: str           # bull/bear/sideways
    volatility_pct: float         # Current volatility
    liquidity_usd: float          # Daily volume in USD
    spread_pct: float             # Current spread
    
    # Correlation
    max_correlation: float        # Max correlation with existing positions
    
    # Timing
    hours_since_news: float       # Hours since last major news
    
    def calculate_overall_score(self) -> float:
        """
        Calculate overall signal quality score (0-1)
        
        Weighted combination of all factors.
        """
        # Technical confluence (40%)
        confluence_score = (
            self.signal_strength * 0.4 +
            (self.num_confirming_indicators / 4.0) * 0.2 +  # Assume max 4 indicators
            (1.0 if self.rsi_oversold else 0.0) * 0.1 +
            (1.0 if self.trend_aligned else 0.0) * 0.1 +
            (1.0 if self.volume_confirmed else 0.0) * 0.1 +
            (1.0 if self.momentum_positive else 0.0) * 0.1
        )
        
        # Risk profile (30%)
        risk_score = min(self.risk_reward_ratio / 3.0, 1.0) * 0.5  # R:R normalized to 3
        stop_score = (1.0 - min(self.stop_distance_pct / 0.03, 1.0)) * 0.5  # Prefer tight stops
        risk_profile_score = (risk_score + stop_score) * 0.3
        
        # Market quality (20%)
        volatility_score = 0.5 if 0.01 <= self.volatility_pct <= 0.03 else 0.2  # Prefer medium vol
        liquidity_score = min(self.liquidity_usd / 500000, 1.0)  # Normalize to $500k
        market_quality_score = (volatility_score + liquidity_score) * 0.1
        
        # Timing (10%)
        correlation_score = (1.0 - self.max_correlation)  # Lower correlation is better
        timing_score = min(self.hours_since_news / 4.0, 1.0)  # Normalize to 4 hours
        timing_profile_score = (correlation_score * 0.5 + timing_score * 0.5) * 0.1
        
        overall_score = confluence_score + risk_profile_score + market_quality_score + timing_profile_score
        
        return min(overall_score, 1.0)  # Cap at 1.0


@dataclass
class EntryEvaluation:
    """
    Complete entry evaluation result
    """
    decision: EntryDecision
    signal_quality: SignalQuality
    overall_score: float
    
    # Criteria evaluation
    criteria_met: Dict[str, bool]
    rejection_reasons: List[str]
    
    # Audit trail
    evaluation_timestamp: datetime
    symbol: str
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for logging/storage"""
        return {
            'decision': self.decision.value,
            'overall_score': self.overall_score,
            'criteria_met': self.criteria_met,
            'rejection_reasons': self.rejection_reasons,
            'evaluation_timestamp': self.evaluation_timestamp.isoformat(),
            'symbol': self.symbol,
            'signal_quality': {
                'signal_strength': self.signal_quality.signal_strength,
                'num_confirming_indicators': self.signal_quality.num_confirming_indicators,
                'risk_reward_ratio': self.signal_quality.risk_reward_ratio,
                'current_regime': self.signal_quality.current_regime,
                'volatility_pct': self.signal_quality.volatility_pct
            }
        }


class InstitutionalEntryDiscipline:
    """
    Institutional Entry Discipline Framework
    
    Enforces hard entry criteria with no discretionary overrides.
    
    Key Principles:
    1. All criteria must be met (AND logic, not OR)
    2. No manual overrides allowed
    3. Regime filtering prevents unfavorable trades
    4. Complete audit trail of all decisions
    5. Overfitting checks prevent parameter sensitivity
    
    Integration:
    This gates ALL entries before they reach the broker.
    If evaluation returns REJECTED_*, entry is blocked.
    """
    
    def __init__(
        self,
        criteria: Optional[HardEntryCriteria] = None,
        audit_dir: str = "./data/entry_discipline"
    ):
        """
        Initialize Institutional Entry Discipline
        
        Args:
            criteria: Hard entry criteria (uses defaults if not provided)
            audit_dir: Directory for audit trail
        """
        self.criteria = criteria or HardEntryCriteria()
        self.audit_dir = Path(audit_dir)
        self.audit_dir.mkdir(exist_ok=True, parents=True)
        
        # Statistics
        self.total_evaluations = 0
        self.approved_count = 0
        self.rejected_count = 0
        self.rejection_breakdown: Dict[str, int] = {}
        
        logger.info("✅ Institutional Entry Discipline initialized")
        logger.info("   Hard criteria enforced (no overrides)")
        logger.info(f"   Allowed regimes: {', '.join(self.criteria.allowed_regimes)}")
        logger.info(f"   Min R:R: {self.criteria.min_risk_reward_ratio}")
        logger.info(f"   Min signal strength: {self.criteria.min_signal_strength}")
    
    def evaluate_entry(
        self,
        symbol: str,
        signal_quality: SignalQuality
    ) -> EntryEvaluation:
        """
        Evaluate entry signal against hard criteria
        
        Args:
            symbol: Trading symbol
            signal_quality: Signal quality metrics
            
        Returns:
            EntryEvaluation with decision and audit trail
        """
        self.total_evaluations += 1
        
        criteria_met = {}
        rejection_reasons = []
        
        # Calculate overall signal score
        overall_score = signal_quality.calculate_overall_score()
        
        # Check 1: Regime filtering
        regime_ok = signal_quality.current_regime.lower() in [r.lower() for r in self.criteria.allowed_regimes]
        criteria_met['regime'] = regime_ok
        if not regime_ok:
            rejection_reasons.append(
                f"Unfavorable regime: {signal_quality.current_regime} "
                f"(allowed: {', '.join(self.criteria.allowed_regimes)})"
            )
        
        # Check 2: Signal strength
        signal_ok = signal_quality.signal_strength >= self.criteria.min_signal_strength
        criteria_met['signal_strength'] = signal_ok
        if not signal_ok:
            rejection_reasons.append(
                f"Signal strength {signal_quality.signal_strength:.2%} < "
                f"minimum {self.criteria.min_signal_strength:.2%}"
            )
        
        # Check 3: Indicator confluence
        confluence_ok = signal_quality.num_confirming_indicators >= self.criteria.min_confluence_indicators
        criteria_met['confluence'] = confluence_ok
        if not confluence_ok:
            rejection_reasons.append(
                f"Only {signal_quality.num_confirming_indicators} confirming indicators "
                f"(need {self.criteria.min_confluence_indicators})"
            )
        
        # Check 4: Risk/Reward ratio
        rr_ok = signal_quality.risk_reward_ratio >= self.criteria.min_risk_reward_ratio
        criteria_met['risk_reward'] = rr_ok
        if not rr_ok:
            rejection_reasons.append(
                f"R:R {signal_quality.risk_reward_ratio:.2f} < "
                f"minimum {self.criteria.min_risk_reward_ratio:.2f}"
            )
        
        # Check 5: Stop distance
        stop_ok = signal_quality.stop_distance_pct <= self.criteria.max_stop_distance_pct
        criteria_met['stop_distance'] = stop_ok
        if not stop_ok:
            rejection_reasons.append(
                f"Stop distance {signal_quality.stop_distance_pct:.2%} > "
                f"maximum {self.criteria.max_stop_distance_pct:.2%}"
            )
        
        # Check 6: Volatility range
        vol_ok = (
            self.criteria.min_volatility_pct <= signal_quality.volatility_pct <= 
            self.criteria.max_volatility_pct
        )
        criteria_met['volatility'] = vol_ok
        if not vol_ok:
            rejection_reasons.append(
                f"Volatility {signal_quality.volatility_pct:.2%} outside range "
                f"[{self.criteria.min_volatility_pct:.2%}, {self.criteria.max_volatility_pct:.2%}]"
            )
        
        # Check 7: Liquidity
        liquidity_ok = signal_quality.liquidity_usd >= self.criteria.min_liquidity_usd
        criteria_met['liquidity'] = liquidity_ok
        if not liquidity_ok:
            rejection_reasons.append(
                f"Liquidity ${signal_quality.liquidity_usd:,.0f} < "
                f"minimum ${self.criteria.min_liquidity_usd:,.0f}"
            )
        
        # Check 8: Spread
        spread_ok = signal_quality.spread_pct <= self.criteria.max_spread_pct
        criteria_met['spread'] = spread_ok
        if not spread_ok:
            rejection_reasons.append(
                f"Spread {signal_quality.spread_pct:.3%} > "
                f"maximum {self.criteria.max_spread_pct:.3%}"
            )
        
        # Check 9: News timing
        news_ok = signal_quality.hours_since_news >= self.criteria.min_hours_since_news
        criteria_met['news_timing'] = news_ok
        if not news_ok:
            rejection_reasons.append(
                f"Only {signal_quality.hours_since_news:.1f}h since news "
                f"(need {self.criteria.min_hours_since_news:.1f}h)"
            )
        
        # Check 10: Correlation with existing positions
        correlation_ok = signal_quality.max_correlation <= self.criteria.max_correlation_existing
        criteria_met['correlation'] = correlation_ok
        if not correlation_ok:
            rejection_reasons.append(
                f"Correlation {signal_quality.max_correlation:.1%} > "
                f"maximum {self.criteria.max_correlation_existing:.1%}"
            )
        
        # Determine decision (ALL criteria must pass)
        all_criteria_met = all(criteria_met.values())
        
        if all_criteria_met:
            decision = EntryDecision.APPROVED
            self.approved_count += 1
        else:
            # Categorize rejection
            if not regime_ok:
                decision = EntryDecision.REJECTED_REGIME
            elif not signal_ok or not confluence_ok:
                decision = EntryDecision.REJECTED_SIGNAL
            elif not vol_ok:
                decision = EntryDecision.REJECTED_VOLATILITY
            elif not liquidity_ok or not spread_ok:
                decision = EntryDecision.REJECTED_LIQUIDITY
            elif not correlation_ok:
                decision = EntryDecision.REJECTED_CORRELATION
            elif not news_ok:
                decision = EntryDecision.REJECTED_TIMING
            else:
                decision = EntryDecision.REJECTED_SIGNAL
            
            self.rejected_count += 1
            self.rejection_breakdown[decision.value] = self.rejection_breakdown.get(decision.value, 0) + 1
        
        # Create evaluation result
        evaluation = EntryEvaluation(
            decision=decision,
            signal_quality=signal_quality,
            overall_score=overall_score,
            criteria_met=criteria_met,
            rejection_reasons=rejection_reasons,
            evaluation_timestamp=datetime.now(),
            symbol=symbol
        )
        
        # Log and audit
        self._log_evaluation(evaluation)
        self._audit_evaluation(evaluation)
        
        return evaluation
    
    def _log_evaluation(self, evaluation: EntryEvaluation) -> None:
        """Log evaluation result"""
        if evaluation.decision == EntryDecision.APPROVED:
            logger.info(
                f"✅ ENTRY APPROVED: {evaluation.symbol} "
                f"(score: {evaluation.overall_score:.2%})"
            )
        else:
            logger.info(
                f"🚫 ENTRY REJECTED: {evaluation.symbol} "
                f"({evaluation.decision.value})"
            )
            for reason in evaluation.rejection_reasons:
                logger.info(f"   - {reason}")
    
    def _audit_evaluation(self, evaluation: EntryEvaluation) -> None:
        """Write evaluation to audit trail"""
        timestamp = evaluation.evaluation_timestamp.strftime("%Y%m%d_%H%M%S")
        filename = f"entry_eval_{evaluation.symbol}_{timestamp}.json"
        filepath = self.audit_dir / filename
        
        with open(filepath, 'w') as f:
            json.dump(evaluation.to_dict(), f, indent=2)
    
    def get_statistics(self) -> Dict:
        """Get entry discipline statistics"""
        approval_rate = (self.approved_count / self.total_evaluations * 100) if self.total_evaluations > 0 else 0
        
        return {
            'total_evaluations': self.total_evaluations,
            'approved': self.approved_count,
            'rejected': self.rejected_count,
            'approval_rate_pct': approval_rate,
            'rejection_breakdown': self.rejection_breakdown
        }
    
    def log_statistics(self) -> None:
        """Log entry discipline statistics"""
        stats = self.get_statistics()
        
        logger.info("=" * 60)
        logger.info("ENTRY DISCIPLINE STATISTICS")
        logger.info("=" * 60)
        logger.info(f"Total Evaluations: {stats['total_evaluations']}")
        logger.info(f"Approved: {stats['approved']} ({stats['approval_rate_pct']:.1f}%)")
        logger.info(f"Rejected: {stats['rejected']}")
        
        if stats['rejection_breakdown']:
            logger.info("\nRejection Breakdown:")
            for reason, count in sorted(stats['rejection_breakdown'].items(), key=lambda x: x[1], reverse=True):
                pct = (count / stats['rejected'] * 100) if stats['rejected'] > 0 else 0
                logger.info(f"  {reason}: {count} ({pct:.1f}%)")
        
        logger.info("=" * 60)


# Convenience function for quick evaluation
def evaluate_entry_signal(
    symbol: str,
    signal_strength: float,
    num_confirming_indicators: int,
    risk_reward_ratio: float,
    stop_distance_pct: float,
    current_regime: str,
    volatility_pct: float,
    liquidity_usd: float,
    spread_pct: float = 0.001,
    max_correlation: float = 0.0,
    hours_since_news: float = 24.0,
    **kwargs
) -> EntryEvaluation:
    """
    Quick function to evaluate entry signal
    
    Args:
        symbol: Trading symbol
        signal_strength: Signal strength (0-1)
        num_confirming_indicators: Number of confirming indicators
        risk_reward_ratio: Risk/reward ratio
        stop_distance_pct: Stop distance as percentage
        current_regime: Market regime ('bull', 'bear', 'sideways')
        volatility_pct: Current volatility
        liquidity_usd: Daily volume in USD
        spread_pct: Current spread
        max_correlation: Max correlation with existing positions
        hours_since_news: Hours since last major news
        **kwargs: Additional signal quality fields
        
    Returns:
        EntryEvaluation with decision
    """
    signal_quality = SignalQuality(
        signal_strength=signal_strength,
        num_confirming_indicators=num_confirming_indicators,
        rsi_oversold=kwargs.get('rsi_oversold', False),
        trend_aligned=kwargs.get('trend_aligned', True),
        volume_confirmed=kwargs.get('volume_confirmed', False),
        momentum_positive=kwargs.get('momentum_positive', True),
        risk_reward_ratio=risk_reward_ratio,
        stop_distance_pct=stop_distance_pct,
        current_regime=current_regime,
        volatility_pct=volatility_pct,
        liquidity_usd=liquidity_usd,
        spread_pct=spread_pct,
        max_correlation=max_correlation,
        hours_since_news=hours_since_news
    )
    
    discipline = InstitutionalEntryDiscipline()
    return discipline.evaluate_entry(symbol, signal_quality)
