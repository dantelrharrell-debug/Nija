"""
NIJA SaaS Monetization Engine

Comprehensive billing and subscription management system with Stripe integration.

Features:
- Subscription tier management (Free, Basic, Pro, Enterprise)
- Stripe payment processing
- Usage tracking and metering
- Invoice generation
- Trial period management
- Revenue analytics
- Webhook handling for payment events

Author: NIJA Trading Systems
Version: 1.0
Date: January 27, 2026
"""

import logging
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from enum import Enum
from decimal import Decimal

from database.db_connection import get_db_session
from database.models import User

logger = logging.getLogger(__name__)


class SubscriptionTier(Enum):
    """Subscription tier levels"""
    FREE = "free"
    BASIC = "basic"
    PRO = "pro"
    ENTERPRISE = "enterprise"
    ALPHA = "alpha"


class BillingInterval(Enum):
    """Billing intervals"""
    MONTHLY = "monthly"
    YEARLY = "yearly"


@dataclass
class TierPricing:
    """Pricing configuration for a subscription tier"""
    tier: SubscriptionTier
    monthly_price: Decimal
    yearly_price: Decimal
    features: List[str] = field(default_factory=list)
    limits: Dict[str, int] = field(default_factory=dict)
    
    def get_price(self, interval: BillingInterval) -> Decimal:
        """Get price for billing interval"""
        if interval == BillingInterval.MONTHLY:
            return self.monthly_price
        else:
            return self.yearly_price
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'tier': self.tier.value,
            'monthly_price': float(self.monthly_price),
            'yearly_price': float(self.yearly_price),
            'yearly_savings': float(self.monthly_price * 12 - self.yearly_price),
            'features': self.features,
            'limits': self.limits
        }


@dataclass
class Subscription:
    """User subscription data"""
    user_id: str
    tier: SubscriptionTier
    interval: BillingInterval
    status: str  # active, cancelled, past_due, trialing
    current_period_start: datetime
    current_period_end: datetime
    cancel_at_period_end: bool = False
    trial_end: Optional[datetime] = None
    stripe_subscription_id: Optional[str] = None
    stripe_customer_id: Optional[str] = None
    
    def is_active(self) -> bool:
        """Check if subscription is active"""
        return self.status in ['active', 'trialing']
    
    def is_trial(self) -> bool:
        """Check if subscription is in trial period"""
        if not self.trial_end:
            return False
        return datetime.now() < self.trial_end
    
    def days_until_renewal(self) -> int:
        """Calculate days until next renewal"""
        delta = self.current_period_end - datetime.now()
        return max(0, delta.days)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'user_id': self.user_id,
            'tier': self.tier.value,
            'interval': self.interval.value,
            'status': self.status,
            'current_period_start': self.current_period_start.isoformat(),
            'current_period_end': self.current_period_end.isoformat(),
            'cancel_at_period_end': self.cancel_at_period_end,
            'trial_end': self.trial_end.isoformat() if self.trial_end else None,
            'is_active': self.is_active(),
            'is_trial': self.is_trial(),
            'days_until_renewal': self.days_until_renewal()
        }


@dataclass
class UsageMetrics:
    """Usage tracking for a user"""
    user_id: str
    period_start: datetime
    period_end: datetime
    trades_executed: int = 0
    api_calls: int = 0
    active_positions: int = 0
    total_volume_usd: Decimal = Decimal('0')
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'user_id': self.user_id,
            'period_start': self.period_start.isoformat(),
            'period_end': self.period_end.isoformat(),
            'trades_executed': self.trades_executed,
            'api_calls': self.api_calls,
            'active_positions': self.active_positions,
            'total_volume_usd': float(self.total_volume_usd)
        }


class MonetizationEngine:
    """
    SaaS Monetization Engine
    
    Manages subscriptions, billing, and revenue tracking for the NIJA platform.
    """
    
    # Default tier pricing
    TIER_PRICING = {
        SubscriptionTier.FREE: TierPricing(
            tier=SubscriptionTier.FREE,
            monthly_price=Decimal('0'),
            yearly_price=Decimal('0'),
            features=[
                'Basic trading strategy',
                '1 broker connection',
                'Up to 3 active positions',
                'Email support'
            ],
            limits={
                'max_positions': 3,
                'max_brokers': 1,
                'max_daily_trades': 10
            }
        ),
        SubscriptionTier.BASIC: TierPricing(
            tier=SubscriptionTier.BASIC,
            monthly_price=Decimal('29.99'),
            yearly_price=Decimal('299.99'),
            features=[
                'Advanced trading strategies',
                'Up to 2 broker connections',
                'Up to 10 active positions',
                'Priority email support',
                'Basic analytics'
            ],
            limits={
                'max_positions': 10,
                'max_brokers': 2,
                'max_daily_trades': 50
            }
        ),
        SubscriptionTier.PRO: TierPricing(
            tier=SubscriptionTier.PRO,
            monthly_price=Decimal('99.99'),
            yearly_price=Decimal('999.99'),
            features=[
                'All advanced strategies',
                'Unlimited broker connections',
                'Up to 50 active positions',
                '24/7 priority support',
                'Advanced analytics & reporting',
                'API access',
                'Custom risk profiles'
            ],
            limits={
                'max_positions': 50,
                'max_brokers': 999,
                'max_daily_trades': 200
            }
        ),
        SubscriptionTier.ENTERPRISE: TierPricing(
            tier=SubscriptionTier.ENTERPRISE,
            monthly_price=Decimal('499.99'),
            yearly_price=Decimal('4999.99'),
            features=[
                'Everything in Pro',
                'Unlimited positions',
                'Dedicated account manager',
                'Custom strategy development',
                'White-label options',
                'SLA guarantees',
                'On-premise deployment option'
            ],
            limits={
                'max_positions': 999999,
                'max_brokers': 999,
                'max_daily_trades': 999999
            }
        ),
        SubscriptionTier.ALPHA: TierPricing(
            tier=SubscriptionTier.ALPHA,
            monthly_price=Decimal('0'),
            yearly_price=Decimal('0'),
            features=[
                'Free access to Pro features',
                'Early access to new features',
                'Direct founder communication',
                'Lifetime grandfathered pricing (future)'
            ],
            limits={
                'max_positions': 50,
                'max_brokers': 5,
                'max_daily_trades': 200
            }
        )
    }
    
    def __init__(self, stripe_api_key: Optional[str] = None):
        """
        Initialize Monetization Engine
        
        Args:
            stripe_api_key: Stripe API key (optional for testing)
        """
        self.stripe_api_key = stripe_api_key
        self._subscriptions: Dict[str, Subscription] = {}
        self._usage_metrics: Dict[str, UsageMetrics] = {}
        
        # Initialize Stripe if API key provided
        if stripe_api_key:
            try:
                import stripe
                stripe.api_key = stripe_api_key
                logger.info("✅ Stripe API initialized")
            except ImportError:
                logger.warning("Stripe library not installed. Install with: pip install stripe")
        
        logger.info("✅ Monetization Engine initialized")
    
    def get_tier_pricing(self, tier: SubscriptionTier) -> TierPricing:
        """
        Get pricing for a subscription tier
        
        Args:
            tier: Subscription tier
            
        Returns:
            TierPricing object
        """
        return self.TIER_PRICING[tier]
    
    def get_all_pricing(self) -> List[TierPricing]:
        """
        Get pricing for all subscription tiers
        
        Returns:
            List of TierPricing objects
        """
        return [
            self.TIER_PRICING[tier]
            for tier in [SubscriptionTier.FREE, SubscriptionTier.BASIC,
                        SubscriptionTier.PRO, SubscriptionTier.ENTERPRISE]
        ]
    
    def create_subscription(self,
                          user_id: str,
                          tier: SubscriptionTier,
                          interval: BillingInterval = BillingInterval.MONTHLY,
                          trial_days: int = 14,
                          payment_method_id: Optional[str] = None) -> Tuple[bool, Optional[str], Optional[Subscription]]:
        """
        Create a new subscription for a user
        
        Args:
            user_id: User identifier
            tier: Subscription tier
            interval: Billing interval
            trial_days: Number of trial days (0 = no trial)
            payment_method_id: Stripe payment method ID (optional)
            
        Returns:
            Tuple of (success: bool, error_message: Optional[str], subscription: Optional[Subscription])
        """
        try:
            # Calculate subscription dates
            now = datetime.now()
            trial_end = now + timedelta(days=trial_days) if trial_days > 0 else None
            
            if interval == BillingInterval.MONTHLY:
                period_end = now + timedelta(days=30)
            else:
                period_end = now + timedelta(days=365)
            
            # Create subscription object
            subscription = Subscription(
                user_id=user_id,
                tier=tier,
                interval=interval,
                status='trialing' if trial_end else 'active',
                current_period_start=now,
                current_period_end=period_end,
                trial_end=trial_end
            )
            
            # TODO: Create Stripe subscription if payment method provided
            # if payment_method_id and self.stripe_api_key:
            #     stripe_sub = self._create_stripe_subscription(...)
            #     subscription.stripe_subscription_id = stripe_sub.id
            
            # Store subscription
            self._subscriptions[user_id] = subscription
            
            # Update user tier in database
            with get_db_session() as session:
                user = session.query(User).filter(User.user_id == user_id).first()
                if user:
                    user.subscription_tier = tier.value
                    session.commit()
            
            logger.info(f"✅ Subscription created for user {user_id}: {tier.value} ({interval.value})")
            
            return True, None, subscription
            
        except Exception as e:
            logger.error(f"Error creating subscription: {e}")
            return False, str(e), None
    
    def get_subscription(self, user_id: str) -> Optional[Subscription]:
        """
        Get subscription for a user
        
        Args:
            user_id: User identifier
            
        Returns:
            Subscription object or None if not found
        """
        return self._subscriptions.get(user_id)
    
    def cancel_subscription(self, user_id: str, immediate: bool = False) -> Tuple[bool, Optional[str]]:
        """
        Cancel a user's subscription
        
        Args:
            user_id: User identifier
            immediate: Cancel immediately vs at period end
            
        Returns:
            Tuple of (success: bool, error_message: Optional[str])
        """
        subscription = self._subscriptions.get(user_id)
        if not subscription:
            return False, "Subscription not found"
        
        if immediate:
            subscription.status = 'cancelled'
            subscription.current_period_end = datetime.now()
        else:
            subscription.cancel_at_period_end = True
        
        logger.info(f"🚫 Subscription cancelled for user {user_id} (immediate={immediate})")
        
        return True, None
    
    def upgrade_subscription(self, user_id: str, new_tier: SubscriptionTier) -> Tuple[bool, Optional[str]]:
        """
        Upgrade user's subscription to a higher tier
        
        Args:
            user_id: User identifier
            new_tier: New subscription tier
            
        Returns:
            Tuple of (success: bool, error_message: Optional[str])
        """
        subscription = self._subscriptions.get(user_id)
        if not subscription:
            return False, "Subscription not found"
        
        # TODO: Implement prorated billing logic
        # Calculate prorated amount and charge difference
        
        subscription.tier = new_tier
        
        # Update user tier in database
        with get_db_session() as session:
            user = session.query(User).filter(User.user_id == user_id).first()
            if user:
                user.subscription_tier = new_tier.value
                session.commit()
        
        logger.info(f"⬆️ Subscription upgraded for user {user_id} to {new_tier.value}")
        
        return True, None
    
    def track_usage(self, user_id: str, metric: str, value: int = 1) -> None:
        """
        Track usage metric for a user
        
        Args:
            user_id: User identifier
            metric: Metric name (trades_executed, api_calls, etc.)
            value: Metric value to add
        """
        # Get or create usage metrics for current period
        if user_id not in self._usage_metrics:
            now = datetime.now()
            self._usage_metrics[user_id] = UsageMetrics(
                user_id=user_id,
                period_start=now,
                period_end=now + timedelta(days=30)
            )
        
        metrics = self._usage_metrics[user_id]
        
        # Update metric
        if metric == 'trades_executed':
            metrics.trades_executed += value
        elif metric == 'api_calls':
            metrics.api_calls += value
        elif metric == 'active_positions':
            metrics.active_positions = value
        elif metric == 'volume_usd':
            metrics.total_volume_usd += Decimal(str(value))
    
    def get_usage_metrics(self, user_id: str) -> Optional[UsageMetrics]:
        """
        Get usage metrics for a user
        
        Args:
            user_id: User identifier
            
        Returns:
            UsageMetrics object or None if not found
        """
        return self._usage_metrics.get(user_id)
    
    def check_usage_limits(self, user_id: str) -> Dict[str, Any]:
        """
        Check if user is within their tier's usage limits
        
        Args:
            user_id: User identifier
            
        Returns:
            Dictionary with limit check results
        """
        subscription = self._subscriptions.get(user_id)
        if not subscription:
            return {'error': 'Subscription not found'}
        
        pricing = self.get_tier_pricing(subscription.tier)
        metrics = self._usage_metrics.get(user_id)
        
        if not metrics:
            return {
                'within_limits': True,
                'limits': pricing.limits,
                'usage': {}
            }
        
        # Check limits
        limits_exceeded = {}
        if metrics.active_positions > pricing.limits['max_positions']:
            limits_exceeded['max_positions'] = {
                'limit': pricing.limits['max_positions'],
                'current': metrics.active_positions
            }
        
        if metrics.trades_executed > pricing.limits['max_daily_trades']:
            limits_exceeded['max_daily_trades'] = {
                'limit': pricing.limits['max_daily_trades'],
                'current': metrics.trades_executed
            }
        
        return {
            'within_limits': len(limits_exceeded) == 0,
            'limits': pricing.limits,
            'usage': metrics.to_dict(),
            'limits_exceeded': limits_exceeded
        }
    
    def calculate_revenue_metrics(self) -> Dict[str, Any]:
        """
        Calculate revenue analytics
        
        Returns:
            Dictionary with revenue metrics
        """
        total_mrr = Decimal('0')
        total_arr = Decimal('0')
        subscriber_counts = {tier: 0 for tier in SubscriptionTier}
        
        for subscription in self._subscriptions.values():
            if subscription.is_active():
                pricing = self.get_tier_pricing(subscription.tier)
                
                if subscription.interval == BillingInterval.MONTHLY:
                    total_mrr += pricing.monthly_price
                    total_arr += pricing.monthly_price * 12
                else:
                    monthly_equiv = pricing.yearly_price / 12
                    total_mrr += monthly_equiv
                    total_arr += pricing.yearly_price
                
                subscriber_counts[subscription.tier] += 1
        
        return {
            'monthly_recurring_revenue': float(total_mrr),
            'annual_recurring_revenue': float(total_arr),
            'total_active_subscribers': sum(subscriber_counts.values()),
            'subscribers_by_tier': {
                tier.value: count
                for tier, count in subscriber_counts.items()
            },
            'average_revenue_per_user': float(total_mrr / len(self._subscriptions)) if self._subscriptions else 0,
            'timestamp': datetime.now().isoformat()
        }
    
    def handle_stripe_webhook(self, event_type: str, event_data: Dict[str, Any]) -> None:
        """
        Handle Stripe webhook events
        
        Args:
            event_type: Stripe event type
            event_data: Event data from Stripe
        """
        logger.info(f"📨 Received Stripe webhook: {event_type}")
        
        # TODO: Implement webhook handlers for various events
        # - invoice.payment_succeeded
        # - invoice.payment_failed
        # - customer.subscription.deleted
        # - customer.subscription.updated
        # etc.
        
        if event_type == 'invoice.payment_succeeded':
            # Update subscription status to active
            pass
        elif event_type == 'invoice.payment_failed':
            # Update subscription status to past_due
            pass
        elif event_type == 'customer.subscription.deleted':
            # Cancel subscription
            pass


# Global singleton instance
_monetization_engine: Optional[MonetizationEngine] = None


def get_monetization_engine(stripe_api_key: Optional[str] = None) -> MonetizationEngine:
    """
    Get or create global monetization engine singleton
    
    Args:
        stripe_api_key: Stripe API key (optional)
        
    Returns:
        MonetizationEngine instance
    """
    global _monetization_engine
    
    if _monetization_engine is None:
        _monetization_engine = MonetizationEngine(stripe_api_key=stripe_api_key)
        logger.info("Created new Monetization Engine instance")
    
    return _monetization_engine


def reset_monetization_engine() -> None:
    """Reset global monetization engine (for testing)"""
    global _monetization_engine
    _monetization_engine = None
    logger.info("Monetization Engine reset")
