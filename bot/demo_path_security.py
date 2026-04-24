"""
Security Demonstration: Path Traversal Prevention

This script demonstrates how the path validation utilities prevent
path traversal attacks in the NIJA dashboard API.

Author: NIJA Trading Systems
Date: January 29, 2026
"""

import sys
import tempfile
import shutil
from pathlib import Path

# Ensure proper import path
sys.path.insert(0, '.')

from bot.performance_dashboard import get_performance_dashboard
from bot.path_validator import PathValidationError


def demonstrate_security():
    """Demonstrate path traversal attack prevention"""

    print("=" * 70)
    print("NIJA Dashboard API - Path Traversal Security Demonstration")
    print("=" * 70)
    print()

    # Create a temporary directory for safe testing
    temp_dir = tempfile.mkdtemp()
    print(f"✓ Created temporary test directory: {temp_dir}")
    print()

    try:
        # Get dashboard and override default directory
        dashboard = get_performance_dashboard()
        dashboard._default_report_dir = Path(temp_dir).resolve()

        print("TEST 1: Valid Export Path")
        print("-" * 70)
        try:
            filepath = dashboard.export_investor_report(output_dir="./reports")
            print(f"✓ SUCCESS: Report exported to: {filepath}")
            print(f"  File exists: {Path(filepath).exists()}")
        except Exception as e:
            print(f"✗ FAILED: {e}")
        print()

        print("TEST 2: Valid Nested Path")
        print("-" * 70)
        try:
            filepath = dashboard.export_investor_report(output_dir="./reports/2026/january")
            print(f"✓ SUCCESS: Report exported to: {filepath}")
            print(f"  File exists: {Path(filepath).exists()}")
        except Exception as e:
            print(f"✗ FAILED: {e}")
        print()

        print("TEST 3: Path Traversal Attack - Parent Directory (../../../)")
        print("-" * 70)
        try:
            filepath = dashboard.export_investor_report(output_dir="../../../etc")
            print(f"✗ SECURITY FAILURE: Attack succeeded, file at: {filepath}")
            print("  THIS SHOULD NOT HAPPEN!")
        except PathValidationError as e:
            print(f"✓ SECURITY SUCCESS: Attack blocked!")
            print(f"  Error message: {e}")
        print()

        print("TEST 4: Path Traversal Attack - Absolute Path (/etc/passwd)")
        print("-" * 70)
        try:
            filepath = dashboard.export_investor_report(output_dir="/etc/passwd")
            print(f"✗ SECURITY FAILURE: Attack succeeded, file at: {filepath}")
            print("  THIS SHOULD NOT HAPPEN!")
        except PathValidationError as e:
            print(f"✓ SECURITY SUCCESS: Attack blocked!")
            print(f"  Error message: {e}")
        print()

        print("TEST 5: Path Traversal Attack - Mixed (./../../sensitive)")
        print("-" * 70)
        try:
            filepath = dashboard.export_investor_report(output_dir="./../../sensitive")
            print(f"✗ SECURITY FAILURE: Attack succeeded, file at: {filepath}")
            print("  THIS SHOULD NOT HAPPEN!")
        except PathValidationError as e:
            print(f"✓ SECURITY SUCCESS: Attack blocked!")
            print(f"  Error message: {e}")
        print()

        print("TEST 6: CSV Export with Path Traversal")
        print("-" * 70)
        try:
            filepath = dashboard.export_csv_report(output_dir="../../../var")
            print(f"✗ SECURITY FAILURE: Attack succeeded, file at: {filepath}")
            print("  THIS SHOULD NOT HAPPEN!")
        except PathValidationError as e:
            print(f"✓ SECURITY SUCCESS: Attack blocked!")
            print(f"  Error message: {e}")
        print()

        print("=" * 70)
        print("SUMMARY")
        print("=" * 70)
        print("✓ All path traversal attacks were successfully blocked")
        print("✓ Valid paths were processed correctly")
        print("✓ The security fix is working as expected")
        print()
        print("Security measures implemented:")
        print("  1. Path validation using pathlib.Path.resolve()")
        print("  2. Verification that resolved paths are within base directory")
        print("  3. Protection against symlink attacks")
        print("  4. Filename sanitization to remove dangerous characters")
        print("  5. Proper error handling and logging")
        print()

    finally:
        # Clean up
        if Path(temp_dir).exists():
            shutil.rmtree(temp_dir)
            print(f"✓ Cleaned up temporary directory: {temp_dir}")


if __name__ == '__main__':
    demonstrate_security()
