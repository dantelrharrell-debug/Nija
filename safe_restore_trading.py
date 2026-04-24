#!/usr/bin/env python3
"""
NIJA Safe Trading Recovery Tool

Safely restore trading from EMERGENCY_STOP state to a safe operational mode.
This tool ensures proper state synchronization between kill switch and state machine.

Usage:
    python safe_restore_trading.py status          # Check current status
    python safe_restore_trading.py restore         # Restore to safe DRY_RUN mode
    python safe_restore_trading.py reset           # Reset to OFF state only
    
Safety Features:
    ✅ Never auto-enables LIVE trading
    ✅ Defaults to DRY_RUN (simulation mode)
    ✅ Validates state consistency
    ✅ Requires user confirmation
    ✅ Logs all state changes

Author: NIJA Trading Systems
Date: February 2026
"""

import os
import sys
import argparse
import logging
from datetime import datetime
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Add bot directory to path for imports
bot_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bot')
sys.path.insert(0, bot_dir)

# Import kill switch and state machine directly
from kill_switch import get_kill_switch
from trading_state_machine import get_state_machine, TradingState


def print_banner():
    """Print tool banner"""
    print("\n" + "=" * 80)
    print("🔧 NIJA SAFE TRADING RECOVERY TOOL")
    print("=" * 80)
    print("Safely restore trading state without risking capital")
    print("=" * 80 + "\n")


def check_status():
    """Check and display current trading status"""
    print_banner()
    
    # Get kill switch status
    kill_switch = get_kill_switch()
    ks_active = kill_switch.is_active()
    ks_status = kill_switch.get_status()
    
    # Get state machine status
    state_machine = get_state_machine()
    current_state = state_machine.get_current_state()
    
    # Display status
    print("📊 CURRENT STATUS")
    print("-" * 80)
    print(f"Trading State Machine: {current_state.value}")
    print(f"Kill Switch Active:    {'🚨 YES - TRADING HALTED' if ks_active else '✅ NO'}")
    print(f"Kill File Exists:      {ks_status['kill_file_exists']}")
    print(f"Can Trade:             {'❌ NO' if ks_active or current_state == TradingState.EMERGENCY_STOP else '✅ YES'}")
    print("-" * 80)
    
    # Check for inconsistency
    inconsistent = False
    if current_state == TradingState.EMERGENCY_STOP and not ks_active:
        inconsistent = True
        print("\n⚠️  STATE INCONSISTENCY DETECTED:")
        print("   • State machine is in EMERGENCY_STOP")
        print("   • But kill switch is DEACTIVATED")
        print("   • Trading is blocked unnecessarily")
        print("\n💡 Solution: Run 'python safe_restore_trading.py restore'")
    elif current_state != TradingState.EMERGENCY_STOP and ks_active:
        inconsistent = True
        print("\n⚠️  STATE INCONSISTENCY DETECTED:")
        print("   • Kill switch is ACTIVE")
        print("   • But state machine is not in EMERGENCY_STOP")
        print("   • This should trigger automatic state transition")
        print("\n💡 Solution: Kill switch will force state machine to EMERGENCY_STOP")
    elif current_state == TradingState.EMERGENCY_STOP and ks_active:
        print("\n🚨 EMERGENCY STOP IS ACTIVE")
        print("   Both kill switch and state machine are in emergency mode")
        print("\n   Steps to recover:")
        print("   1. Investigate why emergency stop was activated")
        print("   2. Resolve the underlying issue")
        print("   3. Run: python emergency_kill_switch.py deactivate 'Issue resolved'")
        print("   4. Then run: python safe_restore_trading.py restore")
    elif current_state == TradingState.OFF:
        print("\n✅ SAFE STATE")
        print("   Bot is in OFF state (no trading)")
        print("\n   To start trading safely:")
        print("   1. Run: python safe_restore_trading.py restore (for DRY_RUN mode)")
        print("   2. Or manually transition to desired state via API/UI")
    elif current_state == TradingState.DRY_RUN:
        print("\n✅ SAFE SIMULATION MODE")
        print("   Bot is in DRY_RUN mode (paper trading)")
        print("   NO REAL MONEY AT RISK")
    elif current_state == TradingState.LIVE_ACTIVE:
        print("\n⚠️  LIVE TRADING ACTIVE")
        print("   Bot is trading with REAL CAPITAL")
        print("   Monitor carefully!")
    
    # Recent history
    if ks_status['recent_history']:
        print("\n📜 RECENT KILL SWITCH HISTORY:")
        print("-" * 80)
        for event in ks_status['recent_history'][-3:]:
            timestamp = event.get('timestamp', 'Unknown')
            reason = event.get('reason', 'No reason provided')
            source = event.get('source', '')
            if source:
                print(f"   {timestamp} - {source}: {reason}")
            else:
                print(f"   {timestamp} - {reason}")
    
    print("\n" + "=" * 80 + "\n")
    
    return {
        'state': current_state,
        'kill_switch_active': ks_active,
        'inconsistent': inconsistent
    }


def reset_to_off(force: bool = False):
    """Reset state machine to OFF state"""
    print_banner()
    print("🔄 RESETTING TO OFF STATE\n")
    
    # Check current status
    kill_switch = get_kill_switch()
    state_machine = get_state_machine()
    current_state = state_machine.get_current_state()
    
    # Verify kill switch is not active
    if kill_switch.is_active():
        print("❌ ERROR: Cannot reset while kill switch is active")
        print("   Please deactivate kill switch first:")
        print("   python emergency_kill_switch.py deactivate 'Reason for resume'\n")
        return False
    
    # Check if already in OFF state
    if current_state == TradingState.OFF:
        print("✅ Already in OFF state - no action needed\n")
        return True
    
    # Confirm action
    print(f"Current state: {current_state.value}")
    print(f"Target state:  {TradingState.OFF.value}")
    print("\nThis will:")
    print("  • Transition state machine to OFF")
    print("  • Stop all trading operations")
    print("  • Require manual re-activation")
    
    if not force:
        confirm = input("\nProceed? (yes/no): ")
        if confirm.lower() != 'yes':
            print("\n❌ Reset cancelled\n")
            return False
    else:
        print("\n⚡ --force flag detected — skipping confirmation prompt\n")
    
    # Perform reset
    try:
        state_machine.transition_to(
            TradingState.OFF,
            "Manual reset via safe_restore_trading.py"
        )
        print("\n✅ Successfully reset to OFF state")
        print("   Trading is now disabled")
        print("\n   To enable trading:")
        print("   • Run: python safe_restore_trading.py restore (for safe DRY_RUN mode)")
        print("   • Or use UI/API to manually transition states\n")
        return True
    except Exception as e:
        print(f"\n❌ ERROR: Failed to reset state: {e}\n")
        logger.error(f"State reset failed: {e}", exc_info=True)
        return False


def restore_safe_mode(force: bool = False):
    """Restore trading to safe DRY_RUN mode"""
    print_banner()
    print("🔄 RESTORING TO SAFE MODE (DRY_RUN)\n")
    
    # Check current status
    status = check_status()
    
    # If kill switch is active, cannot restore
    if status['kill_switch_active']:
        print("\n❌ ERROR: Cannot restore while kill switch is active")
        print("   Please deactivate kill switch first:")
        print("   python emergency_kill_switch.py deactivate 'Reason for resume'\n")
        return False
    
    current_state = status['state']
    
    # If already in DRY_RUN, nothing to do
    if current_state == TradingState.DRY_RUN:
        print("\n✅ Already in safe DRY_RUN mode")
        print("   NO REAL MONEY AT RISK\n")
        return True
    
    # Explain what will happen
    print("\n" + "=" * 80)
    print("📋 RESTORATION PLAN")
    print("=" * 80)
    print(f"Current State: {current_state.value}")
    print(f"Target State:  {TradingState.DRY_RUN.value}")
    print("\nThis will:")
    print("  • Transition state machine through valid states")
    print("  • End in safe DRY_RUN (simulation) mode")
    print("  • NO REAL MONEY WILL BE AT RISK")
    print("  • All trading will be simulated")
    print("\nAfter restoration:")
    print("  • Test bot behavior in DRY_RUN mode")
    print("  • Verify all systems are working correctly")
    print("  • Manually enable LIVE trading only when ready")
    print("=" * 80 + "\n")
    
    # Confirm action (skip when --force is used for non-interactive environments)
    if not force:
        confirm = input("Proceed with safe restoration? (yes/no): ")
        if confirm.lower() != 'yes':
            print("\n❌ Restoration cancelled\n")
            return False
    else:
        print("⚡ --force flag detected — skipping confirmation prompt\n")
    
    # Perform restoration
    state_machine = get_state_machine()
    
    try:
        # Step 1: If in EMERGENCY_STOP, transition to OFF first
        if current_state == TradingState.EMERGENCY_STOP:
            print("\n   Step 1/2: Transitioning EMERGENCY_STOP → OFF...")
            state_machine.transition_to(
                TradingState.OFF,
                "Safe recovery: Clearing emergency stop"
            )
            print("   ✅ Transitioned to OFF")
            current_state = TradingState.OFF
        
        # Step 2: Transition to DRY_RUN
        if current_state == TradingState.OFF:
            print("   Step 2/2: Transitioning OFF → DRY_RUN...")
            state_machine.transition_to(
                TradingState.DRY_RUN,
                "Safe recovery: Enabling simulation mode"
            )
            print("   ✅ Transitioned to DRY_RUN")
        elif current_state == TradingState.LIVE_ACTIVE:
            print("   Transitioning LIVE_ACTIVE → DRY_RUN...")
            state_machine.transition_to(
                TradingState.DRY_RUN,
                "Safe recovery: Switching to simulation mode"
            )
            print("   ✅ Transitioned to DRY_RUN")
        elif current_state == TradingState.LIVE_PENDING_CONFIRMATION:
            print("   Transitioning LIVE_PENDING_CONFIRMATION → OFF → DRY_RUN...")
            state_machine.transition_to(TradingState.OFF, "Safe recovery: Clearing pending state")
            state_machine.transition_to(TradingState.DRY_RUN, "Safe recovery: Enabling simulation mode")
            print("   ✅ Transitioned to DRY_RUN")
        
        # Success!
        print("\n" + "=" * 80)
        print("✅ RESTORATION COMPLETE")
        print("=" * 80)
        print("Bot is now in safe DRY_RUN mode")
        print("\n🟡 SIMULATION MODE ACTIVE:")
        print("   • All trading is simulated")
        print("   • NO REAL ORDERS will be placed")
        print("   • NO REAL MONEY at risk")
        print("   • Safe to test bot behavior")
        print("\n⚠️  To enable LIVE trading:")
        print("   1. Thoroughly test bot in DRY_RUN mode")
        print("   2. Verify all systems are working correctly")
        print("   3. Use UI/API to manually transition to LIVE mode")
        print("   4. Confirm understanding of risks")
        print("=" * 80 + "\n")
        
        return True
        
    except Exception as e:
        print(f"\n❌ ERROR: Restoration failed: {e}\n")
        logger.error(f"State restoration failed: {e}", exc_info=True)
        return False


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description='NIJA Safe Trading Recovery Tool',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python safe_restore_trading.py status           # Check current status
  python safe_restore_trading.py restore          # Restore to safe DRY_RUN mode
  python safe_restore_trading.py restore --force  # Restore without confirmation (CI/CD)
  python safe_restore_trading.py reset            # Reset to OFF state only
  python safe_restore_trading.py reset --force    # Reset without confirmation (CI/CD)

Safety:
  • Never auto-enables LIVE trading
  • Defaults to DRY_RUN (simulation mode)
  • Requires user confirmation (unless --force is set)
  • Validates state consistency
        """
    )
    
    parser.add_argument(
        'action',
        choices=['status', 'restore', 'reset'],
        help='Action to perform'
    )
    
    parser.add_argument(
        '--force',
        action='store_true',
        default=False,
        help='Skip confirmation prompts (for non-interactive/CI environments)'
    )
    
    args = parser.parse_args()
    
    try:
        if args.action == 'status':
            check_status()
        elif args.action == 'reset':
            success = reset_to_off(force=args.force)
            sys.exit(0 if success else 1)
        elif args.action == 'restore':
            success = restore_safe_mode(force=args.force)
            sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\n❌ Cancelled by user\n")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ ERROR: {e}\n")
        logger.error(f"Unexpected error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
