# Coinbase API Permission Requirements

## Current Issue
The bot cannot access your $156.97 in Advanced Trade because the API keys are missing portfolio access permissions.

## Required API Permissions

When creating new API keys at https://www.coinbase.com/settings/api, you MUST enable:

### ✅ Required Scopes:
- **View** (`wallet:accounts:read`)
- **Trade** (`wallet:trades:read`, `wallet:trades:create`)
- **Transfer** (`wallet:transactions:read`)
- **Portfolio Management** ← **CRITICAL!**

### ✅ Portfolio Access:
- Select **"All portfolios"** 
- OR specifically select both:
  - Default portfolio
  - Nija portfolio

## How to Fix

### Option 1: Run the Guided Script
```bash
bash fix_api_permissions.sh
```

This will:
1. Show you exactly what permissions to enable
2. Guide you through creating new keys
3. Help you update the .env file
4. Test that it works

### Option 2: Manual Fix

1. **Create new API keys:**
   - Go to: https://www.coinbase.com/settings/api
   - Create "Cloud API Trading Keys" (not Legacy)
   - Enable all permissions listed above
   - Select "All portfolios"

2. **Update credentials:**
   ```bash
   # Edit this file with your new keys:
   nano quick_update_keys.py
   
   # Then run:
   python3 quick_update_keys.py
   ```

3. **Verify it works:**
   ```bash
   python3 find_my_157.py
   ```
   
   Should show: `💰 Advanced Trade USD Total: $156.97`

## Testing the Fix

After updating keys, run:
```bash
python3 find_my_157.py
```

Expected output:
```
🎯 FOUND IT! $156.97 in ADVANCED TRADE
✅ Bot CAN trade these funds!
```

## Security Notes

⚠️ **NEVER** commit API keys to version control  
⚠️ Keys are stored in `.env` (already in `.gitignore`)  
⚠️ If compromised, immediately revoke in Coinbase settings

## Next Steps After Fix

Once the API can see your funds:

1. **Restart the bot** - it will automatically detect the balance
2. **Bot will start trading** with the $156.97
3. **Monitor via:** `python3 check_current_positions.py`

## Support

If still having issues after following these steps, check:
- Are you using the correct Coinbase account email?
- Did you download the key file and save the PEM?
- Did you select "All portfolios" when creating the key?
