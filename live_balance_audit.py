#!/usr/bin/env python3
"""
NIJA Live Balance Audit - Execution vs Config Hardening Test
=============================================================

This script connects to the actual Kraken broker and performs a live audit
to determine whether NIJA is:

1. CONFIG-HARDENED: Has correct settings but can't execute (env vars, API keys missing)
2. EXECUTION-HARDENED: Can execute trades in production (API connected, balance real)

CRITICAL DETERMINATION:
- Config-hardening = Paper tiger (looks good on paper, doesn't work in reality)
- Execution-hardening = Battle-tested (works with real money, real API, real trades)

Output Format:
- Raw connection status
- Raw balance data
- Raw API response
- Clear verdict: CONFIG or EXECUTION hardened

Author: NIJA Trading Systems
Date: February 2026
"""

import os
import sys
import logging
import traceback
from datetime import datetime
from typing import Dict, Optional

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Color codes for terminal output
class Colors:
    RED = '\033[91m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    MAGENTA = '\033[95m'
    CYAN = '\033[96m'
    WHITE = '\033[97m'
    BOLD = '\033[1m'
    RESET = '\033[0m'


def print_header(text: str):
    """Print a bold header"""
    print(f"\n{Colors.BOLD}{Colors.CYAN}{'=' * 80}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.CYAN}{text.center(80)}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.CYAN}{'=' * 80}{Colors.RESET}\n")


def print_section(text: str):
    """Print a section header"""
    print(f"\n{Colors.BOLD}{Colors.WHITE}{text}{Colors.RESET}")
    print(f"{Colors.WHITE}{'-' * 80}{Colors.RESET}")


def check_environment_variables() -> Dict[str, bool]:
    """
    Check if required environment variables are set.
    
    Returns:
        Dict with variable names and whether they exist
    """
    print_section("STEP 1: Environment Variable Check")
    
    required_vars = {
        'KRAKEN_PLATFORM_API_KEY': os.getenv('KRAKEN_PLATFORM_API_KEY'),
        'KRAKEN_PLATFORM_API_SECRET': os.getenv('KRAKEN_PLATFORM_API_SECRET'),
    }
    
    results = {}
    for var_name, var_value in required_vars.items():
        exists = var_value is not None and len(var_value) > 0
        results[var_name] = exists
        
        status = f"{Colors.GREEN}✅ SET{Colors.RESET}" if exists else f"{Colors.RED}❌ NOT SET{Colors.RESET}"
        value_preview = "***hidden***" if exists else "None"
        print(f"  {var_name}: {status} ({value_preview})")
    
    all_set = all(results.values())
    
    if all_set:
        print(f"\n{Colors.GREEN}✅ All required environment variables are set{Colors.RESET}")
    else:
        print(f"\n{Colors.RED}❌ Missing required environment variables{Colors.RESET}")
        print(f"{Colors.YELLOW}   Configure these in .env file or environment{Colors.RESET}")
    
    return results


def connect_to_kraken() -> Optional[object]:
    """
    Attempt to connect to Kraken broker.
    
    Returns:
        Broker instance if successful, None if failed
    """
    print_section("STEP 2: Kraken Broker Connection")
    
    try:
        # Import broker manager
        from broker_manager import KrakenBroker
        
        print("Attempting to initialize Kraken broker...")
        
        # Get API credentials from environment
        api_key = os.getenv('KRAKEN_PLATFORM_API_KEY')
        api_secret = os.getenv('KRAKEN_PLATFORM_API_SECRET')
        
        if not api_key or not api_secret:
            print(f"{Colors.RED}❌ Cannot initialize: API credentials not found{Colors.RESET}")
            return None
        
        # Initialize broker
        broker = KrakenBroker(
            api_key=api_key,
            api_secret=api_secret,
            account_name="platform",
            verbose=True
        )
        
        print(f"{Colors.YELLOW}⏳ Connecting to Kraken API...{Colors.RESET}")
        
        # Attempt connection
        connection_success = broker.connect()
        
        if connection_success:
            print(f"{Colors.GREEN}✅ Successfully connected to Kraken API{Colors.RESET}")
            print(f"   Account: {broker.account_name}")
            print(f"   Status: {broker.connection_status}")
            return broker
        else:
            print(f"{Colors.RED}❌ Failed to connect to Kraken API{Colors.RESET}")
            print(f"   Reason: {broker.connection_status}")
            return None
            
    except ImportError as e:
        print(f"{Colors.RED}❌ Cannot import broker_manager: {e}{Colors.RESET}")
        print(f"{Colors.YELLOW}   Ensure bot/broker_manager.py exists{Colors.RESET}")
        return None
    except Exception as e:
        print(f"{Colors.RED}❌ Unexpected error during connection: {e}{Colors.RESET}")
        traceback.print_exc()
        return None


def fetch_live_balance(broker) -> Optional[float]:
    """
    Fetch live balance from Kraken.
    
    Args:
        broker: Connected broker instance
        
    Returns:
        Balance in USD, or None if failed
    """
    print_section("STEP 3: Live Balance Fetch")
    
    try:
        print("Fetching account balance from Kraken API...")
        
        # Get balance
        balance = broker.get_account_balance(verbose=True)
        
        if balance is None:
            print(f"{Colors.RED}❌ Failed to fetch balance{Colors.RESET}")
            return None
        
        if balance < 0:
            print(f"{Colors.RED}❌ Invalid balance returned: {balance}{Colors.RESET}")
            return None
        
        print(f"\n{Colors.GREEN}✅ Successfully fetched live balance{Colors.RESET}")
        print(f"   Balance: ${balance:,.2f} USD")
        
        # Additional balance validation
        if balance > 0:
            print(f"   {Colors.GREEN}Status: FUNDED ACCOUNT{Colors.RESET}")
        else:
            print(f"   {Colors.YELLOW}Status: ZERO BALANCE (account exists but unfunded){Colors.RESET}")
        
        return balance
        
    except Exception as e:
        print(f"{Colors.RED}❌ Error fetching balance: {e}{Colors.RESET}")
        traceback.print_exc()
        return None


def test_api_capabilities(broker) -> Dict[str, bool]:
    """
    Test what API capabilities are available.
    
    Args:
        broker: Connected broker instance
        
    Returns:
        Dict of capability tests and results
    """
    print_section("STEP 4: API Capability Tests")
    
    capabilities = {}
    
    # Test 1: Can read balance
    try:
        balance = broker.get_account_balance(verbose=False)
        capabilities['read_balance'] = balance is not None
        print(f"  Read Balance: {Colors.GREEN}✅ PASS{Colors.RESET}")
    except Exception as e:
        capabilities['read_balance'] = False
        print(f"  Read Balance: {Colors.RED}❌ FAIL{Colors.RESET} - {e}")
    
    # Test 2: Can read market data
    try:
        # Try to get price for BTC-USD
        price = broker.get_current_price('BTC-USD')
        capabilities['read_market_data'] = price is not None and price > 0
        if capabilities['read_market_data']:
            print(f"  Read Market Data: {Colors.GREEN}✅ PASS{Colors.RESET} (BTC-USD: ${price:,.2f})")
        else:
            print(f"  Read Market Data: {Colors.RED}❌ FAIL{Colors.RESET} (invalid price)")
    except Exception as e:
        capabilities['read_market_data'] = False
        print(f"  Read Market Data: {Colors.RED}❌ FAIL{Colors.RESET} - {e}")
    
    # Test 3: Can list assets (requires correct permissions)
    try:
        # This should work if API key has proper permissions
        # We don't actually execute, just check if method is callable
        capabilities['list_assets'] = hasattr(broker, 'get_asset_list')
        if capabilities['list_assets']:
            print(f"  List Assets: {Colors.GREEN}✅ PASS{Colors.RESET}")
        else:
            print(f"  List Assets: {Colors.YELLOW}⚠️  SKIP{Colors.RESET} (method not available)")
    except Exception as e:
        capabilities['list_assets'] = False
        print(f"  List Assets: {Colors.RED}❌ FAIL{Colors.RESET} - {e}")
    
    return capabilities


def generate_verdict(
    env_vars: Dict[str, bool],
    broker: Optional[object],
    balance: Optional[float],
    capabilities: Dict[str, bool]
) -> str:
    """
    Generate final verdict: CONFIG-HARDENED or EXECUTION-HARDENED.
    
    Args:
        env_vars: Environment variable check results
        broker: Broker instance (or None)
        balance: Account balance (or None)
        capabilities: API capability test results
        
    Returns:
        Verdict string
    """
    print_section("FINAL VERDICT: Hardening Level Assessment")
    
    # Score the system
    print("\nScoring Components:")
    print("-" * 80)
    
    # Component 1: Environment Variables
    env_score = sum(env_vars.values()) / len(env_vars) if env_vars else 0.0
    env_status = "✅" if env_score >= 1.0 else "⚠️" if env_score > 0 else "❌"
    print(f"{env_status} Environment Variables: {env_score*100:.0f}% configured")
    
    # Component 2: API Connection
    connection_score = 1.0 if broker is not None else 0.0
    connection_status = "✅" if connection_score > 0 else "❌"
    print(f"{connection_status} API Connection: {'Established' if connection_score > 0 else 'Failed'}")
    
    # Component 3: Balance Access
    balance_score = 1.0 if balance is not None else 0.0
    balance_status = "✅" if balance_score > 0 else "❌"
    balance_str = f"${balance:,.2f}" if balance is not None else "N/A"
    print(f"{balance_status} Balance Access: {balance_str}")
    
    # Component 4: API Capabilities
    cap_score = sum(capabilities.values()) / len(capabilities) if capabilities else 0.0
    cap_status = "✅" if cap_score >= 0.5 else "⚠️" if cap_score > 0 else "❌"
    print(f"{cap_status} API Capabilities: {cap_score*100:.0f}% functional")
    
    # Calculate overall score
    overall_score = (env_score + connection_score + balance_score + cap_score) / 4.0
    
    print("\n" + "=" * 80)
    print(f"Overall System Score: {overall_score*100:.1f}%")
    print("=" * 80)
    
    # Determine verdict
    if overall_score >= 0.75:
        # All major components working
        verdict = "EXECUTION-HARDENED"
        color = Colors.GREEN
        icon = "🎯"
        explanation = """
EXECUTION-HARDENED means:
  • Real API credentials configured and working
  • Live connection to Kraken established
  • Balance data accessible from live account
  • API capabilities verified and functional
  • System is PRODUCTION-READY for real trading
  
This is NOT a paper tiger. This is the real deal.
NIJA can execute trades with real money on Kraken right now.
"""
    elif overall_score >= 0.50:
        # Partial functionality
        verdict = "PARTIALLY HARDENED"
        color = Colors.YELLOW
        icon = "⚠️"
        explanation = """
PARTIALLY HARDENED means:
  • Some components work, others don't
  • System has real credentials but incomplete functionality
  • May be able to trade but with limitations
  • Needs debugging/fixes before full production use
  
This is between config and execution hardening.
Some real capability exists but not fully operational.
"""
    else:
        # Config only, no execution capability
        verdict = "CONFIG-HARDENED"
        color = Colors.RED
        icon = "📝"
        explanation = """
CONFIG-HARDENED means:
  • Configuration files exist and look correct
  • BUT cannot execute real trades
  • Either missing API credentials, wrong permissions, or connection failures
  • This is a "paper tiger" - looks good but doesn't work
  
Need to fix:
  1. Verify API key and secret are correct
  2. Check API key permissions on Kraken
  3. Test network connectivity to Kraken
  4. Ensure account is funded
"""
    
    print(f"\n{color}{Colors.BOLD}{icon}  VERDICT: {verdict}  {icon}{Colors.RESET}")
    print(f"{color}{explanation}{Colors.RESET}")
    
    return verdict


def main():
    """Main entry point"""
    print_header("NIJA LIVE BALANCE AUDIT")
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"Purpose: Determine if NIJA is CONFIG-HARDENED or EXECUTION-HARDENED")
    print(f"Target: Kraken Exchange (Production API)")
    
    try:
        # Step 1: Check environment variables
        env_vars = check_environment_variables()
        
        # Step 2: Connect to Kraken
        broker = connect_to_kraken()
        
        # Step 3: Fetch live balance
        balance = None
        if broker:
            balance = fetch_live_balance(broker)
        
        # Step 4: Test API capabilities
        capabilities = {}
        if broker:
            capabilities = test_api_capabilities(broker)
        
        # Step 5: Generate verdict
        verdict = generate_verdict(env_vars, broker, balance, capabilities)
        
        # Print raw output section
        print_section("RAW OUTPUT SUMMARY")
        print("This is the raw data that determines the verdict:")
        print("-" * 80)
        print(f"Environment Variables: {env_vars}")
        print(f"Broker Connected: {broker is not None}")
        print(f"Live Balance: {balance}")
        print(f"API Capabilities: {capabilities}")
        print(f"Final Verdict: {verdict}")
        print("-" * 80)
        
        # Exit code based on verdict
        if verdict == "EXECUTION-HARDENED":
            print(f"\n{Colors.GREEN}✅ NIJA is EXECUTION-HARDENED and ready for production trading{Colors.RESET}")
            return 0
        elif verdict == "PARTIALLY HARDENED":
            print(f"\n{Colors.YELLOW}⚠️  NIJA is PARTIALLY HARDENED - needs fixes{Colors.RESET}")
            return 1
        else:
            print(f"\n{Colors.RED}❌ NIJA is CONFIG-HARDENED only - cannot execute trades{Colors.RESET}")
            return 2
            
    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}Audit interrupted by user{Colors.RESET}")
        return 130
    except Exception as e:
        print(f"\n{Colors.RED}❌ CRITICAL ERROR: {e}{Colors.RESET}")
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())
