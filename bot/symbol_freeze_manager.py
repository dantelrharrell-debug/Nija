#!/usr/bin/env python3
"""
Symbol Freeze Manager
====================
Implements freeze mechanism for symbols with persistent price fetch failures.

Features:
1. Track consecutive price fetch failures per symbol
2. Freeze symbols after failure threshold (default: 3)
3. Flag frozen symbols for manual review
4. Prevent trading on frozen symbols
5. Automatic unfreeze after cooldown period

Priority: HIGH PRIORITY (Issue #2)
"""

import logging
from typing import Dict, Optional, Set, Any
from datetime import datetime, timedelta
from threading import Lock
from dataclasses import dataclass
import json
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class SymbolFreezeInfo:
    """Information about a frozen symbol"""
    symbol: str
    freeze_time: datetime
    consecutive_failures: int
    last_error: str
    manual_review_required: bool = True


class SymbolFreezeManager:
    """
    Manages frozen symbols that have persistent price fetch failures.
    
    When a symbol's price cannot be fetched consistently, it is frozen
    to prevent trading until the issue is resolved. This protects against:
    - Delisted coins
    - Temporarily suspended trading pairs
    - API mapping issues
    - Network/broker issues specific to certain symbols
    """
    
    def __init__(self,
                 failure_threshold: int = 3,
                 cooldown_hours: float = 24.0,
                 data_dir: str = "./data"):
        """
        Initialize symbol freeze manager.
        
        Args:
            failure_threshold: Number of consecutive failures before freeze
            cooldown_hours: Hours before automatic unfreeze attempt
            data_dir: Directory for freeze state persistence
        """
        self.failure_threshold = failure_threshold
        self.cooldown_hours = cooldown_hours
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(exist_ok=True, parents=True)
        self.freeze_file = self.data_dir / "frozen_symbols.json"
        
        self._failure_counts: Dict[str, int] = {}
        self._last_errors: Dict[str, str] = {}
        self._frozen_symbols: Dict[str, SymbolFreezeInfo] = {}
        self._lock = Lock()
        
        # Load persisted freeze state
        self._load_freeze_state()
        
        logger.info("❄️  Symbol Freeze Manager initialized:")
        logger.info(f"   Failure Threshold: {failure_threshold} consecutive failures")
        logger.info(f"   Cooldown Period: {cooldown_hours}h")
        logger.info(f"   Currently Frozen: {len(self._frozen_symbols)} symbols")
        if self._frozen_symbols:
            logger.info(f"   Frozen Symbols: {', '.join(sorted(self._frozen_symbols.keys()))}")
    
    def _load_freeze_state(self):
        """Load frozen symbols from persistent storage."""
        if not self.freeze_file.exists():
            logger.info("   No existing freeze state found (first run)")
            return
        
        try:
            with open(self.freeze_file, 'r') as f:
                data = json.load(f)
                
            for symbol, info in data.get('frozen_symbols', {}).items():
                freeze_time = datetime.fromisoformat(info['freeze_time'])
                self._frozen_symbols[symbol] = SymbolFreezeInfo(
                    symbol=symbol,
                    freeze_time=freeze_time,
                    consecutive_failures=info['consecutive_failures'],
                    last_error=info['last_error'],
                    manual_review_required=info.get('manual_review_required', True)
                )
            
            logger.info(f"   Loaded {len(self._frozen_symbols)} frozen symbols from storage")
        
        except Exception as e:
            logger.error(f"Failed to load freeze state: {e}")
    
    def _save_freeze_state(self):
        """Save frozen symbols to persistent storage."""
        try:
            data = {
                'timestamp': datetime.now().isoformat(),
                'failure_threshold': self.failure_threshold,
                'cooldown_hours': self.cooldown_hours,
                'frozen_symbols': {
                    symbol: {
                        'symbol': info.symbol,
                        'freeze_time': info.freeze_time.isoformat(),
                        'consecutive_failures': info.consecutive_failures,
                        'last_error': info.last_error,
                        'manual_review_required': info.manual_review_required
                    }
                    for symbol, info in self._frozen_symbols.items()
                }
            }
            
            # Atomic write
            temp_file = self.freeze_file.with_suffix('.tmp')
            with open(temp_file, 'w') as f:
                json.dump(data, f, indent=2)
            temp_file.replace(self.freeze_file)
            
            logger.debug(f"Saved freeze state: {len(self._frozen_symbols)} frozen symbols")
        
        except Exception as e:
            logger.error(f"Failed to save freeze state: {e}")
    
    def record_price_fetch_failure(self, symbol: str, error_msg: str) -> bool:
        """
        Record a price fetch failure for a symbol.
        
        Args:
            symbol: Trading pair symbol
            error_msg: Error message from price fetch
            
        Returns:
            bool: True if symbol was frozen as a result
        """
        with self._lock:
            # Increment failure count
            self._failure_counts[symbol] = self._failure_counts.get(symbol, 0) + 1
            self._last_errors[symbol] = error_msg
            
            failures = self._failure_counts[symbol]
            
            logger.warning(f"⚠️  Price fetch failed for {symbol} ({failures}/{self.failure_threshold}): {error_msg}")
            
            # Check if we should freeze
            if failures >= self.failure_threshold and symbol not in self._frozen_symbols:
                return self._freeze_symbol(symbol, failures, error_msg)
            
            return False
    
    def _freeze_symbol(self, symbol: str, failures: int, error_msg: str) -> bool:
        """
        Freeze a symbol due to persistent failures.
        
        Args:
            symbol: Trading pair symbol
            failures: Number of consecutive failures
            error_msg: Last error message
            
        Returns:
            bool: True if frozen successfully
        """
        freeze_info = SymbolFreezeInfo(
            symbol=symbol,
            freeze_time=datetime.now(),
            consecutive_failures=failures,
            last_error=error_msg,
            manual_review_required=True
        )
        
        self._frozen_symbols[symbol] = freeze_info
        self._save_freeze_state()
        
        logger.error("=" * 70)
        logger.error(f"❄️  SYMBOL FROZEN: {symbol}")
        logger.error("=" * 70)
        logger.error(f"   Reason: {failures} consecutive price fetch failures")
        logger.error(f"   Last Error: {error_msg}")
        logger.error(f"   Freeze Time: {freeze_info.freeze_time.isoformat()}")
        logger.error("")
        logger.error("   ⚠️  MANUAL REVIEW REQUIRED")
        logger.error("   Possible causes:")
        logger.error("   - Symbol delisted from exchange")
        logger.error("   - Trading temporarily suspended")
        logger.error("   - Symbol mapping issue (e.g., AUT-USD)")
        logger.error("   - Network/API connectivity issue")
        logger.error("")
        logger.error(f"   Symbol will remain frozen for {self.cooldown_hours}h")
        logger.error("   Use unfreeze_symbol() to manually unfreeze if resolved")
        logger.error("=" * 70)
        
        return True
    
    def record_price_fetch_success(self, symbol: str):
        """
        Record a successful price fetch for a symbol.
        
        Args:
            symbol: Trading pair symbol
        """
        with self._lock:
            if symbol in self._failure_counts:
                del self._failure_counts[symbol]
            if symbol in self._last_errors:
                del self._last_errors[symbol]
    
    def is_frozen(self, symbol: str) -> bool:
        """
        Check if a symbol is frozen.
        
        Args:
            symbol: Trading pair symbol
            
        Returns:
            bool: True if frozen
        """
        with self._lock:
            # Check if frozen
            if symbol not in self._frozen_symbols:
                return False
            
            # Check if cooldown period has passed
            freeze_info = self._frozen_symbols[symbol]
            time_frozen = datetime.now() - freeze_info.freeze_time
            hours_frozen = time_frozen.total_seconds() / 3600
            
            if hours_frozen >= self.cooldown_hours and not freeze_info.manual_review_required:
                # Automatic unfreeze after cooldown
                logger.info(f"❄️  Auto-unfreezing {symbol} after {hours_frozen:.1f}h cooldown")
                del self._frozen_symbols[symbol]
                self._save_freeze_state()
                return False
            
            return True
    
    def get_frozen_symbols(self) -> Dict[str, SymbolFreezeInfo]:
        """
        Get all currently frozen symbols.
        
        Returns:
            Dict mapping symbol to SymbolFreezeInfo
        """
        with self._lock:
            return self._frozen_symbols.copy()
    
    def unfreeze_symbol(self, symbol: str, reason: str = "manual unfreeze") -> bool:
        """
        Manually unfreeze a symbol.
        
        Args:
            symbol: Trading pair symbol
            reason: Reason for unfreezing
            
        Returns:
            bool: True if unfrozen successfully
        """
        with self._lock:
            if symbol not in self._frozen_symbols:
                logger.warning(f"Symbol {symbol} is not frozen")
                return False
            
            freeze_info = self._frozen_symbols[symbol]
            time_frozen = datetime.now() - freeze_info.freeze_time
            hours_frozen = time_frozen.total_seconds() / 3600
            
            del self._frozen_symbols[symbol]
            
            # Clear failure counts
            if symbol in self._failure_counts:
                del self._failure_counts[symbol]
            if symbol in self._last_errors:
                del self._last_errors[symbol]
            
            self._save_freeze_state()
            
            logger.info("=" * 70)
            logger.info(f"✅ SYMBOL UNFROZEN: {symbol}")
            logger.info("=" * 70)
            logger.info(f"   Reason: {reason}")
            logger.info(f"   Was frozen for: {hours_frozen:.1f}h")
            logger.info(f"   Original error: {freeze_info.last_error}")
            logger.info("=" * 70)
            
            return True
    
    def get_failure_count(self, symbol: str) -> int:
        """
        Get current failure count for a symbol.
        
        Args:
            symbol: Trading pair symbol
            
        Returns:
            int: Current failure count
        """
        with self._lock:
            return self._failure_counts.get(symbol, 0)
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get freeze manager statistics.
        
        Returns:
            Dict with statistics
        """
        with self._lock:
            return {
                'failure_threshold': self.failure_threshold,
                'cooldown_hours': self.cooldown_hours,
                'frozen_count': len(self._frozen_symbols),
                'frozen_symbols': list(self._frozen_symbols.keys()),
                'symbols_with_failures': len(self._failure_counts),
                'pending_freeze': [
                    {'symbol': s, 'failures': f}
                    for s, f in self._failure_counts.items()
                    if s not in self._frozen_symbols
                ]
            }


# Global singleton instance
_symbol_freeze_manager: Optional[SymbolFreezeManager] = None
_manager_lock = Lock()


def get_symbol_freeze_manager(failure_threshold: int = 3,
                              cooldown_hours: float = 24.0,
                              data_dir: str = "./data") -> SymbolFreezeManager:
    """
    Get global symbol freeze manager instance (singleton).
    
    Args:
        failure_threshold: Number of consecutive failures before freeze
        cooldown_hours: Hours before automatic unfreeze attempt
        data_dir: Directory for freeze state persistence
        
    Returns:
        SymbolFreezeManager: Global manager instance
    """
    global _symbol_freeze_manager
    
    with _manager_lock:
        if _symbol_freeze_manager is None:
            _symbol_freeze_manager = SymbolFreezeManager(
                failure_threshold=failure_threshold,
                cooldown_hours=cooldown_hours,
                data_dir=data_dir
            )
        return _symbol_freeze_manager
