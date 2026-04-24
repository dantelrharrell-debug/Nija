#!/usr/bin/env python3
"""
Test script for the pre-commit terminology check hook.
Run this to verify the hook is working correctly.
"""

import subprocess
import os
import tempfile
import sys

def run_check():
    """Run the terminology check hook"""
    result = subprocess.run(
        ['.pre-commit-hooks/check-terminology.sh'],
        capture_output=True,
        text=True,
        cwd=os.getcwd()
    )
    return result.returncode, result.stdout, result.stderr

def create_test_file(filename, content):
    """Create a test file and stage it"""
    with open(filename, 'w') as f:
        f.write(content)
    # Use -f to force add files that might be in gitignore
    subprocess.run(['git', 'add', '-f', filename], check=True)

def cleanup_test_file(filename):
    """Remove test file from git and filesystem"""
    subprocess.run(['git', 'rm', '--cached', filename], 
                   capture_output=True, check=False)
    if os.path.exists(filename):
        os.remove(filename)

def test_prohibited_terms():
    """Test that prohibited terms are caught"""
    print("\n" + "="*70)
    print("TEST 1: Prohibited Terms Detection")
    print("="*70)
    
    bad_code = '''import logging
logger = logging.getLogger(__name__)

def example():
    logger.info("MASTER controls all users")
    logger.warning("Primary master broker initialized")
'''
    
    filename = 'sample_prohibited.py'
    try:
        create_test_file(filename, bad_code)
        returncode, stdout, stderr = run_check()
        
        if returncode != 0:
            print("✅ PASS: Hook correctly rejected prohibited terminology")
            print("\nOutput preview:")
            print(stdout[:500] if len(stdout) > 500 else stdout)
        else:
            print("❌ FAIL: Hook did not catch prohibited terms")
            sys.exit(1)
    finally:
        cleanup_test_file(filename)

def test_neutral_terms():
    """Test that neutral terms are accepted"""
    print("\n" + "="*70)
    print("TEST 2: Neutral Terminology Acceptance")
    print("="*70)
    
    good_code = '''import logging
logger = logging.getLogger(__name__)

def example():
    logger.info("Platform account initialized")
    logger.warning("Active platform broker selected")
    logger.info("Platform + user accounts trading independently")
'''
    
    filename = 'sample_neutral.py'
    try:
        create_test_file(filename, good_code)
        returncode, stdout, stderr = run_check()
        
        if returncode == 0:
            print("✅ PASS: Hook correctly accepted neutral terminology")
            print(f"\nOutput: {stdout.strip()}")
        else:
            print("❌ FAIL: Hook incorrectly rejected neutral terms")
            print(f"Output: {stdout}")
            sys.exit(1)
    finally:
        cleanup_test_file(filename)

def test_allowed_exceptions():
    """Test that allowed exceptions work"""
    print("\n" + "="*70)
    print("TEST 3: Allowed Exceptions")
    print("="*70)
    
    exception_code = '''import logging
logger = logging.getLogger(__name__)

def example():
    # These should be allowed
    logger.info("Hard controls module loaded")
    logger.debug(f"Variable is_master = {is_master}")
'''
    
    filename = 'sample_exceptions.py'
    try:
        create_test_file(filename, exception_code)
        returncode, stdout, stderr = run_check()
        
        if returncode == 0:
            print("✅ PASS: Hook correctly allowed exceptions")
            print(f"\nOutput: {stdout.strip()}")
        else:
            print("❌ FAIL: Hook incorrectly rejected allowed exceptions")
            print(f"Output: {stdout}")
            sys.exit(1)
    finally:
        cleanup_test_file(filename)

def test_test_file_exclusion():
    """Test that test files are excluded"""
    print("\n" + "="*70)
    print("TEST 4: Test File Exclusion")
    print("="*70)
    
    test_code = '''import logging
logger = logging.getLogger(__name__)

def test_something():
    # This has prohibited terms but should be ignored in test files
    logger.info("MASTER controls all users")
'''
    
    filename = 'test_sample_file.py'
    try:
        create_test_file(filename, test_code)
        returncode, stdout, stderr = run_check()
        
        if returncode == 0:
            print("✅ PASS: Hook correctly excluded test files")
            print(f"\nOutput: {stdout.strip()}")
        else:
            print("❌ FAIL: Hook incorrectly checked test files")
            print(f"Output: {stdout}")
            sys.exit(1)
    finally:
        cleanup_test_file(filename)

if __name__ == '__main__':
    print("\n" + "🔍 TERMINOLOGY CHECK HOOK - TEST SUITE" + "\n")
    print("This test suite validates the pre-commit hook for terminology.")
    
    try:
        test_prohibited_terms()
        test_neutral_terms()
        test_allowed_exceptions()
        test_test_file_exclusion()
        
        print("\n" + "="*70)
        print("✅ ALL TESTS PASSED")
        print("="*70)
        print("\nThe pre-commit hook is working correctly!")
        print("\nTo enable it:")
        print("  1. Install pre-commit: pip install pre-commit")
        print("  2. Install hooks: pre-commit install")
        print("  3. Hooks will run automatically on git commit")
        print()
        
    except Exception as e:
        print(f"\n❌ TEST SUITE FAILED: {e}")
        sys.exit(1)
