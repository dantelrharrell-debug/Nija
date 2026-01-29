#!/usr/bin/env python3
"""
NIJA Profit Optimization - Quick Start Script

This script helps you quickly enable profit optimization features.
It will:
1. Check if optimization modules are available
2. Validate your configuration
3. Show you what will be enabled
4. Generate a ready-to-use .env file

Usage:
    python3 scripts/enable_profit_optimization.py
"""

import os
import sys
import shutil

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'bot'))

def check_optimization_modules():
    """Check if profit optimization modules are available."""
    print("🔍 Checking for profit optimization modules...")
    print("=" * 70)

    modules_found = {}

    # Check for profit optimization config
    try:
        import profit_optimization_config
        modules_found['profit_optimization_config'] = True
        print("✅ profit_optimization_config.py - FOUND")
    except ImportError:
        modules_found['profit_optimization_config'] = False
        print("❌ profit_optimization_config.py - NOT FOUND")

    # Check for enhanced scoring
    try:
        import enhanced_entry_scoring
        modules_found['enhanced_entry_scoring'] = True
        print("✅ enhanced_entry_scoring.py - FOUND")
    except ImportError:
        modules_found['enhanced_entry_scoring'] = False
        print("❌ enhanced_entry_scoring.py - NOT FOUND (optional)")

    # Check for regime detection
    try:
        import market_regime_detector
        modules_found['market_regime_detector'] = True
        print("✅ market_regime_detector.py - FOUND")
    except ImportError:
        modules_found['market_regime_detector'] = False
        print("❌ market_regime_detector.py - NOT FOUND (optional)")

    # Check for broker fee optimizer
    try:
        import broker_fee_optimizer
        modules_found['broker_fee_optimizer'] = True
        print("✅ broker_fee_optimizer.py - FOUND")
    except ImportError:
        modules_found['broker_fee_optimizer'] = False
        print("❌ broker_fee_optimizer.py - NOT FOUND (optional)")

    print("=" * 70)

    # Summary
    total = len(modules_found)
    found = sum(modules_found.values())

    print(f"\n📊 Summary: {found}/{total} modules available")

    if modules_found['profit_optimization_config']:
        print("✅ Core profit optimization: READY")
    else:
        print("❌ Core profit optimization: NOT AVAILABLE")
        print("   → Profit optimization config is required")
        return False

    if modules_found['enhanced_entry_scoring'] and modules_found['market_regime_detector']:
        print("✅ Advanced features: READY (enhanced scoring + regime detection)")
    elif modules_found['enhanced_entry_scoring'] or modules_found['market_regime_detector']:
        print("⚠️  Advanced features: PARTIALLY AVAILABLE")
        print("   → Some advanced features will work, others will use defaults")
    else:
        print("ℹ️  Advanced features: USING DEFAULTS")
        print("   → Core profit optimization will still work")

    return modules_found['profit_optimization_config']


def show_optimization_features():
    """Show what features will be enabled."""
    print("\n🚀 Profit Optimization Features")
    print("=" * 70)

    features = [
        ("Enhanced Entry Scoring", "0-100 weighted system vs basic 1-5 scoring"),
        ("Market Regime Detection", "Adaptive parameters based on market conditions"),
        ("Stepped Profit-Taking", "Partial exits at 0.8%-5% profit levels"),
        ("Fee Optimization", "Smart routing to best exchange (saves 53% on fees)"),
        ("Multi-Exchange Trading", "Coinbase + Kraken for 2x opportunities"),
        ("Dynamic Position Sizing", "2-10% per position (was 20%, enables more positions)"),
    ]

    for name, desc in features:
        print(f"✅ {name}")
        print(f"   {desc}")
        print()


def setup_env_file():
    """Set up optimized .env file."""
    print("📝 Setting up .env file...")
    print("=" * 70)

    env_template = ".env.profit_optimized"
    env_file = ".env"
    env_backup = ".env.backup"

    # Check if template exists
    if not os.path.exists(env_template):
        print(f"❌ Template file not found: {env_template}")
        print("   Please ensure .env.profit_optimized exists in the repository root.")
        return False

    # Backup existing .env if it exists
    if os.path.exists(env_file):
        print(f"ℹ️  Existing .env file found")
        response = input("   Do you want to backup and replace it? (yes/no): ").strip().lower()

        if response not in ['yes', 'y']:
            print("ℹ️  Keeping existing .env file")
            print("   To enable optimizations, manually copy settings from .env.profit_optimized")
            return False

        # Create backup
        shutil.copy(env_file, env_backup)
        print(f"✅ Backed up existing .env to {env_backup}")

    # Copy template
    shutil.copy(env_template, env_file)
    print(f"✅ Created new .env from template")
    print()
    print("⚠️  IMPORTANT: You must add your API credentials to .env")
    print("   Required:")
    print("   - COINBASE_API_KEY")
    print("   - COINBASE_API_SECRET")
    print("   - KRAKEN_MASTER_API_KEY (optional but recommended)")
    print("   - KRAKEN_MASTER_API_SECRET (optional but recommended)")
    print()

    return True


def main():
    """Main entry point."""
    print()
    print("=" * 70)
    print("NIJA PROFIT OPTIMIZATION - QUICK START")
    print("=" * 70)
    print()

    # Step 1: Check modules
    if not check_optimization_modules():
        print()
        print("❌ SETUP FAILED")
        print("   Core modules are missing. Please ensure you have the latest code.")
        print("   Run: git pull origin main")
        sys.exit(1)

    # Step 2: Show features
    show_optimization_features()

    # Step 3: Setup .env
    print("=" * 70)
    setup_env_file()

    # Final instructions
    print()
    print("=" * 70)
    print("✅ SETUP COMPLETE!")
    print("=" * 70)
    print()
    print("Next steps:")
    print("1. Edit .env and add your API credentials")
    print("2. Restart NIJA: ./start.sh")
    print("3. Check logs for: '🚀 PROFIT OPTIMIZATION CONFIGURATION LOADED'")
    print()
    print("📖 For detailed documentation, see: PROFIT_OPTIMIZATION_GUIDE.md")
    print()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  Setup cancelled by user")
        sys.exit(0)
    except Exception as e:
        print(f"\n\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
