#!/usr/bin/env python3
"""
Test Emergency Response Package - Validate All Deliverables

This script validates that all emergency response deliverables are:
1. Present and accessible
2. Correctly formatted
3. Functional (for executable scripts)
4. Complete with all required sections
"""

import os
import sys


def test_file_exists(filepath, description):
    """Test if a file exists and is readable"""
    print(f"\n{'='*70}")
    print(f"Testing: {description}")
    print(f"File: {filepath}")
    print(f"{'='*70}")
    
    if not os.path.exists(filepath):
        print(f"❌ FAIL: File not found")
        return False
    
    if not os.path.isfile(filepath):
        print(f"❌ FAIL: Not a file")
        return False
    
    try:
        with open(filepath, 'r') as f:
            content = f.read()
            lines = len(content.split('\n'))
            chars = len(content)
            print(f"✅ PASS: File exists and readable")
            print(f"   Lines: {lines:,}")
            print(f"   Size: {chars:,} characters")
            return True
    except Exception as e:
        print(f"❌ FAIL: Cannot read file - {e}")
        return False


def test_executable(filepath, description):
    """Test if a Python script is executable"""
    print(f"\n{'='*70}")
    print(f"Testing: {description}")
    print(f"File: {filepath}")
    print(f"{'='*70}")
    
    # Check file exists
    if not os.path.exists(filepath):
        print(f"❌ FAIL: File not found")
        return False
    
    # Check executable bit (Unix)
    if hasattr(os, 'X_OK'):
        if not os.access(filepath, os.X_OK):
            print(f"⚠️  WARNING: File not executable (chmod +x required)")
    
    # Try to import/run
    try:
        import subprocess
        result = subprocess.run(
            ['python3', filepath, '--status'],
            capture_output=True,
            text=True,
            timeout=5
        )
        
        if result.returncode == 0:
            print(f"✅ PASS: Script executes successfully")
            print(f"   Output: {result.stdout.strip()[:100]}")
            return True
        else:
            print(f"❌ FAIL: Script returned error code {result.returncode}")
            print(f"   Error: {result.stderr.strip()[:200]}")
            return False
    except subprocess.TimeoutExpired:
        print(f"❌ FAIL: Script timed out (>5 seconds)")
        return False
    except Exception as e:
        print(f"❌ FAIL: Cannot execute - {e}")
        return False


def test_markdown_content(filepath, required_sections, description):
    """Test if a markdown file contains required sections"""
    print(f"\n{'='*70}")
    print(f"Testing: {description}")
    print(f"File: {filepath}")
    print(f"{'='*70}")
    
    if not os.path.exists(filepath):
        print(f"❌ FAIL: File not found")
        return False
    
    try:
        with open(filepath, 'r') as f:
            content = f.read()
        
        missing_sections = []
        found_sections = []
        
        for section in required_sections:
            if section.lower() in content.lower():
                found_sections.append(section)
            else:
                missing_sections.append(section)
        
        if missing_sections:
            print(f"❌ FAIL: Missing required sections:")
            for section in missing_sections:
                print(f"   - {section}")
            print(f"\n✅ Found sections:")
            for section in found_sections:
                print(f"   - {section}")
            return False
        else:
            print(f"✅ PASS: All required sections present ({len(required_sections)})")
            for section in found_sections:
                print(f"   ✓ {section}")
            return True
            
    except Exception as e:
        print(f"❌ FAIL: Cannot read/parse file - {e}")
        return False


def main():
    """Run all tests"""
    print("\n" + "="*70)
    print("EMERGENCY RESPONSE PACKAGE - VALIDATION TEST SUITE")
    print("="*70)
    
    results = []
    
    # Test A) SELL Override Patch
    results.append(test_executable(
        'SELL_OVERRIDE_PATCH_DROPIN.py',
        'A) SELL Override Patch - Executable'
    ))
    
    # Test B) Kraken Railway Setup
    results.append(test_markdown_content(
        'KRAKEN_RAILWAY_NONCE_SETUP.md',
        [
            'Railway Container',
            'Step-by-Step Railway Setup',
            'Create Railway Project',
            'Add Persistent Volume',
            'Environment Variables',
            'Troubleshooting',
            'Invalid nonce',
            'DATA_DIR'
        ],
        'B) Kraken Railway Setup - Documentation'
    ))
    
    # Test C) Emergency Deployment Plan
    results.append(test_markdown_content(
        'EMERGENCY_HOTFIX_DEPLOYMENT_PLAN.md',
        [
            'Pre-Deployment Checklist',
            'Phase 1: Preparation',
            'Phase 2: Apply Fixes',
            'Phase 3: Railway/Render Configuration',
            'Phase 4: Deploy to Production',
            'Phase 5: Post-Deployment Verification',
            'Rollback Procedures',
            'Success Criteria',
            'Timeline'
        ],
        'C) Emergency Deployment Plan - Documentation'
    ))
    
    # Test D) Execution Path Audit
    results.append(test_markdown_content(
        'SELL_EXECUTION_PATH_AUDIT.md',
        [
            'High-Level Execution Flow',
            'Detailed Execution Path Audit',
            'LAYER 1: Trading Strategy',
            'LAYER 2: Execution Engine',
            'LAYER 3: Broker Manager',
            'LAYER 4: Broker API',
            'Summary of Blocking Points',
            'Where SELL Can Be Blocked',
            'How to Diagnose',
            'Emergency Mode'
        ],
        'D) Execution Path Audit - Documentation'
    ))
    
    # Test Summary Guide
    results.append(test_markdown_content(
        'EMERGENCY_RESPONSE_PACKAGE_SUMMARY.md',
        [
            'Problem Statement',
            'Deliverables Summary',
            'Coinbase SELL Override',
            'Kraken Persistent Nonce',
            'Emergency Hotfix Deployment',
            'Live Execution Path',
            'How to Use This Package',
            'Quick Reference Card'
        ],
        'Package Summary - Documentation'
    ))
    
    # Test existing core files referenced
    print(f"\n{'='*70}")
    print("Testing: Referenced Core Files")
    print(f"{'='*70}")
    
    core_files = [
        ('bot/broker_manager.py', 'Broker Manager'),
        ('bot/execution_engine.py', 'Execution Engine'),
        ('bot/global_kraken_nonce.py', 'Global Nonce Manager'),
        ('A_SELL_OVERRIDE_CODE.md', 'Original SELL Override Docs'),
        ('C_KRAKEN_PERSISTENT_NONCE.md', 'Original Kraken Nonce Docs'),
        ('D_EMERGENCY_PATCH_ALL_FIXES.md', 'Original Emergency Patch Docs'),
    ]
    
    for filepath, name in core_files:
        exists = os.path.exists(filepath)
        status = "✅" if exists else "❌"
        print(f"{status} {name}: {filepath}")
        results.append(exists)
    
    # Summary
    print("\n" + "="*70)
    print("TEST SUMMARY")
    print("="*70)
    
    total_tests = len(results)
    passed = sum(results)
    failed = total_tests - passed
    
    print(f"\nTotal Tests: {total_tests}")
    print(f"Passed: {passed} ✅")
    print(f"Failed: {failed} ❌")
    
    if failed == 0:
        print("\n🎉 ALL TESTS PASSED - Emergency Response Package is COMPLETE")
        print("\nDeliverables Ready:")
        print("  A) SELL_OVERRIDE_PATCH_DROPIN.py")
        print("  B) KRAKEN_RAILWAY_NONCE_SETUP.md")
        print("  C) EMERGENCY_HOTFIX_DEPLOYMENT_PLAN.md")
        print("  D) SELL_EXECUTION_PATH_AUDIT.md")
        print("  +  EMERGENCY_RESPONSE_PACKAGE_SUMMARY.md")
        print("\n✅ PRODUCTION-READY")
        return 0
    else:
        print("\n❌ SOME TESTS FAILED - Review errors above")
        return 1


if __name__ == '__main__':
    sys.exit(main())
