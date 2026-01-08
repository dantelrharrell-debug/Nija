# NIJA User & Investor Registry

**Official Registry of All Users and Investors**  
**Last Updated**: January 8, 2026

---

## Overview

This registry maintains a comprehensive record of all users and investors in the NIJA trading platform. Each entry includes complete contact information, permissions, trading status, and performance metrics.

---

## Active Users

### User #1: Daivon Frazier

**Status**: 🟢 ACTIVE  
**Type**: Investor/User  
**Tier**: Pro

#### Contact Information
- **Full Name**: Daivon Frazier
- **Email**: Frazierdaivon@gmail.com
- **User ID**: `daivon_frazier`
- **Added**: January 8, 2026
- **Added By**: System Administrator

#### API Credentials
- **Broker**: Coinbase
- **API Key**: `HSo/f1zjeQALCM/rri9bjTB5JisQ/SPgurCRTx8W7kLD7psjcv2PXEf+` (Encrypted)
- **Private Key**: `6WOxnBLq+r4ln2Zz7nT0Nvv8CMkaolHtjYdOgTm7NWIq/mJqV8KbDA2XaThP65bHK9QvpEabRr1u38FrBJntaQ==` (Encrypted)
- **Credentials Status**: ✅ Encrypted and Stored
- **Last Verified**: January 8, 2026

#### Trading Permissions
- **Max Position Size**: $300 USD per trade
- **Max Daily Loss**: $150 USD
- **Max Concurrent Positions**: 7
- **Trade-Only Mode**: Yes (Cannot modify strategy)
- **Allowed Trading Pairs**:
  1. BTC-USD (Bitcoin)
  2. ETH-USD (Ethereum)
  3. SOL-USD (Solana)
  4. AVAX-USD (Avalanche)
  5. MATIC-USD (Polygon)
  6. DOT-USD (Polkadot)
  7. LINK-USD (Chainlink)
  8. ADA-USD (Cardano)

#### Account Settings
- **Risk Level**: Moderate
- **Trailing Stops**: Enabled
- **Auto-Compound**: Enabled
- **Notifications**: Enabled to Frazierdaivon@gmail.com

#### Control & Management
- **Trading Enabled**: ✅ Yes
- **Last Status Check**: January 8, 2026
- **Management Script**: `manage_user_daivon.py`
- **Setup Script**: `setup_user_daivon.py`
- **Control Commands**:
  ```bash
  python manage_user_daivon.py status    # Check status
  python manage_user_daivon.py enable    # Enable trading
  python manage_user_daivon.py disable   # Disable trading
  python manage_user_daivon.py info      # View details
  ```

#### Performance Metrics
- **Account Balance**: TBD
- **Total Trades**: 0 (Just initialized)
- **Winning Trades**: 0
- **Losing Trades**: 0
- **Win Rate**: N/A
- **Total P&L**: $0.00
- **ROI**: 0%
- **Best Trade**: N/A
- **Worst Trade**: N/A
- **Average Trade**: N/A

#### Activity Log
| Date | Event | Details | By |
|------|-------|---------|-----|
| 2026-01-08 | Account Created | Pro tier, Coinbase integration | System Admin |
| 2026-01-08 | API Keys Added | Encrypted credentials stored | System Admin |
| 2026-01-08 | Permissions Set | Max $300 position, 7 concurrent | System Admin |
| 2026-01-08 | Trading Enabled | Account activated | System Admin |

#### Notes
- First user in the layered architecture system
- Serves as template for future user additions
- Full documentation in `USER_SETUP_COMPLETE_DAIVON.md`

---

## Pending Users

*No pending users at this time.*

---

## Inactive/Suspended Users

*No inactive users at this time.*

---

## User Statistics

**Total Users**: 1  
**Active Users**: 1  
**Pending Users**: 0  
**Suspended Users**: 0  
**Deleted Users**: 0

**By Tier**:
- Basic: 0
- Pro: 1 (Daivon Frazier)
- Enterprise: 0

**By Broker**:
- Coinbase: 1 (Daivon Frazier)
- Binance: 0
- OKX: 0
- Kraken: 0
- Alpaca: 0

---

## Adding New Users

When adding a new user to this registry:

1. **Create User Profile** (above)
   - Full contact information
   - API credentials (encrypted)
   - Trading permissions
   - Management details

2. **Update Statistics** (above)
   - Increment total users
   - Update tier counts
   - Update broker counts

3. **Create User Files**
   - `setup_user_[name].py`
   - `manage_user_[name].py`
   - `USER_SETUP_COMPLETE_[NAME].md`

4. **Update Related Documentation**
   - `USER_INVESTOR_TRACKING.md`
   - `MULTI_USER_SETUP_GUIDE.md`
   - `README.md`

5. **Log Activity**
   - Add entry to activity log
   - Document in version control

---

## Registry Maintenance

**Maintained By**: NIJA System Administrator  
**Update Frequency**: Real-time for critical changes, daily summary updates  
**Review Schedule**: Weekly review of all user statuses  
**Backup**: Encrypted credentials backed up in `users_db.json` (not in git)

---

## Contact for Registry Issues

If there are any discrepancies or issues with this registry:
1. Verify with `python manage_user_[name].py status`
2. Check `users_db.json` for encrypted data
3. Review user setup documentation
4. Contact system administrator

---

**Document Version**: 1.0  
**Created**: January 8, 2026  
**Last Modified**: January 8, 2026  
**Next Review**: January 15, 2026
