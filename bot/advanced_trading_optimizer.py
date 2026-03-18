"""
NIJA Advanced Trading Optimization System
==========================================

Comprehensive integration of:
1. Optimized Signal Scoring + Ranking (weighted by risk + volatility)
2. Dynamic Volatility-Based Sizing
3. Adaptive Drawdown Control
4. Smart Compounding Logic

Signal Ranking Formula
----------------------
Signals are ranked using a weighted composite score that accounts for
signal quality, trend strength, volume confirmation, and inverse volatility::

    composite_score = (
        entry_score    * 0.6   # primary signal quality
        + trend_strength * 0.2   # ADX / EMA trend alignment
        + volume_score   * 0.1   # volume confirmation
        + inv_volatility * 0.1   # lower volatility → higher score
    )

Diversity Filter
----------------
After ranking, a sector-aware diversity filter is applied so that the
final selection avoids concentrating all positions in the same correlated
sector.  When the top-N signals all come from the same sector (e.g. BTC,
ETH, SOL), the filter promotes the highest-ranked signal from an
under-represented sector, giving a spread such as BTC + LINK + AVAX.

This system coordinates all optimization modules to create a cohesive,
adaptive trading engine that maximizes returns while protecting capital.

Author: NIJA Trading Systems
Version: 1.1
Date: January 30, 2026
"""

import logging
from typing import Dict, Optional, Tuple, List
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import pandas as pd
import numpy as np

logger = logging.getLogger("nija.advanced_optimizer")

# ---------------------------------------------------------------------------
# Optional sector taxonomy for diversity filter
# ---------------------------------------------------------------------------
try:
    from crypto_sector_taxonomy import SYMBOL_TO_SECTOR
except ImportError:
    try:
        from bot.crypto_sector_taxonomy import SYMBOL_TO_SECTOR
    except ImportError:
        SYMBOL_TO_SECTOR = {}
        logger.debug("crypto_sector_taxonomy not available – diversity filter will use symbol prefix")

# Import existing modules
try:
    from enhanced_entry_scoring import EnhancedEntryScorer
except ImportError:
    try:
        from bot.enhanced_entry_scoring import EnhancedEntryScorer
    except ImportError:
        EnhancedEntryScorer = None
        logger.warning("EnhancedEntryScorer not available")

try:
    from volatility_adaptive_sizer import VolatilityAdaptiveSizer, VolatilityRegime
except ImportError:
    try:
        from bot.volatility_adaptive_sizer import VolatilityAdaptiveSizer, VolatilityRegime
    except ImportError:
        VolatilityAdaptiveSizer = None
        VolatilityRegime = None
        logger.warning("VolatilityAdaptiveSizer not available")

try:
    from drawdown_protection_system import DrawdownProtectionSystem, ProtectionLevel
except ImportError:
    try:
        from bot.drawdown_protection_system import DrawdownProtectionSystem, ProtectionLevel
    except ImportError:
        DrawdownProtectionSystem = None
        ProtectionLevel = None
        logger.warning("DrawdownProtectionSystem not available")

try:
    from profit_compounding_engine import ProfitCompoundingEngine, CompoundingStrategy
except ImportError:
    try:
        from bot.profit_compounding_engine import ProfitCompoundingEngine, CompoundingStrategy
    except ImportError:
        ProfitCompoundingEngine = None
        CompoundingStrategy = None
        logger.warning("ProfitCompoundingEngine not available")


class OptimizationMode(Enum):
    """Optimization modes for different capital levels"""
    MICRO_CAPITAL = "micro"  # < $500: Aggressive growth
    SMALL_CAPITAL = "small"  # $500-$5K: Balanced growth
    MEDIUM_CAPITAL = "medium"  # $5K-$50K: Conservative growth
    LARGE_CAPITAL = "large"  # > $50K: Capital preservation


@dataclass
class SignalRanking:
    """Ranked trading signal with metadata"""
    symbol: str
    score: float
    confidence: float
    volatility_regime: str
    position_size: float
    priority: int
    metadata: Dict = field(default_factory=dict)


@dataclass
class OptimizationConfig:
    """Configuration for the advanced optimization system"""
    # Signal scoring
    enable_signal_scoring: bool = True
    min_signal_score: float = 60.0  # Minimum score to trade
    min_confidence: float = 0.6  # Minimum confidence (0-1)
    
    # Volatility sizing
    enable_volatility_sizing: bool = True
    volatility_lookback: int = 14  # Periods for ATR calculation
    max_volatility_adjustment: float = 0.5  # Max reduction (50%)
    
    # Drawdown protection
    enable_drawdown_protection: bool = True
    drawdown_caution_threshold: float = 5.0  # % drawdown
    drawdown_halt_threshold: float = 20.0  # % drawdown
    
    # Compounding
    enable_compounding: bool = True
    compounding_strategy: str = "moderate"  # conservative/moderate/aggressive
    reinvest_percentage: float = 0.75  # 75% reinvest
    
    # Optimization mode
    optimization_mode: OptimizationMode = OptimizationMode.MICRO_CAPITAL


class AdvancedTradingOptimizer:
    """
    Advanced Trading Optimization System
    
    Coordinates signal scoring, volatility sizing, drawdown protection,
    and profit compounding for optimal trading performance.
    """
    
    def __init__(self, config: OptimizationConfig = None):
        """
        Initialize the advanced optimizer
        
        Args:
            config: Optimization configuration
        """
        self.config = config or OptimizationConfig()
        
        # Initialize sub-systems
        self.signal_scorer = None
        self.volatility_sizer = None
        self.drawdown_protection = None
        self.compounding_engine = None
        
        # State tracking
        self.active = True
        self.ranked_signals: List[SignalRanking] = []
        self.performance_history: List[Dict] = []
        
        # Initialize components
        self._initialize_components()
        
        logger.info("🚀 Advanced Trading Optimizer initialized")
        logger.info(f"   Mode: {self.config.optimization_mode.value.upper()}")
        logger.info(f"   Signal Scoring: {'✅' if self.config.enable_signal_scoring else '❌'}")
        logger.info(f"   Volatility Sizing: {'✅' if self.config.enable_volatility_sizing else '❌'}")
        logger.info(f"   Drawdown Protection: {'✅' if self.config.enable_drawdown_protection else '❌'}")
        logger.info(f"   Compounding: {'✅' if self.config.enable_compounding else '❌'}")
    
    def _initialize_components(self):
        """Initialize optimization components"""
        # Signal scorer
        if self.config.enable_signal_scoring and EnhancedEntryScorer:
            self.signal_scorer = EnhancedEntryScorer()
            logger.info("   ✅ Signal scorer initialized")
        
        # Volatility sizer
        if self.config.enable_volatility_sizing and VolatilityAdaptiveSizer:
            self.volatility_sizer = VolatilityAdaptiveSizer()
            logger.info("   ✅ Volatility sizer initialized")
        
        # Drawdown protection
        if self.config.enable_drawdown_protection and DrawdownProtectionSystem:
            self.drawdown_protection = DrawdownProtectionSystem()
            logger.info("   ✅ Drawdown protection initialized")
        
        # Compounding engine
        if self.config.enable_compounding and ProfitCompoundingEngine:
            strategy = getattr(CompoundingStrategy, self.config.compounding_strategy.upper(), 
                             CompoundingStrategy.MODERATE)
            self.compounding_engine = ProfitCompoundingEngine(strategy=strategy)
            logger.info("   ✅ Compounding engine initialized")
    
    def optimize_signal(self, df: pd.DataFrame, indicators: Dict, 
                       symbol: str, side: str) -> Tuple[float, float, Dict]:
        """
        Optimize and score a trading signal
        
        Args:
            df: Price dataframe
            indicators: Technical indicators
            symbol: Trading symbol
            side: 'long' or 'short'
            
        Returns:
            (score, confidence, metadata)
        """
        score = 50.0  # Default neutral score
        confidence = 0.5  # Default confidence
        metadata = {'optimized': False}
        
        if not self.signal_scorer:
            return score, confidence, metadata
        
        try:
            # Score the signal
            result = self.signal_scorer.score_entry(df, indicators, side)
            score = result.get('score', 50.0)
            confidence = result.get('confidence', 0.5)
            metadata = result.get('metadata', {})
            metadata['optimized'] = True
            
            logger.debug(f"   📊 Signal optimized: {symbol} {side.upper()} - Score: {score:.1f}, Confidence: {confidence:.2f}")
            
        except Exception as e:
            logger.warning(f"   ⚠️ Signal optimization failed for {symbol}: {e}")
        
        return score, confidence, metadata
    
    def optimize_position_size(self, base_size: float, df: pd.DataFrame, 
                              volatility_pct: float = None) -> Tuple[float, Dict]:
        """
        Optimize position size based on volatility
        
        Args:
            base_size: Base position size
            df: Price dataframe
            volatility_pct: Current volatility percentage
            
        Returns:
            (adjusted_size, adjustment_metadata)
        """
        if not self.volatility_sizer:
            return base_size, {'adjusted': False}
        
        try:
            # Get volatility adjustment
            result = self.volatility_sizer.calculate_position_size(
                base_size=base_size,
                df=df,
                volatility_pct=volatility_pct
            )
            
            adjusted_size = result.get('adjusted_size', base_size)
            metadata = result.get('metadata', {})
            metadata['adjusted'] = True
            
            adjustment_pct = ((adjusted_size - base_size) / base_size * 100) if base_size > 0 else 0
            logger.debug(f"   📐 Size optimized: ${base_size:.2f} → ${adjusted_size:.2f} ({adjustment_pct:+.1f}%)")
            
            return adjusted_size, metadata
            
        except Exception as e:
            logger.warning(f"   ⚠️ Position size optimization failed: {e}")
            return base_size, {'adjusted': False, 'error': str(e)}
    
    def check_drawdown_protection(self, current_balance: float, 
                                  peak_balance: float) -> Tuple[bool, float, str]:
        """
        Check drawdown protection status
        
        Args:
            current_balance: Current account balance
            peak_balance: Historical peak balance
            
        Returns:
            (can_trade, position_multiplier, protection_level)
        """
        if not self.drawdown_protection:
            return True, 1.0, "none"
        
        try:
            # Update drawdown protection
            self.drawdown_protection.update_balance(current_balance, peak_balance)
            
            # Get protection status
            status = self.drawdown_protection.get_status()
            can_trade = status.get('can_trade', True)
            multiplier = status.get('position_multiplier', 1.0)
            level = status.get('protection_level', 'normal')
            
            if level != 'normal':
                logger.info(f"   🛡️ Drawdown protection: {level.upper()} - Multiplier: {multiplier:.1%}")
            
            return can_trade, multiplier, level
            
        except Exception as e:
            logger.warning(f"   ⚠️ Drawdown protection check failed: {e}")
            return True, 1.0, "error"
    
    def update_compounding(self, realized_profit: float, current_balance: float) -> Dict:
        """
        Update profit compounding
        
        Args:
            realized_profit: Profit from closed trade
            current_balance: Current account balance
            
        Returns:
            Compounding status dict
        """
        if not self.compounding_engine:
            return {'enabled': False}
        
        try:
            # Record profit
            self.compounding_engine.record_profit(realized_profit, current_balance)
            
            # Get compounding status
            status = self.compounding_engine.get_status()
            
            if realized_profit > 0:
                reinvest_amount = status.get('reinvest_amount', 0)
                logger.info(f"   💰 Profit compounded: ${realized_profit:.2f} → ${reinvest_amount:.2f} reinvested")
            
            return status
            
        except Exception as e:
            logger.warning(f"   ⚠️ Compounding update failed: {e}")
            return {'enabled': False, 'error': str(e)}
    
    def rank_signals(self, signals: List[Dict]) -> List[SignalRanking]:
        """
        Rank and prioritize trading signals using a weighted composite score.

        Scoring Formula
        ---------------
        ::

            composite_score = (
                entry_score    * 0.6
                + trend_strength * 0.2
                + volume_score   * 0.1
                + inv_volatility * 0.1   # (1 / volatility), higher = better
            )

        After scoring, a diversity filter promotes the best signal from each
        sector so the final selection avoids over-concentration in correlated
        assets (e.g. BTC + ETH + SOL → BTC + LINK + AVAX).

        Args:
            signals: List of signal dictionaries.  Recognised keys:
                ``symbol``, ``score``, ``confidence``, ``trend_strength``,
                ``volume_score``, ``volatility_pct``, ``volatility_regime``,
                ``position_size``, ``metadata``.

        Returns:
            Ranked list of :class:`SignalRanking` objects, best first, with
            diversity already applied.
        """
        if not signals:
            return []

        ranked = []

        for signal in signals:
            symbol = signal.get('symbol', '')
            metadata = signal.get('metadata', {})

            # --- entry score (0-100) -----------------------------------------
            entry_score = float(signal.get('score', 50.0) or 50.0)

            # --- trend strength (0-100) – prefer explicit field, else metadata.
            # Falls back to a neutral 50 rather than the entry_score to avoid
            # inflating the composite for signals that lack trend data.
            _ts = signal.get('trend_strength') or metadata.get('trend_strength')
            trend_strength = max(0.0, min(100.0, float(_ts if _ts is not None else 50.0)))

            # --- volume score (0-100) -----------------------------------------
            # Falls back to a neutral 50 rather than deriving from entry_score
            # to avoid inflating the composite for signals without volume data.
            _vs = signal.get('volume_score') or metadata.get('volume_score')
            volume_score_raw = max(0.0, min(100.0, float(_vs if _vs is not None else 50.0)))

            # --- inverse-volatility component (0-100) -------------------------
            # Higher score = lower volatility = more favourable entry conditions.
            # Formula: min(100, 1 / volatility_pct * 100)
            #   0.5 % vol → 100 pts (cap)   1 % vol → 100 pts (cap)
            #   2 %   vol →  50 pts          5 % vol →  20 pts
            #  10 %   vol →  10 pts
            volatility_regime = signal.get('volatility_regime', 'normal')
            volatility_pct = signal.get('volatility_pct') or metadata.get('volatility_pct')

            if volatility_pct and float(volatility_pct) > 0:
                inv_volatility = min(100.0, 1.0 / float(volatility_pct) * 100.0)
            else:
                # Fall back to regime string estimate
                inv_volatility = float({
                    'extreme_low':  90.0,
                    'low':          75.0,
                    'normal':       50.0,
                    'high':         30.0,
                    'extreme_high': 15.0,
                }.get(str(volatility_regime), 50.0))

            # --- weighted composite score ------------------------------------
            composite_score = (
                entry_score      * 0.6
                + trend_strength * 0.2
                + volume_score_raw * 0.1
                + inv_volatility * 0.1
            )


            confidence = float(signal.get('confidence', 0.5) or 0.5)
            position_size = signal.get('position_size', 0)

            ranking = SignalRanking(
                symbol=symbol,
                score=round(composite_score, 2),
                confidence=confidence,
                volatility_regime=str(volatility_regime),
                position_size=position_size,
                priority=int(composite_score),
                metadata=metadata,
            )

            ranked.append(ranking)

        # Sort descending by composite score
        ranked.sort(key=lambda x: x.score, reverse=True)

        # Apply sector-diversity filter
        ranked = _apply_diversity_filter(ranked)

        # Assign sequential priority labels (1 = best)
        for i, ranking in enumerate(ranked):
            ranking.priority = i + 1

        self.ranked_signals = ranked

        logger.info(f"   🏆 Ranked {len(ranked)} signals (diversity filter applied)")
        if ranked:
            top = ranked[0]
            logger.info(
                f"      #1: {top.symbol} – Score: {top.score:.1f}, "
                f"Confidence: {top.confidence:.2f}"
            )

        return ranked
    
    def get_optimization_summary(self) -> Dict:
        """
        Get comprehensive optimization summary
        
        Returns:
            Summary dictionary
        """
        summary = {
            'active': self.active,
            'mode': self.config.optimization_mode.value,
            'components': {
                'signal_scoring': self.signal_scorer is not None,
                'volatility_sizing': self.volatility_sizer is not None,
                'drawdown_protection': self.drawdown_protection is not None,
                'compounding': self.compounding_engine is not None
            },
            'ranked_signals_count': len(self.ranked_signals),
            'config': {
                'min_signal_score': self.config.min_signal_score,
                'min_confidence': self.config.min_confidence,
                'reinvest_percentage': self.config.reinvest_percentage,
                'drawdown_caution_threshold': self.config.drawdown_caution_threshold
            }
        }
        
        # Add component-specific status
        if self.drawdown_protection:
            try:
                summary['drawdown_status'] = self.drawdown_protection.get_status()
            except Exception:
                pass
        
        if self.compounding_engine:
            try:
                summary['compounding_status'] = self.compounding_engine.get_status()
            except Exception:
                pass
        
        return summary
    
    def optimize_trade(self, trade_params: Dict) -> Dict:
        """
        Comprehensive trade optimization
        
        Args:
            trade_params: Dictionary with trade parameters:
                - symbol: Trading symbol
                - side: 'long' or 'short'
                - df: Price dataframe
                - indicators: Technical indicators
                - base_position_size: Base position size
                - current_balance: Current balance
                - peak_balance: Peak balance
                
        Returns:
            Optimized trade parameters
        """
        optimized = trade_params.copy()
        optimized['optimizations'] = {}
        
        # 1. Optimize signal scoring
        if self.signal_scorer:
            score, confidence, metadata = self.optimize_signal(
                df=trade_params.get('df'),
                indicators=trade_params.get('indicators', {}),
                symbol=trade_params.get('symbol', ''),
                side=trade_params.get('side', 'long')
            )
            optimized['score'] = score
            optimized['confidence'] = confidence
            optimized['optimizations']['signal'] = metadata
            
            # Filter low-quality signals
            if score < self.config.min_signal_score or confidence < self.config.min_confidence:
                optimized['rejected'] = True
                optimized['rejection_reason'] = f"Score {score:.1f} < {self.config.min_signal_score} or Confidence {confidence:.2f} < {self.config.min_confidence}"
                return optimized
        
        # 2. Optimize position size with volatility
        base_size = trade_params.get('base_position_size', 0)
        if self.volatility_sizer and base_size > 0:
            adjusted_size, vol_metadata = self.optimize_position_size(
                base_size=base_size,
                df=trade_params.get('df'),
                volatility_pct=trade_params.get('volatility_pct')
            )
            optimized['position_size'] = adjusted_size
            optimized['optimizations']['volatility'] = vol_metadata
        
        # 3. Apply drawdown protection
        if self.drawdown_protection:
            can_trade, multiplier, level = self.check_drawdown_protection(
                current_balance=trade_params.get('current_balance', 0),
                peak_balance=trade_params.get('peak_balance', 0)
            )
            
            if not can_trade:
                optimized['rejected'] = True
                optimized['rejection_reason'] = f"Drawdown protection: {level}"
                return optimized
            
            # Apply multiplier to position size
            if 'position_size' in optimized:
                optimized['position_size'] *= multiplier
            
            optimized['optimizations']['drawdown'] = {
                'can_trade': can_trade,
                'multiplier': multiplier,
                'level': level
            }
        
        optimized['rejected'] = False
        return optimized


# ---------------------------------------------------------------------------
# Diversity filter
# ---------------------------------------------------------------------------

# Maximum signals allowed from the same sector before promotion kicks in.
_MAX_PER_SECTOR: int = 1


def _get_sector(symbol: str) -> str:
    """
    Return a sector string for *symbol*.

    Uses the ``SYMBOL_TO_SECTOR`` mapping when available; falls back to a
    simple prefix heuristic (the base currency before the first ``-`` or
    last three characters).

    Examples
    --------
    >>> _get_sector("BTC-USD")
    'bitcoin'
    >>> _get_sector("ETH-USDT")
    'ethereum'
    >>> _get_sector("UNKNOWN-USD")
    'misc'
    """
    if SYMBOL_TO_SECTOR and symbol in SYMBOL_TO_SECTOR:
        sector = SYMBOL_TO_SECTOR[symbol]
        return sector.value if hasattr(sector, 'value') else str(sector)

    # Prefix fallback: strip quote currency to get base asset.
    # Handles: 'BTC-USD', 'BTCUSDT' (last 4 chars), bare 'BTC'.
    if '-' in symbol:
        base = symbol.split('-')[0].upper()
    elif len(symbol) > 4 and symbol.endswith(('USDT', 'USDC', 'BUSD')):
        base = symbol[:-4].upper()
    elif len(symbol) > 3 and symbol.endswith(('USD', 'BTC', 'ETH')):
        base = symbol[:-3].upper()
    else:
        base = symbol.upper()
    return base if base else 'misc'


def _apply_diversity_filter(
    ranked: List[SignalRanking],
    max_per_sector: int = _MAX_PER_SECTOR,
) -> List[SignalRanking]:
    """
    Promote sector diversity in a pre-sorted signal list.

    Algorithm
    ---------
    1. Iterate through *ranked* (already sorted best-first).
    2. Track how many signals have been *selected* from each sector.
    3. If a signal's sector has already reached *max_per_sector*,
       it is marked as ``diversity_skipped`` in its metadata and moved to
       the tail of the list so under-represented sectors surface first.

    The returned list always contains every input signal – nothing is
    discarded – but lower-ranked correlated signals are moved toward the
    end so callers that take ``ranked[:N]`` naturally get a diversified set.

    Parameters
    ----------
    ranked : list[SignalRanking]
        Signals sorted by composite score, best first.
    max_per_sector : int
        How many signals per sector are allowed before the filter
        promotes a candidate from a different sector (default: 1).

    Returns
    -------
    list[SignalRanking]
        Re-ordered list with sector diversity promoted to the front.
    """
    if not ranked:
        return ranked

    sector_counts: Dict[str, int] = {}
    promoted: List[SignalRanking] = []
    deferred: List[SignalRanking] = []
    skipped_sectors: List[str] = []

    for ranking in ranked:
        sector = _get_sector(ranking.symbol)
        count = sector_counts.get(sector, 0)

        if count < max_per_sector:
            sector_counts[sector] = count + 1
            promoted.append(ranking)
        else:
            # Too correlated with an already-selected signal – defer it
            ranking.metadata['diversity_skipped'] = True
            ranking.metadata['diversity_sector'] = sector
            deferred.append(ranking)
            if sector not in skipped_sectors:
                skipped_sectors.append(sector)

    if skipped_sectors:
        logger.info(
            "   🌐 Diversity filter deferred %d signal(s) from sector(s): %s",
            len(deferred),
            ", ".join(skipped_sectors),
        )

    return promoted + deferred


def create_optimizer(capital_balance: float = 100.0,
                    config: OptimizationConfig = None) -> AdvancedTradingOptimizer:
    """
    Factory function to create optimizer with appropriate mode for capital level
    
    Args:
        capital_balance: Current capital balance
        config: Optional custom configuration
        
    Returns:
        Configured AdvancedTradingOptimizer instance
    """
    if config is None:
        config = OptimizationConfig()
        
        # Auto-detect optimization mode based on capital
        if capital_balance < 500:
            config.optimization_mode = OptimizationMode.MICRO_CAPITAL
            config.compounding_strategy = "aggressive"
            config.reinvest_percentage = 0.90
        elif capital_balance < 5000:
            config.optimization_mode = OptimizationMode.SMALL_CAPITAL
            config.compounding_strategy = "moderate"
            config.reinvest_percentage = 0.75
        elif capital_balance < 50000:
            config.optimization_mode = OptimizationMode.MEDIUM_CAPITAL
            config.compounding_strategy = "moderate"
            config.reinvest_percentage = 0.60
        else:
            config.optimization_mode = OptimizationMode.LARGE_CAPITAL
            config.compounding_strategy = "conservative"
            config.reinvest_percentage = 0.50
    
    return AdvancedTradingOptimizer(config)


if __name__ == "__main__":
    # Test the optimizer
    logging.basicConfig(level=logging.INFO)
    
    print("=" * 80)
    print("ADVANCED TRADING OPTIMIZER - TEST")
    print("=" * 80)
    
    # Create optimizer for micro capital
    optimizer = create_optimizer(capital_balance=250.0)
    
    # Get summary
    summary = optimizer.get_optimization_summary()
    print("\n📊 Optimization Summary:")
    print(f"   Mode: {summary['mode']}")
    print(f"   Components Active:")
    for component, active in summary['components'].items():
        print(f"      {component}: {'✅' if active else '❌'}")
    
    print("\n✅ Advanced Trading Optimizer ready to scale! 🔥")
