#!/usr/bin/env python3
"""
Example: Creating and Approving a Risk Configuration Version

This script demonstrates the complete workflow for proposing, testing,
and approving a risk configuration change under RISK FREEZE policy.

Author: NIJA Trading Systems
Date: February 12, 2026
"""

from bot.risk_config_versions import (
    get_version_manager,
    RiskParameterChange,
    BacktestResults,
    PaperTradingResults,
    Approval
)
from bot.risk_freeze_guard import get_risk_freeze_guard


def example_create_risk_version():
    """Example: Create a new risk configuration version"""
    
    print("=" * 80)
    print("EXAMPLE: Creating New Risk Configuration Version")
    print("=" * 80)
    print()
    
    # Step 1: Get current active configuration
    version_manager = get_version_manager()
    current_params = version_manager.get_active_parameters()
    
    if not current_params:
        print("⚠️  No active configuration found. Loading baseline...")
        import json
        with open('config/risk_versions/baseline_risk_config.json') as f:
            baseline = json.load(f)
        current_params = baseline['risk_parameters']
        
        # Set as baseline
        guard = get_risk_freeze_guard()
        guard.set_baseline(current_params)
    
    print(f"✅ Current active version: {version_manager.get_active_version().version if version_manager.get_active_version() else 'None'}")
    print()
    
    # Step 2: Define proposed changes
    print("📝 STEP 1: Define Changes")
    print("-" * 80)
    
    changes = [
        RiskParameterChange(
            parameter='max_position_size',
            old_value=current_params.get('max_position_size', 0.10),
            new_value=0.08,
            reason='Reduce exposure during Q1 2026 volatility - historically volatile period'
        ),
        RiskParameterChange(
            parameter='stop_loss_atr_multiplier',
            old_value=current_params.get('stop_loss_atr_multiplier', 1.5),
            new_value=1.8,
            reason='Reduce premature stop-outs - backtest showed 15% improvement'
        )
    ]
    
    for change in changes:
        print(f"  • {change.parameter}")
        print(f"    {change.old_value} → {change.new_value}")
        print(f"    Reason: {change.reason}")
        print()
    
    # Step 3: Create new configuration
    print("🔧 STEP 2: Create New Version")
    print("-" * 80)
    
    new_params = current_params.copy()
    new_params['max_position_size'] = 0.08
    new_params['stop_loss_atr_multiplier'] = 1.8
    
    version = version_manager.create_version(
        version='RISK_CONFIG_v1.1.0',
        author='NIJA Risk Management Team',
        changes=changes,
        risk_parameters=new_params
    )
    
    print(f"✅ Created version: {version.version}")
    print(f"   Status: {version.status}")
    print()
    
    # Step 4: Add backtest results
    print("📊 STEP 3: Add Backtest Results")
    print("-" * 80)
    
    backtest_results = BacktestResults(
        period_start='2025-11-12',
        period_end='2026-02-12',
        win_rate=0.60,  # 60%
        max_drawdown=0.11,  # 11% (improvement from 12%)
        sharpe_ratio=1.85,  # (improvement from 1.75)
        total_return=0.52,  # 52%
        total_trades=287,
        conclusion='APPROVED - Win rate +3%, drawdown -1%, Sharpe +0.10'
    )
    
    version_manager.add_backtest_results('RISK_CONFIG_v1.1.0', backtest_results)
    
    print(f"✅ Backtest Results Added:")
    print(f"   Period: {backtest_results.period_start} to {backtest_results.period_end}")
    print(f"   Win Rate: {backtest_results.win_rate:.2%}")
    print(f"   Max Drawdown: {backtest_results.max_drawdown:.2%}")
    print(f"   Sharpe Ratio: {backtest_results.sharpe_ratio:.2f}")
    print(f"   Conclusion: {backtest_results.conclusion}")
    print()
    
    # Step 5: Add paper trading results
    print("🎭 STEP 4: Add Paper Trading Results")
    print("-" * 80)
    
    paper_results = PaperTradingResults(
        period_start='2026-01-29',
        period_end='2026-02-12',
        trades=47,
        win_rate=0.62,  # 62% (consistent with backtest)
        max_drawdown=0.09,  # 9% (better than backtest)
        conclusion='APPROVED - Results consistent with backtest, lower drawdown'
    )
    
    version_manager.add_paper_trading_results('RISK_CONFIG_v1.1.0', paper_results)
    
    print(f"✅ Paper Trading Results Added:")
    print(f"   Period: {paper_results.period_start} to {paper_results.period_end}")
    print(f"   Trades: {paper_results.trades}")
    print(f"   Win Rate: {paper_results.win_rate:.2%}")
    print(f"   Conclusion: {paper_results.conclusion}")
    print()
    
    # Step 6: Add approvals
    print("✅ STEP 5: Add Approvals")
    print("-" * 80)
    
    approvals = [
        Approval(
            role='Technical Lead',
            name='NIJA Development Team',
            date='2026-02-12T14:30:00Z',
            signature='APPROVED_TECH_LEAD'
        ),
        Approval(
            role='Risk Manager',
            name='NIJA Risk Team',
            date='2026-02-12T15:00:00Z',
            signature='APPROVED_RISK_MGR'
        ),
        Approval(
            role='Strategy Developer',
            name='NIJA Strategy Team',
            date='2026-02-12T15:30:00Z',
            signature='APPROVED_STRATEGY'
        )
    ]
    
    for approval in approvals:
        version_manager.add_approval('RISK_CONFIG_v1.1.0', approval)
        print(f"  ✅ {approval.role}: {approval.name}")
    
    print()
    
    # Step 7: Activate version
    print("🚀 STEP 6: Activate Version")
    print("-" * 80)
    
    # Check if can activate
    updated_version = version_manager.get_version('RISK_CONFIG_v1.1.0')
    
    if updated_version.can_activate():
        version_manager.activate_version('RISK_CONFIG_v1.1.0')
        print(f"✅ Version ACTIVATED: {updated_version.version}")
        print(f"   Status: {updated_version.status}")
    else:
        print(f"❌ Cannot activate - requirements not met")
        if not updated_version.is_approved():
            print("   Missing: Approvals")
        if not updated_version.backtesting:
            print("   Missing: Backtest results")
        if not updated_version.paper_trading:
            print("   Missing: Paper trading results")
    
    print()
    
    # Step 8: Generate report
    print("📄 STEP 7: Generate Version Report")
    print("=" * 80)
    
    report = version_manager.generate_version_report('RISK_CONFIG_v1.1.0')
    print(report)


def example_validate_config():
    """Example: Validate configuration against RISK FREEZE"""
    
    print()
    print("=" * 80)
    print("EXAMPLE: Validating Configuration Against RISK FREEZE")
    print("=" * 80)
    print()
    
    guard = get_risk_freeze_guard()
    version_manager = get_version_manager()
    
    # Get active parameters
    active_params = version_manager.get_active_parameters()
    
    if not active_params:
        print("⚠️  No active configuration - skipping validation example")
        return
    
    # Validate unchanged config (should pass)
    print("✅ Test 1: Validate unchanged config")
    try:
        guard.validate_config(active_params)
        print("   PASS - No changes detected")
    except Exception as e:
        print(f"   FAIL - {e}")
    
    print()
    
    # Test with unauthorized change (should fail)
    print("❌ Test 2: Validate unauthorized change")
    changed_params = active_params.copy()
    changed_params['max_position_size'] = 0.99  # Unauthorized change
    
    try:
        guard.validate_config(changed_params)
        print("   FAIL - Should have detected violation!")
    except Exception as e:
        print("   PASS - Violation detected as expected")
        print(f"   Message: {str(e)[:100]}...")
    
    print()


def example_emergency_override():
    """Example: Emergency override workflow"""
    
    print("=" * 80)
    print("EXAMPLE: Emergency Override (Use Sparingly!)")
    print("=" * 80)
    print()
    
    guard = get_risk_freeze_guard()
    
    print("🚨 Declaring Emergency Override")
    print("-" * 80)
    print("Scenario: Exchange suddenly increased margin requirements")
    print()
    
    guard.declare_emergency_override(
        reason="Coinbase increased margin requirements from 2x to 3x",
        authorized_by="Technical Lead - Emergency Authorization",
        parameters_changed=['max_leverage']
    )
    
    print("✅ Emergency override declared and logged")
    print()
    print("⚠️  NEXT STEPS (within 48 hours):")
    print("   1. Document the emergency situation")
    print("   2. Create proper risk configuration version")
    print("   3. Backtest the change")
    print("   4. Get retroactive approvals")
    print("   5. Either formalize as permanent OR rollback")
    print()
    
    # Show override log
    pending = guard.get_pending_approvals()
    print(f"📋 Pending Emergency Approvals: {len(pending)}")
    for override in pending:
        print(f"   • {override.timestamp}")
        print(f"     Reason: {override.reason}")
        print(f"     By: {override.authorized_by}")
    
    print()


if __name__ == '__main__':
    """Run all examples"""
    
    print()
    print("*" * 80)
    print("*" + " " * 78 + "*")
    print("*" + "  RISK FREEZE POLICY - Example Workflows".center(78) + "*")
    print("*" + " " * 78 + "*")
    print("*" * 80)
    print()
    print("This script demonstrates the complete RISK FREEZE workflow:")
    print("  1. Creating a new risk configuration version")
    print("  2. Adding backtest and paper trading results")
    print("  3. Getting approvals from stakeholders")
    print("  4. Activating the approved version")
    print("  5. Validating configurations")
    print("  6. Emergency override procedures")
    print()
    print("*" * 80)
    print()
    
    # Run examples
    try:
        example_create_risk_version()
        example_validate_config()
        example_emergency_override()
        
        print()
        print("*" * 80)
        print("✅ All examples completed successfully!")
        print("*" * 80)
        print()
        print("📚 For more information, see:")
        print("   - RISK_FREEZE_POLICY.md - Complete policy document")
        print("   - RISK_FREEZE_QUICK_REF.md - Quick reference guide")
        print("   - bot/risk_freeze_guard.py - Guard implementation")
        print("   - bot/risk_config_versions.py - Versioning system")
        print()
        
    except Exception as e:
        print(f"\n❌ Error running examples: {e}")
        import traceback
        traceback.print_exc()
