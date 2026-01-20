# bot/broker_manager.py
"""
NIJA Multi-Brokerage Manager
Supports: Coinbase, Interactive Brokers, TD Ameritrade, Alpaca, etc.
"""

from enum import Enum
from abc import ABC, abstractmethod
from typing import Dict, List, Optional
import functools
import json
import logging
import os
import random
import re
import time
import traceback
import uuid
import threading

# Import requests exceptions for proper timeout error handling
# These are used in KrakenBroker.connect() to detect network timeouts
# Note: The flag name is specific to clarify we're checking for timeout exception classes,
# not just whether requests is available (it's used elsewhere for HTTP calls)
try:
    from requests.exceptions import (
        Timeout, 
        ReadTimeout, 
        ConnectTimeout, 
        ConnectionError as RequestsConnectionError  # Avoid shadowing built-in ConnectionError
    )
    REQUESTS_TIMEOUT_EXCEPTIONS_AVAILABLE = True
except (ImportError, ModuleNotFoundError):
    # If requests isn't available, we'll fallback to string matching
    # ModuleNotFoundError is more specific but we catch both for compatibility
    REQUESTS_TIMEOUT_EXCEPTIONS_AVAILABLE = False

# Try to load dotenv if available, but don't fail if not
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv not available, env vars should be set externally

# Import rate limiter for API call throttling
try:
    from bot.rate_limiter import RateLimiter
except ImportError:
    try:
        from rate_limiter import RateLimiter
    except ImportError:
        # Fallback if rate_limiter not available
        RateLimiter = None

# Import Global Kraken Nonce Manager (ONE source for all users - FINAL FIX)
try:
    from bot.global_kraken_nonce import get_global_kraken_nonce, get_kraken_api_lock, jump_global_kraken_nonce_forward
except ImportError:
    try:
        from global_kraken_nonce import get_global_kraken_nonce, get_kraken_api_lock, jump_global_kraken_nonce_forward
    except ImportError:
        # Fallback: Global nonce manager not available
        get_global_kraken_nonce = None
        get_kraken_api_lock = None
        jump_global_kraken_nonce_forward = None

# Import Balance Models (FIX 1: Three-part balance model)
try:
    from bot.balance_models import BalanceSnapshot, UserBrokerState, create_balance_snapshot_from_broker_response
except ImportError:
    try:
        from balance_models import BalanceSnapshot, UserBrokerState, create_balance_snapshot_from_broker_response
    except ImportError:
        # Fallback: Balance models not available
        BalanceSnapshot = None
        UserBrokerState = None
        create_balance_snapshot_from_broker_response = None

# Import KrakenNonce for per-user nonce generation (DEPRECATED - kept for backward compatibility)
# NOTE: This is being phased out in favor of GlobalKrakenNonceManager
try:
    from bot.kraken_nonce import KrakenNonce
except ImportError:
    try:
        from kraken_nonce import KrakenNonce
    except ImportError:
        # Fallback: KrakenNonce not available
        KrakenNonce = None

# Configure logger for broker operations
logger = logging.getLogger('nija.broker')

# Root nija logger for flushing all handlers
# Child loggers (like 'nija.broker', 'nija.multi_account') propagate to this logger
# but don't have their own handlers, so we need to flush the root logger's handlers
_root_logger = logging.getLogger('nija')

# Balance threshold constants
# Note: Large gap between PROTECTION and TRADING thresholds is intentional:
#   - PROTECTION ($0.50): Absolute minimum to allow bot to start (hard requirement)
#   - TRADING ($25.00): Minimum for both Kraken and Coinbase (enforced per broker)
#   This ensures both exchanges require $25 minimum while maintaining different roles
MINIMUM_BALANCE_PROTECTION = 0.50  # Absolute minimum to start (system-wide hard floor)
STANDARD_MINIMUM_BALANCE = 25.00  # Standard minimum for active trading on both exchanges
MINIMUM_TRADING_BALANCE = STANDARD_MINIMUM_BALANCE  # Alias for backward compatibility
DUST_THRESHOLD_USD = 1.00  # USD value threshold for dust positions (consistent with enforcer)

# Broker-specific minimum balance requirements
# Both require the same amount ($25) but with different priority and strategy rules:
# - Kraken: PRIMARY engine for small accounts ($25-$75 range)
# - Coinbase: SECONDARY/selective (not for small accounts, uses Coinbase-specific strategy)
KRAKEN_MINIMUM_BALANCE = STANDARD_MINIMUM_BALANCE  # Kraken is PRIMARY for small accounts
COINBASE_MINIMUM_BALANCE = STANDARD_MINIMUM_BALANCE  # Coinbase is SECONDARY with adjusted rules
# 🚑 FIX 2: Minimum balance for Coinbase to prevent fees eating small accounts
# Coinbase has higher fees than Kraken, so small accounts should use Kraken instead
# UNIFIED MINIMUM: $25 to match position sizing and adapter rules
# At $25 balance, can make 1 full trade; at $50+ can make 2+ concurrent trades
COINBASE_MINIMUM_BALANCE = 25.00  # Disable Coinbase for accounts below this threshold

# Broker health monitoring constants
# Maximum consecutive errors before marking broker unavailable
# This prevents trading when API is persistently failing
BROKER_MAX_CONSECUTIVE_ERRORS = 3

# Kraken startup delay (Jan 17, 2026) - Critical fix for nonce collisions
# This delay is applied before the first Kraken API call to ensure:
# - Nonce file exists and is initialized properly
# - No collision with other user accounts starting simultaneously
# - No parallel nonce generation during bootstrap
KRAKEN_STARTUP_DELAY_SECONDS = 5.0  # Similar to Coinbase's 40s delay but shorter due to better nonce handling

# Credential validation constants
PLACEHOLDER_PASSPHRASE_VALUES = [
    'your_passphrase', 'YOUR_PASSPHRASE', 
    'passphrase', 'PASSPHRASE',
    'your_password', 'YOUR_PASSWORD',
    'password', 'PASSWORD'
]


# ============================================================================
# BROKER-AWARE SYMBOL NORMALIZATION (FIX #1 - Jan 19, 2026)
# ============================================================================
# Each exchange uses different symbol formats:
# - Coinbase:  ETH-USD, ETH-USDT, ETH-USDC (dash separator)
# - Kraken:    ETH/USD, ETH/USDT, XETHZUSD (slash or no separator)
# - Binance:   ETHUSDT, ETHBUSD (no separator, includes BUSD)
# - OKX:       ETH-USDT (dash separator, prefers USDT over USD)
#
# Common mistakes that cause failures:
# - Using Binance symbols (ETH.BUSD) on Kraken → Kraken doesn't support BUSD
# - Using generic symbols without broker-specific mapping → Invalid product errors
#
# This function ensures symbols are properly formatted for each broker.
# ============================================================================

def normalize_symbol_for_broker(symbol: str, broker_name: str) -> str:
    """
    Normalize a trading symbol to the format expected by a specific broker.
    
    This prevents cross-broker symbol compatibility issues like trying to
    trade Binance-only pairs (BUSD) on Kraken, or using wrong separators.
    
    Args:
        symbol: Input symbol in any format (ETH-USD, ETH.BUSD, ETHUSDT, etc.)
        broker_name: Broker name ('coinbase', 'kraken', 'binance', 'okx', etc.)
    
    Returns:
        Normalized symbol in broker-specific format
        
    Examples:
        normalize_symbol_for_broker("ETH.BUSD", "kraken") → "ETH/USD"
        normalize_symbol_for_broker("ETH-USD", "kraken") → "ETH/USD"
        normalize_symbol_for_broker("ETHUSDT", "coinbase") → "ETH-USD"
        normalize_symbol_for_broker("BTC-USD", "binance") → "BTCUSDT"
    """
    if not symbol or not broker_name:
        return symbol
    
    broker_name = broker_name.lower()
    symbol_upper = symbol.upper()
    
    # Extract base and quote currencies from various formats
    # Handle formats: ETH-USD, ETH.BUSD, ETHUSDT, ETH/USD
    base = None
    quote = None
    
    # Split on common separators
    if '-' in symbol_upper:
        parts = symbol_upper.split('-')
        base, quote = parts[0], parts[1] if len(parts) > 1 else 'USD'
    elif '/' in symbol_upper:
        parts = symbol_upper.split('/')
        base, quote = parts[0], parts[1] if len(parts) > 1 else 'USD'
    elif '.' in symbol_upper:
        parts = symbol_upper.split('.')
        base, quote = parts[0], parts[1] if len(parts) > 1 else 'USD'
    else:
        # No separator - try to detect common patterns
        # Most common: ETHUSDT, BTCUSDT, ETHBUSD
        if symbol_upper.endswith('USDT'):
            base = symbol_upper[:-4]
            quote = 'USDT'
        elif symbol_upper.endswith('BUSD'):
            base = symbol_upper[:-4]
            quote = 'BUSD'
        elif symbol_upper.endswith('USDC'):
            base = symbol_upper[:-4]
            quote = 'USDC'
        elif symbol_upper.endswith('USD'):
            base = symbol_upper[:-3]
            quote = 'USD'
        else:
            # Can't parse - return as-is
            return symbol
    
    # CRITICAL: Map BUSD (Binance-only) to supported stablecoins
    # Kraken, Coinbase, OKX don't support BUSD
    if quote == 'BUSD':
        if broker_name == 'kraken':
            quote = 'USD'  # Kraken prefers native USD
        elif broker_name == 'coinbase':
            quote = 'USD'  # Coinbase prefers native USD
        elif broker_name == 'okx':
            quote = 'USDT'  # OKX prefers USDT
        elif broker_name == 'binance':
            quote = 'BUSD'  # Keep BUSD for Binance
        else:
            quote = 'USD'  # Default to USD for unknown brokers
    
    # Broker-specific formatting
    if broker_name == 'kraken':
        # Kraken format: ETH/USD, BTC/USDT, XETHZUSD (slash separator)
        # Note: Kraken internally uses X prefix for some assets (XETH, XXBT)
        # but the slash format is more standard
        return f"{base}/{quote}"
        
    elif broker_name == 'coinbase':
        # Coinbase format: ETH-USD, BTC-USDT (dash separator)
        # NOTE: Coinbase supports both USD and USDT/USDC pairs
        # We don't auto-convert USDC/USDT to USD because some assets
        # may only have USDT/USDC pairs available, not USD
        return f"{base}-{quote}"
        
    elif broker_name == 'binance':
        # Binance format: ETHUSDT, BTCBUSD (no separator)
        return f"{base}{quote}"
        
    elif broker_name == 'okx':
        # OKX format: ETH-USDT, BTC-USDT (dash separator, prefers USDT)
        # Convert USD to USDT for OKX
        if quote == 'USD':
            quote = 'USDT'
        return f"{base}-{quote}"
        
    elif broker_name == 'alpaca':
        # Alpaca format: varies, but generally handles standard formats
        # Keep dash separator
        return f"{base}-{quote}"
        
    else:
        # Unknown broker - return with dash separator (most common)
        return f"{base}-{quote}"

# Rate limiting retry constants
# UPDATED (Jan 10, 2026): Significantly increased 403 error delays to prevent persistent API blocks
# 403 "Forbidden Too many errors" indicates API key is temporarily banned - needs longer cooldown
RATE_LIMIT_MAX_RETRIES = 3  # Maximum retries for rate limit errors (reduced from 6)
RATE_LIMIT_BASE_DELAY = 5.0  # Base delay in seconds for exponential backoff on 429 errors
FORBIDDEN_BASE_DELAY = 60.0  # Fixed delay for 403 "Forbidden" errors (increased from 30s to 60s for API key temporary ban)
FORBIDDEN_JITTER_MAX = 30.0   # Maximum additional random delay for 403 "Forbidden" errors (60-90s total, increased from 30-45s)

# Fallback market list - popular crypto trading pairs used when API fails
FALLBACK_MARKETS = [
    'BTC-USD', 'ETH-USD', 'SOL-USD', 'XRP-USD', 'ADA-USD', 
    'DOGE-USD', 'MATIC-USD', 'DOT-USD', 'LINK-USD', 'UNI-USD',
    'AVAX-USD', 'ATOM-USD', 'LTC-USD', 'NEAR-USD', 'ALGO-USD',
    'XLM-USD', 'HBAR-USD', 'APT-USD', 'ARB-USD', 'OP-USD',
    'INJ-USD', 'SUI-USD', 'TIA-USD', 'SEI-USD', 'RUNE-USD',
    'FET-USD', 'IMX-USD', 'RENDER-USD', 'GRT-USD', 'AAVE-USD',
    'MKR-USD', 'SNX-USD', 'CRV-USD', 'LDO-USD', 'COMP-USD',
    'SAND-USD', 'MANA-USD', 'AXS-USD', 'FIL-USD', 'VET-USD',
    'ICP-USD', 'FLOW-USD', 'EOS-USD', 'XTZ-USD', 'THETA-USD',
    'ZEC-USD', 'ETC-USD', 'BAT-USD', 'ENJ-USD', 'CHZ-USD'
]


def _serialize_object_to_dict(obj) -> Dict:
    """
    Safely convert any object to a dictionary for JSON serialization.
    Handles nested objects, dataclasses, and Coinbase SDK response objects.
    
    Args:
        obj: Any object to convert
        
    Returns:
        dict: Flattened dictionary representation
    """
    if obj is None:
        return {}
    
    if isinstance(obj, dict):
        return obj

    # If it's already a string that looks like JSON/dict, try to parse
    if isinstance(obj, str):
        try:
            return json.loads(obj)
        except Exception:
            try:
                import ast
                return ast.literal_eval(obj)
            except Exception:
                return {"_raw": obj, "_type": type(obj).__name__}
    
    # Try JSON serialization first (handles dataclasses with json.JSONEncoder)
    try:
        json_str = json.dumps(obj, default=str)
        return json.loads(json_str)
    except Exception:
        pass
    
    # Fallback: convert object attributes
    try:
        result = {}
        if hasattr(obj, '__dict__'):
            for key, value in obj.__dict__.items():
                # Recursively serialize nested objects
                if isinstance(value, (dict, list, str, int, float, bool, type(None))):
                    result[key] = value
                else:
                    # For nested objects, convert to string representation
                    result[key] = str(value)
        return result
    except Exception:
        # Last resort: convert to string
        return {"_object": str(obj), "_type": type(obj).__name__}

class BrokerType(Enum):
    COINBASE = "coinbase"
    BINANCE = "binance"
    KRAKEN = "kraken"
    OKX = "okx"
    INTERACTIVE_BROKERS = "interactive_brokers"
    TD_AMERITRADE = "td_ameritrade"
    ALPACA = "alpaca"
    TRADIER = "tradier"


class AccountType(Enum):
    """
    Account type for separating master (Nija system) from user accounts.
    
    MASTER: Nija master account that controls the system
    USER: Individual user/investor accounts
    """
    MASTER = "master"
    USER = "user"


class BaseBroker(ABC):
    """Base class for all broker integrations"""
    
    def __init__(self, broker_type: BrokerType, account_type: AccountType = AccountType.MASTER, user_id: Optional[str] = None):
        self.broker_type = broker_type
        self.account_type = account_type  # MASTER or USER account
        self.user_id = user_id  # User identifier for USER accounts (None for MASTER)
        self.connected = False
        self.credentials_configured = False  # Track if credentials were provided
        self.last_connection_error = None  # Track last connection error for troubleshooting
    
    @abstractmethod
    def connect(self) -> bool:
        """Establish connection to broker"""
        pass
    
    @abstractmethod
    def get_account_balance(self) -> float:
        """Get USD trading balance. Must be implemented by each broker."""
        pass
    
    @abstractmethod
    def get_positions(self) -> List[Dict]:
        """Get open positions. Must be implemented by each broker."""
        pass
    
    @abstractmethod
    def place_market_order(
        self, 
        symbol: str, 
        side: str, 
        quantity: float, 
        size_type: str = 'quote',
        ignore_balance: bool = False,
        ignore_min_trade: bool = False,
        force_liquidate: bool = False
    ) -> Dict:
        """
        Place market order. Must be implemented by each broker.
        
        Args:
            symbol: Trading symbol
            side: 'buy' or 'sell'
            quantity: Order size
            size_type: 'quote' (USD) or 'base' (crypto quantity)
            ignore_balance: Bypass balance validation (EMERGENCY ONLY)
            ignore_min_trade: Bypass minimum trade size validation (EMERGENCY ONLY)
            force_liquidate: Bypass ALL validation (EMERGENCY ONLY)
        """
        pass
    
    def close_position(self, symbol: str, base_size: Optional[float] = None, **kwargs) -> Dict:
        """Default implementation calls place_market_order. Brokers can override."""
        quantity = kwargs.get('quantity', base_size)
        side = kwargs.get('side', 'sell')
        size_type = kwargs.get('size_type', 'base')
        if quantity is None:
            raise ValueError("close_position requires a quantity or base_size")
        return self.place_market_order(symbol, side, quantity, size_type)
    
    def get_candles(self, symbol: str, timeframe: str, count: int) -> List[Dict]:
        """Get candle data. Optional method, brokers can override."""
        return []
    
    def get_current_price(self, symbol: str) -> float:
        """Get current price. Optional method, brokers can override."""
        return 0.0
    
    def get_total_capital(self, include_positions: bool = True) -> Dict:
        """
        Get total capital including both free balance and open position values.
        
        PRO MODE Feature: Default implementation for brokers that don't override.
        
        Args:
            include_positions: If True, includes position values in total capital (default True)
        
        Returns:
            dict: Capital breakdown with keys:
                - free_balance: Available USD/USDC for new trades
                - position_value: Total USD value of all open positions
                - total_capital: free_balance + position_value
                - positions: List of positions with values
                - position_count: Number of open positions
        """
        try:
            # Get free balance
            free_balance = self.get_account_balance()
            
            # Get positions and calculate their values
            positions = self.get_positions()
            position_value_total = 0.0
            position_details = []
            
            if include_positions:
                for pos in positions:
                    symbol = pos.get('symbol')
                    quantity = pos.get('quantity', 0)
                    
                    if not symbol or quantity <= 0:
                        continue
                    
                    # Get current price for position
                    try:
                        price = self.get_current_price(symbol)
                        if price > 0:
                            value = quantity * price
                            position_value_total += value
                            position_details.append({
                                'symbol': symbol,
                                'quantity': quantity,
                                'price': price,
                                'value': value
                            })
                    except Exception:
                        continue
            
            total_capital = free_balance + position_value_total
            
            return {
                'free_balance': free_balance,
                'position_value': position_value_total,
                'total_capital': total_capital,
                'positions': position_details,
                'position_count': len(position_details)
            }
            
        except Exception:
            return {
                'free_balance': 0.0,
                'position_value': 0.0,
                'total_capital': 0.0,
                'positions': [],
                'position_count': 0
            }
    
    def get_market_data(self, symbol: str, timeframe: str = '5m', limit: int = 100) -> Dict:
        """Get market data. Optional method, brokers can override."""
        candles = self.get_candles(symbol, timeframe, limit)
        return {'candles': candles}
    
    def supports_asset_class(self, asset_class: str) -> bool:
        """Check if broker supports asset class. Optional method, brokers can override."""
        return False
    
    def supports_symbol(self, symbol: str) -> bool:
        """
        Check if broker supports a given trading symbol.
        
        This is a critical safety check to prevent attempting trades on unsupported pairs.
        For example, Kraken doesn't support BUSD (Binance-only stablecoin).
        
        Args:
            symbol: Trading symbol to check (any format)
            
        Returns:
            bool: True if broker supports this symbol, False otherwise
            
        Default implementation: extracts quote currency and checks against known unsupported pairs.
        Brokers can override for more sophisticated checks (e.g., API-based validation).
        """
        if not symbol:
            return False
        
        symbol_upper = symbol.upper()
        broker_name = self.broker_type.value.lower()
        
        # Extract quote currency (USD, USDT, BUSD, etc.)
        quote = None
        if '-' in symbol_upper:
            quote = symbol_upper.split('-')[-1]
        elif '/' in symbol_upper:
            quote = symbol_upper.split('/')[-1]
        elif '.' in symbol_upper:
            quote = symbol_upper.split('.')[-1]
        else:
            # No separator - try to detect common patterns
            if symbol_upper.endswith('USDT'):
                quote = 'USDT'
            elif symbol_upper.endswith('BUSD'):
                quote = 'BUSD'
            elif symbol_upper.endswith('USDC'):
                quote = 'USDC'
            elif symbol_upper.endswith('USD'):
                quote = 'USD'
        
        if not quote:
            # Can't determine quote currency - assume supported
            return True
        
        # Broker-specific unsupported pairs
        unsupported = {
            'kraken': ['BUSD'],  # Kraken doesn't support Binance USD
            'coinbase': ['BUSD'],  # Coinbase doesn't support BUSD
            'okx': ['BUSD'],  # OKX doesn't support BUSD
            'alpaca': ['BUSD', 'USDT', 'USDC'],  # Alpaca is stocks/traditional assets
        }
        
        # Check if quote currency is unsupported for this broker
        if broker_name in unsupported:
            if quote in unsupported[broker_name]:
                logger.debug(f"⏭️ {broker_name.title()} doesn't support {quote} pairs (symbol: {symbol})")
                return False
        
        return True


# CRITICAL FIX (Jan 11, 2026): Invalid ProductID error detection
# Used by both logging filter and exception handler for consistency
def _is_invalid_product_error(error_message: str) -> bool:
    """
    Check if an error message indicates an invalid/delisted product.
    
    This function is used both for logging filter and exception handling to
    maintain consistency in how we detect invalid ProductID errors.
    
    Args:
        error_message: The error message to check (case-insensitive)
    
    Returns:
        True if the error indicates an invalid product, False otherwise
    """
    error_str = str(error_message).lower()
    
    # Check for various patterns that indicate invalid/delisted products
    has_invalid_keyword = 'invalid' in error_str and ('product' in error_str or 'symbol' in error_str)
    is_productid_invalid = 'productid is invalid' in error_str
    is_400_invalid_arg = '400' in error_str and 'invalid_argument' in error_str
    is_no_key_error = 'no key' in error_str and 'was found' in error_str
    
    return has_invalid_keyword or is_productid_invalid or is_400_invalid_arg or is_no_key_error


class _CoinbaseInvalidProductFilter(logging.Filter):
    """Filter to suppress Coinbase SDK errors for invalid/delisted products"""
    def filter(self, record):
        """
        Determine if a log record should be logged.
        
        Filters out ERROR-level logs from Coinbase SDK that contain
        invalid ProductID error messages, as these are expected errors
        that are already handled by exception handlers.
        
        Args:
            record: LogRecord instance to be filtered
        
        Returns:
            False if the record should be filtered out (invalid ProductID error),
            True if the record should be logged normally
        """
        # Only filter records from coinbase.RESTClient logger
        if not record.name.startswith('coinbase'):
            return True
        
        # Check if this is an invalid ProductID error using shared detection logic
        msg = record.getMessage()
        is_invalid_product = _is_invalid_product_error(msg)
        
        # Completely suppress ERROR logs for invalid products
        # Return False to prevent the log from being emitted at all
        if is_invalid_product and record.levelno >= logging.ERROR:
            return False  # Filter out completely
        
        # Let all other logs through
        return True


# Coinbase-specific broker implementation
class CoinbaseBroker(BaseBroker):
    """Coinbase Advanced Trade broker implementation"""
    
    def __init__(self, account_type: AccountType = AccountType.MASTER, user_id: Optional[str] = None):
        """Initialize Coinbase broker"""
        super().__init__(BrokerType.COINBASE, account_type=account_type, user_id=user_id)
        self.client = None
        self.portfolio_uuid = None
        self._product_cache = {}  # Cache for product metadata (tick sizes, increments)
        self._invalid_symbols_cache = set()  # Cache for known invalid/delisted symbols (CRITICAL FIX Jan 11, 2026)
        
        # Cache for account data to prevent redundant API calls during initialization
        # NOTE: These caches are only accessed during bot startup in the main thread,
        # before any trading threads are spawned. Thread safety is not a concern as
        # the cache TTL (120s) expires before multi-threaded trading begins.
        self._accounts_cache = None
        self._accounts_cache_time = None
        self._balance_cache = None
        self._balance_cache_time = None
        self._cache_ttl = 120  # Cache TTL in seconds (increased from 30s to 120s to reduce API calls and avoid rate limits)
        
        # Initialize rate limiter for API calls to prevent 403/429 errors
        # Coinbase has strict rate limits: ~10 req/s burst but much lower sustained rate
        # Using 12 requests per minute (1 every 5 seconds) for safe sustained operation
        if RateLimiter:
            self._rate_limiter = RateLimiter(
                default_per_min=12,  # 12 requests per minute = 1 request every 5 seconds
                per_key_overrides={
                    'get_candles': 8,   # Very conservative for candle fetching (7.5s between calls = 8 req/min)
                    'get_product': 15,  # Slightly faster for product queries (4s between calls)
                    'get_all_products': 5,  # Ultra conservative for bulk product fetching (12s between calls = 5 req/min)
                }
            )
            logger.info("✅ Rate limiter initialized (12 req/min default, 8 req/min for candles, 5 req/min for get_all_products)")
        else:
            self._rate_limiter = None
            logger.warning("⚠️ RateLimiter not available - using manual delays only")
        
        # Initialize position tracker for profit-based exits
        try:
            from position_tracker import PositionTracker
            self.position_tracker = PositionTracker(storage_file="positions.json")
            logger.info("✅ Position tracker initialized for profit-based exits")
        except Exception as e:
            logger.warning(f"⚠️ Position tracker initialization failed: {e}")
            self.position_tracker = None
        
        # Balance tracking for fail-closed behavior (Jan 19, 2026)
        # When balance fetch fails, preserve last known balance instead of returning 0
        self._last_known_balance = None  # Last successful balance fetch
        self._balance_fetch_errors = 0   # Count of consecutive errors
        self._is_available = True        # Broker availability flag
        
        # FIX 2: EXIT-ONLY mode when balance is below minimum (Jan 20, 2026)
        # Allows emergency sells even when account is too small for new entries
        self.exit_only_mode = False
        
        # CRITICAL FIX (Jan 11, 2026): Install logging filter to suppress invalid ProductID errors
        # The Coinbase SDK logs "ProductID is invalid" as ERROR before raising exceptions
        # These errors are expected (delisted coins) and already handled by our exception logic
        # This filter prevents log pollution while preserving our own error handling
        self._install_logging_filter()
    
    def _install_logging_filter(self):
        """Install logging filter to suppress Coinbase SDK invalid ProductID errors"""
        # NOTE: Unlike handlers, filters are NOT inherited by child loggers.
        # We must add the filter to both the parent and child loggers explicitly.
        # See: https://docs.python.org/3/library/logging.html#filter-objects
        
        # Apply filter to parent 'coinbase' logger
        coinbase_logger = logging.getLogger('coinbase')
        coinbase_logger.addFilter(_CoinbaseInvalidProductFilter())
        
        # Apply filter to 'coinbase.RESTClient' child logger (not inherited from parent)
        rest_logger = logging.getLogger('coinbase.RESTClient')
        rest_logger.addFilter(_CoinbaseInvalidProductFilter())
        
        logging.debug("✅ Coinbase SDK logging filter installed (suppresses invalid ProductID errors)")
    
    def _is_cache_valid(self, cache_time) -> bool:
        """
        Check if a cache entry is still valid based on its timestamp.
        
        Args:
            cache_time: Timestamp when cache was last updated (or None if never cached)
            
        Returns:
            True if cache is still valid, False otherwise
        """
        return cache_time is not None and (time.time() - cache_time) < self._cache_ttl
    
    def clear_cache(self):
        """
        Clear all cached data to force fresh API calls.
        
        This is useful when stale cached data needs to be refreshed,
        particularly for balance checking immediately after connection.
        """
        self._balance_cache = None
        self._balance_cache_time = None
        self._accounts_cache = None
        self._accounts_cache_time = None
        logger.debug("Cache cleared (balance and accounts)")
    
    def _api_call_with_retry(self, api_func, *args, max_retries=5, base_delay=5.0, **kwargs):
        """
        Execute an API call with exponential backoff retry logic for rate limiting and connection errors.
        
        Args:
            api_func: The API function to call
            *args: Positional arguments for the API function
            max_retries: Maximum number of retry attempts (default: 5)
            base_delay: Base delay in seconds for exponential backoff (default: 5.0)
            **kwargs: Keyword arguments for the API function
            
        Returns:
            The API response if successful
            
        Raises:
            Exception: If all retries are exhausted
        """
        for attempt in range(max_retries):
            try:
                return api_func(*args, **kwargs)
            except Exception as e:
                # Catch all exceptions to handle various API error types (HTTP errors, network errors, etc.)
                # This is intentionally broad to ensure all rate limiting and connection errors are caught
                error_msg = str(e).lower()
                
                # Check if this is a connection error (network issues, connection reset, etc.)
                is_connection_error = (
                    'connection' in error_msg or
                    'connectionreseterror' in error_msg or
                    'connection reset' in error_msg or
                    'connection aborted' in error_msg or
                    'timeout' in error_msg or
                    'timed out' in error_msg or
                    'network' in error_msg or
                    'unreachable' in error_msg or
                    'eof occurred' in error_msg or
                    'broken pipe' in error_msg
                )
                
                # Check if this is a rate limiting error (403, 429, or "too many" errors)
                # Use precise pattern matching to avoid false positives
                is_403_error = (
                    '403 ' in error_msg or ' 403' in error_msg or
                    'forbidden' in error_msg or
                    'too many errors' in error_msg or
                    'too many' in error_msg  # Coinbase sometimes returns "too many" without "errors"
                )
                is_429_error = (
                    '429 ' in error_msg or ' 429' in error_msg or
                    'rate limit' in error_msg or
                    'too many requests' in error_msg
                )
                is_rate_limit = is_403_error or is_429_error
                
                # Determine if error is retryable
                is_retryable = is_rate_limit or is_connection_error
                
                # If this is the last attempt or not a retryable error, raise
                if attempt >= max_retries - 1 or not is_retryable:
                    raise
                
                # Calculate exponential backoff delay with maximum cap
                # For connection errors, use moderate delays
                # For 403 errors, use longer delays (more aggressive backoff)
                if is_connection_error:
                    delay = min(base_delay * (1.5 ** attempt), 30.0)  # 5s, 7.5s, 11.25s, 16.88s, 25.31s (capped at 30s)
                    error_type = "Connection error"
                elif is_403_error:
                    delay = min(base_delay * (3 ** attempt), 120.0)  # 5s, 15s, 45s, 120s (capped), 120s (capped)
                    error_type = "Rate limit (403)"
                else:
                    delay = min(base_delay * (2 ** attempt), 60.0)  # 5s, 10s, 20s, 40s, 60s (capped)
                    error_type = "Rate limit (429)"
                
                logging.warning(f"⚠️  API {error_type} (attempt {attempt + 1}/{max_retries}): {e}")
                logging.warning(f"   Waiting {delay:.1f}s before retry...")
                time.sleep(delay)
    
    def _log_trade_to_journal(self, symbol: str, side: str, price: float,
                               size_usd: float, quantity: float, pnl_data: dict = None):
        """
        Log trade to trade_journal.jsonl with P&L tracking.
        
        Args:
            symbol: Trading symbol
            side: 'BUY' or 'SELL'
            price: Execution price
            size_usd: Trade size in USD
            quantity: Crypto quantity
            pnl_data: Optional P&L data for SELL orders (from position_tracker.calculate_pnl)
        """
        try:
            from datetime import datetime
            
            trade_entry = {
                "timestamp": datetime.now().isoformat(),
                "symbol": symbol,
                "side": side,
                "price": price,
                "size_usd": size_usd,
                "quantity": quantity
            }
            
            # Add P&L data for SELL orders
            if pnl_data and side == 'SELL':
                trade_entry["entry_price"] = pnl_data.get('entry_price', 0)
                trade_entry["pnl_dollars"] = pnl_data.get('pnl_dollars', 0)
                trade_entry["pnl_percent"] = pnl_data.get('pnl_percent', 0)
                trade_entry["entry_value"] = pnl_data.get('entry_value', 0)
            
            # Append to trade journal file
            journal_file = "trade_journal.jsonl"
            with open(journal_file, 'a') as f:
                f.write(json.dumps(trade_entry) + '\n')
            
            logger.debug(f"Trade logged to journal: {symbol} {side} @ ${price:.2f}")
        except Exception as e:
            logger.warning(f"Failed to log trade to journal: {e}")
    
    def connect(self) -> bool:
        """Connect to Coinbase Advanced Trade API with retry logic"""
        try:
            from coinbase.rest import RESTClient
            import os
            import time
            
            # Get credentials from environment
            api_key = os.getenv("COINBASE_API_KEY")
            api_secret = os.getenv("COINBASE_API_SECRET")
            
            if not api_key or not api_secret:
                logging.error("❌ Coinbase API credentials not found")
                return False
            
            # Initialize REST client
            self.client = RESTClient(api_key=api_key, api_secret=api_secret)
            
            # Test connection by fetching accounts with retry logic
            # Increased max attempts for 403 "too many errors" which indicates temporary API key blocking
            # Note: 403 differs from 429 (rate limiting) - it means the API key was temporarily blocked
            max_attempts = 10  # Increased from 6 to give more chances for API to recover from rate limits
            
            for attempt in range(1, max_attempts + 1):
                try:
                    accounts_resp = self.client.get_accounts()
                    
                    # Cache accounts response to avoid redundant API calls during initialization
                    self._accounts_cache = accounts_resp
                    self._accounts_cache_time = time.time()
                    
                    self.connected = True
                    
                    if attempt > 1:
                        logging.info(f"✅ Connected to Coinbase Advanced Trade API (succeeded on attempt {attempt})")
                    else:
                        logging.info("✅ Connected to Coinbase Advanced Trade API")
                    
                    # Portfolio detection (will use cached accounts)
                    self._detect_portfolio()
                    
                    # 🚑 FIX 2: DISABLE COINBASE FOR SMALL ACCOUNTS
                    # If total equity < $75, disable Coinbase and route to Kraken
                    # This prevents Coinbase fees from eating small accounts
                    try:
                        balance_data = self._get_account_balance_detailed()
                        if balance_data is None:
                            # Balance fetch failed - this is critical for small account check
                            # We MUST know account size before allowing connection
                            logging.error("=" * 70)
                            logging.error("⚠️  COINBASE CONNECTION BLOCKED")
                            logging.error("=" * 70)
                            logging.error("   Could not verify account balance")
                            logging.error("   This check prevents small accounts from using Coinbase")
                            logging.error("   ")
                            logging.error("   Possible causes:")
                            logging.error("   1. API permission issues")
                            logging.error("   2. Network connectivity problems")
                            logging.error("   3. Coinbase API temporarily unavailable")
                            logging.error("   ")
                            logging.error("   Solution: Fix API connectivity first")
                            logging.error("=" * 70)
                            self.connected = False
                            return False
                        
                        total_funds = balance_data.get('total_funds', 0.0)
                        
                        # FIX 2: FORCED EXIT OVERRIDES - Allow connection even when balance < minimum
                        # This enables emergency sells to close losing positions
                        # Only NEW ENTRIES are blocked, not EXITS
                        if total_funds < COINBASE_MINIMUM_BALANCE:
                            logging.warning("=" * 70)
                            logging.warning("⚠️ COINBASE: Account balance below minimum for NEW ENTRIES")
                            logging.warning("=" * 70)
                            logging.warning(f"   Your balance: ${total_funds:.2f}")
                            logging.warning(f"   Minimum for entries: ${COINBASE_MINIMUM_BALANCE:.2f}")
                            logging.warning(f"   ")
                            logging.warning(f"   📋 Trading Mode: EXIT-ONLY")
                            logging.warning(f"      ✅ Can SELL (close positions)")
                            logging.warning(f"      ❌ Cannot BUY (new entries blocked)")
                            logging.warning(f"   ")
                            logging.warning(f"   💡 Solution: Use Kraken for new entries")
                            logging.warning(f"      Kraken has 4x lower fees and is optimized for small accounts")
                            logging.warning(f"   ")
                            logging.warning(f"   ✅ Coinbase connection maintained for emergency exits")
                            logging.warning("=" * 70)
                            
                            # Mark as EXIT-ONLY mode (not fully disabled)
                            self.exit_only_mode = True
                            # Keep connected = True so sells can execute
                            self.connected = True
                            return True
                    except Exception as balance_check_err:
                        # Balance check failed - this is CRITICAL, do NOT allow connection
                        # We cannot safely determine if account is too small
                        logging.error("=" * 70)
                        logging.error("⚠️  COINBASE CONNECTION BLOCKED")
                        logging.error("=" * 70)
                        logging.error(f"   Balance check failed: {balance_check_err}")
                        logging.error("   Cannot verify account size - blocking Coinbase connection")
                        logging.error("   ")
                        logging.error("   This safety check prevents small accounts from using Coinbase.")
                        logging.error("   Fix the balance check error before allowing Coinbase connection.")
                        logging.error("=" * 70)
                        self.connected = False
                        return False
                    
                    return True
                    
                except Exception as e:
                    error_msg = str(e)
                    error_msg_lower = error_msg.lower()
                    
                    # Distinguish between 403 (API key temporarily blocked) and 429 (rate limit quota)
                    is_403_forbidden = (
                        '403' in error_msg_lower or 
                        'forbidden' in error_msg_lower or 
                        'too many errors' in error_msg_lower
                    )
                    is_429_rate_limit = (
                        '429' in error_msg_lower or 
                        'rate limit' in error_msg_lower or 
                        'too many requests' in error_msg_lower
                    )
                    is_network_error = any(keyword in error_msg_lower for keyword in [
                        'timeout', 'connection', 'network', 'service unavailable',
                        '503', '504', 'temporary', 'try again'
                    ])
                    
                    is_retryable = is_403_forbidden or is_429_rate_limit or is_network_error
                    
                    if is_retryable and attempt < max_attempts:
                        # Use different delays based on error type
                        if is_403_forbidden:
                            # 403 errors: API key temporarily blocked - use LONG fixed delay with jitter
                            # This prevents rapid retries that make the block worse
                            delay = FORBIDDEN_BASE_DELAY + random.uniform(0, FORBIDDEN_JITTER_MAX)
                            logging.warning(f"⚠️  Connection attempt {attempt}/{max_attempts} failed (retryable): {error_msg}")
                            logging.warning(f"   API key temporarily blocked - waiting {delay:.1f}s before retry...")
                        elif is_429_rate_limit:
                            # 429 errors: Rate limit quota - use exponential backoff
                            delay = min(RATE_LIMIT_BASE_DELAY * (2 ** (attempt - 1)), 120.0)
                            logging.warning(f"⚠️  Connection attempt {attempt}/{max_attempts} failed (retryable): {error_msg}")
                            logging.warning(f"   Rate limit exceeded - waiting {delay:.1f}s before retry...")
                        else:
                            # Network errors: Moderate exponential backoff
                            delay = min(10.0 * (2 ** (attempt - 1)), 60.0)
                            logging.warning(f"⚠️  Connection attempt {attempt}/{max_attempts} failed (retryable): {error_msg}")
                            logging.warning(f"   Network error - waiting {delay:.1f}s before retry...")
                        
                        logging.info(f"🔄 Retrying connection in {delay:.1f}s (attempt {attempt + 1}/{max_attempts})...")
                        time.sleep(delay)
                        continue
                    else:
                        logging.error(f"❌ Failed to verify Coinbase connection: {e}")
                        return False
            
            # Should never reach here, but just in case
            logging.error("❌ Failed to connect after maximum retry attempts")
            return False
                
        except ImportError:
            logging.error("❌ Coinbase SDK not installed. Run: pip install coinbase-advanced-py")
            return False
        except Exception as e:
            logging.error(f"❌ Coinbase connection error: {e}")
            return False
    
    def _detect_portfolio(self):
        """DISABLED: Always use default Advanced Trade portfolio"""
        try:
            # CRITICAL FIX: Do NOT auto-detect portfolio
            # The Coinbase Advanced Trade API can ONLY trade from the default trading portfolio
            # Consumer wallets (even if they show up in accounts list) CANNOT be used for trading
            # The SDK's market_order_buy() always routes to the default portfolio
            
            logging.info("=" * 70)
            logging.info("🎯 PORTFOLIO ROUTING: DEFAULT ADVANCED TRADE")
            logging.info("=" * 70)
            logging.info("   Using default Advanced Trade portfolio (SDK default)")
            logging.info("   Consumer wallets are NOT accessible for trading")
            logging.info("   Transfer funds via: https://www.coinbase.com/advanced-portfolio")
            logging.info("=" * 70)
            
            # Do NOT set portfolio_uuid - let SDK use default
            self.portfolio_uuid = None
            
            # Use cached accounts if available to avoid redundant API calls
            try:
                if self._accounts_cache and self._is_cache_valid(self._accounts_cache_time):
                    # Use cached response
                    accounts_resp = self._accounts_cache
                    logging.debug("Using cached accounts data from connect()")
                else:
                    # Cache expired or not available, fetch fresh
                    accounts_resp = self.client.get_accounts() if hasattr(self.client, 'get_accounts') else self.client.list_accounts()
                    self._accounts_cache = accounts_resp
                    self._accounts_cache_time = time.time()
                
                accounts = getattr(accounts_resp, 'accounts', [])
                
                logging.info("📊 ACCOUNT BALANCES (for information only):")
                logging.info("-" * 70)
                
                for account in accounts:
                    currency = getattr(account, 'currency', None)
                    available_obj = getattr(account, 'available_balance', None)
                    available = float(getattr(available_obj, 'value', 0) or 0)
                    account_name = getattr(account, 'name', 'Unknown')
                    account_type = getattr(account, 'type', 'Unknown')
                    
                    if currency in ['USD', 'USDC'] and available > 0:
                        tradeable = "✅ TRADEABLE" if account_type == "ACCOUNT_TYPE_CRYPTO" else "❌ NOT TRADEABLE (Consumer)"
                        logging.info(f"   {currency}: ${available:.2f} | {account_name} | {tradeable}")
                
                logging.info("=" * 70)
                    
            except Exception as e:
                logging.warning(f"⚠️  Portfolio detection failed: {e}")
                logging.info("   Will use default portfolio routing")
                
        except Exception as e:
            logging.error(f"❌ Portfolio detection error: {e}")
    
    def _is_account_tradeable(self, account_type: str, platform: str) -> bool:
        """
        IMPROVEMENT #3: Expanded account type matching patterns.
        Checks multiple patterns to identify tradeable accounts.
        
        Args:
            account_type: Type string from API (e.g., "ACCOUNT_TYPE_CRYPTO")
            platform: Platform string from API (e.g., "ADVANCED_TRADE")
            
        Returns:
            True if account is tradeable via Advanced Trade API
        """
        if not account_type:
            return False
            
        account_type_str = str(account_type).upper()
        platform_str = str(platform or "").upper()
        
        # Pattern 1: Explicit ACCOUNT_TYPE_CRYPTO
        if account_type_str == "ACCOUNT_TYPE_CRYPTO":
            return True
        
        # Pattern 2: Advanced Trade platform designation
        if "ADVANCED_TRADE" in platform_str or "ADVANCED" in platform_str:
            return True
        
        # Pattern 3: Trading portfolio indicators
        if "TRADING" in platform_str or "TRADING_PORTFOLIO" in account_type_str:
            return True
        
        # Pattern 4: Not explicitly a consumer/vault account
        if "CONSUMER" not in account_type_str and "VAULT" not in account_type_str and "WALLET" not in account_type_str:
            # If platform is not explicitly consumer, assume tradeable
            if platform_str and "ADVANCED" in platform_str:
                return True
        
        return False

    def get_all_products(self) -> list:
        """
        Fetch ALL available products (cryptocurrency pairs) from Coinbase.
        Handles pagination to retrieve 700+ markets without timeouts.
        Uses rate limiting and retry logic to prevent 403/429 errors.
        
        Returns:
            List of product IDs (e.g., ['BTC-USD', 'ETH-USD', ...])
        """
        try:
            logging.info("📡 Fetching all products from Coinbase API (700+ markets)...")
            all_products = []
            
            # Get products with pagination
            if hasattr(self.client, 'get_products'):
                # CRITICAL FIX: Add retry logic for 403/429 rate limit errors
                # The Coinbase SDK's get_all_products=True can trigger rate limits
                # We need to retry with exponential backoff to handle temporary blocks
                max_retries = RATE_LIMIT_MAX_RETRIES
                retry_count = 0
                products_resp = None
                
                while retry_count <= max_retries:
                    try:
                        # CRITICAL FIX: Wrap get_products() call with rate limiting
                        # The Coinbase SDK's get_all_products=True internally makes multiple paginated
                        # requests rapidly, which can exhaust rate limits before market scanning begins
                        # Using rate limiter with retry logic to prevent 403 "Forbidden" errors
                        
                        def _fetch_products():
                            """Inner function for rate-limited product fetching"""
                            return self.client.get_products(get_all_products=True)
                        
                        # Apply rate limiting if available
                        if self._rate_limiter:
                            # Rate-limited call - enforces minimum interval between requests
                            products_resp = self._rate_limiter.call('get_all_products', _fetch_products)
                        else:
                            # Fallback to direct call without rate limiting
                            products_resp = _fetch_products()
                        
                        # Success! Break out of retry loop
                        break
                        
                    except Exception as fetch_err:
                        error_str = str(fetch_err)
                        
                        # Check if it's a rate limit error (403 or 429)
                        is_rate_limit = '429' in error_str or 'rate limit' in error_str.lower()
                        is_forbidden = '403' in error_str or 'forbidden' in error_str.lower() or 'too many' in error_str.lower()
                        
                        if (is_rate_limit or is_forbidden) and retry_count < max_retries:
                            retry_count += 1
                            
                            # Calculate backoff delay
                            if is_forbidden:
                                # 403 errors: Use fixed delay with jitter (API key temporarily blocked)
                                delay = FORBIDDEN_BASE_DELAY + random.uniform(0, FORBIDDEN_JITTER_MAX)
                                logging.warning(f"⚠️  Rate limit (403 Forbidden): API key temporarily blocked on get_all_products, waiting {delay:.1f}s before retry {retry_count}/{max_retries}")
                            else:
                                # 429 errors: Use exponential backoff
                                delay = RATE_LIMIT_BASE_DELAY * (2 ** (retry_count - 1))
                                logging.warning(f"⚠️  Rate limit (429 Too Many Requests): Quota exceeded on get_all_products, waiting {delay:.1f}s before retry {retry_count}/{max_retries}")
                            
                            time.sleep(delay)
                            continue
                        else:
                            # Not a rate limit error or max retries reached
                            raise fetch_err
                
                # Check if we successfully fetched products
                if not products_resp:
                    logging.error("⚠️  Failed to fetch products after retries")
                    return FALLBACK_MARKETS
                    
                # Log response type and structure
                logging.info(f"   Response type: {type(products_resp).__name__}")
                
                # Handle both object and dict responses
                if hasattr(products_resp, 'products'):
                    products = products_resp.products
                    logging.info(f"   Extracted {len(products) if products else 0} products from .products attribute")
                elif isinstance(products_resp, dict):
                    products = products_resp.get('products', [])
                    logging.info(f"   Extracted {len(products)} products from dict['products']")
                else:
                    products = []
                    logging.warning(f"⚠️  Unexpected response type: {type(products_resp).__name__}")
                
                if not products:
                    logging.warning("⚠️  No products returned from API - response may be empty or malformed")
                    # Debug: Show what attributes/keys are available
                    if hasattr(products_resp, '__dict__'):
                        attrs = [k for k in dir(products_resp) if not k.startswith('_')][:10]
                        logging.info(f"   Available attributes: {attrs}")
                    elif isinstance(products_resp, dict):
                        logging.info(f"   Available keys: {list(products_resp.keys())}")
                    return []
                
                # Extract product IDs - handle various response formats
                # CRITICAL FIX (Jan 10, 2026): Add status filtering to exclude delisted/disabled products
                # This prevents invalid symbols (e.g., 2Z-USD, AGLD-USD, HIO, BOE) from causing API errors
                filtered_count = 0
                filtered_products_count = 0  # Tracks all filtered products (status, disabled, format)
                DEBUG_LOG_LIMIT = 5  # Maximum number of filtered products to log at debug level
                
                for i, product in enumerate(products):
                    product_id = None
                    status = None
                    trading_disabled = False
                    
                    # Debug first product to understand structure
                    if i == 0:
                        if hasattr(product, '__dict__'):
                            attrs = [k for k in dir(product) if not k.startswith('_')][:10]
                            logging.info(f"   First product attributes: {attrs}")
                        elif isinstance(product, dict):
                            logging.info(f"   First product keys: {list(product.keys())[:10]}")
                    
                    # Try object attribute access (Coinbase uses 'product_id', not 'id')
                    if hasattr(product, 'product_id'):
                        product_id = getattr(product, 'product_id', None)
                        status = getattr(product, 'status', None)
                        trading_disabled = getattr(product, 'trading_disabled', False)
                    elif hasattr(product, 'id'):
                        product_id = getattr(product, 'id', None)
                        status = getattr(product, 'status', None)
                        trading_disabled = getattr(product, 'trading_disabled', False)
                    # Try dict access
                    elif isinstance(product, dict):
                        product_id = product.get('product_id') or product.get('id')
                        status = product.get('status')
                        trading_disabled = product.get('trading_disabled', False)
                    
                    # CRITICAL FILTERS to prevent invalid symbol errors:
                    # 1. Must have product_id
                    if not product_id:
                        continue
                    
                    # 2. Must be USD or USDC pair
                    if not (product_id.endswith('-USD') or product_id.endswith('-USDC')):
                        continue
                    
                    # 3. Status must be 'online' (exclude offline, delisted, etc.)
                    # This is the KEY fix - prevents delisted coins from being scanned
                    if not status or status.lower() != 'online':
                        filtered_products_count += 1
                        if filtered_products_count <= DEBUG_LOG_LIMIT:  # Log first 5 for debugging
                            logging.debug(f"   Filtered out {product_id}: status={status}")
                        continue
                    
                    # 4. Trading must not be disabled
                    if trading_disabled:
                        filtered_products_count += 1
                        if filtered_products_count <= DEBUG_LOG_LIMIT:
                            logging.debug(f"   Filtered out {product_id}: trading_disabled=True")
                        continue
                    
                    # 5. Validate symbol format (basic sanity check)
                    # Valid format: 2-8 chars, dash, USD/USDC
                    parts = product_id.split('-')
                    if len(parts) != 2 or len(parts[0]) < 2 or len(parts[0]) > 8:
                        filtered_products_count += 1
                        if filtered_products_count <= DEBUG_LOG_LIMIT:
                            logging.debug(f"   Filtered out {product_id}: invalid format (length)")
                        continue
                    
                    # Passed all filters - add to list
                    all_products.append(product_id)
                
                if filtered_products_count > 0:
                    logging.info(f"   Filtered out {filtered_products_count} products (offline/delisted/disabled/invalid format)")
                
                logging.info(f"   Fetched {len(products)} total products, {len(all_products)} USD/USDC pairs after filtering")
                
                # Remove duplicates and sort
                all_products = sorted(list(set(all_products)))
                
                logging.info(f"✅ Successfully fetched {len(all_products)} USD/USDC trading pairs from Coinbase API")
                if all_products:
                    logging.info(f"   Sample markets: {', '.join(all_products[:10])}")
                
                # CRITICAL FIX (Jan 10, 2026): Add cooldown after get_all_products to prevent burst
                # This gives the API time to reset before we start scanning markets
                logging.info("   💤 Cooling down for 10s after bulk product fetch to prevent rate limiting...")
                time.sleep(10.0)
                
                return all_products
            
            # Fallback: Use curated list of popular crypto markets
            logging.warning("⚠️  Could not fetch products from API, using fallback list of popular markets")
            logging.info(f"   Using {len(FALLBACK_MARKETS)} fallback markets")
            return FALLBACK_MARKETS
            
        except Exception as e:
            logging.error(f"🔥 Error fetching all products: {e}")
            return []

    def _get_account_balance_detailed(self):
        """Return ONLY tradable Advanced Trade USD/USDC balances (detailed version).

        Coinbase frequently shows Consumer wallet balances that **cannot** be used
        for Advanced Trade orders. To avoid false positives (and endless
        INSUFFICIENT_FUND rejections), we enumerate accounts and only count
        ones marked as Advanced Trade / crypto accounts.
        
        IMPROVEMENTS:
        1. Better consumer wallet diagnostics - tells user to transfer funds
        2. API permission validation - checks if we can see accounts
        3. Expanded account type matching - handles more Coinbase account types
        4. Caching - reuses accounts data from connect() to avoid redundant API calls

        Returns dict with: {"usdc", "usd", "trading_balance", "crypto", "consumer_*"}
        """
        # Check if we have a cached balance (during initialization only)
        if self._balance_cache and self._is_cache_valid(self._balance_cache_time):
            logging.debug("Using cached balance data")
            return self._balance_cache
        
        usd_balance = 0.0
        usdc_balance = 0.0
        usd_held = 0.0  # Track held funds (in open orders/positions)
        usdc_held = 0.0
        consumer_usd = 0.0
        consumer_usdc = 0.0
        crypto_holdings = {}
        accounts_seen = 0
        tradeable_accounts = 0

        # Preferred path: portfolio breakdown (more reliable than get_accounts)
        try:
            logging.info("💰 Fetching account balance via portfolio breakdown (preferred)...")
            
            # Use retry logic for portfolio API calls to handle rate limiting
            portfolios_resp = None
            if hasattr(self.client, 'get_portfolios'):
                portfolios_resp = self._api_call_with_retry(self.client.get_portfolios)
            
            portfolios = getattr(portfolios_resp, 'portfolios', [])
            if isinstance(portfolios_resp, dict):
                portfolios = portfolios_resp.get('portfolios', [])

            default_portfolio = None
            for pf in portfolios:
                pf_type = getattr(pf, 'type', None) if not isinstance(pf, dict) else pf.get('type')
                if str(pf_type).upper() == 'DEFAULT':
                    default_portfolio = pf
                    break
            if not default_portfolio and portfolios:
                default_portfolio = portfolios[0]

            portfolio_uuid = None
            if default_portfolio:
                portfolio_uuid = getattr(default_portfolio, 'uuid', None)
                if isinstance(default_portfolio, dict):
                    portfolio_uuid = default_portfolio.get('uuid', portfolio_uuid)

            if default_portfolio and portfolio_uuid:
                # Use retry logic for portfolio breakdown API call
                breakdown_resp = self._api_call_with_retry(
                    self.client.get_portfolio_breakdown,
                    portfolio_uuid=portfolio_uuid
                )
                breakdown = getattr(breakdown_resp, 'breakdown', None)
                if isinstance(breakdown_resp, dict):
                    breakdown = breakdown_resp.get('breakdown', breakdown)

                spot_positions = getattr(breakdown, 'spot_positions', []) if breakdown else []
                if isinstance(breakdown, dict):
                    spot_positions = breakdown.get('spot_positions', spot_positions)

                for pos in spot_positions:
                    asset = getattr(pos, 'asset', None) if not isinstance(pos, dict) else pos.get('asset')
                    available_val = getattr(pos, 'available_to_trade_fiat', None) if not isinstance(pos, dict) else pos.get('available_to_trade_fiat')
                    # Try to get held amount if available in the response
                    held_val = getattr(pos, 'hold_fiat', None) if not isinstance(pos, dict) else pos.get('hold_fiat')
                    
                    try:
                        available = float(available_val or 0)
                    except Exception:
                        available = 0.0
                    
                    try:
                        held = float(held_val or 0)
                    except Exception:
                        held = 0.0

                    if asset == 'USD':
                        usd_balance += available
                        usd_held += held
                    elif asset == 'USDC':
                        usdc_balance += available
                        usdc_held += held
                    elif asset:
                        crypto_holdings[asset] = crypto_holdings.get(asset, 0.0) + available

                trading_balance = usd_balance + usdc_balance
                total_held = usd_held + usdc_held
                total_funds = trading_balance + total_held
                
                logging.info("-" * 70)
                logging.info(f"   💰 Available USD (portfolio):  ${usd_balance:.2f}")
                logging.info(f"   💰 Available USDC (portfolio): ${usdc_balance:.2f}")
                logging.info(f"   💰 Total Available: ${trading_balance:.2f}")
                if total_held > 0:
                    logging.info(f"   🔒 Held USD:  ${usd_held:.2f} (in open orders/positions)")
                    logging.info(f"   🔒 Held USDC: ${usdc_held:.2f} (in open orders/positions)")
                    logging.info(f"   🔒 Total Held: ${total_held:.2f}")
                    logging.info(f"   💎 TOTAL FUNDS (Available + Held): ${total_funds:.2f}")
                logging.info("   (Source: get_portfolio_breakdown)")
                logging.info("-" * 70)

                result = {
                    "usdc": usdc_balance,
                    "usd": usd_balance,
                    "trading_balance": trading_balance,
                    "usd_held": usd_held,
                    "usdc_held": usdc_held,
                    "total_held": total_held,
                    "total_funds": total_funds,
                    "crypto": crypto_holdings,
                    "consumer_usd": consumer_usd,
                    "consumer_usdc": consumer_usdc,
                }
                
                # Cache the result
                self._balance_cache = result
                self._balance_cache_time = time.time()
                
                return result
            else:
                logging.warning("⚠️  No default portfolio found; falling back to get_accounts()")
        except Exception as e:
            # Format connection errors more clearly for better readability
            error_msg = str(e)
            if 'ConnectionResetError' in error_msg or 'Connection reset' in error_msg:
                logging.warning("⚠️  Portfolio breakdown failed: Network connection reset by Coinbase API")
                logging.warning("   Falling back to get_accounts() method...")
            elif 'Connection aborted' in error_msg or 'ConnectionAbortedError' in error_msg:
                logging.warning("⚠️  Portfolio breakdown failed: Network connection aborted")
                logging.warning("   Falling back to get_accounts() method...")
            elif 'timeout' in error_msg.lower() or 'timed out' in error_msg.lower():
                logging.warning("⚠️  Portfolio breakdown failed: API request timed out")
                logging.warning("   Falling back to get_accounts() method...")
            else:
                logging.warning(f"⚠️  Portfolio breakdown failed, falling back to get_accounts(): {error_msg}")

        try:
            logging.info("💰 Fetching account balance (Advanced Trade only)...")

            # Use cached accounts if available to avoid redundant API calls
            if self._accounts_cache and self._is_cache_valid(self._accounts_cache_time):
                logging.debug("Using cached accounts data")
                resp = self._accounts_cache
            else:
                # Use retry logic for get_accounts API call to handle rate limiting
                resp = self._api_call_with_retry(self.client.get_accounts)
                self._accounts_cache = resp
                self._accounts_cache_time = time.time()
            
            accounts = getattr(resp, 'accounts', []) or (resp.get('accounts', []) if isinstance(resp, dict) else [])

            # IMPROVEMENT #2: Validate API permissions
            if not accounts:
                logging.warning("=" * 70)
                logging.warning("⚠️  API PERMISSION CHECK: Zero accounts returned")
                logging.warning("=" * 70)
                logging.warning("This usually means:")
                logging.warning("  1. ❌ API key lacks 'View account details' permission")
                logging.warning("  2. ❌ No Advanced Trade portfolio created yet")
                logging.warning("  3. ❌ Wrong API credentials for this account")
                logging.warning("")
                logging.warning("FIX:")
                logging.warning("  1. Go to: https://portal.cloud.coinbase.com/access/api")
                logging.warning("  2. Edit your API key → Enable 'View' permission")
                logging.warning("  3. Or create portfolio: https://www.coinbase.com/advanced-portfolio")
                logging.warning("=" * 70)

            logging.info("=" * 70)
            logging.info("📊 ACCOUNT BALANCES (v3 get_accounts)")
            logging.info(f"📁 Total accounts returned: {len(accounts)}")
            logging.info("=" * 70)

            for acc in accounts:
                accounts_seen += 1
                # Normalize object/dict access
                if isinstance(acc, dict):
                    currency = acc.get('currency')
                    name = acc.get('name')
                    platform = acc.get('platform')
                    account_type = acc.get('type')
                    available_val = (acc.get('available_balance') or {}).get('value')
                    hold_val = (acc.get('hold') or {}).get('value')
                else:
                    currency = getattr(acc, 'currency', None)
                    name = getattr(acc, 'name', None)
                    platform = getattr(acc, 'platform', None)
                    account_type = getattr(acc, 'type', None)
                    available_val = getattr(getattr(acc, 'available_balance', None), 'value', None)
                    hold_val = getattr(getattr(acc, 'hold', None), 'value', None)

                try:
                    available = float(available_val or 0)
                    hold = float(hold_val or 0)
                except Exception:
                    available = 0.0
                    hold = 0.0

                # IMPROVEMENT #3: Use expanded matching function
                is_tradeable = self._is_account_tradeable(account_type, platform)
                if is_tradeable:
                    tradeable_accounts += 1

                if currency in ("USD", "USDC"):
                    location = "✅ TRADEABLE" if is_tradeable else "❌ CONSUMER"
                    logging.info(
                        f"   {currency:>4} | avail=${available:8.2f} | hold=${hold:8.2f} | type={account_type} | platform={platform} | {location}"
                    )

                    if is_tradeable:
                        if currency == "USD":
                            usd_balance += available
                            usd_held += hold  # Track held funds
                        else:
                            usdc_balance += available
                            usdc_held += hold  # Track held funds
                    else:
                        # IMPROVEMENT #1: Better consumer wallet diagnostics
                        if currency == "USD":
                            consumer_usd += available
                        else:
                            consumer_usdc += available
                elif currency and available > 0:
                    # Track non-cash crypto holdings ONLY if tradeable via API
                    # Consumer wallet positions cannot be traded and will cause INSUFFICIENT_FUND errors
                    if is_tradeable:
                        crypto_holdings[currency] = available
                        logging.info(
                            f"   ✅ 🪙 {currency}: {available} (type={account_type}, platform={platform})"
                        )
                    else:
                        # Log consumer wallet holdings separately but don't add to crypto_holdings
                        logging.info(
                            f"   ⏭️  {currency}: {available} in CONSUMER wallet (not API-tradeable, skipping)"
                        )

            trading_balance = usd_balance + usdc_balance
            total_held = usd_held + usdc_held
            total_funds = trading_balance + total_held

            logging.info("-" * 70)
            logging.info(f"   💰 Available USD:  ${usd_balance:.2f}")
            logging.info(f"   💰 Available USDC: ${usdc_balance:.2f}")
            logging.info(f"   💰 Total Available: ${trading_balance:.2f}")
            if total_held > 0:
                logging.info(f"   🔒 Held USD:  ${usd_held:.2f} (in open orders/positions)")
                logging.info(f"   🔒 Held USDC: ${usdc_held:.2f} (in open orders/positions)")
                logging.info(f"   🔒 Total Held: ${total_held:.2f}")
                logging.info(f"   💎 TOTAL FUNDS (Available + Held): ${total_funds:.2f}")
            logging.info(f"   🪙 Crypto Holdings: {len(crypto_holdings)} assets")
            
            # IMPROVEMENT #1: Enhanced consumer wallet detection and diagnosis
            if consumer_usd > 0 or consumer_usdc > 0:
                logging.warning("-" * 70)
                logging.warning("⚠️  CONSUMER WALLET DETECTED:")
                logging.warning(f"   🏦 Consumer USD:  ${consumer_usd:.2f}")
                logging.warning(f"   🏦 Consumer USDC: ${consumer_usdc:.2f}")
                logging.warning("")
                logging.warning("These funds are in your Coinbase Consumer wallet and")
                logging.warning("CANNOT be used for Advanced Trade API orders.")
                logging.warning("")
                logging.warning("TO FIX:")
                logging.warning("  1. Go to: https://www.coinbase.com/advanced-portfolio")
                logging.warning("  2. Click 'Deposit' on the Advanced Trade portfolio")
                logging.warning(f"  3. Transfer ${consumer_usd + consumer_usdc:.2f} from Consumer wallet")
                logging.warning("")
                logging.warning("After transfer, bot will see funds and start trading! ✅")
                logging.warning("-" * 70)
            
            logging.info(f"📊 API Status: Saw {accounts_seen} accounts, {tradeable_accounts} tradeable")
            logging.info(f"   💎 Tradeable crypto holdings: {len(crypto_holdings)} assets")
            logging.info("=" * 70)

            result = {
                "usdc": usdc_balance,
                "usd": usd_balance,
                "trading_balance": trading_balance,
                "usd_held": usd_held,
                "usdc_held": usdc_held,
                "total_held": total_held,
                "total_funds": total_funds,
                "crypto": crypto_holdings,
                "consumer_usd": consumer_usd,
                "consumer_usdc": consumer_usdc,
            }
            
            # Cache the result
            self._balance_cache = result
            self._balance_cache_time = time.time()
            
            return result
        except Exception as e:
            logging.error(f"🔥 ERROR get_account_balance: {e}")
            logging.error("This usually indicates:")
            logging.error("  1. Invalid API credentials")
            logging.error("  2. Network connectivity issue")
            logging.error("  3. Coinbase API temporarily unavailable")
            logging.error("")
            logging.error("Verify your credentials at:")
            logging.error("  https://portal.cloud.coinbase.com/access/api")
            import traceback
            logging.error(traceback.format_exc())
            return {
                "usdc": usdc_balance,
                "usd": usd_balance,
                "trading_balance": usd_balance + usdc_balance,
                "usd_held": 0.0,
                "usdc_held": 0.0,
                "total_held": 0.0,
                "total_funds": usd_balance + usdc_balance,
                "crypto": crypto_holdings,
                "consumer_usd": consumer_usd,
                "consumer_usdc": consumer_usdc,
            }
    
    def get_account_balance(self) -> float:
        """Get USD trading balance with fail-closed behavior (conforms to BaseBroker interface).
        
        🚑 FIX 4: BALANCE MUST INCLUDE LOCKED FUNDS
        Returns total_equity (available + locked) instead of just available_usd.
        This prevents NIJA from thinking it's broke when it has funds locked in positions.
        
        CRITICAL FIX (Jan 19, 2026): Fail closed - not "balance = 0"
        - On error: Return last known balance (if available) instead of 0
        - Track consecutive errors to mark broker unavailable
        - Distinguish API errors from actual zero balance
        
        Returns:
            float: TOTAL EQUITY (cash + positions) not just available cash
                   Returns last known balance on error (not 0)
        """
        try:
            balance_data = self._get_account_balance_detailed()
            
            if balance_data is None:
                # API call failed - use last known balance if available
                self._balance_fetch_errors += 1
                if self._balance_fetch_errors >= BROKER_MAX_CONSECUTIVE_ERRORS:
                    self._is_available = False
                    logger.error(f"❌ Coinbase marked unavailable after {self._balance_fetch_errors} consecutive errors")
                
                if self._last_known_balance is not None:
                    logger.warning(f"⚠️ Coinbase balance fetch failed, using last known balance: ${self._last_known_balance:.2f}")
                    return self._last_known_balance
                else:
                    logger.error("❌ Coinbase balance fetch failed and no last known balance available, returning 0.0")
                    return 0.0
            
            # 🚑 FIX 4: Return total_funds (available + locked) instead of just trading_balance
            # This ensures rotation and sizing use TOTAL EQUITY not just free cash
            # Fallback chain: total_funds -> trading_balance -> 0.0
            total_funds = balance_data.get('total_funds', None)
            if total_funds is None:
                total_funds = balance_data.get('trading_balance', 0.0)
            result = float(total_funds)
            
            # Log what we're returning for transparency
            trading_balance = float(balance_data.get('trading_balance', 0.0))
            total_held = float(balance_data.get('total_held', 0.0))
            
            if total_held > 0:
                logger.debug(f"💎 Total Equity: ${result:.2f} (Available: ${trading_balance:.2f} + Locked: ${total_held:.2f})")
            else:
                logger.debug(f"💰 Total Equity: ${result:.2f} (no locked funds)")
            
            # SUCCESS: Update last known balance and reset error count
            self._last_known_balance = result
            self._balance_fetch_errors = 0
            self._is_available = True
            
            return result
            
        except Exception as e:
            logger.error(f"❌ Exception fetching Coinbase balance: {e}")
            self._balance_fetch_errors += 1
            if self._balance_fetch_errors >= BROKER_MAX_CONSECUTIVE_ERRORS:
                self._is_available = False
                logger.error(f"❌ Coinbase marked unavailable after {self._balance_fetch_errors} consecutive errors")
            
            # Return last known balance instead of 0
            if self._last_known_balance is not None:
                logger.warning(f"   ⚠️ Using last known balance: ${self._last_known_balance:.2f}")
                return self._last_known_balance
            
            return 0.0
    
    def get_account_balance_detailed(self) -> dict:
        """Get detailed account balance information including crypto holdings.
        
        This is a public wrapper around _get_account_balance_detailed() for
        callers that need the full balance breakdown (crypto holdings, consumer wallets, etc).
        
        Returns:
            dict: Detailed balance info with keys: usdc, usd, trading_balance, crypto, consumer_usd, consumer_usdc
        """
        return self._get_account_balance_detailed()
    
    def is_available(self) -> bool:
        """
        Check if Coinbase broker is available for trading.
        
        Returns False if there have been 3+ consecutive balance fetch errors.
        This prevents trading when the API is not working properly.
        
        Returns:
            bool: True if broker is available, False if unavailable
        """
        return self._is_available
    
    def get_error_count(self) -> int:
        """
        Get the number of consecutive balance fetch errors.
        
        Returns:
            int: Number of consecutive errors
        """
        return self._balance_fetch_errors
    
    def get_total_capital(self, include_positions: bool = True) -> Dict:
        """
        Get total capital including both free balance and open position values.
        
        PRO MODE Feature: Counts open positions as available capital for rotation trading.
        
        Args:
            include_positions: If True, includes position values in total capital (default True)
        
        Returns:
            dict: Capital breakdown with keys:
                - free_balance: Available USD/USDC for new trades
                - position_value: Total USD value of all open positions
                - total_capital: free_balance + position_value
                - positions: List of positions with values
                - position_count: Number of open positions
        """
        try:
            # Get free balance
            free_balance = self.get_account_balance()
            
            # Get positions and calculate their values
            positions = self.get_positions()
            position_value_total = 0.0
            position_details = []
            
            if include_positions:
                for pos in positions:
                    symbol = pos.get('symbol')
                    quantity = pos.get('quantity', 0)
                    
                    if not symbol or quantity <= 0:
                        continue
                    
                    # Get current price for position
                    try:
                        price = self.get_current_price(symbol)
                        if price > 0:
                            value = quantity * price
                            position_value_total += value
                            position_details.append({
                                'symbol': symbol,
                                'quantity': quantity,
                                'price': price,
                                'value': value
                            })
                    except Exception as price_err:
                        logger.warning(f"⚠️ Could not get price for {symbol}: {price_err}")
                        continue
            
            total_capital = free_balance + position_value_total
            
            result = {
                'free_balance': free_balance,
                'position_value': position_value_total,
                'total_capital': total_capital,
                'positions': position_details,
                'position_count': len(position_details)
            }
            
            logger.debug(f"💰 Total capital: ${total_capital:.2f} (free: ${free_balance:.2f}, positions: ${position_value_total:.2f})")
            
            return result
            
        except Exception as e:
            logger.error(f"Error calculating total capital: {e}")
            return {
                'free_balance': 0.0,
                'position_value': 0.0,
                'total_capital': 0.0,
                'positions': [],
                'position_count': 0
            }
    
    def get_account_balance_OLD_BROKEN_METHOD(self):
        """
        OLD METHOD - DOES NOT WORK - Kept for reference
        Parse balances from ONLY v3 Advanced Trade API
        
        CRITICAL: Consumer wallet balances are NOT usable for API trading.
        Only Advanced Trade portfolio balance can be used for orders.
        This method ONLY returns Advanced Trade balance to prevent mismatches.
        """
        usd_balance = 0.0
        usdc_balance = 0.0
        consumer_usd = 0.0
        consumer_usdc = 0.0
        crypto_holdings: Dict[str, float] = {}

        try:
            # Check v2 Consumer wallets for DIAGNOSTIC purposes only
            logging.info(f"💰 Checking v2 API (Consumer wallets - DIAGNOSTIC ONLY)...")
            try:
                import requests
                import time
                import jwt
                from cryptography.hazmat.primitives import serialization
                
                api_key = os.getenv("COINBASE_API_KEY")
                api_secret = os.getenv("COINBASE_API_SECRET")
                
                # Normalize PEM
                if '\\n' in api_secret:
                    api_secret = api_secret.replace('\\n', '\n')
                
                private_key = serialization.load_pem_private_key(api_secret.encode('utf-8'), password=None)
                
                # Make v2 API call
                uri = "GET api.coinbase.com/v2/accounts"
                payload = {
                    'sub': api_key,
                    'iss': 'coinbase-cloud',
                    'nbf': int(time.time()),
                    'exp': int(time.time()) + 120,
                    'aud': ['coinbase-apis'],
                    'uri': uri
                }
                token = jwt.encode(payload, private_key, algorithm='ES256', 
                                  headers={'kid': api_key, 'nonce': str(int(time.time()))})
                headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
                response = requests.get(f"https://api.coinbase.com/v2/accounts", headers=headers)
                
                if response.status_code == 200:
                    data = response.json()
                    v2_accounts = data.get('data', [])
                    logging.info(f"📁 v2 Consumer API: {len(v2_accounts)} account(s)")
                    
                    for acc in v2_accounts:
                        currency_obj = acc.get('currency', {})
                        currency = currency_obj.get('code', 'N/A') if isinstance(currency_obj, dict) else currency_obj
                        balance_obj = acc.get('balance', {})
                        balance = float(balance_obj.get('amount', 0) if isinstance(balance_obj, dict) else balance_obj or 0)
                        account_type = acc.get('type', 'unknown')
                        name = acc.get('name', 'Unknown')
                        
                        if currency == "USD":
                            consumer_usd += balance
                            if balance > 0:
                                logging.info(f"   📊 Consumer USD: ${balance:.2f} (type={account_type}, name={name}) [NOT TRADABLE VIA API]")
                        elif currency == "USDC":
                            consumer_usdc += balance
                            if balance > 0:
                                logging.info(f"   📊 Consumer USDC: ${balance:.2f} (type={account_type}, name={name}) [NOT TRADABLE VIA API]")
                else:
                    logging.warning(f"⚠️  v2 API returned status {response.status_code}")
                    
            except Exception as v2_error:
                logging.warning(f"⚠️  v2 API check failed: {v2_error}")
            
            # Check v3 Advanced Trade API - THIS IS THE ONLY TRADABLE BALANCE
            logging.info(f"💰 Checking v3 API (Advanced Trade - TRADABLE BALANCE)...")
            try:
                logging.info(f"   🔍 Calling client.list_accounts()...")
                accounts_resp = self.client.list_accounts() if hasattr(self.client, 'list_accounts') else self.client.get_accounts()
                accounts = getattr(accounts_resp, 'accounts', [])
                logging.info(f"📁 v3 Advanced Trade API: {len(accounts)} account(s)")
                
                # ENHANCED DEBUG: Show ALL accounts
                if len(accounts) == 0:
                    logging.error(f"   🚨 API returned ZERO accounts!")
                    logging.error(f"   Response type: {type(accounts_resp)}")
                    logging.error(f"   Response object: {accounts_resp}")
                else:
                    logging.info(f"   📋 Listing all {len(accounts)} accounts:")

                for account in accounts:
                    currency = getattr(account, 'currency', None)
                    available_obj = getattr(account, 'available_balance', None)
                    available = float(getattr(available_obj, 'value', 0) or 0)
                    account_type = getattr(account, 'type', None)
                    account_name = getattr(account, 'name', 'Unknown')
                    account_uuid = getattr(account, 'uuid', 'no-uuid')
                    
                    # DEBUG: Log EVERY account we see
                    logging.info(f"      → {currency}: ${available:.2f} | {account_name} | {account_type} | UUID: {account_uuid[:8]}...")
                    
                    # ONLY count Advanced Trade balances for trading
                    if currency == "USD":
                        usd_balance += available
                        if available > 0:
                            logging.info(f"   ✅ Advanced Trade USD: ${available:.2f} (name={account_name}, type={account_type}) [TRADABLE]")
                    elif currency == "USDC":
                        usdc_balance += available
                        if available > 0:
                            logging.info(f"   ✅ Advanced Trade USDC: ${available:.2f} (name={account_name}, type={account_type}) [TRADABLE]")
                    elif available > 0:
                        crypto_holdings[currency] = crypto_holdings.get(currency, 0) + available
            except Exception as v3_error:
                logging.error(f"⚠️  v3 API check failed!")
                logging.error(f"   Error type: {type(v3_error).__name__}")
                logging.error(f"   Error message: {v3_error}")
                import traceback
                logging.error(f"   Traceback: {traceback.format_exc()}")

            # CRITICAL FIX: ONLY Advanced Trade balances are tradeable
            # Consumer wallet balances CANNOT be used for trading via API
            # The market_order_buy() function can ONLY access Advanced Trade portfolio
            trading_balance = usdc_balance if usdc_balance > 0 else usd_balance
            
            # IGNORE ALLOW_CONSUMER_USD flag - it's misleading
            # Consumer wallets are simply NOT accessible for API trading
            if self.allow_consumer_usd and (consumer_usd > 0 or consumer_usdc > 0):
                logging.warning("⚠️  ALLOW_CONSUMER_USD is enabled, but API cannot trade from Consumer wallets!")
                logging.warning("   This flag has no effect. Transfer funds to Advanced Trade instead.")

            logging.info("=" * 70)
            logging.info("💰 BALANCE SUMMARY:")
            logging.info(f"   Consumer USD:  ${consumer_usd:.2f} ❌ [NOT TRADABLE - API LIMITATION]")
            logging.info(f"   Consumer USDC: ${consumer_usdc:.2f} ❌ [NOT TRADABLE - API LIMITATION]")
            logging.info(f"   Advanced Trade USD:  ${usd_balance:.2f} ✅ [TRADABLE]")
            logging.info(f"   Advanced Trade USDC: ${usdc_balance:.2f} ✅ [TRADABLE]")
            logging.info(f"   ▶ TRADING BALANCE: ${trading_balance:.2f}")
            logging.info("")
            
            # Warn if funds are insufficient (using module-level constants)
            if trading_balance < MINIMUM_BALANCE_PROTECTION:
                funding_needed = MINIMUM_BALANCE_PROTECTION - trading_balance
                logging.error("=" * 70)
                logging.error("🚨 CRITICAL: INSUFFICIENT TRADING BALANCE!")
                logging.error(f"   Current balance: ${trading_balance:.2f}")
                logging.error(f"   MINIMUM_BALANCE (Protection): ${MINIMUM_BALANCE_PROTECTION:.2f}")
                logging.error(f"   💵 Funding Needed: ${funding_needed:.2f}")
                logging.error(f"   Why? Minimum for small trades to cover fees and safety margin")
                logging.error("")
                if (consumer_usd > 0 or consumer_usdc > 0):
                    logging.error("   🔍 ROOT CAUSE: Your funds are in Consumer wallet!")
                    logging.error(f"   Consumer wallet has ${consumer_usd + consumer_usdc:.2f} (NOT TRADABLE)")
                    logging.error(f"   Advanced Trade has ${trading_balance:.2f} (TRADABLE)")
                    logging.error("")
                    logging.error("   🔧 SOLUTION: Transfer to Advanced Trade")
                    logging.error("      1. Go to: https://www.coinbase.com/advanced-portfolio")
                    logging.error("      2. Click 'Deposit' → 'From Coinbase'")
                    logging.error(f"      3. Transfer ${consumer_usd + consumer_usdc:.2f} USD/USDC to Advanced Trade")
                    logging.error("      4. Instant transfer, no fees")
                    logging.error("")
                    logging.error("   ❌ CANNOT FIX WITH CODE:")
                    logging.error("      The Coinbase Advanced Trade API cannot access Consumer wallets")
                    logging.error("      This is a Coinbase API limitation, not a bot issue")
                elif trading_balance == 0:
                    logging.error("   No funds detected in any account")
                    logging.error("   Add funds to your Coinbase account")
                else:
                    logging.error("   Your balance is very low for reliable trading")
                    logging.error("   💡 Note: Funds will become available as open positions are sold")
                    logging.error("   💡 Bot will attempt to trade but with very limited capacity")
                    logging.error(f"   With ${trading_balance:.2f}, position sizing will be extremely small")
                    logging.error("")
                    logging.error("   🎯 RECOMMENDED: Deposit at least $25-$50")
                    logging.error("      - Allows multiple trades")
                    logging.error("      - Better position sizing")
                    logging.error("      - Strategy works more effectively")
                logging.error("=" * 70)
            elif trading_balance < MINIMUM_TRADING_BALANCE:
                funding_recommended = MINIMUM_TRADING_BALANCE - trading_balance
                logging.warning("=" * 70)
                logging.warning("⚠️  WARNING: Trading balance below recommended minimum")
                logging.warning(f"   Current balance: ${trading_balance:.2f}")
                logging.warning(f"   MINIMUM_TRADING_BALANCE (Recommended): ${MINIMUM_TRADING_BALANCE:.2f}")
                logging.warning(f"   💵 Additional Funding Recommended: ${funding_recommended:.2f}")
                logging.warning("")
                logging.warning("   Bot can operate but with limited capacity")
                logging.warning("   💡 Add funds for optimal trading performance")
                logging.warning("   💡 Or wait for positions to close and reinvest profits")
                logging.warning("=" * 70)
            else:
                logging.info(f"   ✅ Sufficient funds in Advanced Trade for trading!")
            
            logging.info("=" * 70)

            return {
                "usdc": usdc_balance,
                "usd": usd_balance,
                "trading_balance": trading_balance,
                "crypto": crypto_holdings,
                "consumer_usd": consumer_usd,
                "consumer_usdc": consumer_usdc,
            }
        except Exception as e:
            logging.error(f"🔥 ERROR get_account_balance: {e}")
            import traceback
            traceback.print_exc()
            return {
                "usdc": 0.0,
                "usd": 0.0,
                "trading_balance": 0.0,
                "crypto": {},
                "consumer_usd": 0.0,
                "consumer_usdc": 0.0,
            }
    
    def _dump_portfolio_summary(self):
        """Diagnostic: dump all portfolios and their USD/USDC balances"""
        try:
            # RATE LIMIT FIX: Wrap get_accounts with retry logic to prevent 429 errors
            accounts_resp = self._api_call_with_retry(self.client.get_accounts)
            accounts = getattr(accounts_resp, 'accounts', [])
            usd_total = 0.0
            usdc_total = 0.0
            for a in accounts:
                curr = getattr(a, 'currency', None)
                av = float(getattr(getattr(a, 'available_balance', None), 'value', 0) or 0)
                if curr == "USD":
                    usd_total += av
                elif curr == "USDC":
                    usdc_total += av
            logging.info(f"   Default portfolio | USD: ${usd_total:.2f} | USDC: ${usdc_total:.2f}")
        except Exception as e:
            logging.warning(f"⚠️ Portfolio summary failed: {e}")

    def get_usd_usdc_inventory(self) -> list[str]:
        """Return a formatted USD/USDC inventory for logging by callers.

        This method mirrors the inventory logic used by diagnostics but returns
        strings so the caller can log with its own logger configuration
        (important because some apps only attach handlers to the 'nija' logger).
        """
        lines: list[str] = []
        try:
            # RATE LIMIT FIX: Wrap get_accounts with retry logic to prevent 429 errors
            resp = self._api_call_with_retry(self.client.get_accounts)
            accounts = getattr(resp, 'accounts', []) or (resp.get('accounts', []) if isinstance(resp, dict) else [])
            usd_total = 0.0
            usdc_total = 0.0

            def _as_float(v):
                try:
                    return float(v)
                except Exception:
                    return 0.0

            for a in accounts:
                if isinstance(a, dict):
                    currency = a.get('currency')
                    name = a.get('name')
                    platform = a.get('platform')
                    account_type = a.get('type')
                    av = (a.get('available_balance') or {}).get('value')
                    hd = (a.get('hold') or {}).get('value')
                else:
                    currency = getattr(a, 'currency', None)
                    name = getattr(a, 'name', None)
                    platform = getattr(a, 'platform', None)
                    account_type = getattr(a, 'type', None)
                    av = getattr(getattr(a, 'available_balance', None), 'value', None)
                    hd = getattr(getattr(a, 'hold', None), 'value', None)

                is_tradeable = account_type == "ACCOUNT_TYPE_CRYPTO" or (platform and "ADVANCED_TRADE" in str(platform))

                if currency in ("USD", "USDC"):
                    avf = _as_float(av)
                    hdf = _as_float(hd)
                    tag = "TRADEABLE" if is_tradeable else "CONSUMER"
                    lines.append(f"{currency:>4} | name={name} | platform={platform} | type={account_type} | avail={avf:>10.2f} | held={hdf:>10.2f} | {tag}")
                    if is_tradeable:
                        if currency == "USD":
                            usd_total += avf
                        else:
                            usdc_total += avf

            lines.append("-" * 70)
            trading = usd_total + usdc_total
            lines.append(f"Totals → USD: ${usd_total:.2f} | USDC: ${usdc_total:.2f} | Trading Balance: ${trading:.2f}")
            if usd_total == 0.0 and usdc_total == 0.0:
                lines.append("👉 Move funds into your Advanced Trade portfolio: https://www.coinbase.com/advanced-portfolio")
        except Exception as e:
            lines.append(f"⚠️ Failed to fetch USD/USDC inventory: {e}")

        return lines

    def _log_insufficient_fund_context(self, base_currency: str, quote_currency: str) -> None:
        """Log available balances for base/quote/USD/USDC across portfolios for diagnostics."""
        try:
            # RATE LIMIT FIX: Wrap get_accounts with retry logic to prevent 429 errors
            resp = self._api_call_with_retry(self.client.get_accounts)
            accounts = getattr(resp, 'accounts', []) or (resp.get('accounts', []) if isinstance(resp, dict) else [])

            def _as_float(val):
                try:
                    return float(val)
                except Exception:
                    return 0.0

            interesting = {base_currency, quote_currency, 'USD', 'USDC'}
            logger.error(f"   Fund snapshot ({', '.join(sorted(interesting))})")
            for a in accounts:
                if isinstance(a, dict):
                    currency = a.get('currency')
                    platform = a.get('platform')
                    account_type = a.get('type')
                    av = (a.get('available_balance') or {}).get('value')
                    hd = (a.get('hold') or {}).get('value')
                else:
                    currency = getattr(a, 'currency', None)
                    platform = getattr(a, 'platform', None)
                    account_type = getattr(a, 'type', None)
                    av = getattr(getattr(a, 'available_balance', None), 'value', None)
                    hd = getattr(getattr(a, 'hold', None), 'value', None)

                if currency not in interesting:
                    continue

                avf = _as_float(av)
                hdf = _as_float(hd)
                tag = "TRADEABLE" if account_type == "ACCOUNT_TYPE_CRYPTO" or (platform and "ADVANCED_TRADE" in str(platform)) else "CONSUMER"
                logger.error(f"     {currency:>4} | avail={avf:>14.6f} | held={hdf:>12.6f} | type={account_type} | platform={platform} | {tag}")
        except Exception as diag_err:
            logger.error(f"   ⚠️ fund diagnostic failed: {diag_err}")

    def _get_product_metadata(self, symbol: str) -> Dict:
        """Fetch and cache product metadata (base_increment, quote_increment)."""
        # Ensure cache exists (defensive programming)
        if not hasattr(self, '_product_cache'):
            self._product_cache = {}
        
        if symbol in self._product_cache:
            return self._product_cache[symbol]

        meta: Dict = {}
        try:
            # RATE LIMIT FIX: Wrap get_product with rate limiter to prevent 429 errors
            def _fetch_product():
                return self.client.get_product(product_id=symbol)
            
            if self._rate_limiter:
                product = self._rate_limiter.call('get_product', _fetch_product)
            else:
                product = _fetch_product()
            
            if isinstance(product, dict):
                meta = product
            else:
                # Serialize SDK object to dict
                meta = _serialize_object_to_dict(product)
            # Some SDK responses nest data under a top-level "product" key
            if isinstance(meta, dict) and 'product' in meta and isinstance(meta['product'], dict):
                meta = meta['product']
            # Some responses wrap the single product in a list under "products"
            if isinstance(meta, dict) and 'products' in meta and isinstance(meta['products'], list) and meta['products']:
                first = meta['products'][0]
                if isinstance(first, dict):
                    meta = first
        except Exception as e:
            logger.warning(f"⚠️ Could not fetch product metadata for {symbol}: {e}")

        self._product_cache[symbol] = meta
        return meta
    
    def place_market_order(
        self, 
        symbol: str, 
        side: str, 
        quantity: float, 
        size_type: str = 'quote',
        ignore_balance: bool = False,
        ignore_min_trade: bool = False,
        force_liquidate: bool = False
    ) -> Dict:
        """
        Place market order with balance verification (and optional bypasses for emergencies).
        
        Args:
            symbol: Trading pair (e.g., 'BTC-USD')
            side: 'buy' or 'sell'
            quantity: Amount to trade
            size_type: 'quote' for USD amount (default) or 'base' for crypto amount
            ignore_balance: Bypass balance validation (EMERGENCY ONLY - FIX 1)
            ignore_min_trade: Bypass minimum trade size validation (EMERGENCY ONLY - FIX 1)
            force_liquidate: Bypass ALL validation (EMERGENCY ONLY - FIX 1)
        
        Returns:
            Order response dictionary
        """
        try:
            # CRITICAL FIX (Jan 10, 2026): Validate symbol parameter before any API calls
            # Prevents "ProductID is invalid" errors from Coinbase API
            if not symbol:
                logger.error("❌ INVALID SYMBOL: Symbol parameter is None or empty")
                logger.error(f"   Side: {side}, Quantity: {quantity}, Size Type: {size_type}")
                return {
                    "status": "error",
                    "error": "INVALID_SYMBOL",
                    "message": "Symbol parameter is None or empty",
                    "partial_fill": False,
                    "filled_pct": 0.0
                }
            
            if not isinstance(symbol, str):
                logger.error(f"❌ INVALID SYMBOL: Symbol must be string, got {type(symbol)}")
                logger.error(f"   Symbol value: {symbol}")
                return {
                    "status": "error",
                    "error": "INVALID_SYMBOL",
                    "message": f"Symbol must be string, got {type(symbol)}",
                    "partial_fill": False,
                    "filled_pct": 0.0
                }
            
            # Validate symbol format (should be like "BTC-USD", "ETH-USD", etc.)
            if '-' not in symbol or len(symbol) < 5:
                logger.error(f"❌ INVALID SYMBOL: Invalid format '{symbol}'")
                logger.error(f"   Expected format: BASE-QUOTE (e.g., 'BTC-USD')")
                logger.error(f"   Side: {side}, Quantity: {quantity}")
                return {
                    "status": "error",
                    "error": "INVALID_SYMBOL",
                    "message": f"Invalid symbol format '{symbol}' - expected 'BASE-QUOTE'",
                    "partial_fill": False,
                    "filled_pct": 0.0
                }
            
            # Global BUY guard: block all buys when emergency stop is active or HARD_BUY_OFF=1
            try:
                import os as _os
                lock_path = _os.path.join(_os.path.dirname(__file__), '..', 'TRADING_EMERGENCY_STOP.conf')
                hard_buy_off = (_os.getenv('HARD_BUY_OFF', '0') in ('1', 'true', 'True'))
                if side.lower() == 'buy' and (hard_buy_off or _os.path.exists(lock_path)):
                    logger.error("🛑 BUY BLOCKED at broker layer: SELL-ONLY mode or HARD_BUY_OFF active")
                    logger.error(f"   Symbol: {symbol}")
                    logger.error(f"   Reason: {'HARD_BUY_OFF' if hard_buy_off else 'TRADING_EMERGENCY_STOP.conf present'}")
                    return {
                        "status": "unfilled",
                        "error": "BUY_BLOCKED",
                        "message": "Global buy guard active (sell-only mode)",
                        "partial_fill": False,
                        "filled_pct": 0.0
                    }
            except Exception:
                # If guard check fails, proceed but log later if needed
                pass

            # 🚑 FIX #1: FORCE SELL OVERRIDE - SELL orders bypass ALL restrictions
            # ================================================================
            # CRITICAL: SELL orders are NEVER blocked by:
            #   ✅ MINIMUM_TRADING_BALANCE (balance checks only apply to BUY)
            #   ✅ MIN_CASH_TO_BUY (balance checks only apply to BUY)
            #   ✅ ENTRY_ONLY mode / EXIT_ONLY mode (blocks BUY, not SELL)
            #   ✅ Broker preference routing (SELL always executes)
            #   ✅ Emergency stop flags (only block BUY)
            #
            # This ensures:
            #   - Stop-loss exits always execute
            #   - Emergency liquidation always executes
            #   - Losing positions can always be closed
            #   - Capital bleeding can always be stopped
            # ================================================================
            
            # Log explicit bypass for SELL orders
            if side.lower() == 'sell':
                logger.info(f"🚑 SELL order for {symbol}: ALL RESTRICTIONS BYPASSED")
                logger.info(f"   ✅ Balance validation: SKIPPED (SELL only)")
                logger.info(f"   ✅ Minimum balance check: SKIPPED (SELL only)")
                logger.info(f"   ✅ EXIT-ONLY mode: ALLOWED (SELL only)")
                logger.info(f"   ✅ Emergency exit: ENABLED")
            
            # FIX 2: Reject BUY orders when in EXIT-ONLY mode
            # NOTE: SELL orders are NOT checked here - they always pass through
            if side.lower() == 'buy' and getattr(self, 'exit_only_mode', False) and not force_liquidate:
                logger.error(f"❌ BUY order rejected: Coinbase is in EXIT-ONLY mode (balance < ${COINBASE_MINIMUM_BALANCE:.2f})")
                logger.error(f"   Only SELL orders are allowed to close existing positions")
                logger.error(f"   To enable new entries, fund your account to at least ${COINBASE_MINIMUM_BALANCE:.2f}")
                return {
                    "status": "unfilled",
                    "error": "EXIT_ONLY_MODE",
                    "message": f"BUY orders blocked: Account balance below ${COINBASE_MINIMUM_BALANCE:.2f} minimum",
                    "partial_fill": False,
                    "filled_pct": 0.0
                }

            if quantity <= 0:
                raise ValueError(f"Refusing to place {side} order with non-positive size: {quantity}")

            base_currency, quote_currency = (symbol.split('-') + ['USD'])[:2]

            # 🚑 FIX 1: EMERGENCY SELL OVERRIDE - Bypass balance check if forced
            # This allows NIJA to exit losing positions regardless of balance validation
            if force_liquidate or ignore_balance:
                logger.warning(f"⚠️  BALANCE CHECK BYPASSED for {symbol} (force_liquidate={force_liquidate}, ignore_balance={ignore_balance})")

            # PRE-FLIGHT CHECK: Verify sufficient balance before placing order
            # CRITICAL: This check ONLY applies to BUY orders
            # SELL orders ALWAYS bypass this check
            # SKIP if force_liquidate or ignore_balance is True
            if side.lower() == 'buy' and not (force_liquidate or ignore_balance):
                balance_data = self._get_account_balance_detailed()
                trading_balance = float(balance_data.get('trading_balance', 0.0))
                
                logger.info(f"💰 Pre-flight balance check for {symbol}:")
                logger.info(f"   Available: ${trading_balance:.2f}")
                logger.info(f"   Required:  ${quantity:.2f}")
                
                # ADD FIX #2: Add 2% safety buffer for fees/rounding (Coinbase typically takes 0.5-1%)
                safety_buffer = quantity * 0.02  # 2% buffer
                required_with_buffer = quantity + safety_buffer
                
                if trading_balance < required_with_buffer:
                    error_msg = f"Insufficient funds: ${trading_balance:.2f} available, ${required_with_buffer:.2f} required (with 2% fee buffer)"
                    logger.error(f"❌ PRE-FLIGHT CHECK FAILED: {error_msg}")
                    logger.error(f"   Bot detected ${trading_balance:.2f} but needs ${required_with_buffer:.2f} for this order")
                    
                    # Log USD/USDC inventory for debugging
                    logger.error(f"   Account inventory:")
                    inventory_lines = self.get_usd_usdc_inventory()
                    for line in inventory_lines:
                        logger.error(f"     {line}")
                    
                    return {
                        "status": "unfilled",
                        "error": "INSUFFICIENT_FUND",
                        "message": error_msg,
                        "partial_fill": False,
                        "filled_pct": 0.0
                    }

            client_order_id = str(uuid.uuid4())
            
            if side.lower() == 'buy':
                # CRITICAL FIX: Round quote_size to 2 decimal places for Coinbase precision requirements
                # Floating point math can create values like 23.016000000000002
                # Coinbase rejects these with PREVIEW_INVALID_QUOTE_SIZE_PRECISION
                quote_size_rounded = round(quantity, 2)
                
                # Use positional client_order_id to avoid SDK signature mismatch
                logger.info(f"📤 Placing BUY order: {symbol}, quote_size=${quote_size_rounded:.2f}")
                logger.info(f"   Using Coinbase Advanced Trade v3 API (market_order_buy)")
                if self.portfolio_uuid:
                    logger.info(f"   Routing to portfolio: {self.portfolio_uuid[:8]}...")
                else:
                    logger.info(f"   This API can ONLY trade from Advanced Trade portfolio, NOT Consumer wallets")
                
                # Include portfolio_uuid if we have it
                order_kwargs = {
                    'client_order_id': client_order_id,
                    'product_id': symbol,
                    'quote_size': str(quote_size_rounded)
                }
                
                # Note: The Coinbase SDK market_order_buy may not support portfolio_uuid parameter
                # It routes to the default portfolio automatically
                # The real fix is to ensure funds are in the default trading portfolio
                order = self.client.market_order_buy(
                    client_order_id,
                    product_id=symbol,
                    quote_size=str(quote_size_rounded)
                )
            else:
                # SELL order - use base_size (crypto amount) or quote_size (USD value)
                if size_type == 'base':
                    base_currency = symbol.split('-')[0].upper()

                    precision_map = {
                        'XRP': 2,
                        'DOGE': 2,
                        'ADA': 2,
                        'SHIB': 0,
                        'BTC': 8,
                        'ETH': 6,
                        'SOL': 4,
                        'ATOM': 4,
                        'LTC': 8,
                        'BCH': 8,
                        'LINK': 4,
                        'IMX': 4,
                        'XLM': 4,
                        'CRV': 4,
                        'APT': 4,
                        'ICP': 5,
                        'NEAR': 5,
                        'AAVE': 4,
                    }

                    # CRITICAL FIX: Use ACTUAL Coinbase increment values
                    # Many coins only accept WHOLE numbers (increment=1) despite supporting decimal balances
                    fallback_increment_map = {
                        'BTC': 0.00000001,  # 8 decimals
                        'ETH': 0.000001,    # 6 decimals
                        'ADA': 1,           # WHOLE NUMBERS ONLY
                        'SOL': 0.001,       # 3 decimals
                        'XRP': 1,           # WHOLE NUMBERS ONLY
                        'DOGE': 1,          # WHOLE NUMBERS ONLY
                        'AVAX': 0.001,      # 3 decimals
                        'DOT': 0.1,         # 1 decimal
                        'LINK': 0.01,       # 2 decimals
                        'LTC': 0.00000001,  # 8 decimals
                        'UNI': 0.01,        # 2 decimals
                        'XLM': 1,           # WHOLE NUMBERS ONLY
                        'HBAR': 1,          # WHOLE NUMBERS ONLY
                        'APT': 0.01,        # 2 decimals
                        'ICP': 0.01,        # 2 decimals
                        'RENDER': 0.1,      # 1 decimal
                        'ZRX': 1,           # WHOLE NUMBERS ONLY
                        'CRV': 1,           # WHOLE NUMBERS ONLY
                        'FET': 1,           # WHOLE NUMBERS ONLY
                        'AAVE': 0.001,      # 3 decimals
                        'VET': 1,           # WHOLE NUMBERS ONLY
                        'SHIB': 1,          # WHOLE NUMBERS ONLY
                        'BCH': 0.00000001,  # 8 decimals
                        'ATOM': 0.0001,     # 4 decimals
                        'IMX': 0.0001,      # 4 decimals
                        'NEAR': 0.00001,    # 5 decimals
                    }

                    precision = max(0, min(precision_map.get(base_currency, 2), 8))
                    base_increment = None

                    # Emergency mode: skip preflight balance calls to reduce API 429s
                    emergency_file = os.path.join(os.path.dirname(__file__), '..', 'LIQUIDATE_ALL_NOW.conf')
                    skip_preflight = side.lower() == 'sell' and os.path.exists(emergency_file)

                    if not skip_preflight:
                        try:
                            balance_snapshot = self._get_account_balance_detailed()
                            holdings = (balance_snapshot or {}).get('crypto', {}) or {}
                            available_base = float(holdings.get(base_currency, 0.0))

                            try:
                                # RATE LIMIT FIX: Wrap get_accounts with retry logic to prevent 429 errors
                                accounts = self._api_call_with_retry(self.client.get_accounts)
                                hold_amount = 0.0
                                for a in accounts:
                                    if isinstance(a, dict):
                                        currency = a.get('currency')
                                        hd = (a.get('hold') or {}).get('value')
                                    else:
                                        currency = getattr(a, 'currency', None)
                                        hd = getattr(getattr(a, 'hold', None), 'value', None)
                                    if currency == base_currency and hd is not None:
                                        try:
                                            hold_amount = float(hd)
                                        except Exception:
                                            hold_amount = 0.0
                                        break
                                if hold_amount > 0:
                                    available_base = max(0.0, available_base - hold_amount)
                                    logger.info(f"   Adjusted for holds: {hold_amount:.8f} {base_currency} held → usable {available_base:.8f}")
                            except Exception as hold_err:
                                logger.warning(f"⚠️ Could not read holds for {base_currency}: {hold_err}")

                            logger.info(f"   Real-time balance check: {available_base:.8f} {base_currency} available")
                            logger.info(f"   Tracked position size: {quantity:.8f} {base_currency}")
                            
                            # FIX 2: SELL MUST IGNORE CASH BALANCE
                            # CRITICAL: We're selling CRYPTO, not buying with USD
                            # The check should be: "Do we have the crypto?" NOT "Do we have USD?"
                            # Old (WRONG): if available_base <= epsilon: block_sell()
                            # New (CORRECT): if position.quantity > 0: execute_sell()
                            #
                            # This single change stops the bleeding:
                            # - We can now exit losing positions even with $0 USD balance
                            # - Sells are NOT blocked by insufficient USD (which makes no sense!)
                            # - Position management works correctly
                            
                            epsilon = 1e-8
                            
                            # Validate quantity is positive before proceeding
                            if quantity <= epsilon:
                                logger.error(
                                    f"❌ INVALID SELL: Zero or negative quantity "
                                    f"(quantity: {quantity:.8f})"
                                )
                                return {
                                    "status": "unfilled",
                                    "error": "INVALID_QUANTITY",
                                    "message": f"Cannot sell zero or negative quantity: {quantity}",
                                    "partial_fill": False,
                                    "filled_pct": 0.0
                                }
                            
                            if available_base <= epsilon:
                                # FIX 2: Changed from ERROR to WARNING
                                # We should still TRY to sell even if balance shows zero
                                # (position might exist on exchange but not in our cache)
                                logger.warning(
                                    f"⚠️ PRE-FLIGHT WARNING: Zero {base_currency} balance shown "
                                    f"(available: {available_base:.8f})"
                                )
                                logger.warning(
                                    f"   Attempting sell anyway - position may exist on exchange"
                                )
                                # DON'T RETURN - continue with sell attempt
                                # The exchange will reject if there's truly no balance
                            
                            if available_base < quantity:
                                diff = quantity - available_base
                                logger.warning(
                                    f"⚠️ Balance mismatch: tracked {quantity:.8f} but only {available_base:.8f} available"
                                )
                                logger.warning(f"   Difference: {diff:.8f} {base_currency} (likely from partial fills or fees)")
                                logger.warning(f"   SOLUTION: Adjusting sell size to actual available balance")
                                quantity = available_base
                        except Exception as bal_err:
                            logger.warning(f"⚠️ Could not pre-check balance for {base_currency}: {bal_err}")
                    else:
                        logger.info("   EMERGENCY MODE: Skipping pre-flight balance checks")

                    meta = self._get_product_metadata(symbol)
                    inc_candidates = []
                    if isinstance(meta, dict):
                        inc_candidates = [
                            meta.get('base_increment'),
                            meta.get('base_increment_decimal'),
                            meta.get('base_increment_value'),
                            # base_min_size is a minimum size, not an increment; exclude from precision detection
                        ]
                        if meta.get('base_increment_exponent') is not None:
                            try:
                                exp_val = float(meta.get('base_increment_exponent'))
                                inc_candidates.append(10 ** exp_val)
                            except Exception as exp_err:
                                logger.warning(f"⚠️ Could not parse base_increment_exponent for {symbol}: {exp_err}")
                    for inc in inc_candidates:
                        if not inc:
                            continue
                        try:
                            base_increment = float(inc)
                            if base_increment > 0:
                                break
                        except Exception as inc_err:
                            logger.warning(f"⚠️ Could not parse base_increment for {symbol}: {inc_err}")

                    # If API metadata did not provide an increment, use a conservative fallback per asset
                    if base_increment is None and base_currency in fallback_increment_map:
                        base_increment = fallback_increment_map[base_currency]
                    
                    # Final safety: ensure we have an increment
                    if base_increment is None:
                        base_increment = 0.01  # Default to 2 decimal places
                    
                    # Calculate precision from increment CORRECTLY
                    import math
                    if base_increment >= 1:
                        precision = 0  # Whole numbers only
                    else:
                        # Count decimal places: 0.001 → 3, 0.0001 → 4, etc.
                        precision = int(abs(math.floor(math.log10(base_increment))))

                    # Adjust requested quantity against available balance with a safety margin
                    # FIX #3: Use a larger safety margin to account for fees and rounding
                    # Coinbase typically charges 0.5-1% in trading fees, plus potential precision rounding
                    requested_qty = float(quantity)  # Already adjusted to available if needed
                    
                    # CRITICAL FIX: For small positions (< $10 value), use minimal safety margin
                    # The 0.5% margin was causing tiny positions to round to 0 after subtraction
                    try:
                        current_price = self.get_current_price(symbol)
                        position_usd_value = requested_qty * current_price
                    except Exception as price_err:
                        # If we can't get price, assume it's a larger position (safer - uses percentage margin)
                        logger.warning(f"⚠️ Could not get price for {symbol}: {price_err}")
                        position_usd_value = 100  # Default to large position logic
                    
                    if position_usd_value < 10.0:
                        # For small positions, use tiny epsilon only (not percentage)
                        # These positions are too small for fees to matter much
                        safety_margin = 1e-8  # Minimal epsilon
                        logger.info(f"   Small position (${position_usd_value:.2f}) - using minimal safety margin")
                    else:
                        # For larger positions, use 0.5% margin
                        safety_margin = max(requested_qty * 0.005, 1e-8)
                    
                    # Subtract safety margin to leave room for fees and rounding
                    trade_qty = max(0.0, requested_qty - safety_margin)
                    
                    logger.info(f"   Safety margin: {safety_margin:.8f} {base_currency}")
                    logger.info(f"   Final trade qty: {trade_qty:.8f} {base_currency}")

                    # Quantize size DOWN to allowed increment using floor division
                    # This is more reliable than Decimal arithmetic
                    import math
                    
                    # Calculate how many increments fit into trade_qty (floor division)
                    num_increments = math.floor(trade_qty / base_increment)
                    base_size_rounded = num_increments * base_increment
                    
                    # Round to the correct decimal places to avoid floating point artifacts
                    base_size_rounded = round(base_size_rounded, precision)
                    
                    # CRITICAL FIX: If rounding resulted in 0 or too small, try selling FULL available balance
                    # This happens with very small positions where safety margin + rounding = 0
                    if base_size_rounded <= 0 or base_size_rounded < base_increment:
                        logger.warning(f"   ⚠️ Rounded size too small ({base_size_rounded}), attempting to sell FULL balance")
                        # Try using the full requested quantity without safety margin
                        num_increments = math.floor(requested_qty / base_increment)
                        base_size_rounded = num_increments * base_increment
                        base_size_rounded = round(base_size_rounded, precision)
                        logger.info(f"   Retry with full balance: {base_size_rounded} {base_currency}")
                    
                    logger.info(f"   Derived base_increment={base_increment} precision={precision} → rounded={base_size_rounded}")
                    
                    # FINAL CHECK: If still too small, log detailed error and try anyway
                    # Coinbase may accept it or provide better error message
                    if base_size_rounded <= 0 or base_size_rounded < base_increment:
                        logger.error(f"   ❌ Position too small to sell with current precision rules")
                        logger.error(f"   Symbol: {symbol}, Base: {base_currency}")
                        logger.error(f"   Available: {available_base:.8f}" if skip_preflight else f"   Available: (preflight skipped)")
                        logger.error(f"   Requested: {requested_qty}")
                        logger.error(f"   Increment: {base_increment}, Precision: {precision}")
                        logger.error(f"   Rounded: {base_size_rounded}")
                        logger.error(f"   ⚠️ This position cannot be sold via API and may need manual intervention")
                        
                        return {
                            "status": "unfilled",
                            "error": "INVALID_SIZE",
                            "message": f"Position too small: {symbol} rounded to {base_size_rounded} (min: {base_increment}). Manual sell may be required.",
                            "partial_fill": False,
                            "filled_pct": 0.0
                        }

                    logger.info(f"📤 Placing SELL order: {symbol}, base_size={base_size_rounded} ({precision} decimals)")
                    if self.portfolio_uuid:
                        logger.info(f"   Routing to portfolio: {self.portfolio_uuid[:8]}...")

                    # Prefer create_order; fallback to market_order_sell, with 429 backoff
                    def _with_backoff(fn, *args, **kwargs):
                        import time
                        delays = [1, 2, 4]
                        for i, d in enumerate(delays):
                            try:
                                return fn(*args, **kwargs)
                            except Exception as err:
                                msg = str(err)
                                if 'Too Many Requests' in msg or '429' in msg:
                                    logger.warning(f"⚠️ Rate limited, retrying in {d}s (attempt {i+1}/{len(delays)})")
                                    time.sleep(d)
                                    continue
                                raise
                        return fn(*args, **kwargs)

                    try:
                        order = _with_backoff(
                            self.client.create_order,
                            client_order_id=client_order_id,
                            product_id=symbol,
                            order_configuration={
                                'market_market_ioc': {
                                    'base_size': str(base_size_rounded),
                                    'reduce_only': True
                                }
                            },
                            **({'portfolio_id': self.portfolio_uuid} if getattr(self, 'portfolio_uuid', None) else {})
                        )
                    except Exception as co_err:
                        logger.warning(f"⚠️ create_order failed, falling back to market_order_sell: {co_err}")
                        order = _with_backoff(
                            self.client.market_order_sell,
                            client_order_id,
                            product_id=symbol,
                            base_size=str(base_size_rounded)
                        )
                else:
                    # Use quote_size for SELL (less common, but supported)
                    quote_size_rounded = round(quantity, 2)
                    logger.info(f"📤 Placing SELL order: {symbol}, quote_size=${quote_size_rounded:.2f}")
                    if self.portfolio_uuid:
                        logger.info(f"   Routing to portfolio: {self.portfolio_uuid[:8]}...")
                    
                    order = _with_backoff(
                        self.client.market_order_sell,
                        client_order_id,
                        product_id=symbol,
                        quote_size=str(quote_size_rounded)
                    )
            
            # CRITICAL: Parse order response to check for success/failure
            # Coinbase returns an object with 'success' field and 'error_response'
            # Use helper to safely serialize the response
            order_dict = _serialize_object_to_dict(order)

            # If SDK returns a stringified dict, coerce it to a dict to avoid false positives
            if isinstance(order_dict, str):
                try:
                    order_dict = json.loads(order_dict)
                except Exception:
                    try:
                        import ast
                        order_dict = ast.literal_eval(order_dict)
                    except Exception:
                        pass

            # Guard against SDK returning plain strings or unexpected types
            if not isinstance(order_dict, dict):
                logger.error("Received non-dict order response from Coinbase SDK")
                logger.error(f"   Raw response: {order_dict}")
                logger.error(f"   Response type: {type(order_dict)}")
                return {
                    "status": "error",
                    "error": "INVALID_ORDER_RESPONSE",
                    "message": "Coinbase SDK returned non-dict response",
                    "raw_response": str(order_dict)
                }
            
            # Check for Coinbase error response
            success = order_dict.get('success', True)
            error_response = order_dict.get('error_response', {})
            
            if not success or error_response:
                error_code = error_response.get('error', 'UNKNOWN_ERROR')
                error_message = error_response.get('message', 'Unknown error from broker')
                
                logger.error(f"❌ Trade failed for {symbol}:")
                logger.error(f"   Status: unfilled")
                logger.error(f"   Error: {error_message}")
                logger.error(f"   Full order response: {order_dict}")

                if error_code == 'INSUFFICIENT_FUND':
                    self._log_insufficient_fund_context(base_currency, quote_currency)
                elif error_code == 'INVALID_SIZE_PRECISION' and size_type == 'base':
                    # One-shot degradation retry: use stricter per-asset increment if available
                    logger.error(
                        f"   Hint: base_increment={base_increment} precision={precision} quantity={quantity} rounded={base_size_rounded}"
                    )
                    stricter_map = {
                        'APT': 0.001,
                        'NEAR': 0.0001,
                        'ICP': 0.0001,
                        'AAVE': 0.01,
                    }
                    base_currency = symbol.split('-')[0].upper()
                    alt_inc = stricter_map.get(base_currency)
                    if alt_inc and (base_increment is None or alt_inc != base_increment):
                        try:
                            from decimal import Decimal, ROUND_DOWN, getcontext
                            getcontext().prec = 18
                            step2 = Decimal(str(alt_inc))

                            # Recompute safe trade qty based on same available snapshot
                            safety_epsilon2 = max(alt_inc, 1e-6)
                            safe_available2 = max(0.0, (available_base if 'available_base' in locals() else 0.0) - safety_epsilon2)
                            trade_qty2 = min(float(quantity), safe_available2)

                            qty2 = (Decimal(str(trade_qty2)) / step2).to_integral_value(rounding=ROUND_DOWN) * step2
                            base_size_rounded2 = float(qty2)
                            inc_str2 = f"{alt_inc:.16f}".rstrip('0').rstrip('.')
                            precision2 = len(inc_str2.split('.')[1]) if '.' in inc_str2 else 0
                            logger.info(f"   Retry with alt increment {alt_inc} (precision {precision2}) → {base_size_rounded2}")

                            order2 = self.client.market_order_sell(
                                client_order_id,
                                product_id=symbol,
                                base_size=str(base_size_rounded2)
                            )
                            order_dict2 = _serialize_object_to_dict(order2)
                            if isinstance(order_dict2, str):
                                try:
                                    order_dict2 = json.loads(order_dict2)
                                except Exception:
                                    try:
                                        import ast
                                        order_dict2 = ast.literal_eval(order_dict2)
                                    except Exception:
                                        pass

                            success2 = isinstance(order_dict2, dict) and order_dict2.get('success', True) and not order_dict2.get('error_response')
                            if success2:
                                logger.info(f"✅ Order filled successfully (retry): {symbol}")
                                return {
                                    "status": "filled",
                                    "order": order_dict2,
                                    "filled_size": base_size_rounded2
                                }
                            else:
                                logger.error(f"   Retry failed: {order_dict2}")
                        except Exception as retry_err:
                            logger.error(f"   Retry with stricter increment failed: {retry_err}")

                # Generic fallback: decrement by one increment and retry a few times
                if size_type == 'base' and base_increment and error_code in ('INVALID_SIZE_PRECISION', 'INSUFFICIENT_FUND', 'PREVIEW_INVALID_SIZE_PRECISION', 'PREVIEW_INSUFFICIENT_FUND'):
                    try:
                        from decimal import Decimal, ROUND_DOWN, getcontext
                        getcontext().prec = 18
                        step = Decimal(str(base_increment))

                        max_attempts = 5
                        current_qty = Decimal(str(base_size_rounded if 'base_size_rounded' in locals() else quantity))
                        for attempt in range(1, max_attempts + 1):
                            # Reduce by one increment per attempt and quantize down
                            reduced = current_qty - step * attempt
                            if reduced <= Decimal('0'):
                                break
                            qtry = (reduced / step).to_integral_value(rounding=ROUND_DOWN) * step
                            new_size = float(qtry)
                            logger.info(f"   Fallback attempt {attempt}/{max_attempts}: base_size → {new_size} (decrement by {attempt}×{base_increment})")

                            order_try = self.client.market_order_sell(
                                client_order_id,
                                product_id=symbol,
                                base_size=str(new_size)
                            )
                            od_try = _serialize_object_to_dict(order_try)
                            if isinstance(od_try, str):
                                try:
                                    od_try = json.loads(od_try)
                                except Exception:
                                    try:
                                        import ast
                                        od_try = ast.literal_eval(od_try)
                                    except Exception:
                                        pass

                            if isinstance(od_try, dict) and od_try.get('success', True) and not od_try.get('error_response'):
                                logger.info(f"✅ Order filled successfully (fallback attempt {attempt}): {symbol}")
                                return {
                                    "status": "filled",
                                    "order": od_try,
                                    "filled_size": new_size
                                }
                            else:
                                emsg = od_try.get('error_response', {}).get('message') if isinstance(od_try, dict) else str(od_try)
                                logger.error(f"   Fallback attempt {attempt} failed: {emsg}")
                    except Exception as fb_err:
                        logger.error(f"   Fallback decrement retry failed: {fb_err}")
                
                return {
                    "status": "unfilled",
                    "error": error_code,
                    "message": error_message,
                    "order": order_dict,
                    "partial_fill": order_dict.get('partial_fill', False),
                    "filled_pct": order_dict.get('filled_pct', 0.0)
                }
            
            logger.info(f"✅ Order filled successfully: {symbol}")
            
            # Enhanced trade confirmation logging with account identification
            account_label = f"{self.account_identifier}" if hasattr(self, 'account_identifier') else "MASTER"
            
            logger.info("=" * 70)
            logger.info(f"✅ TRADE CONFIRMATION - {account_label}")
            logger.info("=" * 70)
            logger.info(f"   Exchange: Coinbase")
            logger.info(f"   Order Type: {side.upper()}")
            logger.info(f"   Symbol: {symbol}")
            logger.info(f"   Quantity: {quantity}")
            logger.info(f"   Size Type: {size_type}")
            logger.info(f"   Account: {account_label}")
            logger.info(f"   Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}")
            logger.info("=" * 70)
            
            # Flush logs immediately to ensure confirmation is visible
            if _root_logger.handlers:
                for handler in _root_logger.handlers:
                    handler.flush()
            
            # Extract or estimate filled size
            # Coinbase API v3 doesn't return filled_size in the response,
            # so we estimate based on what we sent
            filled_size = None
            
            # Try to extract from success_response
            success_response = order_dict.get('success_response', {})
            if success_response:
                filled_size = success_response.get('filled_size')
            
            # If not available, estimate based on order configuration
            if not filled_size:
                order_config = order_dict.get('order_configuration', {})
                market_config = order_config.get('market_market_ioc', {})
                
                if side.upper() == 'BUY' and 'quote_size' in market_config:
                    # For buy orders, estimate crypto received = quote_size / price
                    try:
                        quote_size = float(market_config['quote_size'])
                        # RATE LIMIT FIX: Wrap get_product with rate limiter to prevent 429 errors
                        def _fetch_price_data():
                            return self.client.get_product(symbol)
                        
                        if self._rate_limiter:
                            price_data = self._rate_limiter.call('get_product', _fetch_price_data)
                        else:
                            price_data = _fetch_price_data()
                        
                        if price_data and 'price' in price_data:
                            current_price = float(price_data['price'])
                            filled_size = quote_size / current_price
                    except:
                        # Fallback: use quantity as estimate
                        filled_size = quantity
                else:
                    # For sell orders or unknown, use quantity as estimate
                    filled_size = quantity
            
            if filled_size:
                logger.info(f"   Filled crypto amount: {filled_size:.6f}")
            
            # CRITICAL: Track position for profit-based exits
            if self.position_tracker:
                try:
                    if side.lower() == 'buy':
                        # Track entry for profit calculation
                        # Try to get actual fill price from order response first
                        fill_price = None
                        
                        # Try to extract actual fill price from success_response
                        if success_response and 'average_filled_price' in success_response:
                            try:
                                fill_price = float(success_response['average_filled_price'])
                            except:
                                pass
                        
                        # Fallback to current market price if fill price not available
                        if not fill_price or fill_price == 0:
                            fill_price = self.get_current_price(symbol)
                        
                        if fill_price > 0:
                            size_usd = quantity if size_type == 'quote' else (filled_size * fill_price if filled_size else 0)
                            self.position_tracker.track_entry(
                                symbol=symbol,
                                entry_price=fill_price,
                                quantity=filled_size if filled_size else 0,
                                size_usd=size_usd,
                                strategy="APEX_v7.1"
                            )
                            logger.info(f"   📊 Position tracked: entry=${fill_price:.2f}, size=${size_usd:.2f}")
                            
                            # Log BUY trade to journal
                            self._log_trade_to_journal(
                                symbol=symbol,
                                side='BUY',
                                price=fill_price,
                                size_usd=size_usd,
                                quantity=filled_size if filled_size else 0
                            )
                    else:
                        # Get P&L before tracking exit
                        fill_price = None
                        if success_response and 'average_filled_price' in success_response:
                            try:
                                fill_price = float(success_response['average_filled_price'])
                            except:
                                pass
                        if not fill_price or fill_price == 0:
                            fill_price = self.get_current_price(symbol)
                        
                        # Calculate P&L for this exit
                        pnl_data = None
                        if fill_price and fill_price > 0:
                            pnl_data = self.position_tracker.calculate_pnl(symbol, fill_price)
                            if pnl_data:
                                logger.info(f"   💰 Exit P&L: ${pnl_data['pnl_dollars']:+.2f} ({pnl_data['pnl_percent']:+.2f}%)")
                        
                        # Track exit (partial or full sell)
                        self.position_tracker.track_exit(
                            symbol=symbol,
                            exit_quantity=filled_size if filled_size else None
                        )
                        logger.info(f"   📊 Position exit tracked")
                        
                        # Log SELL trade to journal with P&L
                        self._log_trade_to_journal(
                            symbol=symbol,
                            side='SELL',
                            price=fill_price if fill_price else 0,
                            size_usd=quantity if size_type == 'quote' else (filled_size * fill_price if filled_size and fill_price else 0),
                            quantity=filled_size if filled_size else 0,
                            pnl_data=pnl_data
                        )
                except Exception as track_err:
                    logger.warning(f"   ⚠️ Position tracking failed: {track_err}")
            
            # COPY TRADING: Emit trade signal for master account trades
            # This allows user accounts to replicate master trades automatically
            try:
                # Only emit signals for MASTER accounts (not USER accounts)
                if self.account_type == AccountType.MASTER:
                    from trade_signal_emitter import emit_trade_signal
                    
                    # Get current balance for position sizing
                    balance_data = self._get_account_balance_detailed()
                    master_balance = balance_data.get('trading_balance', 0.0) if balance_data else 0.0
                    
                    # Get execution price
                    exec_price = fill_price if (fill_price and fill_price > 0) else self.get_current_price(symbol)
                    
                    # Determine broker name
                    broker_name = self.broker_type.value.lower() if hasattr(self, 'broker_type') else 'coinbase'
                    
                    # ✅ FIX 5: VERIFY COPY ENGINE SIGNAL EMISSION
                    logger.info("📡 Emitting trade signal to copy engine")
                    
                    # Emit signal
                    signal_emitted = emit_trade_signal(
                        broker=broker_name,
                        symbol=symbol,
                        side=side,
                        price=exec_price if exec_price else 0.0,
                        size=quantity,
                        size_type=size_type,
                        order_id=order_dict.get('order_id', client_order_id),
                        master_balance=master_balance
                    )
                    
                    # ✅ FIX 5: CONFIRM SIGNAL EMISSION STATUS
                    if signal_emitted:
                        logger.info(f"✅ Trade signal emitted successfully for {symbol} {side}")
                    else:
                        logger.error(f"❌ Trade signal emission FAILED for {symbol} {side}")
                        logger.error("   ⚠️ User accounts will NOT copy this trade!")
            except Exception as signal_err:
                # Don't fail the trade if signal emission fails
                logger.warning(f"   ⚠️ Trade signal emission failed: {signal_err}")
                logger.warning(f"   ⚠️ User accounts will NOT copy this trade!")
                logger.warning(f"   Traceback: {traceback.format_exc()}")
            
            return {
                "status": "filled", 
                "order": order_dict,
                "filled_size": float(filled_size) if filled_size else 0.0
            }
            
        except Exception as e:
            # Enhanced error logging with full details
            error_msg = str(e)
            error_type = type(e).__name__
            logger.error(f"🚨 Coinbase order error for {symbol}:")
            logger.error(f"   Type: {error_type}")
            logger.error(f"   Message: {error_msg}")
            logger.error(f"   Side: {side}, Quantity: {quantity}")
            
            # Log additional context if available
            if hasattr(e, 'response'):
                logger.error(f"   Response: {e.response}")
            if hasattr(e, 'status_code'):
                logger.error(f"   Status code: {e.status_code}")
                
            return {"status": "error", "error": f"{error_type}: {error_msg}"}

    def force_liquidate(
        self,
        symbol: str,
        quantity: float,
        reason: str = "Emergency liquidation"
    ) -> Dict:
        """
        🚑 EMERGENCY SELL OVERRIDE - Force liquidate position bypassing ALL checks.
        
        This is the FIX 1 implementation that allows NIJA to exit losing positions
        immediately without being blocked by balance validation or minimum trade limits.
        
        CRITICAL: This method MUST be used for emergency exits and losing trades.
        It bypasses:
        - Balance checks (ignore_balance=True)
        - Minimum trade size validation (ignore_min_trade=True)
        - All other validation that could prevent exit
        
        Args:
            symbol: Trading symbol (e.g., 'BTC-USD')
            quantity: Quantity to sell (in base currency)
            reason: Reason for forced liquidation (for logging)
        
        Returns:
            Order result dict with status
        """
        logger.warning("=" * 70)
        logger.warning(f"🚑 FORCE LIQUIDATE: {symbol}")
        logger.warning(f"   Reason: {reason}")
        logger.warning(f"   Quantity: {quantity}")
        logger.warning(f"   ⚠️  ALL VALIDATION BYPASSED - EMERGENCY EXIT")
        logger.warning("=" * 70)
        
        try:
            # Force market sell with ALL checks bypassed
            # This uses place_market_order but with special flags
            result = self.place_market_order(
                symbol=symbol,
                side='sell',
                quantity=quantity,
                size_type='base',
                ignore_balance=True,      # ← REQUIRED: Bypass balance validation
                ignore_min_trade=True,    # ← REQUIRED: Bypass minimum trade size
                force_liquidate=True      # ← REQUIRED: Bypass all other checks
            )
            
            if result.get('status') == 'filled':
                logger.warning(f"✅ FORCE LIQUIDATE SUCCESSFUL: {symbol}")
            else:
                logger.error(f"❌ FORCE LIQUIDATE FAILED: {symbol} - {result.get('error', 'Unknown error')}")
            
            return result
            
        except Exception as e:
            logger.error(f"❌ FORCE LIQUIDATE EXCEPTION: {symbol} - {e}")
            logger.error(traceback.format_exc())
            return {
                "status": "error",
                "error": str(e),
                "symbol": symbol
            }
    
    def close_position(
        self,
        symbol: str,
        base_size: Optional[float] = None,
        *,
        side: str = 'sell',
        quantity: Optional[float] = None,
        size_type: str = 'base',
        **_: Dict
    ) -> Dict:
        """Close a position by submitting a market order.

        Accepts both legacy (symbol, base_size) calls and newer keyword-based
        calls that provide ``side``/``quantity``/``size_type``. Defaults to
        selling a base-size amount when only ``base_size`` is provided.
        """
        # Prefer explicitly provided quantity; fall back to legacy base_size
        size = quantity if quantity is not None else base_size
        if size is None:
            raise ValueError("close_position requires a quantity or base_size")

        try:
            return self.place_market_order(
                symbol,
                side.lower() if side else 'sell',
                size,
                size_type=size_type or 'base'
            )
        except TypeError:
            # Graceful fallback if upstream signatures drift
            return self.place_market_order(symbol, 'sell', size, size_type='base')
    
    def get_positions(self) -> List[Dict]:
        """Return tradable crypto positions with base quantities.

        Prefers portfolio breakdown (Advanced Trade) for accurate, tradable amounts.
        Falls back to get_accounts() if breakdown is unavailable.
        """
        positions: List[Dict] = []

        # Preferred: Use portfolio breakdown to derive base quantities
        try:
            # RATE LIMIT FIX: Wrap get_portfolios with rate limiter to prevent 429 errors
            portfolios_resp = None
            if hasattr(self.client, 'get_portfolios'):
                portfolios_resp = self._api_call_with_retry(self.client.get_portfolios)
            
            portfolios = getattr(portfolios_resp, 'portfolios', [])
            if isinstance(portfolios_resp, dict):
                portfolios = portfolios_resp.get('portfolios', [])

            default_portfolio = None
            for pf in portfolios:
                pf_type = getattr(pf, 'type', None) if not isinstance(pf, dict) else pf.get('type')
                if str(pf_type).upper() == 'DEFAULT':
                    default_portfolio = pf
                    break
            if not default_portfolio and portfolios:
                default_portfolio = portfolios[0]

            portfolio_uuid = None
            if default_portfolio:
                portfolio_uuid = getattr(default_portfolio, 'uuid', None)
                if isinstance(default_portfolio, dict):
                    portfolio_uuid = default_portfolio.get('uuid', portfolio_uuid)

            if default_portfolio and portfolio_uuid:
                # RATE LIMIT FIX: Wrap get_portfolio_breakdown with retry logic to prevent 429 errors
                breakdown_resp = self._api_call_with_retry(
                    self.client.get_portfolio_breakdown,
                    portfolio_uuid=portfolio_uuid
                )
                breakdown = getattr(breakdown_resp, 'breakdown', None)
                if isinstance(breakdown_resp, dict):
                    breakdown = breakdown_resp.get('breakdown', breakdown)

                spot_positions = getattr(breakdown, 'spot_positions', []) if breakdown else []
                if isinstance(breakdown, dict):
                    spot_positions = breakdown.get('spot_positions', spot_positions)

                for pos in spot_positions:
                    asset = getattr(pos, 'asset', None) if not isinstance(pos, dict) else pos.get('asset')

                    # Skip fiat assets; we only return crypto positions
                    if not asset or asset in ['USD', 'USDC']:
                        continue

                    # Try to fetch base available to trade; if not present, derive from fiat value
                    base_avail = None
                    if isinstance(pos, dict):
                        base_avail = pos.get('available_to_trade') or pos.get('available_to_trade_base')
                        fiat_avail = pos.get('available_to_trade_fiat')
                    else:
                        base_avail = getattr(pos, 'available_to_trade', None) or getattr(pos, 'available_to_trade_base', None)
                        fiat_avail = getattr(pos, 'available_to_trade_fiat', None)

                    quantity = 0.0
                    try:
                        if base_avail is not None:
                            quantity = float(base_avail or 0)
                        else:
                            # Derive base qty from fiat using current price
                            fiat_val = float(fiat_avail or 0)
                            if fiat_val > 0:
                                symbol = f"{asset}-USD"
                                price = self.get_current_price(symbol)
                                if price > 0:
                                    quantity = fiat_val / price
                    except Exception:
                        quantity = 0.0

                    # CRITICAL FIX: Skip true dust positions to match enforcer
                    # Calculate USD value to filter consistently
                    if quantity > 0:
                        position_symbol = f"{asset}-USD"
                        try:
                            price = self.get_current_price(position_symbol)
                            usd_value = quantity * price if price > 0 else 0
                            # Only skip TRUE dust - count all other positions
                            if usd_value < DUST_THRESHOLD_USD:
                                logger.debug(f"Skipping dust position {position_symbol}: qty={quantity}, value=${usd_value:.4f}")
                                continue
                        except Exception:
                            # If we can't get price, include it anyway to be safe
                            pass
                        
                        positions.append({
                            'symbol': position_symbol,
                            'quantity': quantity,
                            'currency': asset
                        })

                # If we built positions from breakdown, return them
                if positions:
                    return positions
        except Exception as e:
            logger.warning(f"⚠️ Portfolio breakdown unavailable, falling back to get_accounts(): {e}")

        # Fallback: Use get_accounts available balances
        try:
            # RATE LIMIT FIX: Wrap get_accounts with retry logic to prevent 429 errors
            accounts = self._api_call_with_retry(self.client.get_accounts)
            # Handle both dict and object responses from Coinbase SDK
            accounts_list = accounts.get('accounts') if isinstance(accounts, dict) else getattr(accounts, 'accounts', [])

            for account in accounts_list:
                if isinstance(account, dict):
                    currency = account.get('currency')
                    balance = float(account.get('available_balance', {}).get('value', 0)) if account.get('available_balance') else 0
                else:
                    currency = getattr(account, 'currency', None)
                    balance_obj = getattr(account, 'available_balance', {})
                    balance = float(balance_obj.get('value', 0)) if isinstance(balance_obj, dict) else float(getattr(balance_obj, 'value', 0)) if balance_obj else 0

                # CRITICAL FIX: Apply same dust filtering as primary path
                if currency and currency not in ['USD', 'USDC'] and balance > 0:
                    # Calculate USD value to filter consistently
                    position_symbol = f"{currency}-USD"
                    try:
                        price = self.get_current_price(position_symbol)
                        usd_value = balance * price if price > 0 else 0
                        # Only skip TRUE dust - count all other positions
                        if usd_value < DUST_THRESHOLD_USD:
                            logger.debug(f"Skipping dust position {position_symbol}: qty={balance}, value=${usd_value:.4f}")
                            continue
                    except Exception:
                        # If we can't get price, include it anyway to be safe
                        pass
                    
                    positions.append({
                        'symbol': position_symbol,
                        'quantity': balance,
                        'currency': currency
                    })
            return positions
        except Exception as e:
            logger.error(f"Error fetching positions: {e}")
            return []
    
    def get_market_data(self, symbol: str, timeframe: str = '5m', limit: int = 100) -> Dict:
        """
        Get market data (wrapper around get_candles for compatibility)
        Returns dict with 'candles' key containing list of candle dicts
        """
        candles = self.get_candles(symbol, timeframe, limit)
        return {'candles': candles}

    def get_current_price(self, symbol: str) -> float:
        """Fetch latest trade/last candle price for a product."""
        try:
            # CRITICAL FIX (Jan 19, 2026): Normalize symbol for Coinbase format
            # This prevents cross-broker symbol issues (e.g., using Binance BUSD symbols on Coinbase)
            normalized_symbol = normalize_symbol_for_broker(symbol, self.broker_type.value)
            
            # Check if broker supports this symbol (e.g., Coinbase doesn't support BUSD)
            if not self.supports_symbol(normalized_symbol):
                logger.info(f"⏭️ Skipping unsupported symbol {symbol} on Coinbase (normalized: {normalized_symbol})")
                return 0.0
            
            # Fast path: product ticker price
            try:
                # RATE LIMIT FIX: Wrap get_product with rate limiter to prevent 429 errors
                def _fetch_product_price():
                    return self.client.get_product(normalized_symbol)
                
                if self._rate_limiter:
                    product = self._rate_limiter.call('get_product', _fetch_product_price)
                else:
                    product = _fetch_product_price()
                
                price_val = product.get('price') if isinstance(product, dict) else getattr(product, 'price', None)
                if price_val:
                    return float(price_val)
            except Exception:
                # Ignore and fall back to candles
                pass

            # Fallback: last close from 1m candle
            candles = self.get_candles(normalized_symbol, '1m', 1)
            if candles:
                last = candles[-1]
                close = last.get('close') if isinstance(last, dict) else getattr(last, 'close', None)
                if close:
                    return float(close)
            raise RuntimeError("No price data available")
        except Exception as e:
            logging.error(f"⚠️ get_current_price failed for {symbol}: {e}")
            return 0.0
    
    def get_candles(self, symbol: str, timeframe: str, count: int) -> List[Dict]:
        """Get candle data with rate limiting and retry logic
        
        UPDATED (Jan 9, 2026): Added RateLimiter integration to prevent 403/429 errors
        - Uses centralized rate limiter (10 req/min for candles = 1 every 6 seconds)
        - Reduced max retries from 6 to 3 for 403 errors (API key ban, not transient)
        - 429 errors get standard retry with exponential backoff
        - Rate limiter prevents cascading retries that trigger API key bans
        
        UPDATED (Jan 11, 2026): Added invalid symbol caching to prevent repeated API calls
        - Caches known invalid symbols to avoid wasted API calls
        - Reduces log pollution from Coinbase SDK error messages
        """
        
        # CRITICAL FIX (Jan 11, 2026): Check invalid symbols cache first
        # If symbol is known to be invalid, skip API call entirely
        if symbol in self._invalid_symbols_cache:
            logging.debug(f"⚠️  Skipping cached invalid symbol: {symbol}")
            return []
        
        # Wrapper function for rate-limited API call
        def _fetch_candles():
            granularity_map = {
                "1m": "ONE_MINUTE",
                "5m": "FIVE_MINUTE",
                "15m": "FIFTEEN_MINUTE",
                "1h": "ONE_HOUR",
                "1d": "ONE_DAY"
            }
            
            granularity = granularity_map.get(timeframe, "FIVE_MINUTE")
            
            end = int(time.time())
            start = end - (300 * count)  # 5 min candles
            
            candles = self.client.get_candles(
                product_id=symbol,
                start=start,
                end=end,
                granularity=granularity
            )
            
            if hasattr(candles, 'candles'):
                return [vars(c) for c in candles.candles]
            elif isinstance(candles, dict) and 'candles' in candles:
                return candles['candles']
            return []
        
        # Use rate limiter if available
        for attempt in range(RATE_LIMIT_MAX_RETRIES):
            try:
                if self._rate_limiter:
                    # Rate-limited call - automatically enforces minimum interval between requests
                    return self._rate_limiter.call('get_candles', _fetch_candles)
                else:
                    # Fallback to direct call without rate limiting
                    return _fetch_candles()
                
            except Exception as e:
                error_str = str(e).lower()
                
                # CRITICAL FIX (Jan 10, 2026): Distinguish invalid symbols from rate limits
                # Invalid symbols should not trigger retries or count toward rate limit errors
                # This prevents delisted coins from causing circuit breaker activation
                
                # Check for invalid product/symbol errors using shared detection logic
                is_invalid_symbol = _is_invalid_product_error(str(e))
                
                # If invalid symbol, don't retry - just skip it
                if is_invalid_symbol:
                    # CRITICAL FIX (Jan 11, 2026): Cache invalid symbol to prevent future API calls
                    self._invalid_symbols_cache.add(symbol)
                    logging.debug(f"⚠️  Invalid/delisted symbol: {symbol} - cached and skipping")
                    return []  # Return empty to signal "no data" without counting as error
                
                # Distinguish between 429 (rate limit) and 403 (too many errors / temporary ban)
                is_403_forbidden = '403' in error_str or 'forbidden' in error_str or 'too many errors' in error_str
                is_429_rate_limit = '429' in error_str or 'rate limit' in error_str or 'too many requests' in error_str
                is_rate_limited = is_403_forbidden or is_429_rate_limit
                
                if is_rate_limited and attempt < RATE_LIMIT_MAX_RETRIES - 1:
                    # Different handling for 403 vs 429
                    if is_403_forbidden:
                        # 403 "too many errors" means API key was temporarily blocked
                        # Don't retry aggressively - the key needs time to unblock
                        # Use fixed delay with jitter
                        total_delay = FORBIDDEN_BASE_DELAY + random.uniform(0, FORBIDDEN_JITTER_MAX)
                        logging.warning(f"⚠️  API key temporarily blocked (403) on {symbol}, waiting {total_delay:.1f}s before retry {attempt+1}/{RATE_LIMIT_MAX_RETRIES}")
                    else:
                        # 429 rate limit - exponential backoff
                        retry_delay = RATE_LIMIT_BASE_DELAY * (2 ** attempt)
                        jitter = random.uniform(0, retry_delay * 0.3)  # 30% jitter
                        total_delay = retry_delay + jitter
                        logging.warning(f"⚠️  Rate limited (429) on {symbol}, retrying in {total_delay:.1f}s (attempt {attempt+1}/{RATE_LIMIT_MAX_RETRIES})")
                    
                    time.sleep(total_delay)
                    continue
                else:
                    if attempt == RATE_LIMIT_MAX_RETRIES - 1:
                        # Only log as debug - this is expected during rate limiting
                        logging.debug(f"Failed to fetch candles for {symbol} after {RATE_LIMIT_MAX_RETRIES} attempts")
                    else:
                        # Only log non-rate-limit errors as errors
                        if not is_rate_limited:
                            logging.error(f"Error fetching candles for {symbol}: {e}")
                    return []
        
        return []
    
    def supports_asset_class(self, asset_class: str) -> bool:
        """Coinbase supports crypto only"""
        return asset_class.lower() == "crypto"


class AlpacaBroker(BaseBroker):
    """
    Alpaca integration for stocks and crypto.
    
    Features:
    - Stock trading (US equities)
    - Crypto trading (select cryptocurrencies)
    - Paper and live trading modes
    - Multi-account support (master + user accounts)
    
    Documentation: https://alpaca.markets/docs/
    """
    
    def __init__(self, account_type: AccountType = AccountType.MASTER, user_id: Optional[str] = None):
        """
        Initialize Alpaca broker with account type support.
        
        Args:
            account_type: MASTER for Nija system account, USER for individual user accounts
            user_id: User ID for USER account_type (e.g., 'tania_gilbert')
            
        Raises:
            ValueError: If account_type is USER but user_id is not provided
        """
        super().__init__(BrokerType.ALPACA, account_type=account_type, user_id=user_id)
        
        # Validate that USER account_type has user_id
        if account_type == AccountType.USER and not user_id:
            raise ValueError("USER account_type requires user_id parameter")
        
        self.api = None
        
        # Set identifier for logging
        if account_type == AccountType.MASTER:
            self.account_identifier = "MASTER"
        else:
            self.account_identifier = f"USER:{user_id}" if user_id else "USER:unknown"
    
    @property
    def client(self):
        """Alias for self.api to maintain consistency with other brokers"""
        return self.api
    
    def connect(self) -> bool:
        """
        Connect to Alpaca API with retry logic.
        
        Uses different credentials based on account_type:
        - MASTER: ALPACA_API_KEY / ALPACA_API_SECRET / ALPACA_PAPER
        - USER: ALPACA_USER_{user_id}_API_KEY / ALPACA_USER_{user_id}_API_SECRET / ALPACA_USER_{user_id}_PAPER
        
        Returns:
            bool: True if connected successfully
        """
        try:
            from alpaca.trading.client import TradingClient
            import time
            
            # Get credentials based on account type
            if self.account_type == AccountType.MASTER:
                api_key = os.getenv("ALPACA_API_KEY", "").strip()
                api_secret = os.getenv("ALPACA_API_SECRET", "").strip()
                paper = os.getenv("ALPACA_PAPER", "true").lower() == "true"
                cred_label = "MASTER"
            else:
                # User account - construct env var name from user_id
                # Convert user_id to uppercase for env var
                # For user_id like 'tania_gilbert', extracts 'TANIA' for ALPACA_USER_TANIA_API_KEY
                # For user_id like 'john', uses 'JOHN' for ALPACA_USER_JOHN_API_KEY
                user_env_name = self.user_id.split('_')[0].upper() if '_' in self.user_id else self.user_id.upper()
                api_key = os.getenv(f"ALPACA_USER_{user_env_name}_API_KEY", "").strip()
                api_secret = os.getenv(f"ALPACA_USER_{user_env_name}_API_SECRET", "").strip()
                paper_str = os.getenv(f"ALPACA_USER_{user_env_name}_PAPER", "true").strip()
                paper = paper_str.lower() == "true"
                cred_label = f"USER:{self.user_id}"
            
            if not api_key or not api_secret:
                # Mark that credentials were not configured (not an error, just not set up)
                self.credentials_configured = False
                # Silently skip - Alpaca is optional
                logger.info(f"⚠️  Alpaca credentials not configured for {cred_label} (skipping)")
                if self.account_type == AccountType.MASTER:
                    logger.info("   To enable Alpaca MASTER trading, set:")
                    logger.info("      ALPACA_API_KEY=<your-api-key>")
                    logger.info("      ALPACA_API_SECRET=<your-api-secret>")
                    logger.info("      ALPACA_PAPER=true  # or false for live trading")
                else:
                    # USER account - provide specific instructions
                    logger.info(f"   To enable Alpaca USER trading for {self.user_id}, set:")
                    logger.info(f"      ALPACA_USER_{user_env_name}_API_KEY=<your-api-key>")
                    logger.info(f"      ALPACA_USER_{user_env_name}_API_SECRET=<your-api-secret>")
                    logger.info(f"      ALPACA_USER_{user_env_name}_PAPER=true  # or false for live trading")
                return False
            
            # Log connection mode
            mode_str = "PAPER" if paper else "LIVE"
            logging.info(f"📊 Attempting to connect Alpaca {cred_label} ({mode_str} mode)...")
            
            self.api = TradingClient(api_key, api_secret, paper=paper)
            
            # Mark that credentials were configured (we have API key and secret)
            self.credentials_configured = True
            
            # Test connection with retry logic
            # Increased max attempts for 403 "too many errors" which indicates temporary API key blocking
            # Note: 403 differs from 429 (rate limiting) - it means the API key was temporarily blocked
            max_attempts = 5
            base_delay = 5.0  # Increased from 2.0 to allow API key blocks to reset
            
            for attempt in range(1, max_attempts + 1):
                try:
                    if attempt > 1:
                        # Add delay before retry with exponential backoff
                        # For 403 errors, we need longer delays: 5s, 10s, 20s, 40s (attempts 2-5)
                        delay = base_delay * (2 ** (attempt - 2))
                        logging.info(f"🔄 Retrying Alpaca {cred_label} connection in {delay}s (attempt {attempt}/{max_attempts})...")
                        time.sleep(delay)
                    
                    account = self.api.get_account()
                    self.connected = True
                    
                    if attempt > 1:
                        logging.info(f"✅ Connected to Alpaca {cred_label} API (succeeded on attempt {attempt})")
                    else:
                        logging.info(f"✅ Alpaca {cred_label} connected ({'PAPER' if paper else 'LIVE'})")
                    
                    return True
                
                except Exception as e:
                    error_msg = str(e)
                    
                    # Special handling for paper trading being disabled
                    if "paper" in error_msg.lower() and "not" in error_msg.lower():
                        logging.warning(f"⚠️  Alpaca {cred_label} paper trading may be disabled or account not configured for paper trading")
                        logging.warning(f"   Try setting ALPACA{'_USER_' + user_env_name if self.account_type == AccountType.USER else ''}_PAPER=false for live trading")
                        return False
                    
                    # Check if error is retryable (rate limiting, network issues, 403 errors, etc.)
                    # CRITICAL: Include 403, forbidden, and "too many errors" as retryable
                    # These indicate API key blocking and need longer cooldown periods
                    is_retryable = any(keyword in error_msg.lower() for keyword in [
                        'timeout', 'connection', 'network', 'rate limit',
                        'too many requests', 'service unavailable',
                        '503', '504', '429', '403', 'forbidden', 
                        'too many errors', 'temporary', 'try again'
                    ])
                    
                    if is_retryable and attempt < max_attempts:
                        logging.warning(f"⚠️  Alpaca {cred_label} connection attempt {attempt}/{max_attempts} failed (retryable): {error_msg}")
                        continue
                    else:
                        logging.warning(f"⚠️  Alpaca {cred_label} connection failed: {e}")
                        return False
            
            # Should never reach here, but just in case
            logging.error(f"❌ Failed to connect to Alpaca {cred_label} after maximum retry attempts")
            return False
            
        except ImportError as e:
            # SDK not installed or import failed
            logging.error(f"❌ Alpaca connection failed ({self.account_identifier}): SDK import error")
            logging.error(f"   ImportError: {e}")
            logging.error("   The Alpaca SDK (alpaca-py) failed to import")
            logging.error("")
            logging.error("   📋 Troubleshooting steps:")
            logging.error("      1. Verify alpaca-py is in requirements.txt")
            logging.error("      2. Check deployment logs for package installation errors")
            logging.error("      3. Try manual install: pip install alpaca-py")
            logging.error("      4. Check for dependency conflicts with: pip check")
            return False
    
    def get_account_balance(self) -> float:
        """
        Get total equity (cash + position values) for Alpaca account.
        
        CRITICAL FIX (Rule #3): Balance = CASH + POSITION VALUE
        Returns total equity (available cash + position market value), not just cash.
        
        For Alpaca, the account object provides 'equity' which includes both cash and positions.
        This is the correct value to use for risk calculations and position sizing.
        
        Returns:
            float: Total equity (cash + positions)
        """
        try:
            account = self.api.get_account()
            
            # Alpaca provides 'equity' which is cash + position values
            # This is exactly what we need per Rule #3
            equity = float(account.equity)
            cash = float(account.cash)
            position_value = equity - cash
            
            # Enhanced logging to show breakdown
            logger.info("=" * 70)
            logger.info(f"💰 Alpaca Balance ({self.account_identifier}):")
            logger.info(f"   ✅ Cash: ${cash:.2f}")
            if position_value > 0:
                logger.info(f"   📊 Position Value: ${position_value:.2f}")
                logger.info(f"   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
                logger.info(f"   💎 TOTAL EQUITY: ${equity:.2f}")
            else:
                logger.info(f"   💎 TOTAL EQUITY: ${equity:.2f} (no positions)")
            logger.info("=" * 70)
            
            return equity
            
        except Exception as e:
            logger.error(f"Error fetching Alpaca balance: {e}")
            return 0.0
    
    def place_market_order(self, symbol: str, side: str, quantity: float) -> Dict:
        """Place market order"""
        try:
            from alpaca.trading.requests import MarketOrderRequest
            from alpaca.trading.enums import OrderSide, TimeInForce
            
            order_side = OrderSide.BUY if side.lower() == 'buy' else OrderSide.SELL
            
            order_data = MarketOrderRequest(
                symbol=symbol,
                qty=quantity,
                side=order_side,
                time_in_force=TimeInForce.DAY
            )
            
            order = self.api.submit_order(order_data)
            
            # Enhanced trade confirmation logging with account identification
            account_label = f"{self.account_identifier}" if hasattr(self, 'account_identifier') else "MASTER"
            
            logger.info("=" * 70)
            logger.info(f"✅ TRADE CONFIRMATION - {account_label}")
            logger.info("=" * 70)
            logger.info(f"   Exchange: Alpaca (Stocks)")
            logger.info(f"   Order Type: {side.upper()}")
            logger.info(f"   Symbol: {symbol}")
            logger.info(f"   Quantity: {quantity}")
            logger.info(f"   Order ID: {order.id if hasattr(order, 'id') else 'N/A'}")
            logger.info(f"   Account: {account_label}")
            logger.info(f"   Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}")
            logger.info("=" * 70)
            
            # Flush logs immediately to ensure confirmation is visible
            if _root_logger.handlers:
                for handler in _root_logger.handlers:
                    handler.flush()
            
            return {
                "status": "submitted",
                "order": order,
                "account": account_label  # Add account identification to result
            }
            
        except Exception as e:
            logger.error(f"Alpaca order error: {e}")
            return {"status": "error", "error": str(e)}
    
    def get_positions(self) -> List[Dict]:
        """Get open positions"""
        try:
            positions = self.api.get_all_positions()
            return [{
                'symbol': pos.symbol,
                'quantity': float(pos.qty),
                'avg_entry_price': float(pos.avg_entry_price),
                'market_value': float(pos.market_value),
                'unrealized_pl': float(pos.unrealized_pl)
            } for pos in positions]
        except Exception as e:
            logger.error(f"Error fetching positions: {e}")
            return []
    
    def get_candles(self, symbol: str, timeframe: str, count: int) -> List[Dict]:
        """Get candle data with retry logic for rate limiting"""
        # Import Alpaca SDK dependencies (method-level import to avoid import errors when SDK not installed)
        try:
            from alpaca.data.historical import StockHistoricalDataClient
            from alpaca.data.requests import StockBarsRequest
            from alpaca.data.timeframe import TimeFrame
            from datetime import datetime, timedelta
        except ImportError:
            logging.error("Alpaca SDK not installed. Run: pip install alpaca-py")
            return []
        
        # Get credentials and create client outside retry loop (doesn't change between retries)
        api_key = os.getenv("ALPACA_API_KEY")
        api_secret = os.getenv("ALPACA_API_SECRET")
        
        if not api_key or not api_secret:
            logging.error("Alpaca API credentials not configured")
            return []
        
        data_client = StockHistoricalDataClient(api_key, api_secret)
        
        # Timeframe mapping (constant for all retries)
        timeframe_map = {
            "1m": TimeFrame.Minute,
            "5m": TimeFrame(5, TimeFrame.Minute),
            "15m": TimeFrame(15, TimeFrame.Minute),
            "1h": TimeFrame.Hour,
            "1d": TimeFrame.Day
        }
        tf = timeframe_map.get(timeframe, TimeFrame(5, TimeFrame.Minute))
        
        # Retry loop for API call (1-based indexing for clearer log messages)
        for attempt in range(1, RATE_LIMIT_MAX_RETRIES + 1):
            try:
                request_params = StockBarsRequest(
                    symbol_or_symbols=symbol,
                    timeframe=tf,
                    start=datetime.now() - timedelta(days=7)
                )
                
                bars = data_client.get_stock_bars(request_params)
                
                candles = []
                for bar in bars[symbol]:
                    candles.append({
                        'time': bar.timestamp,
                        'open': float(bar.open),
                        'high': float(bar.high),
                        'low': float(bar.low),
                        'close': float(bar.close),
                        'volume': float(bar.volume)
                    })
                
                return candles[-count:] if len(candles) > count else candles
                
            except Exception as e:
                error_str = str(e).lower()
                
                # CRITICAL FIX (Jan 13, 2026): Use centralized error detection function
                # Alpaca returns various error messages for invalid/delisted stocks:
                # - "invalid symbol", "symbol not found", "asset not found"
                # - "No key SYMBOL was found" (common for delisted stocks)
                # These should not trigger retries or count toward rate limit errors
                is_invalid_symbol = _is_invalid_product_error(str(e))
                
                # Log invalid symbols at debug level (not error) since it's expected
                if is_invalid_symbol:
                    logging.debug(f"⚠️  Invalid/delisted stock symbol: {symbol} - skipping")
                    return []  # Return empty to signal "no data" without counting as error
                
                # Distinguish between 429 (rate limit) and 403 (too many errors / temporary ban)
                is_403_forbidden = '403' in error_str or 'forbidden' in error_str or 'too many errors' in error_str
                is_429_rate_limit = '429' in error_str or 'rate limit' in error_str or 'too many requests' in error_str
                is_rate_limited = is_403_forbidden or is_429_rate_limit
                
                if is_rate_limited and attempt < RATE_LIMIT_MAX_RETRIES:
                    # Different handling for 403 vs 429
                    if is_403_forbidden:
                        # 403 errors: Use fixed delay with jitter (API key temporarily blocked)
                        delay = FORBIDDEN_BASE_DELAY + random.uniform(0, FORBIDDEN_JITTER_MAX)
                        logging.warning(f"⚠️  Alpaca rate limit (403 Forbidden): API key temporarily blocked for {symbol}")
                        logging.warning(f"   Waiting {delay:.1f}s before retry {attempt}/{RATE_LIMIT_MAX_RETRIES}...")
                    else:
                        # 429 errors: Use exponential backoff with jitter (prevent thundering herd)
                        base_delay = RATE_LIMIT_BASE_DELAY * (2 ** (attempt - 1))
                        jitter = random.uniform(0, base_delay * 0.3)  # 30% jitter
                        delay = base_delay + jitter
                        logging.warning(f"⚠️  Alpaca rate limit (429): Too many requests for {symbol}")
                        logging.warning(f"   Waiting {delay:.1f}s before retry {attempt}/{RATE_LIMIT_MAX_RETRIES}...")
                    
                    time.sleep(delay)
                    continue
                else:
                    # Not rate limited or max retries reached
                    if is_rate_limited:
                        # Rate limit persisted after retries - log at WARNING level
                        logging.warning(f"⚠️  Alpaca rate limit exceeded for {symbol} after {RATE_LIMIT_MAX_RETRIES} retries")
                    else:
                        # Non-rate-limit error - log at ERROR level
                        logging.error(f"Error fetching candles for {symbol}: {e}")
                    return []
        
        return []
    
    def supports_asset_class(self, asset_class: str) -> bool:
        """Alpaca supports stocks"""
        return asset_class.lower() in ["stocks", "stock"]
    
    def get_all_products(self) -> list:
        """
        Get list of tradeable stock symbols from Alpaca.
        Note: Alpaca is for stocks, not crypto. Returns popular stock symbols.
        
        Returns:
            List of stock symbols (e.g., ['AAPL', 'MSFT', 'GOOGL', ...])
        """
        try:
            if not self.api:
                logging.warning("⚠️  Alpaca not connected, cannot fetch products")
                return []
            
            # Get all active assets from Alpaca
            from alpaca.trading.requests import GetAssetsRequest
            from alpaca.trading.enums import AssetClass, AssetStatus
            
            request = GetAssetsRequest(
                status=AssetStatus.ACTIVE,
                asset_class=AssetClass.US_EQUITY
            )
            
            assets = self.api.get_all_assets(request)
            
            # Extract tradeable symbols
            symbols = []
            for asset in assets:
                if asset.tradable and asset.status == AssetStatus.ACTIVE:
                    symbols.append(asset.symbol)
            
            logging.info(f"📊 Alpaca: Found {len(symbols)} tradeable stock symbols")
            return symbols
            
        except ImportError:
            logging.warning("⚠️  Alpaca SDK not available")
            return []
        except Exception as e:
            logging.warning(f"⚠️  Error fetching Alpaca products: {e}")
            # Return a fallback list of popular stocks
            fallback_stocks = [
                'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'TSLA', 'META', 'NVDA', 'JPM',
                'V', 'WMT', 'MA', 'DIS', 'NFLX', 'ADBE', 'PYPL', 'INTC',
                'CSCO', 'PFE', 'KO', 'NKE', 'BAC', 'XOM', 'T', 'VZ'
            ]
            logging.info(f"📊 Alpaca: Using fallback list of {len(fallback_stocks)} stock symbols")
            return fallback_stocks

class BinanceBroker(BaseBroker):
    """
    Binance Exchange integration for cryptocurrency spot trading.
    
    Features:
    - Spot trading (USDT pairs)
    - Market and limit orders
    - Real-time account balance
    - Historical candle data (OHLCV)
    
    Documentation: https://python-binance.readthedocs.io/
    """
    
    def __init__(self, account_type: AccountType = AccountType.MASTER, user_id: Optional[str] = None):
        super().__init__(BrokerType.BINANCE, account_type=account_type, user_id=user_id)
        self.client = None
    
    def connect(self) -> bool:
        """
        Connect to Binance API with retry logic.
        
        Requires environment variables:
        - BINANCE_API_KEY: Your Binance API key
        - BINANCE_API_SECRET: Your Binance API secret
        - BINANCE_USE_TESTNET: 'true' for testnet, 'false' for live (optional, default: false)
        
        Returns:
            bool: True if connected successfully
        """
        try:
            from binance.client import Client
            import time
            
            api_key = os.getenv("BINANCE_API_KEY", "").strip()
            api_secret = os.getenv("BINANCE_API_SECRET", "").strip()
            use_testnet = os.getenv("BINANCE_USE_TESTNET", "false").lower() in ["true", "1", "yes"]
            
            if not api_key or not api_secret:
                # Silently skip - Binance is optional, no need for scary error messages
                logging.info("⚠️  Binance credentials not configured (skipping)")
                return False
            
            # Initialize Binance client
            if use_testnet:
                # Testnet base URL
                self.client = Client(api_key, api_secret, testnet=True)
            else:
                self.client = Client(api_key, api_secret)
            
            # Test connection by fetching account status with retry logic
            # Increased max attempts for 403 "too many errors" which indicates temporary API key blocking
            # Note: 403 differs from 429 (rate limiting) - it means the API key was temporarily blocked
            max_attempts = 5
            base_delay = 5.0  # Increased from 2.0 to allow API key blocks to reset
            
            for attempt in range(1, max_attempts + 1):
                try:
                    if attempt > 1:
                        # Add delay before retry with exponential backoff
                        # For 403 errors, we need longer delays: 5s, 10s, 20s, 40s (attempts 2-5)
                        delay = base_delay * (2 ** (attempt - 2))
                        logging.info(f"🔄 Retrying Binance connection in {delay}s (attempt {attempt}/{max_attempts})...")
                        time.sleep(delay)
                    
                    account = self.client.get_account()
                    
                    if account:
                        self.connected = True
                        
                        if attempt > 1:
                            logging.info(f"✅ Connected to Binance API (succeeded on attempt {attempt})")
                        
                        env_type = "🧪 TESTNET" if use_testnet else "🔴 LIVE"
                        logging.info("=" * 70)
                        logging.info(f"✅ BINANCE CONNECTED ({env_type})")
                        logging.info("=" * 70)
                        
                        # Log account trading status
                        can_trade = account.get('canTrade', False)
                        logging.info(f"   Trading Enabled: {'✅' if can_trade else '❌'}")
                        
                        # Log USDT balance
                        for balance in account.get('balances', []):
                            if balance['asset'] == 'USDT':
                                usdt_balance = float(balance['free'])
                                logging.info(f"   USDT Balance: ${usdt_balance:.2f}")
                                break
                        
                        logging.info("=" * 70)
                        return True
                    else:
                        if attempt < max_attempts:
                            logging.warning(f"⚠️  Binance connection attempt {attempt}/{max_attempts} failed (retryable): No account data returned")
                            continue
                        else:
                            logging.warning("⚠️  Binance connection test failed: No account data returned")
                            return False
                
                except Exception as e:
                    error_msg = str(e)
                    
                    # Check if error is retryable (rate limiting, network issues, 403 errors, etc.)
                    # CRITICAL: Include 403, forbidden, and "too many errors" as retryable
                    # These indicate API key blocking and need longer cooldown periods
                    is_retryable = any(keyword in error_msg.lower() for keyword in [
                        'timeout', 'connection', 'network', 'rate limit',
                        'too many requests', 'service unavailable',
                        '503', '504', '429', '403', 'forbidden', 
                        'too many errors', 'temporary', 'try again'
                    ])
                    
                    if is_retryable and attempt < max_attempts:
                        logging.warning(f"⚠️  Binance connection attempt {attempt}/{max_attempts} failed (retryable): {error_msg}")
                        continue
                    else:
                        # Handle authentication errors gracefully
                        error_str = error_msg.lower()
                        if 'api' in error_str and ('key' in error_str or 'signature' in error_str or 'authentication' in error_str):
                            logging.warning("⚠️  Binance authentication failed - invalid or expired API credentials")
                            logging.warning("   Please check your BINANCE_API_KEY and BINANCE_API_SECRET")
                        elif 'connection' in error_str or 'network' in error_str or 'timeout' in error_str:
                            logging.warning("⚠️  Binance connection failed - network issue or API unavailable")
                        else:
                            logging.warning(f"⚠️  Binance connection failed: {e}")
                        return False
            
            # Should never reach here, but just in case
            logging.error("❌ Failed to connect to Binance after maximum retry attempts")
            return False
                
        except ImportError as e:
            # SDK not installed or import failed
            logging.error("❌ Binance connection failed: SDK import error")
            logging.error(f"   ImportError: {e}")
            logging.error("   The Binance SDK (python-binance) failed to import")
            logging.error("")
            logging.error("   📋 Troubleshooting steps:")
            logging.error("      1. Verify python-binance is in requirements.txt")
            logging.error("      2. Check deployment logs for package installation errors")
            logging.error("      3. Try manual install: pip install python-binance")
            logging.error("      4. Check for dependency conflicts with: pip check")
            return False
    
    def get_account_balance(self) -> float:
        """
        Get USDT balance available for trading.
        
        Returns:
            float: Available USDT balance
        """
        try:
            if not self.client:
                return 0.0
            
            # Get account balances
            account = self.client.get_account()
            
            # Find USDT balance
            for balance in account.get('balances', []):
                if balance['asset'] == 'USDT':
                    available = float(balance.get('free', 0))
                    logging.info(f"💰 Binance USDT Balance: ${available:.2f}")
                    return available
            
            # No USDT found
            logging.warning("⚠️  No USDT balance found in Binance account")
            return 0.0
            
        except Exception as e:
            logging.error(f"Error fetching Binance balance: {e}")
            return 0.0
    
    def place_market_order(self, symbol: str, side: str, quantity: float) -> Dict:
        """
        Place market order on Binance.
        
        Args:
            symbol: Trading pair (e.g., 'BTC-USD' or 'BTCUSDT')
            side: 'buy' or 'sell'
            quantity: Order size in USDT (for buys) or base currency (for sells)
        
        Returns:
            dict: Order result with status, order_id, etc.
        """
        try:
            if not self.client:
                return {"status": "error", "error": "Not connected to Binance"}
            
            # Convert symbol format (BTC-USD -> BTCUSDT)
            binance_symbol = symbol.replace('-USD', 'USDT').replace('-', '')
            
            # Binance uses uppercase for side
            binance_side = side.upper()
            
            # Place market order
            # Note: Binance requires 'quantity' parameter for market orders
            # For buy orders, you may want to use quoteOrderQty instead
            if binance_side == 'BUY':
                # Use quoteOrderQty for buy orders (spend X USDT)
                order = self.client.order_market_buy(
                    symbol=binance_symbol,
                    quoteOrderQty=quantity
                )
            else:
                # Use quantity for sell orders (sell X crypto)
                order = self.client.order_market_sell(
                    symbol=binance_symbol,
                    quantity=quantity
                )
            
            if order:
                order_id = order.get('orderId')
                status = order.get('status', 'UNKNOWN')
                filled_qty = float(order.get('executedQty', 0))
                
                logging.info(f"✅ Binance order placed: {binance_side} {binance_symbol}")
                logging.info(f"   Order ID: {order_id}")
                logging.info(f"   Status: {status}")
                logging.info(f"   Filled: {filled_qty}")
                
                return {
                    "status": "filled" if status == "FILLED" else "unfilled",
                    "order_id": str(order_id),
                    "symbol": binance_symbol,
                    "side": binance_side.lower(),
                    "quantity": quantity,
                    "filled_quantity": filled_qty
                }
            
            logging.error("❌ Binance order failed: No order data returned")
            return {"status": "error", "error": "No order data"}
            
        except Exception as e:
            logging.error(f"Binance order error: {e}")
            return {"status": "error", "error": str(e)}
    
    def get_positions(self) -> List[Dict]:
        """
        Get open positions (non-zero balances).
        
        Returns:
            list: List of position dicts with symbol, quantity, currency
        """
        try:
            if not self.client:
                return []
            
            # Get account balances
            account = self.client.get_account()
            positions = []
            
            for balance in account.get('balances', []):
                asset = balance['asset']
                available = float(balance.get('free', 0))
                
                # Only include non-zero, non-USDT balances
                if asset != 'USDT' and available > 0:
                    # Convert to standard symbol format
                    symbol = f'{asset}USDT'
                    
                    positions.append({
                        'symbol': symbol,
                        'quantity': available,
                        'currency': asset
                    })
            
            return positions
            
        except Exception as e:
            logging.error(f"Error fetching Binance positions: {e}")
            return []
    
    def get_candles(self, symbol: str, timeframe: str, count: int) -> List[Dict]:
        """
        Get historical candle data from Binance.
        
        Args:
            symbol: Trading pair (e.g., 'BTC-USD' or 'BTCUSDT')
            timeframe: Candle interval ('1m', '5m', '15m', '1h', '1d', etc.)
            count: Number of candles to fetch (max 1000)
        
        Returns:
            list: List of candle dicts with OHLCV data
        """
        try:
            if not self.client:
                return []
            
            # Convert symbol format
            binance_symbol = symbol.replace('-USD', 'USDT').replace('-', '')
            
            # Map timeframe to Binance interval
            # Binance uses: 1m, 3m, 5m, 15m, 30m, 1h, 2h, 4h, 6h, 8h, 12h, 1d, 3d, 1w, 1M
            interval_map = {
                "1m": "1m",
                "5m": "5m",
                "15m": "15m",
                "1h": "1h",
                "4h": "4h",
                "1d": "1d"
            }
            
            binance_interval = interval_map.get(timeframe.lower(), "5m")
            
            # Fetch klines (candles)
            klines = self.client.get_klines(
                symbol=binance_symbol,
                interval=binance_interval,
                limit=min(count, 1000)  # Binance max is 1000
            )
            
            candles = []
            for kline in klines:
                # Binance kline format: [timestamp, open, high, low, close, volume, ...]
                candles.append({
                    'time': int(kline[0]),
                    'open': float(kline[1]),
                    'high': float(kline[2]),
                    'low': float(kline[3]),
                    'close': float(kline[4]),
                    'volume': float(kline[5])
                })
            
            return candles
            
        except Exception as e:
            logging.error(f"Error fetching Binance candles: {e}")
            return []
    
    def supports_asset_class(self, asset_class: str) -> bool:
        """Binance supports crypto spot trading"""
        return asset_class.lower() in ["crypto", "cryptocurrency"]
    
    def get_all_products(self) -> list:
        """
        Get list of all tradeable cryptocurrency pairs from Binance.
        
        Returns:
            List of trading pairs (e.g., ['BTCUSDT', 'ETHUSDT', ...])
        """
        try:
            if not self.client:
                logging.warning("⚠️  Binance not connected, cannot fetch products")
                return []
            
            # Get all exchange info (includes all trading pairs)
            exchange_info = self.client.get_exchange_info()
            
            # Extract symbols that are trading (status = 'TRADING')
            symbols = []
            for symbol_info in exchange_info.get('symbols', []):
                if symbol_info.get('status') == 'TRADING':
                    # Filter for USDT pairs (most common for crypto trading)
                    symbol = symbol_info.get('symbol', '')
                    if symbol.endswith('USDT'):
                        symbols.append(symbol)
            
            logging.info(f"📊 Binance: Found {len(symbols)} tradeable USDT pairs")
            return symbols
            
        except Exception as e:
            logging.warning(f"⚠️  Error fetching Binance products: {e}")
            # Return a fallback list of popular crypto pairs
            fallback_pairs = [
                'BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'SOLUSDT', 'XRPUSDT', 'ADAUSDT',
                'DOGEUSDT', 'MATICUSDT', 'DOTUSDT', 'LINKUSDT', 'UNIUSDT', 'AVAXUSDT',
                'ATOMUSDT', 'LTCUSDT', 'NEARUSDT', 'ALGOUSDT', 'XLMUSDT', 'HBARUSDT'
            ]
            logging.info(f"📊 Binance: Using fallback list of {len(fallback_pairs)} crypto pairs")
            return fallback_pairs


# ============================================================================
# KRAKEN NONCE PERSISTENCE
# ============================================================================
# 
# CRITICAL FIX (Jan 17, 2026): Persist Kraken nonce across restarts
# 
# Problem: Without persistence, nonce resets on restart, causing "Invalid nonce"
# errors if Kraken remembers the previous session's nonce (60+ seconds).
# 
# Solution: Store nonce in kraken_nonce.txt and load it on startup
# - Thread-safe: Uses lock to prevent race conditions
# - Restart-safe: Loads last nonce from file
# - Monotonic: Always increasing (max of time-based and file-based + 1)
# ============================================================================

_nonce_lock = threading.Lock()
# CRITICAL FIX (Jan 17, 2026): Move nonce file to data directory for consistent persistence
# Other persistent state (progressive_targets.json, capital_allocation.json, open_positions.json)
# is stored in /data directory. Nonce file should follow the same pattern.
# This ensures proper persistence in containerized deployments (Railway, Docker, etc.)
_data_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
# DEPRECATED: Use get_kraken_nonce_file() instead to get account-specific nonce file path
NONCE_FILE = os.path.join(_data_dir, "kraken_nonce.txt")

# MASTER account identifier constant (Jan 17, 2026)
# Used for nonce file migration and account identification
MASTER_ACCOUNT_IDENTIFIER = "master"

def get_kraken_nonce_file(account_identifier: str = MASTER_ACCOUNT_IDENTIFIER) -> str:
    """
    Get the nonce file path for a specific Kraken account.
    
    CRITICAL FIX (Jan 17, 2026): Each account needs its own nonce file to prevent collisions.
    - MASTER account: data/kraken_nonce_master.txt
    - USER accounts: data/kraken_nonce_user_daivon.txt, etc.
    
    Args:
        account_identifier: Account identifier (e.g., 'master', 'user_daivon_frazier', 'USER:daivon_frazier')
                           Will be sanitized to safe filename format.
    
    Returns:
        str: Full path to account-specific nonce file
    """
    # Sanitize account_identifier for safe filename
    # Convert 'USER:daivon_frazier' -> 'user_daivon_frazier'
    # Convert 'MASTER' -> 'master'
    # Remove any characters that aren't alphanumeric, underscore, or hyphen
    safe_identifier = account_identifier.lower().replace(':', '_').replace(' ', '_')
    # Remove any remaining unsafe characters (keep only alphanumeric, underscore, hyphen)
    # Place hyphen at the start of character class to avoid needing escape
    safe_identifier = re.sub(r'[^-a-z0-9_]', '', safe_identifier)
    
    # Ensure data directory exists
    os.makedirs(_data_dir, exist_ok=True)
    
    return os.path.join(_data_dir, f"kraken_nonce_{safe_identifier}.txt")

def get_kraken_nonce(account_identifier: str = MASTER_ACCOUNT_IDENTIFIER):
    """
    Generate Kraken nonce with persistence across restarts.
    
    CRITICAL FIX (Jan 18, 2026): Changed to use MILLISECONDS (not microseconds) to match
    KrakenNonce class and Kraken API expectations. Automatically migrates old microsecond
    nonces to milliseconds.
    
    CRITICAL FIX (Jan 17, 2026): Now supports account-specific nonce files to prevent
    nonce collisions between MASTER and USER accounts.
    
    This function:
    1. Loads last nonce from account-specific nonce file (if exists)
    2. Migrates from legacy nonce file for MASTER account (backward compatibility)
    3. Converts microsecond nonces to milliseconds (backward compatibility)
    4. Generates new nonce = max(current_time_ms, last_nonce + 1)
    5. Persists new nonce to account-specific file
    6. Returns new nonce
    
    Thread-safe: Uses lock to prevent race conditions
    Restart-safe: Persists to file for next restart
    Account-isolated: Each account has its own nonce file
    
    Args:
        account_identifier: Account identifier (default: "master")
                           Examples: "master", "user_daivon_frazier", "USER:tania_gilbert"
    
    Returns:
        int: New nonce (milliseconds since epoch)
    """
    with _nonce_lock:
        # Get account-specific nonce file
        nonce_file = get_kraken_nonce_file(account_identifier)
        
        last_nonce = 0
        
        # BACKWARD COMPATIBILITY: Migrate legacy MASTER nonce file
        # If this is the MASTER account and the new file doesn't exist but the old one does,
        # migrate the nonce value from the old file to preserve continuity
        if account_identifier.lower() == MASTER_ACCOUNT_IDENTIFIER and not os.path.exists(nonce_file):
            legacy_nonce_file = os.path.join(_data_dir, "kraken_nonce.txt")
            if os.path.exists(legacy_nonce_file):
                try:
                    with open(legacy_nonce_file, "r") as f:
                        content = f.read().strip()
                        if content:
                            last_nonce = int(content)
                            logging.info(f"📦 Migrated MASTER nonce from legacy file: {last_nonce}")
                except (ValueError, IOError) as e:
                    logging.debug(f"Could not migrate legacy nonce file: {e}")
        
        # Read existing nonce from account-specific file
        if os.path.exists(nonce_file):
            try:
                with open(nonce_file, "r") as f:
                    content = f.read().strip()
                    if content:
                        file_nonce = int(content)
                        # Use the higher value (from migration or existing file)
                        last_nonce = max(last_nonce, file_nonce)
            except (ValueError, IOError) as e:
                logging.debug(f"Could not read nonce file for {account_identifier}: {e}, starting fresh")

        # CRITICAL FIX (Jan 18, 2026): Detect and convert microsecond nonces to milliseconds
        # Old code used microseconds (16 digits), new code uses milliseconds (13 digits)
        # Threshold: 10^14 (100000000000000) safely distinguishes the two
        MICROSECOND_THRESHOLD = 100000000000000  # 10^14
        if last_nonce > MICROSECOND_THRESHOLD:
            # This is in microseconds, convert to milliseconds
            last_nonce = int(last_nonce / 1000)
            logging.debug(f"Converted persisted nonce from microseconds to milliseconds for {account_identifier}")

        # Use MILLISECONDS to match KrakenNonce class
        now = int(time.time() * 1000)  # CHANGED from 1000000 (microseconds) to 1000 (milliseconds)
        nonce = max(now, last_nonce + 1)

        try:
            with open(nonce_file, "w") as f:
                f.write(str(nonce))
        except IOError as e:
            logging.debug(f"Could not write nonce file for {account_identifier}: {e}")

        return nonce


class KrakenBroker(BaseBroker):
    """
    Kraken Pro Exchange integration for cryptocurrency spot trading.
    
    Features:
    - Spot trading (USD/USDT pairs)
    - Market and limit orders
    - Real-time account balance
    - Historical candle data (OHLCV)
    
    Documentation: https://docs.kraken.com/rest/
    Python wrapper: https://github.com/veox/python3-krakenex
    """
    
    # HTTP timeout for Kraken API calls (in seconds)
    # This prevents indefinite hanging if the API is slow or unresponsive
    # 30 seconds is reasonable as Kraken normally responds in 1-5 seconds
    API_TIMEOUT_SECONDS = 30
    
    # Class-level flag to track if detailed permission error instructions have been logged
    # This prevents spamming the logs with duplicate permission error messages
    # The detailed instructions are logged ONCE GLOBALLY (not once per account)
    # because the fix instructions are the same for all accounts
    # Thread-safe: uses lock for concurrent access protection
    _permission_error_details_logged = False
    _permission_errors_lock = threading.Lock()
    
    # Class-level set to track accounts that have had permission errors
    # This prevents retrying connections for accounts with permission errors
    # Permission errors require user action (fixing API key permissions) and cannot
    # be resolved by retrying. Thread-safe: uses same lock as _permission_error_details_logged
    _permission_failed_accounts = set()
    
    def __init__(self, account_type: AccountType = AccountType.MASTER, user_id: Optional[str] = None):
        """
        Initialize Kraken broker with account type support.
        
        Args:
            account_type: MASTER for Nija system account, USER for individual user accounts
            user_id: User ID for USER account_type (e.g., 'daivon_frazier')
            
        Raises:
            ValueError: If account_type is USER but user_id is not provided
        """
        super().__init__(BrokerType.KRAKEN, account_type=account_type, user_id=user_id)
        
        # Validate that USER account_type has user_id
        if account_type == AccountType.USER and not user_id:
            raise ValueError("USER account_type requires user_id parameter")
        
        self.api = None
        self.kraken_api = None
        
        # Balance tracking for fail-closed behavior (Fix 3)
        # When balance fetch fails, preserve last known balance instead of returning 0
        self._last_known_balance = None  # Last successful balance fetch
        self._balance_fetch_errors = 0   # Count of consecutive errors
        self._is_available = True        # Broker availability flag
        
        # FIX 2: EXIT-ONLY mode when balance is below minimum (Jan 20, 2026)
        # Allows emergency sells even when account is too small for new entries
        self.exit_only_mode = False
        
        # FIX #2: Balance cache and health status for Kraken
        # Cache balance after successful fetch and track health
        self.balance_cache = {}  # Structure: {"kraken": balance_value}
        self.kraken_health = "UNKNOWN"  # Status: "OK", "ERROR", or "UNKNOWN"
        
        # CRITICAL FIX (Jan 17, 2026): Monotonic nonce with API call serialization
        # 
        # Nonce tracking for guaranteeing strict monotonic increase
        # This prevents "Invalid nonce" errors from rapid consecutive requests
        # 
        # Research findings from Kraken API documentation and testing:
        # - Kraken REMEMBERS the last nonce it saw for each API key (persists 60+ seconds)
        # - Kraken expects nonces to be NEAR CURRENT TIME (not far in the future)
        # - The strict monotonic counter prevents collisions even with current time
        # - Nonces should be based on current UNIX timestamp (Kraken's best practice)
        # 
        # Why 0-5 seconds is CORRECT:
        # - Aligns with Kraken's expectations (nonces near current time)
        # - Strict monotonic counter prevents all collisions within a session
        # - Small jitter (0-5s) prevents multi-instance collisions
        # - Error recovery uses 60-second immediate jump when nonce errors occur
        # 
        # Why 10-20 seconds FAILS:
        # - Nonces too far in the future may exceed Kraken's acceptable window
        # - Causes "Invalid nonce" errors on first connection attempt
        # - Each retry wastes 30-60 seconds before eventual success
        # 
        # Why very large offsets (180-240s) FAIL:
        # - Definitely exceeds Kraken's acceptable forward time window
        # - Kraken rejects nonces too far in the future
        # 
        # Session Restart Handling:
        # - The strict monotonic counter already handles rapid restarts
        # - If current time hasn't advanced enough, counter increments by 1
        # - This guarantees each nonce is unique and increasing
        # - No large forward offset needed for restart protection
        # 
        # Set identifier for logging (must be set BEFORE nonce initialization)
        if account_type == AccountType.MASTER:
            self.account_identifier = "MASTER"
        else:
            self.account_identifier = f"USER:{user_id}" if user_id else "USER:unknown"
        
        # CRITICAL FIX (Jan 17, 2026): Each account uses its own nonce file
        # This prevents nonce collisions between MASTER and USER accounts
        # - MASTER: data/kraken_nonce_master.txt
        # - USER accounts: data/kraken_nonce_user_daivon_frazier.txt, etc.
        self._nonce_file = get_kraken_nonce_file(self.account_identifier)
        
        # VERIFICATION: Ensure nonce file path is unique per account (prevent cross-contamination)
        # This assertion protects against regression bugs where nonce files might be shared
        if account_type == AccountType.MASTER:
            assert "master" in self._nonce_file.lower(), f"MASTER nonce file must contain 'master': {self._nonce_file}"
        else:
            # USER accounts: user_id is guaranteed to be non-None (validated above at line 3607-3608)
            assert user_id.lower() in self._nonce_file.lower(), f"USER nonce file must contain user_id '{user_id}': {self._nonce_file}"
        
        logger.debug(f"   Nonce file for {self.account_identifier}: {self._nonce_file}")
        
        # ✅ FIX 3: Timestamp-based Kraken Nonce (Global Nonce Manager)
        # ONE global nonce source shared across MASTER + ALL USERS
        # 
        # This is the correct solution per FIX 3 requirements:
        # - Uses int(time.time() * 1000) for milliseconds since epoch
        # - Monotonically increasing (time only moves forward)
        # - No persistence needed (timestamps are always fresh)
        # - Thread-safe (built-in time function)
        # - Scales to any number of users
        # - NO per-instance _last_nonce tracking
        #
        # Architecture:
        # - get_global_kraken_nonce() returns current timestamp in ms
        # - All Kraken API calls (master + users) use this ONE function
        # - Simple, reliable, Railway-ready
        if get_global_kraken_nonce is not None:
            # Use global timestamp-based nonce (Railway-safe)
            self._use_global_nonce = True
            self._kraken_nonce = None  # Not used with global timestamp
            logger.debug(f"   ✅ Using GLOBAL Kraken Nonce (timestamp-based) for {self.account_identifier}")
        elif KrakenNonce is not None:
            # Fallback to per-user KrakenNonce (DEPRECATED but kept for compatibility)
            logger.warning(f"   ⚠️  Global nonce manager not available, falling back to per-user KrakenNonce")
            self._use_global_nonce = False
            
            # Load persisted nonce from file and initialize KrakenNonce with it
            persisted_nonce = get_kraken_nonce(self.account_identifier)
            self._kraken_nonce = KrakenNonce()
            
            # Proper microsecond/millisecond conversion
            current_time_ms = int(time.time() * 1000)
            MICROSECOND_THRESHOLD = 100000000000000  # 10^14
            
            if persisted_nonce > MICROSECOND_THRESHOLD:
                persisted_nonce_ms = int(persisted_nonce / 1000)
                logger.debug(f"   Converted persisted nonce from microseconds ({persisted_nonce}) to milliseconds ({persisted_nonce_ms})")
            else:
                persisted_nonce_ms = persisted_nonce
            
            initial_nonce = max(persisted_nonce_ms, current_time_ms)
            self._kraken_nonce.set_initial_value(initial_nonce)
            
            logger.debug(f"   ✅ KrakenNonce instance created for {self.account_identifier} (fallback), initial nonce: {initial_nonce}ms")
        else:
            # ⚠️ DEPRECATED: This fallback is kept for backward compatibility only
            # Should not be used in production - global nonce manager should always be available
            logger.warning(f"   ⚠️  No nonce managers available, using deprecated fallback")
            self._use_global_nonce = False
            self._kraken_nonce = None
            # Note: _last_nonce is DEPRECATED and should be removed in future versions
        
        # Thread lock to ensure nonce generation is thread-safe
        # Prevents race conditions when multiple threads call API simultaneously
        self._nonce_lock = threading.Lock()
        
        # CRITICAL FIX: API call serialization to prevent simultaneous Kraken calls
        # Problem: Multiple threads can call Kraken API simultaneously, causing nonce collisions
        # Solution: Serialize all private API calls through a lock
        # - This ensures only ONE Kraken private API call happens at a time per account
        # - Public API calls don't need nonces and are not serialized
        # - Lock is per-instance, so MASTER and USER accounts can still call in parallel
        self._api_call_lock = threading.Lock()
        
        # Timestamp of last API call for rate limiting
        # Ensures minimum delay between consecutive Kraken API calls
        # CRITICAL FIX (Jan 18, 2026): Increased from 200ms to 1000ms to prevent nonce errors
        # The short 200ms interval was causing "Invalid nonce" errors when balance was checked
        # immediately after connection test. Kraken's API needs more time between requests.
        self._last_api_call_time = 0.0
        self._min_call_interval = 1.0  # 1000ms (1 second) minimum between calls
    
    def _immediate_nonce_jump(self):
        """
        Immediately jump nonce forward when a nonce error is detected.
        
        This method jumps the nonce forward by 120 seconds to clear the "burned"
        nonce window and ensure the next API call will succeed.
        
        Thread-safe: Uses the nonce generator's internal lock.
        """
        if self._use_global_nonce:
            # Use global nonce manager to jump forward
            if jump_global_kraken_nonce_forward is not None:
                immediate_jump_ms = 120 * 1000  # 120 seconds in milliseconds
                new_nonce = jump_global_kraken_nonce_forward(immediate_jump_ms)
                logger.debug(f"   ⚡ Immediately jumped GLOBAL nonce forward by 120s to clear burned nonce window (new nonce: {new_nonce})")
            else:
                logger.debug(f"   ⚡ Global nonce jump function not available - using time-based recovery")
            return
        elif self._kraken_nonce is not None:
            # Use KrakenNonce instance (fallback)
            immediate_jump_ms = 120 * 1000  # 120 seconds in milliseconds
            new_nonce = self._kraken_nonce.jump_forward(immediate_jump_ms)
            
            # Persist the jumped nonce to account-specific file
            try:
                with open(self._nonce_file, "w") as f:
                    f.write(str(new_nonce))
            except IOError as e:
                logging.debug(f"Could not persist jumped nonce: {e}")
            
            logger.debug(f"   ⚡ Immediately jumped nonce forward by 120s to clear burned nonce window")
        else:
            # FIX 3: Final fallback - use global nonce manager if available, else simple timestamp
            # No per-instance _last_nonce tracking
            logger.debug(f"   ⚡ Global nonce manager in use (fallback path) - timestamp-based, no jump needed")
            return
    
    def _kraken_private_call(self, method: str, params: Optional[Dict] = None):
        """
        CRITICAL: Serialized wrapper for Kraken private API calls.
        
        This method ensures:
        1. Only ONE private API call happens at a time (prevents nonce collisions)
        2. Minimum delay between calls (200ms safety margin)
        3. Thread-safe execution using locks
        4. GLOBAL serialization across MASTER + ALL USERS (Option B)
        
        Problem solved:
        - Multiple threads calling Kraken API simultaneously with same nonce
        - Rapid consecutive calls generating duplicate nonces
        - Race conditions in nonce generation
        - Nonce collisions between MASTER and USER accounts
        
        Args:
            method: Kraken API method name (e.g., 'Balance', 'AddOrder')
            params: Optional parameters dict for the API call
            
        Returns:
            API response dict
            
        Raises:
            Exception: If API call fails or self.api is not initialized
        """
        if not self.api:
            raise Exception("Kraken API not initialized - call connect() first")
        
        # Use GLOBAL API lock to serialize calls across ALL accounts (Option B)
        # This ensures only ONE Kraken API call happens at a time across MASTER + ALL USERS
        if get_kraken_api_lock is not None:
            global_lock = get_kraken_api_lock()
        else:
            global_lock = self._api_call_lock  # Fallback to per-account lock
        
        # Serialize API calls - only one call at a time across ALL accounts
        with global_lock:
            # Enforce minimum delay between calls (per-account tracking)
            with self._api_call_lock:
                current_time = time.time()
                time_since_last_call = current_time - self._last_api_call_time
                
                if time_since_last_call < self._min_call_interval:
                    # Sleep to maintain minimum interval
                    sleep_time = self._min_call_interval - time_since_last_call
                    logger.debug(f"   🛡️  Rate limiting: sleeping {sleep_time*1000:.0f}ms between Kraken calls")
                    time.sleep(sleep_time)
                
                # Update last call time BEFORE making the call
                self._last_api_call_time = time.time()
            
            # Make the API call (nonce is generated by _nonce_monotonic function)
            if params is None:
                result = self.api.query_private(method)
            else:
                result = self.api.query_private(method, params)
            
            return result
    
    def connect(self) -> bool:
        """
        Connect to Kraken Pro API with retry logic.
        
        Uses different credentials based on account_type:
        - MASTER: KRAKEN_MASTER_API_KEY / KRAKEN_MASTER_API_SECRET
        - USER: KRAKEN_USER_{user_id}_API_KEY / KRAKEN_USER_{user_id}_API_SECRET
        
        Returns:
            bool: True if connected successfully
        """
        try:
            import krakenex
            from pykrakenapi import KrakenAPI
            import time
            
            # Get credentials based on account type
            # Enhanced credential detection to identify "set but invalid" variables
            if self.account_type == AccountType.MASTER:
                key_name = "KRAKEN_MASTER_API_KEY"
                secret_name = "KRAKEN_MASTER_API_SECRET"
                api_key_raw = os.getenv(key_name, "")
                api_secret_raw = os.getenv(secret_name, "")
                
                # Fallback to legacy credentials if master credentials not set
                # This provides backward compatibility for deployments using KRAKEN_API_KEY
                if not api_key_raw:
                    legacy_key = os.getenv("KRAKEN_API_KEY", "")
                    if legacy_key:
                        api_key_raw = legacy_key
                        key_name = "KRAKEN_API_KEY (legacy)"
                        logger.info("   Using legacy KRAKEN_API_KEY for master account")
                
                if not api_secret_raw:
                    legacy_secret = os.getenv("KRAKEN_API_SECRET", "")
                    if legacy_secret:
                        api_secret_raw = legacy_secret
                        secret_name = "KRAKEN_API_SECRET (legacy)"
                        logger.info("   Using legacy KRAKEN_API_SECRET for master account")
                
                api_key = api_key_raw.strip()
                api_secret = api_secret_raw.strip()
                cred_label = "MASTER"
            else:
                # User account - construct env var name from user_id
                # Convert user_id to uppercase for env var
                # For user_id like 'daivon_frazier', extracts 'DAIVON' for KRAKEN_USER_DAIVON_API_KEY
                # For user_id like 'john', uses 'JOHN' for KRAKEN_USER_JOHN_API_KEY
                user_env_name = self.user_id.split('_')[0].upper() if '_' in self.user_id else self.user_id.upper()
                key_name = f"KRAKEN_USER_{user_env_name}_API_KEY"
                secret_name = f"KRAKEN_USER_{user_env_name}_API_SECRET"
                api_key_raw = os.getenv(key_name, "")
                api_secret_raw = os.getenv(secret_name, "")
                api_key = api_key_raw.strip()
                api_secret = api_secret_raw.strip()
                cred_label = f"USER:{self.user_id}"
            
            # Enhanced validation: detect if variables are set but contain only whitespace
            key_is_set = api_key_raw != ""
            secret_is_set = api_secret_raw != ""
            key_valid_after_strip = bool(api_key)
            secret_valid_after_strip = bool(api_secret)
            
            # Check for malformed credentials (set but empty after stripping)
            if (key_is_set and not key_valid_after_strip) or (secret_is_set and not secret_valid_after_strip):
                # Mark that credentials were NOT properly configured (empty/whitespace = not configured)
                # This ensures the status display shows "NOT CONFIGURED" instead of "Connection failed"
                self.credentials_configured = False
                self.last_connection_error = "Credentials contain only whitespace"
                logger.warning(f"⚠️  Kraken credentials DETECTED but INVALID for {cred_label}")
                
                # Determine status messages for each credential
                key_status = 'SET but contains only whitespace/invisible characters' if (key_is_set and not key_valid_after_strip) else 'valid'
                secret_status = 'SET but contains only whitespace/invisible characters' if (secret_is_set and not secret_valid_after_strip) else 'valid'
                
                logger.warning(f"   {key_name}: {key_status}")
                logger.warning(f"   {secret_name}: {secret_status}")
                logger.warning("   🔧 FIX: Check your deployment platform (Railway/Render) environment variables:")
                logger.warning("      1. Remove any leading/trailing spaces or newlines from the values")
                logger.warning("      2. Ensure the values are not just whitespace characters")
                logger.warning("      3. Re-deploy after fixing the values")
                return False
            
            # SMART CACHE MANAGEMENT: If credentials exist NOW, clear any previous permission error cache
            # This allows users to fix their credentials/permissions and have the bot retry automatically
            # without requiring a full restart. The cache is meant to prevent retry loops during a single
            # session with the SAME bad credentials, not to permanently block an account.
            # NOTE: This must happen BEFORE the missing credentials check below, so that if credentials
            # are added after a previous failure, we clear the cache before discovering they're still missing.
            if api_key and api_secret:
                with KrakenBroker._permission_errors_lock:
                    if cred_label in KrakenBroker._permission_failed_accounts:
                        logger.info(f"🔄 Clearing previous permission error cache for {cred_label} - credentials now available")
                        logger.info(f"   Will retry connection with current credentials")
                        KrakenBroker._permission_failed_accounts.discard(cred_label)
            
            if not api_key or not api_secret:
                # Mark that credentials were not configured (not an error, just not set up)
                self.credentials_configured = False
                # Silently skip - Kraken is optional, no need for scary error messages
                logger.info(f"⚠️  Kraken credentials not configured for {cred_label} (skipping)")
                if self.account_type == AccountType.MASTER:
                    logger.info("   🔧 FIX #1 — To enable Kraken MASTER trading, set:")
                    logger.info("      KRAKEN_MASTER_API_KEY=<your-api-key>")
                    logger.info("      KRAKEN_MASTER_API_SECRET=<your-api-secret>")
                    logger.info("   OR use legacy credentials:")
                    logger.info("      KRAKEN_API_KEY=<your-api-key>")
                    logger.info("      KRAKEN_API_SECRET=<your-api-secret>")
                    logger.info("   🔧 FIX #3 — Must be Classic API key (NOT OAuth)")
                    logger.info("   📖 Get credentials: https://www.kraken.com/u/security/api")
                else:
                    # USER account - provide specific instructions
                    # Note: user_env_name is guaranteed to be defined from the else block above
                    logger.info(f"   🔧 FIX #1 — To enable Kraken USER trading for {self.user_id}, set:")
                    logger.info(f"      KRAKEN_USER_{user_env_name}_API_KEY=<your-api-key>")
                    logger.info(f"      KRAKEN_USER_{user_env_name}_API_SECRET=<your-api-secret>")
                    logger.info(f"   ⚠️  NOTE: {self.user_id} needs THEIR OWN Kraken account (not a sub-account)")
                    logger.info(f"   🔧 FIX #3 — Must be Classic API key (NOT OAuth)")
                    logger.info(f"   📖 Each user must create their own API key at: https://www.kraken.com/u/security/api")
                    logger.info("   📖 Setup guide: KRAKEN_QUICK_START.md")
                return False
            
            # Initialize Kraken API with custom nonce generator to fix "Invalid nonce" errors
            # CRITICAL FIX: Override default nonce generation to guarantee strict monotonic increase
            # The default krakenex nonce uses time.time() which has seconds precision and can
            # produce duplicate nonces if multiple requests happen in the same second.
            # 
            # SOLUTION: Use milliseconds + tracking to ensure each nonce is strictly greater
            # than the previous one, even if requests happen in the same millisecond.
            self.api = krakenex.API(key=api_key, secret=api_secret)
            
            # CRITICAL FIX (Jan 17, 2026): Set timeout on HTTP requests to prevent hanging
            # krakenex doesn't set a default timeout, causing indefinite hangs if API is slow.
            # We use functools.partial to patch the session (standard pattern for krakenex).
            # Per-instance modification - no global state affected. Degrades gracefully if session changes.
            try:
                self.api.session.request = functools.partial(
                    self.api.session.request, 
                    timeout=self.API_TIMEOUT_SECONDS
                )
                logger.debug(f"✅ HTTP timeout configured ({self.API_TIMEOUT_SECONDS}s) for {cred_label}")
            except AttributeError as e:
                # If session attribute doesn't exist, log warning but continue
                # This maintains backward compatibility if krakenex changes its internals
                logger.warning(f"⚠️  Could not configure HTTP timeout: {e}")
            
            # Mark that credentials were configured (we have API key and secret)
            self.credentials_configured = True
            
            # Override _nonce to use simplified timestamp-based nonce (Railway-safe)
            # This prevents "EAPI:Invalid nonce" errors by using ONE global timestamp source
            # shared across MASTER + ALL USERS.
            # 
            # Benefits:
            # 1. No nonce collisions (timestamps only move forward)
            # 2. Millisecond precision (13 digits) - adequate for API calls
            # 3. Thread-safe (built-in time function)
            # 4. Scales to any number of users
            # 5. No file persistence needed (timestamps are always fresh)
            
            if self._use_global_nonce:
                # Use global timestamp-based nonce (Railway-safe)
                def _nonce_monotonic():
                    """
                    Generate nonce using timestamp (Railway-safe).
                    
                    ONE global source for MASTER + ALL USERS.
                    - Millisecond precision (13 digits)
                    - Thread-safe (uses time.time())
                    - No collisions (time only moves forward)
                    - No file persistence needed
                    """
                    nonce = get_global_kraken_nonce()
                    return str(nonce)
                
                logger.debug(f"✅ GLOBAL Kraken Nonce (timestamp-based) installed for {cred_label}")
                
            elif self._kraken_nonce is not None:
                # Fallback: Use per-user KrakenNonce instance (DEPRECATED)
                def _nonce_monotonic():
                    """
                    Generate nonce using KrakenNonce instance (DEPRECATED).
                    
                    Thread-safe: KrakenNonce uses internal lock.
                    Monotonic: Each nonce is strictly greater than previous.
                    Persistent: Nonces are saved to account-specific file.
                    """
                    nonce = self._kraken_nonce.next()
                    
                    # Persist to account-specific file for restart-safety
                    try:
                        with open(self._nonce_file, "w") as f:
                            f.write(str(nonce))
                    except IOError as e:
                        logging.debug(f"Could not persist nonce: {e}")
                    
                    return str(nonce)
                
                logger.debug(f"✅ KrakenNonce generator installed for {cred_label} (fallback)")
            else:
                # Final fallback to basic implementation
                def _nonce_monotonic():
                    """
                    DEPRECATED: Generate nonce using timestamp (fallback only).
                    
                    FIX 3: No per-instance _last_nonce tracking.
                    Uses simple timestamp-based nonce (milliseconds since epoch).
                    """
                    # FIX 3: Use simple timestamp-based nonce (no per-instance state)
                    current_nonce = int(time.time() * 1000)
                    
                    # Persist to account-specific file for restart-safety
                    try:
                        with open(self._nonce_file, "w") as f:
                            f.write(str(current_nonce))
                    except IOError as e:
                        logging.debug(f"Could not persist nonce: {e}")
                    
                    return str(current_nonce)
                
                logger.debug(f"⚠️  DEPRECATED: Basic fallback nonce generator installed for {cred_label} (should use global nonce manager)")
            
            # Replace the nonce generator
            # NOTE: This directly overrides the internal _nonce method of krakenex.API
            try:
                self.api._nonce = _nonce_monotonic
                # Log initial nonce value for debugging nonce-related issues (only if debug enabled)
                if logger.isEnabledFor(logging.DEBUG):
                    if self._use_global_nonce:
                        # Global nonce manager uses milliseconds (13 digits)
                        test_nonce = get_global_kraken_nonce()
                        logger.debug(f"   Initial nonce (GLOBAL): {test_nonce}ms (timestamp-based)")
                    elif self._kraken_nonce is not None:
                        # KrakenNonce uses milliseconds
                        current_time_ms = int(time.time() * 1000)
                        offset_seconds = (self._kraken_nonce.last - current_time_ms) / 1000.0
                        logger.debug(f"   Initial nonce (fallback): {self._kraken_nonce.last}ms (current time + {offset_seconds:.2f}s)")
                    else:
                        # FIX 3: Basic fallback uses timestamp (no _last_nonce tracking)
                        current_time_ms = int(time.time() * 1000)
                        logger.debug(f"   Initial nonce (basic fallback): {current_time_ms}ms (timestamp-based)")
            except AttributeError as e:
                self.last_connection_error = f"Nonce generator override failed: {str(e)}"
                logger.error(f"❌ Failed to override krakenex nonce generator: {e}")
                logger.error("   This may indicate a version incompatibility with krakenex library")
                logger.error("   Please report this issue with your krakenex version")
                return False
            
            self.kraken_api = KrakenAPI(self.api)
            
            # CRITICAL FIX (Jan 17, 2026): Add startup delay before first Kraken API call
            # This ensures:
            # - Nonce file exists and is initialized properly
            # - No collision with other user accounts starting simultaneously
            # - No parallel nonce generation during bootstrap
            # Similar to Coinbase's 40s delay, but shorter (5s) since we have better nonce handling
            logger.info(f"   ⏳ Waiting {KRAKEN_STARTUP_DELAY_SECONDS:.1f}s before Kraken connection test (prevents nonce collisions)...")
            time.sleep(KRAKEN_STARTUP_DELAY_SECONDS)
            logger.info(f"   ✅ Startup delay complete, testing Kraken connection...")
            
            # Test connection by fetching account balance with retry logic
            # Increased max attempts for 403 "too many errors" which indicates temporary API key blocking
            # Note: 403 differs from 429 (rate limiting) - it means the API key was temporarily blocked
            # Special handling for "Temporary lockout" errors which require much longer delays (2-5 minutes)
            # Special handling for "Invalid nonce" errors which require shorter delays
            # CRITICAL FIX (Jan 18, 2026): Reduced nonce_base_delay from 60s to 3s
            # The _immediate_nonce_jump() already jumps nonce forward by 120s, so we don't need
            # to wait out the nonce window - just need a brief pause to avoid hammering the API
            max_attempts = 5
            base_delay = 5.0  # Base delay for normal retryable errors
            nonce_base_delay = 3.0  # 3 seconds base delay for "Invalid nonce" errors (REDUCED from 60s)
            lockout_base_delay = 120.0  # 2 minutes base delay for "Temporary lockout" errors
            last_error_was_lockout = False  # Track if previous attempt was a lockout error
            last_error_was_nonce = False  # Track if previous attempt was a nonce error
            
            for attempt in range(1, max_attempts + 1):
                try:
                    # Log connection attempt at INFO level so users can see progress
                    if attempt == 1:
                        logger.info(f"   Testing Kraken connection ({cred_label})...")
                    
                    if attempt > 1:
                        # Add delay before retry with exponential backoff
                        # For "Temporary lockout" errors, use much longer delays: 120s, 240s, 360s, 480s (2min, 4min, 6min, 8min)
                        # For "Invalid nonce" errors, use moderate delays: 60s, 120s, 180s, 240s (60s increments - INCREASED from 30s)
                        # For other errors, use shorter delays: 5s, 10s, 20s, 40s
                        if last_error_was_lockout:
                            # Linear scaling for lockout: (attempt-1) * 120s = 120s, 240s, 360s, 480s for attempts 2,3,4,5
                            delay = lockout_base_delay * (attempt - 1)
                            # Log at INFO level for long delays so users know why it's taking time
                            # CRITICAL FIX (Jan 18, 2026): Removed attempt < max_attempts check to log ALL retries
                            logger.info(f"   🔄 Retrying Kraken ({cred_label}) in {delay:.0f}s (attempt {attempt}/{max_attempts}, lockout)")
                        elif last_error_was_nonce:
                            # Linear scaling for nonce errors: (attempt-1) * 3s = 3s, 6s, 9s, 12s for attempts 2,3,4,5
                            # Short delays are sufficient since _immediate_nonce_jump() already jumped nonce by 120s
                            # REDUCED from 60s increments to avoid long startup delays
                            delay = nonce_base_delay * (attempt - 1)
                            # Log at INFO level so users see progress
                            # CRITICAL FIX (Jan 18, 2026): Removed attempt < max_attempts check to log ALL retries
                            logger.info(f"   🔄 Retrying Kraken ({cred_label}) in {delay:.0f}s (attempt {attempt}/{max_attempts}, nonce)")
                        else:
                            # Exponential backoff for normal errors: 5s, 10s, 20s, 40s for attempts 2,3,4,5
                            delay = base_delay * (2 ** (attempt - 2))
                            # Log at INFO level so users see progress
                            # CRITICAL FIX (Jan 18, 2026): Removed attempt < max_attempts check to log ALL retries
                            logger.info(f"   🔄 Retrying Kraken ({cred_label}) in {delay:.0f}s (attempt {attempt}/{max_attempts})")
                        time.sleep(delay)
                        
                        # Jump nonce forward on retry to skip any potentially "burned" nonces
                        # from the failed request. Kraken may have validated but not processed
                        # the nonce, making it unusable for future requests.
                        # Jump scales with attempt number and error type:
                        #   - Normal errors: attempt * 1000ms (1s, 2s, 3s, 4s, 5s for attempts 2,3,4,5)
                        #   - Nonce errors: attempt * 20000ms (20s, 40s, 60s, 80s, 100s) - 20x larger jumps (INCREASED from 10x)
                        # Larger jumps for nonce errors ensure we skip well beyond the burned nonce window
                        # CRITICAL: Maintain monotonic guarantee by taking max of time-based and increment-based
                        
                        if self._kraken_nonce is not None:
                            # Use KrakenNonce instance (OPTION A) with public method
                            # Use 20x larger nonce jump for nonce-specific errors (INCREASED from 10x)
                            nonce_multiplier = 20 if last_error_was_nonce else 1
                            # Convert from microseconds to milliseconds for KrakenNonce
                            nonce_jump_ms = nonce_multiplier * 1000 * attempt  # Formula: multiplier * attempt * 1000ms
                            
                            # Jump forward and get new nonce value
                            new_nonce = self._kraken_nonce.jump_forward(nonce_jump_ms)
                            
                            # Persist the jumped nonce to account-specific file
                            try:
                                with open(self._nonce_file, "w") as f:
                                    f.write(str(new_nonce))
                            except IOError as e:
                                logging.debug(f"Could not persist jumped nonce: {e}")
                            
                            if last_error_was_nonce:
                                logger.debug(f"   Jumped nonce forward by {nonce_jump_ms}ms (20x jump for nonce error)")
                            else:
                                logger.debug(f"   Jumped nonce forward by {nonce_jump_ms}ms for retry {attempt}")
                        else:
                            # FIX 3: Fallback - no per-instance state, just persist current timestamp
                            # Global nonce manager should be used - this path is deprecated
                            nonce_multiplier = 20 if last_error_was_nonce else 1
                            nonce_jump = nonce_multiplier * 1000 * attempt  # milliseconds
                            current_nonce = int(time.time() * 1000) + nonce_jump
                            
                            # Persist the jumped nonce to account-specific file
                            try:
                                with open(self._nonce_file, "w") as f:
                                    f.write(str(current_nonce))
                            except IOError as e:
                                logging.debug(f"Could not persist nonce: {e}")
                            
                            if last_error_was_nonce:
                                logger.debug(f"   Jumped nonce forward by {nonce_jump}ms (20x jump for nonce error)")
                            else:
                                logger.debug(f"   Jumped nonce forward by {nonce_jump}ms for retry {attempt}")
                    
                    # The _nonce_monotonic() function automatically handles nonce generation
                    # with guaranteed strict monotonic increase. No manual nonce refresh needed.
                    # It will be called automatically by krakenex when query_private() is invoked.
                    # CRITICAL: Use _kraken_private_call() wrapper to serialize API calls
                    balance = self._kraken_private_call('Balance')
                    
                    if balance and 'error' in balance:
                        if balance['error']:
                            error_msgs = ', '.join(balance['error'])
                            
                            # Check if it's a permission error (EGeneral:Permission denied, EAPI:Invalid permission, etc.)
                            is_permission_error = any(keyword in error_msgs.lower() for keyword in [
                                'permission denied', 'egeneral:permission', 
                                'eapi:invalid permission', 'insufficient permission'
                            ])
                            
                            if is_permission_error:
                                self.last_connection_error = f"Permission denied: {error_msgs}"
                                logger.error(f"❌ Kraken connection test failed ({cred_label}): {error_msgs}")
                                
                                # Track this account as failed due to permission error for this session
                                # The cache will be automatically cleared if valid credentials are detected later
                                # Thread-safe update using class-level lock
                                with KrakenBroker._permission_errors_lock:
                                    KrakenBroker._permission_failed_accounts.add(cred_label)
                                    
                                    # Only log detailed permission error instructions ONCE GLOBALLY
                                    # After the first account with permission error, subsequent accounts
                                    # get a brief reference message instead of full instructions
                                    # This prevents log spam when multiple users have permission errors
                                    if not KrakenBroker._permission_error_details_logged:
                                        KrakenBroker._permission_error_details_logged = True
                                        should_log_details = True
                                    else:
                                        should_log_details = False
                                
                                if should_log_details:
                                    logger.error("   ⚠️  API KEY PERMISSION ERROR")
                                    logger.error("   Your Kraken API key does not have the required permissions.")
                                    logger.warning("")
                                    logger.warning("   🔧 FIX #1 — Ensure you're using KRAKEN MASTER keys")
                                    logger.warning("      Environment variables: KRAKEN_MASTER_API_KEY / KRAKEN_MASTER_API_SECRET")
                                    logger.warning("      (Not legacy KRAKEN_API_KEY)")
                                    logger.warning("")
                                    logger.warning("   🔧 FIX #2 — Fix Kraken API permissions (mandatory):")
                                    logger.warning("   1. Go to https://www.kraken.com/u/security/api")
                                    logger.warning("   2. Find your API key and edit its permissions")
                                    logger.warning("   3. Enable these permissions:")
                                    logger.warning("      ✅ Query Funds (required to check balance)")
                                    logger.warning("      ✅ Query Open Orders & Trades (required for position tracking)")
                                    logger.warning("      ✅ Query Closed Orders & Trades (required for trade history)")
                                    logger.warning("      ✅ Create & Modify Orders (required to place trades)")
                                    logger.warning("      ✅ Cancel/Close Orders (required for stop losses)")
                                    logger.warning("   4. Save changes and restart the bot")
                                    logger.warning("")
                                    logger.warning("   🔧 FIX #3 — Confirm Kraken key type:")
                                    logger.warning("      ✅ Must be Classic API key (NOT OAuth or App key)")
                                    logger.warning("      To create: Settings > API > Generate New Key")
                                    logger.warning("")
                                    logger.warning("   🔧 FIX #4 — Nonce handling (auto-fixed):")
                                    logger.warning("      ✅ Bot uses microsecond-precision nonces (monotonically increasing)")
                                    logger.warning("      ✅ If nonce errors persist, check system clock (use NTP sync)")
                                    logger.warning("")
                                    logger.warning("   For security, do NOT enable 'Withdraw Funds' permission")
                                    logger.warning("   📖 See KRAKEN_PERMISSION_ERROR_FIX.md for detailed instructions")
                                    # Flush handlers to ensure all permission error messages appear together
                                    # CRITICAL: Flush root 'nija' logger handlers, not child logger (which has no handlers)
                                    for handler in _root_logger.handlers:
                                        handler.flush()
                                else:
                                    logger.error("   ⚠️  API KEY PERMISSION ERROR")
                                    logger.error("   Your Kraken API key does not have the required permissions.")
                                    logger.error("   🔧 FIX: Must use Classic API key with Query/Create/Cancel Orders permissions")
                                    logger.error("   https://www.kraken.com/u/security/api")
                                    logger.error("   📖 See KRAKEN_PERMISSION_ERROR_FIX.md for detailed instructions")
                                
                                return False
                            
                            # Check if error is retryable (rate limiting, network issues, 403 errors, nonce errors, lockout, etc.)
                            # CRITICAL: Include "invalid nonce" and "lockout" as retryable errors
                            # Invalid nonce errors can happen due to:
                            # - Clock drift/NTP adjustments
                            # - Rapid consecutive requests
                            # - Previous failed requests leaving the nonce counter in inconsistent state
                            # The microsecond-based nonce generator should fix this, but we still retry
                            # to handle edge cases and transient issues.
                            # 
                            # "Temporary lockout" errors require special handling with longer delays (minutes, not seconds)
                            # "Invalid nonce" errors require moderate delays (30s increments) and aggressive nonce jumps (10x)
                            is_lockout_error = 'lockout' in error_msgs.lower()
                            # Be specific about nonce errors - match exact Kraken error messages
                            is_nonce_error = any(keyword in error_msgs.lower() for keyword in [
                                'invalid nonce', 'eapi:invalid nonce', 'nonce window'
                            ])
                            is_retryable = is_lockout_error or is_nonce_error or any(keyword in error_msgs.lower() for keyword in [
                                'timeout', 'connection', 'network', 'rate limit',
                                'too many requests', 'service unavailable',
                                '503', '504', '429', '403', 'forbidden', 
                                'too many errors', 'temporary', 'try again'
                            ])
                            
                            if is_retryable and attempt < max_attempts:
                                # Set flags for special error types to use appropriate delays on next retry
                                last_error_was_lockout = is_lockout_error
                                last_error_was_nonce = is_nonce_error and not is_lockout_error  # Lockout takes precedence
                                
                                # CRITICAL FIX: Immediately jump nonce forward on first nonce error detection
                                # Don't wait until the next retry iteration - do it now to clear the burned nonce
                                if is_nonce_error:
                                    self._immediate_nonce_jump()
                                
                                # Reduce log spam for transient errors
                                # - Nonce errors: Log at INFO level on first attempt, DEBUG on retries (transient, will auto-retry)
                                # - Other retryable errors: Log as WARNING only on first attempt
                                # - All retries after first attempt: Log at DEBUG level for diagnostics
                                error_type = "lockout" if is_lockout_error else "nonce" if is_nonce_error else "retryable"
                                
                                # For nonce errors, log at INFO level on first attempt so users know what failed
                                # Log at DEBUG level on retries to reduce spam
                                # These are transient and automatically retried with nonce jumps
                                if is_nonce_error:
                                    if attempt == 1:
                                        logger.info(f"   ⚠️  Kraken ({cred_label}) nonce error on attempt {attempt}/{max_attempts} (auto-retry): {error_msgs}")
                                    else:
                                        logger.debug(f"🔄 Kraken ({cred_label}) attempt {attempt}/{max_attempts} nonce error (auto-retry): {error_msgs}")
                                # For lockout/other errors, log at WARNING on first attempt only
                                elif attempt == 1:
                                    logger.warning(f"⚠️  Kraken ({cred_label}) attempt {attempt}/{max_attempts} failed ({error_type}): {error_msgs}")
                                # All retries after first attempt: DEBUG level only
                                else:
                                    logger.debug(f"🔄 Kraken ({cred_label}) attempt {attempt}/{max_attempts} failed ({error_type}): {error_msgs}")
                                continue
                            else:
                                self.last_connection_error = error_msgs
                                logger.error(f"❌ Kraken connection test failed ({cred_label}): {error_msgs}")
                                return False
                    
                    if balance and 'result' in balance:
                        self.connected = True
                        
                        if attempt > 1:
                            logger.info(f"✅ Connected to Kraken Pro API ({cred_label}) (succeeded on attempt {attempt})")
                        
                        logger.info("=" * 70)
                        logger.info(f"✅ KRAKEN PRO CONNECTED ({cred_label})")
                        logger.info("=" * 70)
                        
                        # Log USD/USDT balance
                        result = balance.get('result', {})
                        usd_balance = float(result.get('ZUSD', 0))  # Kraken uses ZUSD for USD
                        usdt_balance = float(result.get('USDT', 0))
                        
                        total = usd_balance + usdt_balance
                        logger.info(f"   Account: {self.account_identifier}")
                        logger.info(f"   USD Balance: ${usd_balance:.2f}")
                        logger.info(f"   USDT Balance: ${usdt_balance:.2f}")
                        logger.info(f"   Total: ${total:.2f}")
                        
                        # Check minimum balance requirement for Kraken
                        # Kraken is PRIMARY engine for small accounts ($25+)
                        # FIX 2: FORCED EXIT OVERRIDES - Allow connection even when balance < minimum
                        # This enables emergency sells to close losing positions
                        if total < KRAKEN_MINIMUM_BALANCE:
                            logger.warning("=" * 70)
                            logger.warning("⚠️ KRAKEN: Account balance below minimum for NEW ENTRIES")
                            logger.warning("=" * 70)
                            logger.warning(f"   Your balance: ${total:.2f}")
                            logger.warning(f"   Minimum for entries: ${KRAKEN_MINIMUM_BALANCE:.2f}")
                            logger.warning(f"   ")
                            logger.warning(f"   📋 Trading Mode: EXIT-ONLY")
                            logger.warning(f"      ✅ Can SELL (close positions)")
                            logger.warning(f"      ❌ Cannot BUY (new entries blocked)")
                            logger.warning(f"   ")
                            logger.warning(f"   💡 Solution: Fund account to at least ${KRAKEN_MINIMUM_BALANCE:.2f}")
                            logger.warning(f"      Kraken is the best choice for small accounts (4x lower fees)")
                            logger.warning(f"   ")
                            logger.warning(f"   ✅ Kraken connection maintained for emergency exits")
                            logger.warning("=" * 70)
                            
                            # Mark as EXIT-ONLY mode (not fully disabled)
                            self.exit_only_mode = True
                            # Keep connected = True so sells can execute
                            self.connected = True
                        else:
                            # Normal mode - full trading allowed
                            self.exit_only_mode = False
                        
                        logger.info("=" * 70)
                        
                        # CRITICAL FIX (Jan 18, 2026): Add post-connection delay
                        # After successful connection test, wait before allowing next API call
                        # This prevents "Invalid nonce" when balance is checked immediately after
                        # The connection test already called Balance API, and rapid consecutive
                        # calls (even with 1s interval) can trigger nonce errors
                        # NOTE: time.sleep() blocking is INTENTIONAL - we want to pause execution
                        # to ensure proper timing between API calls. This is a synchronous operation
                        # during bot startup, not an async/event-driven context.
                        post_connection_delay = 2.0  # 2 seconds post-connection cooldown
                        logger.info(f"   ⏳ Post-connection cooldown: {post_connection_delay:.1f}s (prevents nonce errors)...")
                        time.sleep(post_connection_delay)
                        logger.debug(f"   ✅ Cooldown complete - ready for balance checks")
                        
                        return True
                    else:
                        # No result, but could be retryable
                        error_msg = "No balance data returned"
                        if attempt < max_attempts:
                            logger.warning(f"⚠️  Kraken connection attempt {attempt}/{max_attempts} failed (retryable): {error_msg}")
                            continue
                        else:
                            self.last_connection_error = error_msg
                            logger.error(f"❌ Kraken connection test failed: {error_msg}")
                            return False
                
                except Exception as e:
                    error_msg = str(e)
                    
                    # Check if this is a timeout or connection error from requests library
                    # These errors should be logged clearly and are always retryable
                    # Use the module-level flag to avoid repeated import attempts
                    # NOTE: The imported exception classes (Timeout, etc.) are only defined when
                    # REQUESTS_TIMEOUT_EXCEPTIONS_AVAILABLE is True, so they're only used inside that branch
                    if REQUESTS_TIMEOUT_EXCEPTIONS_AVAILABLE:
                        # Include both timeout and connection errors (network issues)
                        # Note: Using RequestsConnectionError alias to avoid shadowing built-in ConnectionError
                        is_timeout_error = isinstance(e, (Timeout, ReadTimeout, ConnectTimeout, RequestsConnectionError))
                    else:
                        # Fallback to string matching if requests isn't available
                        is_timeout_error = (
                            'timeout' in error_msg.lower() or
                            'timed out' in error_msg.lower() or
                            'connection' in error_msg.lower()
                        )
                    
                    if is_timeout_error:
                        # Timeout/connection errors are common and expected - log at INFO level, not ERROR
                        # After logging, we 'continue' to the next iteration which applies exponential
                        # backoff via the retry delay logic at the top of the loop
                        if attempt < max_attempts:
                            logger.info(f"   ⏱️  Connection timeout/network error ({cred_label}) - attempt {attempt}/{max_attempts}")
                            logger.info(f"   Will retry with exponential backoff...")
                            continue  # Jump to next iteration, which adds delay before retry
                        else:
                            self.last_connection_error = "Connection timeout or network error (API unresponsive)"
                            logger.warning(f"⚠️  Kraken connection failed after {max_attempts} timeout attempts")
                            logger.warning(f"   The Kraken API may be experiencing issues or network connectivity problems")
                            logger.warning(f"   Will try again on next connection cycle")
                            return False
                    
                    # CRITICAL FIX: Check if this is a permission error in the exception path
                    # Permission errors can also be raised as exceptions by krakenex/pykrakenapi
                    is_permission_error = any(keyword in error_msg.lower() for keyword in [
                        'permission denied', 'egeneral:permission',
                        'eapi:invalid permission', 'insufficient permission'
                    ])
                    
                    if is_permission_error:
                        self.last_connection_error = f"Permission denied: {error_msg}"
                        logger.error(f"❌ Kraken connection test failed ({cred_label}): {error_msg}")
                        
                        # Track this account as failed due to permission error for this session
                        # The cache will be automatically cleared if valid credentials are detected later
                        # Thread-safe update using class-level lock
                        with KrakenBroker._permission_errors_lock:
                            KrakenBroker._permission_failed_accounts.add(cred_label)
                            
                            # Only log detailed instructions ONCE GLOBALLY (not once per account)
                            # This prevents log spam when multiple users have permission errors
                            if not KrakenBroker._permission_error_details_logged:
                                KrakenBroker._permission_error_details_logged = True
                                should_log_details = True
                            else:
                                should_log_details = False
                        
                        if should_log_details:
                            logger.error("   ⚠️  API KEY PERMISSION ERROR")
                            logger.error("   Your Kraken API key does not have the required permissions.")
                            logger.warning("")
                            logger.warning("   🔧 FIX #1 — Ensure you're using KRAKEN MASTER keys")
                            logger.warning("      Environment variables: KRAKEN_MASTER_API_KEY / KRAKEN_MASTER_API_SECRET")
                            logger.warning("      (Not legacy KRAKEN_API_KEY)")
                            logger.warning("")
                            logger.warning("   🔧 FIX #2 — Fix Kraken API permissions (mandatory):")
                            logger.warning("   1. Go to https://www.kraken.com/u/security/api")
                            logger.warning("   2. Find your API key and edit its permissions")
                            logger.warning("   3. Enable these permissions:")
                            logger.warning("      ✅ Query Funds (required to check balance)")
                            logger.warning("      ✅ Query Open Orders & Trades (required for position tracking)")
                            logger.warning("      ✅ Query Closed Orders & Trades (required for trade history)")
                            logger.warning("      ✅ Create & Modify Orders (required to place trades)")
                            logger.warning("      ✅ Cancel/Close Orders (required for stop losses)")
                            logger.warning("   4. Save changes and restart the bot")
                            logger.warning("")
                            logger.warning("   🔧 FIX #3 — Confirm Kraken key type:")
                            logger.warning("      ✅ Must be Classic API key (NOT OAuth or App key)")
                            logger.warning("      To create: Settings > API > Generate New Key")
                            logger.warning("")
                            logger.warning("   🔧 FIX #4 — Nonce handling (auto-fixed):")
                            logger.warning("      ✅ Bot uses microsecond-precision nonces (monotonically increasing)")
                            logger.warning("      ✅ If nonce errors persist, check system clock (use NTP sync)")
                            logger.warning("")
                            logger.warning("   For security, do NOT enable 'Withdraw Funds' permission")
                            logger.warning("   📖 See KRAKEN_PERMISSION_ERROR_FIX.md for detailed instructions")
                            # Flush handlers to ensure all permission error messages appear together
                            # CRITICAL: Flush root 'nija' logger handlers, not child logger (which has no handlers)
                            for handler in _root_logger.handlers:
                                handler.flush()
                        else:
                            logger.error("   ⚠️  API KEY PERMISSION ERROR")
                            logger.error("   Your Kraken API key does not have the required permissions.")
                            logger.error("   🔧 FIX: Must use Classic API key with Query/Create/Cancel Orders permissions")
                            logger.error("   https://www.kraken.com/u/security/api")
                            logger.error("   📖 See KRAKEN_PERMISSION_ERROR_FIX.md for detailed instructions")
                        
                        return False
                    
                    # Check if error is retryable (rate limiting, network issues, 403 errors, nonce errors, lockout, etc.)
                    # CRITICAL: Include "invalid nonce" and "lockout" as retryable errors
                    # Invalid nonce errors can happen due to:
                    # - Clock drift/NTP adjustments
                    # - Rapid consecutive requests
                    # - Previous failed requests leaving the nonce counter in inconsistent state
                    # The microsecond-based nonce generator should fix this, but we still retry
                    # to handle edge cases and transient issues.
                    # 
                    # "Temporary lockout" errors require special handling with longer delays (minutes, not seconds)
                    # "Invalid nonce" errors require moderate delays (30s increments) and aggressive nonce jumps (10x)
                    is_lockout_error = 'lockout' in error_msg.lower()
                    # Be specific about nonce errors - match exact Kraken error messages
                    is_nonce_error = any(keyword in error_msg.lower() for keyword in [
                        'invalid nonce', 'eapi:invalid nonce', 'nonce window'
                    ])
                    is_retryable = is_lockout_error or is_nonce_error or any(keyword in error_msg.lower() for keyword in [
                        'timeout', 'connection', 'network', 'rate limit',
                        'too many requests', 'service unavailable',
                        '503', '504', '429', '403', 'forbidden', 
                        'too many errors', 'temporary', 'try again'
                    ])
                    
                    if is_retryable and attempt < max_attempts:
                        # Set flags for special error types to use appropriate delays on next retry
                        last_error_was_lockout = is_lockout_error
                        last_error_was_nonce = is_nonce_error and not is_lockout_error  # Lockout takes precedence
                        
                        # CRITICAL FIX: Immediately jump nonce forward on first nonce error detection
                        # Don't wait until the next retry iteration - do it now to clear the burned nonce
                        if is_nonce_error:
                            self._immediate_nonce_jump()
                        
                        # Log retryable errors appropriately:
                        # - Timeout errors: Already logged above (special case)
                        # - Nonce errors: Log at INFO level (transient, will auto-retry)
                        # - Lockout/other errors: Log at WARNING on first attempt, INFO on retries
                        error_type = "lockout" if is_lockout_error else "nonce" if is_nonce_error else "retryable"
                        
                        # For nonce errors, log at INFO level so users see progress
                        if is_nonce_error:
                            logger.info(f"   🔄 Kraken ({cred_label}) nonce error - auto-retry (attempt {attempt}/{max_attempts})")
                        # For lockout/other errors, log at WARNING on first attempt, INFO on retries
                        elif attempt == 1:
                            logger.warning(f"⚠️  Kraken ({cred_label}) attempt {attempt}/{max_attempts} failed ({error_type}): {error_msg}")
                        # All retries after first attempt: INFO level for visibility
                        else:
                            logger.info(f"   🔄 Kraken ({cred_label}) retry {attempt}/{max_attempts} ({error_type})")
                        continue
                    else:
                        # Handle errors gracefully for non-retryable or final attempt
                        self.last_connection_error = error_msg
                        error_str = error_msg.lower()
                        if 'api' in error_str and ('key' in error_str or 'signature' in error_str or 'authentication' in error_str):
                            logger.warning("⚠️  Kraken authentication failed - invalid or expired API credentials")
                        elif 'connection' in error_str or 'network' in error_str or 'timeout' in error_str:
                            logger.warning("⚠️  Kraken connection failed - network issue or API unavailable")
                        else:
                            logger.warning(f"⚠️  Kraken connection failed: {error_msg}")
                        return False
            
            # Should never reach here, but just in case
            # Log summary of all failed attempts to help with debugging
            self.last_connection_error = "Failed after max retry attempts"
            logger.error(f"❌ Kraken ({cred_label}) failed after {max_attempts} attempts")
            if last_error_was_nonce:
                self.last_connection_error = "Invalid nonce (retry exhausted)"
                logger.error("   Last error was: Invalid nonce (API nonce synchronization issue)")
                logger.error("   This usually resolves after waiting 1-2 minutes")
            elif last_error_was_lockout:
                self.last_connection_error = "Temporary lockout (retry exhausted)"
                logger.error("   Last error was: Temporary lockout (too many failed requests)")
                logger.error("   Wait 5-10 minutes before restarting")
            return False
                
        except ImportError as e:
            # SDK not installed or import failed
            self.last_connection_error = f"SDK import error: {str(e)}"
            logger.error(f"❌ Kraken connection failed ({self.account_identifier}): SDK import error")
            logger.error(f"   ImportError: {e}")
            logger.error("   The Kraken SDK (krakenex or pykrakenapi) failed to import")
            logger.error("")
            logger.error("   📋 Troubleshooting steps:")
            logger.error("      1. Verify krakenex and pykrakenapi are in requirements.txt")
            logger.error("      2. Check deployment logs for package installation errors")
            logger.error("      3. Try manual install: pip install krakenex pykrakenapi")
            logger.error("      4. Check for dependency conflicts with: pip check")
            logger.error("")
            logger.error("   If the packages are installed but import still fails,")
            logger.error("   there may be a dependency version conflict.")
            return False
    
    def get_account_balance(self) -> float:
        """
        Get USD/USDT balance available for trading with fail-closed behavior.
        
        CRITICAL FIX (Fix 3): Fail closed - not "balance = 0"
        - On error: Return last known balance (if available) instead of 0
        - Track consecutive errors to mark broker unavailable
        - Distinguish API errors from actual zero balance
        
        Returns:
            float: Available USD + USDT balance (not including held funds)
                   Returns last known balance on error (not 0)
        """
        try:
            if not self.api:
                # FIX #2: Not connected - log warning and use last known balance
                self._balance_fetch_errors += 1
                if self._balance_fetch_errors >= BROKER_MAX_CONSECUTIVE_ERRORS:
                    self._is_available = False
                    self.kraken_health = "ERROR"
                    logger.error(f"❌ Kraken marked unavailable ({self.account_identifier}) after {self._balance_fetch_errors} consecutive errors")
                
                if self._last_known_balance is not None:
                    logger.warning(f"⚠️ Kraken API not connected ({self.account_identifier}), using last known balance: ${self._last_known_balance:.2f}")
                    # Use cached balance if available
                    if "kraken" in self.balance_cache:
                        return self.balance_cache["kraken"]
                    return self._last_known_balance
                else:
                    logger.error(f"❌ Kraken API not connected ({self.account_identifier}) and no last known balance")
                    self._is_available = False
                    self.kraken_health = "ERROR"
                    return 0.0
            
            # Get account balance using serialized API call
            balance = self._kraken_private_call('Balance')
            
            if balance and 'error' in balance and balance['error']:
                error_msgs = ', '.join(balance['error'])
                
                # FIX #2: On error, log warning and use last known balance
                logger.warning(f"⚠️ Kraken API error fetching balance ({self.account_identifier}): {error_msgs}")
                
                # DO NOT zero balance on one failure
                self._balance_fetch_errors += 1
                if self._balance_fetch_errors >= BROKER_MAX_CONSECUTIVE_ERRORS:
                    self._is_available = False
                    self.kraken_health = "ERROR"
                    logger.error(f"❌ Kraken marked unavailable ({self.account_identifier}) after {self._balance_fetch_errors} consecutive errors")
                
                if self._last_known_balance is not None:
                    logger.warning(f"   ⚠️ Using last known balance: ${self._last_known_balance:.2f}")
                    # Use cached balance if available
                    if "kraken" in self.balance_cache:
                        return self.balance_cache["kraken"]
                    return self._last_known_balance
                else:
                    logger.error(f"   ❌ No last known balance available, returning 0")
                    return 0.0
            
            if balance and 'result' in balance:
                result = balance['result']
                
                # Kraken uses ZUSD for USD and USDT for Tether
                usd_balance = float(result.get('ZUSD', 0))
                usdt_balance = float(result.get('USDT', 0))
                
                total = usd_balance + usdt_balance
                
                # Also get TradeBalance to see held funds
                trade_balance = self._kraken_private_call('TradeBalance', {'asset': 'ZUSD'})
                held_amount = 0.0
                
                if trade_balance and 'result' in trade_balance:
                    tb_result = trade_balance['result']
                    # eb = equivalent balance (total balance including held orders)
                    # tb = trade balance (free margin available)
                    # held = eb - tb
                    eb = float(tb_result.get('eb', 0))
                    tb = float(tb_result.get('tb', 0))
                    held_amount = eb - tb if eb > tb else 0.0
                
                # Enhanced balance logging with clear breakdown (Jan 19, 2026)
                logger.info("=" * 70)
                logger.info(f"💰 Kraken Balance ({self.account_identifier}):")
                logger.info(f"   ✅ Available USD:  ${usd_balance:.2f}")
                logger.info(f"   ✅ Available USDT: ${usdt_balance:.2f}")
                logger.info(f"   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
                logger.info(f"   💵 Total Available: ${total:.2f}")
                
                # 🚑 FIX 4: Calculate total_funds (available + locked) for Kraken
                total_funds = total + held_amount
                
                if held_amount > 0:
                    logger.info(f"   🔒 Held in open orders: ${held_amount:.2f}")
                    logger.info(f"   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
                    logger.info(f"   💎 TOTAL FUNDS (Available + Held): ${total_funds:.2f}")
                logger.info("=" * 70)
                
                # FIX #3 (Jan 20, 2026): Confirmation log for Kraken balance fetch
                logger.info(f"✅ KRAKEN balance fetched: ${total_funds:.2f}")
                
                # SUCCESS: Update last known balance and reset error count
                # 🚑 FIX 4: Store and return total_funds instead of just available
                self._last_known_balance = total_funds
                self._balance_fetch_errors = 0
                self._is_available = True
                
                # FIX #2: Force Kraken balance cache after success
                self.balance_cache["kraken"] = total_funds
                self.kraken_health = "OK"
                
                return total_funds
            
            # Unexpected response - treat as error
            # FIX #2: Log warning and use last known balance
            logger.warning(f"⚠️ Unexpected Kraken API response format ({self.account_identifier})")
            self._balance_fetch_errors += 1
            if self._balance_fetch_errors >= BROKER_MAX_CONSECUTIVE_ERRORS:
                self._is_available = False
                self.kraken_health = "ERROR"
            
            if self._last_known_balance is not None:
                logger.warning(f"   ⚠️ Using last known balance: ${self._last_known_balance:.2f}")
                # Use cached balance if available
                if "kraken" in self.balance_cache:
                    return self.balance_cache["kraken"]
                return self._last_known_balance
            
            return 0.0
            
        except Exception as e:
            # FIX #2: Log warning and use last known balance on exception
            logger.warning(f"⚠️ Exception fetching Kraken balance ({self.account_identifier}): {e}")
            self._balance_fetch_errors += 1
            if self._balance_fetch_errors >= BROKER_MAX_CONSECUTIVE_ERRORS:
                self._is_available = False
                self.kraken_health = "ERROR"
                logger.error(f"❌ Kraken marked unavailable ({self.account_identifier}) after {self._balance_fetch_errors} consecutive errors")
            
            # Return last known balance instead of 0
            if self._last_known_balance is not None:
                logger.warning(f"   ⚠️ Using last known balance: ${self._last_known_balance:.2f}")
                # Use cached balance if available
                if "kraken" in self.balance_cache:
                    return self.balance_cache["kraken"]
                return self._last_known_balance
            
            return 0.0
    
    def get_account_balance_detailed(self) -> dict:
        """
        Get detailed account balance information with fail-closed behavior.
        
        CRITICAL FIX (Fix 3): Fail closed - not "balance = 0"
        - On error: Include error flag in response
        - Return last known balance if available
        - Don't return all zeros on error
        
        Returns detailed balance breakdown for comprehensive fund visibility.
        Matches CoinbaseBroker interface for consistency.
        
        Returns:
            dict: Detailed balance info with keys:
                - usd: Available USD balance
                - usdt: Available USDT balance  
                - trading_balance: Total available (USD + USDT)
                - usd_held: USD held in open orders
                - usdt_held: USDT held in open orders
                - total_held: Total held (usd_held + usdt_held)
                - total_funds: Complete balance (trading_balance + total_held)
                - crypto: Dictionary of crypto asset balances
                - error: Boolean indicating if fetch failed
                - error_message: Error description (if error=True)
        """
        # Default return structure for error cases
        default_balance = {
            'usd': 0.0,
            'usdt': 0.0,
            'trading_balance': 0.0,
            'usd_held': 0.0,
            'usdt_held': 0.0,
            'total_held': 0.0,
            'total_funds': 0.0,
            'crypto': {},
            'error': True,
            'error_message': 'Unknown error'
        }
        
        try:
            if not self.api:
                error_msg = 'API not connected'
                logger.warning(f"⚠️ {error_msg} ({self.account_identifier})")
                return {**default_balance, 'error_message': error_msg}
            
            # Get account balance using serialized API call
            balance = self._kraken_private_call('Balance')
            
            if balance and 'error' in balance and balance['error']:
                error_msgs = ', '.join(balance['error'])
                logger.error(f"❌ Kraken API error fetching detailed balance ({self.account_identifier}): {error_msgs}")
                return {**default_balance, 'error_message': f'API error: {error_msgs}'}
            
            if balance and 'result' in balance:
                result = balance['result']
                
                # Kraken uses ZUSD for USD and USDT for Tether
                usd_balance = float(result.get('ZUSD', 0))
                usdt_balance = float(result.get('USDT', 0))
                
                # Get crypto holdings (exclude USD and USDT)
                crypto_holdings = {}
                for currency, amount in result.items():
                    if currency not in ['ZUSD', 'USDT'] and float(amount) > 0:
                        # Strip the 'Z' or 'X' prefix Kraken uses for some currencies
                        clean_currency = currency.lstrip('ZX')
                        crypto_holdings[clean_currency] = float(amount)
                
                trading_balance = usd_balance + usdt_balance
                
                # Get TradeBalance to calculate held funds
                trade_balance = self._kraken_private_call('TradeBalance', {'asset': 'ZUSD'})
                usd_held = 0.0
                usdt_held = 0.0
                total_held = 0.0
                
                if trade_balance and 'result' in trade_balance:
                    tb_result = trade_balance['result']
                    # eb = equivalent balance (total balance including held orders)
                    # tb = trade balance (free margin available)
                    # held = eb - tb
                    eb = float(tb_result.get('eb', 0))
                    tb = float(tb_result.get('tb', 0))
                    total_held = eb - tb if eb > tb else 0.0
                    
                    # NOTE: Kraken's TradeBalance API returns total held amount in base currency (USD)
                    # but doesn't break it down by USD vs USDT. We approximate the distribution
                    # based on the ratio of USD to USDT in available balances.
                    if trading_balance > 0 and total_held > 0:
                        usd_ratio = usd_balance / trading_balance
                        usdt_ratio = usdt_balance / trading_balance
                        usd_held = total_held * usd_ratio
                        usdt_held = total_held * usdt_ratio
                    elif usd_balance > 0:
                        # If only USD, assign all held to USD
                        usd_held = total_held
                    else:
                        # If only USDT or no balance, assign all held to USDT
                        usdt_held = total_held
                
                total_funds = trading_balance + total_held
                
                return {
                    'usd': usd_balance,
                    'usdt': usdt_balance,
                    'trading_balance': trading_balance,
                    'usd_held': usd_held,
                    'usdt_held': usdt_held,
                    'total_held': total_held,
                    'total_funds': total_funds,
                    'crypto': crypto_holdings,
                    'error': False
                }
            
            # Unexpected response
            return {**default_balance, 'error_message': 'Unexpected API response format'}
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"❌ Exception fetching Kraken detailed balance ({self.account_identifier}): {error_msg}")
            return {**default_balance, 'error_message': error_msg}
    
    def is_available(self) -> bool:
        """
        Check if Kraken broker is available for trading.
        
        Returns False if there have been 3+ consecutive balance fetch errors.
        This prevents trading when the API is not working properly.
        
        Returns:
            bool: True if broker is available, False if unavailable
        """
        return self._is_available
    
    def get_error_count(self) -> int:
        """
        Get the number of consecutive balance fetch errors.
        
        Returns:
            int: Number of consecutive errors
        """
        return self._balance_fetch_errors
    
    def force_liquidate(
        self,
        symbol: str,
        quantity: float,
        reason: str = "Emergency liquidation"
    ) -> Dict:
        """
        🚑 EMERGENCY SELL OVERRIDE - Force liquidate position bypassing ALL checks.
        
        This is the FIX 1 implementation for Kraken that allows NIJA to exit losing positions
        immediately without being blocked by validation.
        
        CRITICAL: This method MUST be used for emergency exits and losing trades.
        
        Args:
            symbol: Trading symbol (e.g., 'BTC-USD')
            quantity: Quantity to sell (in base currency)
            reason: Reason for forced liquidation (for logging)
        
        Returns:
            Order result dict with status
        """
        logger.warning("=" * 70)
        logger.warning(f"🚑 FORCE LIQUIDATE [Kraken]: {symbol}")
        logger.warning(f"   Account: {self.account_identifier if hasattr(self, 'account_identifier') else 'UNKNOWN'}")
        logger.warning(f"   Reason: {reason}")
        logger.warning(f"   Quantity: {quantity}")
        logger.warning(f"   ⚠️  ALL VALIDATION BYPASSED - EMERGENCY EXIT")
        logger.warning("=" * 70)
        
        try:
            # Force market sell with emergency bypass flags
            result = self.place_market_order(
                symbol=symbol,
                side='sell',
                quantity=quantity,
                ignore_balance=True,
                ignore_min_trade=True,
                force_liquidate=True
            )
            
            if result.get('status') == 'filled':
                logger.warning(f"✅ FORCE LIQUIDATE SUCCESSFUL [Kraken]: {symbol}")
            else:
                logger.error(f"❌ FORCE LIQUIDATE FAILED [Kraken]: {symbol} - {result.get('error', 'Unknown error')}")
            
            return result
            
        except Exception as e:
            logger.error(f"❌ FORCE LIQUIDATE EXCEPTION [Kraken]: {symbol} - {e}")
            logger.error(traceback.format_exc())
            return {
                "status": "error",
                "error": str(e),
                "symbol": symbol
            }
    
    def place_market_order(
        self, 
        symbol: str, 
        side: str, 
        quantity: float,
        size_type: str = 'quote',
        ignore_balance: bool = False,
        ignore_min_trade: bool = False,
        force_liquidate: bool = False
    ) -> Dict:
        """
        Place market order on Kraken.
        
        Args:
            symbol: Trading pair (e.g., 'BTC-USD' or 'XBTUSDT')
            side: 'buy' or 'sell'
            quantity: Order size in USD (for buys) or base currency (for sells)
        
        Returns:
            dict: Order result with status, order_id, etc.
        """
        try:
            if not self.api:
                return {"status": "error", "error": "Not connected to Kraken"}
            
            # 🚑 FIX #1: FORCE SELL OVERRIDE - SELL orders bypass ALL restrictions
            # ================================================================
            # CRITICAL: SELL orders are NEVER blocked by:
            #   ✅ MINIMUM_TRADING_BALANCE (balance checks only apply to BUY)
            #   ✅ MIN_CASH_TO_BUY (balance checks only apply to BUY)
            #   ✅ ENTRY_ONLY mode / EXIT_ONLY mode (blocks BUY, not SELL)
            #   ✅ Broker preference routing (SELL always executes)
            #   ✅ Emergency stop flags (only block BUY)
            #
            # This ensures:
            #   - Stop-loss exits always execute
            #   - Emergency liquidation always executes
            #   - Losing positions can always be closed
            #   - Capital bleeding can always be stopped
            # ================================================================
            
            # Log explicit bypass for SELL orders
            if side.lower() == 'sell':
                logger.info(f"🚑 SELL order for {symbol}: ALL RESTRICTIONS BYPASSED")
                logger.info(f"   ✅ Balance validation: SKIPPED (SELL only)")
                logger.info(f"   ✅ Minimum balance check: SKIPPED (SELL only)")
                logger.info(f"   ✅ EXIT-ONLY mode: ALLOWED (SELL only)")
                logger.info(f"   ✅ Emergency exit: ENABLED")
            
            # FIX 2: Reject BUY orders when in EXIT-ONLY mode
            # NOTE: SELL orders are NOT checked here - they always pass through
            if side.lower() == 'buy' and getattr(self, 'exit_only_mode', False) and not force_liquidate:
                logger.error(f"❌ BUY order rejected: Kraken is in EXIT-ONLY mode (balance < ${KRAKEN_MINIMUM_BALANCE:.2f})")
                logger.error(f"   Only SELL orders are allowed to close existing positions")
                logger.error(f"   To enable new entries, fund your account to at least ${KRAKEN_MINIMUM_BALANCE:.2f}")
                return {
                    "status": "unfilled",
                    "error": "EXIT_ONLY_MODE",
                    "message": f"BUY orders blocked: Account balance below ${KRAKEN_MINIMUM_BALANCE:.2f} minimum",
                    "partial_fill": False,
                    "filled_pct": 0.0
                }
            
            # CRITICAL FIX (Jan 19, 2026): Normalize symbol for Kraken and check support
            # Railway Golden Rule #4: Broker-specific trading pairs
            # This prevents trying to trade Binance-only pairs (BUSD) on Kraken
            if not self.supports_symbol(symbol):
                error_msg = f"Kraken does not support symbol: {symbol} (broker-specific pair filtering)"
                logger.warning(f"⏭️ SKIPPING TRADE: {error_msg}")
                logger.warning(f"   💡 TIP: This symbol contains unsupported quote currency for Kraken (e.g., BUSD)")
                return {"status": "error", "error": error_msg}
            
            # Normalize to Kraken format (ETH/USD, BTC/USDT, etc.)
            normalized_symbol = normalize_symbol_for_broker(symbol, self.broker_type.value)
            
            # Convert symbol format to Kraken internal format
            # Kraken uses XBTUSD, ETHUSD, etc. (no slash)
            # ETH/USD -> ETHUSD, BTC/USD -> XBTUSD
            kraken_symbol = normalized_symbol.replace('/', '').upper()
            
            # Kraken uses X prefix for BTC
            if kraken_symbol.startswith('BTC'):
                kraken_symbol = kraken_symbol.replace('BTC', 'XBT', 1)
            
            # Determine order type
            order_type = side.lower()  # 'buy' or 'sell'
            
            # Place market order using serialized API call
            # Kraken API: AddOrder(pair, type, ordertype, volume, ...)
            order_params = {
                'pair': kraken_symbol,
                'type': order_type,
                'ordertype': 'market',
                'volume': str(quantity)
            }
            
            result = self._kraken_private_call('AddOrder', order_params)
            
            if result and 'error' in result and result['error']:
                error_msgs = ', '.join(result['error'])
                logging.error(f"❌ Kraken order failed: {error_msgs}")
                return {"status": "error", "error": error_msgs}
            
            if result and 'result' in result:
                order_result = result['result']
                txid = order_result.get('txid', [])
                order_id = txid[0] if txid else None
                
                # Enhanced trade confirmation logging with account identification
                account_label = f"{self.account_identifier}" if hasattr(self, 'account_identifier') else "UNKNOWN"
                
                logging.info("=" * 70)
                logging.info(f"✅ TRADE CONFIRMATION - {account_label}")
                logging.info("=" * 70)
                logging.info(f"   Exchange: Kraken")
                logging.info(f"   Order Type: {order_type.upper()}")
                logging.info(f"   Symbol: {kraken_symbol}")
                logging.info(f"   Quantity: {quantity}")
                logging.info(f"   Order ID: {order_id}")
                logging.info(f"   Account: {account_label}")
                logging.info(f"   Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}")
                logging.info("=" * 70)
                
                # Flush logs immediately to ensure confirmation is visible
                if _root_logger.handlers:
                    for handler in _root_logger.handlers:
                        handler.flush()
                
                # COPY TRADING: Emit trade signal for master account trades
                # This allows user accounts to replicate master trades automatically
                try:
                    # Only emit signals for MASTER accounts (not USER accounts)
                    if self.account_type == AccountType.MASTER:
                        from trade_signal_emitter import emit_trade_signal
                        
                        # Get current balance for position sizing
                        balance_data = self.get_account_balance_detailed()
                        master_balance = balance_data.get('trading_balance', 0.0) if balance_data else 0.0
                        
                        # Get current price for this symbol
                        # For market orders, use a reasonable estimate
                        # In future, could fetch actual execution price from order details
                        exec_price = 0.0
                        try:
                            # Try to get current market price using public API
                            # Ticker is a public endpoint, so we use query_public instead of _kraken_private_call
                            ticker_result = self.api.query_public('Ticker', {'pair': kraken_symbol})
                            if ticker_result and 'result' in ticker_result:
                                ticker_data = ticker_result['result'].get(kraken_symbol, {})
                                if ticker_data:
                                    # Use last trade price if available
                                    last_price = ticker_data.get('c', [0.0])[0]  # 'c' is last trade closed array [price, lot volume]
                                    exec_price = float(last_price) if last_price else 0.0
                        except Exception as price_err:
                            logger.debug(f"Could not fetch execution price: {price_err}")
                        
                        # Determine broker name
                        broker_name = self.broker_type.value.lower() if hasattr(self, 'broker_type') else 'kraken'
                        
                        # Determine size_type (Kraken uses base currency quantity for market orders)
                        size_type = 'base'
                        
                        logger.info("📡 Emitting trade signal to copy engine")
                        
                        # Emit signal
                        signal_emitted = emit_trade_signal(
                            broker=broker_name,
                            symbol=symbol,  # Use original symbol format (e.g., BTC-USD)
                            side=side,
                            price=exec_price if exec_price else 0.0,
                            size=quantity,
                            size_type=size_type,
                            order_id=order_id,
                            master_balance=master_balance
                        )
                        
                        # Confirm signal emission status
                        if signal_emitted:
                            logger.info(f"✅ Trade signal emitted successfully for {symbol} {side}")
                        else:
                            logger.error(f"❌ Trade signal emission FAILED for {symbol} {side}")
                            logger.error("   ⚠️ User accounts will NOT copy this trade!")
                except Exception as signal_err:
                    # Don't fail the trade if signal emission fails
                    logger.warning(f"   ⚠️ Trade signal emission failed: {signal_err}")
                    logger.warning(f"   ⚠️ User accounts will NOT copy this trade!")
                    logger.warning(f"   Traceback: {traceback.format_exc()}")
                
                return {
                    "status": "filled",
                    "order_id": order_id,
                    "symbol": kraken_symbol,
                    "side": order_type,
                    "quantity": quantity,
                    "account": account_label  # Add account identification to result
                }
            
            logger.error("❌ Kraken order failed: No result data")
            return {"status": "error", "error": "No result data"}
            
        except Exception as e:
            logger.error(f"Kraken order error: {e}")
            return {"status": "error", "error": str(e)}
    
    def get_positions(self) -> List[Dict]:
        """
        Get open positions (non-zero balances).
        
        Returns:
            list: List of position dicts with symbol, quantity, currency
        """
        try:
            if not self.api:
                return []
            
            # Get account balance using serialized API call
            balance = self._kraken_private_call('Balance')
            
            if balance and 'error' in balance and balance['error']:
                error_msgs = ', '.join(balance['error'])
                logging.error(f"Error fetching Kraken positions: {error_msgs}")
                return []
            
            if balance and 'result' in balance:
                result = balance['result']
                positions = []
                
                for asset, amount in result.items():
                    balance_val = float(amount)
                    
                    # Skip USD/USDT and zero balances
                    if asset in ['ZUSD', 'USDT'] or balance_val <= 0:
                        continue
                    
                    # Convert Kraken asset codes to standard format
                    # XXBT -> BTC, XETH -> ETH, etc.
                    currency = asset
                    if currency.startswith('X') and len(currency) == 4:
                        currency = currency[1:]
                    if currency == 'XBT':
                        currency = 'BTC'
                    
                    # Create symbol (e.g., BTCUSD)
                    symbol = f'{currency}USD'
                    
                    positions.append({
                        'symbol': symbol,
                        'quantity': balance_val,
                        'currency': currency
                    })
                
                return positions
            
            return []
            
        except Exception as e:
            logging.error(f"Error fetching Kraken positions: {e}")
            return []
    
    def get_candles(self, symbol: str, timeframe: str, count: int) -> List[Dict]:
        """
        Get historical candle data from Kraken.
        
        Args:
            symbol: Trading pair (e.g., 'BTC-USD' or 'XBTUSD')
            timeframe: Candle interval ('1m', '5m', '15m', '1h', '1d', etc.)
            count: Number of candles to fetch (max 720)
        
        Returns:
            list: List of candle dicts with OHLCV data
        """
        try:
            if not self.kraken_api:
                return []
            
            # Convert symbol format to Kraken format
            kraken_symbol = symbol.replace('-', '').upper()
            if kraken_symbol.startswith('BTC'):
                kraken_symbol = kraken_symbol.replace('BTC', 'XBT', 1)
            
            # Map timeframe to Kraken interval (in minutes)
            # Kraken supports: 1, 5, 15, 30, 60, 240, 1440, 10080, 21600
            interval_map = {
                "1m": 1,
                "5m": 5,
                "15m": 15,
                "30m": 30,
                "1h": 60,
                "4h": 240,
                "1d": 1440
            }
            
            kraken_interval = interval_map.get(timeframe.lower(), 5)
            
            # Fetch OHLC data using pykrakenapi
            ohlc, last = self.kraken_api.get_ohlc_data(
                kraken_symbol,
                interval=kraken_interval,
                ascending=True
            )
            
            # Convert to standard format
            candles = []
            for idx, row in ohlc.tail(count).iterrows():
                candles.append({
                    'time': int(idx.timestamp()),
                    'open': float(row['open']),
                    'high': float(row['high']),
                    'low': float(row['low']),
                    'close': float(row['close']),
                    'volume': float(row['volume'])
                })
            
            return candles
            
        except Exception as e:
            logging.error(f"Error fetching Kraken candles: {e}")
            return []
    
    def supports_asset_class(self, asset_class: str) -> bool:
        """
        Kraken supports multiple asset classes.
        
        - Crypto: Spot trading via Kraken API (fully supported)
        - Futures: Via Kraken Futures API (enabled)
        - Stocks: Via AlpacaBroker integration (use AlpacaBroker for stocks)
        - Options: In development by Kraken (not yet available)
        
        Returns:
            bool: True if asset class is supported
        """
        supported = asset_class.lower() in ["crypto", "cryptocurrency", "futures"]
        return supported
    
    def get_all_products(self) -> list:
        """
        Get list of all tradeable cryptocurrency and futures pairs from Kraken.
        
        Includes:
        - Crypto spot pairs (BTC-USD, ETH-USD, etc.)
        - Futures pairs (if enable_futures is True in config)
        
        Returns:
            List of trading pairs in standard format (e.g., ['BTC-USD', 'ETH-USD', 'BTC-PERP', ...])
        """
        try:
            if not self.kraken_api:
                logging.warning("⚠️  Kraken not connected, cannot fetch products")
                return []
            
            # Get all tradable asset pairs (returns pandas DataFrame)
            asset_pairs = self.kraken_api.get_tradable_asset_pairs()
            
            # Extract pairs that trade against USD or USDT
            symbols = []
            futures_count = 0
            spot_count = 0
            
            # Iterate over DataFrame rows using iterrows()
            # pykrakenapi returns DataFrame with pair info including 'wsname' column
            for pair_name, pair_info in asset_pairs.iterrows():
                # Kraken uses format like 'XXBTZUSD' for BTC/USD
                # Convert to our standard format BTC-USD
                # Access DataFrame column value - pair_info is a pandas Series
                wsname = pair_info.get('wsname', '')
                if wsname and ('USD' in wsname or 'USDT' in wsname):
                    # Convert from Kraken format to standard format
                    # e.g., BTC/USD -> BTC-USD
                    symbol = wsname.replace('/', '-')
                    
                    # Detect futures pairs (contain 'PERP', 'F0', or quarter codes like 'Z24', 'H25')
                    # Kraken futures typically have symbols like BTC-PERP, ETH-F0, BTC-Z24
                    is_futures = any(x in symbol for x in ['PERP', 'F0', 'F1', 'F2', 'F3', 'F4'])
                    
                    if is_futures:
                        futures_count += 1
                        # Only add futures if enabled in config
                        from bot.broker_configs.kraken_config import KRAKEN_CONFIG
                        if KRAKEN_CONFIG.enable_futures:
                            symbols.append(symbol)
                    else:
                        spot_count += 1
                        symbols.append(symbol)
            
            logging.info(f"📊 Kraken: Found {spot_count} spot pairs + {futures_count} futures pairs = {len(symbols)} total tradable USD/USDT pairs")
            return symbols
            
        except Exception as e:
            logging.warning(f"⚠️  Error fetching Kraken products: {e}")
            # Return a fallback list of popular crypto pairs
            fallback_pairs = [
                'BTC-USD', 'ETH-USD', 'SOL-USD', 'XRP-USD', 'ADA-USD', 'DOGE-USD',
                'MATIC-USD', 'DOT-USD', 'LINK-USD', 'UNI-USD', 'AVAX-USD', 'ATOM-USD',
                'LTC-USD', 'ALGO-USD', 'XLM-USD'
            ]
            logging.info(f"📊 Kraken: Using fallback list of {len(fallback_pairs)} crypto pairs")
            return fallback_pairs


class OKXBroker(BaseBroker):
    """
    OKX Exchange integration for crypto spot and futures trading.
    
    Features:
    - Spot trading (USDT pairs)
    - Futures/perpetual contracts  
    - Testnet support for paper trading
    - Advanced order types
    
    Documentation: https://www.okx.com/docs-v5/en/
    Python SDK: https://github.com/okx/okx-python-sdk
    """
    
    def __init__(self, account_type: AccountType = AccountType.MASTER, user_id: Optional[str] = None):
        super().__init__(BrokerType.OKX, account_type=account_type, user_id=user_id)
        self.client = None
        self.account_api = None
        self.market_api = None
        self.trade_api = None
        self.use_testnet = False
        
        # Balance tracking for fail-closed behavior (Jan 19, 2026)
        # When balance fetch fails, preserve last known balance instead of returning 0
        self._last_known_balance = None  # Last successful balance fetch
        self._balance_fetch_errors = 0   # Count of consecutive errors
        self._is_available = True        # Broker availability flag
    
    def connect(self) -> bool:
        """
        Connect to OKX Exchange API with retry logic.
        
        Requires environment variables:
        - OKX_API_KEY: Your OKX API key
        - OKX_API_SECRET: Your OKX API secret
        - OKX_PASSPHRASE: Your OKX API passphrase
        - OKX_USE_TESTNET: 'true' for testnet, 'false' for live (optional, default: false)
        
        Returns:
            bool: True if connected successfully
        """
        try:
            from okx.api import Account, Market, Trade
            import time
            
            api_key = os.getenv("OKX_API_KEY", "").strip()
            api_secret = os.getenv("OKX_API_SECRET", "").strip()
            passphrase = os.getenv("OKX_PASSPHRASE", "").strip()
            self.use_testnet = os.getenv("OKX_USE_TESTNET", "false").lower() in ["true", "1", "yes"]
            
            if not api_key or not api_secret or not passphrase:
                # Silently skip - OKX is optional, no need for scary error messages
                logging.info("⚠️  OKX credentials not configured (skipping)")
                return False
            
            
            # Check for placeholder passphrase (most common user error)
            # Note: Only checking passphrase because API keys are UUIDs/hex without obvious placeholder patterns
            if passphrase in PLACEHOLDER_PASSPHRASE_VALUES:
                logging.warning("⚠️  OKX passphrase appears to be a placeholder value")
                logging.warning("   Please set a valid OKX_PASSPHRASE in your environment")
                logging.warning("   Current value looks like a placeholder (e.g., 'your_passphrase')")
                logging.warning("   Replace it with your actual OKX API passphrase from https://www.okx.com/account/my-api")
                return False
            
            # Determine API flag (0 = live, 1 = testnet)
            flag = "1" if self.use_testnet else "0"
            
            # Initialize OKX API clients
            self.account_api = Account(api_key, api_secret, passphrase, flag)
            self.market_api = Market(api_key, api_secret, passphrase, flag)
            self.trade_api = Trade(api_key, api_secret, passphrase, flag)
            
            # Test connection by fetching account balance with retry logic
            # Increased max attempts for 403 "too many errors" which indicates temporary API key blocking
            # Note: 403 differs from 429 (rate limiting) - it means the API key was temporarily blocked
            max_attempts = 5
            base_delay = 5.0  # Increased from 2.0 to allow API key blocks to reset
            
            for attempt in range(1, max_attempts + 1):
                try:
                    if attempt > 1:
                        # Add delay before retry with exponential backoff
                        # For 403 errors, we need longer delays: 5s, 10s, 20s, 40s (attempts 2-5)
                        delay = base_delay * (2 ** (attempt - 2))
                        logging.info(f"🔄 Retrying OKX connection in {delay}s (attempt {attempt}/{max_attempts})...")
                        time.sleep(delay)
                    
                    result = self.account_api.get_balance()
                    
                    if result and result.get('code') == '0':
                        self.connected = True
                        
                        if attempt > 1:
                            logging.info(f"✅ Connected to OKX API (succeeded on attempt {attempt})")
                        
                        env_type = "🧪 TESTNET" if self.use_testnet else "🔴 LIVE"
                        logging.info("=" * 70)
                        logging.info(f"✅ OKX CONNECTED ({env_type})")
                        logging.info("=" * 70)
                        
                        # Log account info
                        data = result.get('data', [])
                        if data and len(data) > 0:
                            total_eq = data[0].get('totalEq', '0')
                            logging.info(f"   Total Account Value: ${float(total_eq):.2f}")
                        
                        logging.info("=" * 70)
                        return True
                    else:
                        error_msg = result.get('msg', 'Unknown error') if result else 'No response'
                        
                        # Check if error is retryable
                        is_retryable = any(keyword in error_msg.lower() for keyword in [
                            'timeout', 'connection', 'network', 'rate limit',
                            'too many requests', 'service unavailable',
                            '503', '504', '429', '403', 'forbidden', 
                            'too many errors', 'temporary', 'try again'
                        ])
                        
                        if is_retryable and attempt < max_attempts:
                            logging.warning(f"⚠️  OKX connection attempt {attempt}/{max_attempts} failed (retryable): {error_msg}")
                            continue
                        else:
                            logging.warning(f"⚠️  OKX connection test failed: {error_msg}")
                            return False
                
                except Exception as e:
                    error_msg = str(e)
                    
                    # Check if error is retryable (rate limiting, network issues, 403 errors, etc.)
                    # CRITICAL: Include 403, forbidden, and "too many errors" as retryable
                    # These indicate API key blocking and need longer cooldown periods
                    is_retryable = any(keyword in error_msg.lower() for keyword in [
                        'timeout', 'connection', 'network', 'rate limit',
                        'too many requests', 'service unavailable',
                        '503', '504', '429', '403', 'forbidden', 
                        'too many errors', 'temporary', 'try again'
                    ])
                    
                    if is_retryable and attempt < max_attempts:
                        logging.warning(f"⚠️  OKX connection attempt {attempt}/{max_attempts} failed (retryable): {error_msg}")
                        continue
                    else:
                        # Handle authentication errors gracefully
                        # Note: OKX error code 50119 = "API key doesn't exist"
                        error_str = error_msg.lower()
                        if 'api key' in error_str or '401' in error_str or 'authentication' in error_str or '50119' in error_str:
                            logging.warning("⚠️  OKX authentication failed - invalid or expired API credentials")
                            logging.warning("   Please check your OKX_API_KEY, OKX_API_SECRET, and OKX_PASSPHRASE")
                        elif 'connection' in error_str or 'network' in error_str or 'timeout' in error_str:
                            logging.warning("⚠️  OKX connection failed - network issue or API unavailable")
                        else:
                            logging.warning(f"⚠️  OKX connection failed: {e}")
                        return False
            
            # Should never reach here, but just in case
            logging.error("❌ Failed to connect to OKX after maximum retry attempts")
            return False
                
        except ImportError as e:
            # SDK not installed or import failed
            logging.error("❌ OKX connection failed: SDK import error")
            logging.error(f"   ImportError: {e}")
            logging.error("   The OKX SDK (okx) failed to import")
            logging.error("")
            logging.error("   📋 Troubleshooting steps:")
            logging.error("      1. Verify okx is in requirements.txt")
            logging.error("      2. Check deployment logs for package installation errors")
            logging.error("      3. Try manual install: pip install okx")
            logging.error("      4. Check for dependency conflicts with: pip check")
            return False
    
    def get_account_balance(self) -> float:
        """
        Get total equity (USDT + position values) with fail-closed behavior.
        
        CRITICAL FIX (Rule #3): Balance = CASH + POSITION VALUE
        Returns total equity (available cash + position market value), not just available balance.
        This ensures risk calculations and position sizing account for capital deployed in positions.
        
        CRITICAL FIX (Jan 19, 2026): Fail closed - not "balance = 0"
        - On error: Return last known balance (if available) instead of 0
        - Track consecutive errors to mark broker unavailable
        - Distinguish API errors from actual zero balance
        
        Returns:
            float: Total equity (available USDT + position values)
                   Returns last known balance on error (not 0)
        """
        try:
            if not self.account_api:
                # Not connected - return last known balance if available
                if self._last_known_balance is not None:
                    logger.warning(f"⚠️ OKX API not connected, using last known balance: ${self._last_known_balance:.2f}")
                    self._balance_fetch_errors += 1
                    if self._balance_fetch_errors >= BROKER_MAX_CONSECUTIVE_ERRORS:
                        self._is_available = False
                        logger.error(f"❌ OKX marked unavailable after {self._balance_fetch_errors} consecutive errors")
                    return self._last_known_balance
                else:
                    logger.error("❌ OKX API not connected and no last known balance")
                    self._balance_fetch_errors += 1
                    self._is_available = False
                    return 0.0
            
            # Get account balance (available cash)
            result = self.account_api.get_balance()
            
            if result and result.get('code') == '0':
                data = result.get('data', [])
                if data and len(data) > 0:
                    details = data[0].get('details', [])
                    
                    # Find USDT balance
                    available = 0.0
                    for detail in details:
                        if detail.get('ccy') == 'USDT':
                            available = float(detail.get('availBal', 0))
                            break
                    
                    # FIX Rule #3: Get position values and add to available cash
                    position_value = 0.0
                    try:
                        positions = self.get_positions()
                        for pos in positions:
                            symbol = pos.get('symbol', '')
                            quantity = pos.get('quantity', 0.0)
                            if symbol and quantity > 0:
                                # Get current price for this position
                                try:
                                    price = self.get_current_price(symbol)
                                    if price > 0:
                                        pos_value = quantity * price
                                        position_value += pos_value
                                        logger.debug(f"   Position {symbol}: {quantity:.8f} @ ${price:.2f} = ${pos_value:.2f}")
                                except Exception as price_err:
                                    logger.debug(f"   Could not price position {symbol}: {price_err}")
                                    # If we can't price a position, skip it rather than fail
                                    continue
                    except Exception as pos_err:
                        logger.debug(f"   Could not fetch positions: {pos_err}")
                        # Continue with just cash balance if positions can't be fetched
                    
                    # Calculate total equity
                    total_equity = available + position_value
                    
                    # Enhanced logging
                    logger.info("=" * 70)
                    logger.info(f"💰 OKX Balance:")
                    logger.info(f"   ✅ Available USDT: ${available:.2f}")
                    if position_value > 0:
                        logger.info(f"   📊 Position Value: ${position_value:.2f}")
                        logger.info(f"   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
                        logger.info(f"   💎 TOTAL EQUITY (Available + Positions): ${total_equity:.2f}")
                    else:
                        logger.info(f"   💎 TOTAL EQUITY: ${total_equity:.2f} (no positions)")
                    logger.info("=" * 70)
                    
                    # SUCCESS: Update last known balance and reset error count
                    self._last_known_balance = total_equity
                    self._balance_fetch_errors = 0
                    self._is_available = True
                    
                    return total_equity
                
                # No USDT found - treat as zero balance (not an error)
                logger.warning("⚠️  No USDT balance found in OKX account")
                # Update last known balance to 0 (this is a successful API call, just zero balance)
                self._last_known_balance = 0.0
                self._balance_fetch_errors = 0
                self._is_available = True
                return 0.0
            else:
                error_msg = result.get('msg', 'Unknown error') if result else 'No response'
                logger.error(f"❌ OKX API error fetching balance: {error_msg}")
                
                # Return last known balance instead of 0
                self._balance_fetch_errors += 1
                if self._balance_fetch_errors >= BROKER_MAX_CONSECUTIVE_ERRORS:
                    self._is_available = False
                    logger.error(f"❌ OKX marked unavailable after {self._balance_fetch_errors} consecutive errors")
                
                if self._last_known_balance is not None:
                    logger.warning(f"   ⚠️ Using last known balance: ${self._last_known_balance:.2f}")
                    return self._last_known_balance
                else:
                    logger.error(f"   ❌ No last known balance available, returning 0")
                    return 0.0
                
        except Exception as e:
            logger.error(f"❌ Exception fetching OKX balance: {e}")
            self._balance_fetch_errors += 1
            if self._balance_fetch_errors >= BROKER_MAX_CONSECUTIVE_ERRORS:
                self._is_available = False
                logger.error(f"❌ OKX marked unavailable after {self._balance_fetch_errors} consecutive errors")
            
            # Return last known balance instead of 0
            if self._last_known_balance is not None:
                logger.warning(f"   ⚠️ Using last known balance: ${self._last_known_balance:.2f}")
                return self._last_known_balance
            
            return 0.0
    
    def is_available(self) -> bool:
        """
        Check if OKX broker is available for trading.
        
        Returns False if there have been 3+ consecutive balance fetch errors.
        This prevents trading when the API is not working properly.
        
        Returns:
            bool: True if broker is available, False if unavailable
        """
        return self._is_available
    
    def get_error_count(self) -> int:
        """
        Get the number of consecutive balance fetch errors.
        
        Returns:
            int: Number of consecutive errors
        """
        return self._balance_fetch_errors
    
    def place_market_order(self, symbol: str, side: str, quantity: float) -> Dict:
        """
        Place market order on OKX.
        
        Args:
            symbol: Trading pair (e.g., 'BTC-USDT')
            side: 'buy' or 'sell'
            quantity: Order size in USDT (for buys) or base currency (for sells)
        
        Returns:
            dict: Order result with status, order_id, etc.
        """
        try:
            if not self.trade_api:
                return {"status": "error", "error": "Not connected to OKX"}
            
            # Convert symbol format if needed (BTC-USD -> BTC-USDT)
            okx_symbol = symbol.replace('-USD', '-USDT') if '-USD' in symbol else symbol
            
            # Determine order side (buy/sell)
            okx_side = side.lower()
            
            # Place market order
            # For spot trading: tdMode = 'cash'
            # For margin/futures: tdMode = 'cross' or 'isolated'
            result = self.trade_api.place_order(
                instId=okx_symbol,
                tdMode='cash',  # Spot trading mode
                side=okx_side,
                ordType='market',
                sz=str(quantity)
            )
            
            if result and result.get('code') == '0':
                data = result.get('data', [])
                if data and len(data) > 0:
                    order_id = data[0].get('ordId')
                    logging.info(f"✅ OKX order placed: {okx_side.upper()} {okx_symbol} (Order ID: {order_id})")
                    return {
                        "status": "filled",
                        "order_id": order_id,
                        "symbol": okx_symbol,
                        "side": okx_side,
                        "quantity": quantity
                    }
            
            error_msg = result.get('msg', 'Unknown error') if result else 'No response'
            logging.error(f"❌ OKX order failed: {error_msg}")
            return {"status": "error", "error": error_msg}
            
        except Exception as e:
            logging.error(f"OKX order error: {e}")
            return {"status": "error", "error": str(e)}
    
    def get_positions(self) -> List[Dict]:
        """
        Get open positions (non-zero balances).
        
        Returns:
            list: List of position dicts with symbol, quantity, currency
        """
        try:
            if not self.account_api:
                return []
            
            # Get account balance to see all assets
            result = self.account_api.get_balance()
            
            if result and result.get('code') == '0':
                positions = []
                data = result.get('data', [])
                
                if data and len(data) > 0:
                    details = data[0].get('details', [])
                    
                    for detail in details:
                        ccy = detail.get('ccy')
                        available = float(detail.get('availBal', 0))
                        
                        # Only include non-zero, non-USDT balances
                        if ccy != 'USDT' and available > 0:
                            positions.append({
                                'symbol': f'{ccy}-USDT',
                                'quantity': available,
                                'currency': ccy
                            })
                
                return positions
            
            return []
            
        except Exception as e:
            logging.error(f"Error fetching OKX positions: {e}")
            return []
    
    def get_candles(self, symbol: str, timeframe: str, count: int) -> List[Dict]:
        """
        Get historical candle data from OKX.
        
        Args:
            symbol: Trading pair (e.g., 'BTC-USDT')
            timeframe: Candle interval ('1m', '5m', '15m', '1H', '1D', etc.)
            count: Number of candles to fetch (max 100)
        
        Returns:
            list: List of candle dicts with OHLCV data
        """
        try:
            if not self.market_api:
                return []
            
            # Convert symbol format if needed
            okx_symbol = symbol.replace('-USD', '-USDT') if '-USD' in symbol else symbol
            
            # Map timeframe to OKX format
            # OKX uses: 1m, 3m, 5m, 15m, 30m, 1H, 2H, 4H, 6H, 12H, 1D, 1W, 1M
            timeframe_map = {
                "1m": "1m",
                "5m": "5m", 
                "15m": "15m",
                "1h": "1H",
                "4h": "4H",
                "1d": "1D"
            }
            
            okx_timeframe = timeframe_map.get(timeframe.lower(), "5m")
            
            # Fetch candles
            result = self.market_api.get_candles(
                instId=okx_symbol,
                bar=okx_timeframe,
                limit=str(min(count, 100))  # OKX max is 100
            )
            
            if result and result.get('code') == '0':
                data = result.get('data', [])
                candles = []
                
                for candle in data:
                    # OKX candle format: [timestamp, open, high, low, close, volume, volumeCcy, volumeCcyQuote, confirm]
                    candles.append({
                        'time': int(candle[0]),
                        'open': float(candle[1]),
                        'high': float(candle[2]),
                        'low': float(candle[3]),
                        'close': float(candle[4]),
                        'volume': float(candle[5])
                    })
                
                return candles
            
            return []
            
        except Exception as e:
            logging.error(f"Error fetching OKX candles: {e}")
            return []
    
    def get_current_price(self, symbol: str) -> float:
        """
        Get current market price for a symbol.
        
        Args:
            symbol: Trading pair (e.g., 'BTC-USDT')
        
        Returns:
            float: Current price or 0.0 on error
        """
        try:
            if not self.market_api:
                return 0.0
            
            # Convert symbol format if needed
            okx_symbol = symbol.replace('-USD', '-USDT') if '-USD' in symbol else symbol
            
            # Get ticker data
            result = self.market_api.get_ticker(instId=okx_symbol)
            
            if result and result.get('code') == '0':
                data = result.get('data', [])
                if data and len(data) > 0:
                    last_price = data[0].get('last')
                    return float(last_price) if last_price else 0.0
            
            return 0.0
            
        except Exception as e:
            logging.debug(f"Error fetching OKX price for {symbol}: {e}")
            return 0.0
    
    def supports_asset_class(self, asset_class: str) -> bool:
        """OKX supports crypto spot and futures"""
        return asset_class.lower() in ["crypto", "futures"]
    
    def get_all_products(self) -> list:
        """
        Get list of all tradeable cryptocurrency pairs from OKX.
        
        Returns:
            List of trading pairs (e.g., ['BTC-USDT', 'ETH-USDT', ...])
        """
        try:
            if not self.market_api:
                logging.warning("⚠️  OKX not connected, cannot fetch products")
                return []
            
            # Get all trading instruments (spot trading)
            result = self.market_api.get_instruments(instType='SPOT')
            
            if result and result.get('code') == '0':
                instruments = result.get('data', [])
                
                # Extract symbols that trade against USDT
                symbols = []
                for inst in instruments:
                    inst_id = inst.get('instId', '')
                    # Filter for USDT pairs
                    if inst_id.endswith('-USDT') and inst.get('state') == 'live':
                        symbols.append(inst_id)
                
                logging.info(f"📊 OKX: Found {len(symbols)} tradeable USDT pairs")
                return symbols
            else:
                logging.warning(f"⚠️  OKX API returned error: {result.get('msg', 'Unknown error')}")
                return self._get_okx_fallback_pairs()
            
        except Exception as e:
            logging.warning(f"⚠️  Error fetching OKX products: {e}")
            return self._get_okx_fallback_pairs()
    
    def _get_okx_fallback_pairs(self) -> list:
        """Get fallback list of popular OKX trading pairs"""
        fallback_pairs = [
            'BTC-USDT', 'ETH-USDT', 'SOL-USDT', 'XRP-USDT', 'ADA-USDT', 'DOGE-USDT',
            'MATIC-USDT', 'DOT-USDT', 'LINK-USDT', 'UNI-USDT', 'AVAX-USDT', 'ATOM-USDT',
            'LTC-USDT', 'NEAR-USDT', 'ALGO-USDT', 'XLM-USDT', 'HBAR-USDT', 'APT-USDT'
        ]
        logging.info(f"📊 OKX: Using fallback list of {len(fallback_pairs)} crypto pairs")
        return fallback_pairs


class BrokerManager:
    """
    Manages multiple broker connections with independent operation.
    
    ARCHITECTURE (Jan 10, 2026 Update):
    ------------------------------------
    Each broker operates INDEPENDENTLY and should NOT affect other brokers.
    
    The "primary broker" concept exists only for backward compatibility:
    - Used by legacy single-broker code paths
    - Used for master account position cap enforcement
    - Does NOT control independent broker trading
    
    For multi-broker trading, use IndependentBrokerTrader which:
    - Runs each broker in its own thread
    - Isolates errors between brokers
    - Prevents cascade failures
    - Ensures one broker's issues don't affect others
    
    CRITICAL: No broker should have automatic priority over others.
    Previously, Coinbase was automatically set as primary, which caused
    it to control trading decisions for all brokers. This has been fixed.
    """
    
    def __init__(self):
        self.brokers: Dict[BrokerType, BaseBroker] = {}
        self.active_broker: Optional[BaseBroker] = None
        self.primary_broker_type: Optional[BrokerType] = None
    
    def add_broker(self, broker: BaseBroker):
        """
        Add a broker to the manager.
        
        IMPORTANT: Each broker is independent and should be treated equally.
        No broker automatically becomes "primary" - this prevents one broker
        from controlling or affecting trading decisions for other brokers.
        
        To set a primary broker for legacy compatibility, explicitly call
        set_primary_broker() after adding brokers.
        """
        self.brokers[broker.broker_type] = broker
        
        # CRITICAL FIX (Jan 10, 2026): Remove automatic primary broker selection
        # Previously, Coinbase was automatically set as primary, which made it
        # control trading logic for all other brokers. Each broker should operate
        # independently without one broker affecting others.
        # 
        # Auto-set first broker as primary ONLY if no primary is set yet
        # This maintains backward compatibility while removing Coinbase preference
        if self.active_broker is None:
            self.set_primary_broker(broker.broker_type)
            logger.info(f"   First broker {broker.broker_type.value} set as primary (for legacy compatibility)")
        
        # NOTE: Removed automatic Coinbase priority logic
        # Old logic: "Always prefer Coinbase as primary if available"
        # This was causing Coinbase to control other brokerages
        # Each broker now operates independently through IndependentBrokerTrader
        
        logger.info(f"📊 Added {broker.broker_type.value} broker (independent operation)")
    
    def set_primary_broker(self, broker_type: BrokerType) -> bool:
        """
        Set a specific broker as the primary/active broker.
        
        NOTE: This method exists for backward compatibility with legacy code
        that expects a "primary" broker. In modern multi-broker architecture,
        each broker should operate independently via IndependentBrokerTrader.
        
        The primary broker is used only for:
        - Legacy single-broker trading logic
        - Position cap enforcement (shared across master account)
        - Backward compatibility with older code
        
        It does NOT control or affect other brokers' independent trading.
        
        Args:
            broker_type: Type of broker to set as primary
            
        Returns:
            bool: True if successfully set as primary
        """
        if broker_type in self.brokers:
            self.active_broker = self.brokers[broker_type]
            self.primary_broker_type = broker_type
            logging.info(f"📌 PRIMARY BROKER SET: {broker_type.value}")
            return True
        else:
            logging.warning(f"⚠️  Cannot set {broker_type.value} as primary - not connected")
            return False
    
    def get_primary_broker(self) -> Optional[BaseBroker]:
        """
        Get the current primary/active broker.
        
        Returns:
            BaseBroker instance or None if no broker is active
        """
        return self.active_broker
    
    def connect_all(self):
        """Connect to all configured brokers"""
        logger.info("")
        logger.info("🔌 Connecting to brokers...")
        for broker in self.brokers.values():
            broker.connect()
    
    def get_broker_for_symbol(self, symbol: str) -> Optional[BaseBroker]:
        """Get appropriate broker for a symbol"""
        from market_adapter import market_adapter
        
        # Detect market type
        market_type = market_adapter.detect_market_type(symbol)
        
        # Map to asset class
        asset_class_map = {
            "crypto": "crypto",
            "stocks": "stocks",
            "futures": "futures",
            "options": "options"
        }
        
        asset_class = asset_class_map.get(market_type.value, "stocks")
        
        # Find broker that supports this asset class
        for broker in self.brokers.values():
            if broker.connected and broker.supports_asset_class(asset_class):
                return broker
        
        return None
    
    def place_order(self, symbol: str, side: str, quantity: float) -> Dict:
        """Route order to appropriate broker"""
        broker = self.get_broker_for_symbol(symbol)
        
        if not broker:
            return {
                "status": "error",
                "error": f"No broker available for {symbol}"
            }
        
        logger.info(f"📤 Routing {side} order for {symbol} to {broker.broker_type.value}")
        return broker.place_market_order(symbol, side, quantity)
    
    def get_total_balance(self) -> float:
        """Get total USD balance across all brokers"""
        total = 0.0
        for broker in self.brokers.values():
            if broker.connected:
                total += broker.get_account_balance()
        return total
    
    def get_all_positions(self) -> List[Dict]:
        """Get positions from all brokers"""
        all_positions = []
        for broker_type, broker in self.brokers.items():
            if broker.connected:
                positions = broker.get_positions()
                for pos in positions:
                    pos['broker'] = broker_type.value
                all_positions.extend(positions)
        return all_positions
    
    def get_connected_brokers(self) -> List[str]:
        """Get list of connected broker names"""
        return [b.broker_type.value for b in self.brokers.values() if b.connected]

# Global instance
broker_manager = BrokerManager()
