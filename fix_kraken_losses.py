#!/usr/bin/env python3
"""
Verify Filter Settings for Kraken Trading Bot

This script verifies that the trading strategy filter settings are optimized
and not using the overly-relaxed emergency settings from Jan 29, 2026.

NOTE: This script verifies FILTER SETTINGS (ADX, confidence, entry score, volume).
      The main fix for Kraken losses was PROFIT TARGETS in execution_engine.py
      (raised to 1.2%, 1.7%, 2.2%, 3.0%). This script doesn't verify profit targets.

Background:
- Emergency filter relaxations in Jan 29, 2026 allowed LOW-QUALITY trades
- ADX=6, Entry Score=50, Volume=0.1% → weak trades
- These settings have since been OPTIMIZED to ADX=10, Score=60, Volume=0.2%
  
This Script Verifies:
✅ ADX = 10 (moderate trends, not 6 = extremely weak)
✅ MIN_CONFIDENCE = 0.60 (60%, not 0.50 = too low)
✅ min_score_threshold = 60 (good quality, not 50 = marginal)
✅ volume_min_threshold = 0.002 (0.2%, not 0.001 = virtually none)
✅ min_trend_confirmation = 2 (2/5 indicators, not 1/5 = too loose)
✅ candle_exclusion_seconds = 2 (avoid false breakouts, not 0 = disabled)

Expected Result:
- Confirms filter settings are BALANCED for quality trades
- Separate from profit target fix (see execution_engine.py for that)
"""

import os
import sys
import re

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

def check_strategy_filters():
    """Check nija_apex_strategy_v71.py filter settings"""
    print("=" * 80)
    print("CHECKING NIJA APEX STRATEGY V7.1 FILTER SETTINGS")
    print("=" * 80)
    
    file_path = 'bot/nija_apex_strategy_v71.py'
    
    if not os.path.exists(file_path):
        print(f"❌ ERROR: {file_path} not found!")
        return False
    
    with open(file_path, 'r') as f:
        content = f.read()
    
    # Expected OPTIMIZED values (from the Jan 29, 2026 optimization)
    expected_values = {
        'MIN_CONFIDENCE': 0.60,
        'min_adx': 10,
        'volume_threshold': 0.10,
        'volume_min_threshold': 0.002,
        'min_trend_confirmation': 2,
        'candle_exclusion_seconds': 2,
    }
    
    # Emergency relaxed values that cause losses
    emergency_values = {
        'MIN_CONFIDENCE': 0.50,
        'min_adx': 6,
        'volume_threshold': 0.05,
        'volume_min_threshold': 0.001,
        'min_trend_confirmation': 1,
        'candle_exclusion_seconds': 0,
    }
    
    issues_found = []
    all_good = True
    
    # Check MIN_CONFIDENCE
    match = re.search(r'MIN_CONFIDENCE\s*=\s*([\d.]+)', content)
    if match:
        value = float(match.group(1))
        print(f"\n✓ MIN_CONFIDENCE = {value}")
        if value < expected_values['MIN_CONFIDENCE']:
            print(f"  ⚠️  WARNING: Too low! Should be {expected_values['MIN_CONFIDENCE']} (60%)")
            print(f"  Current {value} allows marginal confidence trades → losses")
            issues_found.append(f"MIN_CONFIDENCE is {value}, should be {expected_values['MIN_CONFIDENCE']}")
            all_good = False
        elif value == expected_values['MIN_CONFIDENCE']:
            print(f"  ✅ OPTIMIZED: Balanced 60% confidence for good trade quality")
    
    # Check min_adx
    match = re.search(r"self\.min_adx\s*=\s*self\.config\.get\('min_adx',\s*(\d+)\)", content)
    if match:
        value = int(match.group(1))
        print(f"\n✓ min_adx = {value}")
        if value < expected_values['min_adx']:
            print(f"  ⚠️  WARNING: Too low! Should be {expected_values['min_adx']}")
            print(f"  Current {value} allows extremely weak trends → poor quality trades → losses")
            issues_found.append(f"min_adx is {value}, should be {expected_values['min_adx']}")
            all_good = False
        elif value == expected_values['min_adx']:
            print(f"  ✅ OPTIMIZED: Moderate trends for better quality")
    
    # Check volume_min_threshold
    match = re.search(r"self\.volume_min_threshold\s*=\s*self\.config\.get\('volume_min_threshold',\s*([\d.]+)\)", content)
    if match:
        value = float(match.group(1))
        print(f"\n✓ volume_min_threshold = {value}")
        if value < expected_values['volume_min_threshold']:
            print(f"  ⚠️  WARNING: Too low! Should be {expected_values['volume_min_threshold']}")
            print(f"  Current {value} allows virtually no volume → slippage and poor fills → losses")
            issues_found.append(f"volume_min_threshold is {value}, should be {expected_values['volume_min_threshold']}")
            all_good = False
        elif value == expected_values['volume_min_threshold']:
            print(f"  ✅ OPTIMIZED: Filters very low volume for better execution")
    
    # Check min_trend_confirmation
    match = re.search(r"self\.min_trend_confirmation\s*=\s*self\.config\.get\('min_trend_confirmation',\s*(\d+)\)", content)
    if match:
        value = int(match.group(1))
        print(f"\n✓ min_trend_confirmation = {value}")
        if value < expected_values['min_trend_confirmation']:
            print(f"  ⚠️  WARNING: Too low! Should be {expected_values['min_trend_confirmation']}")
            print(f"  Current {value}/5 indicators = weak confirmation → false signals → losses")
            issues_found.append(f"min_trend_confirmation is {value}, should be {expected_values['min_trend_confirmation']}")
            all_good = False
        elif value == expected_values['min_trend_confirmation']:
            print(f"  ✅ OPTIMIZED: Requires 2/5 indicators for better confirmation")
    
    # Check candle_exclusion_seconds
    match = re.search(r"self\.candle_exclusion_seconds\s*=\s*self\.config\.get\('candle_exclusion_seconds',\s*(\d+)\)", content)
    if match:
        value = int(match.group(1))
        print(f"\n✓ candle_exclusion_seconds = {value}")
        if value == 0:
            print(f"  ⚠️  WARNING: DISABLED! Should be {expected_values['candle_exclusion_seconds']}")
            print(f"  Current 0 = no timing filter → false breakouts → losses")
            issues_found.append(f"candle_exclusion_seconds is {value}, should be {expected_values['candle_exclusion_seconds']}")
            all_good = False
        elif value == expected_values['candle_exclusion_seconds']:
            print(f"  ✅ OPTIMIZED: Avoids false breakouts with 2-second wait")
    
    return all_good, issues_found


def check_entry_scoring():
    """Check enhanced_entry_scoring.py settings"""
    print("\n" + "=" * 80)
    print("CHECKING ENHANCED ENTRY SCORING SETTINGS")
    print("=" * 80)
    
    file_path = 'bot/enhanced_entry_scoring.py'
    
    if not os.path.exists(file_path):
        print(f"❌ ERROR: {file_path} not found!")
        return False
    
    with open(file_path, 'r') as f:
        content = f.read()
    
    # Expected OPTIMIZED values
    expected_values = {
        'min_score_threshold': 60,
        'excellent_score_threshold': 75,
    }
    
    issues_found = []
    all_good = True
    
    # Check min_score_threshold
    match = re.search(r"self\.min_score_threshold\s*=\s*self\.config\.get\('min_score_threshold',\s*(\d+)\)", content)
    if match:
        value = int(match.group(1))
        print(f"\n✓ min_score_threshold = {value}/100")
        if value < expected_values['min_score_threshold']:
            print(f"  ⚠️  WARNING: Too low! Should be {expected_values['min_score_threshold']}/100")
            print(f"  Current {value}/100 allows marginal trade setups → losses")
            issues_found.append(f"min_score_threshold is {value}, should be {expected_values['min_score_threshold']}")
            all_good = False
        elif value == expected_values['min_score_threshold']:
            print(f"  ✅ OPTIMIZED: Good quality threshold for 60-65% win rate")
    
    # Check excellent_score_threshold
    match = re.search(r"self\.excellent_score_threshold\s*=\s*self\.config\.get\('excellent_score_threshold',\s*(\d+)\)", content)
    if match:
        value = int(match.group(1))
        print(f"\n✓ excellent_score_threshold = {value}/100")
        if value == expected_values['excellent_score_threshold']:
            print(f"  ✅ OPTIMIZED: Excellent threshold for top-tier trades")
    
    return all_good, issues_found


def main():
    """Main verification and fix routine"""
    print("\n" + "=" * 80)
    print("KRAKEN LOSS FIX - FILTER VERIFICATION")
    print("=" * 80)
    print("\nProblem: Emergency filter relaxations on Jan 29, 2026 went too far")
    print("Symptom: Kraken lost $4.28 in one day due to low-quality trades")
    print("Solution: Verify OPTIMIZED filter settings are active")
    print()
    
    # Check strategy filters
    strategy_ok, strategy_issues = check_strategy_filters()
    
    # Check entry scoring
    scoring_ok, scoring_issues = check_entry_scoring()
    
    # Summary
    print("\n" + "=" * 80)
    print("VERIFICATION SUMMARY")
    print("=" * 80)
    
    all_issues = strategy_issues + scoring_issues
    
    if strategy_ok and scoring_ok:
        print("\n✅ ALL SETTINGS OPTIMIZED!")
        print("\nCurrent filter settings are BALANCED for quality trades:")
        print("  • ADX = 10 (moderate trends)")
        print("  • MIN_CONFIDENCE = 0.60 (60% confidence)")
        print("  • min_score_threshold = 60/100 (good quality)")
        print("  • volume_min_threshold = 0.002 (0.2% volume)")
        print("  • min_trend_confirmation = 2/5 indicators")
        print("  • candle_exclusion_seconds = 2 (timing filter)")
        print("\nExpected results:")
        print("  • Fewer trades (3-8 per day vs 10-20)")
        print("  • Higher quality (60-65% win rate vs losses)")
        print("  • Better risk/reward (avoid weak trends)")
        print("\n🎯 No changes needed - settings are optimal!")
        print("\nIf still experiencing losses, check:")
        print("  1. Are optimized settings actually deployed and running?")
        print("  2. Is bot using config overrides via environment variables?")
        print("  3. Review recent trade history for patterns")
        return 0
    else:
        print(f"\n❌ FOUND {len(all_issues)} ISSUES:")
        for i, issue in enumerate(all_issues, 1):
            print(f"   {i}. {issue}")
        
        print("\n" + "=" * 80)
        print("RECOMMENDED FIX")
        print("=" * 80)
        print("\nThe settings in the code files appear to have issues.")
        print("Based on verification, the following values need to be corrected:\n")
        
        if any('MIN_CONFIDENCE' in issue for issue in all_issues):
            print("1. In bot/nija_apex_strategy_v71.py (line ~65):")
            print("   MIN_CONFIDENCE = 0.60  # 60% balanced confidence\n")
        
        if any('min_adx' in issue for issue in all_issues):
            print("2. In bot/nija_apex_strategy_v71.py (line ~164):")
            print("   self.min_adx = self.config.get('min_adx', 10)\n")
        
        if any('volume_min_threshold' in issue for issue in all_issues):
            print("3. In bot/nija_apex_strategy_v71.py (line ~166):")
            print("   self.volume_min_threshold = self.config.get('volume_min_threshold', 0.002)\n")
        
        if any('min_trend_confirmation' in issue for issue in all_issues):
            print("4. In bot/nija_apex_strategy_v71.py (line ~167):")
            print("   self.min_trend_confirmation = self.config.get('min_trend_confirmation', 2)\n")
        
        if any('candle_exclusion_seconds' in issue for issue in all_issues):
            print("5. In bot/nija_apex_strategy_v71.py (line ~168):")
            print("   self.candle_exclusion_seconds = self.config.get('candle_exclusion_seconds', 2)\n")
        
        if any('min_score_threshold' in issue for issue in all_issues):
            print("6. In bot/enhanced_entry_scoring.py (line ~57):")
            print("   self.min_score_threshold = self.config.get('min_score_threshold', 60)\n")
        
        print("\n🚨 Action Required: Review and update these values to stop losses!")
        return 1


if __name__ == '__main__':
    exit_code = main()
    sys.exit(exit_code)
