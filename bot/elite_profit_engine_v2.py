"""
NIJA Elite Profit Engine v2
============================

Master orchestrator for all profit optimization systems.

Integrates:
1. Volatility-Adaptive Position Sizing
2. Smart Capital Rotation (scalp/momentum/trend)
3. Adaptive Leverage System
4. Smart Daily Profit Locking
5. Trade Frequency Optimization
6. Auto-Compounding Engine

This is the TOP-LEVEL profit optimization layer that coordinates all subsystems.

Author: NIJA Trading Systems
Version: 2.0 - Elite Profit Engine
Date: January 29, 2026
"""

import logging
from typing import Dict, Optional, Tuple
from datetime import datetime
import pandas as pd

# Import all optimization modules
try:
    from volatility_adaptive_sizer import VolatilityAdaptiveSizer, get_volatility_adaptive_sizer
    from smart_capital_rotator import SmartCapitalRotator, StrategyType, get_smart_capital_rotator
    from adaptive_leverage_system import AdaptiveLeverageSystem, get_adaptive_leverage_system, LeverageMode
    from smart_daily_profit_locker import SmartDailyProfitLocker, get_smart_daily_profit_locker
    from trade_frequency_optimizer import TradeFrequencyOptimizer, get_trade_frequency_optimizer, SignalQuality
    from profit_compounding_engine import ProfitCompoundingEngine, get_compounding_engine
except ImportError:
    # Try absolute imports if relative imports fail
    from bot.volatility_adaptive_sizer import VolatilityAdaptiveSizer, get_volatility_adaptive_sizer
    from bot.smart_capital_rotator import SmartCapitalRotator, StrategyType, get_smart_capital_rotator
    from bot.adaptive_leverage_system import AdaptiveLeverageSystem, get_adaptive_leverage_system, LeverageMode
    from bot.smart_daily_profit_locker import SmartDailyProfitLocker, get_smart_daily_profit_locker
    from bot.trade_frequency_optimizer import TradeFrequencyOptimizer, get_trade_frequency_optimizer, SignalQuality
    from bot.profit_compounding_engine import ProfitCompoundingEngine, get_compounding_engine

logger = logging.getLogger("nija.elite_engine")


class EliteProfitEngineV2:
    """
    Master profit optimization orchestrator

    Coordinates all profit optimization subsystems to maximize returns
    while managing risk dynamically.
    """

    def __init__(
        self,
        base_capital: float,
        config: Dict = None
    ):
        """
        Initialize Elite Profit Engine v2

        Args:
            base_capital: Starting capital
            config: Configuration dictionary
        """
        self.base_capital = base_capital
        self.config = config or {}
        self.current_balance = base_capital

        # Initialize all subsystems
        logger.info("=" * 90)
        logger.info("🚀 INITIALIZING ELITE PROFIT ENGINE V2")
        logger.info("=" * 90)
        logger.info(f"Base Capital: ${base_capital:,.2f}")
        logger.info("")

        # 1. Volatility-Adaptive Position Sizing
        volatility_config = self.config.get('volatility_sizer', {})
        self.volatility_sizer = get_volatility_adaptive_sizer(volatility_config)
        logger.info("✅ Volatility-Adaptive Sizer initialized")

        # 2. Smart Capital Rotation
        rotation_config = self.config.get('capital_rotation', {})
        self.capital_rotator = get_smart_capital_rotator(base_capital, rotation_config)
        logger.info("✅ Smart Capital Rotator initialized")

        # 3. Adaptive Leverage System
        leverage_config = self.config.get('leverage', {})
        self.leverage_system = get_adaptive_leverage_system(leverage_config)
        logger.info("✅ Adaptive Leverage System initialized")

        # 4. Smart Daily Profit Locking
        profit_lock_config = self.config.get('profit_locking', {})
        self.profit_locker = get_smart_daily_profit_locker(base_capital, profit_lock_config)
        logger.info("✅ Smart Daily Profit Locker initialized")

        # 5. Trade Frequency Optimizer
        frequency_config = self.config.get('frequency_optimizer', {})
        self.frequency_optimizer = get_trade_frequency_optimizer(frequency_config)
        logger.info("✅ Trade Frequency Optimizer initialized")

        # 6. Profit Compounding Engine
        compounding_strategy = self.config.get('compounding_strategy', 'moderate')
        self.compounding_engine = get_compounding_engine(base_capital, compounding_strategy)
        logger.info("✅ Profit Compounding Engine initialized")

        logger.info("")
        logger.info("=" * 90)
        logger.info("🏆 ELITE PROFIT ENGINE V2 READY")
        logger.info("=" * 90)
        logger.info("")

    def calculate_optimal_position_size(
        self,
        df: pd.DataFrame,
        indicators: Dict,
        signal_score: float,
        strategy_type: StrategyType = StrategyType.MOMENTUM
    ) -> Dict:
        """
        Calculate optimal position size using all optimization systems

        Args:
            df: Price DataFrame
            indicators: Technical indicators
            signal_score: Entry signal score (0-100)
            strategy_type: Type of strategy (SCALP/MOMENTUM/TREND)

        Returns:
            Dictionary with position sizing details
        """
        # 1. Get volatility-adjusted base position
        volatility_result = self.volatility_sizer.calculate_adaptive_position_size(
            df=df,
            indicators=indicators,
            available_balance=self.current_balance
        )

        base_position = volatility_result['position_size_usd']

        # 2. Get strategy-specific capital allocation
        strategy_capital = self.capital_rotator.get_strategy_capital(strategy_type)

        # Limit position to strategy allocation
        if base_position > strategy_capital:
            base_position = strategy_capital

        # 3. Apply leverage (if enabled)
        leverage_state = self.leverage_system.calculate_adaptive_leverage(
            df=df,
            indicators=indicators,
            base_capital=self.base_capital,
            current_balance=self.current_balance
        )

        leveraged_position = self.leverage_system.get_effective_position_size(base_position)

        # 4. Apply daily profit locking adjustments
        profit_multiplier = self.profit_locker.get_position_size_multiplier()
        final_position = leveraged_position * profit_multiplier

        # 5. Compile result
        result = {
            'final_position_usd': final_position,
            'base_position_usd': base_position,
            'volatility_adjusted': volatility_result,
            'strategy_allocation': strategy_capital,
            'leverage': leverage_state.current_leverage,
            'leverage_state': leverage_state,
            'profit_lock_multiplier': profit_multiplier,
            'signal_score': signal_score,
        }

        logger.info("=" * 90)
        logger.info("💰 OPTIMAL POSITION SIZE CALCULATED")
        logger.info("=" * 90)
        logger.info(f"Signal Score: {signal_score:.1f}/100")
        logger.info(f"Strategy: {strategy_type.value.upper()}")
        logger.info(f"Volatility Regime: {volatility_result['volatility_regime']}")
        logger.info(f"Base Position: ${base_position:,.2f}")
        logger.info(f"Leverage: {leverage_state.current_leverage:.2f}x → ${leveraged_position:,.2f}")
        logger.info(f"Profit Lock Multiplier: {profit_multiplier:.0%}")
        logger.info(f"FINAL POSITION: ${final_position:,.2f}")
        logger.info("=" * 90)

        return result

    def should_take_trade(
        self,
        signal_score: float,
        min_quality: SignalQuality = SignalQuality.FAIR
    ) -> Tuple[bool, str]:
        """
        Determine if a trade should be taken

        Args:
            signal_score: Signal quality score
            min_quality: Minimum required quality

        Returns:
            Tuple of (should_take, reason)
        """
        # Check signal quality
        if not self.frequency_optimizer.should_take_signal(signal_score, min_quality):
            return False, f"Signal quality too low: {signal_score:.1f}/100"

        # Check daily profit locking status
        if not self.profit_locker.should_take_new_trade():
            return False, "Daily profit target achieved - trading stopped"

        # Check leverage system risk score
        # (This would need current leverage state, skipping for simplicity)

        return True, "All systems green - trade approved"

    def record_trade_result(
        self,
        strategy_type: StrategyType,
        gross_profit: float,
        fees: float,
        is_win: bool
    ):
        """
        Record trade result across all subsystems

        Args:
            strategy_type: Strategy that generated the trade
            gross_profit: Gross profit before fees
            fees: Trading fees paid
            is_win: True if trade was profitable
        """
        net_profit = gross_profit - fees

        # Update balance
        self.current_balance += net_profit

        # 1. Update capital rotator
        self.capital_rotator.record_trade_result(strategy_type, net_profit, is_win)

        # 2. Update leverage system
        self.leverage_system.record_trade_result(net_profit, is_win)

        # 3. Update daily profit locker
        self.profit_locker.record_trade(net_profit, is_win)

        # 4. Update compounding engine
        self.compounding_engine.record_trade(gross_profit, fees, is_win)

        # 5. Update capital rotator total capital
        self.capital_rotator.update_total_capital(self.current_balance)

        logger.info("=" * 90)
        logger.info("📊 TRADE RESULT RECORDED ACROSS ALL SYSTEMS")
        logger.info("=" * 90)
        logger.info(f"Strategy: {strategy_type.value.upper()}")
        logger.info(f"Gross P/L: ${gross_profit:+.2f}")
        logger.info(f"Fees: ${fees:.2f}")
        logger.info(f"Net P/L: ${net_profit:+.2f}")
        logger.info(f"New Balance: ${self.current_balance:,.2f}")
        logger.info("=" * 90)

    def execute_capital_rotation(
        self,
        df: pd.DataFrame,
        indicators: Dict
    ) -> Dict[StrategyType, float]:
        """
        Execute capital rotation based on market conditions

        Args:
            df: Price DataFrame
            indicators: Technical indicators

        Returns:
            Dictionary mapping strategies to capital amounts
        """
        return self.capital_rotator.rotate_capital(df, indicators, smooth_transition=True)

    def get_optimal_scan_interval(
        self,
        volatility_regime: str = "normal"
    ) -> int:
        """
        Get optimal market scanning interval

        Args:
            volatility_regime: Current volatility regime

        Returns:
            Scan interval in seconds
        """
        signal_density = self.frequency_optimizer.calculate_signal_density(60)

        return self.frequency_optimizer.get_optimal_scan_interval(
            current_time=datetime.utcnow(),
            volatility_regime=volatility_regime,
            signal_density=signal_density
        )

    def get_master_report(
        self,
        df: pd.DataFrame,
        indicators: Dict
    ) -> str:
        """
        Generate comprehensive master report from all subsystems

        Args:
            df: Price DataFrame
            indicators: Technical indicators

        Returns:
            Formatted master report
        """
        report = [
            "\n" + "=" * 100,
            "ELITE PROFIT ENGINE V2 - MASTER REPORT",
            "=" * 100,
            f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"Base Capital: ${self.base_capital:,.2f}",
            f"Current Balance: ${self.current_balance:,.2f}",
            f"Total Profit: ${self.current_balance - self.base_capital:+,.2f} ({((self.current_balance/self.base_capital - 1)*100):+.2f}%)",
            "=" * 100,
            "",
        ]

        # Add individual subsystem reports
        report.append("📊 VOLATILITY ANALYSIS")
        report.append("-" * 100)
        report.append(self.volatility_sizer.get_volatility_report(df, indicators))
        report.append("")

        report.append("🔄 CAPITAL ROTATION")
        report.append("-" * 100)
        report.append(self.capital_rotator.get_rotation_report(df, indicators))
        report.append("")

        report.append("🔒 DAILY PROFIT LOCKING")
        report.append("-" * 100)
        report.append(self.profit_locker.get_profit_locking_report())
        report.append("")

        report.append("🎯 TRADE FREQUENCY OPTIMIZATION")
        report.append("-" * 100)
        report.append(self.frequency_optimizer.get_frequency_report())
        report.append("")

        report.append("💰 PROFIT COMPOUNDING")
        report.append("-" * 100)
        report.append(self.compounding_engine.get_compounding_report())
        report.append("")

        report.append("=" * 100)
        report.append("END OF MASTER REPORT")
        report.append("=" * 100)

        return "\n".join(report)

    def get_current_status(self) -> Dict:
        """
        Get current status of all subsystems

        Returns:
            Dictionary with status information
        """
        return {
            'base_capital': self.base_capital,
            'current_balance': self.current_balance,
            'total_profit': self.current_balance - self.base_capital,
            'roi_pct': ((self.current_balance / self.base_capital) - 1) * 100,
            'daily_profit': self.profit_locker.daily_profit,
            'daily_target': self.profit_locker.daily_target,
            'locked_profit': self.profit_locker.locked_profit,
            'trading_mode': self.profit_locker.trading_mode.value,
            'current_leverage': self.leverage_system.current_leverage,
            'compounding_multiplier': self.compounding_engine.get_compound_multiplier(),
        }


def get_elite_profit_engine_v2(
    base_capital: float,
    config: Dict = None
) -> EliteProfitEngineV2:
    """
    Factory function to create Elite Profit Engine v2

    Args:
        base_capital: Starting capital
        config: Configuration dictionary

    Returns:
        EliteProfitEngineV2 instance
    """
    return EliteProfitEngineV2(base_capital, config)


# Example usage
if __name__ == "__main__":
    import logging
    import numpy as np

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Create sample data
    dates = pd.date_range('2024-01-01', periods=100, freq='1h')
    df = pd.DataFrame({
        'timestamp': dates,
        'close': np.random.randn(100).cumsum() + 100,
        'high': np.random.randn(100).cumsum() + 102,
        'low': np.random.randn(100).cumsum() + 98,
        'volume': np.random.randint(1000, 10000, 100)
    })

    # Calculate indicators
    try:
        from indicators import calculate_atr, calculate_rsi, calculate_macd
    except ImportError:
        from bot.indicators import calculate_atr, calculate_rsi, calculate_macd
    df['atr'] = calculate_atr(df, period=14)
    df['rsi'] = calculate_rsi(df, period=14)
    macd, signal, hist = calculate_macd(df)

    indicators = {
        'atr': df['atr'],
        'adx': pd.Series([28.0] * 100),  # Mock ADX
        'rsi': df['rsi'],
        'macd': macd,
        'signal': signal,
        'histogram': hist,
    }

    # Configuration
    config = {
        'leverage': {
            'leverage_mode': 'moderate'  # conservative/moderate/aggressive
        },
        'profit_locking': {
            'daily_target_pct': 0.02  # 2% daily target
        },
        'compounding_strategy': 'moderate'  # conservative/moderate/aggressive
    }

    # Create Elite Profit Engine v2
    print("\n" + "=" * 100)
    print("INITIALIZING ELITE PROFIT ENGINE V2")
    print("=" * 100 + "\n")

    engine = get_elite_profit_engine_v2(base_capital=10000.0, config=config)

    # Calculate optimal position size
    print("\n" + "=" * 100)
    print("CALCULATING OPTIMAL POSITION SIZE")
    print("=" * 100 + "\n")

    position_result = engine.calculate_optimal_position_size(
        df=df,
        indicators=indicators,
        signal_score=82.0,  # High quality signal
        strategy_type=StrategyType.MOMENTUM
    )

    print(f"\n✅ Optimal Position Size: ${position_result['final_position_usd']:,.2f}")

    # Simulate some trades
    print("\n" + "=" * 100)
    print("SIMULATING TRADES")
    print("=" * 100 + "\n")

    engine.record_trade_result(
        strategy_type=StrategyType.MOMENTUM,
        gross_profit=150.0,
        fees=5.0,
        is_win=True
    )

    engine.record_trade_result(
        strategy_type=StrategyType.TREND,
        gross_profit=200.0,
        fees=7.0,
        is_win=True
    )

    # Get current status
    status = engine.get_current_status()
    print("\n" + "=" * 100)
    print("CURRENT STATUS")
    print("=" * 100)
    for key, value in status.items():
        if isinstance(value, float):
            print(f"{key:25s}: {value:>15,.2f}")
        else:
            print(f"{key:25s}: {value:>15}")

    # Generate master report
    print("\n" + "=" * 100)
    print("GENERATING MASTER REPORT")
    print("=" * 100 + "\n")

    master_report = engine.get_master_report(df, indicators)
    print(master_report)
