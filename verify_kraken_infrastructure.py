#!/usr/bin/env python3
"""
Verify Kraken Infrastructure in NIJA Trading Bot

This script verifies that all necessary Kraken integration components
are present and properly configured in the codebase.

This does NOT require API credentials - it only checks the code infrastructure.

Usage:
    python3 verify_kraken_infrastructure.py

Exit codes:
    0 = All infrastructure verified
    1 = Some infrastructure missing or broken
"""

import os
import sys
import importlib.util


def check_file_exists(filepath, description):
    """Check if a file exists"""
    full_path = os.path.join(os.path.dirname(__file__), filepath)
    exists = os.path.exists(full_path)
    status = "✅" if exists else "❌"
    print(f"  {status} {description}")
    print(f"      Path: {filepath}")
    return exists


def check_class_in_module(module_path, class_name, description):
    """Check if a class exists in a Python module"""
    try:
        full_path = os.path.join(os.path.dirname(__file__), module_path)
        spec = importlib.util.spec_from_file_location("module", full_path)
        if spec is None:
            print(f"  ❌ {description}")
            print(f"      Could not load module: {module_path}")
            return False
        
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        
        has_class = hasattr(module, class_name)
        status = "✅" if has_class else "❌"
        print(f"  {status} {description}")
        print(f"      Class: {class_name} in {module_path}")
        return has_class
    except Exception as e:
        print(f"  ❌ {description}")
        print(f"      Error: {e}")
        return False


def check_dependency(package_name, description):
    """Check if a Python package is installed"""
    try:
        __import__(package_name)
        print(f"  ✅ {description}")
        print(f"      Package: {package_name}")
        return True
    except ImportError:
        print(f"  ❌ {description}")
        print(f"      Package not found: {package_name}")
        return False


def print_header(title):
    """Print a formatted header"""
    print()
    print("=" * 80)
    print(title.center(80))
    print("=" * 80)


def print_section(title):
    """Print a formatted section header"""
    print()
    print(title)
    print("-" * 80)


def main():
    """Main verification function"""
    
    print_header("KRAKEN INFRASTRUCTURE VERIFICATION")
    print()
    print("This script verifies that Kraken integration code is present.")
    print("It does NOT test API connections (no credentials required).")
    
    all_checks_passed = True
    
    # Check core broker files
    print_section("📁 Core Integration Files")
    
    checks = [
        ("bot/broker_integration.py", "Broker Integration Module"),
        ("bot/broker_manager.py", "Broker Manager Module"),
    ]
    
    for filepath, description in checks:
        if not check_file_exists(filepath, description):
            all_checks_passed = False
    
    # Check Kraken-specific classes
    print_section("🔧 Kraken Integration Classes")
    
    class_checks = [
        ("bot/broker_integration.py", "KrakenBrokerAdapter", "Kraken Broker Adapter"),
        ("bot/broker_manager.py", "KrakenBroker", "Kraken Broker Manager"),
    ]
    
    for module_path, class_name, description in class_checks:
        if not check_class_in_module(module_path, class_name, description):
            all_checks_passed = False
    
    # Check Python dependencies
    print_section("📦 Required Python Packages")
    
    dependencies = [
        ("krakenex", "Kraken API Client (krakenex)"),
        ("pykrakenapi", "Pandas-based Kraken API Wrapper (pykrakenapi)"),
    ]
    
    for package, description in dependencies:
        if not check_dependency(package, description):
            all_checks_passed = False
    
    # Check verification tools
    print_section("🔍 Verification and Testing Tools")
    
    tools = [
        ("check_kraken_status.py", "Status Check Script"),
        ("verify_kraken_config.py", "Configuration Validator"),
        ("test_kraken_connection_live.py", "Live Connection Test"),
        ("verify_kraken_users.py", "User Configuration Verifier"),
    ]
    
    for filepath, description in tools:
        if not check_file_exists(filepath, description):
            all_checks_passed = False
    
    # Check documentation
    print_section("📚 Documentation Files")
    
    docs = [
        ("KRAKEN_CONNECTION_STATUS.md", "Connection Status Documentation"),
        ("KRAKEN_SETUP_GUIDE.md", "Setup Guide"),
        ("HOW_TO_ENABLE_KRAKEN.md", "Quick Start Guide"),
        ("MULTI_USER_SETUP_GUIDE.md", "Multi-User Setup Guide"),
    ]
    
    for filepath, description in docs:
        if not check_file_exists(filepath, description):
            # Documentation is optional, don't fail if missing
            pass
    
    # Check environment variable configuration
    print_section("⚙️  Environment Variable Configuration")
    
    print("  ℹ️  Checking .env.example for Kraken variable templates...")
    env_example_path = os.path.join(os.path.dirname(__file__), ".env.example")
    
    if os.path.exists(env_example_path):
        with open(env_example_path, 'r') as f:
            content = f.read()
            
        required_vars = [
            "KRAKEN_MASTER_API_KEY",
            "KRAKEN_MASTER_API_SECRET",
            "KRAKEN_USER_DAIVON_API_KEY",
            "KRAKEN_USER_DAIVON_API_SECRET",
            "KRAKEN_USER_TANIA_API_KEY",
            "KRAKEN_USER_TANIA_API_SECRET",
        ]
        
        for var in required_vars:
            if var in content:
                print(f"  ✅ {var} template found in .env.example")
            else:
                print(f"  ⚠️  {var} not found in .env.example (optional)")
    else:
        print("  ⚠️  .env.example not found (optional)")
    
    # Summary
    print_header("📊 VERIFICATION SUMMARY")
    
    if all_checks_passed:
        print()
        print("  ✅ ALL CRITICAL INFRASTRUCTURE CHECKS PASSED")
        print()
        print("  Kraken integration is fully installed and ready:")
        print("    • Core broker integration files present")
        print("    • Kraken adapter classes implemented")
        print("    • Required Python packages installed")
        print("    • Verification tools available")
        print()
        print("  Next steps:")
        print("    1. Configure Kraken API credentials (see KRAKEN_SETUP_GUIDE.md)")
        print("    2. Run 'python3 check_kraken_status.py' to check credential status")
        print("    3. Run 'python3 test_kraken_connection_live.py' to test connection")
        print("    4. Start the bot with './start.sh'")
        print()
        exit_code = 0
    else:
        print()
        print("  ❌ SOME INFRASTRUCTURE CHECKS FAILED")
        print()
        print("  Missing or broken components detected.")
        print("  Review the output above to identify issues.")
        print()
        print("  Common fixes:")
        print("    • Install missing packages: pip install -r requirements.txt")
        print("    • Ensure you're in the correct directory")
        print("    • Check that bot/ directory exists and is not empty")
        print()
        exit_code = 1
    
    print()
    print("=" * 80)
    print()
    
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
