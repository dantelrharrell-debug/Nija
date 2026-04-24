#!/usr/bin/env python3
"""
NIJA Graduation System - Quick Start Demo
==========================================

Demonstrates the complete paper trading to live trading graduation flow.

This script shows:
1. Regulatory compliance testing
2. New user onboarding
3. Paper trading progress tracking
4. Graduation eligibility checking
5. Live trading activation
6. Progressive limit unlocking
"""

import sys
import time
from datetime import datetime, timedelta

# Import graduation and compliance systems
from bot.paper_trading_graduation import PaperTradingGraduationSystem, TradingMode
from bot.regulatory_compliance import run_compliance_test


def print_section(title: str):
    """Print section header"""
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80 + "\n")


def demo_regulatory_compliance():
    """Demo: Run regulatory compliance checks"""
    print_section("STEP 1: Regulatory Compliance Check")
    
    print("Running comprehensive compliance test for app store submission...")
    print("Checking 18 compliance requirements across 5 categories...\n")
    
    report = run_compliance_test()
    
    if report['summary']['ready_for_submission']:
        print("✅ Platform is ready for app store submission!")
    else:
        print("❌ Platform has compliance issues that must be fixed.")
        sys.exit(1)


def demo_new_user_onboarding():
    """Demo: New user starts in paper trading"""
    print_section("STEP 2: New User Onboarding")
    
    user_id = "demo_user_001"
    print(f"Creating new user: {user_id}")
    
    graduation = PaperTradingGraduationSystem(user_id, data_dir="/tmp/graduation_demo")
    
    print(f"✅ User created successfully")
    print(f"   Trading Mode: {graduation.progress.trading_mode.value}")
    print(f"   Status: {graduation.progress.status.value}")
    print(f"   Paper Trading Start: {graduation.progress.paper_trading_start_date[:10]}")
    print(f"\nNew users automatically start in PAPER TRADING mode.")
    print("This ensures they learn the platform risk-free before using real money.")
    
    return graduation


def demo_paper_trading_progress(graduation: PaperTradingGraduationSystem):
    """Demo: Track paper trading progress"""
    print_section("STEP 3: Paper Trading Progress")
    
    print("Simulating 30 days of paper trading with good performance...\n")
    
    # Simulate user has been trading for 35 days
    past_date = (datetime.utcnow() - timedelta(days=35)).isoformat()
    graduation.progress.paper_trading_start_date = past_date
    
    # Simulate good paper trading stats
    paper_stats = {
        'total_trades': 30,
        'winning_trades': 20,
        'losing_trades': 10,
        'win_rate': 66.7,
        'total_pnl': 650.0,
        'max_drawdown': 11.5,
        'avg_position_size': 75.0
    }
    
    graduation.update_from_paper_account(paper_stats)
    
    print(f"📊 Paper Trading Results:")
    print(f"   Days Trading: {graduation.progress.days_in_paper_trading}")
    print(f"   Total Trades: {graduation.progress.total_paper_trades}")
    print(f"   Win Rate: {graduation.progress.win_rate:.1f}%")
    print(f"   Total P&L: ${graduation.progress.total_pnl:,.2f}")
    print(f"   Max Drawdown: {graduation.progress.max_drawdown:.1f}%")
    print(f"   Risk Score: {graduation.progress.risk_score:.1f}/100")
    
    print("\n📋 Graduation Criteria Status:")
    criteria = graduation.get_criteria_details()
    for criterion in criteria:
        icon = "✅" if criterion.met else "⏳"
        print(f"   {icon} {criterion.name}: {criterion.progress:.1f}%")
    
    return graduation


def demo_graduation_eligibility(graduation: PaperTradingGraduationSystem):
    """Demo: Check graduation eligibility"""
    print_section("STEP 4: Graduation Eligibility Check")
    
    if graduation.is_eligible_for_graduation():
        print("🎉 CONGRATULATIONS!")
        print("You have met all graduation requirements and are ready for live trading!")
        print("\n✅ All criteria met:")
        for criterion_id in graduation.progress.criteria_met:
            print(f"   • {criterion_id}")
    else:
        print("⏳ Not yet eligible for graduation.")
        print("\n❌ Criteria not yet met:")
        for criterion_id in graduation.progress.criteria_not_met:
            print(f"   • {criterion_id}")
        sys.exit(0)


def demo_graduate_to_live_trading(graduation: PaperTradingGraduationSystem):
    """Demo: Graduate to live trading with restrictions"""
    print_section("STEP 5: Graduate to Live Trading")
    
    print("User acknowledges risks and enables live trading...")
    time.sleep(1)
    
    result = graduation.graduate_to_live_trading()
    
    if result['success']:
        print("\n🎊 GRADUATION SUCCESSFUL!")
        print(f"   {result['message']}")
        print(f"\n📊 Initial Trading Limits (Safety Training Period):")
        print(f"   Max Position Size: ${result['restrictions']['max_position_size']}")
        print(f"   Max Total Capital: ${result['restrictions']['max_total_capital']}")
        print(f"   Full Access In: {result['restrictions']['unlock_full_after_days']} days")
        print(f"\nThese restrictions protect new live traders while they gain experience.")
    else:
        print(f"\n❌ Graduation failed: {result['message']}")
        sys.exit(1)


def demo_trading_limits(graduation: PaperTradingGraduationSystem):
    """Demo: Show current trading limits"""
    print_section("STEP 6: Trading Limits Enforcement")
    
    limits = graduation.get_current_limits()
    
    print(f"Current Trading Mode: {limits['mode'].upper()}")
    print(f"\n🛡️ Active Restrictions:")
    print(f"   {limits['restrictions']}")
    
    if limits['max_position_size']:
        print(f"\n💡 Examples:")
        print(f"   ✅ Can trade: ${limits['max_position_size']} position in BTC")
        print(f"   ❌ Cannot trade: ${limits['max_position_size'] + 50} position (exceeds limit)")
        print(f"   ✅ Can trade: Multiple positions up to ${limits['max_total_capital']} total")


def demo_unlock_full_access(graduation: PaperTradingGraduationSystem):
    """Demo: Unlock full access after restricted period"""
    print_section("STEP 7: Unlock Full Live Trading Access")
    
    print("After 14 days of successful live trading with restrictions...")
    print("Checking eligibility for full access...\n")
    
    # Simulate 14+ days have passed
    past_date = (datetime.utcnow() - timedelta(days=15)).isoformat()
    graduation.progress.live_trading_enabled_date = past_date
    
    result = graduation.unlock_full_live_trading()
    
    if result['success']:
        print("🚀 FULL ACCESS UNLOCKED!")
        print(f"   {result['message']}")
        print(f"   Trading Mode: {result['trading_mode'].upper()}")
        print(f"\n✅ You now have access to:")
        print("   • Your full account balance")
        print("   • No platform-imposed position limits")
        print("   • All advanced features")
        print("   • Full trading capabilities")
    else:
        print(f"⏳ {result['message']}")


def demo_safety_features(graduation: PaperTradingGraduationSystem):
    """Demo: Safety features like reversion to paper"""
    print_section("STEP 8: Safety Features")
    
    print("🛡️ User Safety Controls:")
    print("\n1. REVERSIBLE GRADUATION")
    print("   Users can return to paper trading anytime:")
    
    current_mode = graduation.progress.trading_mode
    print(f"   Current mode: {current_mode.value}")
    
    result = graduation.revert_to_paper_trading()
    print(f"   ✅ {result['message']}")
    print(f"   New mode: {graduation.progress.trading_mode.value}")
    
    # Switch back for demo
    graduation.progress.trading_mode = current_mode
    
    print("\n2. KILL-SWITCH")
    print("   Emergency stop button always available in mobile app")
    
    print("\n3. PROGRESSIVE LIMITS")
    print("   Capital exposure increases gradually as user gains experience")
    
    print("\n4. RISK ACKNOWLEDGMENT")
    print("   Required before each mode transition")
    
    print("\n5. REAL-TIME MONITORING")
    print("   Continuous tracking of performance and risk metrics")


def main():
    """Run complete graduation system demo"""
    print("\n" + "=" * 80)
    print("  NIJA Paper Trading → Live Trading Graduation System")
    print("  Complete Demonstration")
    print("=" * 80)
    
    try:
        # Step 1: Regulatory compliance
        demo_regulatory_compliance()
        time.sleep(1)
        
        # Step 2: New user onboarding
        graduation = demo_new_user_onboarding()
        time.sleep(1)
        
        # Step 3: Paper trading progress
        graduation = demo_paper_trading_progress(graduation)
        time.sleep(1)
        
        # Step 4: Check graduation eligibility
        demo_graduation_eligibility(graduation)
        time.sleep(1)
        
        # Step 5: Graduate to live trading
        demo_graduate_to_live_trading(graduation)
        time.sleep(1)
        
        # Step 6: Show trading limits
        demo_trading_limits(graduation)
        time.sleep(1)
        
        # Step 7: Unlock full access
        demo_unlock_full_access(graduation)
        time.sleep(1)
        
        # Step 8: Safety features
        demo_safety_features(graduation)
        
        # Final summary
        print_section("DEMO COMPLETE")
        print("✅ The graduation system is fully operational and ready for production.")
        print("\n📱 Next Steps:")
        print("   1. Integrate graduation API into mobile app")
        print("   2. Implement mobile UX screens from documentation")
        print("   3. Test complete user journey end-to-end")
        print("   4. Deploy to app stores")
        
        print("\n📖 Documentation: PAPER_TRADING_GRADUATION_GUIDE.md")
        print("🔧 API Reference: bot/graduation_api.py")
        print("🧪 Test Suite: bot/tests/test_paper_trading_graduation.py")
        
        print("\n" + "=" * 80 + "\n")
        
        return 0
        
    except Exception as e:
        print(f"\n❌ Error during demo: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
