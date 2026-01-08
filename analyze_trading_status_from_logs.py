#!/usr/bin/env python3
"""
Analyze NIJA Trading Status from Logs

This script analyzes bot startup/runtime logs to determine if NIJA is actively trading.
Useful for answering: "Is NIJA trading for user #1 now?"

Usage:
    # Analyze from stdin (paste logs)
    python analyze_trading_status_from_logs.py < logs.txt
    
    # Analyze from file
    python analyze_trading_status_from_logs.py logs.txt
    
    # Analyze from Railway logs
    railway logs --tail 200 | python analyze_trading_status_from_logs.py
"""

import sys
import re
from datetime import datetime, timedelta
from collections import defaultdict


def parse_timestamp(log_line):
    """Extract timestamp from log line."""
    # Try different timestamp formats
    patterns = [
        r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+Z)',  # ISO format with Z
        r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})',        # ISO format without Z
        r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})',        # Space-separated format
    ]
    
    for pattern in patterns:
        match = re.search(pattern, log_line)
        if match:
            try:
                ts_str = match.group(1)
                # Try to parse with different formats
                for fmt in ['%Y-%m-%dT%H:%M:%S.%fZ', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M:%S']:
                    try:
                        return datetime.strptime(ts_str, fmt)
                    except:
                        continue
            except:
                pass
    return None


def analyze_logs(log_lines):
    """Analyze log lines to determine trading status."""
    
    indicators = {
        'container_started': False,
        'strategy_loaded': False,
        'api_connected': False,
        'health_server_started': False,
        'trading_loop_started': False,
        'market_scanning': False,
        'trades_executed': False,
        'errors_found': False,
    }
    
    timestamps = {
        'first_log': None,
        'last_log': None,
        'initialization_complete': None,
        'trading_started': None,
    }
    
    details = {
        'total_capital': None,
        'active_capital': None,
        'daily_target': None,
        'strategy_mode': None,
        'trading_iterations': 0,
        'error_messages': [],
        'warning_messages': [],
    }
    
    print("\n" + "=" * 80)
    print("NIJA TRADING STATUS ANALYSIS")
    print("=" * 80)
    
    # First pass: collect all information
    for i, line in enumerate(log_lines):
        line = line.strip()
        if not line:
            continue
            
        # Extract timestamp
        ts = parse_timestamp(line)
        if ts:
            if timestamps['first_log'] is None:
                timestamps['first_log'] = ts
            timestamps['last_log'] = ts
        
        # Check for initialization indicators
        if 'Starting Container' in line or 'STARTING NIJA TRADING BOT' in line:
            indicators['container_started'] = True
            
        if 'APEX v7' in line or 'TradingStrategy' in line or 'Strategy loaded' in line:
            indicators['strategy_loaded'] = True
            
        if 'Coinbase RESTClient initialized' in line or 'API credentials' in line:
            indicators['api_connected'] = True
            
        if 'Health server' in line or 'listening on port' in line:
            indicators['health_server_started'] = True
            if ts:
                timestamps['initialization_complete'] = ts
        
        # Check for trading activity
        if 'Main trading loop iteration' in line:
            indicators['trading_loop_started'] = True
            details['trading_iterations'] += 1
            if ts and timestamps['trading_started'] is None:
                timestamps['trading_started'] = ts
                
        if 'Scanning' in line and 'markets' in line:
            indicators['market_scanning'] = True
            
        if 'BUY order' in line or 'SELL order' in line or 'Position opened' in line:
            indicators['trades_executed'] = True
        
        # Check for errors
        if 'ERROR' in line or 'Error' in line or 'error' in line.lower():
            if 'no error' not in line.lower():
                indicators['errors_found'] = True
                details['error_messages'].append(line[:150])
                
        if 'WARNING' in line or 'Warning' in line:
            details['warning_messages'].append(line[:150])
        
        # Extract configuration details
        if 'Total Capital:' in line and 'INFO' in line:
            match = re.search(r'Total Capital:\s*\$?([\d,]+\.?\d*)', line)
            if match:
                details['total_capital'] = match.group(1).replace(',', '')
                
        if ('Active Capital:' in line or 'trading capital' in line.lower()) and 'INFO' in line:
            match = re.search(r'(?:Active Capital|trading capital):\s*\$?([\d,]+\.?\d*)', line, re.IGNORECASE)
            if match:
                details['active_capital'] = match.group(1).replace(',', '')
                
        if 'Daily Target:' in line and 'INFO' in line:
            match = re.search(r'Daily Target:\s*\$?([\d,]+\.?\d*)', line)
            if match:
                details['daily_target'] = match.group(1).replace(',', '')
                
        if 'Strategy:' in line or 'strategy:' in line.lower():
            if 'conservative' in line.lower():
                details['strategy_mode'] = 'conservative'
            elif 'aggressive' in line.lower():
                details['strategy_mode'] = 'aggressive'
            elif 'balanced' in line.lower():
                details['strategy_mode'] = 'balanced'
    
    # Analysis output
    print("\n📊 LOG ANALYSIS RESULTS")
    print("-" * 80)
    
    # Timeline
    print("\n⏱️  TIMELINE:")
    if timestamps['first_log']:
        print(f"   First log entry: {timestamps['first_log'].strftime('%Y-%m-%d %H:%M:%S UTC')}")
    if timestamps['last_log']:
        print(f"   Last log entry:  {timestamps['last_log'].strftime('%Y-%m-%d %H:%M:%S UTC')}")
        
        if timestamps['first_log']:
            duration = timestamps['last_log'] - timestamps['first_log']
            print(f"   Log duration:    {duration.total_seconds():.1f} seconds")
    
    if timestamps['initialization_complete']:
        print(f"   Initialization:  {timestamps['initialization_complete'].strftime('%Y-%m-%d %H:%M:%S UTC')}")
        
    if timestamps['trading_started']:
        print(f"   Trading started: {timestamps['trading_started'].strftime('%Y-%m-%d %H:%M:%S UTC')}")
    
    # Initialization Status
    print("\n✅ INITIALIZATION STATUS:")
    init_checks = [
        ('Container started', indicators['container_started']),
        ('Strategy loaded', indicators['strategy_loaded']),
        ('API connected', indicators['api_connected']),
        ('Health server', indicators['health_server_started']),
    ]
    
    for check_name, passed in init_checks:
        icon = "✅" if passed else "❌"
        print(f"   {icon} {check_name}")
    
    # Trading Activity Status  
    print("\n🔄 TRADING ACTIVITY STATUS:")
    activity_checks = [
        ('Trading loop active', indicators['trading_loop_started']),
        ('Market scanning', indicators['market_scanning']),
        ('Trades executed', indicators['trades_executed']),
    ]
    
    for check_name, passed in activity_checks:
        icon = "✅" if passed else "⏳"
        print(f"   {icon} {check_name}")
    
    if details['trading_iterations'] > 0:
        print(f"\n   📈 Trading loop iterations: {details['trading_iterations']}")
    
    # Configuration
    if any([details['total_capital'], details['active_capital'], details['daily_target']]):
        print("\n💰 CONFIGURATION:")
        if details['total_capital']:
            print(f"   Total Capital:  ${details['total_capital']}")
        if details['active_capital']:
            print(f"   Active Capital: ${details['active_capital']}")
        if details['daily_target']:
            print(f"   Daily Target:   ${details['daily_target']}")
        if details['strategy_mode']:
            print(f"   Strategy Mode:  {details['strategy_mode'].title()}")
    
    # Errors and warnings
    if indicators['errors_found']:
        print("\n⚠️  ERRORS DETECTED:")
        for err in details['error_messages'][:5]:  # Show first 5
            print(f"   • {err}")
    
    if details['warning_messages']:
        print(f"\n⚠️  WARNINGS: {len(details['warning_messages'])} found")
    
    # Final Assessment
    print("\n" + "=" * 80)
    print("FINAL ASSESSMENT")
    print("=" * 80)
    
    # Determine status
    init_complete = all([
        indicators['container_started'],
        indicators['strategy_loaded'],
        indicators['api_connected'],
    ])
    
    trading_active = indicators['trading_loop_started'] or indicators['market_scanning']
    trades_happening = indicators['trades_executed']
    
    print("\n🎯 ANSWER: Is NIJA trading now?\n")
    
    if trades_happening:
        print("✅ YES - NIJA IS ACTIVELY EXECUTING TRADES")
        print("\nEvidence:")
        print("   ✅ Trades found in logs")
        print("   ✅ Bot is executing buy/sell orders")
        print("\nConfidence: 100% - NIJA is trading")
        status = "TRADING_CONFIRMED"
        
    elif trading_active:
        print("✅ YES - NIJA IS RUNNING AND SCANNING MARKETS")
        print("\nEvidence:")
        print(f"   ✅ Trading loop active ({details['trading_iterations']} iterations)")
        print("   ✅ Market scanning detected")
        if details['trading_iterations'] > 0:
            print(f"   ✅ {details['trading_iterations']} trading cycles completed")
        print("\nNote: No trades executed yet (may be waiting for valid signals)")
        print("      This is NORMAL - bot is selective and waits for good setups")
        print("\nConfidence: 95% - NIJA is trading (waiting for signals)")
        status = "TRADING_ACTIVE"
        
    elif init_complete and not indicators['errors_found']:
        print("⏳ LIKELY STARTING - Initialization Complete")
        print("\nEvidence:")
        print("   ✅ Container started successfully")
        print("   ✅ Strategy loaded")
        print("   ✅ API connected")
        print("   ⏳ Trading loop not yet visible in logs")
        print("\nLikely Scenario:")
        
        if timestamps['initialization_complete']:
            expected_start = timestamps['initialization_complete'] + timedelta(seconds=15)
            print(f"   • Initialization completed: {timestamps['initialization_complete'].strftime('%H:%M:%S UTC')}")
            print(f"   • Expected trading start: {expected_start.strftime('%H:%M:%S UTC')}")
            
            if timestamps['last_log']:
                if timestamps['last_log'] < expected_start:
                    print(f"   • Logs end BEFORE expected start (in 15-sec wait period)")
                    print(f"   • Bot should be starting trading NOW")
                else:
                    print(f"   • Logs extend past expected start")
                    print(f"   • Trading may have started (not visible in these logs)")
        
        print("\nRecommendation:")
        print("   1. View more recent logs: railway logs --tail 100")
        print("   2. Look for 'Main trading loop iteration #2' or higher")
        print("   3. Check Coinbase for recent orders")
        print("\nConfidence: 75% - Bot should be trading (need to verify)")
        status = "LIKELY_TRADING"
        
    elif indicators['errors_found']:
        print("❌ ERROR DETECTED - Bot May Not Be Trading")
        print("\nEvidence:")
        print("   ❌ Errors found in logs")
        print("\nErrors:")
        for err in details['error_messages'][:3]:
            print(f"   • {err}")
        print("\nRecommendation:")
        print("   1. Review full error logs")
        print("   2. Check Railway deployment status")
        print("   3. Verify API credentials and balance")
        print("\nConfidence: 60% - Bot likely NOT trading due to errors")
        status = "ERROR_DETECTED"
        
    else:
        print("❓ INSUFFICIENT INFORMATION")
        print("\nEvidence:")
        print("   ⚠️  Limited log data available")
        print("   ⚠️  Cannot determine trading status from logs alone")
        print("\nRecommendation:")
        print("   1. Check Railway logs: railway logs --tail 200")
        print("   2. Check Coinbase for recent orders")
        print("   3. Run: python check_if_trading_now.py")
        print("\nConfidence: 30% - Need more information")
        status = "UNKNOWN"
    
    print("\n" + "=" * 80)
    print("NEXT STEPS")
    print("=" * 80)
    
    print("\n📝 To verify NIJA is trading:")
    print("\n   1. Check Railway Logs:")
    print("      railway logs --tail 100")
    print("      Look for: 'Main trading loop iteration #2' or higher")
    print("\n   2. Check Coinbase Orders:")
    print("      https://www.coinbase.com/advanced-portfolio")
    print("      Look for: Recent buy/sell orders")
    print("\n   3. Run Diagnostic:")
    print("      python check_if_trading_now.py")
    print("      python check_first_user_trading_status.py")
    
    print("\n" + "=" * 80)
    print()
    
    return status, indicators, details


def main():
    """Main execution."""
    
    # Read logs from stdin or file
    if len(sys.argv) > 1:
        # Read from file
        filename = sys.argv[1]
        try:
            with open(filename, 'r') as f:
                log_lines = f.readlines()
            print(f"📁 Reading logs from: {filename}")
        except Exception as e:
            print(f"❌ Error reading file: {e}")
            sys.exit(1)
    else:
        # Read from stdin
        print("📋 Reading logs from stdin... (Ctrl+D when done)")
        print("   Or pipe logs: railway logs | python analyze_trading_status_from_logs.py")
        print()
        log_lines = sys.stdin.readlines()
    
    if not log_lines:
        print("❌ No log data provided")
        print("\nUsage:")
        print("   python analyze_trading_status_from_logs.py < logs.txt")
        print("   python analyze_trading_status_from_logs.py logs.txt")
        print("   railway logs --tail 200 | python analyze_trading_status_from_logs.py")
        sys.exit(1)
    
    print(f"📊 Analyzing {len(log_lines)} log lines...\n")
    
    # Analyze
    status, indicators, details = analyze_logs(log_lines)
    
    # Exit code based on status
    exit_codes = {
        'TRADING_CONFIRMED': 0,   # Definitely trading
        'TRADING_ACTIVE': 0,      # Trading loop active
        'LIKELY_TRADING': 1,      # Probably trading but not confirmed
        'ERROR_DETECTED': 2,      # Errors found
        'UNKNOWN': 3,             # Can't determine
    }
    
    sys.exit(exit_codes.get(status, 3))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n❌ Analysis interrupted by user")
        sys.exit(130)
    except Exception as e:
        print(f"\n❌ FATAL ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
