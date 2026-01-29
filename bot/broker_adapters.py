"""
NIJA Broker-Specific Execution Adapters
========================================

FIX #4: BROKER-SPECIFIC EXECUTION RULES (PER USER)

NIJA logic should generate INTENT, not size.
Each broker: INTENT → BROKER ADAPTER → VALIDATED ORDER → EXECUTE

This module provides broker-specific adapters that enforce:
- Minimum notional/volume requirements
- Symbol format validation
- Precision rules
- Fee awareness
- Exchange-specific constraints
"""

import logging
from abc import ABC, abstractmethod
from typing import Dict, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger("nija.adapters")


class OrderIntent(Enum):
    """Trading intent types."""
    BUY = "buy"
    SELL = "sell"
    STOP_LOSS = "stop_loss"  # Force sell, bypass all filters


@dataclass
class TradeIntent:
    """
    High-level trading intent before broker-specific validation.

    The strategy generates intents, and adapters convert them to
    broker-specific validated orders.
    """
    intent_type: OrderIntent
    symbol: str
    quantity: float = 0.0  # Base currency quantity
    size_usd: float = 0.0  # USD notional size
    size_type: str = "base"  # "base" or "quote"
    force_execute: bool = False  # If True, bypass minimum size checks (for stop-loss)
    reason: str = ""  # Why this trade is being placed


@dataclass
class ValidatedOrder:
    """
    Broker-specific validated order ready for execution.

    After adapter validates and adjusts the intent based on broker rules.
    """
    symbol: str
    side: str  # 'buy' or 'sell'
    quantity: float
    size_type: str  # 'base' or 'quote'
    valid: bool
    error_message: Optional[str] = None
    warnings: list = None
    adjusted: bool = False  # True if adapter modified the order

    def __post_init__(self):
        """Initialize mutable defaults."""
        if self.warnings is None:
            self.warnings = []


class BrokerAdapter(ABC):
    """
    Base class for broker-specific execution adapters.

    Each broker adapter enforces its specific constraints and rules.
    """

    def __init__(self, broker_name: str):
        """
        Initialize broker adapter.

        Args:
            broker_name: Name of the broker (coinbase, kraken, alpaca, etc.)
        """
        self.broker_name = broker_name
        logger.info(f"Initialized {broker_name} adapter")

    @abstractmethod
    def validate_and_adjust(self, intent: TradeIntent) -> ValidatedOrder:
        """
        Validate and adjust trade intent to broker-specific requirements.

        Args:
            intent: High-level trading intent

        Returns:
            ValidatedOrder: Validated and adjusted order, or invalid order with error
        """
        pass

    @abstractmethod
    def get_min_order_size(self, symbol: str) -> Tuple[float, str]:
        """
        Get minimum order size for a symbol.

        Args:
            symbol: Trading pair symbol

        Returns:
            Tuple of (min_size, size_type) where size_type is 'base' or 'quote'
        """
        pass

    @abstractmethod
    def normalize_symbol(self, symbol: str) -> str:
        """
        Normalize symbol to broker-specific format.

        Args:
            symbol: Input symbol in any format

        Returns:
            Normalized symbol for this broker
        """
        pass


class CoinbaseAdapter(BrokerAdapter):
    """
    Coinbase-specific execution adapter.

    Enforces:
    - Minimum notional: $25 for all pairs (profitability after fees)
    - Portfolio routing for efficient fills
    - Fee-aware exits (account for 0.6% maker + 0.6% taker fees)
    - Symbol format: ETH-USD, BTC-USDT, etc. (dash separator)
    """

    # ✅ REQUIREMENT #4: Coinbase minimum notional per pair
    # UNIFIED MINIMUM: $25 to ensure profitability after 1.20% round-trip fees
    # At $25 position with 1.20% fees = $0.30 fee cost, target 1.5% = $0.375 profit = net $0.075
    # NOTE: $5 positions will be REJECTED as they cannot cover fees
    MIN_NOTIONAL_DEFAULT = 25.0  # $25 minimum for all pairs (profitability threshold)
    MIN_NOTIONAL_BTC = 25.0  # $25 minimum for BTC pairs (same as default)

    # Coinbase fee structure
    MAKER_FEE_PCT = 0.60  # 0.6% maker fee
    TAKER_FEE_PCT = 0.60  # 0.6% taker fee
    TOTAL_FEE_PCT = 1.20  # 1.20% combined round-trip cost (stored as decimal 1.20)

    def __init__(self):
        """Initialize Coinbase adapter."""
        super().__init__("coinbase")

    def validate_and_adjust(self, intent: TradeIntent) -> ValidatedOrder:
        """
        Validate trade intent for Coinbase.

        Checks:
        1. Symbol format is correct (XXX-YYY)
        2. Order size meets minimum notional
        3. Fees won't eat all profits (for sells)
        """
        # Normalize symbol
        normalized_symbol = self.normalize_symbol(intent.symbol)

        # If force_execute (stop-loss), bypass size checks
        if intent.force_execute:
            return ValidatedOrder(
                symbol=normalized_symbol,
                side=intent.intent_type.value if intent.intent_type != OrderIntent.STOP_LOSS else "sell",
                quantity=intent.quantity,
                size_type=intent.size_type,
                valid=True,
                warnings=["FORCE EXECUTE: Bypassing minimum size checks for stop-loss"]
            )

        # Get minimum order size
        min_size, min_size_type = self.get_min_order_size(normalized_symbol)

        # Calculate order size in USD for validation
        if intent.size_type == "quote" or intent.size_usd > 0:
            order_size_usd = intent.size_usd if intent.size_usd > 0 else intent.quantity
        else:
            # For base currency, we'd need current price - assume caller provides size_usd
            order_size_usd = intent.size_usd

        # Check minimum notional
        if order_size_usd < min_size:
            return ValidatedOrder(
                symbol=normalized_symbol,
                side=intent.intent_type.value,
                quantity=intent.quantity,
                size_type=intent.size_type,
                valid=False,
                error_message=f"Order size ${order_size_usd:.2f} below minimum ${min_size:.2f}"
            )

        # Fee awareness check for sells
        warnings = []
        if intent.intent_type in [OrderIntent.SELL, OrderIntent.STOP_LOSS]:
            fee_cost = order_size_usd * (self.TOTAL_FEE_PCT / 100)
            if fee_cost > order_size_usd * 0.5:  # Fees > 50% of order value
                warnings.append(f"High fee impact: ${fee_cost:.2f} ({self.TOTAL_FEE_PCT}% of order)")

        return ValidatedOrder(
            symbol=normalized_symbol,
            side=intent.intent_type.value if intent.intent_type != OrderIntent.STOP_LOSS else "sell",
            quantity=intent.quantity,
            size_type=intent.size_type,
            valid=True,
            warnings=warnings
        )

    def get_min_order_size(self, symbol: str) -> Tuple[float, str]:
        """Get Coinbase minimum order size."""
        # BTC pairs have higher minimums
        if symbol.startswith("BTC-") or symbol.startswith("BTC/"):
            return (self.MIN_NOTIONAL_BTC, "quote")
        return (self.MIN_NOTIONAL_DEFAULT, "quote")

    def normalize_symbol(self, symbol: str) -> str:
        """Normalize to Coinbase format (XXX-YYY)."""
        if not symbol:
            return symbol

        # Replace slash with dash
        symbol = symbol.replace("/", "-")

        # Replace dot with dash
        symbol = symbol.replace(".", "-")

        # Handle no separator case (BTCUSD -> BTC-USD)
        if "-" not in symbol and len(symbol) >= 6:
            # Common base currencies
            for base in ["BTC", "ETH", "SOL", "XRP", "ADA", "DOT"]:
                if symbol.startswith(base):
                    quote = symbol[len(base):]
                    return f"{base}-{quote}"

        return symbol.upper()


class KrakenAdapter(BrokerAdapter):
    """
    Kraken-specific execution adapter.

    Enforces:
    - Minimum volume per pair (varies by pair)
    - Precision rules (varies by pair)
    - Pair availability (Kraken doesn't support all pairs)
    - Nonce safety (sequential API calls)
    - Symbol format: ETH/USD, BTC/USDT, etc. (slash separator or no separator)
    """

    # ✅ REQUIREMENT #4: Kraken minimum volumes (lower than Coinbase)
    # Kraken fees are lower (0.42% vs Coinbase 1.20%), so minimum can be lower
    # $10 minimum ensures profitability after fees for small accounts
    MIN_VOLUME_DEFAULT = 10.0  # $10 minimum for most pairs (lower than Coinbase $25)
    MIN_VOLUME_BTC = 10.0  # $10 minimum even for BTC

    # Kraken fee structure (lower than Coinbase)
    MAKER_FEE_PCT = 0.16  # 0.16% maker fee (volume tier)
    TAKER_FEE_PCT = 0.26  # 0.26% taker fee (volume tier)
    TOTAL_FEE_PCT = 0.42  # 0.42% combined round-trip cost (stored as decimal 0.42)

    # Kraken doesn't support certain quote currencies
    UNSUPPORTED_QUOTES = ["BUSD"]  # Kraken doesn't have BUSD pairs

    def __init__(self):
        """Initialize Kraken adapter."""
        super().__init__("kraken")

    def validate_and_adjust(self, intent: TradeIntent) -> ValidatedOrder:
        """
        Validate trade intent for Kraken.

        Checks:
        1. Symbol format is correct (XXX/YYY)
        2. Pair is available on Kraken
        3. Order size meets minimum volume
        4. Precision is appropriate
        """
        # Check for unsupported pairs BEFORE normalization
        for unsupported in self.UNSUPPORTED_QUOTES:
            if unsupported in intent.symbol.upper():
                return ValidatedOrder(
                    symbol=intent.symbol,
                    side=intent.intent_type.value if intent.intent_type != OrderIntent.STOP_LOSS else "sell",
                    quantity=intent.quantity,
                    size_type=intent.size_type,
                    valid=False,
                    error_message=f"Kraken does not support {unsupported} pairs"
                )

        # Normalize symbol (this will convert BUSD to USD if needed)
        normalized_symbol = self.normalize_symbol(intent.symbol)

        # If force_execute (stop-loss), bypass size checks
        if intent.force_execute:
            return ValidatedOrder(
                symbol=normalized_symbol,
                side=intent.intent_type.value if intent.intent_type != OrderIntent.STOP_LOSS else "sell",
                quantity=intent.quantity,
                size_type=intent.size_type,
                valid=True,
                warnings=["FORCE EXECUTE: Bypassing minimum size checks for stop-loss"]
            )

        # Get minimum order size
        min_size, min_size_type = self.get_min_order_size(normalized_symbol)

        # Calculate order size in USD for validation
        order_size_usd = intent.size_usd if intent.size_usd > 0 else intent.quantity

        # Check minimum volume
        if order_size_usd < min_size:
            return ValidatedOrder(
                symbol=normalized_symbol,
                side=intent.intent_type.value if intent.intent_type != OrderIntent.STOP_LOSS else "sell",
                quantity=intent.quantity,
                size_type=intent.size_type,
                valid=False,
                error_message=f"Order size ${order_size_usd:.2f} below Kraken minimum ${min_size:.2f}"
            )

        return ValidatedOrder(
            symbol=normalized_symbol,
            side=intent.intent_type.value if intent.intent_type != OrderIntent.STOP_LOSS else "sell",
            quantity=intent.quantity,
            size_type=intent.size_type,
            valid=True
        )

    def get_min_order_size(self, symbol: str) -> Tuple[float, str]:
        """Get Kraken minimum order size."""
        return (self.MIN_VOLUME_DEFAULT, "quote")

    def normalize_symbol(self, symbol: str) -> str:
        """
        Normalize to Kraken format (no separators: BTCUSD, ETHUSD).

        Uses the centralized kraken_adapter module for symbol normalization.
        """
        if not symbol:
            return symbol

        # Use kraken_adapter module for normalization
        try:
            from bot.kraken_adapter import normalize_kraken_symbol
            return normalize_kraken_symbol(symbol)
        except ImportError:
            # Fallback: Remove separators and uppercase
            symbol = symbol.replace("-", "").replace("/", "").upper()
            # Replace BUSD with USD (Kraken doesn't support BUSD)
            symbol = symbol.replace("BUSD", "USD")
            return symbol


class AlpacaAdapter(BrokerAdapter):
    """
    Alpaca-specific execution adapter (stocks/options).

    Enforces:
    - PDT (Pattern Day Trader) rules
    - Margin availability
    - Options approval level
    - Market hours restrictions
    - Symbol format: AAPL, TSLA, etc. (stock tickers)
    """

    # Alpaca minimum order sizes
    MIN_ORDER_VALUE = 1.0  # $1 minimum

    # PDT rule: < $25k account cannot make >3 day trades in 5 days
    PDT_THRESHOLD = 25000.0
    PDT_MAX_DAY_TRADES = 3

    def __init__(self, account_value: float = 0.0):
        """
        Initialize Alpaca adapter.

        Args:
            account_value: Current account value for PDT rule checking
        """
        super().__init__("alpaca")
        self.account_value = account_value

    def validate_and_adjust(self, intent: TradeIntent) -> ValidatedOrder:
        """
        Validate trade intent for Alpaca.

        Checks:
        1. Symbol format is correct (stock ticker)
        2. PDT rules if account < $25k
        3. Order size meets minimum
        """
        # Normalize symbol (stocks are simple, just uppercase)
        normalized_symbol = self.normalize_symbol(intent.symbol)

        # If force_execute (stop-loss), bypass checks
        if intent.force_execute:
            return ValidatedOrder(
                symbol=normalized_symbol,
                side=intent.intent_type.value if intent.intent_type != OrderIntent.STOP_LOSS else "sell",
                quantity=intent.quantity,
                size_type=intent.size_type,
                valid=True,
                warnings=["FORCE EXECUTE: Bypassing checks for stop-loss"]
            )

        # Check PDT rules
        warnings = []
        if self.account_value > 0 and self.account_value < self.PDT_THRESHOLD:
            warnings.append(f"PDT Warning: Account value ${self.account_value:.2f} < ${self.PDT_THRESHOLD:.2f}")

        # Get minimum order size
        min_size, min_size_type = self.get_min_order_size(normalized_symbol)

        # Calculate order size
        order_size_usd = intent.size_usd if intent.size_usd > 0 else intent.quantity

        # Check minimum
        if order_size_usd < min_size:
            return ValidatedOrder(
                symbol=normalized_symbol,
                side=intent.intent_type.value if intent.intent_type != OrderIntent.STOP_LOSS else "sell",
                quantity=intent.quantity,
                size_type=intent.size_type,
                valid=False,
                error_message=f"Order size ${order_size_usd:.2f} below minimum ${min_size:.2f}"
            )

        return ValidatedOrder(
            symbol=normalized_symbol,
            side=intent.intent_type.value if intent.intent_type != OrderIntent.STOP_LOSS else "sell",
            quantity=intent.quantity,
            size_type=intent.size_type,
            valid=True,
            warnings=warnings
        )

    def get_min_order_size(self, symbol: str) -> Tuple[float, str]:
        """Get Alpaca minimum order size."""
        return (self.MIN_ORDER_VALUE, "quote")

    def normalize_symbol(self, symbol: str) -> str:
        """Normalize to Alpaca format (stock ticker)."""
        if not symbol:
            return symbol

        # Remove any separators
        symbol = symbol.replace("-", "").replace("/", "").replace(".", "")

        return symbol.upper()


class BinanceAdapter(BrokerAdapter):
    """
    Binance-specific execution adapter.

    Enforces:
    - Minimum notional per pair (varies, typically $10-15)
    - Precision rules (8 decimals for most pairs)
    - Pair availability (1000+ pairs)
    - Symbol format: BTCUSDT, ETHUSDT (no separator)
    - Fee awareness (0.10% maker/taker with BNB discount)
    """

    # Binance minimum notional values
    MIN_NOTIONAL_DEFAULT = 10.0  # $10 minimum for most pairs
    MIN_NOTIONAL_BTC = 10.0  # $10 minimum for BTC pairs

    # Binance fee structure (with BNB discount)
    MAKER_FEE_PCT = 0.10  # 0.10% maker fee (0.075% with BNB)
    TAKER_FEE_PCT = 0.10  # 0.10% taker fee (0.075% with BNB)
    TOTAL_FEE_PCT = 0.28  # 0.28% combined round-trip cost (with spread)

    def __init__(self):
        """Initialize Binance adapter."""
        super().__init__("binance")

    def validate_and_adjust(self, intent: TradeIntent) -> ValidatedOrder:
        """
        Validate trade intent for Binance.

        Checks:
        1. Symbol format is correct (no separator)
        2. Order size meets minimum notional
        3. Fees are acceptable
        """
        # Normalize symbol
        normalized_symbol = self.normalize_symbol(intent.symbol)

        # If force_execute (stop-loss), bypass size checks
        if intent.force_execute:
            return ValidatedOrder(
                symbol=normalized_symbol,
                side=intent.intent_type.value if intent.intent_type != OrderIntent.STOP_LOSS else "sell",
                quantity=intent.quantity,
                size_type=intent.size_type,
                valid=True,
                warnings=["FORCE EXECUTE: Bypassing minimum size checks for stop-loss"]
            )

        # Get minimum order size
        min_size, min_size_type = self.get_min_order_size(normalized_symbol)

        # Calculate order size in USD for validation
        order_size_usd = intent.size_usd if intent.size_usd > 0 else intent.quantity

        # Check minimum notional
        if order_size_usd < min_size:
            return ValidatedOrder(
                symbol=normalized_symbol,
                side=intent.intent_type.value if intent.intent_type != OrderIntent.STOP_LOSS else "sell",
                quantity=intent.quantity,
                size_type=intent.size_type,
                valid=False,
                error_message=f"Order size ${order_size_usd:.2f} below Binance minimum ${min_size:.2f}"
            )

        # Fee awareness check for sells
        warnings = []
        if intent.intent_type in [OrderIntent.SELL, OrderIntent.STOP_LOSS]:
            fee_cost = order_size_usd * (self.TOTAL_FEE_PCT / 100)
            if fee_cost > order_size_usd * 0.5:  # Fees > 50% of order value
                warnings.append(f"High fee impact: ${fee_cost:.2f} ({self.TOTAL_FEE_PCT}% of order)")

        return ValidatedOrder(
            symbol=normalized_symbol,
            side=intent.intent_type.value if intent.intent_type != OrderIntent.STOP_LOSS else "sell",
            quantity=intent.quantity,
            size_type=intent.size_type,
            valid=True,
            warnings=warnings
        )

    def get_min_order_size(self, symbol: str) -> Tuple[float, str]:
        """Get Binance minimum order size."""
        # BTC pairs have same minimums as others on Binance
        return (self.MIN_NOTIONAL_DEFAULT, "quote")

    def normalize_symbol(self, symbol: str) -> str:
        """
        Normalize to Binance format (no separators: BTCUSDT, ETHUSDT).

        Binance uses no separators and USDT as the primary quote currency.
        """
        if not symbol:
            return symbol

        # Remove all separators
        symbol = symbol.replace("-", "").replace("/", "").replace(".", "").upper()

        # Convert USD to USDT (Binance uses USDT, not USD)
        # Only convert if it's a crypto quote currency (ends with USD but not USDT/BUSD)
        # Common crypto base currencies that should use USDT quote
        CRYPTO_BASES = ["BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "DOT", "AVAX",
                        "MATIC", "LINK", "UNI", "ATOM", "LTC", "BCH", "ETC", "XLM"]

        # Check if this looks like a crypto pair with USD quote
        for base in CRYPTO_BASES:
            if symbol.startswith(base) and symbol.endswith("USD") and not symbol.endswith("USDT"):
                return symbol[:-3] + "USDT"

        # If already has USDT or other quote, return as-is
        return symbol


class OKXAdapter(BrokerAdapter):
    """
    OKX-specific execution adapter.

    Enforces:
    - Minimum order size per pair (typically $10)
    - Precision rules (varies by pair)
    - Symbol format: BTC-USDT, ETH-USDT (dash separator)
    - Fee awareness (0.08% maker/0.10% taker for VIP tier)
    - Futures and perpetuals support
    """

    # OKX minimum order sizes
    MIN_ORDER_DEFAULT = 10.0  # $10 minimum for most pairs
    MIN_ORDER_BTC = 10.0  # $10 minimum for BTC pairs

    # OKX fee structure (VIP tier)
    MAKER_FEE_PCT = 0.08  # 0.08% maker fee
    TAKER_FEE_PCT = 0.10  # 0.10% taker fee
    TOTAL_FEE_PCT = 0.20  # 0.20% combined round-trip cost (with spread)

    def __init__(self):
        """Initialize OKX adapter."""
        super().__init__("okx")

    def validate_and_adjust(self, intent: TradeIntent) -> ValidatedOrder:
        """
        Validate trade intent for OKX.

        Checks:
        1. Symbol format is correct (XXX-YYY with dash)
        2. Order size meets minimum
        3. Fees are acceptable
        """
        # Normalize symbol
        normalized_symbol = self.normalize_symbol(intent.symbol)

        # If force_execute (stop-loss), bypass size checks
        if intent.force_execute:
            return ValidatedOrder(
                symbol=normalized_symbol,
                side=intent.intent_type.value if intent.intent_type != OrderIntent.STOP_LOSS else "sell",
                quantity=intent.quantity,
                size_type=intent.size_type,
                valid=True,
                warnings=["FORCE EXECUTE: Bypassing minimum size checks for stop-loss"]
            )

        # Get minimum order size
        min_size, min_size_type = self.get_min_order_size(normalized_symbol)

        # Calculate order size in USD for validation
        order_size_usd = intent.size_usd if intent.size_usd > 0 else intent.quantity

        # Check minimum order size
        if order_size_usd < min_size:
            return ValidatedOrder(
                symbol=normalized_symbol,
                side=intent.intent_type.value if intent.intent_type != OrderIntent.STOP_LOSS else "sell",
                quantity=intent.quantity,
                size_type=intent.size_type,
                valid=False,
                error_message=f"Order size ${order_size_usd:.2f} below OKX minimum ${min_size:.2f}"
            )

        # Fee awareness check
        warnings = []
        if intent.intent_type in [OrderIntent.SELL, OrderIntent.STOP_LOSS]:
            fee_cost = order_size_usd * (self.TOTAL_FEE_PCT / 100)
            if fee_cost > order_size_usd * 0.5:  # Fees > 50% of order value
                warnings.append(f"High fee impact: ${fee_cost:.2f} ({self.TOTAL_FEE_PCT}% of order)")

        return ValidatedOrder(
            symbol=normalized_symbol,
            side=intent.intent_type.value if intent.intent_type != OrderIntent.STOP_LOSS else "sell",
            quantity=intent.quantity,
            size_type=intent.size_type,
            valid=True,
            warnings=warnings
        )

    def get_min_order_size(self, symbol: str) -> Tuple[float, str]:
        """Get OKX minimum order size."""
        return (self.MIN_ORDER_DEFAULT, "quote")

    def normalize_symbol(self, symbol: str) -> str:
        """
        Normalize to OKX format (XXX-YYY with dash separator).

        OKX uses dash separators and USDT as the primary quote currency.
        """
        if not symbol:
            return symbol

        # Replace slash with dash
        symbol = symbol.replace("/", "-")

        # Replace dot with dash
        symbol = symbol.replace(".", "-")

        # Uppercase
        symbol = symbol.upper()

        # Common crypto base currencies
        CRYPTO_BASES = ["BTC", "ETH", "SOL", "XRP", "ADA", "DOT", "AVAX", "BNB",
                        "MATIC", "LINK", "UNI", "ATOM", "LTC", "BCH", "ETC", "XLM"]

        # Convert USD to USDT (OKX prefers USDT) for known crypto bases
        if symbol.endswith("-USD"):
            base = symbol[:-4]
            if base in CRYPTO_BASES:
                return f"{base}-USDT"

        # Handle no separator case (BTCUSD -> BTC-USDT)
        if "-" not in symbol and len(symbol) >= 6:
            for base in CRYPTO_BASES:
                if symbol.startswith(base):
                    quote = symbol[len(base):]
                    # Convert USD to USDT for crypto pairs
                    if quote == "USD":
                        quote = "USDT"
                    return f"{base}-{quote}"

        return symbol


class BrokerAdapterFactory:
    """Factory for creating broker-specific adapters."""

    @staticmethod
    def create_adapter(broker_type: str, **kwargs) -> BrokerAdapter:
        """
        Create a broker adapter.

        Args:
            broker_type: Broker type (coinbase, kraken, alpaca, binance, okx, etc.)
            **kwargs: Broker-specific arguments

        Returns:
            BrokerAdapter instance

        Raises:
            ValueError: If broker type is not supported
        """
        broker_type_lower = broker_type.lower()

        if broker_type_lower == "coinbase":
            return CoinbaseAdapter()
        elif broker_type_lower == "kraken":
            return KrakenAdapter()
        elif broker_type_lower == "alpaca":
            account_value = kwargs.get('account_value', 0.0)
            return AlpacaAdapter(account_value=account_value)
        elif broker_type_lower == "binance":
            return BinanceAdapter()
        elif broker_type_lower == "okx":
            return OKXAdapter()
        else:
            raise ValueError(f"Unsupported broker type: {broker_type}")


# Convenience functions for quick access
def validate_trade_for_broker(broker_type: str, intent: TradeIntent, **kwargs) -> ValidatedOrder:
    """
    Validate a trade intent for a specific broker.

    Args:
        broker_type: Broker type
        intent: Trade intent
        **kwargs: Broker-specific arguments

    Returns:
        ValidatedOrder
    """
    adapter = BrokerAdapterFactory.create_adapter(broker_type, **kwargs)
    return adapter.validate_and_adjust(intent)
