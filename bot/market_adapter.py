# market_adapter.py
"""
NIJA MARKET ADAPTER™
Auto-detect market type and adjust risk/volatility parameters

Supports:
- Crypto (Spot + Futures + Coinbase)
- Stocks (Intraday Trading)
- Futures (Indexes: S&P, NASDAQ, Dow, Gold, Oil)
- Options (Day trading contracts)
"""

from enum import Enum
from dataclasses import dataclass
from typing import Tuple

class MarketType(Enum):
    CRYPTO = "crypto"
    STOCKS = "stocks"
    FUTURES = "futures"
    OPTIONS = "options"

@dataclass
class MarketParameters:
    """Market-specific trading parameters"""
    market_type: MarketType

    # Stop-Loss & Take-Profit
    sl_min: float
    sl_max: float
    tp1: float
    tp2: float
    tp3_min: float
    tp3_max: float

    # Position Sizing
    position_min: float
    position_max: float

    # Trailing
    use_ema_trail: bool
    use_percentage_trail: bool
    percentage_trail_threshold: float

    # Limits
    max_daily_trades: int
    max_daily_loss: float  # as percentage

    # Options-specific
    min_delta: float = 0.0
    max_bid_ask_spread: float = 0.0
    min_volume: int = 0
    max_iv_rank: float = 0.0

class MarketAdapter:
    """Auto-detect and configure market-specific parameters"""

    def __init__(self):
        self.market_configs = {
            MarketType.CRYPTO: MarketParameters(
                market_type=MarketType.CRYPTO,
                sl_min=0.0075,  # 0.75% (WIDER for bigger moves)
                sl_max=0.015,   # 1.5% (WIDER for volatility)
                tp1=0.015,      # 1.5% (HIGHER first target)
                tp2=0.030,      # 3.0% (HIGHER second target)
                tp3_min=0.040,  # 4.0% (HIGHER third zone)
                tp3_max=0.100,  # 10.0% (Let runners GO!)
                position_min=0.02,  # 2% (HARD MINIMUM)
                position_max=0.10,  # 10% (HARD MAXIMUM)
                use_ema_trail=True,
                use_percentage_trail=True,
                percentage_trail_threshold=0.015,  # Active at TP1 (1.5%)
                max_daily_trades=20,  # More trades allowed
                max_daily_loss=0.025  # 2.5%
            ),

            MarketType.STOCKS: MarketParameters(
                market_type=MarketType.STOCKS,
                sl_min=0.0015,  # 0.15%
                sl_max=0.0030,  # 0.30%
                tp1=0.0025,     # 0.25%
                tp2=0.0050,     # 0.50%
                tp3_min=0.0075, # 0.75%
                tp3_max=0.010,  # 1.0%
                position_min=0.02,  # 2% (HARD MINIMUM)
                position_max=0.10,  # 10% (HARD MAXIMUM)
                use_ema_trail=True,
                use_percentage_trail=True,
                percentage_trail_threshold=0.0075,  # Active above +0.75%
                max_daily_trades=10,
                max_daily_loss=0.025  # 2.5%
            ),

            MarketType.FUTURES: MarketParameters(
                market_type=MarketType.FUTURES,
                sl_min=0.0015,  # 0.15% (ES)
                sl_max=0.0050,  # 0.50% (GOLD)
                tp1=0.0025,     # 0.25%
                tp2=0.0050,     # 0.50%
                tp3_min=0.0075, # 0.75%
                tp3_max=0.010,  # 1.0%
                position_min=0.02,  # 2% (HARD MINIMUM)
                position_max=0.10,  # 10% (HARD MAXIMUM)
                use_ema_trail=True,
                use_percentage_trail=True,
                percentage_trail_threshold=0.005,  # Active at +0.5%
                max_daily_trades=7,
                max_daily_loss=0.025  # 2.5%
            ),

            MarketType.OPTIONS: MarketParameters(
                market_type=MarketType.OPTIONS,
                sl_min=0.10,    # 10% of premium
                sl_max=0.20,    # 20% of premium
                tp1=0.15,       # 15%
                tp2=0.25,       # 25%
                tp3_min=0.40,   # 40%
                tp3_max=0.50,   # 50%
                position_min=0.02,  # 2% (HARD MINIMUM)
                position_max=0.10,  # 10% (HARD MAXIMUM)
                use_ema_trail=True,
                use_percentage_trail=True,
                percentage_trail_threshold=0.15,  # Active at TP1
                max_daily_trades=5,
                max_daily_loss=0.025,  # 2.5%
                # Options-specific filters
                min_delta=0.30,
                max_bid_ask_spread=0.08,  # 8%
                min_volume=500,
                max_iv_rank=50.0
            )
        }

    def detect_market_type(self, symbol: str) -> MarketType:
        """
        Auto-detect market type from symbol

        Examples:
        - BTC-USD, ETH-USD, FORTH-USDC → CRYPTO
        - AAPL, TSLA, SPY → STOCKS
        - ES, NQ, GC, CL → FUTURES
        - AAPL250117C00150000 → OPTIONS
        """
        symbol = symbol.upper()

        # Crypto patterns - check for crypto pairs first
        if '-USD' in symbol or '-USDC' in symbol or '-USDT' in symbol:
            return MarketType.CRYPTO

        if any(crypto in symbol for crypto in ['BTC', 'ETH', 'SOL', 'DOGE', 'XRP', 'ADA']):
            return MarketType.CRYPTO

        # Futures patterns
        futures_symbols = ['ES', 'NQ', 'YM', 'RTY', 'GC', 'SI', 'CL', 'NG', 'ZB', 'ZN']
        if any(symbol.startswith(fut) for fut in futures_symbols):
            return MarketType.FUTURES

        # Options pattern (contains strike/expiry)
        if len(symbol) > 10 and any(c in symbol for c in ['C', 'P']) and any(c.isdigit() for c in symbol):
            return MarketType.OPTIONS

        # Default to stocks
        return MarketType.STOCKS

    def get_parameters(self, symbol: str) -> MarketParameters:
        """Get market-specific parameters for symbol"""
        market_type = self.detect_market_type(symbol)
        return self.market_configs[market_type]

    def adjust_stop_loss(self, symbol: str, entry_price: float, volatility: float) -> float:
        """Calculate market-adjusted stop-loss"""
        params = self.get_parameters(symbol)

        # PROFITABILITY FIX (Feb 3, 2026): Disable ultra-tight stops for crypto
        # These 0.15-0.25% stops are for futures only, NOT crypto
        # Crypto volatility: 0.3-0.8% intraday, needs 1.5%+ stops (handled in trading_strategy.py)
        # For futures, could implement tick-based logic here
        if params.market_type == MarketType.FUTURES:
            # Example: ES tick = 0.25, NQ tick = 0.25, GC tick = 0.10
            if symbol.startswith('ES'):
                sl_pct = 0.0015 + (volatility * 5)  # 0.15-0.25%
            elif symbol.startswith('NQ'):
                sl_pct = 0.0025 + (volatility * 7.5)  # 0.25-0.40%
            elif symbol.startswith('GC') or symbol.startswith('SI'):
                sl_pct = 0.0030 + (volatility * 10)  # 0.30-0.50%
            else:
                sl_pct = params.sl_min + (volatility * 10)
        else:
            # CRYPTO/STOCKS: Use strategy-level stops (1.5%), NOT market adapter
            # Previously this was applying 0.15% stops to crypto = death by whipsaws
            # Now delegates to trading_strategy.py which uses proper 1.5% crypto stops
            sl_pct = params.sl_min + (volatility * 10)  # Will be overridden by trading_strategy.py

        # Clamp to market limits
        sl_pct = max(params.sl_min, min(sl_pct, params.sl_max))

        return entry_price * (1 - sl_pct)

    def get_position_size(self, symbol: str, signal_score: int, account_balance: float) -> float:
        """Calculate market-adjusted position size - AGGRESSIVE: 3-15% of account, MIN: $0.01"""
        params = self.get_parameters(symbol)

        # AGGRESSIVE Score-based allocation: 3-15% range (50% more than before)
        if signal_score <= 1:
            allocation_pct = 0.03  # 3% for score 1 (increased from 2%)
        elif signal_score == 2:
            allocation_pct = 0.05  # 5% for score 2 (increased from 2%)
        elif signal_score == 3:
            allocation_pct = 0.08  # 8% for score 3 (increased from 4.4%)
        elif signal_score == 4:
            allocation_pct = 0.12  # 12% for score 4 (increased from 6.8%)
        elif signal_score >= 5:
            allocation_pct = 0.15  # Maximum 15% for A+ setups (increased from 10%)
        else:
            allocation_pct = 0.03  # Default minimum

        position_size = account_balance * allocation_pct

        # COINBASE MINIMUM ENFORCEMENT:
        # - Target 3-15% of account balance (AGGRESSIVE)
        # - Coinbase Advanced Trade minimum: $5.00 per order
        # - Never exceed 15% of account
        min_size = max(5.00, account_balance * 0.03)  # Greater of $5.00 or 3% (Coinbase minimum)
        max_size = account_balance * 0.15

        return max(min_size, min(position_size, max_size))

    def validate_options_entry(self, options_data: dict) -> Tuple[bool, str]:
        """
        Validate options contract meets NIJA filters

        Required data:
        - delta: float
        - bid_ask_spread: float (percentage)
        - volume: int
        - iv_rank: float
        """
        params = self.market_configs[MarketType.OPTIONS]

        # Check delta
        if options_data.get('delta', 0) < params.min_delta:
            return False, f"Delta too low: {options_data.get('delta')} < {params.min_delta}"

        # Check bid/ask spread
        spread = options_data.get('bid_ask_spread', 1.0)
        if spread > params.max_bid_ask_spread:
            return False, f"Bid/ask spread too wide: {spread*100:.1f}%"

        # Check volume
        if options_data.get('volume', 0) < params.min_volume:
            return False, f"Volume too low: {options_data.get('volume')} < {params.min_volume}"

        # Check IV rank
        if options_data.get('iv_rank', 100) > params.max_iv_rank:
            return False, f"IV Rank too high: {options_data.get('iv_rank')} > {params.max_iv_rank}"

        return True, "Options filters passed"

    def supports_shorting(self, symbol: str, broker: str = None) -> bool:
        """
        Check if market supports shorting.

        DEPRECATED (Jan 2026): This method is being replaced by exchange_capabilities.py
        which provides more accurate broker + symbol-specific capability checking.

        Migration Timeline:
        - Jan 2026: New exchange_capabilities.py module introduced
        - Feb 2026: All call sites should migrate to using can_short(broker, symbol)
        - Mar 2026: This method will be removed

        Migration Instructions:
        Instead of:
            market_adapter.supports_shorting(symbol)
        Use:
            from exchange_capabilities import can_short
            can_short(broker_name, symbol)

        Args:
            symbol: Trading symbol
            broker: Optional broker name for exchange-specific checking

        Returns:
            True if shorting is supported
        """
        # If broker provided, use new capability matrix
        if broker:
            try:
                from exchange_capabilities import can_short
                return can_short(broker, symbol)
            except ImportError:
                # Fallback to legacy logic if exchange_capabilities not available
                logger.warning("exchange_capabilities module not available, using legacy logic")

        # Legacy logic (less accurate, doesn't consider exchange differences)
        market_type = self.detect_market_type(symbol)

        # Crypto (Coinbase spot) typically doesn't support shorting
        # Stocks and Futures do
        # Options use PUTs instead
        if market_type == MarketType.CRYPTO:
            # Could check if it's a futures symbol (e.g., BTC-PERP)
            return 'PERP' in symbol or 'FUTURE' in symbol
        elif market_type == MarketType.OPTIONS:
            return False  # Use PUTs instead
        else:
            return True  # Stocks and Futures support shorts

# Global instance
market_adapter = MarketAdapter()
