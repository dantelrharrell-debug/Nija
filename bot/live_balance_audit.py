#!/usr/bin/env python3
"""
Live Balance Audit - Reality Check
===================================

Verify MICRO_CAP hardening is actually working by checking:
1. Total funds per account
2. Available capital
3. Held capital
4. Open order count

If MICRO_CAP is working properly, held should align with a single ~$20 position.

Author: NIJA Trading Systems
Date: February 17, 2026
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
from datetime import datetime
from typing import Dict, List, Optional

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s'
)
logger = logging.getLogger(__name__)

try:
    from account_order_tracker import get_order_tracker
    from account_performance_tracker import get_performance_tracker
    from micro_capital_config import (
        MICRO_CAPITAL_MODE,
        MAX_POSITIONS,
        MIN_TRADE_SIZE,
        ENABLE_DCA,
        ALLOW_MULTIPLE_ENTRIES_SAME_SYMBOL
    )
except ImportError as e:
    logger.warning(f"Could not import tracking modules: {e}")
    MICRO_CAPITAL_MODE = None

# Try to import broker modules
try:
    from broker_manager import BrokerType, AccountType, BaseBroker
    from multi_account_broker_manager import MultiAccountBrokerManager
    BROKER_AVAILABLE = True
except ImportError as e:
    logger.warning(f"Broker modules not available: {e}")
    BROKER_AVAILABLE = False


class LiveBalanceAuditor:
    """Live balance auditor for reality check"""
    
    def __init__(self):
        """Initialize the auditor"""
        self.order_tracker = None
        self.perf_tracker = None
        self.broker_manager = None
        
        # Try to initialize trackers
        try:
            self.order_tracker = get_order_tracker()
            logger.info("✅ Order tracker loaded")
        except Exception as e:
            logger.warning(f"⚠️ Could not load order tracker: {e}")
        
        try:
            self.perf_tracker = get_performance_tracker()
            logger.info("✅ Performance tracker loaded")
        except Exception as e:
            logger.warning(f"⚠️ Could not load performance tracker: {e}")
        
        # Try to initialize broker manager
        if BROKER_AVAILABLE:
            try:
                self.broker_manager = MultiAccountBrokerManager()
                logger.info("✅ Broker manager loaded")
            except Exception as e:
                logger.warning(f"⚠️ Could not load broker manager: {e}")
    
    def get_broker_balances(self) -> Dict[str, Dict]:
        """
        Get actual balances from broker APIs
        
        Returns:
            Dictionary mapping account_id to balance info
        """
        balances = {}
        
        if not self.broker_manager:
            logger.warning("⚠️ Broker manager not available, cannot get live balances")
            return balances
        
        # Check platform account
        try:
            platform_broker = self.broker_manager.get_platform_broker()
            if platform_broker and platform_broker.is_connected():
                balance = platform_broker.get_account_balance()
                positions = platform_broker.get_positions() or []
                
                # Calculate held capital from positions
                held_in_positions = sum(
                    float(pos.get('size_usd', 0) or pos.get('current_value', 0) or 0)
                    for pos in positions
                )
                
                balances['PLATFORM'] = {
                    'total': balance,
                    'available': balance - held_in_positions,
                    'held_in_positions': held_in_positions,
                    'position_count': len(positions),
                    'positions': positions
                }
                logger.info(f"✅ Got PLATFORM balance: ${balance:.2f}")
        except Exception as e:
            logger.warning(f"⚠️ Could not get PLATFORM balance: {e}")
        
        # Check user accounts
        if hasattr(self.broker_manager, 'user_brokers'):
            for user_id, brokers in self.broker_manager.user_brokers.items():
                try:
                    for broker_type, broker in brokers.items():
                        if broker and broker.is_connected():
                            balance = broker.get_account_balance()
                            positions = broker.get_positions() or []
                            
                            held_in_positions = sum(
                                float(pos.get('size_usd', 0) or pos.get('current_value', 0) or 0)
                                for pos in positions
                            )
                            
                            account_id = f"USER_{user_id}_{broker_type.value if hasattr(broker_type, 'value') else broker_type}"
                            balances[account_id] = {
                                'total': balance,
                                'available': balance - held_in_positions,
                                'held_in_positions': held_in_positions,
                                'position_count': len(positions),
                                'positions': positions
                            }
                            logger.info(f"✅ Got {account_id} balance: ${balance:.2f}")
                except Exception as e:
                    logger.warning(f"⚠️ Could not get user {user_id} balance: {e}")
        
        return balances
    
    def get_tracked_orders(self) -> Dict[str, Dict]:
        """
        Get order information from tracking system
        
        Returns:
            Dictionary mapping account_id to order info
        """
        tracked = {}
        
        if not self.order_tracker:
            logger.warning("⚠️ Order tracker not available")
            return tracked
        
        # Get all accounts from tracker
        all_accounts = set()
        if hasattr(self.order_tracker, 'orders_by_account'):
            all_accounts.update(self.order_tracker.orders_by_account.keys())
        if hasattr(self.order_tracker, 'reserved_capital_by_account'):
            all_accounts.update(self.order_tracker.reserved_capital_by_account.keys())
        
        for account_id in all_accounts:
            try:
                stats = self.order_tracker.get_account_stats(account_id)
                tracked[account_id] = {
                    'open_order_count': stats.total_open_orders,
                    'held_capital': stats.total_held_capital,
                    'market_orders': stats.market_orders,
                    'stop_orders': stats.stop_orders,
                    'target_orders': stats.target_orders,
                    'oldest_order_age_min': stats.oldest_order_age_minutes,
                    'stale_orders': stats.stale_orders_count
                }
            except Exception as e:
                logger.warning(f"⚠️ Could not get tracked orders for {account_id}: {e}")
        
        return tracked
    
    def check_micro_cap_compliance(self, account_id: str, balance: float, held: float, order_count: int) -> tuple:
        """
        Check if account is compliant with MICRO_CAP rules
        
        Returns:
            (is_compliant, issues_list)
        """
        issues = []
        
        if not MICRO_CAPITAL_MODE:
            return True, ["MICRO_CAP mode not active"]
        
        # Check 1: Held capital should be reasonable for a single position
        if held > 0:
            # For MICRO_CAP, a single position should be around MIN_TRADE_SIZE ($5-$20)
            # Allow some margin for price fluctuation
            max_reasonable_held = MIN_TRADE_SIZE * 2  # $10-$40 range
            
            if held > max_reasonable_held and order_count > 1:
                issues.append(
                    f"⚠️ ORDER FRAGMENTATION: ${held:.2f} held across {order_count} orders "
                    f"(expected ~${MIN_TRADE_SIZE:.2f} for single position)"
                )
        
        # Check 2: Should not have many open orders
        if order_count > MAX_POSITIONS:
            issues.append(
                f"⚠️ TOO MANY ORDERS: {order_count} orders (max: {MAX_POSITIONS})"
            )
        
        # Check 3: Held capital percentage
        if balance > 0:
            held_pct = (held / balance) * 100
            if held_pct > 30:
                issues.append(
                    f"⚠️ HIGH CAPITAL HELD: {held_pct:.1f}% of balance tied up in orders"
                )
        
        is_compliant = len(issues) == 0
        return is_compliant, issues
    
    def run_audit(self) -> Dict:
        """
        Run comprehensive live balance audit
        
        Returns:
            Audit results dictionary
        """
        print("\n" + "="*80)
        print("LIVE BALANCE AUDIT - REALITY CHECK")
        print("="*80)
        print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"MICRO_CAP Mode: {'✅ ACTIVE' if MICRO_CAPITAL_MODE else '❌ INACTIVE'}")
        
        if MICRO_CAPITAL_MODE:
            print(f"\nMICRO_CAP Configuration:")
            print(f"  Max Positions: {MAX_POSITIONS}")
            print(f"  Min Trade Size: ${MIN_TRADE_SIZE:.2f}")
            print(f"  DCA Enabled: {'❌ DISABLED' if not ENABLE_DCA else '✅ ENABLED'}")
            print(f"  Multiple Entries Same Symbol: {'❌ DISABLED' if not ALLOW_MULTIPLE_ENTRIES_SAME_SYMBOL else '✅ ENABLED'}")
        
        print("="*80)
        
        # Get broker balances (reality)
        broker_balances = self.get_broker_balances()
        
        # Get tracked orders
        tracked_orders = self.get_tracked_orders()
        
        # Combine and analyze
        all_accounts = set(broker_balances.keys()) | set(tracked_orders.keys())
        
        results = {
            'timestamp': datetime.now().isoformat(),
            'micro_cap_active': MICRO_CAPITAL_MODE,
            'accounts': {},
            'overall_compliant': True
        }
        
        for account_id in sorted(all_accounts):
            print(f"\n{'─'*80}")
            print(f"📊 ACCOUNT: {account_id}")
            print(f"{'─'*80}")
            
            # Get broker data
            broker_data = broker_balances.get(account_id, {})
            total = broker_data.get('total', 0)
            available = broker_data.get('available', 0)
            held_in_positions = broker_data.get('held_in_positions', 0)
            position_count = broker_data.get('position_count', 0)
            
            # Get tracker data
            tracker_data = tracked_orders.get(account_id, {})
            open_order_count = tracker_data.get('open_order_count', 0)
            held_in_orders = tracker_data.get('held_capital', 0)
            
            # Total held (positions + orders)
            total_held = held_in_positions + held_in_orders
            
            # Print account status
            print(f"\n💰 FUNDS:")
            print(f"   Total Balance:        ${total:>10.2f}")
            print(f"   Available:            ${available:>10.2f}")
            print(f"   Held in Positions:    ${held_in_positions:>10.2f}")
            print(f"   Held in Orders:       ${held_in_orders:>10.2f}")
            print(f"   ────────────────────────────────")
            print(f"   Total Held:           ${total_held:>10.2f}")
            
            print(f"\n📦 POSITIONS & ORDERS:")
            print(f"   Open Positions:       {position_count:>10}")
            print(f"   Open Orders:          {open_order_count:>10}")
            
            # Show position details if available
            if broker_data.get('positions'):
                print(f"\n   Position Details:")
                for i, pos in enumerate(broker_data['positions'], 1):
                    symbol = pos.get('symbol', 'UNKNOWN')
                    size_usd = float(pos.get('size_usd', 0) or pos.get('current_value', 0) or 0)
                    side = pos.get('side', 'UNKNOWN')
                    print(f"     {i}. {symbol} {side} - ${size_usd:.2f}")
            
            # Show order details if available
            if tracker_data:
                print(f"\n   Order Details:")
                print(f"     Market Orders:      {tracker_data.get('market_orders', 0)}")
                print(f"     Stop Orders:        {tracker_data.get('stop_orders', 0)}")
                print(f"     Target Orders:      {tracker_data.get('target_orders', 0)}")
                if tracker_data.get('stale_orders', 0) > 0:
                    print(f"     ⚠️ Stale Orders:     {tracker_data.get('stale_orders', 0)}")
            
            # Check MICRO_CAP compliance
            if MICRO_CAPITAL_MODE and total > 0:
                is_compliant, issues = self.check_micro_cap_compliance(
                    account_id, total, total_held, open_order_count
                )
                
                print(f"\n🔍 MICRO_CAP COMPLIANCE:")
                if is_compliant:
                    print(f"   ✅ COMPLIANT")
                else:
                    print(f"   ❌ NON-COMPLIANT")
                    for issue in issues:
                        print(f"   {issue}")
                    results['overall_compliant'] = False
            
            # Store results
            results['accounts'][account_id] = {
                'total': total,
                'available': available,
                'held_in_positions': held_in_positions,
                'held_in_orders': held_in_orders,
                'total_held': total_held,
                'position_count': position_count,
                'open_order_count': open_order_count,
                'compliant': is_compliant if MICRO_CAPITAL_MODE else None,
                'issues': issues if MICRO_CAPITAL_MODE else []
            }
        
        # Overall summary
        print(f"\n{'═'*80}")
        print("📋 OVERALL SUMMARY")
        print(f"{'═'*80}")
        
        total_accounts = len(all_accounts)
        accounts_with_funds = sum(1 for acc in results['accounts'].values() if acc['total'] > 0)
        accounts_with_positions = sum(1 for acc in results['accounts'].values() if acc['position_count'] > 0)
        accounts_with_orders = sum(1 for acc in results['accounts'].values() if acc['open_order_count'] > 0)
        
        print(f"\nAccounts Found:        {total_accounts}")
        print(f"Accounts with Funds:   {accounts_with_funds}")
        print(f"Accounts with Positions: {accounts_with_positions}")
        print(f"Accounts with Orders:  {accounts_with_orders}")
        
        if MICRO_CAPITAL_MODE:
            print(f"\nMICRO_CAP Compliance:  {'✅ ALL COMPLIANT' if results['overall_compliant'] else '❌ ISSUES FOUND'}")
        
        print(f"\n{'═'*80}")
        
        if not results['overall_compliant']:
            print("\n⚠️ ACTION REQUIRED:")
            print("   MICRO_CAP hardening is NOT fully working.")
            print("   Review the issues above and address order fragmentation.")
        else:
            print("\n✅ VERIFICATION SUCCESSFUL:")
            print("   MICRO_CAP hardening is working as expected.")
            print("   Capital allocation is appropriate for micro account size.")
        
        print(f"{'═'*80}\n")
        
        return results


def main():
    """Main entry point"""
    try:
        auditor = LiveBalanceAuditor()
        results = auditor.run_audit()
        
        # Exit code based on compliance
        if MICRO_CAPITAL_MODE and not results['overall_compliant']:
            print("❌ Audit completed with compliance issues")
            return 1
        else:
            print("✅ Audit completed successfully")
            return 0
            
    except Exception as e:
        logger.error(f"❌ Audit failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())
