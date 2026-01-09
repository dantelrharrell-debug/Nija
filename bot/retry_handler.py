"""
NIJA Retry Handler - Robust Error Handling for API Calls

Implements exponential backoff, partial fill handling, and network resilience.
"""

import time
import logging
from typing import Callable, Optional, Any, Dict
from functools import wraps

logger = logging.getLogger("nija.retry")


class RetryHandler:
    """
    Handles API call retries with exponential backoff.
    
    Features:
    - Exponential backoff (2s, 4s, 8s, 16s delays)
    - Configurable max attempts
    - Handles partial fills
    - Network timeout recovery
    - API rate limit detection
    """
    
    def __init__(self, max_attempts: int = 3, base_delay: float = 2.0):
        """
        Initialize retry handler.
        
        Args:
            max_attempts: Maximum retry attempts
            base_delay: Base delay in seconds (doubles each retry)
        """
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        logger.info(f"🔄 Retry handler initialized: {max_attempts} attempts, {base_delay}s base delay")
    
    def retry_on_failure(self, operation_name: str = "API call"):
        """
        Decorator for retrying functions that may fail.
        
        Args:
            operation_name: Name of operation for logging
        
        Usage:
            @retry_handler.retry_on_failure("place_order")
            def place_order():
                return broker.place_market_order(...)
        """
        def decorator(func: Callable) -> Callable:
            @wraps(func)
            def wrapper(*args, **kwargs) -> Any:
                delay = self.base_delay
                
                for attempt in range(1, self.max_attempts + 1):
                    try:
                        result = func(*args, **kwargs)
                        
                        if attempt > 1:
                            logger.info(f"✅ {operation_name} succeeded on attempt {attempt}")
                        
                        return result
                        
                    except Exception as e:
                        error_msg = str(e)
                        
                        # Check if retryable error
                        if self._is_retryable(error_msg):
                            if attempt < self.max_attempts:
                                logger.warning(
                                    f"⚠️  {operation_name} failed (attempt {attempt}/{self.max_attempts}): {error_msg}"
                                )
                                logger.info(f"🔄 Retrying in {delay}s...")
                                time.sleep(delay)
                                delay = min(delay * 2, 30)  # Cap at 30s
                                continue
                        
                        # Non-retryable or max attempts reached
                        logger.error(
                            f"❌ {operation_name} failed permanently (attempt {attempt}/{self.max_attempts}): {error_msg}"
                        )
                        raise
                
                # Should never reach here
                raise RuntimeError(f"{operation_name} failed after {self.max_attempts} attempts")
            
            return wrapper
        return decorator
    
    def _is_retryable(self, error_msg: str) -> bool:
        """
        Determine if error is retryable.
        
        Args:
            error_msg: Error message string
        
        Returns:
            bool: True if error should be retried
        """
        error_msg_lower = error_msg.lower()
        
        # Retryable errors
        retryable_keywords = [
            'timeout',
            'connection',
            'network',
            'rate limit',
            'too many requests',
            'too many errors',  # Coinbase-specific rate limiting message
            'service unavailable',
            '503',
            '504',
            '429',
            'temporary',
            'try again'
        ]
        
        for keyword in retryable_keywords:
            if keyword in error_msg_lower:
                return True
        
        # CRITICAL: Check for 403 errors which can indicate either:
        # 1. Temporary API key blocking from rate limiting (RETRYABLE)
        # 2. Permanent authentication failure (NON-RETRYABLE)
        # We need to distinguish between these cases based on the error message
        if '403' in error_msg_lower:
            # 403 with rate limiting indicators is retryable (Coinbase temporary block)
            # Example messages: "403 Forbidden Too many errors", "403 too many requests"
            if any(indicator in error_msg_lower for indicator in ['too many', 'rate limit']):
                return True
            # 403 with auth failure indicators is not retryable
            elif any(indicator in error_msg_lower for indicator in ['invalid', 'authentication', 'unauthorized']):
                return False
            # Default: treat bare 403 as non-retryable to avoid infinite loops on auth issues
            return False
        
        # Non-retryable errors
        non_retryable_keywords = [
            'invalid',
            'unauthorized',
            'not found',
            'insufficient',
            'authentication',
            '400',
            '401',
            '404'
        ]
        
        for keyword in non_retryable_keywords:
            if keyword in error_msg_lower:
                return False
        
        # Default: retry unknown errors
        return True
    
    def handle_partial_fill(self, order_response: Dict, expected_size: float,
                           tolerance: float = 0.01) -> Dict:
        """
        Check for partial fills and handle accordingly.
        
        Args:
            order_response: Response from place_order API
            expected_size: Expected order size
            tolerance: Acceptable size deviation (default 1%)
        
        Returns:
            dict: Enhanced response with partial_fill flag and filled_pct
        """
        if not order_response:
            return {
                'partial_fill': False,
                'filled_pct': 0.0,
                'status': 'failed'
            }
        
        try:
            # Extract filled size (varies by broker)
            # Handle None values gracefully
            filled_size_raw = order_response.get('filled_size')
            if filled_size_raw is None:
                filled_size_raw = order_response.get('size', 0)
            filled_size = float(filled_size_raw) if filled_size_raw else 0.0
            
            if filled_size <= 0:
                return {
                    **order_response,
                    'partial_fill': True,
                    'filled_pct': 0.0,
                    'status': 'unfilled'
                }
            
            filled_pct = (filled_size / expected_size) * 100
            deviation = abs(1.0 - (filled_size / expected_size))
            
            is_partial = deviation > tolerance
            
            if is_partial:
                logger.warning(
                    f"⚠️  Partial fill detected: {filled_pct:.1f}% "
                    f"(Expected: {expected_size:.6f}, Filled: {filled_size:.6f})"
                )
            
            return {
                **order_response,
                'partial_fill': is_partial,
                'filled_pct': filled_pct,
                'expected_size': expected_size,
                'actual_filled': filled_size,
                'status': 'partial' if is_partial else 'filled'
            }
            
        except Exception as e:
            logger.error(f"Error checking partial fill: {e}")
            return {
                **order_response,
                'partial_fill': False,
                'filled_pct': 0.0,
                'status': 'unknown'
            }
    
    def verify_order_status(self, broker, order_id: str, 
                           max_checks: int = 5,
                           check_interval: float = 1.0) -> Optional[Dict]:
        """
        Verify order status after placement.
        
        Args:
            broker: Broker instance
            order_id: Order ID to verify
            max_checks: Maximum status checks
            check_interval: Delay between checks (seconds)
        
        Returns:
            dict: Order status or None if failed
        """
        logger.info(f"🔍 Verifying order status: {order_id}")
        
        for check in range(1, max_checks + 1):
            try:
                # Try to get order status (if broker supports it)
                if hasattr(broker, 'get_order_status'):
                    status = broker.get_order_status(order_id)
                    
                    if status:
                        logger.info(f"✅ Order status verified (check {check}/{max_checks}): {status.get('status')}")
                        return status
                else:
                    # Fallback: assume success if no status method
                    logger.debug("Broker doesn't support get_order_status, assuming success")
                    return {'status': 'assumed_filled', 'order_id': order_id}
                
                if check < max_checks:
                    time.sleep(check_interval)
                    
            except Exception as e:
                logger.warning(f"Order status check failed (attempt {check}/{max_checks}): {e}")
                if check < max_checks:
                    time.sleep(check_interval)
        
        logger.error(f"❌ Failed to verify order status after {max_checks} checks")
        return None


# Global retry handler instance
retry_handler = RetryHandler(max_attempts=3, base_delay=2.0)
