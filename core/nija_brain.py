"""
NIJA Brain - Integrated Intelligence System
===========================================

Central intelligence coordinator that integrates:
- Multi-Strategy Orchestration
- Execution Intelligence
- Self-Learning Engine
- Investor Metrics

This is the master "Brain" that runs the entire NIJA trading system.

Author: NIJA Trading Systems
Version: 1.0
Date: January 2026
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional, Any
import pandas as pd

logger = logging.getLogger("nija.brain")


class NIJABrain:
    """
    Integrated trading intelligence system

    Coordinates all AI components for optimal trading performance
    """

    def __init__(self, total_capital: float, config: Optional[Dict] = None):
        """
        Initialize NIJA Brain

        Args:
            total_capital: Total trading capital
            config: Optional configuration
        """
        self.total_capital = total_capital
        self.config = config or {}

        # Initialize components
        self.orchestrator = None
        self.execution_intelligence = None
        self.learning_engine = None
        self.metrics_engine = None
        self.auto_optimizer = None

        self._initialize_components()

        logger.info("🧠 NIJA Brain initialized - All systems operational")

    def _initialize_components(self):
        """Initialize all brain components"""
        try:
            from core.strategy_orchestrator import create_default_orchestrator
            self.orchestrator = create_default_orchestrator(self.total_capital)
            logger.info("✅ Strategy Orchestrator online")
        except Exception as e:
            logger.error(f"Failed to initialize orchestrator: {e}")

        try:
            from core.execution_intelligence import create_execution_intelligence
            self.execution_intelligence = create_execution_intelligence(self.config.get('execution'))
            logger.info("✅ Execution Intelligence online")
        except Exception as e:
            logger.error(f"Failed to initialize execution intelligence: {e}")

        try:
            from core.self_learning_engine import create_learning_engine
            self.learning_engine = create_learning_engine(
                data_dir=self.config.get('learning_data_dir', './data/learning'),
                config=self.config.get('learning')
            )
            logger.info("✅ Self-Learning Engine online")
        except Exception as e:
            logger.error(f"Failed to initialize learning engine: {e}")

        try:
            from core.investor_metrics import create_metrics_engine
            self.metrics_engine = create_metrics_engine(
                self.total_capital,
                config=self.config.get('metrics')
            )
            logger.info("✅ Investor Metrics Engine online")
        except Exception as e:
            logger.error(f"Failed to initialize metrics engine: {e}")

        try:
            from bot.auto_optimization_engine import get_auto_optimizer
            self.auto_optimizer = get_auto_optimizer(
                state_dir=self.config.get('optimization_state_dir', './data/optimization'),
                config=self.config.get('auto_optimization')
            )
            logger.info("✅ Auto-Optimization Engine online")
        except Exception as e:
            logger.error(f"Failed to initialize auto-optimization engine: {e}")

    def analyze_opportunity(self, symbol: str, df: pd.DataFrame,
                          indicators: Dict, broker_name: str = "coinbase") -> Dict[str, Any]:
        """
        Comprehensive opportunity analysis using all brain components

        Args:
            symbol: Trading symbol
            df: OHLCV DataFrame
            indicators: Technical indicators
            broker_name: Broker name

        Returns:
            Complete analysis with trading decision
        """
        analysis = {
            'symbol': symbol,
            'timestamp': datetime.now(),
            'decision': 'no_action',
            'confidence': 0.0,
            'components': {}
        }

        # 1. Get signals from strategy orchestrator
        if self.orchestrator:
            signals = self.orchestrator.get_trading_signals(symbol, df, indicators, broker_name)

            if signals:
                # Use ensemble voting
                consensus = self.orchestrator.execute_ensemble_vote(signals)

                if consensus:
                    analysis['decision'] = consensus.get('action', 'no_action')
                    analysis['confidence'] = consensus.get('confidence', 0)
                    analysis['components']['orchestrator'] = {
                        'signals_count': len(signals),
                        'consensus': consensus,
                        'agreeing_strategies': consensus.get('agreeing_strategies', [])
                    }
                else:
                    analysis['components']['orchestrator'] = {
                        'signals_count': len(signals),
                        'consensus': None,
                        'reason': 'Insufficient agreement among strategies'
                    }

        # 2. Get execution intelligence recommendation (if we have a position)
        # This would be called when evaluating exit opportunities
        analysis['components']['execution'] = {
            'status': 'ready',
            'slippage_stats': self.execution_intelligence.slippage_stats if self.execution_intelligence else {}
        }

        # 3. Learning engine insights
        if self.learning_engine and analysis['decision'] != 'no_action':
            # Get parameter suggestions
            suggestions = self.learning_engine.get_optimization_suggestions('apex_v72')
            analysis['components']['learning'] = {
                'optimization_suggestions': suggestions
            }

        logger.debug(f"Opportunity analysis for {symbol}: {analysis['decision']} ({analysis['confidence']:.0%} confidence)")

        return analysis

    def evaluate_exit(self, symbol: str, df: pd.DataFrame, indicators: Dict,
                     position: Dict) -> Dict[str, Any]:
        """
        Evaluate exit opportunity for existing position

        Args:
            symbol: Trading symbol
            df: OHLCV DataFrame
            indicators: Technical indicators
            position: Current position details

        Returns:
            Exit recommendation
        """
        exit_analysis = {
            'symbol': symbol,
            'timestamp': datetime.now(),
            'should_exit': False,
            'exit_pct': 0.0,
            'reason': ''
        }

        if not self.execution_intelligence:
            return exit_analysis

        # Get exit signal from execution intelligence
        exit_signal = self.execution_intelligence.calculate_exit_score(
            symbol, df, indicators, position
        )

        # Calculate optimal exit size
        exit_size, reason = self.execution_intelligence.calculate_optimal_exit_size(
            position, exit_signal, self.total_capital
        )

        position_size = position.get('size', 0)
        exit_pct = exit_size / position_size if position_size > 0 else 0

        exit_analysis.update({
            'should_exit': exit_size > 0,
            'exit_size': exit_size,
            'exit_pct': exit_pct,
            'reason': reason,
            'signal': {
                'type': exit_signal.signal_type,
                'confidence': exit_signal.confidence,
                'urgency': exit_signal.urgency,
                'score': exit_signal.exit_score
            }
        })

        logger.info(f"Exit evaluation for {symbol}: {'EXIT' if exit_analysis['should_exit'] else 'HOLD'} "
                   f"({exit_pct*100:.0f}% of position)")

        return exit_analysis

    def record_trade_completion(self, trade_data: Dict):
        """
        Record completed trade across all systems

        Args:
            trade_data: Complete trade information
        """
        # Record with auto-optimizer
        if self.auto_optimizer:
            try:
                self.auto_optimizer.record_trade_result(
                    strategy_name=trade_data.get('strategy_id', 'unknown'),
                    trade_result=trade_data
                )
            except Exception as e:
                logger.error(f"Error recording trade with auto-optimizer: {e}")

        # Record with learning engine
        if self.learning_engine:
            try:
                from core.self_learning_engine import TradeRecord

                trade_record = TradeRecord(
                    trade_id=trade_data['trade_id'],
                    strategy_id=trade_data.get('strategy_id', 'unknown'),
                    symbol=trade_data['symbol'],
                    side=trade_data['side'],
                    entry_time=trade_data['entry_time'],
                    entry_price=trade_data['entry_price'],
                    entry_size=trade_data['entry_size'],
                    entry_indicators=trade_data.get('entry_indicators', {}),
                    entry_regime=trade_data.get('entry_regime', 'unknown'),
                    entry_confidence=trade_data.get('entry_confidence', 0.5),
                    exit_time=trade_data['exit_time'],
                    exit_price=trade_data['exit_price'],
                    exit_size=trade_data['exit_size'],
                    exit_reason=trade_data.get('exit_reason', 'unknown'),
                    pnl=trade_data['pnl'],
                    pnl_pct=trade_data['pnl_pct'],
                    fees=trade_data.get('fees', 0),
                    net_pnl=trade_data['pnl'] - trade_data.get('fees', 0),
                    duration_minutes=int((trade_data['exit_time'] - trade_data['entry_time']).total_seconds() / 60),
                    max_favorable_excursion=trade_data.get('mfe', 0),
                    max_adverse_excursion=trade_data.get('mae', 0)
                )

                self.learning_engine.record_trade(trade_record)
            except Exception as e:
                logger.error(f"Error recording trade with learning engine: {e}")

        # Record with orchestrator
        if self.orchestrator:
            try:
                self.orchestrator.record_trade_result(
                    strategy_id=trade_data.get('strategy_id', 'unknown'),
                    pnl=trade_data['pnl'],
                    fees=trade_data.get('fees', 0),
                    regime=trade_data.get('entry_regime', 'unknown')
                )
            except Exception as e:
                logger.error(f"Error recording trade with orchestrator: {e}")

        # Update metrics engine
        if self.metrics_engine:
            try:
                # Calculate new equity
                new_equity = self.metrics_engine.current_capital + trade_data['pnl'] - trade_data.get('fees', 0)
                self.metrics_engine.update_equity(
                    new_equity,
                    strategy_id=trade_data.get('strategy_id')
                )
            except Exception as e:
                logger.error(f"Error updating metrics: {e}")

        logger.info(f"✅ Trade recorded: {trade_data['symbol']} {trade_data['side']} - "
                   f"P&L: ${trade_data['pnl']:.2f}")

    def get_performance_report(self) -> Dict[str, Any]:
        """
        Generate comprehensive performance report

        Returns:
            Complete performance report from all systems
        """
        report = {
            'timestamp': datetime.now(),
            'systems_status': {
                'orchestrator': self.orchestrator is not None,
                'execution_intelligence': self.execution_intelligence is not None,
                'learning_engine': self.learning_engine is not None,
                'metrics_engine': self.metrics_engine is not None,
                'auto_optimizer': self.auto_optimizer is not None
            }
        }

        # Orchestrator performance
        if self.orchestrator:
            report['strategy_performance'] = self.orchestrator.get_performance_summary()

        # Execution quality
        if self.execution_intelligence:
            report['execution_quality'] = self.execution_intelligence.get_execution_quality_report()

        # Learning insights
        if self.learning_engine:
            report['learning_insights'] = {
                'total_trades_analyzed': len(self.learning_engine.trade_history),
                'active_ab_tests': len(self.learning_engine.active_tests)
            }

        # Investor metrics
        if self.metrics_engine:
            report['investor_metrics'] = self.metrics_engine.generate_investor_report()

        # Auto-optimization status
        if self.auto_optimizer:
            report['auto_optimization'] = self.auto_optimizer.get_status()

        return report

    def perform_daily_review(self):
        """Perform daily system review and optimization"""
        logger.info("🔍 Performing daily system review...")

        # Review strategy performance
        if self.orchestrator:
            review_results = self.orchestrator.review_strategy_performance()
            logger.info(f"Strategy review: {len(review_results['actions_taken'])} actions taken")

        # Get learning insights
        if self.learning_engine:
            suggestions = self.learning_engine.get_optimization_suggestions('apex_v72')
            if suggestions:
                logger.info(f"💡 {len(suggestions)} optimization suggestions available")
                for sugg in suggestions:
                    logger.info(f"   - {sugg['parameter']}: {sugg['reason']}")

        # Check auto-optimization status
        if self.auto_optimizer:
            optimizer_status = self.auto_optimizer.get_status()
            logger.info(f"🤖 Auto-Optimizer: {optimizer_status['state']} - Score: {optimizer_status['current_performance_score']:.2f}")
            if optimizer_status.get('current_cycle'):
                logger.info(f"   Active optimization cycle: {optimizer_status['current_cycle']}")

        logger.info("✅ Daily review complete")


def create_nija_brain(total_capital: float, config: Optional[Dict] = None) -> NIJABrain:
    """
    Factory function to create NIJA Brain

    Args:
        total_capital: Total trading capital
        config: Optional configuration

    Returns:
        NIJABrain instance
    """
    return NIJABrain(total_capital, config)
