"""
NIJA Exchange-Specific Risk Profiles
Optimize trading parameters for each exchange based on fee structure and characteristics

Each exchange has different:
- Fee structures (maker/taker fees)
- Liquidity characteristics
- Available markets
- Order execution speed
- Reliability

This module defines optimal risk parameters for each exchange.

Author: NIJA Trading Systems
Version: 1.0
Date: December 30, 2025
"""

import logging
from typing import Dict, List, Optional
from enum import Enum

logger = logging.getLogger("nija.exchange_profiles")

# ============================================================================
# EXCHANGE FEE STRUCTURES (as of Dec 2025)
# ============================================================================

class ExchangeFees:
    """Fee structures for different exchanges"""
    
    COINBASE = {
        'maker_fee': 0.004,  # 0.4% maker fee
        'taker_fee': 0.006,  # 0.6% taker fee
        'avg_spread': 0.002,  # ~0.2% average spread
        'total_round_trip': 0.014,  # 1.4% total (market orders)
        'name': 'Coinbase Advanced Trade'
    }
    
    OKX = {
        'maker_fee': 0.0008,  # 0.08% maker fee (VIP 0)
        'taker_fee': 0.0010,  # 0.10% taker fee (VIP 0)
        'avg_spread': 0.001,  # ~0.1% average spread
        'total_round_trip': 0.003,  # 0.3% total (market orders)
        'name': 'OKX Exchange'
    }
    
    KRAKEN = {
        'maker_fee': 0.0016,  # 0.16% maker fee
        'taker_fee': 0.0026,  # 0.26% taker fee
        'avg_spread': 0.0015,  # ~0.15% average spread
        'total_round_trip': 0.0067,  # 0.67% total (market orders)
        'name': 'Kraken Pro'
    }
    
    BINANCE = {
        'maker_fee': 0.0010,  # 0.10% maker fee
        'taker_fee': 0.0010,  # 0.10% taker fee
        'avg_spread': 0.0008,  # ~0.08% average spread (very liquid)
        'total_round_trip': 0.0028,  # 0.28% total (market orders)
        'name': 'Binance'
    }


# ============================================================================
# EXCHANGE-SPECIFIC RISK PROFILES
# ============================================================================

def get_exchange_risk_profile(exchange: str) -> Dict:
    """
    Get optimized risk profile for a specific exchange.
    
    Args:
        exchange: Exchange name ('coinbase', 'okx', 'kraken', 'binance')
        
    Returns:
        Dict with exchange-specific risk parameters
    """
    exchange_lower = exchange.lower()
    
    if exchange_lower == 'coinbase':
        return _get_coinbase_profile()
    elif exchange_lower == 'okx':
        return _get_okx_profile()
    elif exchange_lower == 'kraken':
        return _get_kraken_profile()
    elif exchange_lower == 'binance':
        return _get_binance_profile()
    else:
        logger.warning(f"Unknown exchange: {exchange}, using default profile")
        return _get_default_profile()


def _get_coinbase_profile() -> Dict:
    """
    Coinbase Advanced Trade - Higher fees require larger profit targets
    
    Fee Structure: 1.4% round-trip (highest)
    Strategy: Larger positions, wider targets, quality over quantity
    """
    fees = ExchangeFees.COINBASE
    
    return {
        'exchange': 'coinbase',
        'name': fees['name'],
        'fees': fees,
        
        # Position Sizing (larger positions to offset fees)
        'min_position_pct': 0.15,  # 15% minimum (fees eat small positions)
        'max_position_pct': 0.30,  # 30% maximum
        'optimal_position_pct': 0.20,  # 20% optimal
        'min_position_usd': 15.00,  # $15 minimum for fee efficiency
        
        # Profit Targets (must exceed 1.4% fees)
        'min_profit_target_pct': 0.025,  # 2.5% minimum profit target
        'tp1_pct': 0.030,  # 3.0% - first take profit
        'tp2_pct': 0.045,  # 4.5% - second take profit
        'tp3_pct': 0.065,  # 6.5% - third take profit
        
        # Stop Loss (tighter to protect capital from fee erosion)
        'stop_loss_pct': 0.012,  # 1.2% stop loss
        'max_loss_per_trade': 0.015,  # 1.5% max loss
        
        # Trade Frequency (quality over quantity due to high fees)
        'max_trades_per_day': 15,  # Fewer trades, better quality
        'min_time_between_trades': 300,  # 5 min between trades
        'preferred_order_type': 'limit',  # Use limit orders to save fees
        
        # Signal Quality (stricter filtering)
        'min_signal_strength': 4,  # Require 4/5 signal strength
        'min_adx': 25,  # Higher ADX for stronger trends
        'min_volume_multiplier': 1.2,  # Higher volume confirmation
        
        # Risk Management
        'max_total_exposure': 0.60,  # 60% max exposure
        'max_positions': 3,  # Max 3 positions due to larger sizes
        'capital_allocation_pct': 0.40,  # Default 40% of total capital
        
        # Exchange Characteristics
        'reliability_score': 0.95,  # Very reliable
        'liquidity_tier': 'high',  # High liquidity
        'execution_speed': 'medium',  # Medium speed
    }


def _get_okx_profile() -> Dict:
    """
    OKX Exchange - Lowest fees enable more aggressive trading
    
    Fee Structure: 0.3% round-trip (lowest)
    Strategy: Smaller positions, tighter targets, higher frequency
    """
    fees = ExchangeFees.OKX
    
    return {
        'exchange': 'okx',
        'name': fees['name'],
        'fees': fees,
        
        # Position Sizing (smaller positions due to low fees)
        'min_position_pct': 0.05,  # 5% minimum
        'max_position_pct': 0.20,  # 20% maximum
        'optimal_position_pct': 0.10,  # 10% optimal
        'min_position_usd': 5.00,  # $5 minimum (fees are minimal)
        
        # Profit Targets (tighter due to low fees)
        'min_profit_target_pct': 0.015,  # 1.5% minimum profit target
        'tp1_pct': 0.020,  # 2.0% - first take profit
        'tp2_pct': 0.030,  # 3.0% - second take profit
        'tp3_pct': 0.045,  # 4.5% - third take profit
        
        # Stop Loss (can be tighter with low fees)
        'stop_loss_pct': 0.010,  # 1.0% stop loss
        'max_loss_per_trade': 0.012,  # 1.2% max loss
        
        # Trade Frequency (higher frequency possible)
        'max_trades_per_day': 30,  # More trades due to low fees
        'min_time_between_trades': 180,  # 3 min between trades
        'preferred_order_type': 'market',  # Can use market orders
        
        # Signal Quality (slightly more lenient)
        'min_signal_strength': 3,  # Require 3/5 signal strength
        'min_adx': 20,  # Standard ADX threshold
        'min_volume_multiplier': 1.0,  # Standard volume confirmation
        
        # Risk Management
        'max_total_exposure': 0.80,  # 80% max exposure (aggressive)
        'max_positions': 6,  # Max 6 positions (more diversification)
        'capital_allocation_pct': 0.30,  # Default 30% of total capital
        
        # Exchange Characteristics
        'reliability_score': 0.90,  # Reliable
        'liquidity_tier': 'high',  # High liquidity
        'execution_speed': 'fast',  # Fast execution
    }


def _get_kraken_profile() -> Dict:
    """
    Kraken Pro - Medium fees, balanced approach
    
    Fee Structure: 0.67% round-trip (medium)
    Strategy: Balanced positions and targets
    """
    fees = ExchangeFees.KRAKEN
    
    return {
        'exchange': 'kraken',
        'name': fees['name'],
        'fees': fees,
        
        # Position Sizing (balanced)
        'min_position_pct': 0.10,  # 10% minimum
        'max_position_pct': 0.25,  # 25% maximum
        'optimal_position_pct': 0.15,  # 15% optimal
        'min_position_usd': 10.00,  # $10 minimum
        
        # Profit Targets (balanced)
        'min_profit_target_pct': 0.020,  # 2.0% minimum profit target
        'tp1_pct': 0.025,  # 2.5% - first take profit
        'tp2_pct': 0.038,  # 3.8% - second take profit
        'tp3_pct': 0.055,  # 5.5% - third take profit
        
        # Stop Loss (balanced)
        'stop_loss_pct': 0.011,  # 1.1% stop loss
        'max_loss_per_trade': 0.013,  # 1.3% max loss
        
        # Trade Frequency (balanced)
        'max_trades_per_day': 20,  # Moderate frequency
        'min_time_between_trades': 240,  # 4 min between trades
        'preferred_order_type': 'limit',  # Prefer limit orders
        
        # Signal Quality (balanced)
        'min_signal_strength': 3,  # Require 3/5 signal strength
        'min_adx': 22,  # Moderate ADX threshold
        'min_volume_multiplier': 1.1,  # Moderate volume confirmation
        
        # Risk Management
        'max_total_exposure': 0.70,  # 70% max exposure
        'max_positions': 4,  # Max 4 positions
        'capital_allocation_pct': 0.30,  # Default 30% of total capital
        
        # Exchange Characteristics
        'reliability_score': 0.92,  # Very reliable
        'liquidity_tier': 'medium-high',  # Good liquidity
        'execution_speed': 'medium',  # Medium speed
    }


def _get_binance_profile() -> Dict:
    """
    Binance - Very low fees, very high liquidity
    
    Fee Structure: 0.28% round-trip (very low)
    Strategy: Flexible sizing, high frequency
    """
    fees = ExchangeFees.BINANCE
    
    return {
        'exchange': 'binance',
        'name': fees['name'],
        'fees': fees,
        
        # Position Sizing (flexible)
        'min_position_pct': 0.05,  # 5% minimum
        'max_position_pct': 0.20,  # 20% maximum
        'optimal_position_pct': 0.12,  # 12% optimal
        'min_position_usd': 5.00,  # $5 minimum
        
        # Profit Targets (tight due to very low fees)
        'min_profit_target_pct': 0.012,  # 1.2% minimum profit target
        'tp1_pct': 0.018,  # 1.8% - first take profit
        'tp2_pct': 0.028,  # 2.8% - second take profit
        'tp3_pct': 0.042,  # 4.2% - third take profit
        
        # Stop Loss (tight)
        'stop_loss_pct': 0.009,  # 0.9% stop loss
        'max_loss_per_trade': 0.011,  # 1.1% max loss
        
        # Trade Frequency (very high frequency possible)
        'max_trades_per_day': 35,  # Highest frequency
        'min_time_between_trades': 150,  # 2.5 min between trades
        'preferred_order_type': 'market',  # Can use market orders
        
        # Signal Quality (lenient due to high liquidity)
        'min_signal_strength': 3,  # Require 3/5 signal strength
        'min_adx': 20,  # Standard ADX
        'min_volume_multiplier': 0.9,  # Lower volume requirement
        
        # Risk Management
        'max_total_exposure': 0.85,  # 85% max exposure (very aggressive)
        'max_positions': 7,  # Max 7 positions
        'capital_allocation_pct': 0.0,  # Not currently integrated
        
        # Exchange Characteristics
        'reliability_score': 0.88,  # Generally reliable
        'liquidity_tier': 'very-high',  # Highest liquidity
        'execution_speed': 'very-fast',  # Fastest execution
    }


def _get_default_profile() -> Dict:
    """Default conservative profile for unknown exchanges"""
    return {
        'exchange': 'default',
        'name': 'Default Conservative Profile',
        'fees': {
            'maker_fee': 0.005,
            'taker_fee': 0.005,
            'avg_spread': 0.002,
            'total_round_trip': 0.012,
        },
        'min_position_pct': 0.10,
        'max_position_pct': 0.20,
        'optimal_position_pct': 0.15,
        'min_position_usd': 10.00,
        'min_profit_target_pct': 0.020,
        'tp1_pct': 0.025,
        'tp2_pct': 0.040,
        'tp3_pct': 0.060,
        'stop_loss_pct': 0.012,
        'max_loss_per_trade': 0.015,
        'max_trades_per_day': 15,
        'min_time_between_trades': 300,
        'preferred_order_type': 'limit',
        'min_signal_strength': 4,
        'min_adx': 25,
        'min_volume_multiplier': 1.2,
        'max_total_exposure': 0.60,
        'max_positions': 3,
        'capital_allocation_pct': 0.0,
        'reliability_score': 0.80,
        'liquidity_tier': 'medium',
        'execution_speed': 'medium',
    }


# ============================================================================
# MULTI-EXCHANGE COMPARISON
# ============================================================================

def compare_exchange_profiles() -> None:
    """Print comparison table of all exchange profiles"""
    exchanges = ['coinbase', 'okx', 'kraken', 'binance']
    
    print("\n" + "="*100)
    print("EXCHANGE RISK PROFILE COMPARISON")
    print("="*100)
    
    print(f"\n{'Exchange':<15} {'Fees':<10} {'Min Pos':<10} {'Opt Pos':<10} {'Min Target':<12} {'Max Trades':<12}")
    print("-"*100)
    
    for exchange in exchanges:
        profile = get_exchange_risk_profile(exchange)
        print(f"{profile['name']:<15} "
              f"{profile['fees']['total_round_trip']*100:>6.2f}%   "
              f"{profile['min_position_pct']*100:>6.1f}%   "
              f"{profile['optimal_position_pct']*100:>6.1f}%   "
              f"{profile['min_profit_target_pct']*100:>8.2f}%   "
              f"{profile['max_trades_per_day']:>8}")
    
    print("\n" + "="*100)
    print("\nKEY INSIGHTS:")
    print("• OKX & Binance: Low fees (0.28-0.30%) → Higher frequency, tighter targets")
    print("• Kraken: Medium fees (0.67%) → Balanced approach")
    print("• Coinbase: High fees (1.4%) → Quality over quantity, wider targets")
    print("="*100 + "\n")


def get_best_exchange_for_balance(account_balance: float, 
                                  available_exchanges: List[str]) -> str:
    """
    Recommend best exchange based on account balance.
    
    Args:
        account_balance: Current account balance
        available_exchanges: List of available exchange names
        
    Returns:
        Recommended exchange name
    """
    if account_balance < 50:
        # Small accounts: prefer lowest fees
        for exchange in ['okx', 'binance', 'kraken', 'coinbase']:
            if exchange in [e.lower() for e in available_exchanges]:
                logger.info(f"💡 Recommended for ${account_balance:.2f}: {exchange.upper()} (lowest fees)")
                return exchange
    
    elif account_balance < 200:
        # Medium accounts: prefer balance of fees and reliability
        for exchange in ['kraken', 'okx', 'coinbase']:
            if exchange in [e.lower() for e in available_exchanges]:
                logger.info(f"💡 Recommended for ${account_balance:.2f}: {exchange.upper()} (balanced)")
                return exchange
    
    else:
        # Large accounts: prefer reliability and liquidity
        for exchange in ['coinbase', 'kraken', 'binance', 'okx']:
            if exchange in [e.lower() for e in available_exchanges]:
                logger.info(f"💡 Recommended for ${account_balance:.2f}: {exchange.upper()} (reliable)")
                return exchange
    
    # Fallback to first available
    return available_exchanges[0].lower() if available_exchanges else 'coinbase'


# ============================================================================
# EXPORT FOR INTEGRATION
# ============================================================================

def get_all_exchange_profiles() -> Dict[str, Dict]:
    """Get all exchange profiles as a dictionary"""
    return {
        'coinbase': _get_coinbase_profile(),
        'okx': _get_okx_profile(),
        'kraken': _get_kraken_profile(),
        'binance': _get_binance_profile(),
        'default': _get_default_profile()
    }


if __name__ == "__main__":
    # Print comparison table
    compare_exchange_profiles()
    
    # Test recommendations
    print("\nBALANCE-BASED RECOMMENDATIONS:")
    test_exchanges = ['coinbase', 'okx', 'kraken']
    for balance in [25, 100, 500]:
        best = get_best_exchange_for_balance(balance, test_exchanges)
        print(f"  ${balance}: {best.upper()}")


# ============================================================================
# SECOND MODULE: Exchange Risk Manager with Dataclass Profiles
# ============================================================================
"""
Different risk parameters for each exchange based on:
- Fee structures
- Liquidity characteristics
- Volatility patterns
- Historical performance
- Regulatory environment

Version: 1.0
Author: NIJA Trading Systems
"""

import logging
from typing import Dict, Optional
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger("nija.exchange_risk")


class ExchangeType(Enum):
    """Supported exchanges"""
    COINBASE = "coinbase"
    BINANCE = "binance"
    OKX = "okx"
    KRAKEN = "kraken"
    ALPACA = "alpaca"


@dataclass
class ExchangeRiskProfile:
    """Risk parameters for a specific exchange"""
    
    # Exchange identification
    exchange_name: str
    exchange_type: ExchangeType
    
    # Fee structure (as decimals, e.g., 0.006 = 0.6%)
    maker_fee: float  # Limit order fee
    taker_fee: float  # Market order fee
    withdrawal_fee_usd: float  # Typical withdrawal fee
    
    # Position sizing adjustments
    min_position_size_usd: float  # Minimum viable position
    max_position_size_pct: float  # Max % of account per trade
    recommended_position_pct: float  # Recommended position size
    
    # Stop-loss parameters (as decimals)
    min_stop_loss_pct: float  # Minimum stop distance
    max_stop_loss_pct: float  # Maximum stop distance
    recommended_stop_loss_pct: float  # Recommended stop
    
    # Take-profit parameters (as decimals)
    min_take_profit_pct: float  # Minimum TP to cover fees
    tp1_target_pct: float  # First profit target
    tp2_target_pct: float  # Second profit target
    tp3_target_pct: float  # Third profit target
    
    # Risk multipliers (1.0 = neutral)
    volatility_multiplier: float  # Adjust for exchange volatility
    liquidity_multiplier: float  # Adjust for liquidity depth
    risk_score: float  # Overall risk score (0-10, 10 = riskiest)
    
    # Trading constraints
    max_trades_per_day: int
    max_open_positions: int
    max_total_exposure_pct: float  # Max total capital on exchange
    
    # Exchange-specific features
    supports_limit_orders: bool
    supports_stop_loss_orders: bool
    supports_trailing_stops: bool
    has_maker_rebates: bool
    
    # Performance tracking
    historical_win_rate: Optional[float] = None
    avg_trade_duration_hours: Optional[float] = None
    
    def get_break_even_profit_pct(self, use_limit_order: bool = True) -> float:
        """
        Calculate break-even profit percentage including fees
        
        Args:
            use_limit_order: True for maker fees, False for taker
            
        Returns:
            Break-even profit % as decimal
        """
        fee = self.maker_fee if use_limit_order else self.taker_fee
        # Round-trip cost (buy + sell)
        round_trip_cost = fee * 2
        # Add small buffer for slippage and price movement
        break_even = round_trip_cost * 1.2
        return break_even
    
    def get_adjusted_position_size(self, base_size_pct: float, 
                                   account_balance: float) -> float:
        """
        Get exchange-adjusted position size
        
        Args:
            base_size_pct: Base position size as % (e.g., 0.05 = 5%)
            account_balance: Current account balance
            
        Returns:
            Adjusted position size in USD
        """
        # Apply exchange risk multipliers
        adjusted_pct = base_size_pct * self.liquidity_multiplier
        adjusted_pct = min(adjusted_pct, self.max_position_size_pct)
        adjusted_pct = max(adjusted_pct, self.min_position_size_usd / account_balance)
        
        position_usd = account_balance * adjusted_pct
        position_usd = max(position_usd, self.min_position_size_usd)
        
        return position_usd
    
    def get_adjusted_stop_loss(self, base_stop_pct: float) -> float:
        """
        Get exchange-adjusted stop-loss percentage
        
        Args:
            base_stop_pct: Base stop-loss %
            
        Returns:
            Adjusted stop-loss % as decimal
        """
        # Adjust for exchange volatility
        adjusted_stop = base_stop_pct * self.volatility_multiplier
        
        # Ensure within min/max bounds
        adjusted_stop = max(adjusted_stop, self.min_stop_loss_pct)
        adjusted_stop = min(adjusted_stop, self.max_stop_loss_pct)
        
        return adjusted_stop


# ============================================================================
# EXCHANGE RISK PROFILES
# ============================================================================

EXCHANGE_PROFILES = {
    ExchangeType.COINBASE: ExchangeRiskProfile(
        exchange_name="Coinbase Advanced Trade",
        exchange_type=ExchangeType.COINBASE,
        
        # Coinbase fees (Advanced Trade)
        maker_fee=0.004,  # 0.4% maker (limit orders)
        taker_fee=0.006,  # 0.6% taker (market orders)
        withdrawal_fee_usd=0.0,  # Free withdrawals to Coinbase wallet
        
        # Position sizing (conservative due to higher fees)
        min_position_size_usd=10.0,  # $10 minimum
        max_position_size_pct=0.15,  # 15% max per trade
        recommended_position_pct=0.08,  # 8% recommended
        
        # Stop-loss parameters
        min_stop_loss_pct=0.008,  # 0.8% minimum
        max_stop_loss_pct=0.025,  # 2.5% maximum
        recommended_stop_loss_pct=0.015,  # 1.5% recommended
        
        # Take-profit parameters
        min_take_profit_pct=0.015,  # 1.5% minimum (covers fees)
        tp1_target_pct=0.025,  # 2.5%
        tp2_target_pct=0.040,  # 4.0%
        tp3_target_pct=0.060,  # 6.0%
        
        # Risk adjustments
        volatility_multiplier=1.0,  # Average volatility
        liquidity_multiplier=1.0,  # Good liquidity
        risk_score=4.0,  # Medium-low risk
        
        # Trading constraints
        max_trades_per_day=30,
        max_open_positions=8,
        max_total_exposure_pct=0.40,  # 40% max on Coinbase
        
        # Features
        supports_limit_orders=True,
        supports_stop_loss_orders=True,
        supports_trailing_stops=False,  # Not native
        has_maker_rebates=False,
    ),
    
    ExchangeType.BINANCE: ExchangeRiskProfile(
        exchange_name="Binance",
        exchange_type=ExchangeType.BINANCE,
        
        # Binance fees (lowest in industry)
        maker_fee=0.001,  # 0.1% maker
        taker_fee=0.001,  # 0.1% taker
        withdrawal_fee_usd=1.0,  # ~$1 typical
        
        # Position sizing (more aggressive due to low fees)
        min_position_size_usd=5.0,  # $5 minimum
        max_position_size_pct=0.20,  # 20% max per trade
        recommended_position_pct=0.12,  # 12% recommended
        
        # Stop-loss parameters
        min_stop_loss_pct=0.005,  # 0.5% minimum
        max_stop_loss_pct=0.020,  # 2.0% maximum
        recommended_stop_loss_pct=0.010,  # 1.0% recommended
        
        # Take-profit parameters (can be tighter due to low fees)
        min_take_profit_pct=0.008,  # 0.8% minimum
        tp1_target_pct=0.015,  # 1.5%
        tp2_target_pct=0.025,  # 2.5%
        tp3_target_pct=0.040,  # 4.0%
        
        # Risk adjustments
        volatility_multiplier=1.1,  # Slightly higher volatility
        liquidity_multiplier=1.2,  # Excellent liquidity
        risk_score=5.0,  # Medium risk (regulatory uncertainty)
        
        # Trading constraints
        max_trades_per_day=50,  # More trades allowed (lower fees)
        max_open_positions=12,
        max_total_exposure_pct=0.35,  # 35% max on Binance
        
        # Features
        supports_limit_orders=True,
        supports_stop_loss_orders=True,
        supports_trailing_stops=True,
        has_maker_rebates=True,  # VIP tiers
    ),
    
    ExchangeType.OKX: ExchangeRiskProfile(
        exchange_name="OKX",
        exchange_type=ExchangeType.OKX,
        
        # OKX fees
        maker_fee=0.0008,  # 0.08% maker
        taker_fee=0.0010,  # 0.10% taker
        withdrawal_fee_usd=1.5,  # ~$1.50 typical
        
        # Position sizing
        min_position_size_usd=5.0,  # $5 minimum
        max_position_size_pct=0.18,  # 18% max per trade
        recommended_position_pct=0.10,  # 10% recommended
        
        # Stop-loss parameters
        min_stop_loss_pct=0.006,  # 0.6% minimum
        max_stop_loss_pct=0.020,  # 2.0% maximum
        recommended_stop_loss_pct=0.012,  # 1.2% recommended
        
        # Take-profit parameters
        min_take_profit_pct=0.010,  # 1.0% minimum
        tp1_target_pct=0.018,  # 1.8%
        tp2_target_pct=0.030,  # 3.0%
        tp3_target_pct=0.045,  # 4.5%
        
        # Risk adjustments
        volatility_multiplier=1.05,  # Slightly elevated
        liquidity_multiplier=1.15,  # Very good liquidity
        risk_score=4.5,  # Medium risk
        
        # Trading constraints
        max_trades_per_day=40,
        max_open_positions=10,
        max_total_exposure_pct=0.30,  # 30% max on OKX
        
        # Features
        supports_limit_orders=True,
        supports_stop_loss_orders=True,
        supports_trailing_stops=True,
        has_maker_rebates=True,
    ),
    
    ExchangeType.KRAKEN: ExchangeRiskProfile(
        exchange_name="Kraken Pro",
        exchange_type=ExchangeType.KRAKEN,
        
        # Kraken fees
        maker_fee=0.0016,  # 0.16% maker
        taker_fee=0.0026,  # 0.26% taker
        withdrawal_fee_usd=0.5,  # ~$0.50 typical
        
        # Position sizing
        min_position_size_usd=10.0,  # $10 minimum
        max_position_size_pct=0.15,  # 15% max per trade
        recommended_position_pct=0.09,  # 9% recommended
        
        # Stop-loss parameters
        min_stop_loss_pct=0.008,  # 0.8% minimum
        max_stop_loss_pct=0.022,  # 2.2% maximum
        recommended_stop_loss_pct=0.014,  # 1.4% recommended
        
        # Take-profit parameters
        min_take_profit_pct=0.012,  # 1.2% minimum
        tp1_target_pct=0.020,  # 2.0%
        tp2_target_pct=0.035,  # 3.5%
        tp3_target_pct=0.050,  # 5.0%
        
        # Risk adjustments
        volatility_multiplier=0.95,  # Lower volatility
        liquidity_multiplier=1.0,  # Good liquidity
        risk_score=3.0,  # Low risk (regulated, established)
        
        # Trading constraints
        max_trades_per_day=35,
        max_open_positions=8,
        max_total_exposure_pct=0.25,  # 25% max on Kraken
        
        # Features
        supports_limit_orders=True,
        supports_stop_loss_orders=True,
        supports_trailing_stops=False,
        has_maker_rebates=True,
    ),
    
    ExchangeType.ALPACA: ExchangeRiskProfile(
        exchange_name="Alpaca Markets",
        exchange_type=ExchangeType.ALPACA,
        
        # Alpaca fees (stock trading)
        maker_fee=0.0,  # Commission-free
        taker_fee=0.0,  # Commission-free
        withdrawal_fee_usd=0.0,  # Free
        
        # Position sizing (stocks have different dynamics)
        min_position_size_usd=25.0,  # $25 minimum (stocks)
        max_position_size_pct=0.10,  # 10% max per trade
        recommended_position_pct=0.05,  # 5% recommended
        
        # Stop-loss parameters (tighter for stocks)
        min_stop_loss_pct=0.005,  # 0.5% minimum
        max_stop_loss_pct=0.015,  # 1.5% maximum
        recommended_stop_loss_pct=0.008,  # 0.8% recommended
        
        # Take-profit parameters
        min_take_profit_pct=0.008,  # 0.8% minimum
        tp1_target_pct=0.012,  # 1.2%
        tp2_target_pct=0.020,  # 2.0%
        tp3_target_pct=0.030,  # 3.0%
        
        # Risk adjustments
        volatility_multiplier=0.8,  # Lower than crypto
        liquidity_multiplier=1.1,  # Good stock liquidity
        risk_score=2.5,  # Low risk (regulated, established)
        
        # Trading constraints
        max_trades_per_day=25,  # PDT rules may apply
        max_open_positions=6,
        max_total_exposure_pct=0.30,  # 30% max
        
        # Features
        supports_limit_orders=True,
        supports_stop_loss_orders=True,
        supports_trailing_stops=True,
        has_maker_rebates=False,
    ),
}


class ExchangeRiskManager:
    """Manages risk across multiple exchanges"""
    
    def __init__(self):
        """Initialize exchange risk manager"""
        self.profiles = EXCHANGE_PROFILES
        logger.info("🛡️ Exchange Risk Manager initialized")
        logger.info(f"   Loaded profiles for {len(self.profiles)} exchanges")
    
    def get_profile(self, exchange: ExchangeType) -> ExchangeRiskProfile:
        """
        Get risk profile for an exchange
        
        Args:
            exchange: Exchange type
            
        Returns:
            Exchange risk profile
        """
        return self.profiles[exchange]
    
    def get_optimal_position_size(self, exchange: ExchangeType, 
                                  base_position_pct: float,
                                  account_balance: float) -> float:
        """
        Calculate optimal position size for exchange
        
        Args:
            exchange: Exchange type
            base_position_pct: Base position size
            account_balance: Account balance on exchange
            
        Returns:
            Position size in USD
        """
        profile = self.get_profile(exchange)
        return profile.get_adjusted_position_size(base_position_pct, account_balance)
    
    def get_optimal_stop_loss(self, exchange: ExchangeType,
                             base_stop_pct: float) -> float:
        """
        Get exchange-specific stop-loss percentage
        
        Args:
            exchange: Exchange type
            base_stop_pct: Base stop-loss %
            
        Returns:
            Adjusted stop-loss % as decimal
        """
        profile = self.get_profile(exchange)
        return profile.get_adjusted_stop_loss(base_stop_pct)
    
    def compare_exchanges(self) -> str:
        """
        Generate comparison report of all exchanges
        
        Returns:
            Formatted comparison string
        """
        report = [
            "\n" + "=" * 90,
            "EXCHANGE RISK PROFILE COMPARISON",
            "=" * 90,
            ""
        ]
        
        for exchange_type, profile in self.profiles.items():
            report.extend([
                f"\n{profile.exchange_name} ({exchange_type.value.upper()})",
                "-" * 90,
                f"  Fees: Maker {profile.maker_fee*100:.2f}% | Taker {profile.taker_fee*100:.2f}%",
                f"  Break-Even: {profile.get_break_even_profit_pct(True)*100:.2f}% (limit) | "
                f"{profile.get_break_even_profit_pct(False)*100:.2f}% (market)",
                f"  Position Size: {profile.min_position_size_usd:.0f}-{profile.recommended_position_pct*100:.0f}% "
                f"(max {profile.max_position_size_pct*100:.0f}%)",
                f"  Stop-Loss: {profile.min_stop_loss_pct*100:.2f}%-{profile.max_stop_loss_pct*100:.2f}% "
                f"(recommended {profile.recommended_stop_loss_pct*100:.2f}%)",
                f"  Take-Profit Targets: {profile.tp1_target_pct*100:.1f}% | "
                f"{profile.tp2_target_pct*100:.1f}% | {profile.tp3_target_pct*100:.1f}%",
                f"  Risk Score: {profile.risk_score}/10",
                f"  Max Trades/Day: {profile.max_trades_per_day}",
                f"  Max Exposure: {profile.max_total_exposure_pct*100:.0f}%",
                f"  Features: {'Limit' if profile.supports_limit_orders else ''} "
                f"{'| Stop-Loss' if profile.supports_stop_loss_orders else ''} "
                f"{'| Trailing' if profile.supports_trailing_stops else ''} "
                f"{'| Rebates' if profile.has_maker_rebates else ''}",
            ])
        
        report.extend(["", "=" * 90, ""])
        return "\n".join(report)


# Singleton instance
_risk_manager_instance: Optional[ExchangeRiskManager] = None

def get_exchange_risk_manager() -> ExchangeRiskManager:
    """Get singleton instance of ExchangeRiskManager"""
    global _risk_manager_instance
    if _risk_manager_instance is None:
        _risk_manager_instance = ExchangeRiskManager()
    return _risk_manager_instance


if __name__ == "__main__":
    # Test/demonstration
    logging.basicConfig(
        level=logging.INFO,
        format='%(levelname)s - %(message)s'
    )
    
    manager = ExchangeRiskManager()
    print(manager.compare_exchanges())
    
    # Example calculations
    print("\nExample Position Size Calculations ($1000 account, 5% base):")
    print("-" * 60)
    for exchange in ExchangeType:
        pos_size = manager.get_optimal_position_size(exchange, 0.05, 1000.0)
        print(f"{exchange.value:12s}: ${pos_size:.2f}")
