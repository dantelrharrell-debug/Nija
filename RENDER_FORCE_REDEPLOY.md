# Force Render to Redeploy Latest Code

## Problem
Render is not picking up the enhanced debugging code that was just pushed to GitHub.

## Solution: Manual Redeploy

### Option 1: Trigger Manual Deploy in Render Dashboard
1. Go to https://dashboard.render.com/
2. Find your NIJA service
3. Click "Manual Deploy" → "Deploy latest commit"
4. Wait for build to complete
5. Check logs again for enhanced debugging output

### Option 2: Clear Build Cache
1. Go to Render dashboard → Your service → Settings
2. Scroll to "Build & Deploy"
3. Click "Clear build cache"
4. Trigger manual deploy
5. This forces Render to rebuild from scratch with latest code

### Option 3: Dummy Commit to Force Redeploy
```bash
cd /workspaces/Nija
echo "# Force redeploy" >> README.md
git add README.md
git commit -m "Force Render redeploy - trigger build"
git push origin main
```

## What to Look For in New Logs

After redeployment, you should see:
```
💰 Checking v3 API (Advanced Trade - TRADABLE BALANCE)...
   🔍 Calling client.list_accounts()...
📁 v3 Advanced Trade API: 0 account(s)
   🚨 API returned ZERO accounts!
```

OR if accounts are found:
```
📁 v3 Advanced Trade API: 5 account(s)
   📋 Listing all 5 accounts:
      → USD: $57.54 | Default | ACCOUNT | UUID: abc12345...
      → BTC: $0.00 | Default | ACCOUNT | UUID: def67890...
```

## Critical Issue

If API returns **0 accounts**, the problem is:
- ❌ API credentials are for wrong Coinbase organization
- ❌ API credentials are expired/invalid  
- ❌ API key doesn't have portfolio access permissions

This CANNOT be fixed with code - you need to verify:
1. API keys in Render match keys from Coinbase Cloud API settings
2. Keys are for the correct Coinbase account (Dantelrharrell@gmail.com)
3. Keys have "View" and "Trade" permissions enabled
