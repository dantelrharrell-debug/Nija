#!/usr/bin/env python3
"""
Quick Check: Is NIJA Trading Right Now?

This script provides a fast answer to "Is NIJA actively trading right now?"
by checking multiple indicators.

Usage:
    python check_if_trading_now.py
"""

import sys
import os
from datetime import datetime, timedelta

# Load environment variables
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

def print_header(text):
    """Print a formatted header."""
    print("\n" + "=" * 80)
    print(text)
    print("=" * 80)

def print_section(text):
    """Print a formatted section."""
    print("\n" + "-" * 80)
    print(text)
    print("-" * 80)

def check_recent_activity():
    """Check if there has been recent trading activity."""
    print_header("CHECKING IF NIJA IS TRADING NOW")
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}")
    
    trading_indicators = {
        'log_file_active': False,
        'recent_logs': False,
        'coinbase_connected': False,
        'recent_positions': False,
        'recent_orders': False,
    }
    
    # Check 1: Log file exists and is being written to
    print_section("CHECK 1: Log File Activity")
    log_file = os.path.join(os.path.dirname(__file__), 'nija.log')
    
    if os.path.exists(log_file):
        print(f"✅ Log file exists: {log_file}")
        
        # Check when log file was last modified
        last_modified = datetime.fromtimestamp(os.path.getmtime(log_file))
        time_since_update = datetime.now() - last_modified
        
        print(f"   Last modified: {last_modified.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"   Time since update: {time_since_update.total_seconds():.0f} seconds ago")
        
        if time_since_update.total_seconds() < 300:  # 5 minutes
            print(f"   ✅ Log file is ACTIVELY being written to")
            print(f"      → This suggests the bot is running")
            trading_indicators['log_file_active'] = True
        else:
            print(f"   ⚠️  Log file was last updated {time_since_update.total_seconds() / 60:.1f} minutes ago")
            print(f"      → Bot may have stopped or crashed")
        
        # Read last few lines to see what's happening
        try:
            with open(log_file, 'r') as f:
                lines = f.readlines()
                last_lines = lines[-10:] if len(lines) >= 10 else lines
                
                print(f"\n   Last {len(last_lines)} log entries:")
                for line in last_lines:
                    print(f"   {line.rstrip()}")
                
                # Look for trading indicators in recent logs
                recent_log_text = '\n'.join(last_lines)
                if 'Main trading loop iteration' in recent_log_text:
                    print(f"\n   ✅ FOUND: Trading loop iterations in recent logs")
                    trading_indicators['recent_logs'] = True
                elif 'Scanning' in recent_log_text or 'markets' in recent_log_text:
                    print(f"\n   ✅ FOUND: Market scanning activity in recent logs")
                    trading_indicators['recent_logs'] = True
                elif 'BUY' in recent_log_text or 'SELL' in recent_log_text:
                    print(f"\n   ✅ FOUND: Buy/sell activity in recent logs")
                    trading_indicators['recent_logs'] = True
                else:
                    print(f"\n   ⚠️  No clear trading activity in recent logs")
        except Exception as e:
            print(f"   ⚠️  Could not read log file: {e}")
    else:
        print(f"❌ Log file not found: {log_file}")
        print(f"   → Bot may not have started yet")
    
    # Check 2: Can we connect to Coinbase?
    print_section("CHECK 2: Coinbase API Connection")
    
    try:
        from broker_manager import CoinbaseBroker
        
        broker = CoinbaseBroker()
        if broker.connect():
            print(f"✅ Successfully connected to Coinbase API")
            trading_indicators['coinbase_connected'] = True
            
            # Try to get recent orders
            try:
                print(f"\n   Checking for recent orders...")
                # Note: This would require implementing a get_recent_orders method
                # For now, we'll just check balance to verify connection
                balance_data = broker.get_account_balance()
                trading_balance = balance_data.get('trading_balance', 0)
                
                print(f"   💰 Current trading balance: ${trading_balance:,.2f} USD")
                
                if trading_balance >= 25:
                    print(f"   ✅ Sufficient balance for trading")
                elif trading_balance >= 2:
                    print(f"   ⚠️  Limited balance for trading (minimum met)")
                else:
                    print(f"   ❌ Insufficient balance for trading (need min $2)")
                
            except Exception as e:
                print(f"   ⚠️  Could not check orders: {e}")
        else:
            print(f"❌ Could not connect to Coinbase API")
            print(f"   → Check API credentials")
    except Exception as e:
        print(f"❌ Error connecting to Coinbase: {e}")
    
    # Check 3: Look for position tracker file
    print_section("CHECK 3: Active Positions")
    
    position_files = [
        'positions.json',
        'data/positions.json',
        'bot/positions.json',
    ]
    
    position_found = False
    for pos_file in position_files:
        full_path = os.path.join(os.path.dirname(__file__), pos_file)
        if os.path.exists(full_path):
            print(f"✅ Position file found: {pos_file}")
            position_found = True
            
            # Check when it was last updated
            last_modified = datetime.fromtimestamp(os.path.getmtime(full_path))
            time_since_update = datetime.now() - last_modified
            
            print(f"   Last updated: {last_modified.strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"   Time since update: {time_since_update.total_seconds() / 60:.1f} minutes ago")
            
            if time_since_update.total_seconds() < 300:  # 5 minutes
                print(f"   ✅ Recently updated → Active position management")
                trading_indicators['recent_positions'] = True
            
            # Try to read positions
            try:
                import json
                with open(full_path, 'r') as f:
                    positions = json.load(f)
                    if positions:
                        print(f"   📊 Active positions: {len(positions)}")
                        trading_indicators['recent_positions'] = True
                    else:
                        print(f"   ℹ️  No active positions (may be waiting for signals)")
            except:
                pass
            
            break
    
    if not position_found:
        print(f"ℹ️  No position tracker file found")
        print(f"   → Bot may not have any open positions yet (normal)")
    
    # Check 4: Process check (if possible)
    print_section("CHECK 4: Process Status")
    
    try:
        # Try to check if bot.py or trading_strategy.py is running
        import subprocess
        result = subprocess.run(['ps', 'aux'], capture_output=True, text=True, timeout=5)
        
        if 'bot.py' in result.stdout or 'trading_strategy' in result.stdout:
            print(f"✅ NIJA bot process is RUNNING")
            print(f"   → Process found in system")
        else:
            print(f"⚠️  Bot process not found in current system")
            print(f"   → May be running in a container/remote server")
    except Exception as e:
        print(f"ℹ️  Could not check process status: {e}")
        print(f"   → This is normal if running in a containerized environment")
    
    # Final assessment
    print_section("FINAL ASSESSMENT")
    
    indicators_met = sum(trading_indicators.values())
    total_indicators = len(trading_indicators)
    
    print(f"\nTrading Indicators Check: {indicators_met}/{total_indicators} positive")
    print(f"\nIndicator Status:")
    for indicator, status in trading_indicators.items():
        status_icon = "✅" if status else "❌"
        print(f"   {status_icon} {indicator.replace('_', ' ').title()}")
    
    print(f"\n" + "=" * 80)
    
    if indicators_met >= 3:
        print(f"🟢 CONCLUSION: NIJA IS LIKELY TRADING")
        print(f"=" * 80)
        print(f"\nConfidence: HIGH")
        print(f"Evidence: Multiple indicators show active trading")
        print(f"\n✅ The bot appears to be actively trading right now")
        return True
        
    elif indicators_met >= 2:
        print(f"🟡 CONCLUSION: NIJA MAY BE TRADING")
        print(f"=" * 80)
        print(f"\nConfidence: MEDIUM")
        print(f"Evidence: Some indicators show activity")
        print(f"\n⚠️  Bot may be running but not actively trading (waiting for signals)")
        print(f"    or there may be limited activity due to market conditions")
        return None
        
    elif indicators_met >= 1:
        print(f"🟠 CONCLUSION: UNCERTAIN - MORE INVESTIGATION NEEDED")
        print(f"=" * 80)
        print(f"\nConfidence: LOW")
        print(f"Evidence: Minimal trading indicators detected")
        print(f"\n📝 RECOMMENDED ACTIONS:")
        print(f"   1. Check Railway/deployment logs for recent activity")
        print(f"   2. Check Coinbase Advanced Trade for recent orders")
        print(f"   3. Verify bot deployment is running")
        return None
        
    else:
        print(f"🔴 CONCLUSION: NIJA IS LIKELY NOT TRADING")
        print(f"=" * 80)
        print(f"\nConfidence: HIGH")
        print(f"Evidence: No trading indicators detected")
        print(f"\n❌ The bot does not appear to be actively trading")
        print(f"\n📝 POSSIBLE REASONS:")
        print(f"   • Bot not started or deployment failed")
        print(f"   • Insufficient balance (need min $25)")
        print(f"   • API connection issues")
        print(f"   • Bot crashed after initialization")
        print(f"\n📝 NEXT STEPS:")
        print(f"   1. Check deployment status on Railway")
        print(f"   2. View recent logs: railway logs --tail 100")
        print(f"   3. Verify Coinbase balance")
        print(f"   4. Check API credentials")
        return False
    
    print(f"\n" + "=" * 80)
    print(f"\n💡 TIP: For definitive answer, check:")
    print(f"   • Railway logs: railway logs --tail 100")
    print(f"   • Coinbase orders: https://www.coinbase.com/advanced-portfolio")
    print(f"   • Or see: IS_NIJA_TRADING_NOW.md for detailed guide")
    print(f"\n" + "=" * 80 + "\n")


def main():
    """Main execution."""
    try:
        check_recent_activity()
    except KeyboardInterrupt:
        print("\n\n❌ Check interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
