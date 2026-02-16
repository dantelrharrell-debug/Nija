#!/usr/bin/env python3
"""
Enhanced Balance Fetcher with Retry Logic
==========================================
Implements robust balance fetching with exponential backoff retry logic.

Features:
1. 3 retry attempts with exponential backoff (2s, 4s, 8s)
2. Fallback to last known balance on failure
3. Comprehensive error logging
4. Thread-safe last known balance caching

Priority: HIGH PRIORITY (Issue #2)
"""

import logging
import time
from typing import Optional, Dict
from datetime import datetime
from threading import Lock

logger = logging.getLogger(__name__)


class EnhancedBalanceFetcher:
    """
    Wraps broker balance fetch with retry logic and fallback.
    
    This ensures the trading bot can continue operating even when
    broker API is temporarily unavailable or experiencing issues.
    """
    
    def __init__(self, max_attempts: int = 3, base_delay: float = 2.0):
        """
        Initialize enhanced balance fetcher.
        
        Args:
            max_attempts: Maximum retry attempts (default: 3)
            base_delay: Base delay in seconds (doubles each retry)
        """
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self._last_known_balance: Optional[float] = None
        self._last_balance_time: Optional[datetime] = None
        self._lock = Lock()
        self._consecutive_errors = 0
        
        logger.info("💰 Enhanced Balance Fetcher initialized:")
        logger.info(f"   Max Attempts: {max_attempts}")
        logger.info(f"   Base Delay: {base_delay}s (exponential backoff)")
    
    def get_balance_with_retry(self, broker, verbose: bool = True) -> Optional[float]:
        """
        Fetch account balance with retry logic.
        
        Args:
            broker: Broker instance with get_account_balance() method
            verbose: If True, log detailed information
            
        Returns:
            float: Account balance or None if all attempts fail
        """
        delay = self.base_delay
        
        for attempt in range(1, self.max_attempts + 1):
            try:
                # Attempt to fetch balance
                balance = broker.get_account_balance(verbose=verbose and attempt == 1)
                
                # Validate balance
                if balance is None or balance < 0:
                    raise ValueError(f"Invalid balance returned: {balance}")
                
                # Success!
                with self._lock:
                    self._last_known_balance = balance
                    self._last_balance_time = datetime.now()
                    self._consecutive_errors = 0
                
                if attempt > 1:
                    logger.info(f"✅ Balance fetch succeeded on attempt {attempt}: ${balance:.2f}")
                
                return balance
            
            except Exception as e:
                error_msg = str(e)
                
                if attempt < self.max_attempts:
                    logger.warning(
                        f"⚠️  Balance fetch failed (attempt {attempt}/{self.max_attempts}): {error_msg}"
                    )
                    logger.info(f"🔄 Retrying in {delay}s...")
                    time.sleep(delay)
                    delay = min(delay * 2, 30)  # Cap at 30s
                else:
                    # Final attempt failed
                    logger.error(
                        f"❌ Balance fetch failed permanently after {self.max_attempts} attempts"
                    )
                    logger.error(f"   Last error: {error_msg}")
                    
                    with self._lock:
                        self._consecutive_errors += 1
        
        # All attempts failed - return None
        return None
    
    def get_balance_with_fallback(self, broker, verbose: bool = True) -> float:
        """
        Fetch balance with retry and fallback to last known balance.
        
        This is the main method to use - it guarantees a balance is returned
        (either fresh or cached) so trading can continue.
        
        Args:
            broker: Broker instance
            verbose: If True, log detailed information
            
        Returns:
            float: Account balance (fresh or cached)
        """
        # Try to fetch with retry
        balance = self.get_balance_with_retry(broker, verbose=verbose)
        
        if balance is not None:
            return balance
        
        # Fetch failed - use fallback
        with self._lock:
            if self._last_known_balance is not None:
                age_seconds = (datetime.now() - self._last_balance_time).total_seconds()
                age_minutes = age_seconds / 60
                
                logger.warning("=" * 70)
                logger.warning("⚠️  USING FALLBACK BALANCE")
                logger.warning("=" * 70)
                logger.warning(f"   Last Known Balance: ${self._last_known_balance:.2f}")
                logger.warning(f"   Age: {age_minutes:.1f} minutes")
                logger.warning(f"   Consecutive Errors: {self._consecutive_errors}")
                logger.warning("")
                logger.warning("   Bot will continue trading with cached balance.")
                logger.warning("   Balance will be updated once API is available.")
                
                if age_minutes > 30:
                    logger.warning("")
                    logger.warning("   ⚠️  WARNING: Balance data is old (> 30 minutes)")
                    logger.warning("   Consider pausing trading until API is available")
                
                logger.warning("=" * 70)
                
                return self._last_known_balance
            else:
                logger.error("=" * 70)
                logger.error("❌ CRITICAL: No balance available")
                logger.error("=" * 70)
                logger.error("   - Balance fetch failed")
                logger.error("   - No cached balance available")
                logger.error("   - Cannot continue trading")
                logger.error("")
                logger.error("   Returning 0.0 - trading will be paused")
                logger.error("=" * 70)
                
                return 0.0
    
    def get_last_known_balance(self) -> Optional[Dict[str, any]]:
        """
        Get information about last known balance.
        
        Returns:
            Dict with balance, timestamp, and age information
        """
        with self._lock:
            if self._last_known_balance is None:
                return None
            
            age_seconds = (datetime.now() - self._last_balance_time).total_seconds() if self._last_balance_time else 0
            
            return {
                'balance': self._last_known_balance,
                'timestamp': self._last_balance_time.isoformat() if self._last_balance_time else None,
                'age_seconds': age_seconds,
                'age_minutes': age_seconds / 60,
                'consecutive_errors': self._consecutive_errors
            }
    
    def reset_error_count(self):
        """Reset consecutive error counter."""
        with self._lock:
            self._consecutive_errors = 0
            logger.info("✅ Balance fetch error counter reset")
    
    def set_last_known_balance(self, balance: float):
        """
        Manually set last known balance (for initialization).
        
        Args:
            balance: Balance value to cache
        """
        with self._lock:
            self._last_known_balance = balance
            self._last_balance_time = datetime.now()
            logger.info(f"💰 Last known balance set: ${balance:.2f}")


# Global singleton instance
_enhanced_balance_fetcher: Optional[EnhancedBalanceFetcher] = None
_fetcher_lock = Lock()


def get_enhanced_balance_fetcher(max_attempts: int = 3,
                                 base_delay: float = 2.0) -> EnhancedBalanceFetcher:
    """
    Get global enhanced balance fetcher instance (singleton).
    
    Args:
        max_attempts: Maximum retry attempts
        base_delay: Base delay in seconds
        
    Returns:
        EnhancedBalanceFetcher: Global fetcher instance
    """
    global _enhanced_balance_fetcher
    
    with _fetcher_lock:
        if _enhanced_balance_fetcher is None:
            _enhanced_balance_fetcher = EnhancedBalanceFetcher(
                max_attempts=max_attempts,
                base_delay=base_delay
            )
        return _enhanced_balance_fetcher
