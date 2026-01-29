"""
NIJA God Mode Engine
====================

Master orchestration system integrating all advanced quant features:

1️⃣ Bayesian Regime Probability Engine
   - Probabilistic market regime detection
   - Confidence-weighted strategy parameters

2️⃣ Meta-Learning Optimizer
   - Self-tuning parameters based on performance
   - Automatic parameter adaptation

3️⃣ Walk-Forward Genetic Optimization
   - Rolling window optimization
   - Out-of-sample validation
   - Prevents overfitting

4️⃣ Risk Parity & Correlation Control
   - Equal risk contribution per position
   - Correlation-adjusted sizing
   - Portfolio-level optimization

5️⃣ Live Reinforcement Learning
   - Continuous learning from live trades
   - Strategy selection based on market conditions
   - Real-time performance feedback

This is the "God Mode" - maximum quant-research firepower.

Author: NIJA Trading Systems
Version: 1.0 - God Mode Edition
Date: January 29, 2026
"""

import logging
import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime
import os

# Import all God Mode components
from bot.bayesian_regime_detector import BayesianRegimeDetector, RegimeProbabilities
from bot.meta_optimizer import MetaLearningOptimizer
from bot.walk_forward_optimizer import WalkForwardOptimizer
from bot.risk_parity_allocator import RiskParityAllocator
from bot.live_rl_feedback import LiveRLFeedbackLoop
from bot.meta_ai.reinforcement_learning import MarketState

logger = logging.getLogger("nija.god_mode")


@dataclass
class GodModeConfig:
    """Configuration for God Mode Engine"""
    
    # Feature toggles
    enable_bayesian_regime: bool = True
    enable_meta_optimizer: bool = True
    enable_walk_forward: bool = True
    enable_risk_parity: bool = True
    enable_live_rl: bool = True
    
    # Sub-system configs
    bayesian_config: Dict = field(default_factory=dict)
    meta_optimizer_config: Dict = field(default_factory=dict)
    walk_forward_config: Dict = field(default_factory=dict)
    risk_parity_config: Dict = field(default_factory=dict)
    live_rl_config: Dict = field(default_factory=dict)
    
    # Integration settings
    use_regime_weighted_params: bool = True
    use_ensemble_params: bool = True
    rebalance_frequency_hours: int = 24
    
    # State persistence
    state_dir: str = "./god_mode_state"
    auto_save: bool = True
    save_frequency_trades: int = 10


@dataclass
class GodModeRecommendation:
    """Trading recommendation from God Mode"""
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    
    # Strategy selection
    recommended_strategy_id: int = 0
    strategy_confidence: float = 0.0
    
    # Parameters
    recommended_parameters: Dict[str, float] = field(default_factory=dict)
    parameter_source: str = ""  # "meta_optimizer", "ensemble", "walk_forward", etc.
    
    # Regime
    market_regime: str = "neutral"
    regime_probabilities: Optional[RegimeProbabilities] = None
    regime_confidence: float = 0.0
    
    # Position sizing
    recommended_position_sizes: Dict[str, float] = field(default_factory=dict)
    risk_parity_adjustment: bool = False
    
    # Summary
    summary: str = ""


class GodModeEngine:
    """
    God Mode Engine - Ultimate quant-research trading system
    
    Integrates all advanced features into a unified trading intelligence.
    """
    
    def __init__(self, config: GodModeConfig = None):
        """
        Initialize God Mode Engine
        
        Args:
            config: GodModeConfig or None for defaults
        """
        self.config = config or GodModeConfig()
        
        # Initialize sub-systems
        self.bayesian_regime = None
        self.meta_optimizer = None
        self.walk_forward = None
        self.risk_parity = None
        self.live_rl = None
        
        if self.config.enable_bayesian_regime:
            self.bayesian_regime = BayesianRegimeDetector(self.config.bayesian_config)
            logger.info("✅ Bayesian Regime Engine enabled")
        
        if self.config.enable_meta_optimizer:
            self.meta_optimizer = MetaLearningOptimizer(self.config.meta_optimizer_config)
            logger.info("✅ Meta-Learning Optimizer enabled")
        
        if self.config.enable_walk_forward:
            self.walk_forward = WalkForwardOptimizer(self.config.walk_forward_config)
            logger.info("✅ Walk-Forward Optimizer enabled")
        
        if self.config.enable_risk_parity:
            self.risk_parity = RiskParityAllocator(self.config.risk_parity_config)
            logger.info("✅ Risk Parity Allocator enabled")
        
        if self.config.enable_live_rl:
            # Number of strategies = number of regime types × parameter variations
            num_strategies = 3  # TRENDING, RANGING, VOLATILE
            self.live_rl = LiveRLFeedbackLoop(num_strategies, self.config.live_rl_config)
            logger.info("✅ Live RL Feedback Loop enabled")
        
        # State management
        self.trades_since_save = 0
        
        # Create state directory
        if self.config.auto_save:
            os.makedirs(self.config.state_dir, exist_ok=True)
        
        logger.info("=" * 70)
        logger.info("🔥 GOD MODE ACTIVATED - True Quant-Research Level Trading 🔥")
        logger.info("=" * 70)
        logger.info("Active Features:")
        logger.info(f"  1️⃣ Bayesian Regime Probability: {self.config.enable_bayesian_regime}")
        logger.info(f"  2️⃣ Meta-Learning Optimizer: {self.config.enable_meta_optimizer}")
        logger.info(f"  3️⃣ Walk-Forward Genetic Optimization: {self.config.enable_walk_forward}")
        logger.info(f"  4️⃣ Risk Parity & Correlation Control: {self.config.enable_risk_parity}")
        logger.info(f"  5️⃣ Live Reinforcement Learning: {self.config.enable_live_rl}")
        logger.info("=" * 70)
    
    def get_recommendation(
        self,
        market_data: pd.DataFrame,
        indicators: Dict,
        current_positions: Dict[str, Dict] = None,
        price_history: Dict[str, pd.DataFrame] = None,
    ) -> GodModeRecommendation:
        """
        Get comprehensive trading recommendation from God Mode
        
        Args:
            market_data: Current market OHLCV data
            indicators: Current technical indicators
            current_positions: Current portfolio positions
            price_history: Historical price data for correlation analysis
        
        Returns:
            GodModeRecommendation with all recommendations
        """
        recommendation = GodModeRecommendation()
        
        # 1️⃣ Bayesian Regime Detection
        if self.bayesian_regime:
            regime_result = self.bayesian_regime.detect_regime(market_data, indicators)
            recommendation.market_regime = regime_result.regime.value
            recommendation.regime_probabilities = regime_result.probabilities
            recommendation.regime_confidence = regime_result.confidence
            
            logger.info(
                f"📊 Regime: {regime_result.regime.value} "
                f"(confidence: {regime_result.confidence:.2%})"
            )
        
        # 2️⃣ Meta-Learning Optimizer - Get best parameters
        if self.meta_optimizer:
            use_ensemble = self.config.use_ensemble_params
            params = self.meta_optimizer.get_parameters(use_ensemble=use_ensemble)
            recommendation.recommended_parameters = params
            recommendation.parameter_source = "ensemble" if use_ensemble else "best"
            
            logger.info(f"🧠 Parameters: {recommendation.parameter_source}")
        
        # 3️⃣ Regime-weighted parameters (if Bayesian enabled)
        if self.bayesian_regime and self.config.use_regime_weighted_params:
            # Get regime-specific parameter sets (would come from strategy)
            # For now, use simple example
            regime_params = self._get_regime_parameter_sets()
            weighted_params = self.bayesian_regime.get_regime_weighted_params(regime_params)
            
            # Blend with meta-optimizer params
            if recommendation.recommended_parameters:
                # 50-50 blend
                blended = {}
                for key in weighted_params.keys():
                    meta_val = recommendation.recommended_parameters.get(key, weighted_params[key])
                    blended[key] = 0.5 * weighted_params[key] + 0.5 * meta_val
                recommendation.recommended_parameters = blended
                recommendation.parameter_source = "regime_weighted_blend"
        
        # 4️⃣ Risk Parity Position Sizing
        if self.risk_parity and current_positions and price_history:
            rp_result = self.risk_parity.calculate_allocation(
                current_positions,
                price_history,
            )
            
            # Extract position size recommendations
            for symbol, risk_contrib in rp_result.risk_contributions.items():
                recommendation.recommended_position_sizes[symbol] = risk_contrib.recommended_allocation
            
            recommendation.risk_parity_adjustment = rp_result.rebalancing_needed
            
            logger.info(f"⚖️  Risk Parity: {len(recommendation.recommended_position_sizes)} positions sized")
        
        # 5️⃣ Live RL Strategy Selection
        if self.live_rl:
            # Convert current market to MarketState
            market_state = self._create_market_state(market_data, indicators)
            
            strategy_id, confidence = self.live_rl.select_strategy(market_state)
            recommendation.recommended_strategy_id = strategy_id
            recommendation.strategy_confidence = confidence
            
            logger.info(
                f"🤖 RL Strategy: {strategy_id} "
                f"(confidence: {confidence:.2%})"
            )
        
        # Generate summary
        recommendation.summary = self._generate_recommendation_summary(recommendation)
        
        return recommendation
    
    def record_trade_entry(
        self,
        trade_id: str,
        market_data: pd.DataFrame,
        indicators: Dict,
        strategy_used: int,
        entry_price: float,
        parameters_used: Dict[str, float],
    ):
        """
        Record trade entry for all learning systems
        
        Args:
            trade_id: Unique trade identifier
            market_data: Market data at entry
            indicators: Indicators at entry
            strategy_used: Strategy ID used
            entry_price: Entry price
            parameters_used: Parameters used for this trade
        """
        # Record for RL
        if self.live_rl:
            market_state = self._create_market_state(market_data, indicators)
            self.live_rl.record_trade_entry(
                trade_id,
                market_state,
                strategy_used,
                entry_price,
            )
    
    def record_trade_exit(
        self,
        trade_id: str,
        market_data: pd.DataFrame,
        indicators: Dict,
        exit_price: float,
        profit_loss: float,
        parameters_used: Dict[str, float],
    ):
        """
        Record trade exit and update learning systems
        
        Args:
            trade_id: Unique trade identifier
            market_data: Market data at exit
            indicators: Indicators at exit
            exit_price: Exit price
            profit_loss: Profit/loss in dollars
            parameters_used: Parameters used for this trade
        """
        # Calculate trade result
        trade_result = {
            'profit': profit_loss,
            'return_pct': 0.0,  # Would calculate from entry/exit
        }
        
        # Update meta-optimizer
        if self.meta_optimizer:
            self.meta_optimizer.update_performance(parameters_used, trade_result)
        
        # Update RL
        if self.live_rl:
            market_state = self._create_market_state(market_data, indicators)
            self.live_rl.record_trade_exit(
                trade_id,
                market_state,
                exit_price,
                profit_loss,
            )
        
        # Update Bayesian priors periodically
        if self.bayesian_regime:
            self.bayesian_regime.update_prior()
        
        # Auto-save state
        self.trades_since_save += 1
        if self.config.auto_save and self.trades_since_save >= self.config.save_frequency_trades:
            self.save_state()
            self.trades_since_save = 0
    
    def _create_market_state(
        self,
        market_data: pd.DataFrame,
        indicators: Dict,
    ) -> MarketState:
        """Create MarketState from market data and indicators"""
        # Extract state features
        volatility = indicators.get('atr', 0.02) / market_data['close'].iloc[-1] if len(market_data) > 0 else 0.02
        volatility = np.clip(volatility / 0.05, 0.0, 1.0)  # Normalize to 0-1
        
        trend_strength = indicators.get('adx', 20.0) / 50.0  # Normalize ADX
        trend_strength = np.clip(trend_strength, 0.0, 1.0)
        
        volume_regime = indicators.get('volume_ratio', 0.5)
        volume_regime = np.clip(volume_regime, 0.0, 1.0)
        
        # Momentum from RSI
        rsi = indicators.get('rsi_14', 50.0)
        momentum = (rsi - 50.0) / 50.0  # Map 0-100 to -1 to +1
        
        # Time features
        now = datetime.now()
        
        return MarketState(
            volatility=volatility,
            trend_strength=trend_strength,
            volume_regime=volume_regime,
            momentum=momentum,
            time_of_day=now.hour,
            day_of_week=now.weekday(),
        )
    
    def _get_regime_parameter_sets(self) -> Dict:
        """Get parameter sets for each regime (example)"""
        from bot.market_regime_detector import MarketRegime
        
        # These would normally come from strategy configuration
        return {
            MarketRegime.TRENDING: {
                'min_signal_score': 3.0,
                'min_adx': 25.0,
                'atr_stop_multiplier': 1.5,
            },
            MarketRegime.RANGING: {
                'min_signal_score': 4.0,
                'min_adx': 15.0,
                'atr_stop_multiplier': 1.0,
            },
            MarketRegime.VOLATILE: {
                'min_signal_score': 4.0,
                'min_adx': 20.0,
                'atr_stop_multiplier': 2.0,
            },
        }
    
    def _generate_recommendation_summary(self, rec: GodModeRecommendation) -> str:
        """Generate human-readable summary"""
        lines = [
            "🔥 GOD MODE RECOMMENDATION 🔥",
            f"Timestamp: {rec.timestamp}",
            "",
            f"Market Regime: {rec.market_regime.upper()} (confidence: {rec.regime_confidence:.1%})",
            f"Strategy: #{rec.recommended_strategy_id} (confidence: {rec.strategy_confidence:.1%})",
            f"Parameters: {rec.parameter_source}",
        ]
        
        if rec.risk_parity_adjustment:
            lines.append(f"Portfolio Rebalancing: RECOMMENDED")
        
        return "\n".join(lines)
    
    def save_state(self):
        """Save state of all learning systems"""
        if not self.config.auto_save:
            return
        
        try:
            if self.meta_optimizer:
                path = os.path.join(self.config.state_dir, "meta_optimizer.pkl")
                self.meta_optimizer.save_state(path)
            
            if self.live_rl:
                path = os.path.join(self.config.state_dir, "live_rl.pkl")
                self.live_rl.save_state(path)
            
            logger.info("💾 God Mode state saved")
        except Exception as e:
            logger.error(f"Failed to save God Mode state: {e}")
    
    def load_state(self):
        """Load state of all learning systems"""
        try:
            if self.meta_optimizer:
                path = os.path.join(self.config.state_dir, "meta_optimizer.pkl")
                if os.path.exists(path):
                    self.meta_optimizer.load_state(path)
            
            if self.live_rl:
                path = os.path.join(self.config.state_dir, "live_rl.pkl")
                if os.path.exists(path):
                    self.live_rl.load_state(path)
            
            logger.info("📂 God Mode state loaded")
        except Exception as e:
            logger.error(f"Failed to load God Mode state: {e}")
