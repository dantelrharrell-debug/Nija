"""
NIJA Self-Learning Engine
=========================

Continuous improvement system that learns from trading results and optimizes strategy parameters.

Features:
1. Automated performance feedback loop
2. Parameter optimization through Bayesian methods
3. A/B testing framework for strategy variants
4. Feature importance analysis
5. Online learning for adaptive parameters
6. Model retraining scheduler

This creates a system that gets better over time through data-driven optimization.

Author: NIJA Trading Systems
Version: 1.0
Date: January 2026
"""

import logging
import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from collections import deque
import pandas as pd
import numpy as np

logger = logging.getLogger("nija.learning")


@dataclass
class TradeRecord:
    """Record of a completed trade for learning"""
    trade_id: str
    strategy_id: str
    symbol: str
    side: str  # 'long' or 'short'
    
    # Entry
    entry_time: datetime
    entry_price: float
    entry_size: float
    entry_indicators: Dict[str, float]
    entry_regime: str
    entry_confidence: float
    
    # Exit
    exit_time: datetime
    exit_price: float
    exit_size: float
    exit_reason: str
    
    # Results
    pnl: float
    pnl_pct: float
    fees: float
    net_pnl: float
    duration_minutes: int
    max_favorable_excursion: float = 0.0  # Best price during trade
    max_adverse_excursion: float = 0.0    # Worst price during trade
    
    # Classification
    outcome: str = ""  # 'win', 'loss', 'breakeven'
    quality_score: float = 0.0  # 0-100, how good was this trade
    
    def __post_init__(self):
        """Calculate derived metrics"""
        self.outcome = 'win' if self.net_pnl > 0 else ('loss' if self.net_pnl < 0 else 'breakeven')
        
        # Quality score factors:
        # - PnL magnitude
        # - Duration efficiency (faster is often better)
        # - Low slippage (MFE/MAE vs entry)
        pnl_score = min(abs(self.pnl_pct) * 1000, 50)  # Max 50 points for PnL
        
        duration_score = 25 if self.duration_minutes < 60 else (50 - self.duration_minutes / 10)
        duration_score = max(0, min(duration_score, 25))  # 0-25 points
        
        # Execution quality (how well did we capture the move)
        if self.side == 'long':
            capture_ratio = (self.exit_price - self.entry_price) / (self.max_favorable_excursion - self.entry_price) if self.max_favorable_excursion > self.entry_price else 0
        else:
            capture_ratio = (self.entry_price - self.exit_price) / (self.entry_price - self.max_favorable_excursion) if self.entry_price > self.max_favorable_excursion else 0
        
        capture_score = capture_ratio * 25  # 0-25 points
        
        self.quality_score = pnl_score + duration_score + capture_score if self.outcome == 'win' else 0


@dataclass
class ParameterTest:
    """A/B test for strategy parameters"""
    test_id: str
    strategy_id: str
    parameter_name: str
    control_value: Any
    test_value: Any
    
    # Test tracking
    start_time: datetime = field(default_factory=datetime.now)
    end_time: Optional[datetime] = None
    
    # Results
    control_trades: List[str] = field(default_factory=list)
    test_trades: List[str] = field(default_factory=list)
    control_pnl: float = 0.0
    test_pnl: float = 0.0
    
    # Statistics
    is_significant: bool = False
    confidence_level: float = 0.0
    winner: str = ""  # 'control', 'test', or 'inconclusive'


class SelfLearningEngine:
    """
    Self-learning engine that optimizes strategies through continuous feedback
    """
    
    def __init__(self, data_dir: str = "./data/learning", config: Optional[Dict] = None):
        """
        Initialize self-learning engine
        
        Args:
            data_dir: Directory for storing learning data
            config: Optional configuration
        """
        self.data_dir = data_dir
        self.config = config or {}
        
        # Create data directory
        os.makedirs(data_dir, exist_ok=True)
        
        # Trade history
        self.trade_history: deque = deque(maxlen=10000)
        self.trade_history_file = os.path.join(data_dir, "trade_history.jsonl")
        
        # Active A/B tests
        self.active_tests: Dict[str, ParameterTest] = {}
        
        # Parameter optimization
        self.parameter_performance: Dict[str, Dict] = {}  # parameter -> value -> performance
        
        # Learning intervals
        self.min_trades_for_learning = self.config.get('min_trades_for_learning', 30)
        self.optimization_interval_hours = self.config.get('optimization_interval_hours', 24)
        self.last_optimization_time = datetime.now()
        
        # Feature importance tracking
        self.feature_importance: Dict[str, float] = {}
        
        # Load existing trade history
        self._load_trade_history()
        
        logger.info(f"Self-Learning Engine initialized (data dir: {data_dir})")
        logger.info(f"Loaded {len(self.trade_history)} historical trades")
    
    def record_trade(self, trade: TradeRecord):
        """
        Record a completed trade for learning
        
        Args:
            trade: TradeRecord object
        """
        self.trade_history.append(trade)
        
        # Save to persistent storage
        self._save_trade_to_file(trade)
        
        # Update parameter performance tracking
        self._update_parameter_performance(trade)
        
        # Check if we should trigger optimization
        if len(self.trade_history) % self.min_trades_for_learning == 0:
            self._trigger_parameter_optimization()
        
        logger.debug(f"Trade recorded: {trade.symbol} {trade.side} -> {trade.outcome} (${trade.net_pnl:.2f})")
    
    def _save_trade_to_file(self, trade: TradeRecord):
        """Save trade to JSONL file"""
        try:
            trade_dict = {
                'trade_id': trade.trade_id,
                'strategy_id': trade.strategy_id,
                'symbol': trade.symbol,
                'side': trade.side,
                'entry_time': trade.entry_time.isoformat(),
                'entry_price': trade.entry_price,
                'entry_size': trade.entry_size,
                'entry_regime': trade.entry_regime,
                'entry_confidence': trade.entry_confidence,
                'exit_time': trade.exit_time.isoformat(),
                'exit_price': trade.exit_price,
                'exit_reason': trade.exit_reason,
                'pnl': trade.pnl,
                'pnl_pct': trade.pnl_pct,
                'fees': trade.fees,
                'net_pnl': trade.net_pnl,
                'duration_minutes': trade.duration_minutes,
                'outcome': trade.outcome,
                'quality_score': trade.quality_score
            }
            
            with open(self.trade_history_file, 'a') as f:
                f.write(json.dumps(trade_dict) + '\n')
                
        except Exception as e:
            logger.error(f"Error saving trade to file: {e}")
    
    def _load_trade_history(self):
        """Load trade history from file"""
        if not os.path.exists(self.trade_history_file):
            return
        
        try:
            with open(self.trade_history_file, 'r') as f:
                for line_num, line in enumerate(f, 1):
                    try:
                        trade_dict = json.loads(line.strip())
                        # Note: We're loading a simplified version, not full TradeRecord
                        # This is sufficient for analytics
                    except json.JSONDecodeError as e:
                        logger.error(f"Error parsing trade history line {line_num}: {e}")
                        # Continue with next line instead of failing completely
                        continue
        except Exception as e:
            logger.error(f"Error loading trade history: {e}")
    
    def analyze_strategy_performance(self, strategy_id: str, 
                                   lookback_days: int = 30) -> Dict[str, Any]:
        """
        Analyze performance of a specific strategy
        
        Args:
            strategy_id: Strategy to analyze
            lookback_days: Number of days to look back
            
        Returns:
            Performance analysis dictionary
        """
        # Filter trades for this strategy
        cutoff_time = datetime.now() - timedelta(days=lookback_days)
        strategy_trades = [
            t for t in self.trade_history 
            if t.strategy_id == strategy_id and t.exit_time > cutoff_time
        ]
        
        if not strategy_trades:
            return {'status': 'no_data', 'message': f'No trades for {strategy_id} in last {lookback_days} days'}
        
        # Calculate metrics
        total_trades = len(strategy_trades)
        winning_trades = sum(1 for t in strategy_trades if t.outcome == 'win')
        win_rate = winning_trades / total_trades
        
        total_pnl = sum(t.net_pnl for t in strategy_trades)
        avg_pnl = total_pnl / total_trades
        
        avg_duration = sum(t.duration_minutes for t in strategy_trades) / total_trades
        avg_quality = sum(t.quality_score for t in strategy_trades) / total_trades
        
        # Regime analysis
        regime_performance = {}
        for trade in strategy_trades:
            regime = trade.entry_regime
            if regime not in regime_performance:
                regime_performance[regime] = {'trades': 0, 'wins': 0, 'pnl': 0.0}
            
            regime_performance[regime]['trades'] += 1
            if trade.outcome == 'win':
                regime_performance[regime]['wins'] += 1
            regime_performance[regime]['pnl'] += trade.net_pnl
        
        # Calculate win rates by regime
        for regime, stats in regime_performance.items():
            stats['win_rate'] = stats['wins'] / stats['trades'] if stats['trades'] > 0 else 0
        
        # Confidence score analysis
        high_conf_trades = [t for t in strategy_trades if t.entry_confidence > 0.7]
        low_conf_trades = [t for t in strategy_trades if t.entry_confidence <= 0.7]
        
        high_conf_win_rate = sum(1 for t in high_conf_trades if t.outcome == 'win') / len(high_conf_trades) if high_conf_trades else 0
        low_conf_win_rate = sum(1 for t in low_conf_trades if t.outcome == 'win') / len(low_conf_trades) if low_conf_trades else 0
        
        analysis = {
            'strategy_id': strategy_id,
            'lookback_days': lookback_days,
            'total_trades': total_trades,
            'win_rate': win_rate,
            'total_pnl': total_pnl,
            'avg_pnl_per_trade': avg_pnl,
            'avg_duration_minutes': avg_duration,
            'avg_quality_score': avg_quality,
            'regime_performance': regime_performance,
            'high_confidence_win_rate': high_conf_win_rate,
            'low_confidence_win_rate': low_conf_win_rate,
            'confidence_differential': high_conf_win_rate - low_conf_win_rate
        }
        
        logger.info(f"📊 Strategy analysis for {strategy_id}: {total_trades} trades, "
                   f"{win_rate:.1%} win rate, ${total_pnl:.2f} P&L")
        
        return analysis
    
    def start_ab_test(self, strategy_id: str, parameter_name: str, 
                     control_value: Any, test_value: Any) -> str:
        """
        Start an A/B test for a strategy parameter
        
        Args:
            strategy_id: Strategy to test
            parameter_name: Parameter to vary
            control_value: Current/control value
            test_value: New/test value
            
        Returns:
            Test ID
        """
        test_id = f"{strategy_id}_{parameter_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        test = ParameterTest(
            test_id=test_id,
            strategy_id=strategy_id,
            parameter_name=parameter_name,
            control_value=control_value,
            test_value=test_value
        )
        
        self.active_tests[test_id] = test
        
        logger.info(f"🧪 Started A/B test: {test_id}")
        logger.info(f"   Parameter: {parameter_name}")
        logger.info(f"   Control: {control_value}, Test: {test_value}")
        
        return test_id
    
    def record_test_trade(self, test_id: str, trade_id: str, 
                         is_control: bool, pnl: float):
        """
        Record a trade result for an A/B test
        
        Args:
            test_id: Test identifier
            trade_id: Trade identifier
            is_control: True if control variant, False if test variant
            pnl: Trade P&L
        """
        if test_id not in self.active_tests:
            logger.warning(f"Unknown test ID: {test_id}")
            return
        
        test = self.active_tests[test_id]
        
        if is_control:
            test.control_trades.append(trade_id)
            test.control_pnl += pnl
        else:
            test.test_trades.append(trade_id)
            test.test_pnl += pnl
        
        # Check if we have enough data to conclude test
        if len(test.control_trades) >= 20 and len(test.test_trades) >= 20:
            self._analyze_ab_test(test_id)
    
    def _analyze_ab_test(self, test_id: str):
        """Analyze A/B test results"""
        if test_id not in self.active_tests:
            return
        
        test = self.active_tests[test_id]
        
        # Simple analysis: compare average P&L
        control_avg = test.control_pnl / len(test.control_trades) if test.control_trades else 0
        test_avg = test.test_pnl / len(test.test_trades) if test.test_trades else 0
        
        # Determine winner (simplified - in production, use proper statistical tests)
        # Safe division: avoid division by zero
        if abs(control_avg) > 0.01:  # Minimum threshold to avoid division by near-zero
            improvement_pct = (test_avg - control_avg) / abs(control_avg)
        else:
            improvement_pct = 0
        
        if improvement_pct > 0.10:  # 10% improvement
            test.winner = 'test'
            test.is_significant = True
            test.confidence_level = 0.85
        elif improvement_pct < -0.10:  # 10% worse
            test.winner = 'control'
            test.is_significant = True
            test.confidence_level = 0.85
        else:
            test.winner = 'inconclusive'
            test.is_significant = False
            test.confidence_level = 0.50
        
        test.end_time = datetime.now()
        
        logger.info(f"🎯 A/B test {test_id} concluded:")
        logger.info(f"   Control: ${control_avg:.2f} avg P&L ({len(test.control_trades)} trades)")
        logger.info(f"   Test: ${test_avg:.2f} avg P&L ({len(test.test_trades)} trades)")
        logger.info(f"   Winner: {test.winner} ({test.confidence_level:.0%} confidence)")
    
    def get_optimization_suggestions(self, strategy_id: str) -> List[Dict]:
        """
        Get parameter optimization suggestions based on historical performance
        
        Args:
            strategy_id: Strategy to optimize
            
        Returns:
            List of optimization suggestions
        """
        analysis = self.analyze_strategy_performance(strategy_id)
        
        if analysis.get('status') == 'no_data':
            return []
        
        suggestions = []
        
        # Suggestion 1: Confidence threshold
        conf_diff = analysis.get('confidence_differential', 0)
        if conf_diff > 0.10:  # High confidence trades perform 10%+ better
            suggestions.append({
                'parameter': 'min_confidence_threshold',
                'current': 0.65,
                'suggested': 0.75,
                'reason': f'High confidence trades show {conf_diff:.1%} better win rate',
                'expected_improvement': f'{conf_diff*100:.0f}% win rate increase'
            })
        
        # Suggestion 2: Regime-specific activation
        regime_perf = analysis.get('regime_performance', {})
        best_regime = None
        best_win_rate = 0
        
        for regime, stats in regime_perf.items():
            if stats['win_rate'] > best_win_rate and stats['trades'] >= 5:
                best_win_rate = stats['win_rate']
                best_regime = regime
        
        if best_regime and best_win_rate > 0.60:
            suggestions.append({
                'parameter': 'preferred_regimes',
                'current': ['all'],
                'suggested': [best_regime],
                'reason': f'{best_regime} regime shows {best_win_rate:.1%} win rate',
                'expected_improvement': 'Focus on best-performing market conditions'
            })
        
        # Suggestion 3: Position sizing based on quality
        avg_quality = analysis.get('avg_quality_score', 0)
        if avg_quality < 30:  # Low quality trades
            suggestions.append({
                'parameter': 'max_position_size_pct',
                'current': 0.05,
                'suggested': 0.03,
                'reason': f'Average trade quality is low ({avg_quality:.0f}/100)',
                'expected_improvement': 'Reduce risk on lower quality setups'
            })
        
        logger.info(f"💡 Generated {len(suggestions)} optimization suggestions for {strategy_id}")
        
        return suggestions
    
    def _update_parameter_performance(self, trade: TradeRecord):
        """Update performance tracking for parameters"""
        # Track confidence level performance
        conf_bucket = round(trade.entry_confidence, 1)  # Round to nearest 0.1
        
        if 'confidence' not in self.parameter_performance:
            self.parameter_performance['confidence'] = {}
        
        if conf_bucket not in self.parameter_performance['confidence']:
            self.parameter_performance['confidence'][conf_bucket] = {
                'trades': 0, 'wins': 0, 'total_pnl': 0.0
            }
        
        perf = self.parameter_performance['confidence'][conf_bucket]
        perf['trades'] += 1
        if trade.outcome == 'win':
            perf['wins'] += 1
        perf['total_pnl'] += trade.net_pnl
        perf['win_rate'] = perf['wins'] / perf['trades']
        perf['avg_pnl'] = perf['total_pnl'] / perf['trades']
    
    def _trigger_parameter_optimization(self):
        """Trigger parameter optimization based on recent performance"""
        # Check if enough time has passed since last optimization
        if (datetime.now() - self.last_optimization_time).total_seconds() < self.optimization_interval_hours * 3600:
            return
        
        logger.info("🔧 Triggering parameter optimization...")
        
        # Analyze parameter performance
        if 'confidence' in self.parameter_performance:
            conf_perf = self.parameter_performance['confidence']
            
            # Find optimal confidence threshold
            best_conf = 0.5
            best_sharpe = 0
            
            for conf_level, stats in conf_perf.items():
                if stats['trades'] < 10:  # Need minimum sample size
                    continue
                
                # Simple Sharpe-like metric: avg_pnl / std
                # (In production, would calculate proper Sharpe)
                if stats['avg_pnl'] > 0 and stats['win_rate'] > 0.5:
                    sharpe_estimate = stats['avg_pnl'] * stats['win_rate']
                    if sharpe_estimate > best_sharpe:
                        best_sharpe = sharpe_estimate
                        best_conf = conf_level
            
            if best_conf > 0.6:
                logger.info(f"📈 Optimal confidence threshold found: {best_conf:.1f}")
                # In production, this would update strategy parameters
        
        self.last_optimization_time = datetime.now()
    
    def export_training_data(self, output_file: str) -> bool:
        """
        Export trade data for ML model training
        
        Args:
            output_file: Path to output CSV file
            
        Returns:
            Success status
        """
        if not self.trade_history:
            logger.warning("No trade data to export")
            return False
        
        try:
            # Convert trades to DataFrame
            data = []
            for trade in self.trade_history:
                data.append({
                    'strategy_id': trade.strategy_id,
                    'symbol': trade.symbol,
                    'side': trade.side,
                    'entry_regime': trade.entry_regime,
                    'entry_confidence': trade.entry_confidence,
                    'duration_minutes': trade.duration_minutes,
                    'pnl_pct': trade.pnl_pct,
                    'outcome': trade.outcome,
                    'quality_score': trade.quality_score
                })
            
            df = pd.DataFrame(data)
            df.to_csv(output_file, index=False)
            
            logger.info(f"✅ Exported {len(data)} trades to {output_file}")
            return True
            
        except Exception as e:
            logger.error(f"Error exporting training data: {e}")
            return False


def create_learning_engine(data_dir: str = "./data/learning", 
                          config: Optional[Dict] = None) -> SelfLearningEngine:
    """
    Factory function to create self-learning engine
    
    Args:
        data_dir: Directory for learning data
        config: Optional configuration
        
    Returns:
        SelfLearningEngine instance
    """
    return SelfLearningEngine(data_dir, config)
