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
