#!/usr/bin/env python3
"""
Test script for Kraken order validation and tier enforcement.

This script tests the new validation logic without placing real orders.
"""

import sys
import os

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

from broker_adapters import BrokerAdapterFactory, TradeIntent, OrderIntent
from tier_config import get_tier_from_balance, get_tier_config, validate_trade_size, TradingTier


def test_tier_detection():
    """Test tier detection from balance."""
    print("\n" + "="*60)
    print("TEST 1: Tier Detection")
    print("="*60)
    
    test_cases = [
        (10, "Below minimum"),
        (25, TradingTier.SAVER),
        (75, TradingTier.SAVER),
        (100, TradingTier.INVESTOR),
        (250, TradingTier.INCOME),
        (1000, TradingTier.LIVABLE),
        (5000, TradingTier.BALLER),
        (10000, TradingTier.BALLER),
    ]
    
    for balance, expected in test_cases:
        tier = get_tier_from_balance(balance)
        status = "✅" if tier == expected or (balance < 25 and expected == "Below minimum") else "❌"
        print(f"{status} Balance ${balance:>6.2f} → {tier.value:>8} (expected: {expected if isinstance(expected, str) else expected.value})")


def test_tier_validation():
    """Test trade size validation for tiers."""
    print("\n" + "="*60)
    print("TEST 2: Tier Trade Size Validation")
    print("="*60)
    
    test_cases = [
        # (balance, trade_size, should_pass)
        (50, 1.0, False),   # SAVER: below $2 min
        (50, 2.0, True),    # SAVER: at $2 min
        (50, 10.0, False),  # SAVER: above $5 max (too risky)
        (150, 5.0, False),  # INVESTOR: below $10 min
        (150, 10.0, True),  # INVESTOR: at $10 min
        (150, 50.0, False), # INVESTOR: above $25 max (too risky)
        (500, 15.0, True),  # INCOME: at $15 min
        (500, 50.0, True),  # INCOME: at $50 max
        (2000, 25.0, True), # LIVABLE: at $25 min
        (10000, 50.0, True),# BALLER: at $50 min
    ]
    
    for balance, trade_size, should_pass in test_cases:
        tier = get_tier_from_balance(balance)
        is_valid, reason = validate_trade_size(trade_size, tier, balance)
        
        status = "✅" if is_valid == should_pass else "❌"
        result = "PASS" if is_valid else "FAIL"
        print(f"{status} [{tier.value:>8}] ${balance:>6.2f} balance, ${trade_size:>5.2f} trade → {result}")
        if not is_valid:
            print(f"     Reason: {reason}")


def test_broker_adapter_validation():
    """Test broker adapter validation."""
    print("\n" + "="*60)
    print("TEST 3: Broker Adapter Validation")
    print("="*60)
    
    # Test Kraken adapter
    kraken_adapter = BrokerAdapterFactory.create_adapter("kraken")
    
    test_cases = [
        # (symbol, side, size_usd, should_pass, reason)
        ("BTC-USD", "buy", 5.0, False, "Below Kraken $10 min"),
        ("BTC-USD", "buy", 10.0, True, "At Kraken $10 min"),
        ("BTC-USD", "buy", 50.0, True, "Above Kraken $10 min"),
        ("ETH/USD", "sell", 15.0, True, "Valid USD pair"),
        ("SOL-USDT", "buy", 20.0, True, "Valid USDT pair"),
        ("XRP-BUSD", "buy", 10.0, False, "Kraken doesn't support BUSD"),
    ]
    
    for symbol, side, size_usd, should_pass, description in test_cases:
        intent_type = OrderIntent.BUY if side == "buy" else OrderIntent.SELL
        intent = TradeIntent(
            intent_type=intent_type,
            symbol=symbol,
            quantity=size_usd / 100,  # Assume $100 price for simplicity
            size_usd=size_usd,
            size_type="quote",
            force_execute=False,
            reason="Test"
        )
        
        validated = kraken_adapter.validate_and_adjust(intent)
        status = "✅" if validated.valid == should_pass else "❌"
        result = "PASS" if validated.valid else "FAIL"
        
        print(f"{status} {symbol:>10} {side:>4} ${size_usd:>5.2f} → {result}")
        print(f"     {description}")
        if not validated.valid and validated.error_message:
            print(f"     Error: {validated.error_message}")
        if validated.warnings:
            for warning in validated.warnings:
                print(f"     Warning: {warning}")


def test_symbol_conversion():
    """Test symbol conversion for Kraken."""
    print("\n" + "="*60)
    print("TEST 4: Symbol Conversion")
    print("="*60)
    
    adapter = BrokerAdapterFactory.create_adapter("kraken")
    
    test_cases = [
        ("BTC-USD", "BTC/USD"),
        ("ETH/USDT", "ETH/USDT"),
        ("SOL-USD", "SOL/USD"),
        ("XRP.USD", "XRP/USD"),
        ("ADAUSD", "ADA/USD"),  # No separator case
    ]
    
    for input_symbol, expected_output in test_cases:
        normalized = adapter.normalize_symbol(input_symbol)
        status = "✅" if normalized == expected_output else "⚠️"
        print(f"{status} {input_symbol:>10} → {normalized:>10} (expected: {expected_output})")


def main():
    """Run all tests."""
    print("\n" + "="*60)
    print("NIJA KRAKEN VALIDATION & TIER ENFORCEMENT TESTS")
    print("="*60)
    
    try:
        test_tier_detection()
        test_tier_validation()
        test_broker_adapter_validation()
        test_symbol_conversion()
        
        print("\n" + "="*60)
        print("✅ ALL TESTS COMPLETED")
        print("="*60)
        print("\nNote: These tests validate logic only.")
        print("No real orders were placed on Kraken.")
        print("\nTo test with real orders:")
        print("  1. Ensure Kraken API credentials in .env")
        print("  2. Start with a small test trade ($10-$20)")
        print("  3. Check logs for validation messages")
        print("  4. Verify trade in Kraken UI")
        
    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
