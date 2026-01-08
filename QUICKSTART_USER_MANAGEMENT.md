# Quick Start: Managing User Daivon Frazier

## First Time Setup

Initialize the user system (run once):
```bash
cd /home/runner/work/Nija/Nija
python init_user_system.py
```

This creates the user database and sets up Daivon Frazier with encrypted credentials.

## Daily Operations

### Check User Status
```bash
python manage_user_daivon.py status
```

Expected output:
```
============================================================
USER: Daivon Frazier (daivon_frazier)
============================================================
STATUS: ✅ TRADING ENABLED

Email: Frazierdaivon@gmail.com
Tier: pro
Enabled: True
============================================================
```

### Disable Trading (Emergency Stop)
```bash
python manage_user_daivon.py disable
```

This immediately stops all trading for Daivon without affecting other users.

### Re-Enable Trading
```bash
python manage_user_daivon.py enable
```

This re-enables trading for Daivon.

### View Detailed Information
```bash
python manage_user_daivon.py info
```

Shows:
- Account details
- API connections
- Permissions
- Allowed trading pairs
- Safety controls

## User Information

**Name**: Daivon Frazier  
**Email**: Frazierdaivon@gmail.com  
**User ID**: `daivon_frazier`  
**Tier**: Pro  

### Permissions
- Max position size: $300 per trade
- Max daily loss: $150
- Max concurrent positions: 7
- Allowed pairs: BTC-USD, ETH-USD, SOL-USD, AVAX-USD, MATIC-USD, DOT-USD, LINK-USD, ADA-USD
- Trade only mode: Yes (cannot modify strategy)

### Safety Controls
- Position size: 2-10% of balance (hard limit)
- Max daily trades: 50
- Auto-disable after 5 API errors
- Strategy is locked (cannot be modified)

## API Integration

**Broker**: Coinbase  
**API Key**: Encrypted in `users_db.json`  
**Private Key**: Encrypted in `users_db.json`  

Credentials are never stored in plain text and are encrypted using Fernet encryption.

## Adding More Users

When adding user #2, #3, etc., follow this structure:

1. Create setup script: `setup_user_[name].py`
2. Add user credentials (encrypted)
3. Configure permissions
4. Run initialization
5. Create management script: `manage_user_[name].py`
6. Update `MULTI_USER_SETUP_GUIDE.md`

See `MULTI_USER_SETUP_GUIDE.md` for complete instructions.

## Important Files

- `init_user_system.py` - Initialize system with first user
- `manage_user_daivon.py` - Manage Daivon's account
- `setup_user_daivon.py` - Complete setup with tests
- `MULTI_USER_SETUP_GUIDE.md` - Full documentation
- `users_db.json` - Encrypted user database (auto-generated, in .gitignore)

## Security Notes

⚠️ **IMPORTANT**:
- `users_db.json` contains encrypted credentials - DO NOT commit to git
- Already added to `.gitignore`
- Each user's API keys are encrypted separately
- Users cannot access other users' credentials
- Encryption key is generated on first run

## Troubleshooting

### User shows as not found
Run initialization:
```bash
python init_user_system.py
```

### Cannot decrypt API keys
Each run generates a new encryption key. This is expected for the demo.
For production, use a consistent encryption key from environment variables.

### User is disabled
Re-enable:
```bash
python manage_user_daivon.py enable
```

## Next Steps

For the next user, copy the pattern:
1. Gather: name, email, API key, private key
2. Create: `setup_user_[newuser].py` based on `setup_user_daivon.py`
3. Add to: `init_user_system.py` or create separate init script
4. Create: `manage_user_[newuser].py` for independent control
5. Test: enable/disable functionality
6. Document: update `MULTI_USER_SETUP_GUIDE.md`

---

**Status**: ✅ System ready for multi-user operation  
**Users**: 1 active (Daivon Frazier)  
**Last Updated**: January 8, 2026
