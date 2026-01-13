#!/usr/bin/env python3
"""
NIJA Trading Status Checker
============================

Quick check to see if NIJA is ready to trade and which exchanges are actively trading.
This script:
- Tests actual broker connections (not just environment variables)
- Shows which exchanges can trade
- Identifies connection issues and provides fixes
- Gives a clear GO/NO-GO trading status

Usage:
    python3 check_trading_status.py
"""

import os
import sys
from pathlib import Path

# Setup Python path to import bot modules
sys.path.insert(0, str(Path(__file__).parent / 'bot'))

# ANSI color codes for terminal output
class Colors:
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    RESET = '\033[0m'
    BOLD = '\033[1m'


def test_broker_connection(broker_name: str, account_type: str = "MASTER") -> tuple:
    """
    Test if a broker can connect.
    
    Returns:
        (connected: bool, status_msg: str, details: str)
    """
    try:
        if broker_name.lower() == "coinbase":
            from broker_manager import CoinbaseBroker
            broker = CoinbaseBroker()
            if broker.connect():
                try:
                    balance = broker.get_account_balance()
                    return True, "Connected", f"Balance: ${balance:,.2f}"
                except:
                    return True, "Connected", "Balance check failed"
            else:
                return False, "Connection failed", "Check credentials"
        
        elif broker_name.lower() == "kraken":
            from broker_manager import KrakenBroker, AccountType
            acc_type = AccountType.MASTER if account_type == "MASTER" else AccountType.USER
            broker = KrakenBroker(account_type=acc_type)
            if broker.connect():
                try:
                    balance = broker.get_account_balance()
                    return True, "Connected", f"Balance: ${balance:,.2f}"
                except:
                    return True, "Connected", "Balance check failed"
            else:
                return False, "Connection failed", "Check credentials or permissions"
        
        elif broker_name.lower() == "alpaca":
            from broker_manager import AlpacaBroker, AccountType
            acc_type = AccountType.MASTER if account_type == "MASTER" else AccountType.USER
            broker = AlpacaBroker(account_type=acc_type)
            if broker.connect():
                try:
                    balance = broker.get_account_balance()
                    return True, "Connected", f"Balance: ${balance:,.2f}"
                except:
                    return True, "Connected", "Balance check failed"
            else:
                return False, "Connection failed", "Check credentials"
        
        elif broker_name.lower() == "okx":
            from broker_manager import OKXBroker
            broker = OKXBroker()
            if broker.connect():
                try:
                    balance = broker.get_account_balance()
                    return True, "Connected", f"Balance: ${balance:,.2f}"
                except:
                    return True, "Connected", "Balance check failed"
            else:
                return False, "Connection failed", "Check credentials"
        
        elif broker_name.lower() == "binance":
            from broker_manager import BinanceBroker
            broker = BinanceBroker()
            if broker.connect():
                try:
                    balance = broker.get_account_balance()
                    return True, "Connected", f"Balance: ${balance:,.2f}"
                except:
                    return True, "Connected", "Balance check failed"
            else:
                return False, "Connection failed", "Check credentials"
        
        else:
            return False, "Unknown broker", f"{broker_name} not supported"
    
    except ImportError as e:
        return False, "SDK not installed", f"Missing: {str(e)}"
    except Exception as e:
        error_msg = str(e)
        # Check for specific errors
        if "permission" in error_msg.lower():
            return False, "Permission denied", "Fix API key permissions"
        elif "nonce" in error_msg.lower():
            return False, "Nonce error", "Retry or check system clock"
        elif "credentials" in error_msg.lower() or "auth" in error_msg.lower():
            return False, "Auth failed", "Check credentials"
        else:
            return False, "Error", error_msg[:50]


def main():
    """Main function to check trading status."""
    
    print(f"{Colors.BOLD}{Colors.CYAN}")
    print("=" * 70)
    print("    NIJA TRADING STATUS CHECK")
    print("=" * 70)
    print(f"{Colors.RESET}\n")
    
    # Load environment variables from .env if present
    try:
        from dotenv import load_dotenv
        if os.path.exists('.env'):
            load_dotenv()
            print(f"{Colors.GREEN}✅ Loaded .env file{Colors.RESET}\n")
        else:
            print(f"{Colors.YELLOW}⚠️  No .env file (using system env vars){Colors.RESET}\n")
    except ImportError:
        print(f"{Colors.YELLOW}⚠️  python-dotenv not installed (using system env vars){Colors.RESET}\n")
    
    # Test master account brokers
    print(f"{Colors.BOLD}{'=' * 70}{Colors.RESET}")
    print(f"{Colors.BOLD}MASTER ACCOUNT BROKER STATUS{Colors.RESET}")
    print(f"{Colors.BOLD}{'=' * 70}{Colors.RESET}\n")
    
    master_brokers = []
    master_connected = []
    
    brokers_to_test = [
        ("Coinbase", "coinbase"),
        ("Kraken", "kraken"),
        ("Alpaca", "alpaca"),
        ("OKX", "okx"),
        ("Binance", "binance")
    ]
    
    for display_name, broker_id in brokers_to_test:
        print(f"{Colors.CYAN}Testing {display_name} MASTER...{Colors.RESET}")
        connected, status, details = test_broker_connection(broker_id, "MASTER")
        
        if connected:
            print(f"   {Colors.GREEN}✅ {status} - {details}{Colors.RESET}")
            master_connected.append(display_name)
        else:
            print(f"   {Colors.RED}❌ {status} - {details}{Colors.RESET}")
        
        print()
    
    # Summary
    print(f"{Colors.BOLD}{'=' * 70}{Colors.RESET}")
    print(f"{Colors.BOLD}TRADING STATUS SUMMARY{Colors.RESET}")
    print(f"{Colors.BOLD}{'=' * 70}{Colors.RESET}\n")
    
    if master_connected:
        print(f"{Colors.BOLD}{Colors.GREEN}✅ NIJA CAN TRADE{Colors.RESET}")
        print(f"\n{Colors.BOLD}Active Master Exchanges:{Colors.RESET}")
        for exchange in master_connected:
            print(f"   {Colors.GREEN}✅ {exchange}{Colors.RESET}")
        
        print(f"\n{Colors.BOLD}What this means:{Colors.RESET}")
        print(f"   • NIJA bot is READY to execute trades")
        print(f"   • Trading will occur on {len(master_connected)} exchange(s)")
        print(f"   • Each exchange operates independently")
        print(f"   • Failures on one exchange won't affect others")
        
        if len(master_connected) == 1:
            print(f"\n{Colors.YELLOW}💡 Tip: Enable more exchanges for better diversification{Colors.RESET}")
            print(f"   Run: python3 validate_all_env_vars.py")
        
    else:
        print(f"{Colors.BOLD}{Colors.RED}❌ NIJA CANNOT TRADE{Colors.RESET}")
        print(f"\n{Colors.BOLD}No master exchanges connected!{Colors.RESET}")
        print(f"\n{Colors.YELLOW}Action Required:{Colors.RESET}")
        print(f"   1. Configure at least one exchange's API credentials")
        print(f"   2. Run: python3 validate_all_env_vars.py")
        print(f"   3. Fix any issues identified")
        print(f"   4. Restart NIJA bot")
    
    print(f"\n{Colors.BOLD}{'=' * 70}{Colors.RESET}\n")
    
    # Provide next steps based on status
    if master_connected:
        print(f"{Colors.BOLD}Next Steps:{Colors.RESET}")
        print(f"   • Start bot: python3 bot.py")
        print(f"   • Or use: bash start.sh")
        print(f"   • Monitor logs for trading activity")
        print()
        return 0
    else:
        print(f"{Colors.BOLD}Troubleshooting:{Colors.RESET}")
        print(f"   1. Check environment variables: python3 validate_all_env_vars.py")
        print(f"   2. Verify API key permissions (Kraken especially)")
        print(f"   3. Check .env file or platform environment variables")
        print(f"   4. See GETTING_STARTED.md for setup instructions")
        print()
        return 1


if __name__ == "__main__":
    sys.exit(main())
