"""
NIJA Revenue Tracking System

Tracks multiple revenue streams for the SaaS platform:
1. Subscription fees (monthly/annual)
2. Performance fees (% of profits)
3. Copy trading fees (% of follower profits)

How NIJA Becomes a Money Machine:

┌─────────────────────────────────────────────────────────────┐
│ Revenue Stream 1: Subscriptions                             │
│ - STARTER: $19/mo → $228/year                              │
│ - SAVER: $49/mo → $588/year                                │
│ - INVESTOR: $99/mo → $1,188/year                           │
│ - INCOME: $249/mo → $2,988/year                            │
│ - LIVABLE: $499/mo → $5,988/year                           │
│ - BALLER: $999/mo → $11,988/year                           │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ Revenue Stream 2: Performance Fees                          │
│ - Take 10% of all profits above high water mark            │
│ - User wins $1,000 → Platform earns $100                   │
│ - Incentive alignment: platform wins when users win        │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ Revenue Stream 3: Copy Trading Fees                         │
│ - Master traders earn 5% of follower profits               │
│ - Platform earns 2% facilitation fee                       │
│ - 1,000 followers @ $50 profit each = $1,000 platform fee  │
└─────────────────────────────────────────────────────────────┘

Author: NIJA Trading Systems
Version: 1.0
Date: January 27, 2026
"""

import logging
from enum import Enum
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

logger = logging.getLogger("nija.revenue")


class SubscriptionTier(Enum):
    """Subscription tiers with pricing."""
    STARTER = ("STARTER", 19.00, "Entry level learning")
    SAVER = ("SAVER", 49.00, "Capital protection mode")
    INVESTOR = ("INVESTOR", 99.00, "Multi-position trading")
    INCOME = ("INCOME", 249.00, "Full AI trading")
    LIVABLE = ("LIVABLE", 499.00, "Pro-style scaling")
    BALLER = ("BALLER", 999.00, "Institutional mode")
    
    def __init__(self, tier_name: str, monthly_price: float, description: str):
        self.tier_name = tier_name
        self.monthly_price = monthly_price
        self.annual_price = monthly_price * 12 * 0.80  # 20% discount
        self.description = description


class RevenueType(Enum):
    """Types of revenue."""
    SUBSCRIPTION = "subscription"
    PERFORMANCE_FEE = "performance_fee"
    COPY_TRADING_FEE = "copy_trading_fee"


@dataclass
class RevenueEvent:
    """A revenue event."""
    user_id: str
    revenue_type: RevenueType
    amount: Decimal
    timestamp: datetime
    description: str
    metadata: Dict = None


class RevenueTracker:
    """
    Tracks all revenue streams for the platform.
    
    Features:
    - Subscription revenue tracking
    - Performance fee calculation
    - Copy trading fee tracking
    - Revenue analytics and reporting
    """
    
    # Performance fee configuration
    PERFORMANCE_FEE_PCT = 10.0  # 10% of profits
    COPY_TRADING_PLATFORM_FEE_PCT = 2.0  # 2% platform fee
    COPY_TRADING_MASTER_FEE_PCT = 5.0  # 5% to master trader
    
    def __init__(self):
        """Initialize revenue tracker."""
        self.revenue_events: List[RevenueEvent] = []
        self.high_water_marks: Dict[str, Decimal] = {}  # user_id -> peak equity
        
        logger.info("RevenueTracker initialized")
    
    def record_subscription(
        self,
        user_id: str,
        tier: SubscriptionTier,
        is_annual: bool = False
    ) -> RevenueEvent:
        """
        Record a subscription payment.
        
        Args:
            user_id: User ID
            tier: Subscription tier
            is_annual: Whether it's an annual subscription
            
        Returns:
            RevenueEvent
        """
        amount = Decimal(str(tier.annual_price if is_annual else tier.monthly_price))
        
        event = RevenueEvent(
            user_id=user_id,
            revenue_type=RevenueType.SUBSCRIPTION,
            amount=amount,
            timestamp=datetime.now(),
            description=f"{tier.tier_name} subscription ({'annual' if is_annual else 'monthly'})",
            metadata={
                "tier": tier.tier_name,
                "is_annual": is_annual
            }
        )
        
        self.revenue_events.append(event)
        logger.info(f"Subscription recorded: user={user_id}, tier={tier.tier_name}, amount=${amount}")
        
        return event
    
    def record_performance_fee(
        self,
        user_id: str,
        profit: float,
        current_equity: float
    ) -> Optional[RevenueEvent]:
        """
        Record a performance fee (10% of profits above high water mark).
        
        Args:
            user_id: User ID
            profit: Realized profit from a trade
            current_equity: Current account equity
            
        Returns:
            RevenueEvent if fee charged, None if below high water mark
        """
        current_equity_decimal = Decimal(str(current_equity))
        
        # Get or initialize high water mark
        if user_id not in self.high_water_marks:
            self.high_water_marks[user_id] = current_equity_decimal
            # No fee on first profit
            return None
        
        high_water_mark = self.high_water_marks[user_id]
        
        # Only charge fees if above previous peak
        if current_equity_decimal > high_water_mark:
            # Calculate fee on new profit above high water mark
            new_profit = current_equity_decimal - high_water_mark
            fee_amount = new_profit * Decimal(str(self.PERFORMANCE_FEE_PCT / 100.0))
            
            # Update high water mark
            self.high_water_marks[user_id] = current_equity_decimal
            
            event = RevenueEvent(
                user_id=user_id,
                revenue_type=RevenueType.PERFORMANCE_FEE,
                amount=fee_amount,
                timestamp=datetime.now(),
                description=f"Performance fee: {self.PERFORMANCE_FEE_PCT}% of ${new_profit}",
                metadata={
                    "profit": float(new_profit),
                    "fee_pct": self.PERFORMANCE_FEE_PCT,
                    "high_water_mark": float(high_water_mark),
                    "new_high_water_mark": float(current_equity_decimal)
                }
            )
            
            self.revenue_events.append(event)
            logger.info(
                f"Performance fee recorded: user={user_id}, "
                f"profit=${new_profit}, fee=${fee_amount}"
            )
            
            return event
        
        return None
    
    def record_copy_trading_fee(
        self,
        master_user_id: str,
        follower_user_id: str,
        follower_profit: float
    ) -> Tuple[RevenueEvent, RevenueEvent]:
        """
        Record copy trading fees.
        
        Splits follower profit:
        - 5% to master trader
        - 2% to platform
        - 93% to follower
        
        Args:
            master_user_id: Master trader user ID
            follower_user_id: Follower user ID
            follower_profit: Profit made by follower
            
        Returns:
            Tuple of (platform_fee_event, master_fee_event)
        """
        profit_decimal = Decimal(str(follower_profit))
        
        # Platform fee (2%)
        platform_fee = profit_decimal * Decimal(str(self.COPY_TRADING_PLATFORM_FEE_PCT / 100.0))
        
        platform_event = RevenueEvent(
            user_id=follower_user_id,
            revenue_type=RevenueType.COPY_TRADING_FEE,
            amount=platform_fee,
            timestamp=datetime.now(),
            description=f"Copy trading platform fee: {self.COPY_TRADING_PLATFORM_FEE_PCT}% of follower profit",
            metadata={
                "master_user_id": master_user_id,
                "follower_user_id": follower_user_id,
                "follower_profit": follower_profit,
                "fee_pct": self.COPY_TRADING_PLATFORM_FEE_PCT
            }
        )
        
        # Master trader fee (5%) - not counted as platform revenue but tracked
        master_fee = profit_decimal * Decimal(str(self.COPY_TRADING_MASTER_FEE_PCT / 100.0))
        
        master_event = RevenueEvent(
            user_id=master_user_id,
            revenue_type=RevenueType.COPY_TRADING_FEE,
            amount=master_fee,
            timestamp=datetime.now(),
            description=f"Master trader fee: {self.COPY_TRADING_MASTER_FEE_PCT}% of follower profit",
            metadata={
                "master_user_id": master_user_id,
                "follower_user_id": follower_user_id,
                "follower_profit": follower_profit,
                "fee_pct": self.COPY_TRADING_MASTER_FEE_PCT,
                "is_master_payout": True  # This goes to master, not platform
            }
        )
        
        self.revenue_events.append(platform_event)
        self.revenue_events.append(master_event)
        
        logger.info(
            f"Copy trading fees recorded: platform=${platform_fee}, "
            f"master=${master_fee}, follower_profit=${follower_profit}"
        )
        
        return (platform_event, master_event)
    
    def get_total_revenue(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        revenue_type: Optional[RevenueType] = None
    ) -> Decimal:
        """
        Get total revenue for a period.
        
        Args:
            start_date: Start date (optional)
            end_date: End date (optional)
            revenue_type: Filter by revenue type (optional)
            
        Returns:
            Total revenue as Decimal
        """
        total = Decimal("0")
        
        for event in self.revenue_events:
            # Date filter
            if start_date and event.timestamp < start_date:
                continue
            if end_date and event.timestamp > end_date:
                continue
            
            # Type filter
            if revenue_type and event.revenue_type != revenue_type:
                continue
            
            # Skip master payouts (not platform revenue)
            if event.metadata and event.metadata.get("is_master_payout"):
                continue
            
            total += event.amount
        
        return total
    
    def get_revenue_by_type(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> Dict[RevenueType, Decimal]:
        """
        Get revenue breakdown by type.
        
        Args:
            start_date: Start date (optional)
            end_date: End date (optional)
            
        Returns:
            Dictionary mapping RevenueType to total amount
        """
        breakdown = {
            RevenueType.SUBSCRIPTION: Decimal("0"),
            RevenueType.PERFORMANCE_FEE: Decimal("0"),
            RevenueType.COPY_TRADING_FEE: Decimal("0")
        }
        
        for event in self.revenue_events:
            # Date filter
            if start_date and event.timestamp < start_date:
                continue
            if end_date and event.timestamp > end_date:
                continue
            
            # Skip master payouts
            if event.metadata and event.metadata.get("is_master_payout"):
                continue
            
            breakdown[event.revenue_type] += event.amount
        
        return breakdown
    
    def get_monthly_recurring_revenue(self) -> Decimal:
        """
        Calculate Monthly Recurring Revenue (MRR) from subscriptions.
        
        Returns:
            MRR as Decimal
        """
        # Get subscription events from last 30 days
        thirty_days_ago = datetime.now() - timedelta(days=30)
        
        mrr = Decimal("0")
        
        for event in self.revenue_events:
            if event.revenue_type == RevenueType.SUBSCRIPTION:
                if event.timestamp >= thirty_days_ago:
                    # Convert annual to monthly
                    if event.metadata and event.metadata.get("is_annual"):
                        mrr += event.amount / Decimal("12")
                    else:
                        mrr += event.amount
        
        return mrr
    
    def get_annual_recurring_revenue(self) -> Decimal:
        """
        Calculate Annual Recurring Revenue (ARR).
        
        Returns:
            ARR as Decimal
        """
        return self.get_monthly_recurring_revenue() * Decimal("12")
    
    def get_revenue_summary(self) -> Dict:
        """
        Get comprehensive revenue summary.
        
        Returns:
            Dictionary with revenue metrics
        """
        # All-time totals
        total_revenue = self.get_total_revenue()
        revenue_by_type = self.get_revenue_by_type()
        
        # Monthly/Annual recurring
        mrr = self.get_monthly_recurring_revenue()
        arr = self.get_annual_recurring_revenue()
        
        # Last 30 days
        thirty_days_ago = datetime.now() - timedelta(days=30)
        revenue_30d = self.get_total_revenue(start_date=thirty_days_ago)
        
        return {
            "total_revenue": float(total_revenue),
            "revenue_by_type": {
                k.value: float(v) for k, v in revenue_by_type.items()
            },
            "mrr": float(mrr),
            "arr": float(arr),
            "revenue_last_30_days": float(revenue_30d),
            "total_events": len(self.revenue_events),
            "active_users": len(self.high_water_marks)
        }


# Global revenue tracker instance
_revenue_tracker = None


def get_revenue_tracker() -> RevenueTracker:
    """Get global revenue tracker instance."""
    global _revenue_tracker
    if _revenue_tracker is None:
        _revenue_tracker = RevenueTracker()
    return _revenue_tracker
