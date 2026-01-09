#!/usr/bin/env python3
"""
NIJA Active Trading Status Checker

This script provides a comprehensive check to determine if NIJA is actively trading
for you and NIJA users.

Usage:
    python check_trading_status.py
    
    # Or check via HTTP endpoint (if bot is running):
    curl http://localhost:5001/api/trading_status
    curl http://localhost:5001/status  # Human-readable HTML
"""

import sys
import os
import json
from datetime import datetime, timedelta
from pathlib import Path

# Load environment variables
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))


def print_header(text, char="="):
    """Print a formatted header."""
    print("\n" + char * 80)
    print(text)
    print(char * 80)


def print_section(text):
    """Print a formatted section."""
    print("\n" + "-" * 80)
    print(text)
    print("-" * 80)


def check_log_activity():
    """Check if bot log file is being actively updated."""
    log_locations = [
        Path("nija.log"),
        Path("/usr/src/app/nija.log"),
        Path("bot/nija.log"),
    ]
    
    for log_file in log_locations:
        if log_file.exists():
            last_modified = datetime.fromtimestamp(log_file.stat().st_mtime)
            time_since_update = datetime.now() - last_modified
            
            return {
                "active": time_since_update.total_seconds() < 300,  # 5 minutes
                "last_update": last_modified,
                "age_seconds": int(time_since_update.total_seconds()),
                "log_file": str(log_file)
            }
    
    return {"active": False, "error": "No log file found"}


def check_broker_positions():
    """Check positions across all brokers."""
    try:
        from broker_manager import CoinbaseBroker, KrakenBroker, OKXBroker
    except ImportError as e:
        return {"error": f"Cannot import broker_manager: {e}"}
    
    brokers = [
        ("Coinbase Advanced Trade", CoinbaseBroker),
        ("Kraken Pro", KrakenBroker),
        ("OKX", OKXBroker),
    ]
    
    results = {
        "total_positions": 0,
        "total_balance": 0.0,
        "active_brokers": [],
        "errors": []
    }
    
    for broker_name, broker_class in brokers:
        try:
            broker = broker_class()
            if broker.connect():
                # Get positions
                positions = broker.get_positions()
                position_count = len(positions) if positions else 0
                
                # Get balance
                try:
                    balance_data = broker.get_account_balance()
                    if isinstance(balance_data, dict):
                        balance = balance_data.get('trading_balance', 0)
                    else:
                        balance = float(balance_data) if balance_data else 0
                except Exception as e:
                    balance = 0
                    results["errors"].append(f"{broker_name} balance check failed: {str(e)[:50]}")
                
                results["total_positions"] += position_count
                results["total_balance"] += balance
                
                results["active_brokers"].append({
                    "name": broker_name,
                    "connected": True,
                    "positions": position_count,
                    "balance": balance
                })
        except Exception as e:
            results["errors"].append(f"{broker_name}: {str(e)[:50]}")
    
    return results


def check_recent_trades():
    """Check recent trading activity from trade journal."""
    journal_locations = [
        Path("trade_journal.jsonl"),
        Path("/usr/src/app/trade_journal.jsonl"),
        Path("../trade_journal.jsonl"),
    ]
    
    for journal_file in journal_locations:
        if journal_file.exists():
            trades_24h = 0
            last_trade_time = None
            cutoff_time = datetime.now() - timedelta(hours=24)
            
            try:
                with open(journal_file, 'r') as f:
                    for line in f:
                        if not line.strip():
                            continue
                        try:
                            trade = json.loads(line)
                            trade_time = datetime.fromisoformat(trade.get('timestamp', ''))
                            
                            if trade_time >= cutoff_time:
                                trades_24h += 1
                                if not last_trade_time or trade_time > last_trade_time:
                                    last_trade_time = trade_time
                        except:
                            continue
                
                return {
                    "trades_24h": trades_24h,
                    "last_trade_time": last_trade_time.isoformat() if last_trade_time else None,
                    "journal_file": str(journal_file)
                }
            except Exception as e:
                return {"error": f"Could not read journal: {e}"}
    
    return {"trades_24h": 0, "error": "No trade journal found"}


def check_user_status():
    """Check multi-user system status."""
    try:
        from auth import get_user_manager
        from controls import get_hard_controls
        
        user_mgr = get_user_manager()
        controls = get_hard_controls()
        
        users = []
        
        # Check for known users
        known_user_ids = ["daivon_frazier"]
        
        for user_id in known_user_ids:
            try:
                user = user_mgr.get_user(user_id)
                if user:
                    can_trade, error = controls.can_trade(user_id)
                    users.append({
                        "user_id": user_id,
                        "email": user.get('email', 'N/A'),
                        "enabled": user.get('enabled', False),
                        "can_trade": can_trade,
                        "tier": user.get('subscription_tier', 'N/A'),
                        "blocked_reason": error if not can_trade else None
                    })
            except:
                continue
        
        return {"users": users, "system_available": True}
        
    except ImportError:
        return {"users": [], "system_available": False, "note": "Multi-user system not initialized"}
    except Exception as e:
        return {"error": f"User check failed: {e}"}


def main():
    """Main execution."""
    print_header("NIJA ACTIVE TRADING STATUS CHECK")
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}")
    
    # Check 1: Log file activity
    print_section("CHECK 1: Bot Process Activity")
    log_status = check_log_activity()
    
    if log_status.get("active"):
        print(f"✅ Bot is RUNNING")
        print(f"   Log file: {log_status['log_file']}")
        print(f"   Last update: {log_status['last_update'].strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"   Age: {log_status['age_seconds']} seconds")
    else:
        print(f"❌ Bot may NOT be running")
        if log_status.get("error"):
            print(f"   {log_status['error']}")
        else:
            print(f"   Log file last updated: {log_status.get('last_update', 'Unknown')}")
            print(f"   Age: {log_status.get('age_seconds', 0)} seconds (> 5 minutes)")
    
    # Check 2: Broker positions and balances
    print_section("CHECK 2: Broker Positions & Balances")
    broker_status = check_broker_positions()
    
    if broker_status.get("error"):
        print(f"❌ Could not check brokers: {broker_status['error']}")
    else:
        print(f"\n📊 Total Open Positions: {broker_status['total_positions']}")
        print(f"💰 Total Trading Balance: ${broker_status['total_balance']:,.2f}")
        print(f"\n🔗 Connected Brokers:")
        
        for broker in broker_status['active_brokers']:
            positions = broker['positions']
            balance = broker['balance']
            status_icon = "🟢" if positions > 0 else "⚪"
            
            print(f"\n   {status_icon} {broker['name']}")
            print(f"      Positions: {positions}")
            print(f"      Balance: ${balance:,.2f}")
            
            if positions > 0:
                print(f"      Status: ACTIVELY TRADING")
            else:
                print(f"      Status: Connected but idle")
        
        if broker_status.get('errors'):
            print(f"\n⚠️  Errors:")
            for error in broker_status['errors']:
                print(f"   • {error}")
    
    # Check 3: Recent trading activity
    print_section("CHECK 3: Recent Trading Activity")
    trade_status = check_recent_trades()
    
    if trade_status.get("error"):
        print(f"ℹ️  {trade_status['error']}")
    else:
        trades_24h = trade_status['trades_24h']
        last_trade = trade_status.get('last_trade_time')
        
        print(f"\n📈 Trades (Last 24 Hours): {trades_24h}")
        
        if last_trade:
            last_trade_dt = datetime.fromisoformat(last_trade)
            time_since_trade = datetime.now() - last_trade_dt
            print(f"⏱️  Last Trade: {last_trade_dt.strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"   Time since last trade: {int(time_since_trade.total_seconds() / 60)} minutes ago")
        
        if trades_24h > 0:
            print(f"\n✅ Bot has been trading recently")
        else:
            print(f"\nℹ️  No trades in the last 24 hours")
    
    # Check 4: User status
    print_section("CHECK 4: User Trading Status")
    user_status = check_user_status()
    
    if not user_status.get('system_available'):
        print(f"ℹ️  Multi-user system not initialized")
        print(f"   Note: Bot is trading with direct broker credentials")
        print(f"   To enable multi-user system:")
        print(f"   1. python init_user_system.py")
        print(f"   2. python setup_user_daivon.py")
    elif user_status.get('error'):
        print(f"⚠️  {user_status['error']}")
    else:
        users = user_status.get('users', [])
        
        if users:
            print(f"\n👥 Configured Users: {len(users)}\n")
            
            for user in users:
                status_icon = "✅" if user['can_trade'] and user['enabled'] else "❌"
                print(f"{status_icon} User: {user['user_id']}")
                print(f"   Email: {user['email']}")
                print(f"   Tier: {user['tier']}")
                print(f"   Enabled: {user['enabled']}")
                print(f"   Can Trade: {user['can_trade']}")
                
                if user.get('blocked_reason'):
                    print(f"   ⚠️  Blocked: {user['blocked_reason']}")
                print()
        else:
            print(f"ℹ️  No users configured yet")
    
    # Final assessment
    print_header("FINAL ASSESSMENT", "=")
    
    is_trading = False
    bot_running = log_status.get("active", False)
    has_positions = broker_status.get("total_positions", 0) > 0
    recent_trades = trade_status.get("trades_24h", 0) > 0
    
    if has_positions or recent_trades:
        is_trading = True
    
    print()
    
    if is_trading and bot_running:
        print("🟢 CONCLUSION: NIJA IS ACTIVELY TRADING")
        print()
        print("✅ Evidence:")
        print(f"   • Bot process is running")
        print(f"   • {broker_status.get('total_positions', 0)} open positions")
        print(f"   • ${broker_status.get('total_balance', 0):,.2f} available for trading")
        print(f"   • {trade_status.get('trades_24h', 0)} trades in last 24 hours")
        
        active_brokers = [b for b in broker_status.get('active_brokers', []) if b['positions'] > 0]
        if active_brokers:
            print(f"   • Trading on: {', '.join([b['name'] for b in active_brokers])}")
    
    elif bot_running and not has_positions:
        print("🟡 CONCLUSION: NIJA IS READY BUT NOT ACTIVELY TRADING")
        print()
        print("ℹ️  Status:")
        print(f"   • Bot process is running")
        print(f"   • No open positions currently")
        print(f"   • ${broker_status.get('total_balance', 0):,.2f} available for trading")
        
        if recent_trades:
            print(f"   • {trade_status.get('trades_24h', 0)} trades in last 24 hours (all closed)")
        
        print()
        print("💡 This is normal. Bot is waiting for entry signals that meet strategy criteria.")
    
    else:
        print("🔴 CONCLUSION: NIJA IS NOT TRADING")
        print()
        print("❌ Status:")
        print(f"   • Bot may not be running (log inactive)")
        print(f"   • No open positions")
        print(f"   • No recent trading activity")
        print()
        print("📝 RECOMMENDED ACTIONS:")
        print("   1. Check if bot is deployed and running")
        print("   2. Check Railway/deployment logs")
        print("   3. Verify broker credentials are configured")
        print("   4. Ensure minimum balance requirements are met ($25+)")
    
    print()
    print_header("HOW TO ACCESS TRADING STATUS", "=")
    print()
    print("📡 Via HTTP Endpoints (when bot is running):")
    print("   • API: http://localhost:5001/api/trading_status")
    print("   • Web: http://localhost:5001/status")
    print("   • Health: http://localhost:5001/health")
    print()
    print("🐍 Via Python Script:")
    print("   • Run: python check_trading_status.py")
    print()
    print("📄 Documentation:")
    print("   • IS_NIJA_TRADING_NOW.md")
    print("   • ACTIVE_TRADING_STATUS.md")
    print()
    print("=" * 80 + "\n")
    
    # Exit code: 0 if trading, 1 if not
    sys.exit(0 if is_trading else 1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n❌ Check interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
