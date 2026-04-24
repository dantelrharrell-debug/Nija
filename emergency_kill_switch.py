#!/usr/bin/env python3
"""
NIJA Emergency Kill Switch - CLI Tool

Quick activation/deactivation of the NIJA kill switch from command line.
Designed for <30 second emergency response.

Usage:
    python emergency_kill_switch.py activate "Reason for halt"
    python emergency_kill_switch.py deactivate "Reason for resume"
    python emergency_kill_switch.py status

For fastest activation:
    python emergency_kill_switch.py activate emergency

Author: NIJA Trading Systems
Date: February 2026
"""

import sys
import argparse
from datetime import datetime
from bot.kill_switch import get_kill_switch


def activate(reason: str):
    """Activate kill switch"""
    kill_switch = get_kill_switch()
    
    if kill_switch.is_active():
        print("\n⚠️  KILL SWITCH ALREADY ACTIVE")
        print_status(kill_switch)
        return
    
    print("\n" + "=" * 70)
    print("🚨 ACTIVATING EMERGENCY KILL SWITCH 🚨")
    print("=" * 70)
    print(f"Reason: {reason}")
    print(f"Time: {datetime.utcnow().isoformat()}")
    print("=" * 70)
    
    kill_switch.activate(reason, source="CLI")
    
    print("\n✅ KILL SWITCH ACTIVATED")
    print("=" * 70)
    print("ALL TRADING OPERATIONS HAVE BEEN HALTED")
    print("=" * 70)
    print("\nNext steps:")
    print("1. Investigate the issue that triggered the kill switch")
    print("2. Resolve the underlying problem")
    print("3. Verify system integrity")
    print("4. Use 'deactivate' command to resume (with caution)")
    print("")


def deactivate(reason: str):
    """Deactivate kill switch"""
    kill_switch = get_kill_switch()
    
    if not kill_switch.is_active():
        print("\n✅ Kill switch is already inactive")
        return
    
    print("\n" + "=" * 70)
    print("⚠️  DEACTIVATING KILL SWITCH")
    print("=" * 70)
    print(f"Reason: {reason}")
    print(f"Time: {datetime.utcnow().isoformat()}")
    print("=" * 70)
    
    # Confirm deactivation
    confirm = input("\nAre you sure you want to resume trading? (yes/no): ")
    if confirm.lower() != 'yes':
        print("\n❌ Deactivation cancelled")
        return
    
    kill_switch.deactivate(reason)
    
    print("\n✅ KILL SWITCH DEACTIVATED")
    print("=" * 70)
    print("⚠️  TRADING CAN NOW RESUME")
    print("=" * 70)
    print("\n⚠️  WARNING: Carefully monitor initial trades")
    print("⚠️  WARNING: Verify all systems are functioning correctly")
    print("")


def print_status(kill_switch=None):
    """Print kill switch status"""
    if kill_switch is None:
        kill_switch = get_kill_switch()
    
    status = kill_switch.get_status()
    
    print("\n" + "=" * 70)
    print("🔴 KILL SWITCH STATUS")
    print("=" * 70)
    print(f"Active: {'🚨 YES - TRADING HALTED' if status['is_active'] else '✅ NO - Trading allowed'}")
    print(f"Kill file exists: {status['kill_file_exists']}")
    print(f"Kill file path: {status['kill_file_path']}")
    print(f"Total activations: {kill_switch.get_activation_count()}")
    print("=" * 70)
    
    if status['recent_history']:
        print("\nRecent History:")
        print("-" * 70)
        for event in status['recent_history']:
            timestamp = event.get('timestamp', 'unknown')
            reason = event.get('reason', 'No reason provided')
            source = event.get('source', 'unknown')
            
            if 'source' in event:  # Activation event
                print(f"  🚨 ACTIVATED - {timestamp}")
                print(f"     Source: {source}")
                print(f"     Reason: {reason}")
            else:  # Deactivation event
                print(f"  🟢 DEACTIVATED - {timestamp}")
                print(f"     Reason: {reason}")
            print()
    
    print("=" * 70)


def main():
    parser = argparse.ArgumentParser(
        description='NIJA Emergency Kill Switch Control',
        epilog='For emergency halt: python emergency_kill_switch.py activate emergency'
    )
    
    parser.add_argument(
        'command',
        choices=['activate', 'deactivate', 'status'],
        help='Command to execute'
    )
    
    parser.add_argument(
        'reason',
        nargs='?',
        default='Emergency activation',
        help='Reason for activation/deactivation'
    )
    
    args = parser.parse_args()
    
    try:
        if args.command == 'activate':
            activate(args.reason)
        elif args.command == 'deactivate':
            deactivate(args.reason)
        elif args.command == 'status':
            print_status()
        
        return 0
        
    except KeyboardInterrupt:
        print("\n\n⚠️  Operation cancelled by user")
        return 1
    except Exception as e:
        print(f"\n❌ ERROR: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())
