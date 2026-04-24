"""
APEX Strategy with Crash-Resilient Infrastructure
==================================================

Example integration of NIJA APEX v7.2 strategy with crash-resilient
institutional infrastructure for maximum safety and performance.

This demonstrates how to:
1. Initialize crash-resilient trader
2. Validate trades through institutional checks
3. Adjust position sizes based on regime and liquidity
4. Handle emergency conditions
5. Monitor infrastructure health

Author: NIJA Trading Systems
Date: February 16, 2026
"""

import logging
import pandas as pd
from typing import Dict, Optional, Tuple
from datetime import datetime

logger = logging.getLogger("nija.apex_crash_resilient")


class ApexCrashResilientStrategy:
    """
    APEX v7.2 strategy enhanced with crash-resilient infrastructure
    
    This class wraps the standard APEX strategy and adds institutional-grade
    safety checks and adaptive parameters.
    """
    
    def __init__(self, broker_client=None, config: Optional[Dict] = None):
        """
        Initialize crash-resilient APEX strategy
        
        Args:
            broker_client: Broker client for trade execution
            config: Optional configuration dictionary
        """
        self.broker_client = broker_client
        self.config = config or {}
        
        # Initialize APEX strategy
        try:
            from nija_apex_strategy_v72_upgrade import NIJAApexStrategyV72
            self.apex_strategy = NIJAApexStrategyV72(broker_client, config)
            logger.info("✅ APEX v7.2 strategy loaded")
        except ImportError:
            try:
                from bot.nija_apex_strategy_v72_upgrade import NIJAApexStrategyV72
                self.apex_strategy = NIJAApexStrategyV72(broker_client, config)
                logger.info("✅ APEX v7.2 strategy loaded")
            except ImportError:
                self.apex_strategy = None
                logger.warning("⚠️ APEX v7.2 not available - using basic logic")
        
        # Initialize crash-resilient trader
        try:
            from crash_resilient_trading_integration import get_crash_resilient_trader
            self.resilient_trader = get_crash_resilient_trader(broker_client, config)
            self.crash_resilience_enabled = True
            logger.info("✅ Crash-resilient infrastructure enabled")
        except ImportError:
            try:
                from bot.crash_resilient_trading_integration import get_crash_resilient_trader
                self.resilient_trader = get_crash_resilient_trader(broker_client, config)
                self.crash_resilience_enabled = True
                logger.info("✅ Crash-resilient infrastructure enabled")
            except ImportError:
                self.resilient_trader = None
                self.crash_resilience_enabled = False
                logger.warning("⚠️ Crash-resilient infrastructure not available")
        
        # Track performance
        self.trades_validated = 0
        self.trades_approved = 0
        self.trades_blocked = 0
        self.last_crash_check = None
        
        logger.info("🎯 APEX Crash-Resilient Strategy initialized")
        logger.info(f"   APEX Strategy: {'✅' if self.apex_strategy else '❌'}")
        logger.info(f"   Crash Resilience: {'✅' if self.crash_resilience_enabled else '❌'}")
    
    def check_long_entry(
        self,
        symbol: str,
        df: pd.DataFrame,
        indicators: Dict,
        portfolio_state: Dict
    ) -> Tuple[bool, int, str, Dict]:
        """
        Check long entry with institutional validation
        
        Args:
            symbol: Trading symbol
            df: Price DataFrame
            indicators: Technical indicators
            portfolio_state: Current portfolio state
            
        Returns:
            Tuple of (can_enter, score, reason, adjusted_params)
        """
        # Step 1: Run APEX entry logic
        if self.apex_strategy:
            # Update regime for adaptive RSI
            self.apex_strategy.update_regime(df, indicators)
            
            # Check APEX entry conditions
            can_enter_apex, score, reason_apex = self.apex_strategy.check_long_entry_v72(
                df, indicators
            )
            
            if not can_enter_apex:
                logger.debug(f"APEX entry blocked: {reason_apex} (score: {score})")
                return False, score, reason_apex, {}
        else:
            # Fallback to basic check
            can_enter_apex = True
            score = 3
            reason_apex = "APEX not available - using basic check"
        
        # Step 2: Calculate position value
        account_balance = portfolio_state.get('account_balance', 0)
        base_position_pct = 0.03  # 3% default
        base_position_value = account_balance * base_position_pct
        
        # Step 3: Validate through crash-resilient infrastructure
        if self.crash_resilience_enabled and self.resilient_trader:
            self.trades_validated += 1
            
            # Get market data from DataFrame
            market_data = {
                'close': df['close'].iloc[-1],
                'volume': df.get('volume', pd.Series([0])).iloc[-1],
                'bid': df['close'].iloc[-1] * 0.9999,  # Estimate
                'ask': df['close'].iloc[-1] * 1.0001,  # Estimate
                'avg_volume': df.get('volume', pd.Series([0])).mean(),
            }
            
            # Validate trade
            validation = self.resilient_trader.validate_trade(
                symbol=symbol,
                side='buy',
                position_value=base_position_value,
                market_data=market_data,
                indicators=indicators,
                portfolio_state=portfolio_state
            )
            
            if not validation.approved:
                self.trades_blocked += 1
                logger.info(f"❌ Trade blocked by infrastructure: {validation.reason}")
                return False, score, validation.reason, {}
            
            self.trades_approved += 1
            
            # Step 4: Adjust position size
            adjusted_value = self.resilient_trader.adjust_position_size(
                base_position_value, validation
            )
            
            # Step 5: Get regime-adjusted entry score requirement
            min_score = self.resilient_trader.get_regime_adjusted_entry_score(
                self.apex_strategy.min_signal_score if self.apex_strategy else 3,
                validation
            )
            
            # Step 6: Check if score meets regime requirement
            if score < min_score:
                logger.info(f"Score {score} below regime minimum {min_score} (regime: {validation.regime})")
                return False, score, f"Score below {min_score} for {validation.regime} regime", {}
            
            # Build adjusted parameters
            adjusted_params = {
                'position_value': adjusted_value,
                'regime': validation.regime,
                'liquidity_score': validation.liquidity_score,
                'min_entry_score': min_score,
                'warnings': validation.warnings,
            }
            
            # Add regime-specific parameters
            if validation.adjusted_params:
                adjusted_params.update(validation.adjusted_params)
            
            logger.info(f"✅ Trade approved: {symbol} LONG")
            logger.info(f"   Regime: {validation.regime}")
            logger.info(f"   Position: ${adjusted_value:.2f} (from ${base_position_value:.2f})")
            logger.info(f"   Entry Score: {score}/{min_score}")
            
            return True, score, "Approved by crash-resilient infrastructure", adjusted_params
        
        else:
            # No crash resilience - approve with base parameters
            logger.warning("⚠️ Trading without crash-resilient infrastructure")
            return True, score, reason_apex, {'position_value': base_position_value}
    
    def check_short_entry(
        self,
        symbol: str,
        df: pd.DataFrame,
        indicators: Dict,
        portfolio_state: Dict
    ) -> Tuple[bool, int, str, Dict]:
        """
        Check short entry with institutional validation
        
        Similar to check_long_entry but for short positions.
        """
        # Similar logic as check_long_entry
        # Implementation simplified for example
        logger.info("Short entry check - similar to long entry logic")
        return False, 0, "Short entries not implemented in example", {}
    
    def run_periodic_checks(self, portfolio_state: Dict):
        """
        Run periodic infrastructure health checks
        
        Args:
            portfolio_state: Current portfolio state
        """
        if not self.crash_resilience_enabled or not self.resilient_trader:
            return
        
        # Check if crash validation needed
        if self.resilient_trader.should_run_crash_validation():
            logger.info("🔍 Running periodic crash validation...")
            
            passed, results = self.resilient_trader.run_crash_validation(
                portfolio_state=portfolio_state,
                stress_level='moderate'
            )
            
            if passed:
                logger.info("✅ Crash validation PASSED")
            else:
                logger.warning("⚠️ Crash validation FAILED - consider reducing exposure")
                logger.warning(f"   Max simulated drawdown: {results.get('max_drawdown', 0):.1f}%")
            
            self.last_crash_check = datetime.now()
    
    def get_infrastructure_status(self) -> Dict:
        """Get infrastructure health status"""
        if not self.crash_resilience_enabled or not self.resilient_trader:
            return {
                'enabled': False,
                'status': 'unavailable'
            }
        
        status = self.resilient_trader.get_infrastructure_status()
        
        # Add strategy-specific stats
        status['strategy_stats'] = {
            'trades_validated': self.trades_validated,
            'trades_approved': self.trades_approved,
            'trades_blocked': self.trades_blocked,
            'approval_rate': (
                (self.trades_approved / self.trades_validated * 100)
                if self.trades_validated > 0 else 0.0
            ),
            'last_crash_check': (
                self.last_crash_check.isoformat()
                if self.last_crash_check else None
            ),
        }
        
        return status
    
    def print_status_summary(self):
        """Print human-readable status summary"""
        status = self.get_infrastructure_status()
        
        print("\n" + "="*80)
        print("APEX CRASH-RESILIENT STRATEGY - STATUS")
        print("="*80)
        
        if not status['enabled']:
            print("⚠️ Crash-resilient infrastructure NOT ENABLED")
            print("="*80 + "\n")
            return
        
        print(f"\n🏛️ Infrastructure Health: {status.get('health', 'unknown').upper()}")
        print(f"   Emergency Mode: {status.get('emergency_mode', False)}")
        
        print(f"\n📊 Strategy Statistics:")
        stats = status.get('strategy_stats', {})
        print(f"   • Trades Validated: {stats.get('trades_validated', 0)}")
        print(f"   • Trades Approved: {stats.get('trades_approved', 0)}")
        print(f"   • Trades Blocked: {stats.get('trades_blocked', 0)}")
        print(f"   • Approval Rate: {stats.get('approval_rate', 0):.1f}%")
        
        print(f"\n📈 Market Metrics:")
        metrics = status.get('metrics', {})
        print(f"   • Portfolio State: {metrics.get('portfolio_state', 'unknown')}")
        print(f"   • Market Regime: {metrics.get('market_regime', 'unknown')}")
        print(f"   • Liquidity Score: {metrics.get('liquidity_score', 0):.2f}")
        print(f"   • Resilience Score: {metrics.get('resilience_score', 0):.2f}")
        
        if status.get('warnings'):
            print(f"\n⚠️ Warnings:")
            for warning in status['warnings']:
                print(f"   • {warning}")
        else:
            print(f"\n✅ No warnings - system healthy")
        
        print("\n" + "="*80 + "\n")


def demo_integration():
    """Demonstrate APEX + Crash-Resilient integration"""
    logging.basicConfig(level=logging.INFO)
    
    print("\n" + "="*80)
    print("APEX CRASH-RESILIENT STRATEGY - DEMO")
    print("="*80)
    
    # Initialize strategy
    strategy = ApexCrashResilientStrategy()
    
    # Simulate market data (OHLCV)
    import numpy as np
    
    dates = pd.date_range(start='2024-01-01', periods=100, freq='1h')
    close_prices = np.random.randn(100).cumsum() + 50000
    df = pd.DataFrame({
        'timestamp': dates,
        'open': close_prices * (1 + np.random.randn(100) * 0.001),
        'high': close_prices * (1 + abs(np.random.randn(100)) * 0.002),
        'low': close_prices * (1 - abs(np.random.randn(100)) * 0.002),
        'close': close_prices,
        'volume': np.random.randint(100000, 1000000, 100),
    })
    
    # Simulate indicators
    indicators = {
        'rsi': pd.Series(np.random.randint(30, 70, 100)),
        'adx': pd.Series(np.random.randint(20, 40, 100)),
        'ema_21': pd.Series(np.random.randn(100).cumsum() + 49800),
        'vwap': pd.Series(np.random.randn(100).cumsum() + 50000),
        'histogram': pd.Series(np.random.randn(100)),
    }
    
    # Simulate portfolio state
    portfolio_state = {
        'account_balance': 10000,
        'total_value': 10000,
        'cash_reserve': 5000,
        'positions': []
    }
    
    # Test entry check
    print("\n📊 Testing long entry validation...")
    can_enter, score, reason, params = strategy.check_long_entry(
        symbol='BTC-USD',
        df=df,
        indicators=indicators,
        portfolio_state=portfolio_state
    )
    
    print(f"\n   Can Enter: {can_enter}")
    print(f"   Score: {score}")
    print(f"   Reason: {reason}")
    
    if params:
        print(f"   Adjusted Params:")
        for key, value in params.items():
            if key != 'warnings':
                print(f"     • {key}: {value}")
    
    # Run periodic checks
    print("\n🔍 Running periodic infrastructure checks...")
    strategy.run_periodic_checks(portfolio_state)
    
    # Show status
    strategy.print_status_summary()


if __name__ == "__main__":
    demo_integration()
