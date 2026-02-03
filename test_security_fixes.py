#!/usr/bin/env python3
"""
Security Validation Tests for NIJA Trading Bot
Tests the security fixes applied during reviewer-mode walkthrough
"""

import re
import os
import sys

def test_webhook_secret_validation():
    """Test that webhook secret cannot have default value"""
    print("\n🔍 Testing webhook secret validation...")
    
    # Check that hardcoded default is removed
    with open('bot/tradingview_webhook.py', 'r') as f:
        content = f.read()
        
    # Should NOT contain the old default
    if "'nija_webhook_2025'" in content and "WEBHOOK_SECRET = os.getenv('TRADINGVIEW_WEBHOOK_SECRET', 'nija_webhook_2025')" in content:
        print("  ❌ FAILED: Hardcoded default webhook secret still present")
        return False
    
    # Should require env var
    if "raise ValueError" not in content or "TRADINGVIEW_WEBHOOK_SECRET environment variable is required" not in content:
        print("  ⚠️  WARNING: Webhook secret validation may not be strict enough")
        return False
    
    print("  ✅ PASSED: Webhook secret validation enforced")
    return True

def test_position_size_validation():
    """Test that position size limits are enforced"""
    print("\n🔍 Testing position size validation...")
    
    with open('bot/tradingview_webhook.py', 'r') as f:
        content = f.read()
    
    checks = [
        ("Hard cap $10,000", "position_size > 10000"),
        ("Percentage-based limit", "available_balance * 0.20"),
        ("Minimum size check", "position_size < 0.005"),
    ]
    
    all_passed = True
    for check_name, pattern in checks:
        if pattern in content:
            print(f"  ✅ PASSED: {check_name} enforced")
        else:
            print(f"  ❌ FAILED: {check_name} not found")
            all_passed = False
    
    return all_passed

def test_symbol_validation():
    """Test that symbol validation regex is present"""
    print("\n🔍 Testing symbol validation...")
    
    with open('bot/tradingview_webhook.py', 'r') as f:
        content = f.read()
    
    # Check for regex pattern
    if "SYMBOL_PATTERN" in content and r"^[A-Z0-9]{1,10}-USD$" in content:
        print("  ✅ PASSED: Symbol validation regex present")
        
        # Check it's being used
        if "SYMBOL_PATTERN.match" in content:
            print("  ✅ PASSED: Symbol validation is applied")
            return True
        else:
            print("  ⚠️  WARNING: Symbol pattern defined but not used")
            return False
    else:
        print("  ❌ FAILED: Symbol validation regex not found")
        return False

def test_multi_order_limit():
    """Test that multi-order limit is enforced"""
    print("\n🔍 Testing multi-order limit...")
    
    with open('bot/tradingview_webhook.py', 'r') as f:
        content = f.read()
    
    if "MAX_ORDERS_PER_REQUEST" in content:
        print("  ✅ PASSED: Multi-order limit constant defined")
        
        if "len(orders) > MAX_ORDERS_PER_REQUEST" in content:
            print("  ✅ PASSED: Multi-order limit check enforced")
            return True
        else:
            print("  ⚠️  WARNING: Limit defined but not checked")
            return False
    else:
        print("  ❌ FAILED: Multi-order limit not found")
        return False

def test_cors_configuration():
    """Test that CORS is properly configured"""
    print("\n🔍 Testing CORS configuration...")
    
    with open('fastapi_backend.py', 'r') as f:
        content = f.read()
    
    all_passed = True
    
    # Should NOT have wildcard default
    if "allow_origins = os.getenv('ALLOWED_ORIGINS', '*')" in content:
        print("  ❌ FAILED: CORS still has wildcard default")
        all_passed = False
    else:
        print("  ✅ PASSED: CORS wildcard default removed")
    
    # Should have restricted methods
    if 'allow_methods=["*"]' in content and 'CORSMiddleware' in content:
        print("  ⚠️  WARNING: CORS allows all methods")
        all_passed = False
    else:
        print("  ✅ PASSED: CORS methods restricted")
    
    return all_passed

def test_jwt_secret_validation():
    """Test that JWT secret is required"""
    print("\n🔍 Testing JWT secret validation...")
    
    with open('fastapi_backend.py', 'r') as f:
        content = f.read()
    
    # Should NOT have default token generation
    if "JWT_SECRET_KEY = os.getenv('JWT_SECRET_KEY', secrets.token_hex(32))" in content:
        print("  ❌ FAILED: JWT secret still has auto-generated default")
        return False
    
    # Should require env var
    if "raise ValueError" in content and "JWT_SECRET_KEY environment variable is required" in content:
        print("  ✅ PASSED: JWT secret validation enforced")
        return True
    else:
        print("  ⚠️  WARNING: JWT secret validation may not be strict enough")
        return False

def test_exception_handling():
    """Test that exception handling is improved"""
    print("\n🔍 Testing exception handling...")
    
    with open('bot/tradingview_webhook.py', 'r') as f:
        content = f.read()
    
    # Should have specific exception catches
    specific_exceptions = ["ValueError", "KeyError"]
    all_found = True
    
    for exc in specific_exceptions:
        if f"except {exc}" in content:
            print(f"  ✅ PASSED: Catches specific exception: {exc}")
        else:
            print(f"  ⚠️  WARNING: Missing specific exception handler for: {exc}")
            all_found = False
    
    return all_found

def test_env_example_documentation():
    """Test that .env.example documents new security requirements"""
    print("\n🔍 Testing .env.example documentation...")
    
    with open('.env.example', 'r') as f:
        content = f.read()
    
    required_vars = [
        "TRADINGVIEW_WEBHOOK_SECRET",
        "JWT_SECRET_KEY",
        "ALLOWED_ORIGINS"
    ]
    
    all_found = True
    for var in required_vars:
        if var in content:
            print(f"  ✅ PASSED: {var} documented")
        else:
            print(f"  ❌ FAILED: {var} not documented")
            all_found = False
    
    return all_found

def main():
    """Run all security validation tests"""
    print("="*70)
    print("NIJA Security Fixes Validation")
    print("="*70)
    
    tests = [
        ("Webhook Secret Validation", test_webhook_secret_validation),
        ("Position Size Validation", test_position_size_validation),
        ("Symbol Validation", test_symbol_validation),
        ("Multi-Order Limit", test_multi_order_limit),
        ("CORS Configuration", test_cors_configuration),
        ("JWT Secret Validation", test_jwt_secret_validation),
        ("Exception Handling", test_exception_handling),
        (".env.example Documentation", test_env_example_documentation),
    ]
    
    results = {}
    for test_name, test_func in tests:
        try:
            results[test_name] = test_func()
        except Exception as e:
            print(f"  ⚠️  ERROR running test: {e}")
            results[test_name] = False
    
    # Summary
    print("\n" + "="*70)
    print("SUMMARY")
    print("="*70)
    
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    for test_name, passed_test in results.items():
        status = "✅ PASSED" if passed_test else "❌ FAILED"
        print(f"{status}: {test_name}")
    
    print(f"\n{passed}/{total} tests passed")
    
    if passed == total:
        print("\n🎉 All security fixes validated successfully!")
        return 0
    else:
        print("\n⚠️  Some tests failed - review fixes needed")
        return 1

if __name__ == "__main__":
    sys.exit(main())
