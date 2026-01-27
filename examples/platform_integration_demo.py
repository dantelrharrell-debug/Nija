"""
NIJA Platform Integration Example

Demonstrates how to use all the new infrastructure components together:
- Founder Dashboard
- Alpha Onboarding
- Monetization Engine
- Global Risk Engine

This example shows a complete user journey from invitation to active trading.
"""

import logging
from datetime import datetime

# Import NIJA components
from alpha_onboarding import get_onboarding_system
from monetization_engine import (
    get_monetization_engine,
    SubscriptionTier,
    BillingInterval
)
from core.global_risk_engine import get_global_risk_engine
from founder_dashboard import FounderDashboard

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def demo_alpha_user_onboarding():
    """
    Demo: Complete alpha user onboarding workflow
    """
    print("\n" + "="*60)
    print("DEMO: Alpha User Onboarding")
    print("="*60 + "\n")
    
    onboarding = get_onboarding_system()
    
    # 1. Founder generates invitation code
    print("Step 1: Generate invitation code")
    invitation = onboarding.generate_invitation_code(
        email="alice@trader.com",
        tier="alpha",
        validity_days=7
    )
    print(f"✅ Invitation code generated: {invitation.code}")
    print(f"   Expires: {invitation.expires_at.strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    # 2. User registers with invitation code
    print("Step 2: User registration")
    success, error, user_id = onboarding.register_user(
        invitation_code=invitation.code,
        email="alice@trader.com",
        password_hash="hashed_password_here"
    )
    
    if success:
        print(f"✅ User registered: {user_id}")
    else:
        print(f"❌ Registration failed: {error}")
        return None
    print()
    
    # 3. Email verification
    print("Step 3: Email verification")
    success, error = onboarding.verify_email(user_id, "verification_code_123")
    if success:
        print("✅ Email verified")
    print()
    
    # 4. Broker credentials setup
    print("Step 4: Broker credentials setup")
    success, error = onboarding.setup_broker_credentials(
        user_id=user_id,
        broker="coinbase",
        api_key="user_coinbase_api_key",
        api_secret="user_coinbase_api_secret"
    )
    if success:
        print("✅ Broker credentials configured")
    print()
    
    # 5. Tutorial completion
    print("Step 5: Complete tutorial")
    success, error = onboarding.complete_tutorial(user_id)
    if success:
        print("✅ Tutorial completed")
    print()
    
    # 6. Account activation
    print("Step 6: Activate account")
    success, error = onboarding.activate_user(user_id)
    if success:
        print("✅ Account activated!")
    print()
    
    # Check onboarding status
    status = onboarding.get_onboarding_status(user_id)
    if status:
        print(f"📊 Onboarding Status:")
        print(f"   Progress: {status.get_progress_percent()}%")
        print(f"   Status: {status.status.value}")
        print(f"   Steps completed: {', '.join(status.steps_completed)}")
    
    return user_id


def demo_subscription_management(user_id: str):
    """
    Demo: Subscription and billing management
    """
    print("\n" + "="*60)
    print("DEMO: Subscription Management")
    print("="*60 + "\n")
    
    engine = get_monetization_engine()
    
    # 1. Show available tiers
    print("Step 1: Available subscription tiers")
    pricing = engine.get_all_pricing()
    for tier in pricing:
        print(f"   {tier.tier.value.upper()}:")
        print(f"     Monthly: ${tier.monthly_price}")
        print(f"     Yearly: ${tier.yearly_price} (save ${tier.monthly_price * 12 - tier.yearly_price})")
        print(f"     Max Positions: {tier.limits['max_positions']}")
        print()
    
    # 2. Create subscription with trial
    print("Step 2: Create subscription (14-day trial)")
    success, error, subscription = engine.create_subscription(
        user_id=user_id,
        tier=SubscriptionTier.PRO,
        interval=BillingInterval.MONTHLY,
        trial_days=14
    )
    
    if success:
        print(f"✅ Subscription created")
        print(f"   Tier: {subscription.tier.value}")
        print(f"   Status: {subscription.status}")
        print(f"   Trial ends: {subscription.trial_end.strftime('%Y-%m-%d')}")
        print(f"   Next billing: {subscription.current_period_end.strftime('%Y-%m-%d')}")
    print()
    
    # 3. Track usage
    print("Step 3: Track usage")
    engine.track_usage(user_id, "trades_executed", 5)
    engine.track_usage(user_id, "api_calls", 100)
    engine.track_usage(user_id, "active_positions", 3)
    print("✅ Usage tracked")
    print()
    
    # 4. Check usage limits
    print("Step 4: Check usage limits")
    limits = engine.check_usage_limits(user_id)
    if limits['within_limits']:
        print("✅ Within usage limits")
    else:
        print("⚠️  Usage limits exceeded:")
        for limit, info in limits['limits_exceeded'].items():
            print(f"   {limit}: {info['current']}/{info['limit']}")
    print()
    
    # 5. Simulate upgrade
    print("Step 5: Upgrade to Enterprise")
    success, error = engine.upgrade_subscription(user_id, SubscriptionTier.ENTERPRISE)
    if success:
        print("✅ Upgraded to Enterprise tier")
    print()
    
    return subscription


def demo_risk_monitoring(user_id: str):
    """
    Demo: Global risk monitoring
    """
    print("\n" + "="*60)
    print("DEMO: Global Risk Monitoring")
    print("="*60 + "\n")
    
    risk_engine = get_global_risk_engine()
    
    # 1. Update account metrics
    print("Step 1: Update account metrics")
    risk_engine.update_account_metrics(user_id, {
        'total_exposure': 5000.0,
        'position_count': 3,
        'current_balance': 10000.0,
        'unrealized_pnl': 250.0
    })
    print("✅ Metrics updated")
    print()
    
    # 2. Get account risk metrics
    print("Step 2: Get account risk metrics")
    account_metrics = risk_engine.get_account_metrics(user_id)
    if account_metrics:
        print(f"   Balance: ${account_metrics.current_balance:,.2f}")
        print(f"   Exposure: ${account_metrics.total_exposure:,.2f}")
        print(f"   Positions: {account_metrics.position_count}")
        print(f"   Unrealized P&L: ${account_metrics.unrealized_pnl:,.2f}")
        print(f"   Drawdown: {account_metrics.drawdown_pct:.2f}%")
    print()
    
    # 3. Check if new position can be opened
    print("Step 3: Check if new position can be opened")
    can_open, reason = risk_engine.can_open_position(user_id, 1000.0)
    if can_open:
        print(f"✅ Position allowed: {reason}")
    else:
        print(f"❌ Position denied: {reason}")
    print()
    
    # 4. Get portfolio metrics
    print("Step 4: Get portfolio-level metrics")
    portfolio = risk_engine.calculate_portfolio_metrics()
    print(f"   Total Accounts: {portfolio.total_accounts}")
    print(f"   Total Exposure: ${portfolio.total_exposure:,.2f}")
    print(f"   Total Positions: {portfolio.total_positions}")
    print(f"   Total Balance: ${portfolio.total_balance:,.2f}")
    print(f"   Portfolio Drawdown: {portfolio.portfolio_drawdown_pct:.2f}%")
    print()
    
    # 5. Get recent risk events
    print("Step 5: Get recent risk events")
    events = risk_engine.get_risk_events(hours=24)
    if events:
        print(f"   Found {len(events)} risk events in last 24h")
        for event in events[:3]:  # Show first 3
            print(f"   - [{event.risk_level.value}] {event.message}")
    else:
        print("   No risk events in last 24h")
    print()


def demo_founder_dashboard():
    """
    Demo: Founder dashboard overview
    """
    print("\n" + "="*60)
    print("DEMO: Founder Dashboard")
    print("="*60 + "\n")
    
    dashboard = FounderDashboard(update_interval=5)
    
    # 1. Get dashboard overview
    print("Step 1: Get dashboard overview")
    overview = dashboard.get_dashboard_overview()
    
    print("Platform Metrics:")
    if 'platform_metrics' in overview:
        metrics = overview['platform_metrics']
        if 'users' in metrics:
            print(f"  Users: {metrics['users'].get('total', 0)} total, {metrics['users'].get('active', 0)} active")
        if 'positions' in metrics:
            print(f"  Active Positions: {metrics['positions'].get('active', 0)}")
        if 'trades_24h' in metrics:
            print(f"  Trades (24h): {metrics['trades_24h'].get('count', 0)}")
            print(f"  P&L (24h): ${metrics['trades_24h'].get('total_pnl', 0):,.2f}")
    print()
    
    # 2. Get system health
    print("Step 2: Get system health")
    health = dashboard.get_system_health()
    print(f"  CPU: {health['cpu_percent']:.1f}%")
    print(f"  Memory: {health['memory_percent']:.1f}%")
    print(f"  Disk: {health['disk_percent']:.1f}%")
    print()
    
    # 3. Get revenue metrics
    print("Step 3: Get revenue metrics")
    revenue = dashboard.get_revenue_metrics()
    print(f"  MRR: ${revenue['monthly_recurring_revenue']:,.2f}")
    print(f"  Active Users: {revenue['total_active_users']}")
    if 'users_by_tier' in revenue:
        print("  Users by tier:")
        for tier, count in revenue['users_by_tier'].items():
            if count > 0:
                print(f"    {tier}: {count}")
    print()
    
    dashboard.shutdown()


def main():
    """
    Run complete integration demo
    """
    print("\n" + "="*80)
    print(" "*20 + "NIJA PLATFORM INTEGRATION DEMO")
    print("="*80)
    
    # 1. Onboard alpha user
    user_id = demo_alpha_user_onboarding()
    if not user_id:
        print("❌ Onboarding failed, stopping demo")
        return
    
    # 2. Set up subscription
    demo_subscription_management(user_id)
    
    # 3. Monitor risk
    demo_risk_monitoring(user_id)
    
    # 4. View founder dashboard
    demo_founder_dashboard()
    
    print("\n" + "="*80)
    print(" "*25 + "DEMO COMPLETE! ✅")
    print("="*80)
    print()
    print("Next steps:")
    print("  1. Deploy to Kubernetes: ./scripts/deploy_k8s.sh")
    print("  2. Access Founder Dashboard: http://<EXTERNAL-IP>:5001")
    print("  3. Start onboarding real users")
    print()


if __name__ == "__main__":
    main()
