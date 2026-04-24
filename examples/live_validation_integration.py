"""
Example: Live Validation Framework Integration

Demonstrates how to integrate the Live Validation Framework
into your trading bot execution flow.

Author: NIJA Trading Systems
Date: January 30, 2026
"""

import logging
from datetime import datetime
from typing import Optional, Dict, Any

from bot.live_validation_framework import get_validation_framework
from bot.validation_models import ValidationContext, ValidationLevel

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(name)s | %(levelname)s | %(message)s'
)
logger = logging.getLogger("nija.example")


def execute_trade_with_validation(
    symbol: str,
    side: str,
    size: float,
    price: Optional[float] = None,
    account_balance: float = 10000.0,
    broker: str = "coinbase",
    account_id: str = "main"
) -> Optional[str]:
    """
    Execute a trade with full validation
    
    Args:
        symbol: Trading symbol (e.g., 'BTC-USD')
        side: 'buy' or 'sell'
        size: Position size
        price: Entry price (optional, fetched if None)
        account_balance: Account balance
        broker: Broker name
        account_id: Account identifier
        
    Returns:
        Order ID if successful, None if blocked by validation
    """
    # Get validation framework
    framework = get_validation_framework()
    
    logger.info("=" * 80)
    logger.info(f"TRADE REQUEST: {symbol} {side} {size}")
    logger.info("=" * 80)
    
    # Fetch current price if not provided
    if price is None:
        price = fetch_current_price(symbol, broker)
        logger.info(f"Fetched price: ${price:.2f}")
    
    # Create validation context
    ctx = ValidationContext(
        symbol=symbol,
        side=side,
        size=size,
        price=price,
        account_id=account_id,
        broker=broker,
        account_balance=account_balance,
        timestamp=datetime.utcnow()
    )
    
    # STEP 1: Pre-Trade Validation
    logger.info("\n🔍 Running Pre-Trade Validation...")
    results = framework.validate_pre_trade(
        ctx=ctx,
        current_price=price,
        bid=price * 0.999,  # Mock bid
        ask=price * 1.001,  # Mock ask
        account_balance=account_balance,
        open_positions=get_open_position_count()
    )
    
    # Log all validation results
    for result in results:
        if result.level == ValidationLevel.PASS:
            logger.debug(f"  ✅ {result.message}")
        elif result.level == ValidationLevel.INFO:
            logger.info(f"  ℹ️  {result.message}")
        elif result.level == ValidationLevel.WARNING:
            logger.warning(f"  ⚠️  {result.message}")
        else:
            logger.error(f"  ❌ {result.message}")
            if result.recommended_action:
                logger.error(f"     → {result.recommended_action}")
    
    # Check for blocking issues
    if framework.has_blocking_results(results):
        blocking = framework.get_blocking_results(results)
        logger.error("\n❌ TRADE BLOCKED BY VALIDATION")
        logger.error(f"   Blocking Issues: {len(blocking)}")
        for result in blocking:
            logger.error(f"   - {result.message}")
        return None
    
    logger.info("✅ Pre-trade validation passed")
    
    # STEP 2: Submit Order
    logger.info("\n📤 Submitting order to broker...")
    order_id = submit_order_to_broker(symbol, side, size, price, broker)
    
    if not order_id:
        logger.error("❌ Order submission failed")
        return None
    
    logger.info(f"✅ Order submitted: {order_id}")
    
    # Record order for tracking
    framework.record_order_submission(
        order_id=order_id,
        symbol=symbol,
        side=side,
        size=size,
        price=price,
        account_id=account_id,
        broker=broker
    )
    
    # STEP 3: Validate Order Execution
    logger.info("\n🔍 Validating Order Execution...")
    broker_response = wait_for_order_confirmation(order_id, broker)
    
    exec_results = framework.validate_order_execution(
        order_id=order_id,
        broker_response=broker_response,
        broker=broker
    )
    
    for result in exec_results:
        if result.is_blocking():
            logger.error(f"  ❌ {result.message}")
        else:
            logger.info(f"  ✅ {result.message}")
    
    # STEP 4: Validate Fill
    fill_price = broker_response.get('fill_price', price)
    logger.info(f"\n📊 Fill Price: ${fill_price:.2f}")
    
    post_results = framework.validate_post_trade(
        order_id=order_id,
        fill_price=fill_price,
        expected_price=price,
        broker=broker,
        symbol=symbol,
        side=side,
        size=size
    )
    
    for result in post_results:
        if result.level == ValidationLevel.WARNING:
            logger.warning(f"  ⚠️  {result.message}")
        elif result.is_blocking():
            logger.error(f"  ❌ {result.message}")
        else:
            logger.info(f"  ✅ {result.message}")
    
    logger.info("\n✅ TRADE EXECUTED SUCCESSFULLY")
    logger.info("=" * 80)
    
    return order_id


def monitor_risk_limits(account_id: str = "main", broker: str = "coinbase"):
    """
    Monitor and validate risk limits
    
    Args:
        account_id: Account identifier
        broker: Broker name
    """
    framework = get_validation_framework()
    
    # Get account data (mock data for example)
    account_data = {
        'starting_balance': 10000.0,
        'current_balance': 9500.0,
        'peak_balance': 10500.0,
        'daily_pnl': -500.0,
        'open_positions': 3,
        'total_position_value': 14000.0
    }
    
    logger.info("=" * 80)
    logger.info("RISK LIMITS VALIDATION")
    logger.info("=" * 80)
    logger.info(f"Account: {account_id}")
    logger.info(f"Balance: ${account_data['current_balance']:.2f}")
    logger.info(f"Daily P&L: ${account_data['daily_pnl']:.2f}")
    logger.info(f"Open Positions: {account_data['open_positions']}")
    
    results = framework.validate_risk_limits(
        account_id=account_id,
        broker=broker,
        **account_data
    )
    
    # Check for circuit breakers
    circuit_breakers = [r for r in results if r.level == ValidationLevel.CRITICAL]
    
    if circuit_breakers:
        logger.critical("\n🔴 CIRCUIT BREAKER TRIGGERED!")
        for result in circuit_breakers:
            logger.critical(f"  {result.message}")
            logger.critical(f"  Action: {result.recommended_action}")
        
        # Halt trading
        halt_trading(account_id)
        return False
    
    # Check for warnings
    warnings = [r for r in results if r.level == ValidationLevel.WARNING]
    if warnings:
        logger.warning("\n⚠️  Risk Warnings:")
        for result in warnings:
            logger.warning(f"  {result.message}")
    
    logger.info("\n✅ Risk limits validated")
    logger.info("=" * 80)
    return True


def show_validation_metrics():
    """Display validation framework metrics"""
    framework = get_validation_framework()
    
    print("\n" + framework.get_validation_summary())


# Mock functions (replace with actual implementations)

def fetch_current_price(symbol: str, broker: str) -> float:
    """Fetch current market price"""
    # Mock: return sample price
    prices = {
        'BTC-USD': 50000.0,
        'ETH-USD': 3000.0,
        'SOL-USD': 100.0
    }
    return prices.get(symbol, 1000.0)


def get_open_position_count() -> int:
    """Get count of open positions"""
    # Mock: return sample count
    return 2


def submit_order_to_broker(
    symbol: str,
    side: str,
    size: float,
    price: float,
    broker: str
) -> Optional[str]:
    """Submit order to broker"""
    # Mock: return sample order ID
    import uuid
    return f"order_{uuid.uuid4().hex[:8]}"


def wait_for_order_confirmation(order_id: str, broker: str) -> Dict[str, Any]:
    """Wait for order confirmation from broker"""
    # Mock: return sample confirmation
    return {
        'order_id': order_id,
        'status': 'filled',
        'fill_price': 50000.0,
        'filled_size': 0.001
    }


def halt_trading(account_id: str):
    """Halt trading for account"""
    logger.critical(f"🛑 TRADING HALTED FOR ACCOUNT: {account_id}")


# Example usage
if __name__ == "__main__":
    print("\n" + "=" * 80)
    print("LIVE VALIDATION FRAMEWORK - INTEGRATION EXAMPLE")
    print("=" * 80 + "\n")
    
    # Example 1: Execute trade with validation
    print("\n📋 Example 1: Execute Trade with Validation\n")
    order_id = execute_trade_with_validation(
        symbol="BTC-USD",
        side="buy",
        size=0.001,
        price=50000.0,
        account_balance=10000.0
    )
    
    if order_id:
        print(f"\n✅ Trade executed successfully: {order_id}")
    else:
        print("\n❌ Trade blocked by validation")
    
    # Example 2: Monitor risk limits
    print("\n\n📋 Example 2: Monitor Risk Limits\n")
    risk_ok = monitor_risk_limits()
    
    if not risk_ok:
        print("\n🔴 Trading halted due to risk limits")
    
    # Example 3: Show validation metrics
    print("\n\n📋 Example 3: Validation Metrics\n")
    show_validation_metrics()
    
    print("\n" + "=" * 80)
    print("EXAMPLE COMPLETE")
    print("=" * 80 + "\n")
