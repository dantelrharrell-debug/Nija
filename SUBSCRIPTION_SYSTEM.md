# NIJA Subscription System - Complete Specification

**Version:** 2.0  
**Last Updated:** January 29, 2026  
**Payment Provider:** Stripe

---

## Table of Contents

1. [Overview](#overview)
2. [Subscription Tiers](#subscription-tiers)
3. [Pricing Strategy](#pricing-strategy)
4. [Stripe Integration](#stripe-integration)
5. [Usage Tracking](#usage-tracking)
6. [Trial Management](#trial-management)
7. [Billing Logic](#billing-logic)
8. [Upgrade/Downgrade Flow](#upgradedowngrade-flow)
9. [Cancellation & Refunds](#cancellation--refunds)
10. [Revenue Analytics](#revenue-analytics)

---

## Overview

NIJA operates on a **freemium SaaS subscription model** with four tiers:
- **Free**: Paper trading only
- **Basic**: Live trading with core features
- **Pro**: Advanced AI features (most popular)
- **Enterprise**: Full feature set + white-label

### Key Features

- ✅ 14-day Pro trial for all new users
- ✅ Monthly and yearly billing (20% discount on yearly)
- ✅ Prorated upgrades/downgrades
- ✅ Grandfathered pricing for early adopters
- ✅ Usage-based limits (positions, trades, API calls)
- ✅ Stripe-powered billing automation

---

## Subscription Tiers

### Free Tier

```python
FREE_TIER = {
    'tier_id': 'free',
    'name': 'Free',
    'price_monthly_usd': 0,
    'price_yearly_usd': 0,
    'trial_days': 0,
    
    'features': [
        'Paper trading only',
        'APEX V7.2 strategy',
        '1 exchange connection',
        'Community support (Discord)',
        'Basic analytics'
    ],
    
    'limits': {
        'max_position_size_usd': 0,  # Paper trading only
        'max_concurrent_positions': 3,
        'max_daily_trades': 10,
        'max_brokers': 1,
        'api_calls_per_minute': 10,
        'data_retention_days': 30,
        'support_response_hours': 72,
    },
    
    'disabled_features': [
        'live_trading',
        'meta_ai',
        'mmin',
        'gmig',
        'custom_risk_profiles',
        'tradingview_webhooks',
        'api_access',
        'priority_support'
    ]
}
```

**Target Audience:**
- New users exploring the platform
- Paper traders learning strategies
- Users with small accounts (<$500)

---

### Basic Tier

```python
BASIC_TIER = {
    'tier_id': 'basic',
    'name': 'Basic',
    'price_monthly_usd': 49,
    'price_yearly_usd': 470,  # $39.17/month (~20% savings)
    'stripe_price_id_monthly': 'price_basic_monthly',
    'stripe_price_id_yearly': 'price_basic_yearly',
    'trial_days': 14,  # New users get 14-day Pro trial
    
    'features': [
        'Live trading',
        'APEX V7.2 strategy',
        '2 exchange connections',
        'Email support (48h response)',
        'Standard analytics',
        'Mobile app access',
        'Trade history export',
        'Email notifications'
    ],
    
    'limits': {
        'max_position_size_usd': 500,
        'max_concurrent_positions': 5,
        'max_daily_trades': 30,
        'max_brokers': 2,
        'api_calls_per_minute': 30,
        'data_retention_days': 90,
        'support_response_hours': 48,
    },
    
    'enabled_features': [
        'live_trading',
        'mobile_app',
        'email_support',
        'export_data'
    ]
}
```

**Target Audience:**
- Individual traders with $1K-$10K accounts
- Part-time traders
- Users wanting live trading basics

**Conversion Strategy:**
- Ideal for users downgrading from trial
- Entry point for live trading

---

### Pro Tier (Most Popular)

```python
PRO_TIER = {
    'tier_id': 'pro',
    'name': 'Pro',
    'price_monthly_usd': 149,
    'price_yearly_usd': 1430,  # $119.17/month (~20% savings)
    'stripe_price_id_monthly': 'price_pro_monthly',
    'stripe_price_id_yearly': 'price_pro_yearly',
    'trial_days': 14,
    'popular': True,  # Display "Most Popular" badge
    
    'features': [
        'All Basic features',
        'Meta-AI strategy optimization',
        'MMIN multi-market intelligence',
        '5 exchange connections',
        'Priority email support (24h response)',
        'Advanced analytics & reports',
        'Custom risk profiles',
        'TradingView webhook integration',
        'Daily/weekly reports',
        'Performance comparison tools'
    ],
    
    'limits': {
        'max_position_size_usd': 2000,
        'max_concurrent_positions': 10,
        'max_daily_trades': 100,
        'max_brokers': 5,
        'api_calls_per_minute': 100,
        'data_retention_days': 365,
        'support_response_hours': 24,
    },
    
    'enabled_features': [
        'live_trading',
        'meta_ai',
        'mmin',
        'custom_risk_profiles',
        'tradingview_webhooks',
        'priority_support',
        'advanced_analytics',
        'mobile_app'
    ]
}
```

**Target Audience:**
- Serious traders with $10K-$100K accounts
- Full-time/professional traders
- Users wanting advanced AI features

**Value Proposition:**
- Meta-AI can increase returns by 10-15%
- MMIN provides cross-market edge
- Priority support reduces downtime
- ROI typically >10x subscription cost

---

### Enterprise Tier

```python
ENTERPRISE_TIER = {
    'tier_id': 'enterprise',
    'name': 'Enterprise',
    'price_monthly_usd': 499,
    'price_yearly_usd': 4790,  # $399.17/month (~20% savings)
    'stripe_price_id_monthly': 'price_enterprise_monthly',
    'stripe_price_id_yearly': 'price_enterprise_yearly',
    'trial_days': 14,
    'contact_sales': True,  # Option for custom pricing
    
    'features': [
        'All Pro features',
        'GMIG global macro intelligence',
        'Unlimited exchange connections',
        'Dedicated account manager',
        'Custom strategy tuning',
        'Full API access',
        'White-label option',
        'Multi-account management',
        'Custom integrations',
        'SLA guarantee (99.9% uptime)',
        'Phone support',
        'Custom reporting'
    ],
    
    'limits': {
        'max_position_size_usd': 10000,
        'max_concurrent_positions': 50,
        'max_daily_trades': 500,
        'max_brokers': -1,  # Unlimited
        'api_calls_per_minute': 500,
        'data_retention_days': -1,  # Unlimited
        'support_response_hours': 4,  # 4-hour SLA
    },
    
    'enabled_features': [
        'live_trading',
        'meta_ai',
        'mmin',
        'gmig',
        'custom_risk_profiles',
        'tradingview_webhooks',
        'api_access',
        'white_label',
        'multi_account',
        'dedicated_support',
        'custom_integrations',
        'sla_guarantee'
    ]
}
```

**Target Audience:**
- Hedge funds / prop trading firms
- High-net-worth individuals ($100K+ accounts)
- Trading teams
- White-label partners

**Value Proposition:**
- GMIG macro intelligence for institutional-grade insights
- API access for custom integrations
- White-label for firms wanting branded solution
- Dedicated support minimizes operational risk

---

## Pricing Strategy

### Pricing Rationale

**Basic ($49/month):**
- Target: 3-5% monthly return on $10K account = $300-$500
- ROI: 6-10x subscription cost
- Competitive: Other algo trading bots charge $99-$199

**Pro ($149/month):**
- Target: 3-5% monthly return on $30K account = $900-$1,500
- ROI: 6-10x subscription cost
- Meta-AI adds ~10% to returns → extra $300/month value
- Price anchored between Basic and Enterprise

**Enterprise ($499/month):**
- Target: Institutional accounts ($100K+)
- Dedicated support cost justifies premium
- White-label adds significant value
- Custom pricing available for very large accounts

### Discount Strategy

**Yearly Discount (20%):**
- Encourages annual commitment (improves LTV)
- Reduces churn (harder to cancel annual)
- Cash flow benefit (upfront payment)

**Special Promotions:**
- Launch discount: 30% off first 3 months (limited time)
- Referral program: 1 month free for referrer + referee
- Annual subscription bonus: 2 months free (16.7% discount)
- Black Friday: 40% off yearly plans

---

## Stripe Integration

### Setup

```python
import stripe
from config import STRIPE_SECRET_KEY

stripe.api_key = STRIPE_SECRET_KEY

# Create Stripe products (one-time setup)
def create_stripe_products():
    # Basic - Monthly
    basic_monthly = stripe.Price.create(
        unit_amount=4900,  # $49.00
        currency="usd",
        recurring={"interval": "month"},
        product_data={
            "name": "NIJA Basic - Monthly",
            "description": "Live trading with core features"
        }
    )
    
    # Basic - Yearly
    basic_yearly = stripe.Price.create(
        unit_amount=47000,  # $470.00
        currency="usd",
        recurring={"interval": "year"},
        product_data={
            "name": "NIJA Basic - Yearly",
            "description": "Live trading with core features (Save 20%)"
        }
    )
    
    # Pro - Monthly
    pro_monthly = stripe.Price.create(
        unit_amount=14900,  # $149.00
        currency="usd",
        recurring={"interval": "month"},
        product_data={
            "name": "NIJA Pro - Monthly",
            "description": "Advanced AI features and analytics"
        }
    )
    
    # Pro - Yearly
    pro_yearly = stripe.Price.create(
        unit_amount=143000,  # $1,430.00
        currency="usd",
        recurring={"interval": "year"},
        product_data={
            "name": "NIJA Pro - Yearly",
            "description": "Advanced AI features and analytics (Save 20%)"
        }
    )
    
    # Enterprise - Monthly
    enterprise_monthly = stripe.Price.create(
        unit_amount=49900,  # $499.00
        currency="usd",
        recurring={"interval": "month"},
        product_data={
            "name": "NIJA Enterprise - Monthly",
            "description": "Full feature set with dedicated support"
        }
    )
    
    # Enterprise - Yearly
    enterprise_yearly = stripe.Price.create(
        unit_amount=479000,  # $4,790.00
        currency="usd",
        recurring={"interval": "year"},
        product_data={
            "name": "NIJA Enterprise - Yearly",
            "description": "Full feature set with dedicated support (Save 20%)"
        }
    )
```

### Create Subscription

```python
from monetization_engine import SubscriptionEngine

sub_engine = SubscriptionEngine()

def create_subscription(user_id, tier, interval, payment_method_id):
    # Create or retrieve Stripe customer
    customer = stripe.Customer.create(
        email=user.email,
        payment_method=payment_method_id,
        invoice_settings={
            "default_payment_method": payment_method_id
        }
    )
    
    # Get price ID based on tier and interval
    price_id = get_price_id(tier, interval)
    
    # Create subscription with trial period
    subscription = stripe.Subscription.create(
        customer=customer.id,
        items=[{"price": price_id}],
        trial_period_days=14 if tier != 'free' else 0,
        expand=["latest_invoice.payment_intent"]
    )
    
    # Store subscription in database
    sub_engine.store_subscription(
        user_id=user_id,
        stripe_subscription_id=subscription.id,
        stripe_customer_id=customer.id,
        tier=tier,
        interval=interval,
        status='trialing',
        current_period_start=subscription.current_period_start,
        current_period_end=subscription.current_period_end,
        trial_end=subscription.trial_end
    )
    
    return subscription
```

### Webhook Handler

```python
from fastapi import Request, HTTPException
import stripe

@app.post("/webhooks/stripe")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")
    
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, STRIPE_WEBHOOK_SECRET
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid signature")
    
    # Handle different event types
    if event['type'] == 'invoice.payment_succeeded':
        handle_payment_succeeded(event['data']['object'])
    
    elif event['type'] == 'invoice.payment_failed':
        handle_payment_failed(event['data']['object'])
    
    elif event['type'] == 'customer.subscription.updated':
        handle_subscription_updated(event['data']['object'])
    
    elif event['type'] == 'customer.subscription.deleted':
        handle_subscription_deleted(event['data']['object'])
    
    elif event['type'] == 'customer.subscription.trial_will_end':
        handle_trial_ending(event['data']['object'])
    
    return {"status": "success"}

def handle_payment_succeeded(invoice):
    # Activate or renew subscription
    subscription_id = invoice['subscription']
    sub = sub_engine.get_subscription_by_stripe_id(subscription_id)
    sub_engine.activate_subscription(sub.user_id)
    
    # Send receipt email
    send_receipt_email(sub.user_id, invoice)

def handle_payment_failed(invoice):
    # Suspend account
    subscription_id = invoice['subscription']
    sub = sub_engine.get_subscription_by_stripe_id(subscription_id)
    sub_engine.suspend_subscription(sub.user_id)
    
    # Send payment failure email
    send_payment_failed_email(sub.user_id, invoice)

def handle_trial_ending(subscription):
    # Send trial ending reminder (3 days before)
    user_id = sub_engine.get_user_by_stripe_subscription(subscription.id)
    send_trial_ending_email(user_id, days_remaining=3)
```

---

## Usage Tracking

### Tracked Metrics

```python
from database.models import UsageMetrics

class UsageTracker:
    def __init__(self, user_id):
        self.user_id = user_id
        self.subscription = get_user_subscription(user_id)
        self.limits = get_tier_limits(self.subscription.tier)
    
    def track_api_call(self):
        # Increment API call counter
        metrics = get_current_period_metrics(self.user_id)
        metrics.api_calls += 1
        
        # Check rate limit
        calls_per_minute = get_calls_last_minute(self.user_id)
        if calls_per_minute > self.limits['api_calls_per_minute']:
            raise RateLimitExceeded(
                f"Rate limit exceeded: {self.limits['api_calls_per_minute']}/min"
            )
        
        db.session.commit()
    
    def track_trade_executed(self):
        # Increment trade counter
        metrics = get_current_period_metrics(self.user_id)
        metrics.trades_executed += 1
        
        # Check daily limit
        trades_today = get_trades_today(self.user_id)
        if trades_today > self.limits['max_daily_trades']:
            raise TradeLimitExceeded(
                f"Daily trade limit exceeded: {self.limits['max_daily_trades']}"
            )
        
        db.session.commit()
    
    def track_position_opened(self):
        # Increment position counter
        metrics = get_current_period_metrics(self.user_id)
        metrics.positions_opened += 1
        
        # Check concurrent positions
        active_positions = get_active_positions_count(self.user_id)
        if active_positions > self.limits['max_concurrent_positions']:
            raise PositionLimitExceeded(
                f"Max concurrent positions exceeded: {self.limits['max_concurrent_positions']}"
            )
        
        db.session.commit()
    
    def get_usage_summary(self):
        metrics = get_current_period_metrics(self.user_id)
        
        return {
            'period_start': metrics.period_start,
            'period_end': metrics.period_end,
            'api_calls': metrics.api_calls,
            'api_calls_limit': self.limits['api_calls_per_minute'] * 60 * 24 * 30,
            'trades_executed': metrics.trades_executed,
            'trades_limit': self.limits['max_daily_trades'] * 30,
            'positions_opened': metrics.positions_opened,
            'max_concurrent_positions': metrics.max_concurrent_positions,
            'max_concurrent_positions_limit': self.limits['max_concurrent_positions'],
            'brokers_connected': metrics.brokers_connected,
            'brokers_limit': self.limits['max_brokers'],
            'overage': False,  # Future: implement overage billing
            'warnings': self._generate_warnings(metrics)
        }
    
    def _generate_warnings(self, metrics):
        warnings = []
        
        # API calls warning
        api_limit = self.limits['api_calls_per_minute'] * 60 * 24 * 30
        if metrics.api_calls > api_limit * 0.8:
            warnings.append({
                'type': 'api_calls',
                'message': 'Approaching API call limit (80%)',
                'action': 'Consider upgrading to higher tier'
            })
        
        # Trades warning
        trades_limit = self.limits['max_daily_trades'] * 30
        if metrics.trades_executed > trades_limit * 0.8:
            warnings.append({
                'type': 'trades',
                'message': 'Approaching monthly trade limit (80%)',
                'action': 'Consider upgrading to higher tier'
            })
        
        return warnings
```

---

## Trial Management

### Trial Flow

```python
from datetime import datetime, timedelta

class TrialManager:
    def __init__(self):
        self.default_trial_days = 14
        self.trial_tier = 'pro'  # All trials are Pro tier
    
    def start_trial(self, user_id):
        # Create trial subscription
        trial_end = datetime.now() + timedelta(days=self.default_trial_days)
        
        subscription = Subscription(
            user_id=user_id,
            tier=self.trial_tier,
            status='trialing',
            trial_end=trial_end,
            current_period_start=datetime.now(),
            current_period_end=trial_end
        )
        
        db.session.add(subscription)
        db.session.commit()
        
        # Schedule trial ending emails
        schedule_email(
            user_id=user_id,
            template='trial_started',
            send_at=datetime.now()
        )
        schedule_email(
            user_id=user_id,
            template='trial_ending_soon',
            send_at=trial_end - timedelta(days=3)
        )
        schedule_email(
            user_id=user_id,
            template='trial_ended',
            send_at=trial_end
        )
        
        return subscription
    
    def end_trial(self, user_id):
        subscription = get_user_subscription(user_id)
        
        if not subscription.stripe_subscription_id:
            # User didn't add payment method
            # Downgrade to Free tier
            subscription.tier = 'free'
            subscription.status = 'active'
            subscription.trial_end = None
            
            send_email(user_id, 'trial_ended_no_payment')
        else:
            # User added payment method
            # Subscription automatically converts to paid
            subscription.status = 'active'
            subscription.trial_end = None
            
            send_email(user_id, 'subscription_activated')
        
        db.session.commit()
    
    def extend_trial(self, user_id, days):
        # Admin function to extend trial
        subscription = get_user_subscription(user_id)
        subscription.trial_end += timedelta(days=days)
        db.session.commit()
```

---

## Billing Logic

### Proration Calculation

```python
def calculate_proration(current_tier, new_tier, days_remaining, interval='monthly'):
    """
    Calculate proration amount when upgrading/downgrading mid-cycle.
    """
    current_price = get_tier_price(current_tier, interval)
    new_price = get_tier_price(new_tier, interval)
    
    if interval == 'monthly':
        days_in_period = 30
    else:
        days_in_period = 365
    
    # Unused amount from current subscription
    unused_amount = (days_remaining / days_in_period) * current_price
    
    # Amount for new subscription
    new_amount = (days_remaining / days_in_period) * new_price
    
    # Proration credit (positive for upgrade, negative for downgrade)
    proration_credit = unused_amount - new_amount
    
    return {
        'unused_amount': unused_amount,
        'new_amount': new_amount,
        'proration_credit': proration_credit,
        'amount_due_now': max(0, new_amount - unused_amount)
    }

# Example: Upgrade from Basic to Pro mid-month
>>> calculate_proration('basic', 'pro', days_remaining=15)
{
    'unused_amount': 24.50,   # Unused portion of Basic ($49/30*15)
    'new_amount': 74.50,      # Pro for 15 days ($149/30*15)
    'proration_credit': -50.00,  # Need to pay $50 more
    'amount_due_now': 50.00
}
```

### Invoice Generation

```python
def generate_invoice(user_id, subscription_id, period_start, period_end):
    subscription = get_subscription(subscription_id)
    tier = subscription.tier
    interval = subscription.interval
    
    invoice = Invoice(
        user_id=user_id,
        subscription_id=subscription_id,
        period_start=period_start,
        period_end=period_end,
        tier=tier,
        interval=interval,
        subtotal=get_tier_price(tier, interval),
        tax=calculate_tax(user_id),  # Based on user location
        total=subtotal + tax,
        status='pending',
        due_date=period_end
    )
    
    db.session.add(invoice)
    db.session.commit()
    
    # Send invoice email
    send_invoice_email(user_id, invoice)
    
    return invoice
```

---

## Upgrade/Downgrade Flow

### Upgrade Flow

```python
def upgrade_subscription(user_id, new_tier, new_interval='monthly'):
    subscription = get_user_subscription(user_id)
    
    # Calculate proration
    days_remaining = (subscription.current_period_end - datetime.now()).days
    proration = calculate_proration(
        subscription.tier,
        new_tier,
        days_remaining,
        subscription.interval
    )
    
    # Update Stripe subscription
    stripe_subscription = stripe.Subscription.modify(
        subscription.stripe_subscription_id,
        items=[{
            'id': subscription.stripe_subscription_item_id,
            'price': get_stripe_price_id(new_tier, new_interval)
        }],
        proration_behavior='always_invoice',  # Invoice immediately
        billing_cycle_anchor='unchanged'  # Keep same billing date
    )
    
    # Update database
    subscription.tier = new_tier
    subscription.interval = new_interval
    db.session.commit()
    
    # Send upgrade confirmation
    send_email(user_id, 'subscription_upgraded', {
        'new_tier': new_tier,
        'proration_credit': proration['proration_credit'],
        'amount_charged': proration['amount_due_now']
    })
    
    # Immediately unlock new features
    unlock_tier_features(user_id, new_tier)
    
    return subscription
```

### Downgrade Flow

```python
def downgrade_subscription(user_id, new_tier):
    subscription = get_user_subscription(user_id)
    
    # Downgrade at period end (no immediate change)
    stripe.Subscription.modify(
        subscription.stripe_subscription_id,
        items=[{
            'id': subscription.stripe_subscription_item_id,
            'price': get_stripe_price_id(new_tier, subscription.interval)
        }],
        proration_behavior='none',  # Don't charge/refund immediately
        billing_cycle_anchor='unchanged'
    )
    
    # Mark for downgrade at period end
    subscription.pending_tier = new_tier
    subscription.downgrade_at_period_end = True
    db.session.commit()
    
    # Send downgrade scheduled email
    send_email(user_id, 'subscription_downgrade_scheduled', {
        'current_tier': subscription.tier,
        'new_tier': new_tier,
        'effective_date': subscription.current_period_end
    })
    
    return subscription
```

---

## Cancellation & Refunds

### Cancellation Flow

```python
def cancel_subscription(user_id, cancel_immediately=False, reason=None, feedback=None):
    subscription = get_user_subscription(user_id)
    
    if cancel_immediately:
        # Cancel now and refund prorated amount
        stripe.Subscription.delete(subscription.stripe_subscription_id)
        
        # Calculate refund
        days_remaining = (subscription.current_period_end - datetime.now()).days
        refund_amount = calculate_proration(
            subscription.tier, 'free', days_remaining, subscription.interval
        )['unused_amount']
        
        # Issue refund
        if refund_amount > 0:
            stripe.Refund.create(
                payment_intent=subscription.last_payment_intent_id,
                amount=int(refund_amount * 100)  # Stripe uses cents
            )
        
        # Downgrade to free
        subscription.tier = 'free'
        subscription.status = 'cancelled'
        subscription.cancelled_at = datetime.now()
        
    else:
        # Cancel at period end
        stripe.Subscription.modify(
            subscription.stripe_subscription_id,
            cancel_at_period_end=True
        )
        
        subscription.cancel_at_period_end = True
    
    # Store cancellation reason
    if reason or feedback:
        cancellation = CancellationFeedback(
            user_id=user_id,
            reason=reason,
            feedback=feedback,
            cancelled_at=datetime.now()
        )
        db.session.add(cancellation)
    
    db.session.commit()
    
    # Send cancellation email
    send_email(user_id, 'subscription_cancelled', {
        'cancel_immediately': cancel_immediately,
        'access_until': subscription.current_period_end if not cancel_immediately else datetime.now()
    })
    
    return subscription
```

### Refund Policy

**Full Refund (7 days):**
- Within 7 days of initial subscription
- No questions asked
- Full refund issued

**Prorated Refund (Annual Plans):**
- Cancel annual plan mid-year
- Refund unused portion
- Minus one-month penalty fee

**No Refund:**
- Monthly plans (cancel at period end)
- After 7-day window

---

## Revenue Analytics

### Key Metrics

```python
class RevenueAnalytics:
    def get_mrr(self):
        """Monthly Recurring Revenue"""
        active_subs = Subscription.query.filter_by(status='active').all()
        
        mrr = 0
        for sub in active_subs:
            if sub.interval == 'monthly':
                mrr += get_tier_price(sub.tier, 'monthly')
            else:  # yearly
                mrr += get_tier_price(sub.tier, 'yearly') / 12
        
        return mrr
    
    def get_arr(self):
        """Annual Recurring Revenue"""
        return self.get_mrr() * 12
    
    def get_churn_rate(self, period_days=30):
        """Churn rate over period"""
        period_start = datetime.now() - timedelta(days=period_days)
        
        customers_start = Subscription.query.filter(
            Subscription.created_at < period_start,
            Subscription.status == 'active'
        ).count()
        
        churned = Subscription.query.filter(
            Subscription.cancelled_at >= period_start,
            Subscription.cancelled_at < datetime.now()
        ).count()
        
        if customers_start == 0:
            return 0
        
        return churned / customers_start
    
    def get_ltv(self):
        """Customer Lifetime Value"""
        avg_revenue_per_user = self.get_mrr() / Subscription.query.filter_by(status='active').count()
        churn_rate = self.get_churn_rate()
        
        if churn_rate == 0:
            return float('inf')
        
        # LTV = ARPU / Churn Rate
        return avg_revenue_per_user / churn_rate
    
    def get_tier_distribution(self):
        """Distribution of users across tiers"""
        return {
            'free': Subscription.query.filter_by(tier='free', status='active').count(),
            'basic': Subscription.query.filter_by(tier='basic', status='active').count(),
            'pro': Subscription.query.filter_by(tier='pro', status='active').count(),
            'enterprise': Subscription.query.filter_by(tier='enterprise', status='active').count()
        }
```

### Revenue Dashboard

```
┌────────────────────────────────────────────────────────────┐
│  💰 Revenue Analytics                                      │
└────────────────────────────────────────────────────────────┘

MRR:  $156,789
ARR:  $1,881,468
Growth (MoM): +12.5%

Churn Rate: 3.5%
LTV: $2,450
CAC: $450
LTV:CAC = 5.4:1

┌────────────────────────────────────────────────────────────┐
│  User Distribution                                         │
├──────────┬─────────┬──────────┬──────────┬────────────────┤
│ Tier     │ Users   │ % Total  │   MRR    │ Avg Rev/User   │
├──────────┼─────────┼──────────┼──────────┼────────────────┤
│ Free     │   456   │   36.6%  │      $0  │      $0        │
│ Basic    │   345   │   27.7%  │ $16,905  │    $49         │
│ Pro      │   389   │   31.3%  │ $57,961  │   $149         │
│ Enterprise│   55   │    4.4%  │ $27,445  │   $499         │
├──────────┼─────────┼──────────┼──────────┼────────────────┤
│ Total    │ 1,245   │  100.0%  │$102,311  │   $125         │
└──────────┴─────────┴──────────┴──────────┴────────────────┘
```

---

**Version:** 2.0  
**Last Updated:** January 29, 2026  
**Maintained By:** NIJA Monetization Team
