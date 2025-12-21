#!/usr/bin/env python3
"""
Instructions to move funds from Default/Primary to NIJA Portfolio
"""

print("\n" + "="*80)
print("📋 HOW TO TRANSFER FUNDS TO NIJA PORTFOLIO")
print("="*80 + "\n")

print("Your situation:")
print("✅ You have 2 Coinbase portfolios:")
print("   1. Default/Primary Portfolio - HAS YOUR 10 CRYPTO + CASH")
print("   2. NIJA Portfolio - EMPTY (where your API key accesses)")
print()
print("❌ Problem: API key can only see NIJA Portfolio (empty)")
print("✅ Solution: Transfer funds from Default/Primary → NIJA Portfolio\n")

print("="*80)
print("STEP-BY-STEP TRANSFER INSTRUCTIONS")
print("="*80 + "\n")

print("1️⃣  LOGIN TO COINBASE")
print("   → Go to https://www.coinbase.com/advanced-portfolio")
print("   → Make sure you're logged in\n")

print("2️⃣  SWITCH TO DEFAULT/PRIMARY PORTFOLIO")
print("   → Top navigation: Click portfolio dropdown")
print("   → Select 'Default' or 'Primary' portfolio")
print("   → You should see your 10 crypto + cash here\n")

print("3️⃣  TRANSFER EACH CRYPTO POSITION")
print("   For EACH of your 10 crypto:")
print("   → Click on the crypto (e.g., BTC, ETH, etc.)")
print("   → Click 'Transfer' or 'Send'")
print("   → Select 'To another Coinbase portfolio'")
print("   → Choose destination: 'NIJA Portfolio'")
print("   → Enter amount: ALL (max amount)")
print("   → Confirm transfer\n")

print("4️⃣  TRANSFER YOUR CASH (USD/USDC)")
print("   → Click on USD or USDC balance")
print("   → Click 'Transfer'")
print("   → Select 'To another Coinbase portfolio'")
print("   → Choose destination: 'NIJA Portfolio'")
print("   → Enter amount: ALL (max amount)")
print("   → Confirm transfer\n")

print("5️⃣  VERIFY TRANSFER COMPLETED")
print("   → Switch to 'NIJA Portfolio' in the dropdown")
print("   → You should now see all 10 crypto + cash here")
print("   → Default/Primary should be empty\n")

print("6️⃣  TEST THE API CONNECTION")
print("   Run this command to verify:")
print("   → python3 check_nija_trading_status.py")
print("   → You should now see your positions and cash!\n")

print("="*80)
print("⚠️  IMPORTANT NOTES")
print("="*80 + "\n")

print("• The 2 staking positions might NOT be transferable")
print("  (Staked crypto often locked until unstaking period ends)")
print("  → Those will stay in Default/Primary until unstaking completes\n")

print("• This is an INTERNAL transfer (within Coinbase)")
print("  → No fees")
print("  → Instant")
print("  → No blockchain transaction needed\n")

print("• After transfer, NIJA bot will be able to:")
print("  ✅ See all positions")
print("  ✅ Manage stop losses and take profits")
print("  ✅ Close positions automatically")
print("  ✅ Open new positions with available cash\n")

print("="*80)
print("ALTERNATIVE: USE DEFAULT/PRIMARY PORTFOLIO API KEY")
print("="*80 + "\n")

print("If you prefer NOT to transfer, you can instead:")
print("1. Go to Coinbase Settings → API")
print("2. Make sure you're viewing Default/Primary Portfolio")
print("3. Create new API keys for that portfolio")
print("4. Copy those credentials")
print("5. Update your .env file with the new credentials")
print()
print("⚠️  But recommended approach: Transfer funds to NIJA Portfolio\n")

print("="*80 + "\n")
