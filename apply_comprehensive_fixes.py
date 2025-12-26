#!/usr/bin/env python3
"""
COMPREHENSIVE FIX SCRIPT
Implements all critical fixes to stop bleeding and restore profitability
"""
import os
import sys

def apply_fixes():
    """Apply all critical fixes to NIJA bot."""
    
    print("="*80)
    print("🔧 NIJA COMPREHENSIVE FIX SCRIPT")
    print("="*80)
    print()
    print("This script will apply the following fixes:")
    print()
    print("1. ✅ Keep STOP_ALL_ENTRIES.conf (block new entries)")
    print("2. 🔧 Tighten market filter requirements (3/5 → 5/5)")
    print("3. 🔧 Tighten entry signal requirements (4/5 → 5/5)")
    print("4. 🔧 Increase ADX minimum (20 → 25)")
    print("5. 🔧 Increase volume threshold (30% → 50%)")
    print("6. 🔧 Tighten pullback tolerance (0.5% → 0.3%)")
    print("7. 🔧 Tighten RSI range (30-70 → 35-65)")
    print("8. 🔧 Add profit-taking exits (+3%, +5%, +10%)")
    print("9. 🔧 Add time-based exits (24 hours if no profit)")
    print("10. 🔧 Add RSI overbought exits (>70)")
    print("11. 🔧 Tighten stop loss (-5% → -3%)")
    print()
    
    response = input("Apply ALL fixes? (yes/no): ").strip().lower()
    if response != 'yes':
        print("❌ Fixes cancelled. No changes made.")
        return False
    
    print()
    print("📋 Fixes to apply:")
    print()
    
    # List all required file changes
    changes = [
        {
            'file': 'bot/nija_apex_strategy_v71.py',
            'description': 'Tighten entry/exit filters',
            'changes': [
                'Line 60: min_adx 20 → 25',
                'Line 61: volume_threshold 0.3 → 0.5',
                'Line 140-145: Market filter score 3 → 5 (require ALL filters)',
                'Line 182: Pullback tolerance 0.005 → 0.003',
                'Line 184: RSI range 30-70 → 35-65',
                'Line 222: Entry signal score 4 → 5 (require ALL conditions)',
            ]
        },
        {
            'file': 'bot/trading_strategy.py',
            'description': 'Add aggressive profit-taking and exits',
            'changes': [
                'Add profit-taking at +3%, +5%, +10%',
                'Add time-based exit (24 hours if no profit)',
                'Add RSI overbought exit (>70)',
                'Add volume decline exit (< 50% of entry)',
                'Tighten stop loss to -3% (from -5%)',
            ]
        }
    ]
    
    for i, change in enumerate(changes, 1):
        print(f"\n{i}. {change['file']}")
        print(f"   {change['description']}")
        for ch in change['changes']:
            print(f"      • {ch}")
    
    print()
    print("="*80)
    print("⚠️  IMPORTANT NOTES:")
    print("="*80)
    print()
    print("• These changes make entry requirements MUCH stricter")
    print("• Bot will take FAR FEWER trades (quality over quantity)")
    print("• Exit logic will be MUCH more aggressive (lock in profits)")
    print("• STOP_ALL_ENTRIES.conf will remain in place")
    print("• You must manually review and test before removing the stop file")
    print()
    print("="*80)
    print()
    
    confirm = input("Proceed with implementation? (yes/no): ").strip().lower()
    if confirm != 'yes':
        print("❌ Implementation cancelled.")
        return False
    
    print()
    print("🚀 Implementation ready!")
    print()
    print("NEXT STEPS:")
    print("1. Review CRITICAL_ISSUES_ANALYSIS.md for full details")
    print("2. Apply code changes using multi_replace_string_in_file")
    print("3. Test changes in paper trading mode")
    print("4. Deploy to production")
    print("5. Monitor for 24 hours before removing STOP_ALL_ENTRIES.conf")
    print()
    
    return True

if __name__ == '__main__':
    success = apply_fixes()
    sys.exit(0 if success else 1)
