#!/usr/bin/env python3
"""
Test script for Micro Capital Mode Configuration
Validates all configuration parameters and dynamic scaling logic
"""

import sys
import os

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from bot.micro_capital_config import (
    MICRO_CAPITAL_CONFIG,
    get_dynamic_config,
    apply_micro_capital_config,
    get_config_summary,
    get_environment_variables,
)


def test_base_configuration():
    """Test that all base configuration parameters are present"""
    print("Testing base configuration...")
    
    required_keys = [
        'micro_capital_mode', 'mode', 'primary_broker', 'secondary_broker',
        'live_trading', 'pro_mode', 'copy_trading',
        'min_balance_to_trade', 'min_trade_size',
        'max_positions', 'max_position_pct', 'risk_per_trade',
        'daily_max_loss', 'max_drawdown', 'position_sizer',
        'kelly_weight', 'volatility_weight', 'equity_weight',
        'min_signal_score', 'min_ai_confidence', 'min_risk_reward',
        'trade_only', 'market_regime_engine', 'signal_ensemble', 'ai_trade_filter',
        'leverage_enabled', 'arbitrage',
        'auto_shutoff_on_errors', 'max_consecutive_losses',
        'force_cash_buffer', 'exchange_priority',
        'min_balance_kraken', 'min_balance_coinbase',
        'log_signal_rejections', 'log_entry_block_reasons',
        'reset_strategy_state', 'clear_entry_blocks', 'flush_cached_balances',
    ]
    
    missing_keys = [key for key in required_keys if key not in MICRO_CAPITAL_CONFIG]
    
    if missing_keys:
        print(f"  ❌ FAILED: Missing configuration keys: {missing_keys}")
        return False
    
    print(f"  ✅ PASSED: All {len(required_keys)} required configuration keys present")
    return True


def test_dynamic_scaling():
    """Test dynamic scaling at different equity levels"""
    print("\nTesting dynamic scaling...")
    
    test_cases = [
        # (equity, expected_max_positions, expected_risk, expected_copy, expected_leverage)
        (15.0, 2, 3.0, False, False),
        (100.0, 2, 3.0, False, False),
        (249.99, 2, 3.0, False, False),
        (250.0, 3, 4.0, False, False),
        (499.99, 3, 4.0, False, False),
        (500.0, 4, 4.0, True, False),
        (999.99, 4, 4.0, True, False),
        (1000.0, 6, 5.0, True, True),
        (5000.0, 6, 5.0, True, True),
    ]
    
    all_passed = True
    
    for equity, exp_pos, exp_risk, exp_copy, exp_lev in test_cases:
        config = get_dynamic_config(equity)
        
        checks = [
            (config['max_positions'] == exp_pos, f"max_positions: expected {exp_pos}, got {config['max_positions']}"),
            (config['risk_per_trade'] == exp_risk, f"risk_per_trade: expected {exp_risk}, got {config['risk_per_trade']}"),
            (config['copy_trading'] == exp_copy, f"copy_trading: expected {exp_copy}, got {config['copy_trading']}"),
            (config['leverage_enabled'] == exp_lev, f"leverage_enabled: expected {exp_lev}, got {config['leverage_enabled']}"),
        ]
        
        equity_passed = all(check[0] for check in checks)
        
        if equity_passed:
            print(f"  ✅ PASSED: Equity ${equity:.2f}")
        else:
            print(f"  ❌ FAILED: Equity ${equity:.2f}")
            for check, msg in checks:
                if not check:
                    print(f"      - {msg}")
            all_passed = False
    
    return all_passed


def test_environment_variables():
    """Test environment variable generation"""
    print("\nTesting environment variable generation...")
    
    # Test without equity
    env_vars = get_environment_variables()
    
    required_env_vars = [
        'MICRO_CAPITAL_MODE', 'MODE', 'PRIMARY_BROKER', 'SECONDARY_BROKER',
        'LIVE_TRADING', 'PRO_MODE', 'COPY_TRADING_MODE',
        'MINIMUM_TRADING_BALANCE', 'MIN_CASH_TO_BUY',
        'MAX_CONCURRENT_POSITIONS', 'MAX_POSITION_PCT', 'RISK_PER_TRADE',
    ]
    
    missing_env_vars = [var for var in required_env_vars if var not in env_vars]
    
    if missing_env_vars:
        print(f"  ❌ FAILED: Missing environment variables: {missing_env_vars}")
        return False
    
    print(f"  ✅ PASSED: All {len(required_env_vars)} required environment variables generated")
    
    # Test with equity to check dynamic values
    env_vars_500 = get_environment_variables(equity=500.0)
    
    if env_vars_500['MAX_CONCURRENT_POSITIONS'] != '4':
        print(f"  ❌ FAILED: MAX_CONCURRENT_POSITIONS at $500 should be '4', got '{env_vars_500['MAX_CONCURRENT_POSITIONS']}'")
        return False
    
    if env_vars_500['COPY_TRADING_MODE'] != 'MASTER_FOLLOW':
        print(f"  ❌ FAILED: COPY_TRADING_MODE at $500 should be 'MASTER_FOLLOW', got '{env_vars_500['COPY_TRADING_MODE']}'")
        return False
    
    print(f"  ✅ PASSED: Dynamic environment variables scale correctly")
    return True


def test_apply_configuration():
    """Test applying configuration without setting environment variables"""
    print("\nTesting configuration application...")
    
    try:
        config = apply_micro_capital_config(equity=250.0, set_env_vars=False)
        
        if 'base_config' not in config:
            print(f"  ❌ FAILED: Missing 'base_config' in returned configuration")
            return False
        
        if 'dynamic_config' not in config:
            print(f"  ❌ FAILED: Missing 'dynamic_config' in returned configuration")
            return False
        
        if 'environment_variables' not in config:
            print(f"  ❌ FAILED: Missing 'environment_variables' in returned configuration")
            return False
        
        if config['current_equity'] != 250.0:
            print(f"  ❌ FAILED: Current equity should be 250.0, got {config['current_equity']}")
            return False
        
        print(f"  ✅ PASSED: Configuration application works correctly")
        return True
        
    except Exception as e:
        print(f"  ❌ FAILED: Exception during configuration application: {e}")
        return False


def test_config_summary():
    """Test configuration summary generation"""
    print("\nTesting configuration summary generation...")
    
    try:
        summary = get_config_summary(equity=100.0)
        
        if not summary:
            print(f"  ❌ FAILED: Summary is empty")
            return False
        
        # Check that summary contains key information
        required_strings = [
            'MICRO CAPITAL MODE CONFIGURATION',
            'CURRENT EQUITY:',
            'OPERATIONAL MODE:',
            'POSITION MANAGEMENT:',
            'RISK MANAGEMENT:',
            'DYNAMIC SCALING THRESHOLDS:',
        ]
        
        missing_strings = [s for s in required_strings if s not in summary]
        
        if missing_strings:
            print(f"  ❌ FAILED: Summary missing required sections: {missing_strings}")
            return False
        
        print(f"  ✅ PASSED: Configuration summary generated successfully")
        return True
        
    except Exception as e:
        print(f"  ❌ FAILED: Exception during summary generation: {e}")
        return False


def test_parameter_values():
    """Test that parameter values match problem statement"""
    print("\nTesting parameter values match problem statement...")
    
    checks = [
        (MICRO_CAPITAL_CONFIG['micro_capital_mode'] == True, "MICRO_CAPITAL_MODE should be True"),
        (MICRO_CAPITAL_CONFIG['mode'] == "MASTER_ONLY", "MODE should be MASTER_ONLY"),
        (MICRO_CAPITAL_CONFIG['primary_broker'] == "COINBASE", "PRIMARY_BROKER should be COINBASE"),
        (MICRO_CAPITAL_CONFIG['secondary_broker'] == "KRAKEN", "SECONDARY_BROKER should be KRAKEN"),
        (MICRO_CAPITAL_CONFIG['live_trading'] == True, "LIVE_TRADING should be True"),
        (MICRO_CAPITAL_CONFIG['pro_mode'] == True, "PRO_MODE should be True"),
        (MICRO_CAPITAL_CONFIG['copy_trading'] == False, "COPY_TRADING should be False initially"),
        (MICRO_CAPITAL_CONFIG['min_balance_to_trade'] == 15.00, "MIN_BALANCE_TO_TRADE should be 15.00"),
        (MICRO_CAPITAL_CONFIG['min_trade_size'] == 5.00, "MIN_TRADE_SIZE should be 5.00"),
        (MICRO_CAPITAL_CONFIG['max_positions'] == 2, "MAX_POSITIONS should be 2 initially"),
        (MICRO_CAPITAL_CONFIG['max_position_pct'] == 18.0, "MAX_POSITION_PCT should be 18.0"),
        (MICRO_CAPITAL_CONFIG['risk_per_trade'] == 3.0, "RISK_PER_TRADE should be 3.0 initially"),
        (MICRO_CAPITAL_CONFIG['daily_max_loss'] == 6.0, "DAILY_MAX_LOSS should be 6.0"),
        (MICRO_CAPITAL_CONFIG['max_drawdown'] == 12.0, "MAX_DRAWDOWN should be 12.0"),
        (MICRO_CAPITAL_CONFIG['position_sizer'] == "HYBRID", "POSITION_SIZER should be HYBRID"),
        (MICRO_CAPITAL_CONFIG['kelly_weight'] == 0.30, "KELLY_WEIGHT should be 0.30"),
        (MICRO_CAPITAL_CONFIG['volatility_weight'] == 0.40, "VOLATILITY_WEIGHT should be 0.40"),
        (MICRO_CAPITAL_CONFIG['equity_weight'] == 0.30, "EQUITY_WEIGHT should be 0.30"),
        (MICRO_CAPITAL_CONFIG['min_signal_score'] == 0.75, "MIN_SIGNAL_SCORE should be 0.75"),
        (MICRO_CAPITAL_CONFIG['min_ai_confidence'] == 0.70, "MIN_AI_CONFIDENCE should be 0.70"),
        (MICRO_CAPITAL_CONFIG['min_risk_reward'] == 1.8, "MIN_RISK_REWARD should be 1.8"),
        (MICRO_CAPITAL_CONFIG['trade_only'] == ["BTC", "ETH", "SOL"], "TRADE_ONLY should be ['BTC', 'ETH', 'SOL']"),
        (MICRO_CAPITAL_CONFIG['market_regime_engine'] == True, "MARKET_REGIME_ENGINE should be True"),
        (MICRO_CAPITAL_CONFIG['signal_ensemble'] == True, "SIGNAL_ENSEMBLE should be True"),
        (MICRO_CAPITAL_CONFIG['ai_trade_filter'] == True, "AI_TRADE_FILTER should be True"),
        (MICRO_CAPITAL_CONFIG['leverage_enabled'] == False, "LEVERAGE_ENABLED should be False initially"),
        (MICRO_CAPITAL_CONFIG['arbitrage'] == False, "ARBITRAGE should be False"),
        (MICRO_CAPITAL_CONFIG['auto_shutoff_on_errors'] == True, "AUTO_SHUTOFF_ON_ERRORS should be True"),
        (MICRO_CAPITAL_CONFIG['max_consecutive_losses'] == 3, "MAX_CONSECUTIVE_LOSSES should be 3"),
        (MICRO_CAPITAL_CONFIG['force_cash_buffer'] == 15.0, "FORCE_CASH_BUFFER should be 15.0"),
        (MICRO_CAPITAL_CONFIG['exchange_priority'] == ["COINBASE", "KRAKEN"], "EXCHANGE_PRIORITY should be ['COINBASE', 'KRAKEN']"),
        (MICRO_CAPITAL_CONFIG['min_balance_kraken'] == 50.0, "MIN_BALANCE_KRAKEN should be 50.0"),
        (MICRO_CAPITAL_CONFIG['min_balance_coinbase'] == 10.0, "MIN_BALANCE_COINBASE should be 10.0"),
        (MICRO_CAPITAL_CONFIG['log_signal_rejections'] == True, "LOG_SIGNAL_REJECTIONS should be True"),
        (MICRO_CAPITAL_CONFIG['log_entry_block_reasons'] == True, "LOG_ENTRY_BLOCK_REASONS should be True"),
        (MICRO_CAPITAL_CONFIG['reset_strategy_state'] == True, "RESET_STRATEGY_STATE should be True"),
        (MICRO_CAPITAL_CONFIG['clear_entry_blocks'] == True, "CLEAR_ENTRY_BLOCKS should be True"),
        (MICRO_CAPITAL_CONFIG['flush_cached_balances'] == True, "FLUSH_CACHED_BALANCES should be True"),
    ]
    
    all_passed = True
    
    for check, description in checks:
        if not check:
            print(f"  ❌ FAILED: {description}")
            all_passed = False
    
    if all_passed:
        print(f"  ✅ PASSED: All {len(checks)} parameter values match problem statement")
    
    return all_passed


def run_all_tests():
    """Run all tests"""
    print("="*80)
    print("MICRO CAPITAL MODE CONFIGURATION - TEST SUITE")
    print("="*80)
    
    tests = [
        ("Base Configuration", test_base_configuration),
        ("Dynamic Scaling", test_dynamic_scaling),
        ("Environment Variables", test_environment_variables),
        ("Configuration Application", test_apply_configuration),
        ("Configuration Summary", test_config_summary),
        ("Parameter Values", test_parameter_values),
    ]
    
    results = []
    
    for test_name, test_func in tests:
        try:
            passed = test_func()
            results.append((test_name, passed))
        except Exception as e:
            print(f"\n  ❌ EXCEPTION in {test_name}: {e}")
            import traceback
            traceback.print_exc()
            results.append((test_name, False))
    
    # Print summary
    print("\n" + "="*80)
    print("TEST SUMMARY")
    print("="*80)
    
    total_tests = len(results)
    passed_tests = sum(1 for _, passed in results if passed)
    
    for test_name, passed in results:
        status = "✅ PASSED" if passed else "❌ FAILED"
        print(f"{status}: {test_name}")
    
    print("\n" + "="*80)
    print(f"TOTAL: {passed_tests}/{total_tests} tests passed")
    
    if passed_tests == total_tests:
        print("🎉 ALL TESTS PASSED!")
        print("="*80)
        return 0
    else:
        print(f"⚠️  {total_tests - passed_tests} tests failed")
        print("="*80)
        return 1


if __name__ == "__main__":
    sys.exit(run_all_tests())
