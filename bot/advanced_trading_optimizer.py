"""
NIJA Advanced Trading Optimization System
==========================================

Comprehensive integration of:
1. Optimized Signal Scoring + Ranking
2. Dynamic Volatility-Based Sizing  
3. Adaptive Drawdown Control
4. Smart Compounding Logic

This system coordinates all optimization modules to create a cohesive,
adaptive trading engine that maximizes returns while protecting capital.

Author: NIJA Trading Systems
Version: 1.0
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
        Rank and prioritize trading signals
        
        Args:
            signals: List of signal dictionaries
            
        Returns:
            Ranked list of signals
        """
        if not signals:
            return []
        
        ranked = []
        
        for signal in signals:
            # Extract signal data
            symbol = signal.get('symbol', '')
            score = signal.get('score', 50.0)
            confidence = signal.get('confidence', 0.5)
            volatility = signal.get('volatility_regime', 'normal')
            position_size = signal.get('position_size', 0)
            
            # Calculate composite priority
            # Higher score + higher confidence + lower volatility = higher priority
            volatility_weight = {
                'extreme_low': 1.2,
                'low': 1.1,
                'normal': 1.0,
                'high': 0.9,
                'extreme_high': 0.8
            }.get(volatility, 1.0)
            
            composite_score = score * confidence * volatility_weight
            
            # Create ranking
            ranking = SignalRanking(
                symbol=symbol,
                score=score,
                confidence=confidence,
                volatility_regime=volatility,
                position_size=position_size,
                priority=int(composite_score),
                metadata=signal.get('metadata', {})
            )
            
            ranked.append(ranking)
        
        # Sort by priority (highest first)
        ranked.sort(key=lambda x: x.priority, reverse=True)
        
        # Assign final priority rankings
        for i, ranking in enumerate(ranked):
            ranking.priority = i + 1
        
        self.ranked_signals = ranked
        
        logger.info(f"   🏆 Ranked {len(ranked)} signals")
        if ranked:
            top = ranked[0]
            logger.info(f"      #1: {top.symbol} - Score: {top.score:.1f}, Confidence: {top.confidence:.2f}")
        
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
            except:
                pass
        
        if self.compounding_engine:
            try:
                summary['compounding_status'] = self.compounding_engine.get_status()
            except:
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
