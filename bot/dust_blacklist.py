#!/usr/bin/env python3
"""
Dust Position Blacklist - Permanent exclusion for sub-$1 positions

Maintains a persistent blacklist of symbols that have been identified as dust positions
(< $1 USD value). Once blacklisted, these positions are permanently ignored from:
- Position counting
- Trading strategy evaluation
- Cap enforcement calculations
- New entry consideration

This reduces noise in logs and ensures predictable position management.
"""

import json
import logging
from pathlib import Path
from typing import Set, Optional
from datetime import datetime
from threading import Lock

logger = logging.getLogger("nija.dust_blacklist")

# Dust threshold - positions below this are blacklisted
DUST_THRESHOLD_USD = 1.00


class DustBlacklist:
    """
    Manages permanent blacklist for dust positions (< $1 USD).
    
    Thread-safe, persistent storage in JSON file.
    Once a symbol is blacklisted, it stays blacklisted until manually cleared.
    """
    
    def __init__(self, data_dir: str = "./data"):
        """
        Initialize dust blacklist manager.
        
        Args:
            data_dir: Directory for blacklist file storage
        """
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(exist_ok=True, parents=True)
        self.blacklist_file = self.data_dir / "dust_blacklist.json"
        self._lock = Lock()
        self._blacklisted_symbols: Set[str] = set()
        self._load_blacklist()
        
    def _load_blacklist(self) -> None:
        """Load blacklist from file."""
        if not self.blacklist_file.exists():
            logger.info("No existing dust blacklist found (first run)")
            return
            
        try:
            with open(self.blacklist_file, 'r') as f:
                data = json.load(f)
                self._blacklisted_symbols = set(data.get('blacklisted_symbols', []))
                logger.info(f"Loaded {len(self._blacklisted_symbols)} blacklisted symbols")
                if self._blacklisted_symbols:
                    logger.info(f"  Blacklisted: {', '.join(sorted(self._blacklisted_symbols))}")
        except Exception as e:
            logger.error(f"Failed to load dust blacklist: {e}")
            
    def _save_blacklist(self) -> bool:
        """
        Save blacklist to file.
        
        Returns:
            bool: True if save successful
        """
        try:
            data = {
                'timestamp': datetime.now().isoformat(),
                'blacklisted_symbols': sorted(list(self._blacklisted_symbols)),
                'count': len(self._blacklisted_symbols),
                'threshold_usd': DUST_THRESHOLD_USD
            }
            
            # Atomic write using temp file
            temp_file = self.blacklist_file.with_suffix('.tmp')
            with open(temp_file, 'w') as f:
                json.dump(data, f, indent=2)
                
            # Rename to final file (atomic on POSIX)
            temp_file.replace(self.blacklist_file)
            
            logger.debug(f"Saved {len(self._blacklisted_symbols)} blacklisted symbols")
            return True
            
        except Exception as e:
            logger.error(f"Failed to save dust blacklist: {e}")
            return False
            
    def add_to_blacklist(self, symbol: str, usd_value: float, reason: str = "dust position") -> bool:
        """
        Add a symbol to the permanent blacklist.
        
        Args:
            symbol: Trading pair symbol (e.g., 'BTC-USD')
            usd_value: Current USD value of position
            reason: Reason for blacklisting (for logging)
            
        Returns:
            bool: True if added (or already blacklisted)
        """
        with self._lock:
            if symbol in self._blacklisted_symbols:
                logger.debug(f"Symbol {symbol} already blacklisted")
                return True
                
            self._blacklisted_symbols.add(symbol)
            logger.warning(f"🗑️  BLACKLISTED: {symbol} (${usd_value:.4f}) - {reason}")
            return self._save_blacklist()
            
    def is_blacklisted(self, symbol: str) -> bool:
        """
        Check if a symbol is blacklisted.
        
        Args:
            symbol: Trading pair symbol
            
        Returns:
            bool: True if blacklisted
        """
        with self._lock:
            return symbol in self._blacklisted_symbols
            
    def remove_from_blacklist(self, symbol: str) -> bool:
        """
        Remove a symbol from the blacklist (manual override).
        
        Args:
            symbol: Trading pair symbol
            
        Returns:
            bool: True if removed
        """
        with self._lock:
            if symbol not in self._blacklisted_symbols:
                logger.warning(f"Symbol {symbol} not in blacklist")
                return False
                
            self._blacklisted_symbols.remove(symbol)
            logger.info(f"Removed {symbol} from dust blacklist")
            return self._save_blacklist()
            
    def get_blacklisted_symbols(self) -> Set[str]:
        """
        Get all blacklisted symbols.
        
        Returns:
            set: Blacklisted symbols
        """
        with self._lock:
            return self._blacklisted_symbols.copy()
            
    def clear_blacklist(self) -> bool:
        """
        Clear entire blacklist (manual reset).
        
        Returns:
            bool: True if cleared successfully
        """
        with self._lock:
            count = len(self._blacklisted_symbols)
            self._blacklisted_symbols.clear()
            logger.warning(f"Cleared {count} symbols from dust blacklist")
            return self._save_blacklist()
            
    def get_stats(self) -> dict:
        """
        Get blacklist statistics.
        
        Returns:
            dict: Statistics including count and threshold
        """
        with self._lock:
            return {
                'count': len(self._blacklisted_symbols),
                'threshold_usd': DUST_THRESHOLD_USD,
                'symbols': sorted(list(self._blacklisted_symbols))
            }


# Global singleton instance
_dust_blacklist: Optional[DustBlacklist] = None
_blacklist_lock = Lock()


def get_dust_blacklist(data_dir: str = "./data") -> DustBlacklist:
    """
    Get global dust blacklist instance (singleton).
    
    Args:
        data_dir: Directory for blacklist storage
        
    Returns:
        DustBlacklist: Global blacklist instance
    """
    global _dust_blacklist
    
    with _blacklist_lock:
        if _dust_blacklist is None:
            _dust_blacklist = DustBlacklist(data_dir=data_dir)
        return _dust_blacklist
