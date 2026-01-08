# User & Investor Tracking System

**Comprehensive Tracking and Management System for All NIJA Users**

---

## Table of Contents

1. [Overview](#overview)
2. [Tracking Files](#tracking-files)
3. [User Lifecycle](#user-lifecycle)
4. [Performance Tracking](#performance-tracking)
5. [Communication Log](#communication-log)
6. [Financial Tracking](#financial-tracking)
7. [Compliance & Reporting](#compliance--reporting)

---

## Overview

This document outlines NIJA's complete tracking system for users and investors. It ensures accountability, transparency, and proper record-keeping for all trading activities and user interactions.

### Key Principles

1. **Individual Tracking**: Each user has separate records and controls
2. **Real-time Updates**: Status and performance updated continuously
3. **Encrypted Security**: All credentials encrypted and secured
4. **Full Audit Trail**: Complete history of all user activities
5. **Easy Access**: Quick status checks via CLI commands

---

## Tracking Files

### Master Registry
**File**: `USER_INVESTOR_REGISTRY.md`
- Complete list of all users
- Contact information
- Trading permissions
- Current status
- Performance summaries

### Individual User Files

For each user (example: Daivon Frazier):

1. **Setup Documentation**
   - File: `USER_SETUP_COMPLETE_DAIVON.md`
   - Initial configuration details
   - API credentials info (encrypted references)
   - Permission settings
   - Setup date and administrator

2. **Management Script**
   - File: `manage_user_daivon.py`
   - Enable/disable trading
   - Check status
   - View detailed information
   - Update settings

3. **Setup Script**
   - File: `setup_user_daivon.py`
   - Initial user creation
   - Credential encryption
   - Permission configuration
   - Testing procedures

4. **Activity Log**
   - File: `USER_ACTIVITY_LOG_DAIVON.md` (auto-generated)
   - All trades executed
   - Status changes
   - Configuration updates
   - Communication history

### System-wide Files

1. **users_db.json**
   - Encrypted credential storage
   - User configurations
   - Permission settings
   - **NOT** in version control (in .gitignore)

2. **MULTI_USER_SETUP_GUIDE.md**
   - Instructions for adding new users
   - Template for user setup
   - Best practices

3. **QUICKSTART_USER_MANAGEMENT.md**
   - Quick reference for daily operations
   - Common commands
   - Troubleshooting

---

## User Lifecycle

### 1. User Onboarding

**Documentation**: `USER_INVESTOR_REGISTRY.md` (new entry)

**Required Information**:
- Full legal name
- Contact email
- Phone number (optional)
- Broker API credentials
- Preferred subscription tier
- Initial capital amount
- Risk tolerance

**Process**:
1. Collect user information
2. Verify identity and credentials
3. Create user account: `setup_user_[name].py`
4. Configure permissions
5. Encrypt and store credentials
6. Initialize tracking
7. Send welcome email with management instructions
8. Add to registry

**Checklist**:
- [ ] Contact information collected
- [ ] API credentials verified
- [ ] User account created
- [ ] Permissions configured
- [ ] Credentials encrypted
- [ ] Management scripts created
- [ ] Documentation updated
- [ ] User notified
- [ ] Registry updated

### 2. Active Trading

**Daily Tracking**:
```bash
# Check user status
python manage_user_daivon.py status

# View detailed performance
python manage_user_daivon.py info
```

**Weekly Review**:
- Performance metrics
- Risk exposure
- Position sizes
- Win/loss ratios
- Communication needs

**Monthly Reporting**:
- Complete performance summary
- P&L statement
- Trade journal review
- Strategy effectiveness
- Recommendations

### 3. Status Changes

**Enable Trading**:
```bash
python manage_user_daivon.py enable
```
- Log: Activity timestamp, reason, administrator
- Notify: User via email
- Update: Registry status to ACTIVE

**Disable Trading**:
```bash
python manage_user_daivon.py disable
```
- Log: Activity timestamp, reason, administrator
- Notify: User via email
- Update: Registry status to SUSPENDED
- Reason: Required for suspension

**Reactivation**:
- Review suspension reason
- Verify issues resolved
- Enable trading
- Log reactivation

### 4. User Offboarding

**Process**:
1. Disable trading
2. Close all positions
3. Calculate final P&L
4. Generate final report
5. Archive credentials (encrypted)
6. Update registry to INACTIVE
7. Move to inactive section

**Documentation**:
- Final performance report
- Exit date and reason
- Total P&L
- Account status at exit

---

## Performance Tracking

### Real-time Metrics

Track for each user:

1. **Trade Statistics**
   - Total trades executed
   - Winning trades
   - Losing trades
   - Win rate percentage
   - Average trade duration
   - Largest win
   - Largest loss

2. **Financial Metrics**
   - Starting balance
   - Current balance
   - Total P&L ($)
   - Total P&L (%)
   - ROI
   - Best day
   - Worst day
   - Average daily P&L

3. **Risk Metrics**
   - Current positions
   - Total exposure
   - Max drawdown
   - Sharpe ratio
   - Risk/reward ratio
   - Daily loss limit status

### Performance Reports

**Daily Summary** (auto-generated):
```
User: Daivon Frazier
Date: 2026-01-08
Trades: 3 (2 wins, 1 loss)
P&L: +$45.50 (+1.2%)
Win Rate: 66.7%
Status: Active
```

**Weekly Report**:
- 7-day performance chart
- Trade breakdown
- Best/worst trades
- Risk analysis
- Recommendations

**Monthly Report**:
- 30-day performance
- Strategy effectiveness
- Position analysis
- Full trade journal
- Compliance review

### Tracking Script

**File**: `track_user_performance.py` (to be created)
```python
# Example usage
python track_user_performance.py daivon_frazier --period=daily
python track_user_performance.py daivon_frazier --period=weekly
python track_user_performance.py daivon_frazier --period=monthly
```

---

## Communication Log

### User Communication Tracking

**File**: `USER_COMMUNICATION_LOG.md`

Track all communications with users:

| Date | User | Type | Subject | Details | Follow-up |
|------|------|------|---------|---------|-----------|
| 2026-01-08 | Daivon Frazier | Email | Welcome | Account setup complete | None |
| 2026-01-08 | Daivon Frazier | System | Setup | First user initialized | Monitor performance |

**Communication Types**:
- Email (outbound)
- Email (inbound)
- System notification
- Alert/warning
- Performance update
- Emergency contact
- Support request
- Feedback

### Templates

**Welcome Email**:
```
Subject: Welcome to NIJA Trading Platform

Dear [User Name],

Your NIJA trading account is now active!

User ID: [user_id]
Tier: [tier]
Status: Active

You can check your status anytime:
python manage_user_[name].py status

Questions? Reply to this email.

Best regards,
NIJA Team
```

**Performance Update**:
```
Subject: Weekly Performance Update - [Date]

Dear [User Name],

Your weekly trading summary:
- Trades: [count]
- Win Rate: [percentage]
- P&L: [amount]

Full details available via:
python manage_user_[name].py info

Best regards,
NIJA Team
```

**Alert/Warning**:
```
Subject: ALERT: Daily Loss Limit Approaching

Dear [User Name],

Your account has approached the daily loss limit:
Current Loss: $[amount]
Limit: $[limit]

Trading may be automatically suspended if limit is reached.

Review your positions immediately.

NIJA Team
```

---

## Financial Tracking

### Capital Management

**For Each User**:

1. **Initial Capital**: Recorded at setup
2. **Current Balance**: Updated real-time
3. **Available Balance**: After position reserves
4. **Position Value**: Current open positions
5. **Unrealized P&L**: Open position profit/loss
6. **Realized P&L**: Closed position profit/loss
7. **Total P&L**: Combined profit/loss

### Transaction Log

**File**: `USER_TRANSACTIONS_[NAME].json`

```json
{
  "user_id": "daivon_frazier",
  "transactions": [
    {
      "date": "2026-01-08T14:30:00Z",
      "type": "deposit",
      "amount": 1000.00,
      "balance_after": 1000.00,
      "note": "Initial capital"
    },
    {
      "date": "2026-01-08T15:45:00Z",
      "type": "trade",
      "pair": "BTC-USD",
      "side": "buy",
      "size": 100.00,
      "price": 45000.00,
      "fee": 1.40,
      "balance_after": 898.60
    }
  ]
}
```

### Fee Tracking

Track all fees per user:
- Trading fees (exchange)
- Platform fees (if applicable)
- Withdrawal fees
- Total fees paid
- Fees as % of volume

### Tax Reporting

**Annual Summary** (per user):
- Total realized gains/losses
- Trade-by-trade breakdown
- Fee summary
- Holding periods
- Capital gains classification

---

## Compliance & Reporting

### Daily Checks

**Automated Daily Tasks**:
1. Verify all user statuses
2. Check for limit violations
3. Update performance metrics
4. Generate daily summaries
5. Check for required actions

**Script**: `daily_user_check.py` (to be created)
```bash
python daily_user_check.py
```

### Weekly Reviews

**Every Monday**:
1. Review all user performances
2. Check for concerning patterns
3. Update risk assessments
4. Send weekly summaries
5. Document any issues

### Monthly Reports

**First of Each Month**:
1. Generate monthly reports for all users
2. Calculate month-end balances
3. Update registry with new metrics
4. Archive previous month data
5. Send investor updates

### Audit Trail

**All Actions Logged**:
- User creation/deletion
- Permission changes
- Trading enable/disable
- Configuration updates
- Emergency actions
- Support interventions

**Log Format**:
```
[2026-01-08 20:00:00] USER_CREATE: daivon_frazier by admin
[2026-01-08 20:00:05] CREDENTIALS_STORED: daivon_frazier (Coinbase)
[2026-01-08 20:00:10] PERMISSIONS_SET: daivon_frazier (Pro tier)
[2026-01-08 20:00:15] TRADING_ENABLED: daivon_frazier by admin
```

---

## Quick Reference

### Daily Operations

```bash
# Check all users
python check_all_users.py

# Check specific user
python manage_user_daivon.py status

# View performance
python track_user_performance.py daivon_frazier

# Emergency disable
python manage_user_daivon.py disable
```

### Weekly Tasks

```bash
# Generate weekly reports
python generate_weekly_reports.py

# Review all users
python weekly_user_review.py

# Send updates
python send_user_updates.py --period=weekly
```

### Monthly Tasks

```bash
# Generate monthly reports
python generate_monthly_reports.py

# Archive data
python archive_monthly_data.py

# Send investor updates
python send_investor_updates.py --month=current
```

---

## Document Maintenance

**Updated By**: System Administrator  
**Update Frequency**: Real-time for critical changes  
**Review Schedule**: Weekly  
**Version**: 1.0  
**Created**: January 8, 2026  
**Last Updated**: January 8, 2026  

---

## Related Documentation

- `USER_INVESTOR_REGISTRY.md` - Master user list
- `MULTI_USER_SETUP_GUIDE.md` - Setup instructions
- `QUICKSTART_USER_MANAGEMENT.md` - Quick reference
- `USER_SETUP_COMPLETE_DAIVON.md` - Individual user docs
- `ARCHITECTURE.md` - System architecture
- `SECURITY.md` - Security practices
