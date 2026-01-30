"""
Example: NAMIE Integration with APEX v7.1 Strategy

This example shows how to integrate NAMIE with the existing APEX v7.1 strategy
for maximum performance improvement.

Author: NIJA Trading Systems
Date: January 30, 2026
"""

import logging
from typing import Dict, Optional

try:
    from bot.nija_apex_strategy_v71 import NIJAApexStrategyV71
    from bot.namie_integration import NAMIEIntegration
except ImportError:
    # Try alternate import paths
    try:
        from nija_apex_strategy_v71 import NIJAApexStrategyV71
        from namie_integration import NAMIEIntegration
    except ImportError:
        print("⚠️  Could not import APEX or NAMIE modules")
        print("This is a reference example. Adjust imports based on your setup.")
        exit(1)

logger = logging.getLogger("nija.apex_namie")


class ApexWithNAMIE(NIJAApexStrategyV71):
    """
    APEX v7.1 Strategy Enhanced with NAMIE Intelligence
    
    Combines APEX's proven dual-RSI strategy with NAMIE's adaptive
    market intelligence for superior performance.
    
    Improvements:
    - Better regime detection
    - Chop filtering
    - Adaptive position sizing
    - Dynamic RSI ranges
    - Auto strategy switching
    """
    
    def __init__(self, broker_client=None, config: Optional[Dict] = None):
        """
        Initialize APEX + NAMIE strategy
        
        Args:
            broker_client: Broker API client
            config: Strategy configuration
        """
        # Initialize base APEX strategy
        super().__init__(broker_client, config)
        
        # Initialize NAMIE
        namie_config = config.get('namie_config', {}) if config else {}
        self.namie = NAMIEIntegration(config=namie_config)
        
        # NAMIE integration settings
        self.use_namie_regime_detection = config.get('use_namie_regime_detection', True) if config else True
        self.use_namie_position_sizing = config.get('use_namie_position_sizing', True) if config else True
        self.use_namie_chop_filter = config.get('use_namie_chop_filter', True) if config else True
        self.use_adaptive_rsi_ranges = config.get('use_adaptive_rsi_ranges', True) if config else True
        
        logger.info("🧠 APEX + NAMIE Strategy initialized")
        logger.info(f"   Regime Detection: {'✅' if self.use_namie_regime_detection else '❌'}")
        logger.info(f"   Position Sizing: {'✅' if self.use_namie_position_sizing else '❌'}")
        logger.info(f"   Chop Filter: {'✅' if self.use_namie_chop_filter else '❌'}")
        logger.info(f"   Adaptive RSI: {'✅' if self.use_adaptive_rsi_ranges else '❌'}")
    
    def analyze_market(self, df, symbol, account_balance):
        """
        Enhanced market analysis with NAMIE intelligence
        
        Args:
            df: Price DataFrame
            symbol: Trading symbol
            account_balance: Current account balance
        
        Returns:
            Analysis dictionary with NAMIE enhancements
        """
        # Get base APEX analysis
        analysis = super().analyze_market(df, symbol, account_balance)
        
        # If APEX says hold, skip NAMIE (no need to analyze)
        if analysis['action'] == 'hold':
            return analysis
        
        # Calculate indicators for NAMIE
        indicators = self._get_indicators_from_analysis(df)
        
        # Get NAMIE intelligence
        namie_signal = self.namie.analyze(df, indicators, symbol)
        
        # Add NAMIE metrics to analysis
        analysis['namie'] = {
            'regime': namie_signal.regime.value,
            'regime_confidence': namie_signal.regime_confidence,
            'trend_strength': namie_signal.trend_strength,
            'chop_score': namie_signal.chop_score,
            'optimal_strategy': namie_signal.optimal_strategy.value,
            'should_trade': namie_signal.should_trade,
            'reason': namie_signal.trade_reason,
        }
        
        # Apply NAMIE filters and enhancements
        if analysis['action'] != 'hold':
            # 1. NAMIE Regime Detection and Chop Filter
            if self.use_namie_chop_filter and not namie_signal.should_trade:
                logger.info(f"🧠 NAMIE blocked {symbol}: {namie_signal.trade_reason}")
                analysis['action'] = 'hold'
                analysis['reason'] = f"NAMIE: {namie_signal.trade_reason}"
                return analysis
            
            # 2. Check entry score meets NAMIE threshold
            entry_score = analysis.get('entry_score', 3)
            if entry_score < namie_signal.min_entry_score_required:
                logger.info(
                    f"🧠 NAMIE raised entry bar for {symbol}: "
                    f"{entry_score} < {namie_signal.min_entry_score_required} required"
                )
                analysis['action'] = 'hold'
                analysis['reason'] = f"NAMIE: Entry score too low ({entry_score}/{namie_signal.min_entry_score_required})"
                return analysis
            
            # 3. NAMIE Position Sizing Adjustment
            if self.use_namie_position_sizing:
                original_size = analysis['position_size']
                adjusted_size = self.namie.adjust_position_size(namie_signal, original_size)
                analysis['position_size'] = adjusted_size
                analysis['namie_size_multiplier'] = namie_signal.position_size_multiplier
                
                logger.debug(
                    f"🧠 NAMIE adjusted position for {symbol}: "
                    f"${original_size:.2f} → ${adjusted_size:.2f} "
                    f"({namie_signal.position_size_multiplier:.2f}x)"
                )
            
            # 4. Adaptive RSI Ranges (for future entries)
            if self.use_adaptive_rsi_ranges:
                rsi_ranges = self.namie.get_adaptive_rsi_ranges(namie_signal)
                analysis['adaptive_rsi_ranges'] = rsi_ranges
                
                logger.debug(
                    f"🧠 NAMIE RSI ranges for {symbol} ({namie_signal.regime.value}): "
                    f"Long [{rsi_ranges['long_min']:.0f}-{rsi_ranges['long_max']:.0f}], "
                    f"Short [{rsi_ranges['short_min']:.0f}-{rsi_ranges['short_max']:.0f}]"
                )
        
        return analysis
    
    def _get_indicators_from_analysis(self, df):
        """
        Extract indicators from DataFrame for NAMIE analysis
        
        This is a helper to get indicators without recalculating everything.
        In a real implementation, you'd share the indicator calculation.
        """
        try:
            # Try to get indicators from the strategy's calculations
            # This assumes indicators are already calculated in analyze_market
            from bot.indicators import (
                calculate_vwap, calculate_ema, calculate_rsi,
                calculate_macd, calculate_atr, calculate_adx
            )
            
            indicators = {
                'vwap': calculate_vwap(df),
                'ema9': calculate_ema(df, 9),
                'ema21': calculate_ema(df, 21),
                'ema50': calculate_ema(df, 50),
                'rsi': calculate_rsi(df, 14),
                'rsi_9': calculate_rsi(df, 9),
                'atr': calculate_atr(df, 14),
                'adx': calculate_adx(df, 14),
            }
            
            macd_data = calculate_macd(df)
            indicators['macd_line'] = macd_data['macd_line']
            indicators['macd_signal'] = macd_data['macd_signal']
            indicators['macd_histogram'] = macd_data['macd_histogram']
            
            return indicators
        except Exception as e:
            logger.warning(f"Could not calculate indicators: {e}")
            # Return empty dict - NAMIE will handle gracefully
            return {}
    
    def record_trade_exit(self, symbol, entry_price, exit_price, side, size_usd, commission=0.0):
        """
        Record trade exit for NAMIE learning
        
        Call this when closing a position to help NAMIE learn which
        regimes and strategies work best.
        
        Args:
            symbol: Trading symbol
            entry_price: Entry price
            exit_price: Exit price
            side: 'long' or 'short'
            size_usd: Position size in USD
            commission: Trading fees paid
        """
        # Get the NAMIE signal that was used for this trade
        # In practice, you'd store this when entering the trade
        # For now, we'll just record the result
        
        # Note: In a production implementation, you'd want to:
        # 1. Store the NAMIE signal when entering the trade
        # 2. Retrieve it here when recording the exit
        # 3. Pass the stored signal to record_trade_result
        
        logger.info(
            f"📊 Recording trade exit for {symbol}: "
            f"{side} ${size_usd:.2f} @ {entry_price:.4f} → {exit_price:.4f}"
        )
        
        # For now, just log that the trade was recorded
        # In production, integrate with position tracking
    
    def get_namie_performance(self):
        """
        Get NAMIE performance summary
        
        Returns:
            Dictionary with NAMIE performance metrics
        """
        return self.namie.get_performance_summary()


# Example usage
if __name__ == "__main__":
    print("\n" + "="*60)
    print("APEX + NAMIE Integration Example")
    print("="*60 + "\n")
    
    # Configuration
    config = {
        # APEX configuration
        'min_adx': 20,
        'volume_threshold': 0.5,
        
        # NAMIE configuration
        'use_namie_regime_detection': True,
        'use_namie_position_sizing': True,
        'use_namie_chop_filter': True,
        'use_adaptive_rsi_ranges': True,
        
        'namie_config': {
            'min_regime_confidence': 0.6,
            'min_trend_strength': 40,
            'max_chop_score': 60,
        }
    }
    
    # Initialize strategy
    strategy = ApexWithNAMIE(broker_client=None, config=config)
    
    print("✅ APEX + NAMIE strategy initialized")
    print("\nConfiguration:")
    print(f"  NAMIE Regime Detection: Enabled")
    print(f"  NAMIE Position Sizing: Enabled")
    print(f"  NAMIE Chop Filter: Enabled")
    print(f"  Adaptive RSI Ranges: Enabled")
    print("\nNAMIE Thresholds:")
    print(f"  Min Regime Confidence: 60%")
    print(f"  Min Trend Strength: 40/100")
    print(f"  Max Chop Score: 60/100")
    print("\nStrategy is ready to trade with NAMIE intelligence! 🚀")
    print("\nNext steps:")
    print("1. Connect to broker: strategy.broker_client = your_broker")
    print("2. Start trading loop")
    print("3. Call strategy.analyze_market(df, symbol, balance)")
    print("4. Execute trades based on analysis")
    print("5. Record exits with strategy.record_trade_exit()")
    print()
