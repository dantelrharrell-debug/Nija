"""
Geographic Restriction Blacklist Manager

Manages a persistent blacklist of symbols that cannot be traded due to
geographic restrictions (e.g., "KMNO trading restricted for US:WA").

This prevents the bot from repeatedly attempting to trade restricted symbols.
"""

import os
import json
import logging
from typing import List, Set
from datetime import datetime

logger = logging.getLogger("nija.restrictions")

# Path to the blacklist file (persists across restarts)
BLACKLIST_FILE = os.path.join(os.path.dirname(__file__), 'restricted_symbols.json')


class RestrictedSymbolsManager:
    """Manages blacklist of geographically restricted trading symbols"""
    
    def __init__(self):
        self.restricted_symbols: Set[str] = set()
        self.restriction_reasons: dict = {}  # symbol -> reason mapping
        self.load_blacklist()
    
    def load_blacklist(self):
        """Load blacklist from file"""
        try:
            if os.path.exists(BLACKLIST_FILE):
                with open(BLACKLIST_FILE, 'r') as f:
                    data = json.load(f)
                    self.restricted_symbols = set(data.get('symbols', []))
                    self.restriction_reasons = data.get('reasons', {})
                    
                if self.restricted_symbols:
                    logger.info(f"📋 Loaded {len(self.restricted_symbols)} restricted symbols from blacklist")
                    logger.info(f"   Restricted: {', '.join(sorted(self.restricted_symbols))}")
        except Exception as e:
            logger.warning(f"⚠️ Could not load restriction blacklist: {e}")
            self.restricted_symbols = set()
            self.restriction_reasons = {}
    
    def save_blacklist(self):
        """Persist blacklist to file"""
        try:
            data = {
                'symbols': list(self.restricted_symbols),
                'reasons': self.restriction_reasons,
                'last_updated': datetime.now().isoformat()
            }
            with open(BLACKLIST_FILE, 'w') as f:
                json.dump(data, f, indent=2)
            logger.info(f"💾 Saved restriction blacklist ({len(self.restricted_symbols)} symbols)")
        except Exception as e:
            logger.error(f"❌ Could not save restriction blacklist: {e}")
    
    def add_restricted_symbol(self, symbol: str, reason: str = None):
        """
        Add a symbol to the restriction blacklist
        
        Args:
            symbol: Trading symbol to blacklist (e.g., 'KMNO-USD', 'KMNOUSD')
            reason: Reason for restriction (e.g., 'trading restricted for US:WA')
        """
        # Normalize symbol (handle both dash and no-dash formats)
        normalized_symbols = self._normalize_symbol(symbol)
        
        added_any = False
        for sym in normalized_symbols:
            if sym not in self.restricted_symbols:
                self.restricted_symbols.add(sym)
                if reason:
                    self.restriction_reasons[sym] = reason
                added_any = True
                logger.warning(f"🚫 Added to restriction blacklist: {sym}")
                if reason:
                    logger.warning(f"   Reason: {reason}")
        
        if added_any:
            self.save_blacklist()
    
    def is_restricted(self, symbol: str) -> bool:
        """
        Check if a symbol is on the restriction blacklist
        
        Args:
            symbol: Trading symbol to check
            
        Returns:
            True if symbol is restricted, False otherwise
        """
        normalized_symbols = self._normalize_symbol(symbol)
        return any(sym in self.restricted_symbols for sym in normalized_symbols)
    
    def get_restriction_reason(self, symbol: str) -> str:
        """Get the restriction reason for a symbol"""
        normalized_symbols = self._normalize_symbol(symbol)
        for sym in normalized_symbols:
            if sym in self.restriction_reasons:
                return self.restriction_reasons[sym]
        return "Geographic restriction"
    
    def _normalize_symbol(self, symbol: str) -> List[str]:
        """
        Normalize symbol to handle different formats
        
        Returns both with and without dash (e.g., ['KMNO-USD', 'KMNOUSD'])
        """
        symbols = [symbol.upper()]
        
        # Add variant with/without dash
        if '-' in symbol:
            symbols.append(symbol.replace('-', '').upper())
        else:
            # Try to add dash before common quote currencies
            for quote in ['USD', 'USDT', 'USDC', 'BTC', 'ETH']:
                if symbol.upper().endswith(quote):
                    base = symbol[:-len(quote)]
                    symbols.append(f"{base}-{quote}".upper())
                    break
        
        return symbols
    
    def get_all_restricted_symbols(self) -> List[str]:
        """Get all restricted symbols as a list"""
        return sorted(list(self.restricted_symbols))


# Global instance
_restriction_manager = None


def get_restriction_manager() -> RestrictedSymbolsManager:
    """Get or create the global restriction manager instance"""
    global _restriction_manager
    if _restriction_manager is None:
        _restriction_manager = RestrictedSymbolsManager()
    return _restriction_manager


def is_symbol_restricted(symbol: str) -> bool:
    """Convenience function to check if a symbol is restricted"""
    return get_restriction_manager().is_restricted(symbol)


def add_restricted_symbol(symbol: str, reason: str = None):
    """Convenience function to add a restricted symbol"""
    get_restriction_manager().add_restricted_symbol(symbol, reason)


def is_geographic_restriction_error(error_message: str) -> bool:
    """
    Detect if an error message indicates a geographic restriction
    
    Args:
        error_message: Error message from broker
        
    Returns:
        True if error indicates geographic restriction
    """
    error_lower = error_message.lower()
    restriction_indicators = [
        'trading restricted',
        'restricted for us:',
        'not available in your region',
        'geographic restriction',
        'not permitted in',
        'invalid permissions',
        'region not supported'
    ]
    return any(indicator in error_lower for indicator in restriction_indicators)


def extract_symbol_from_error(error_message: str, attempted_symbol: str = None) -> str:
    """
    Extract the restricted symbol from an error message
    
    Args:
        error_message: Error message from broker
        attempted_symbol: The symbol that was attempted (fallback)
        
    Returns:
        Symbol that should be blacklisted
    """
    # For now, use the attempted symbol
    # Could be enhanced to parse symbol from error message if needed
    return attempted_symbol
