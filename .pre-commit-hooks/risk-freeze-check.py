#!/usr/bin/env python3
"""
Pre-commit hook to detect RISK FREEZE violations

This hook checks for changes to risk configuration files and ensures
that proper versioning and approval is in place.

Install: ln -s ../../.pre-commit-hooks/risk-freeze-check.py .git/hooks/pre-commit
Or use with pre-commit framework.
"""

import sys
import subprocess
import json
import re
from pathlib import Path


# Files that contain risk parameters (protected by RISK FREEZE)
PROTECTED_FILES = [
    'bot/risk_manager.py',
    'bot/apex_risk_manager.py',
    'bot/risk_management.py',
    'bot/user_risk_manager.py',
    'bot/validators/risk_validator.py',
    'bot/apex_config.py',
    'bot/tier_config.py',
    'bot/god_mode_config.py',
    'bot/elite_performance_config.py',
]

# Risk parameter patterns to detect
RISK_PARAM_PATTERNS = [
    r'max_position_size\s*[=:]',
    r'min_position_size\s*[=:]',
    r'max_risk_per_trade\s*[=:]',
    r'max_daily_loss\s*[=:]',
    r'max_total_exposure\s*[=:]',
    r'max_drawdown\s*[=:]',
    r'max_positions\s*[=:]',
    r'max_leverage\s*[=:]',
    r'stop_loss.*multiplier\s*[=:]',
    r'trailing.*stop\s*[=:]',
    r'take_profit.*pct\s*[=:]',
    r'position_size.*pct\s*[=:]',
    r'adx.*threshold\s*[=:]',
    r'volume.*threshold\s*[=:]',
    r'signal.*score\s*[=:]',
]


def get_staged_files():
    """Get list of staged files"""
    result = subprocess.run(
        ['git', 'diff', '--cached', '--name-only'],
        capture_output=True,
        text=True
    )
    return result.stdout.strip().split('\n')


def get_file_diff(filepath):
    """Get diff for a specific file"""
    result = subprocess.run(
        ['git', 'diff', '--cached', filepath],
        capture_output=True,
        text=True
    )
    return result.stdout


def check_risk_param_changes(diff_text):
    """Check if diff contains risk parameter changes"""
    changes = []
    
    for pattern in RISK_PARAM_PATTERNS:
        matches = re.finditer(pattern, diff_text, re.IGNORECASE)
        for match in matches:
            # Get the line containing the match
            lines = diff_text[:match.start()].split('\n')
            line_num = len(lines)
            line_text = diff_text.split('\n')[line_num - 1] if line_num <= len(diff_text.split('\n')) else ''
            
            # Check if this is an addition or modification (starts with +)
            if line_text.strip().startswith('+'):
                changes.append({
                    'pattern': pattern,
                    'line': line_text.strip()[1:].strip(),
                    'line_num': line_num
                })
    
    return changes


def check_version_increment():
    """Check if risk configuration version was incremented"""
    version_dir = Path('config/risk_versions')
    
    if not version_dir.exists():
        return False
    
    # Get list of version files
    staged_files = get_staged_files()
    version_files = [f for f in staged_files if f.startswith('config/risk_versions/RISK_CONFIG_v')]
    
    return len(version_files) > 0


def main():
    """Main pre-commit hook logic"""
    print("🔒 Checking RISK FREEZE compliance...")
    
    staged_files = get_staged_files()
    
    # Check for changes to protected files
    protected_changes = []
    for filepath in staged_files:
        if any(filepath.endswith(pf) or pf in filepath for pf in PROTECTED_FILES):
            diff = get_file_diff(filepath)
            risk_changes = check_risk_param_changes(diff)
            
            if risk_changes:
                protected_changes.append({
                    'file': filepath,
                    'changes': risk_changes
                })
    
    if not protected_changes:
        print("✅ No risk parameter changes detected")
        return 0
    
    # Risk parameter changes detected
    print("\n" + "=" * 80)
    print("🚨 RISK FREEZE VIOLATION DETECTED")
    print("=" * 80)
    print()
    print("The following risk parameter changes were detected:")
    print()
    
    for change in protected_changes:
        print(f"📄 {change['file']}")
        for param_change in change['changes']:
            print(f"   • {param_change['line']}")
        print()
    
    # Check if version was incremented
    version_incremented = check_version_increment()
    
    print("⚠️  All risk parameter changes require:")
    print("   1. ✅ Backtesting (minimum 3 months)")
    print("   2. ✅ Paper Trading (minimum 2 weeks)")
    print("   3. ✅ Version documentation")
    print("   4. ✅ Multi-stakeholder approval")
    print()
    
    if version_incremented:
        print("✅ Risk configuration version incremented")
        print()
        print("📋 APPROVAL CHECKLIST:")
        print("   - [ ] Backtest results documented")
        print("   - [ ] Paper trading results documented")
        print("   - [ ] Technical Lead approval signature")
        print("   - [ ] Risk Manager approval signature")
        print("   - [ ] Strategy Developer approval signature")
        print()
        print("✅ Commit allowed (version incremented)")
        print("   ⚠️  Ensure all approvals are documented before merging!")
        print()
        return 0
    else:
        print("❌ No risk configuration version increment detected")
        print()
        print("📋 TO PROCEED:")
        print("   1. Create new version: config/risk_versions/RISK_CONFIG_vX.Y.Z.json")
        print("   2. Document all changes and approvals")
        print("   3. Include backtest and paper trading results")
        print("   4. Stage the new version file")
        print("   5. Commit again")
        print()
        print("OR use emergency override (requires post-emergency approval):")
        print("   git commit --no-verify")
        print()
        print("See RISK_FREEZE_POLICY.md for full details.")
        print()
        print("=" * 80)
        return 1


if __name__ == '__main__':
    sys.exit(main())
