"""
Exchange Capability Matrix

Defines what trading capabilities each exchange/broker supports.
This provides a clean separation between:
- Strategy Layer: Generates trading signals (LONG, SHORT, etc.)
- Execution Layer: Executes based on what exchange actually supports

Key Capabilities:
- Spot trading (buy/sell assets you own)
- Futures trading (perpetual and dated contracts)
- Margin trading (borrow to increase position size)
- Short selling on spot markets (borrow and sell)
- Short selling on futures (native to contract)

Exchange-Specific Rules:
- Kraken Spot: NO shorting (BTC-USD, ETH-USD, etc.)
- Kraken Futures: YES shorting (BTC-PERP, ETH-PERP, etc.)
- Coinbase: NO shorting (spot only, high fees)
- Binance Spot: NO shorting
- Binance Futures: YES shorting
- Alpaca: YES shorting (stocks via locate/borrow)
"""

from dataclasses import dataclass
from enum import Enum
from typing import Dict, Optional, Tuple
import logging

logger = logging.getLogger("nija.capabilities")


class MarketMode(Enum):
    """Market type for capability lookup"""
    SPOT = "spot"
    FUTURES = "futures"
    PERPETUAL = "perpetual"
    MARGIN = "margin"
    OPTIONS = "options"


@dataclass
class ExchangeCapabilities:
    """Capabilities for a specific exchange/market combination"""
    
    broker_name: str
    market_mode: MarketMode
    
    # Trading capabilities
    supports_long: bool = True  # Almost all exchanges support buying
    supports_short: bool = False  # Many don't support shorting
    supports_margin: bool = False  # Borrow to increase position
    supports_leverage: bool = False  # Built-in leverage
    
    # Constraints
    max_leverage: float = 1.0  # Maximum leverage allowed
    requires_margin_account: bool = False  # Need special account type
    
    # Features
    has_stop_loss: bool = True  # Exchange-native stop loss
    has_take_profit: bool = True  # Exchange-native take profit
    has_trailing_stop: bool = False  # Exchange-native trailing
    
    # Fee structure (for fee-aware profit targets)
    # Round-trip cost = (taker_fee * 2) + spread_cost or (maker_fee * 2) + spread_cost
    taker_fee: float = 0.001  # Default 0.1% taker fee
    maker_fee: float = 0.001  # Default 0.1% maker fee
    spread_cost: float = 0.001  # Default 0.1% spread
    
    def can_short(self) -> bool:
        """Check if this exchange/market can execute SHORT positions"""
        return self.supports_short
    
    def can_long(self) -> bool:
        """Check if this exchange/market can execute LONG positions"""
        return self.supports_long
    
    def get_round_trip_fee(self, use_limit_order: bool = True) -> float:
        """
        Calculate round-trip trading cost (entry + exit).
        
        Args:
            use_limit_order: True for maker fees, False for taker fees
            
        Returns:
            Total round-trip cost as decimal (e.g., 0.014 = 1.4%)
        """
        fee = self.maker_fee if use_limit_order else self.taker_fee
        return (fee * 2) + self.spread_cost
    
    def get_min_profit_target(self, use_limit_order: bool = True, multiplier: float = 2.5) -> float:
        """
        Calculate minimum profit target to overcome fees.
        
        Formula: min_profit_target = round_trip_fee * multiplier
        Default multiplier = 2.5 (ensures profit after fees + buffer for slippage)
        
        Args:
            use_limit_order: True for maker fees, False for taker fees
            multiplier: Multiplier for fee coverage (default 2.5)
            
        Returns:
            Minimum profit target as decimal (e.g., 0.035 = 3.5%)
        """
        round_trip = self.get_round_trip_fee(use_limit_order)
        return round_trip * multiplier


class ExchangeCapabilityMatrix:
    """
    Central registry of what each exchange/broker actually supports.
    
    This matrix is the source of truth for execution decisions.
    Strategy can generate any signal, but execution checks this matrix.
    """
    
    def __init__(self):
        """Initialize capability matrix with all known exchanges"""
        self._capabilities: Dict[str, Dict[MarketMode, ExchangeCapabilities]] = {
            # KRAKEN
            'kraken': {
                MarketMode.SPOT: ExchangeCapabilities(
                    broker_name='kraken',
                    market_mode=MarketMode.SPOT,
                    supports_long=True,
                    supports_short=False,  # ❌ KRAKEN SPOT DOES NOT SUPPORT SHORTING
                    supports_margin=False,
                    supports_leverage=False,
                    max_leverage=1.0,
                    has_stop_loss=True,
                    has_take_profit=True,
                    has_trailing_stop=False,
                    taker_fee=0.0026,  # 0.26% taker fee
                    maker_fee=0.0016,  # 0.16% maker fee
                    spread_cost=0.001   # ~0.1% spread (0.42% round-trip)
                ),
                MarketMode.FUTURES: ExchangeCapabilities(
                    broker_name='kraken',
                    market_mode=MarketMode.FUTURES,
                    supports_long=True,
                    supports_short=True,  # ✅ KRAKEN FUTURES SUPPORTS SHORTING
                    supports_margin=False,
                    supports_leverage=True,
                    max_leverage=50.0,  # Kraken Futures allows up to 50x
                    has_stop_loss=True,
                    has_take_profit=True,
                    has_trailing_stop=False,
                    taker_fee=0.0005,  # 0.05% taker fee (lower on futures)
                    maker_fee=0.0002,  # 0.02% maker fee (lower on futures)
                    spread_cost=0.0005  # ~0.05% spread (0.15% round-trip)
                ),
                MarketMode.PERPETUAL: ExchangeCapabilities(
                    broker_name='kraken',
                    market_mode=MarketMode.PERPETUAL,
                    supports_long=True,
                    supports_short=True,  # ✅ PERPETUALS SUPPORT SHORTING
                    supports_margin=False,
                    supports_leverage=True,
                    max_leverage=50.0,
                    has_stop_loss=True,
                    has_take_profit=True,
                    has_trailing_stop=False,
                    taker_fee=0.0005,  # 0.05% taker fee
                    maker_fee=0.0002,  # 0.02% maker fee
                    spread_cost=0.0005  # ~0.05% spread (0.15% round-trip)
                ),
            },
            
            # COINBASE (Spot only, no shorting)
            'coinbase': {
                MarketMode.SPOT: ExchangeCapabilities(
                    broker_name='coinbase',
                    market_mode=MarketMode.SPOT,
                    supports_long=True,
                    supports_short=False,  # ❌ COINBASE DOES NOT SUPPORT SHORTING
                    supports_margin=False,
                    supports_leverage=False,
                    max_leverage=1.0,
                    has_stop_loss=True,
                    has_take_profit=True,
                    has_trailing_stop=False,
                    taker_fee=0.006,  # 0.6% taker fee (HIGH)
                    maker_fee=0.004,  # 0.4% maker fee (HIGH)
                    spread_cost=0.002  # ~0.2% spread (1.4% round-trip with taker)
                ),
            },
            
            # BINANCE (Spot no shorting, Futures yes)
            'binance': {
                MarketMode.SPOT: ExchangeCapabilities(
                    broker_name='binance',
                    market_mode=MarketMode.SPOT,
                    supports_long=True,
                    supports_short=False,  # ❌ BINANCE SPOT NO SHORTING
                    supports_margin=False,
                    supports_leverage=False,
                    max_leverage=1.0,
                    has_stop_loss=True,
                    has_take_profit=True,
                    has_trailing_stop=True,
                    taker_fee=0.001,  # 0.1% taker fee
                    maker_fee=0.001,  # 0.1% maker fee
                    spread_cost=0.0008  # ~0.08% spread (0.28% round-trip)
                ),
                MarketMode.MARGIN: ExchangeCapabilities(
                    broker_name='binance',
                    market_mode=MarketMode.MARGIN,
                    supports_long=True,
                    supports_short=True,  # ✅ BINANCE MARGIN SUPPORTS SHORTING
                    supports_margin=True,
                    supports_leverage=True,
                    max_leverage=10.0,
                    requires_margin_account=True,
                    has_stop_loss=True,
                    has_take_profit=True,
                    has_trailing_stop=True,
                    taker_fee=0.001,  # 0.1% taker fee
                    maker_fee=0.001,  # 0.1% maker fee
                    spread_cost=0.0008  # ~0.08% spread
                ),
                MarketMode.FUTURES: ExchangeCapabilities(
                    broker_name='binance',
                    market_mode=MarketMode.FUTURES,
                    supports_long=True,
                    supports_short=True,  # ✅ BINANCE FUTURES SUPPORTS SHORTING
                    supports_margin=False,
                    supports_leverage=True,
                    max_leverage=125.0,
                    has_stop_loss=True,
                    has_take_profit=True,
                    has_trailing_stop=True,
                    taker_fee=0.0004,  # 0.04% taker fee (lower on futures)
                    maker_fee=0.0002,  # 0.02% maker fee (lower on futures)
                    spread_cost=0.0004  # ~0.04% spread
                ),
                MarketMode.PERPETUAL: ExchangeCapabilities(
                    broker_name='binance',
                    market_mode=MarketMode.PERPETUAL,
                    supports_long=True,
                    supports_short=True,  # ✅ PERPETUALS SUPPORT SHORTING
                    supports_margin=False,
                    supports_leverage=True,
                    max_leverage=125.0,
                    has_stop_loss=True,
                    has_take_profit=True,
                    has_trailing_stop=True,
                    taker_fee=0.0004,  # 0.04% taker fee
                    maker_fee=0.0002,  # 0.02% maker fee
                    spread_cost=0.0004  # ~0.04% spread
                ),
            },
            
            # OKX (Similar to Binance)
            'okx': {
                MarketMode.SPOT: ExchangeCapabilities(
                    broker_name='okx',
                    market_mode=MarketMode.SPOT,
                    supports_long=True,
                    supports_short=False,  # ❌ OKX SPOT NO SHORTING
                    supports_margin=False,
                    supports_leverage=False,
                    max_leverage=1.0,
                    has_stop_loss=True,
                    has_take_profit=True,
                    has_trailing_stop=True,
                    taker_fee=0.0008,  # 0.08% taker fee
                    maker_fee=0.0006,  # 0.06% maker fee
                    spread_cost=0.0006  # ~0.06% spread (0.20% round-trip)
                ),
                MarketMode.MARGIN: ExchangeCapabilities(
                    broker_name='okx',
                    market_mode=MarketMode.MARGIN,
                    supports_long=True,
                    supports_short=True,  # ✅ OKX MARGIN SUPPORTS SHORTING
                    supports_margin=True,
                    supports_leverage=True,
                    max_leverage=10.0,
                    requires_margin_account=True,
                    has_stop_loss=True,
                    has_take_profit=True,
                    has_trailing_stop=True,
                    taker_fee=0.0008,  # 0.08% taker fee
                    maker_fee=0.0006,  # 0.06% maker fee
                    spread_cost=0.0006  # ~0.06% spread
                ),
                MarketMode.FUTURES: ExchangeCapabilities(
                    broker_name='okx',
                    market_mode=MarketMode.FUTURES,
                    supports_long=True,
                    supports_short=True,  # ✅ OKX FUTURES SUPPORTS SHORTING
                    supports_margin=False,
                    supports_leverage=True,
                    max_leverage=100.0,
                    has_stop_loss=True,
                    has_take_profit=True,
                    has_trailing_stop=True,
                    taker_fee=0.0005,  # 0.05% taker fee
                    maker_fee=0.0002,  # 0.02% maker fee
                    spread_cost=0.0004  # ~0.04% spread
                ),
                MarketMode.PERPETUAL: ExchangeCapabilities(
                    broker_name='okx',
                    market_mode=MarketMode.PERPETUAL,
                    supports_long=True,
                    supports_short=True,  # ✅ PERPETUALS SUPPORT SHORTING
                    supports_margin=False,
                    supports_leverage=True,
                    max_leverage=100.0,
                    has_stop_loss=True,
                    has_take_profit=True,
                    has_trailing_stop=True,
                    taker_fee=0.0005,  # 0.05% taker fee
                    maker_fee=0.0002,  # 0.02% maker fee
                    spread_cost=0.0004  # ~0.04% spread
                ),
            },
            
            # ALPACA (US Stocks - shorting via locate/borrow)
            'alpaca': {
                MarketMode.SPOT: ExchangeCapabilities(
                    broker_name='alpaca',
                    market_mode=MarketMode.SPOT,
                    supports_long=True,
                    supports_short=True,  # ✅ ALPACA SUPPORTS STOCK SHORTING
                    supports_margin=True,
                    supports_leverage=True,
                    max_leverage=4.0,  # Regulation T: 4x intraday, 2x overnight
                    requires_margin_account=True,
                    has_stop_loss=True,
                    has_take_profit=True,
                    has_trailing_stop=True,
                    taker_fee=0.0,  # 0% commission (commission-free)
                    maker_fee=0.0,  # 0% commission (commission-free)
                    spread_cost=0.0005  # ~0.05% spread (SEC fees + spread)
                ),
            },
        }
    
    def get_capabilities(self, broker: str, market_mode: MarketMode) -> Optional[ExchangeCapabilities]:
        """
        Get capabilities for a specific broker/market combination.
        
        Args:
            broker: Broker name (e.g., 'kraken', 'coinbase')
            market_mode: Market mode (SPOT, FUTURES, etc.)
            
        Returns:
            ExchangeCapabilities object or None if not found
        """
        broker_lower = broker.lower()
        
        if broker_lower not in self._capabilities:
            logger.warning(f"⚠️  Unknown broker: {broker} - using conservative defaults (no shorting)")
            logger.warning(f"   Add {broker} to exchange_capabilities.py for proper support")
            # Conservative default: no shorting allowed for unknown brokers
            # This is safer than allowing shorts on untested exchanges
            return ExchangeCapabilities(
                broker_name=broker_lower,
                market_mode=MarketMode.SPOT,
                supports_long=True,
                supports_short=False  # Safe default: no shorting on unknown exchanges
            )
        
        broker_caps = self._capabilities[broker_lower]
        
        if market_mode not in broker_caps:
            # Fallback to SPOT if specific mode not found
            logger.debug(f"{broker} does not support {market_mode.value} - using SPOT capabilities")
            return broker_caps.get(MarketMode.SPOT)
        
        return broker_caps[market_mode]
    
    def supports_shorting(self, broker: str, symbol: str) -> bool:
        """
        Check if a broker supports shorting for a given symbol.
        
        This is the main entry point for SHORT capability checking.
        
        Args:
            broker: Broker name (e.g., 'kraken', 'coinbase')
            symbol: Trading symbol (e.g., 'BTC-USD', 'BTC-PERP')
            
        Returns:
            True if shorting is supported, False otherwise
        """
        market_mode = self._detect_market_mode(symbol)
        caps = self.get_capabilities(broker, market_mode)
        
        if caps is None:
            logger.warning(f"No capabilities found for {broker}/{symbol} - blocking SHORT")
            return False
        
        can_short = caps.can_short()
        
        if not can_short:
            logger.debug(f"❌ SHORT blocked: {broker} {market_mode.value} does not support shorting (symbol: {symbol})")
        else:
            logger.debug(f"✅ SHORT allowed: {broker} {market_mode.value} supports shorting (symbol: {symbol})")
        
        return can_short
    
    def get_broker_fees(self, broker: str, symbol: str) -> Tuple[float, float, float]:
        """
        Get broker fee structure for a symbol.
        
        Args:
            broker: Broker name
            symbol: Trading symbol
            
        Returns:
            Tuple of (taker_fee, maker_fee, round_trip_fee_with_limit_orders)
        """
        market_mode = self._detect_market_mode(symbol)
        caps = self.get_capabilities(broker, market_mode)
        
        if caps is None:
            logger.warning(f"No fee data for {broker}/{symbol} - using conservative defaults")
            return (0.001, 0.001, 0.003)  # 0.1% fees + 0.1% spread
        
        return (caps.taker_fee, caps.maker_fee, caps.get_round_trip_fee(use_limit_order=True))
    
    def get_min_profit_target_for_broker(self, broker: str, symbol: str, 
                                         use_limit_order: bool = True, 
                                         multiplier: float = 2.5) -> float:
        """
        Get minimum profit target for a broker/symbol to overcome fees.
        
        Formula: min_profit_target = round_trip_fee * multiplier
        
        Args:
            broker: Broker name
            symbol: Trading symbol
            use_limit_order: True for maker fees, False for taker fees
            multiplier: Fee coverage multiplier (default 2.5)
            
        Returns:
            Minimum profit target as decimal (e.g., 0.035 = 3.5%)
        """
        market_mode = self._detect_market_mode(symbol)
        caps = self.get_capabilities(broker, market_mode)
        
        if caps is None:
            logger.warning(f"No capability data for {broker}/{symbol} - using default 2.5% target")
            return 0.025
        
        return caps.get_min_profit_target(use_limit_order, multiplier)
    
    def _detect_market_mode(self, symbol: str) -> MarketMode:
        """
        Detect market mode from symbol.
        
        Args:
            symbol: Trading symbol
            
        Returns:
            MarketMode enum value
        """
        symbol_upper = symbol.upper()
        
        # Perpetual futures (most common naming)
        if 'PERP' in symbol_upper or 'PERPETUAL' in symbol_upper:
            return MarketMode.PERPETUAL
        
        # Futures - check for "FUTURE" keyword or typical futures patterns
        if 'FUTURE' in symbol_upper:
            return MarketMode.FUTURES
        
        # Dated futures (month codes, expiry dates)
        # Common futures month codes: F, G, H, J, K, M, N, Q, U, V, X, Z
        # But need to be careful not to match regular symbols
        if any(char.isdigit() for char in symbol_upper[-6:]):
            # Has digits at end, might be dated futures
            return MarketMode.FUTURES
        
        # Margin indicators
        if 'MARGIN' in symbol_upper:
            return MarketMode.MARGIN
        
        # Options
        if 'CALL' in symbol_upper or 'PUT' in symbol_upper:
            return MarketMode.OPTIONS
        
        # Default to SPOT
        return MarketMode.SPOT
    
    def get_summary(self, broker: str) -> str:
        """Get human-readable summary of broker capabilities"""
        if broker.lower() not in self._capabilities:
            return f"Unknown broker: {broker}"
        
        broker_caps = self._capabilities[broker.lower()]
        lines = [f"\n{broker.upper()} Exchange Capabilities:"]
        lines.append("=" * 60)
        
        for mode, caps in broker_caps.items():
            short_status = "✅ YES" if caps.supports_short else "❌ NO"
            round_trip = caps.get_round_trip_fee(use_limit_order=True)
            min_target = caps.get_min_profit_target(use_limit_order=True)
            
            lines.append(f"\n{mode.value.upper()}:")
            lines.append(f"  Long Positions:  ✅ YES")
            lines.append(f"  Short Positions: {short_status}")
            lines.append(f"  Fees: Taker {caps.taker_fee*100:.2f}% | Maker {caps.maker_fee*100:.2f}%")
            lines.append(f"  Round-trip Cost: {round_trip*100:.2f}% (with limit orders)")
            lines.append(f"  Min Profit Target: {min_target*100:.2f}% (fee × 2.5)")
            if caps.supports_leverage:
                lines.append(f"  Max Leverage:    {caps.max_leverage}x")
            if caps.requires_margin_account:
                lines.append(f"  Requires:        Margin Account")
        
        return "\n".join(lines)


# Global instance
EXCHANGE_CAPABILITIES = ExchangeCapabilityMatrix()


# Convenience function
def can_short(broker: str, symbol: str) -> bool:
    """
    Quick check if broker/symbol supports shorting.
    
    Args:
        broker: Broker name
        symbol: Trading symbol
        
    Returns:
        True if shorting supported
    """
    return EXCHANGE_CAPABILITIES.supports_shorting(broker, symbol)


def get_broker_capabilities(broker: str, symbol: str) -> Optional[ExchangeCapabilities]:
    """
    Get full capabilities for a broker/symbol combination.
    
    Args:
        broker: Broker name
        symbol: Trading symbol
        
    Returns:
        ExchangeCapabilities object or None
    """
    market_mode = EXCHANGE_CAPABILITIES._detect_market_mode(symbol)
    return EXCHANGE_CAPABILITIES.get_capabilities(broker, market_mode)


def get_min_profit_target(broker: str, symbol: str, use_limit_order: bool = True) -> float:
    """
    Get minimum profit target for a broker/symbol to overcome fees.
    
    Formula: min_profit_target = broker_fee * 2.5
    
    Args:
        broker: Broker name
        symbol: Trading symbol
        use_limit_order: True for maker fees, False for taker fees
        
    Returns:
        Minimum profit target as decimal (e.g., 0.035 = 3.5%)
    """
    return EXCHANGE_CAPABILITIES.get_min_profit_target_for_broker(broker, symbol, use_limit_order)


if __name__ == "__main__":
    # Print capability summaries when run directly
    print("\n" + "=" * 70)
    print("EXCHANGE CAPABILITY MATRIX".center(70))
    print("=" * 70)
    
    for broker in ['kraken', 'coinbase', 'binance', 'okx', 'alpaca']:
        print(EXCHANGE_CAPABILITIES.get_summary(broker))
    
    # Test examples
    print("\n" + "=" * 70)
    print("SHORTING CAPABILITY TESTS".center(70))
    print("=" * 70)
    
    test_cases = [
        ('kraken', 'BTC-USD', False),  # Kraken spot - NO
        ('kraken', 'BTC-PERP', True),  # Kraken perpetual - YES
        ('coinbase', 'ETH-USD', False),  # Coinbase - NO
        ('binance', 'BTC-USDT', False),  # Binance spot - NO
        ('binance', 'BTCUSDT-PERP', True),  # Binance perpetual - YES
        ('alpaca', 'AAPL', True),  # Alpaca stocks - YES
    ]
    
    print("\nTest Results:")
    for broker, symbol, expected in test_cases:
        result = can_short(broker, symbol)
        status = "✅ PASS" if result == expected else "❌ FAIL"
        print(f"{status} | {broker:10} | {symbol:15} | Expected: {expected:5} | Got: {result:5}")
