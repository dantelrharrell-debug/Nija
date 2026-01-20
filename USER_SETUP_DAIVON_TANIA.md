# User Setup: Daivon Frazier & Tania Gilbert

## ✅ Configuration Files Created

The following user config files have been created:

1. `config/users/daivon_frazier.json`
2. `config/users/tania_gilbert.json`

Each file contains the required configuration:
```json
{
  "name": "User Name",
  "broker": "kraken",
  "role": "user",
  "enabled": true,
  "copy_from_master": true,
  "risk_multiplier": 1.0
}
```

## 🔑 Required Environment Variables

For the bot to load these users, the following environment variables **MUST** be set:

### Daivon Frazier
```bash
KRAKEN_USER_DAIVON_API_KEY=your_api_key_here
KRAKEN_USER_DAIVON_API_SECRET=your_api_secret_here
```

### Tania Gilbert
```bash
KRAKEN_USER_TANIA_API_KEY=your_api_key_here
KRAKEN_USER_TANIA_API_SECRET=your_api_secret_here
```

## 📝 Setting Environment Variables

### Option 1: Add to `.env` file (Recommended)

Edit your `.env` file and add:
```bash
# Daivon Frazier - Kraken User
KRAKEN_USER_DAIVON_API_KEY=your_actual_api_key
KRAKEN_USER_DAIVON_API_SECRET=your_actual_api_secret

# Tania Gilbert - Kraken User  
KRAKEN_USER_TANIA_API_KEY=your_actual_api_key
KRAKEN_USER_TANIA_API_SECRET=your_actual_api_secret
```

### Option 2: Set in Railway/Deployment Platform

If deploying to Railway, Render, or another platform:

1. Go to your project settings
2. Navigate to environment variables
3. Add each variable with its value
4. Save changes

## 🔄 Restart Required

After setting the environment variables, you **MUST** perform a **FULL RESTART** of the bot.

### ❌ Not Sufficient:
- Reload
- Partial redeploy
- Hot restart

### ✅ Required:
- **Hard restart** of the entire bot process
- Full application restart on Railway/deployment platform

### How to Restart:

#### Local Development:
```bash
# Stop the bot (Ctrl+C)
# Then restart:
./start.sh
# or
python3 main.py
```

#### Railway:
1. Go to your Railway project
2. Click on your service
3. Click "Restart" button
4. Or redeploy the service completely

#### Docker:
```bash
docker-compose down
docker-compose up -d
```

## ✨ Auto-Enable Feature

The new loader automatically enables users if their API keys are detected:

- If API keys exist → User is **AUTO-ENABLED**
- If API keys missing → User stays disabled, **HARD FAIL** occurs

## 🛑 Hard Fail Mode

The bot now uses **HARD FAIL** mode for user loading:

- If required users are missing → **BOT FAILS TO START**
- If API keys are not set → **BOT FAILS TO START**
- No silent fallback or warnings

This ensures:
- You know immediately if configuration is wrong
- No silent failures that could cause missed trades
- Clear error messages telling you exactly what's missing

## 🧪 Testing Configuration

Run this test to verify your configuration:

```bash
python3 test_individual_user_loader.py
```

This will:
1. Check if config files exist
2. Verify environment variables are set
3. Test both soft fail and hard fail modes
4. Show clear error messages if anything is wrong

### Expected Output (Success):
```
✅ All tests passed! Users are ready for trading.
```

### Expected Output (Missing API Keys):
```
❌ FAILED (Invalid Config/API Keys): HARD FAIL: Invalid users...
```

## 📋 Checklist

Before starting the bot, ensure:

- [ ] Config files exist in `config/users/`
  - [ ] `daivon_frazier.json`
  - [ ] `tania_gilbert.json`
- [ ] Environment variables are set
  - [ ] `KRAKEN_USER_DAIVON_API_KEY`
  - [ ] `KRAKEN_USER_DAIVON_API_SECRET`
  - [ ] `KRAKEN_USER_TANIA_API_KEY`
  - [ ] `KRAKEN_USER_TANIA_API_SECRET`
- [ ] Run test script: `python3 test_individual_user_loader.py`
- [ ] Perform HARD RESTART of the bot

## 🚨 Troubleshooting

### Error: "HARD FAIL: Invalid users"

**Cause**: API keys are not set in environment variables

**Fix**:
1. Add API keys to `.env` or deployment platform
2. Verify variable names are EXACTLY as shown above (case-sensitive)
3. Restart the bot (hard restart required)

### Error: "Config directory not found"

**Cause**: The `config/users/` directory doesn't exist

**Fix**:
1. Ensure you're in the correct directory
2. Check that `config/users/` exists
3. Verify config files are present

### Users show as disabled

**Cause**: API keys are not detected

**Fix**:
1. Check environment variable names (must match exactly)
2. Ensure values are not empty
3. Restart the bot after setting variables

## 📞 Support

If you encounter issues:
1. Run the test script and share the output
2. Verify all environment variables are set
3. Check that config files match the required format
4. Ensure you performed a HARD RESTART

---

**Last Updated**: 2026-01-20
**Status**: ✅ Configuration files created, loader implemented
**Next Step**: Set environment variables and restart bot
