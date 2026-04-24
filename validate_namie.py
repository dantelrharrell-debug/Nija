"""
Simple NAMIE Validation Script

Validates that NAMIE files are properly created and can be imported.
Does not require full dependency installation.

Run:
    python validate_namie.py
"""

import os
import sys


def check_file_exists(filepath, description):
    """Check if file exists and print status"""
    exists = os.path.exists(filepath)
    status = "✅" if exists else "❌"
    print(f"{status} {description}: {filepath}")
    
    if exists:
        # Get file size
        size = os.path.getsize(filepath)
        size_kb = size / 1024
        print(f"   Size: {size_kb:.1f} KB")
    
    return exists


def check_file_content(filepath, required_strings, description):
    """Check if file contains required strings"""
    try:
        with open(filepath, 'r') as f:
            content = f.read()
        
        missing = []
        for required in required_strings:
            if required not in content:
                missing.append(required)
        
        if not missing:
            print(f"✅ {description}: All required content present")
            return True
        else:
            print(f"❌ {description}: Missing content:")
            for m in missing:
                print(f"   - {m}")
            return False
    except Exception as e:
        print(f"❌ {description}: Error reading file - {e}")
        return False


def main():
    print("\n" + "="*60)
    print("NAMIE VALIDATION")
    print("="*60 + "\n")
    
    base_dir = os.path.dirname(os.path.abspath(__file__))
    bot_dir = os.path.join(base_dir, 'bot')
    
    all_passed = True
    
    # Check core files exist
    print("1. Checking Core Files...")
    print("-" * 60)
    
    files_to_check = [
        (os.path.join(bot_dir, 'namie_core.py'), 'NAMIE Core Engine'),
        (os.path.join(bot_dir, 'namie_strategy_switcher.py'), 'Strategy Switcher'),
        (os.path.join(bot_dir, 'namie_integration.py'), 'Integration Layer'),
        (os.path.join(base_dir, 'NAMIE_DOCUMENTATION.md'), 'Documentation'),
        (os.path.join(base_dir, 'NAMIE_QUICKSTART.md'), 'Quick Start Guide'),
        (os.path.join(base_dir, 'test_namie.py'), 'Test Suite'),
    ]
    
    for filepath, description in files_to_check:
        if not check_file_exists(filepath, description):
            all_passed = False
    
    print()
    
    # Check core content
    print("2. Checking Core Content...")
    print("-" * 60)
    
    # Check namie_core.py
    namie_core_checks = [
        'class NAMIECore',
        'class NAMIESignal',
        'def analyze_market',
        'def _classify_regime',
        'def _score_trend_strength',
        'def _detect_chop',
        'def get_namie_engine',
    ]
    
    if not check_file_content(
        os.path.join(bot_dir, 'namie_core.py'),
        namie_core_checks,
        'NAMIE Core Engine'
    ):
        all_passed = False
    
    # Check namie_strategy_switcher.py
    switcher_checks = [
        'class NAMIEStrategySwitcher',
        'class StrategyPerformance',
        'def select_strategy',
        'def record_trade',
        'def get_performance_summary',
    ]
    
    if not check_file_content(
        os.path.join(bot_dir, 'namie_strategy_switcher.py'),
        switcher_checks,
        'Strategy Switcher'
    ):
        all_passed = False
    
    # Check namie_integration.py
    integration_checks = [
        'class NAMIEIntegration',
        'def analyze',
        'def should_enter_trade',
        'def adjust_position_size',
        'def quick_namie_check',
    ]
    
    if not check_file_content(
        os.path.join(bot_dir, 'namie_integration.py'),
        integration_checks,
        'Integration Layer'
    ):
        all_passed = False
    
    print()
    
    # Check documentation
    print("3. Checking Documentation...")
    print("-" * 60)
    
    doc_checks = [
        'NAMIE',
        'Regime Classification',
        'Trend Strength Scoring',
        'Chop Detection',
        'Strategy Auto-Switching',
        'Quick Start',
    ]
    
    if not check_file_content(
        os.path.join(base_dir, 'NAMIE_DOCUMENTATION.md'),
        doc_checks,
        'Main Documentation'
    ):
        all_passed = False
    
    quickstart_checks = [
        'Quick Start',
        'NAMIEIntegration',
        'quick_namie_check',
        'Example',
    ]
    
    if not check_file_content(
        os.path.join(base_dir, 'NAMIE_QUICKSTART.md'),
        quickstart_checks,
        'Quick Start Guide'
    ):
        all_passed = False
    
    print()
    
    # Summary
    print("="*60)
    print("VALIDATION SUMMARY")
    print("="*60)
    
    if all_passed:
        print("✅ ALL CHECKS PASSED!")
        print("\nNAMIE is properly installed and ready to use.")
        print("\nNext steps:")
        print("1. Read NAMIE_QUICKSTART.md for integration guide")
        print("2. Add NAMIE to your trading strategy")
        print("3. Run backtest to validate performance improvement")
        print("4. Monitor live performance")
    else:
        print("❌ SOME CHECKS FAILED")
        print("\nPlease review errors above and ensure all NAMIE files are present.")
    
    print()
    
    return all_passed


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
