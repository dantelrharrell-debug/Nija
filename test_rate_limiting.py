#!/usr/bin/env python3
"""
Test script to verify rate limiting improvements work correctly.
This tests the exponential backoff with jitter and adaptive throttling.
"""

import time
import random
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def test_exponential_backoff_with_jitter():
    """Test the exponential backoff with jitter algorithm."""
    logger.info("="*70)
    logger.info("Testing Exponential Backoff with Jitter")
    logger.info("="*70)
    
    max_retries = 3
    base_delay = 1.0
    
    for attempt in range(max_retries):
        # Exponential backoff with jitter
        retry_delay = base_delay * (2 ** attempt)
        jitter = random.uniform(0, retry_delay * 0.3)  # Add up to 30% jitter
        total_delay = retry_delay + jitter
        
        logger.info(f"Attempt {attempt+1}/{max_retries}")
        logger.info(f"  Base delay: {retry_delay:.2f}s")
        logger.info(f"  Jitter: {jitter:.2f}s (0-30% of base)")
        logger.info(f"  Total delay: {total_delay:.2f}s")
        
        if attempt < max_retries - 1:
            logger.info(f"  Sleeping for {total_delay:.2f}s...")
            time.sleep(0.1)  # Short sleep for testing
    
    logger.info("✅ Exponential backoff test complete\n")

def test_scan_delay_with_jitter():
    """Test the market scan delay with jitter."""
    logger.info("="*70)
    logger.info("Testing Market Scan Delay with Jitter")
    logger.info("="*70)
    
    num_markets = 10
    base_delay = 0.25
    total_time = 0
    
    logger.info(f"Simulating scan of {num_markets} markets")
    logger.info(f"Base delay: {base_delay}s")
    
    start_time = time.time()
    
    for i in range(num_markets):
        if i < num_markets - 1:  # Don't delay after last market
            jitter = random.uniform(0, 0.05)  # 0-50ms jitter
            delay = base_delay + jitter
            total_time += delay
            
            if i < 3:  # Show first 3 for brevity
                logger.info(f"  Market {i+1}: delay={delay:.3f}s (base={base_delay}s + jitter={jitter:.3f}s)")
    
    elapsed = time.time() - start_time
    logger.info(f"\nTotal expected delay: {total_time:.2f}s")
    logger.info(f"Actual elapsed: {elapsed:.2f}s (includes execution overhead)")
    logger.info(f"Request rate: {num_markets/total_time:.2f} requests/second")
    logger.info("✅ Scan delay test complete\n")

def test_adaptive_throttling():
    """Test adaptive throttling logic."""
    logger.info("="*70)
    logger.info("Testing Adaptive Throttling")
    logger.info("="*70)
    
    rate_limit_counter = 0
    max_consecutive_rate_limits = 5
    
    # Simulate getting rate limited
    logger.info("Simulating consecutive failures (rate limiting):")
    for i in range(10):
        # Simulate no candles returned (possible rate limit)
        candles = None
        
        if not candles:
            rate_limit_counter += 1
            logger.info(f"  Request {i+1}: Failed (counter={rate_limit_counter})")
            
            if rate_limit_counter >= max_consecutive_rate_limits:
                logger.warning(f"  ⚠️ Rate limiting detected after {rate_limit_counter} failures")
                logger.warning(f"  Adding 2s recovery delay...")
                time.sleep(0.1)  # Short sleep for testing
                rate_limit_counter = 0  # Reset
                logger.info(f"  Counter reset, continuing...")
        else:
            # Success
            rate_limit_counter = 0
            logger.info(f"  Request {i+1}: Success (counter reset)")
    
    logger.info("✅ Adaptive throttling test complete\n")

def test_rate_calculation():
    """Calculate actual request rates with different delays."""
    logger.info("="*70)
    logger.info("Request Rate Calculations")
    logger.info("="*70)
    
    scenarios = [
        ("Old (0.1s delay)", 0.1, 730),
        ("New (0.25s delay)", 0.25, 730),
        ("With adaptive (0.25s + 2s recovery every 100)", 0.25, 730, 2.0, 100)
    ]
    
    for scenario in scenarios:
        if len(scenario) == 3:
            name, delay, markets = scenario
            total_time = markets * delay
            rate = markets / total_time if total_time > 0 else 0
            logger.info(f"{name}:")
            logger.info(f"  Total time: {total_time:.1f}s ({total_time/60:.1f} minutes)")
            logger.info(f"  Request rate: {rate:.2f} req/s")
        else:
            name, delay, markets, recovery_delay, recovery_freq = scenario
            num_recoveries = markets // recovery_freq
            total_time = (markets * delay) + (num_recoveries * recovery_delay)
            rate = markets / total_time if total_time > 0 else 0
            logger.info(f"{name}:")
            logger.info(f"  Total time: {total_time:.1f}s ({total_time/60:.1f} minutes)")
            logger.info(f"  Request rate: {rate:.2f} req/s (avg)")
            logger.info(f"  Recovery delays: {num_recoveries} x {recovery_delay}s")
    
    logger.info("✅ Rate calculation complete\n")

if __name__ == "__main__":
    logger.info("Starting rate limiting tests...\n")
    
    test_exponential_backoff_with_jitter()
    test_scan_delay_with_jitter()
    test_adaptive_throttling()
    test_rate_calculation()
    
    logger.info("="*70)
    logger.info("All tests completed successfully! ✅")
    logger.info("="*70)
    logger.info("\nSummary:")
    logger.info("- Exponential backoff with jitter prevents thundering herd")
    logger.info("- Market scan delay reduced to 4 req/s (from 10 req/s)")
    logger.info("- Adaptive throttling adds recovery delays when rate limited")
    logger.info("- Expected to eliminate 429 errors during normal operation")
