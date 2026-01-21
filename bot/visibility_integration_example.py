"""
EXAMPLE: Integrating Activity Feed, Position Mirror, and Tier Config

This is a reference implementation showing how to integrate the new
three-layer visibility system into the trading strategy.

To integrate into your existing trading strategy:
1. Import the modules at the top of your file
2. Initialize the systems in __init__
3. Call logging methods at decision points
4. Use tier config for trade validation
5. Use stablecoin routing for broker selection

Author: NIJA Trading Systems
Date: January 2026
"""

from bot.activity_feed import get_activity_feed, ActivityType
from bot.position_mirror import get_position_mirror
from bot.tier_config import (
    get_tier_from_balance,
    get_min_trade_size,
    get_stablecoin_broker,
    is_stablecoin_pair,
    validate_trade_size,
    should_show_trade_in_feed,
    StablecoinPolicy
)
import os


class EnhancedTradingStrategy:
    """
    Example trading strategy with full visibility integration.
    """
    
    def __init__(self):
        # Initialize visibility systems
        self.activity_feed = get_activity_feed()
        self.position_mirror = get_position_mirror()
        
        # Get stablecoin policy from environment
        policy_str = os.getenv('STABLECOIN_POLICY', 'route_to_kraken')
        self.stablecoin_policy = StablecoinPolicy(policy_str)
        
        # Tier will be determined from balance
        self.current_tier = None
    
    def check_trading_signal(self, symbol: str, side: str, ai_score: float, 
                            confidence: float, price: float) -> bool:
        """
        Check if a trading signal should be executed.
        
        Returns True if signal is accepted, False if rejected.
        """
        # Log signal generation
        self.activity_feed.log_signal_generated(
            symbol=symbol,
            signal_type=side,
            ai_score=ai_score,
            confidence=confidence,
            details={
                'price': price,
                'timestamp': 'now'
            }
        )
        
        # Example: Reject low-confidence signals
        if confidence < 0.7:
            self.activity_feed.log_signal_rejected(
                symbol=symbol,
                signal_type=side,
                rejection_reason=f"Low confidence ({confidence:.2%} < 70%)",
                details={
                    'ai_score': ai_score,
                    'confidence': confidence,
                    'threshold': 0.7
                }
            )
            return False
        
        # Signal accepted
        return True
    
    def validate_trade_before_execution(self, symbol: str, broker: str,
                                       position_size: float, balance: float) -> tuple:
        """
        Validate trade against tier limits, fees, and stablecoin routing.
        
        Returns: (is_valid, final_broker, reason)
        """
        # Determine tier from balance
        tier = get_tier_from_balance(balance)
        self.current_tier = tier
        
        # Check tier-based minimum size
        is_valid, reason = validate_trade_size(position_size, tier, balance)
        if not is_valid:
            self.activity_feed.log_min_size_block(
                symbol=symbol,
                broker=broker,
                attempted_size=position_size,
                min_size=get_min_trade_size(tier, balance),
                tier=tier.value,
                details={'balance': balance}
            )
            return (False, broker, reason)
        
        # Check stablecoin routing
        if is_stablecoin_pair(symbol):
            final_broker, routing_reason = get_stablecoin_broker(
                symbol=symbol,
                preferred_broker=broker,
                policy=self.stablecoin_policy
            )
            
            if final_broker is None:
                # Stablecoin blocked
                self.activity_feed.log_stablecoin_blocked(
                    symbol=symbol,
                    broker=broker,
                    reason=routing_reason
                )
                return (False, broker, f"Stablecoin trades blocked: {routing_reason}")
            
            if final_broker != broker:
                # Stablecoin routed to different broker
                self.activity_feed.log_stablecoin_routed(
                    symbol=symbol,
                    from_broker=broker,
                    to_broker=final_broker,
                    reason=routing_reason
                )
                broker = final_broker
        else:
            final_broker = broker
        
        # Example: Check for excessive fees (simplified)
        estimated_fees = position_size * 0.012  # 1.2% round-trip estimate
        if estimated_fees > position_size * 0.05:  # >5% fee impact
            self.activity_feed.log_fee_block(
                symbol=symbol,
                broker=final_broker,
                estimated_fees=estimated_fees,
                position_size=position_size,
                details={
                    'fee_pct': (estimated_fees / position_size) * 100,
                    'max_acceptable': 5.0
                }
            )
            return (False, final_broker, "Fee impact too high")
        
        return (True, final_broker, "Validated")
    
    def execute_trade(self, symbol: str, broker: str, side: str,
                     quantity: float, price: float, position_size: float,
                     balance: float) -> str:
        """
        Execute a trade and update visibility systems.
        
        Returns position_id if successful.
        """
        # Generate position ID
        import uuid
        position_id = f"{symbol.replace('/', '-')}_{int(time.time())}"
        
        # Log trade execution in activity feed
        self.activity_feed.log_trade_executed(
            symbol=symbol,
            broker=broker,
            side=side,
            size=position_size,
            price=price,
            details={
                'quantity': quantity,
                'position_id': position_id
            }
        )
        
        # Open position in position mirror
        self.position_mirror.open_position(
            position_id=position_id,
            symbol=symbol,
            broker=broker,
            side=side,
            entry_price=price,
            position_size=position_size,
            quantity=quantity,
            stop_loss=price * 0.97 if side == 'long' else price * 1.03,  # Example: 3% stop
            take_profit_levels={
                'tp1': price * 1.015 if side == 'long' else price * 0.985,  # 1.5%
                'tp2': price * 1.025 if side == 'long' else price * 0.975,  # 2.5%
                'tp3': price * 1.04 if side == 'long' else price * 0.96    # 4%
            },
            notes=f"Tier: {self.current_tier.value}"
        )
        
        # Check if trade should be shown prominently
        tier = get_tier_from_balance(balance)
        should_show = should_show_trade_in_feed(position_size, tier)
        if not should_show:
            print(f"Note: Trade ${position_size:.2f} below tier minimum for prominent display")
        
        return position_id
    
    def close_position(self, position_id: str, exit_price: float,
                      exit_reason: str, fees: float = 0.0):
        """
        Close a position and update visibility systems.
        """
        # Close in position mirror
        summary = self.position_mirror.close_position(
            position_id=position_id,
            exit_price=exit_price,
            exit_reason=exit_reason,
            fees=fees
        )
        
        if summary:
            # Log in activity feed
            self.activity_feed.log_position_closed(
                symbol=summary['symbol'],
                broker=summary['broker'],
                exit_reason=exit_reason,
                pnl=summary['net_pnl'],
                details={
                    'gross_pnl': summary['gross_pnl'],
                    'fees': fees,
                    'hold_time_minutes': summary['hold_time_minutes'],
                    'outcome': summary['outcome']
                }
            )
    
    def check_filter(self, symbol: str, spread: float, volume: float) -> bool:
        """
        Example filter check with activity feed logging.
        """
        # Spread check
        if spread > 0.0015:  # 0.15%
            self.activity_feed.log_filter_block(
                symbol=symbol,
                filter_name="spread_check",
                filter_reason=f"Spread {spread*100:.3f}% exceeds 0.15% maximum",
                details={
                    'spread_pct': spread * 100,
                    'max_spread_pct': 0.15
                }
            )
            return False
        
        # Volume check
        if volume < 100000:  # $100k minimum
            self.activity_feed.log_filter_block(
                symbol=symbol,
                filter_name="volume_check",
                filter_reason=f"Volume ${volume:,.0f} below $100k minimum",
                details={
                    'volume': volume,
                    'min_volume': 100000
                }
            )
            return False
        
        return True


# Example usage
if __name__ == "__main__":
    import time
    
    strategy = EnhancedTradingStrategy()
    
    print("=== Example 1: Signal Generation and Rejection ===")
    # Low confidence signal - will be rejected
    accepted = strategy.check_trading_signal(
        symbol="ETH/USD",
        side="long",
        ai_score=75.0,
        confidence=0.65,
        price=3250.0
    )
    print(f"Signal accepted: {accepted}\n")
    
    print("=== Example 2: Tier Validation and Stablecoin Routing ===")
    # Check trade with stablecoin routing
    balance = 500.0  # INCOME tier
    is_valid, broker, reason = strategy.validate_trade_before_execution(
        symbol="ETH/USDT",
        broker="coinbase",
        position_size=20.0,
        balance=balance
    )
    print(f"Trade valid: {is_valid}, Broker: {broker}, Reason: {reason}\n")
    
    print("=== Example 3: Execute Trade and Open Position ===")
    if is_valid:
        position_id = strategy.execute_trade(
            symbol="ETH/USDT",
            broker=broker,
            side="long",
            quantity=0.006,
            price=3250.0,
            position_size=20.0,
            balance=balance
        )
        print(f"Position opened: {position_id}\n")
        
        # Simulate price movement
        time.sleep(1)
        strategy.position_mirror.update_position_price(position_id, 3275.0)
        
        print("=== Example 4: Close Position ===")
        strategy.close_position(
            position_id=position_id,
            exit_price=3275.0,
            exit_reason="Take Profit 1 hit",
            fees=0.48
        )
    
    print("\n=== Example 5: Filter Block ===")
    passed = strategy.check_filter(
        symbol="XRP/USD",
        spread=0.0025,  # 0.25% - too high
        volume=50000    # Too low
    )
    print(f"Filter passed: {passed}\n")
    
    print("=== Check Activity Feed ===")
    feed = get_activity_feed()
    recent = feed.get_recent_events(n=10)
    print(f"Recent activity events: {len(recent)}")
    for event in recent:
        print(f"  - {event['message']}")
