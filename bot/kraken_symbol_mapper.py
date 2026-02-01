#!/usr/bin/env python3
"""
Kraken Symbol Mapper
Handles symbol translation between standard format (BTC-USD) and Kraken format (XXBTZUSD).

Features:
1. Auto-detection of Kraken pairs dynamically
2. Validation of pair availability before trading
3. Support for copy trading with only common pairs
4. Caching for performance

This module prevents "EQuery:Unknown asset pair" errors by validating symbols
before attempting to trade them on Kraken.
"""

import os
import json
import logging
from typing import Dict, List, Set, Optional, Tuple
from pathlib import Path

# Import stdout suppression utility for pykrakenapi
try:
    from bot.stdout_utils import suppress_pykrakenapi_prints
except ImportError:
    try:
        from stdout_utils import suppress_pykrakenapi_prints
    except ImportError:
        # Fallback: Define locally if import fails
        import sys
        import io
        from contextlib import contextmanager

        @contextmanager
        def suppress_pykrakenapi_prints():
            original_stdout = sys.stdout
            try:
                sys.stdout = io.StringIO()
                yield
            finally:
                sys.stdout = original_stdout

logger = logging.getLogger('nija.kraken_symbol_mapper')

# Path to the symbol mapping file
CONFIG_DIR = Path(__file__).parent.parent / "config" / "brokers"
SYMBOL_MAP_FILE = CONFIG_DIR / "kraken_pairs.json"


class KrakenSymbolMapper:
    """
    Manages symbol translation and validation for Kraken trading pairs.

    This class:
    - Loads static symbol mappings from config file
    - Dynamically fetches available pairs from Kraken API
    - Validates symbols before trading
    - Provides fast lookup with caching
    """

    def __init__(self):
        """Initialize the symbol mapper."""
        self._static_map: Dict[str, str] = {}
        self._dynamic_map: Dict[str, str] = {}
        self._available_pairs: Set[str] = set()
        self._reverse_map: Dict[str, str] = {}
        self._initialized = False

        # Load static mappings
        self._load_static_mappings()

    def _load_static_mappings(self):
        """Load static symbol mappings from JSON file."""
        try:
            if SYMBOL_MAP_FILE.exists():
                with open(SYMBOL_MAP_FILE, 'r') as f:
                    self._static_map = json.load(f)
                    logger.info(f"📋 Loaded {len(self._static_map)} static Kraken symbol mappings")

                    # Create reverse mapping (Kraken -> Standard)
                    self._reverse_map = {v: k for k, v in self._static_map.items()}
            else:
                logger.warning(f"⚠️  Static symbol map not found: {SYMBOL_MAP_FILE}")
                logger.warning("   Using dynamic detection only")
        except Exception as e:
            logger.error(f"❌ Failed to load static symbol mappings: {e}")

    def initialize_from_api(self, kraken_api=None):
        """
        Initialize dynamic symbol mappings from Kraken API.

        Args:
            kraken_api: Optional KrakenAPI instance for fetching tradable pairs
        """
        if self._initialized:
            logger.debug("Symbol mapper already initialized")
            return

        try:
            if kraken_api is None:
                # We don't have a direct API accessor function
                # The initialization should be done by passing the API instance
                logger.warning("⚠️  No Kraken API provided for dynamic symbol detection")
                logger.warning("   Using static mappings only")
                self._initialized = True
                return

            if kraken_api:
                logger.info("🔍 Fetching available Kraken trading pairs...")

                # Get tradable asset pairs from Kraken
                # Suppress pykrakenapi's print() statements
                with suppress_pykrakenapi_prints():
                    asset_pairs = kraken_api.get_tradable_asset_pairs()

                # Build dynamic mapping
                for pair_name, pair_info in asset_pairs.iterrows():
                    wsname = pair_info.get('wsname', '')

                    # Only include USD and USDT pairs
                    if wsname and ('USD' in wsname or 'USDT' in wsname):
                        # Convert to standard format: BTC/USD -> BTC-USD
                        standard_symbol = wsname.replace('/', '-')

                        # Get Kraken internal format (from index)
                        kraken_symbol = pair_name

                        # Add to dynamic map
                        self._dynamic_map[standard_symbol] = kraken_symbol
                        self._available_pairs.add(standard_symbol)

                        # Update reverse map
                        self._reverse_map[kraken_symbol] = standard_symbol

                logger.info(f"✅ Detected {len(self._dynamic_map)} tradable Kraken pairs")

                # Save newly discovered pairs to static map file
                self._update_static_mappings()

            self._initialized = True

        except Exception as e:
            logger.error(f"❌ Failed to initialize dynamic symbol mappings: {e}")
            logger.error("   Falling back to static mappings only")
            self._initialized = True

    def _update_static_mappings(self):
        """Update static mappings file with newly discovered pairs."""
        try:
            # Merge static and dynamic maps
            merged_map = {**self._static_map, **self._dynamic_map}

            # Only update if we have new pairs
            if len(merged_map) > len(self._static_map):
                CONFIG_DIR.mkdir(parents=True, exist_ok=True)

                with open(SYMBOL_MAP_FILE, 'w') as f:
                    json.dump(merged_map, f, indent=2, sort_keys=True)

                new_pairs = len(merged_map) - len(self._static_map)
                logger.info(f"💾 Updated symbol map with {new_pairs} new pairs")

                # Update internal static map
                self._static_map = merged_map
        except Exception as e:
            logger.warning(f"⚠️  Could not update static mappings: {e}")

    def to_kraken_symbol(self, standard_symbol: str) -> Optional[str]:
        """
        Convert standard symbol (BTC-USD) to Kraken format (XXBTZUSD).

        Args:
            standard_symbol: Symbol in standard format (e.g., "BTC-USD")

        Returns:
            Kraken symbol format or None if not found
        """
        # Try static map first (fastest)
        if standard_symbol in self._static_map:
            return self._static_map[standard_symbol]

        # Try dynamic map
        if standard_symbol in self._dynamic_map:
            return self._dynamic_map[standard_symbol]

        # Fallback: Simple conversion
        # Remove dash and uppercase
        kraken_symbol = standard_symbol.replace('-', '').upper()

        # BTC -> XBT conversion (Kraken's special naming)
        if kraken_symbol.startswith('BTC'):
            kraken_symbol = kraken_symbol.replace('BTC', 'XBT', 1)

        logger.debug(f"🔄 Fallback conversion: {standard_symbol} -> {kraken_symbol}")
        return kraken_symbol

    def to_standard_symbol(self, kraken_symbol: str) -> Optional[str]:
        """
        Convert Kraken symbol (XXBTZUSD) to standard format (BTC-USD).

        Args:
            kraken_symbol: Symbol in Kraken format

        Returns:
            Standard symbol format or None if not found
        """
        # Try reverse map
        if kraken_symbol in self._reverse_map:
            return self._reverse_map[kraken_symbol]

        # Fallback: Manual conversion
        # This is approximate and may not work for all pairs
        symbol = kraken_symbol

        # Handle XBT -> BTC conversion
        if symbol.startswith('XXBT'):
            symbol = symbol.replace('XXBT', 'BTC', 1)
        elif symbol.startswith('XBT'):
            symbol = symbol.replace('XBT', 'BTC', 1)

        # Try to split into base and quote
        # Most USD pairs end with USD or USDT
        if symbol.endswith('USDT'):
            base = symbol[:-4]
            quote = 'USDT'
        elif symbol.endswith('USD'):
            base = symbol[:-3]
            quote = 'USD'
        else:
            logger.warning(f"⚠️  Cannot convert Kraken symbol to standard: {kraken_symbol}")
            return None

        # Remove X prefix if present
        if base.startswith('X') and len(base) > 3:
            base = base[1:]

        standard = f"{base}-{quote}"
        logger.debug(f"🔄 Reverse conversion: {kraken_symbol} -> {standard}")
        return standard

    def is_available(self, standard_symbol: str) -> bool:
        """
        Check if a trading pair is available on Kraken.

        Args:
            standard_symbol: Symbol in standard format (e.g., "BTC-USD")

        Returns:
            True if pair is available, False otherwise
        """
        # If we have dynamic data, use it
        if self._initialized and self._available_pairs:
            return standard_symbol in self._available_pairs

        # Otherwise check if we can map it
        kraken_symbol = self.to_kraken_symbol(standard_symbol)
        return kraken_symbol is not None

    def validate_for_trading(self, standard_symbol: str) -> Tuple[bool, str]:
        """
        Validate if a symbol can be traded on Kraken.

        Args:
            standard_symbol: Symbol in standard format

        Returns:
            Tuple of (is_valid, message)
        """
        # Check if symbol is in our available pairs
        if not self.is_available(standard_symbol):
            return False, f"Symbol {standard_symbol} is not available on Kraken"

        # Check if we can map to Kraken format
        kraken_symbol = self.to_kraken_symbol(standard_symbol)
        if not kraken_symbol:
            return False, f"Cannot convert {standard_symbol} to Kraken format"

        return True, f"Symbol {standard_symbol} is valid (maps to {kraken_symbol})"

    def get_common_pairs(self, other_symbols: List[str]) -> List[str]:
        """
        Get symbols that are available on both Kraken and another list.

        This is useful for copy trading to ensure trades only happen on
        pairs available on both exchanges.

        Args:
            other_symbols: List of symbols from another exchange

        Returns:
            List of common symbols in standard format
        """
        # Get all available Kraken symbols
        if self._initialized and self._available_pairs:
            kraken_symbols = self._available_pairs
        else:
            kraken_symbols = set(self._static_map.keys())

        # Find intersection
        common = list(kraken_symbols & set(other_symbols))

        logger.info(f"🔗 Found {len(common)} common pairs between Kraken and other exchange")
        return sorted(common)

    def get_all_available_pairs(self) -> List[str]:
        """
        Get all available Kraken trading pairs in standard format.

        Returns:
            List of all available symbols
        """
        if self._initialized and self._available_pairs:
            return sorted(list(self._available_pairs))
        else:
            return sorted(list(self._static_map.keys()))


# Global instance for easy access
_mapper_instance: Optional[KrakenSymbolMapper] = None


def get_kraken_symbol_mapper() -> KrakenSymbolMapper:
    """
    Get the global KrakenSymbolMapper instance.

    Returns:
        Global mapper instance
    """
    global _mapper_instance
    if _mapper_instance is None:
        _mapper_instance = KrakenSymbolMapper()
    return _mapper_instance


def validate_kraken_symbol(symbol: str) -> bool:
    """
    Quick validation helper - check if symbol is available on Kraken.

    Args:
        symbol: Standard format symbol (e.g., "BTC-USD")

    Returns:
        True if valid, False otherwise
    """
    mapper = get_kraken_symbol_mapper()
    return mapper.is_available(symbol)


def convert_to_kraken(symbol: str) -> Optional[str]:
    """
    Quick conversion helper - convert to Kraken format.

    Args:
        symbol: Standard format symbol

    Returns:
        Kraken format symbol or None
    """
    mapper = get_kraken_symbol_mapper()
    return mapper.to_kraken_symbol(symbol)


def validate_for_copy_trading(platform_symbols: List[str], user_symbols: List[str]) -> List[str]:
    """
    Get symbols that can be safely copy traded.

    Args:
        platform_symbols: Symbols available on platform account exchange
        user_symbols: Symbols available on user account exchange

    Returns:
        List of common symbols suitable for copy trading
    """
    mapper = get_kraken_symbol_mapper()

    # Get Kraken available pairs
    kraken_pairs = mapper.get_all_available_pairs()

    # Find intersection of all three sets
    platform_set = set(platform_symbols)
    user_set = set(user_symbols)
    kraken_set = set(kraken_pairs)

    # Common pairs across all exchanges
    common = sorted(list(platform_set & user_set & kraken_set))

    logger.info(f"🎯 Copy trading enabled for {len(common)} common pairs")
    return common
