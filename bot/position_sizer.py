"""
NIJA Position Sizer
===================

Calculates appropriate position sizes for user accounts based on master account trades.
Uses equity-based scaling to ensure users trade proportionally to their account size.

Formula:
    user_size = master_size * (user_balance / master_balance)

This ensures:
- Users with smaller accounts take smaller positions (risk management)
- Users with larger accounts take larger positions (capital efficiency)
- All users maintain same risk/reward ratio as master account
"""

import logging
from typing import Dict, Optional

logger = logging.getLogger('nija.position_sizer')

# Minimum position sizes (exchange-specific)
# These prevent creating dust positions that can't be sold
# Updated Jan 21, 2026: Lowered to $2.00 to allow smaller trades (from $5.00)
# Position size must be >= $2.00 for trades to execute
MIN_POSITION_USD = 2.0  # Minimum $2 USD value for any position
MIN_BASE_SIZES = {
    # Coinbase minimums (approximate - updated Jan 2026)
    # NOTE: USD values in comments are examples at Jan 2026 prices and will change
    'BTC': 0.00001,  # Example: ~$0.45 at $45k BTC
    'ETH': 0.0001,   # Example: ~$0.30 at $3k ETH
    'SOL': 0.01,     # Example: ~$1.00 at $100 SOL
    'XRP': 1.0,      # Example: ~$0.50 at $0.50 XRP
    'ADA': 1.0,      # Example: ~$0.50 at $0.50 ADA
    'DOGE': 1.0,     # Example: ~$0.10 at $0.10 DOGE
}


def calculate_user_position_size(
    master_size: float,
    master_balance: float,
    user_balance: float,
    size_type: str = 'quote',
    symbol: str = None,
    min_position_usd: float = MIN_POSITION_USD
) -> Dict:
    """
    Calculate appropriate position size for a user account.
    
    Args:
        master_size: Size of the master account's trade
        master_balance: Total balance of master account
        user_balance: Total balance of user account
        size_type: "quote" (USD amount) or "base" (crypto amount)
        symbol: Trading pair symbol (e.g., "BTC-USD") - used for minimum size validation
        min_position_usd: Minimum position size in USD (default: $1.00)
        
    Returns:
        Dictionary with:
            - 'size': Calculated position size for user
            - 'size_type': Same as input size_type
            - 'valid': True if position meets minimum requirements
            - 'reason': Explanation if position is invalid
            - 'scale_factor': Ratio of user_balance to master_balance
            
    Example:
        Master: $10,000 balance, $500 BTC trade
        User: $1,000 balance
        Result: $50 BTC trade (10% of master size, matching 10% account ratio)
    """
    try:
        # Validate inputs
        if master_balance <= 0:
            logger.error(f"❌ Invalid master_balance: {master_balance}")
            return {
                'size': 0,
                'size_type': size_type,
                'valid': False,
                'reason': f'Invalid master balance: {master_balance}',
                'scale_factor': 0
            }
        
        if user_balance <= 0:
            logger.warning(f"⚠️  User has zero or negative balance: {user_balance}")
            return {
                'size': 0,
                'size_type': size_type,
                'valid': False,
                'reason': f'User balance too low: ${user_balance:.2f}',
                'scale_factor': 0
            }
        
        if master_size <= 0:
            logger.error(f"❌ Invalid master_size: {master_size}")
            return {
                'size': 0,
                'size_type': size_type,
                'valid': False,
                'reason': f'Invalid master size: {master_size}',
                'scale_factor': 0
            }
        
        # Calculate scale factor (user equity as % of master equity)
        scale_factor = user_balance / master_balance
        
        # Calculate scaled position size
        user_size = master_size * scale_factor
        
        logger.info(f"📊 Position Sizing Calculation:")
        logger.info(f"   Master: ${master_balance:.2f} balance, {master_size} size ({size_type})")
        logger.info(f"   User: ${user_balance:.2f} balance")
        logger.info(f"   Scale Factor: {scale_factor:.4f} ({scale_factor*100:.2f}%)")
        logger.info(f"   Calculated User Size: {user_size} ({size_type})")
        
        # Validate minimum position size
        if size_type == 'quote':
            # For USD-denominated trades, check against minimum USD
            if user_size < min_position_usd:
                logger.warning(f"   ⚠️  Position too small: ${user_size:.2f} < ${min_position_usd:.2f} minimum")
                return {
                    'size': user_size,
                    'size_type': size_type,
                    'valid': False,
                    'reason': f'Position too small: ${user_size:.2f} < ${min_position_usd:.2f} minimum',
                    'scale_factor': scale_factor
                }
        
        elif size_type == 'base' and symbol:
            # For crypto-denominated trades, check against exchange minimums
            base_currency = symbol.split('-')[0] if '-' in symbol else symbol
            min_base = MIN_BASE_SIZES.get(base_currency, 0.0001)
            
            if user_size < min_base:
                logger.warning(f"   ⚠️  Position too small: {user_size} {base_currency} < {min_base} minimum")
                return {
                    'size': user_size,
                    'size_type': size_type,
                    'valid': False,
                    'reason': f'Position too small: {user_size} < {min_base} {base_currency} minimum',
                    'scale_factor': scale_factor
                }
        
        logger.info(f"   ✅ Position size valid: {user_size} ({size_type})")
        
        return {
            'size': user_size,
            'size_type': size_type,
            'valid': True,
            'reason': 'Position size valid',
            'scale_factor': scale_factor
        }
        
    except Exception as e:
        logger.error(f"❌ Error calculating position size: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return {
            'size': 0,
            'size_type': size_type,
            'valid': False,
            'reason': f'Calculation error: {e}',
            'scale_factor': 0
        }


def validate_position_size(
    size: float,
    size_type: str,
    symbol: str = None,
    min_position_usd: float = MIN_POSITION_USD
) -> Dict:
    """
    Validate if a position size meets minimum requirements.
    
    Args:
        size: Position size to validate
        size_type: "quote" (USD) or "base" (crypto)
        symbol: Trading pair symbol (e.g., "BTC-USD")
        min_position_usd: Minimum position value in USD
        
    Returns:
        Dictionary with 'valid' (bool) and 'reason' (str)
    """
    try:
        if size <= 0:
            return {'valid': False, 'reason': 'Size must be positive'}
        
        if size_type == 'quote':
            if size < min_position_usd:
                return {
                    'valid': False,
                    'reason': f'Size ${size:.2f} below minimum ${min_position_usd:.2f}'
                }
        
        elif size_type == 'base' and symbol:
            base_currency = symbol.split('-')[0] if '-' in symbol else symbol
            min_base = MIN_BASE_SIZES.get(base_currency, 0.0001)
            
            if size < min_base:
                return {
                    'valid': False,
                    'reason': f'Size {size} {base_currency} below minimum {min_base}'
                }
        
        return {'valid': True, 'reason': 'Valid position size'}
        
    except Exception as e:
        logger.error(f"❌ Error validating position size: {e}")
        return {'valid': False, 'reason': f'Validation error: {e}'}


def round_to_exchange_precision(
    size: float,
    symbol: str,
    size_type: str = 'quote'
) -> float:
    """
    Round position size to exchange-specific precision requirements.
    
    Args:
        size: Position size to round
        symbol: Trading pair symbol (e.g., "BTC-USD")
        size_type: "quote" (USD) or "base" (crypto)
        
    Returns:
        Rounded position size
    """
    try:
        if size_type == 'quote':
            # USD amounts typically use 2 decimal places
            return round(size, 2)
        
        elif size_type == 'base' and symbol:
            # Crypto amounts vary by currency
            base_currency = symbol.split('-')[0] if '-' in symbol else symbol
            
            # Precision map based on typical exchange requirements
            precision_map = {
                'BTC': 8,
                'ETH': 6,
                'SOL': 4,
                'XRP': 2,
                'ADA': 2,
                'DOGE': 2,
                'AVAX': 4,
                'DOT': 4,
                'LINK': 4,
                'LTC': 8,
            }
            
            precision = precision_map.get(base_currency, 4)  # Default to 4 decimals
            return round(size, precision)
        
        # Fallback: return original size
        return size
        
    except Exception as e:
        logger.warning(f"⚠️  Error rounding position size: {e}, returning original")
        return size
