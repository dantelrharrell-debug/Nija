"""
NIJA Validation Layer

Mathematical validation and backtesting layer separate from live performance.
This layer validates strategies mathematically without implying forward performance.

Responsibilities:
- Strategy backtesting and validation
- Historical data analysis
- Mathematical model validation
- Statistical significance testing
- Strategy parameter optimization

Author: NIJA Trading Systems
Version: 1.0
Date: February 2026
"""

import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from datetime import datetime
import numpy as np

try:
    from institutional_disclaimers import get_institutional_logger, VALIDATION_DISCLAIMER
except ImportError:
    from bot.institutional_disclaimers import get_institutional_logger, VALIDATION_DISCLAIMER

logger = get_institutional_logger(__name__)


@dataclass
class ValidationResult:
    """Result from strategy validation"""
    strategy_name: str
    validation_date: datetime
    sample_size: int
    win_rate: float
    profit_factor: float
    sharpe_ratio: float
    max_drawdown: float
    total_trades: int
    validation_period_days: int
    statistical_confidence: float
    notes: str


class ValidationLayer:
    """
    Validation Layer - Mathematical strategy validation
    
    This layer is strictly for mathematical validation and does NOT
    represent historical or forward performance.
    """
    
    def __init__(self):
        """Initialize validation layer"""
        self.validation_results: List[ValidationResult] = []
        logger.show_validation_disclaimer()
        logger.info("✅ Validation Layer initialized")
    
    def validate_strategy(self, 
                         strategy_name: str,
                         historical_trades: List[Dict],
                         validation_period_days: int = 90) -> ValidationResult:
        """
        Mathematically validate a trading strategy.
        
        DISCLAIMER: This is mathematical validation only. Does not represent
        historical or forward performance.
        
        Args:
            strategy_name: Name of strategy to validate
            historical_trades: List of historical trade data
            validation_period_days: Days of data to validate
            
        Returns:
            ValidationResult with mathematical statistics
        """
        logger.info(f"🔬 Mathematical validation of strategy: {strategy_name}")
        logger.show_validation_disclaimer()
        
        if not historical_trades:
            logger.warning("No trade data available for validation")
            return ValidationResult(
                strategy_name=strategy_name,
                validation_date=datetime.now(),
                sample_size=0,
                win_rate=0.0,
                profit_factor=0.0,
                sharpe_ratio=0.0,
                max_drawdown=0.0,
                total_trades=0,
                validation_period_days=validation_period_days,
                statistical_confidence=0.0,
                notes="No data available"
            )
        
        # Calculate mathematical statistics
        winning_trades = [t for t in historical_trades if t.get('profit', 0) > 0]
        losing_trades = [t for t in historical_trades if t.get('profit', 0) <= 0]
        
        total_trades = len(historical_trades)
        win_rate = (len(winning_trades) / total_trades * 100) if total_trades > 0 else 0.0
        
        total_profit = sum(t.get('profit', 0) for t in winning_trades)
        total_loss = abs(sum(t.get('profit', 0) for t in losing_trades))
        profit_factor = (total_profit / total_loss) if total_loss > 0 else 0.0
        
        # Calculate returns for Sharpe ratio
        returns = [t.get('profit', 0) for t in historical_trades]
        if len(returns) > 1:
            sharpe_ratio = (np.mean(returns) / np.std(returns)) if np.std(returns) > 0 else 0.0
        else:
            sharpe_ratio = 0.0
        
        # Max drawdown (simplified)
        cumulative_returns = np.cumsum(returns)
        running_max = np.maximum.accumulate(cumulative_returns)
        drawdowns = running_max - cumulative_returns
        max_drawdown = np.max(drawdowns) if len(drawdowns) > 0 else 0.0
        
        # Statistical confidence (simplified - based on sample size)
        statistical_confidence = min(100.0, (total_trades / 100.0) * 100.0)
        
        result = ValidationResult(
            strategy_name=strategy_name,
            validation_date=datetime.now(),
            sample_size=total_trades,
            win_rate=win_rate,
            profit_factor=profit_factor,
            sharpe_ratio=sharpe_ratio,
            max_drawdown=max_drawdown,
            total_trades=total_trades,
            validation_period_days=validation_period_days,
            statistical_confidence=statistical_confidence,
            notes="Mathematical validation only"
        )
        
        self.validation_results.append(result)
        
        logger.info(f"✅ Validation complete: Win Rate={win_rate:.1f}%, "
                   f"Profit Factor={profit_factor:.2f}, Sample={total_trades} trades")
        
        return result
    
    def get_validation_summary(self) -> Dict[str, Any]:
        """
        Get summary of all validation results.
        
        Returns:
            Dictionary with validation summary
        """
        logger.show_validation_disclaimer()
        
        return {
            'disclaimer': 'MATHEMATICAL VALIDATION ONLY - DOES NOT REPRESENT HISTORICAL OR FORWARD PERFORMANCE',
            'total_validations': len(self.validation_results),
            'validations': [
                {
                    'strategy': v.strategy_name,
                    'date': v.validation_date.isoformat(),
                    'win_rate': v.win_rate,
                    'profit_factor': v.profit_factor,
                    'sample_size': v.sample_size,
                    'confidence': v.statistical_confidence,
                    'notes': v.notes
                }
                for v in self.validation_results
            ]
        }


# Global singleton
_validation_layer: Optional[ValidationLayer] = None


def get_validation_layer() -> ValidationLayer:
    """
    Get or create the global validation layer instance.
    
    Returns:
        ValidationLayer instance
    """
    global _validation_layer
    
    if _validation_layer is None:
        _validation_layer = ValidationLayer()
    
    return _validation_layer
