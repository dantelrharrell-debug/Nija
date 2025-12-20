# 🔍 How to Check Your Coinbase Account Status

## Option 1: Check Render Logs (FASTEST)

1. Go to your Render dashboard
2. Open the NIJA service
3. Click "Logs" tab
4. Look for the latest balance check (happens every ~15 seconds)

You'll see lines like:
```
Consumer USD (v2 API): $XX.XX [NOT TRADABLE]
Consumer USDC (v2 API): $XX.XX [NOT TRADABLE]  
Advanced Trade USD (v3 API): $XX.XX [TRADABLE ✅]
Advanced Trade USDC (v3 API): $XX.XX [TRADABLE ✅]
```

## Option 2: Manually Check on Coinbase

### Consumer Wallet Balance:
1. Go to https://www.coinbase.com
2. Click "Assets" 
3. Look at your holdings (USD, USDC, and crypto)

### Advanced Trade Balance:
1. Go to https://www.coinbase.com/advanced-trade
2. Look at bottom left "Portfolio value"
3. Click "Holdings" to see what's in Advanced Trade

## What You're Looking For:

### ✅ GOOD (Bot can trade):
```
Advanced Trade USD/USDC: $50+ 
Consumer: $0
```

### ❌ BAD (Bot cannot trade):
```
Consumer USD/USDC: $50+
Advanced Trade: $0
```

### ⚠️ CRYPTO HOLDINGS:
- **Consumer wallet crypto**: Bot CANNOT sell (manual sale required)
- **Advanced Trade crypto**: Bot CAN sell (if it created the position)

## Quick Status from Latest Logs:

Based on your last logs shown:
- Consumer wallet: $57.54 (NOT TRADABLE)
- Advanced Trade: $0.00 (TRADABLE)

**Current Status: ❌ FUNDS IN WRONG LOCATION**

## Transfer Instructions:

If funds are in Consumer wallet:
1. https://www.coinbase.com/advanced-portfolio
2. Click "Deposit" → "From Coinbase"
3. Transfer USD/USDC to Advanced Trade
4. Wait 30 seconds
5. Check Render logs again

## Check Crypto Holdings:

If you have crypto in Consumer wallet (your 8+ holdings):
- These CANNOT be sold via bot
- You must manually sell on Coinbase.com
- Or check if they can be transferred to Advanced Trade first
