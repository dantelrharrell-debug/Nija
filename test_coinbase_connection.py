#!/usr/bin/env python3
"""
Simple Coinbase Connection Test
Tests if Coinbase API is accessible without starting the full bot
Use this to verify if 403 block has cleared
"""

import os
import sys

def test_connection():
    """Test Coinbase connection"""
    
    print("\n" + "="*70)
    print("🔍 COINBASE API CONNECTION TEST")
    print("="*70)
    print()
    
    # Check for credentials
    api_key = os.getenv("COINBASE_API_KEY")
    api_secret = os.getenv("COINBASE_API_SECRET")
    
    if not api_key:
        print("❌ COINBASE_API_KEY not found in environment")
        print("   Set the environment variable and try again")
        return False
    
    if not api_secret:
        print("❌ COINBASE_API_SECRET not found in environment")
        print("   Set the environment variable and try again")
        return False
    
    print(f"✅ API Key found: {api_key[:10]}...{api_key[-5:]}")
    print(f"✅ API Secret found: {len(api_secret)} characters")
    print()
    
    # Try to import Coinbase SDK
    try:
        from coinbase.rest import RESTClient
    except ImportError:
        print("❌ Coinbase SDK not installed")
        print("   Run: pip install coinbase-advanced-py")
        return False
    
    print("✅ Coinbase SDK imported")
    print()
    
    # Try to connect
    print("🔄 Testing connection to Coinbase Advanced Trade API...")
    print("   This may take a few seconds...")
    print()
    
    try:
        client = RESTClient(api_key=api_key, api_secret=api_secret)
        accounts = client.get_accounts()
        
        print("=" * 70)
        print("✅ CONNECTION SUCCESSFUL!")
        print("=" * 70)
        print()
        print(f"Found {len(accounts.accounts)} accounts in your Coinbase profile")
        print()
        
        # Show some account details (without sensitive info)
        print("Accounts:")
        for i, account in enumerate(accounts.accounts[:5], 1):
            name = account.get('name', 'Unknown')
            currency = account.get('currency', 'Unknown')
            print(f"  {i}. {name} ({currency})")
        
        if len(accounts.accounts) > 5:
            print(f"  ... and {len(accounts.accounts) - 5} more")
        
        print()
        print("🎉 API is accessible - Bot should be able to connect!")
        print()
        print("Next steps:")
        print("  1. The 403 block has cleared")
        print("  2. You can safely start/restart the bot")
        print("  3. Bot should connect successfully")
        print()
        print("=" * 70)
        
        return True
        
    except Exception as e:
        error_msg = str(e)
        
        print("=" * 70)
        print("❌ CONNECTION FAILED")
        print("=" * 70)
        print()
        print(f"Error: {error_msg}")
        print()
        
        # Diagnose the error
        if "403" in error_msg or "forbidden" in error_msg.lower():
            print("⚠️  DIAGNOSIS: 403 Forbidden Error")
            print()
            print("The API key is still temporarily blocked by Coinbase.")
            print()
            print("What this means:")
            print("  - Your API key triggered Coinbase's abuse detection")
            print("  - The block is still in effect")
            print("  - You need to wait longer")
            print()
            print("What to do:")
            print("  1. Wait another 15-30 minutes")
            print("  2. Don't make any more API calls during this time")
            print("  3. Run this test again after waiting")
            print("  4. Don't restart the bot until this test passes")
            print()
            
        elif "401" in error_msg or "unauthorized" in error_msg.lower():
            print("⚠️  DIAGNOSIS: 401 Unauthorized Error")
            print()
            print("Your API credentials are invalid or incorrect.")
            print()
            print("What to do:")
            print("  1. Log into Coinbase")
            print("  2. Go to Settings → API Keys")
            print("  3. Verify your API key is valid and not revoked")
            print("  4. Check that you're using the correct key and secret")
            print("  5. If needed, create a new API key")
            print("  6. Update your environment variables:")
            print("     export COINBASE_API_KEY='your-new-key'")
            print("     export COINBASE_API_SECRET='your-new-secret'")
            print()
            
        elif "429" in error_msg or "rate limit" in error_msg.lower():
            print("⚠️  DIAGNOSIS: 429 Rate Limit Error")
            print()
            print("You're making too many requests too quickly.")
            print()
            print("What to do:")
            print("  1. Wait 5-10 minutes")
            print("  2. Run this test again")
            print("  3. If it persists, wait longer")
            print()
            
        elif "timeout" in error_msg.lower() or "connection" in error_msg.lower():
            print("⚠️  DIAGNOSIS: Network/Connection Error")
            print()
            print("Network issue preventing connection to Coinbase.")
            print()
            print("What to do:")
            print("  1. Check your internet connection")
            print("  2. Verify you can access https://www.coinbase.com/")
            print("  3. Check Coinbase status: https://status.coinbase.com/")
            print("  4. Try again in a few minutes")
            print()
            
        else:
            print("⚠️  DIAGNOSIS: Unknown Error")
            print()
            print("What to do:")
            print("  1. Check the error message above")
            print("  2. Verify API credentials are correct")
            print("  3. Check Coinbase status: https://status.coinbase.com/")
            print("  4. Wait 5-10 minutes and try again")
            print()
        
        print("=" * 70)
        print()
        
        return False

if __name__ == "__main__":
    success = test_connection()
    sys.exit(0 if success else 1)
