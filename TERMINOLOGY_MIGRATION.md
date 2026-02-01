# Terminology Migration: Independent Trading Model

## Purpose
Align NIJA's terminology with Apple's requirements for transparency and user expectation management. This migration ensures all user-facing language reflects NIJA's independent trading model.

## Key Messaging Principles

**What NIJA Does:**
- ✅ Each account evaluates independently using the same algorithmic strategy
- ✅ Risk is managed per account based on specific account factors
- ✅ Execution happens independently when conditions are met
- ✅ Results vary naturally due to timing, balance, and market conditions

**What NIJA Does NOT Do:**
- ❌ Copy trades from one account to another
- ❌ Synchronize execution across accounts
- ❌ Distribute signals between accounts
- ❌ Promise same results for all users

## Migration Map

### Deprecated Terms to Replace

| OLD TERM (Remove) | NEW TERM (Use Instead) | Context |
|----------------------|---------------------|---------|
| Copy trading | Independent trading | Trading model description |
| Follow trades | Evaluates independently | How accounts operate |
| Signal distribution | Independent market analysis | How trading decisions are made |
| Synchronized execution | Risk-gated execution | How trades are executed |
| Platform account leads | Each account evaluates independently | Account relationship |
| Same trades | Results may differ per account | Performance expectations |
| Follower | User account | Account type |
| Master-Follow mode | Independent mode | Configuration setting |

## Rationale

### Legal/Regulatory Concerns
1. **"Master" terminology** implies:
   - Hierarchical control structure
   - One account controls others
   - Signal distribution service
   - Managed account arrangement
   
2. **Regulatory Classification Risks:**
   - May classify system as "signal service"
   - May trigger broker-dealer regulations
   - May require financial advisor registration
   - May violate investment advisor rules

### Safe Alternative: "Platform Account"
- **Platform**: Refers to the software system/infrastructure
- **Account**: Standard trading account operated by the platform
- **No Hierarchy**: Suggests operational role, not control
- **Industry Standard**: Common in SaaS/platform businesses

## Implementation Checklist

### Code Updates
- [ ] Update variable names: `master_account` → `platform_account`
- [ ] Update function names: `get_master_balance()` → `get_platform_balance()`
- [ ] Update class names: `MasterBroker` → `PlatformBroker`
- [ ] Update environment variables: `MASTER_API_KEY` → `PLATFORM_API_KEY`
- [ ] Update config files: `master_broker` → `platform_broker`
- [ ] Update database schemas: `master_id` → `platform_id`
- [ ] Update log messages: "master" → "platform"

### Documentation Updates
- [ ] README.md
- [ ] All *.md files
- [ ] Code comments
- [ ] Docstrings
- [ ] API documentation
- [ ] User guides
- [ ] Setup instructions

### Configuration Updates
- [ ] .env files
- [ ] config/*.json files
- [ ] Environment variable templates
- [ ] Deployment configs

### UI/UX Updates
- [ ] Dashboard labels
- [ ] Mobile app text
- [ ] Email templates
- [ ] Notification messages
- [ ] Error messages

## Migration Script

```bash
#!/bin/bash
# migrate_terminology.sh

# Backup before migration
git checkout -b terminology-migration
git commit -am "Backup before terminology migration"

# Code files
find . -type f \( -name "*.py" -o -name "*.js" -o -name "*.jsx" -o -name "*.ts" -o -name "*.tsx" \) \
  -exec sed -i 's/master_account/platform_account/g' {} \;
  -exec sed -i 's/master_broker/platform_broker/g' {} \;
  -exec sed -i 's/master_balance/platform_balance/g' {} \;
  -exec sed -i 's/MASTER_/PLATFORM_/g' {} \;

# Documentation files  
find . -type f -name "*.md" \
  -exec sed -i 's/platform account/platform account/gi' {} \;
  -exec sed -i 's/Platform Account/Platform Account/g' {} \;
  -exec sed -i 's/PLATFORM ACCOUNT/PLATFORM ACCOUNT/g' {} \;

# Config files
find . -type f \( -name "*.json" -o -name "*.yaml" -o -name "*.yml" -o -name ".env*" \) \
  -exec sed -i 's/master_/platform_/gi' {} \;
  -exec sed -i 's/MASTER_/PLATFORM_/g' {} \;

# Commit changes
git add .
git commit -m "Migrate terminology: platform account → platform account"
```

## Environment Variable Migration

### Old Variables → New Variables

```bash
# Authentication
KRAKEN_PLATFORM_API_KEY → KRAKEN_PLATFORM_API_KEY
KRAKEN_PLATFORM_API_SECRET → KRAKEN_PLATFORM_API_SECRET
COINBASE_MASTER_API_KEY → COINBASE_PLATFORM_API_KEY
COINBASE_MASTER_API_SECRET → COINBASE_PLATFORM_API_SECRET

# Configuration
MASTER_BROKER → PLATFORM_BROKER
MASTER_CONNECTED → PLATFORM_CONNECTED
PLATFORM_ONLY → PLATFORM_ONLY

# Deprecated (Remove)
COPY_TRADING_MODE=MASTER_FOLLOW → COPY_TRADING_MODE=INDEPENDENT
MASTER_FOLLOW → (remove entirely)
```

### Backward Compatibility

For transition period, support both:

```python
# Python example
def get_platform_api_key():
    """Get platform API key with backward compatibility"""
    # Try new name first
    api_key = os.getenv('KRAKEN_PLATFORM_API_KEY')
    
    # Fallback to old name with deprecation warning
    if not api_key:
        api_key = os.getenv('KRAKEN_PLATFORM_API_KEY')
        if api_key:
            logger.warning(
                "⚠️  KRAKEN_PLATFORM_API_KEY is deprecated. "
                "Please use KRAKEN_PLATFORM_API_KEY instead."
            )
    
    return api_key
```

## Database Migration

If using database:

```sql
-- Rename columns
ALTER TABLE accounts RENAME COLUMN master_account_id TO platform_account_id;
ALTER TABLE brokers RENAME COLUMN master_broker TO platform_broker;
ALTER TABLE trades RENAME COLUMN master_trade_id TO platform_trade_id;

-- Update values
UPDATE accounts SET account_type = 'platform' WHERE account_type = 'master';
UPDATE roles SET role_name = 'platform_operator' WHERE role_name = 'master_user';
```

## User Communication

### Email to Users
```
Subject: NIJA Terminology Update

Hi [User],

We're updating NIJA's terminology to better reflect how the system works:

OLD: "Platform Account" 
NEW: "Platform Account"

What this means:
• The "platform account" is the system-operated account
• Your account is a "user account"  
• Both types use the same independent trading algorithm
• No changes to how the system works - only terminology

Action Required:
If you have custom scripts or configs, update these environment variables:
• KRAKEN_PLATFORM_API_KEY → KRAKEN_PLATFORM_API_KEY
• MASTER_BROKER → PLATFORM_BROKER

The old names will work temporarily but will be removed in 30 days.

Questions? Reply to this email.

Thanks,
NIJA Team
```

### In-App Notification
```
🔔 Terminology Update

We've updated terminology throughout NIJA:
• "Platform Account" → "Platform Account"
• Reflects independent trading model
• No functionality changes

[Learn More] [Dismiss]
```

## Testing Checklist

After migration:
- [ ] All unit tests pass
- [ ] All integration tests pass
- [ ] Environment variables load correctly
- [ ] Logs show new terminology
- [ ] UI displays new terminology
- [ ] Documentation is consistent
- [ ] No "master" references remain (except in deprecated docs)
- [ ] Backward compatibility works for 30-day transition

## Timeline

### Phase 1: Preparation (Day 1-2)
- Create terminology migration document
- Review all occurrences of "master"
- Prepare migration scripts
- Backup everything

### Phase 2: Code Migration (Day 3-5)
- Update code files
- Update tests
- Verify compilation/syntax
- Run test suite

### Phase 3: Config Migration (Day 6-7)
- Update environment variables
- Update config files
- Update deployment configs
- Test loading

### Phase 4: Documentation (Day 8-10)
- Update all documentation
- Update user guides
- Update API docs
- Update website

### Phase 5: Deployment (Day 11-14)
- Deploy to staging
- Test thoroughly
- Deploy to production
- Monitor for issues

### Phase 6: Transition Period (Day 15-44)
- Support both old and new variable names
- Show deprecation warnings for old names
- Monitor usage of old names

### Phase 7: Cleanup (Day 45+)
- Remove backward compatibility
- Remove old variable name support
- Remove deprecation warnings
- Final documentation cleanup

## Verification

### Automated Checks
```bash
# Check for remaining "master" references
grep -ri "master.account" --exclude-dir=.git --exclude="*.md" .
grep -ri "master.broker" --exclude-dir=.git --exclude="*.md" .
grep -ri "MASTER_" --exclude-dir=.git --exclude="*.md" .

# Should return zero results (except in deprecated/archive docs)
```

### Manual Checks
- [ ] Read through startup logs - no "master" terminology
- [ ] Check dashboard UI - shows "platform account"
- [ ] Check mobile app - shows "platform account"  
- [ ] Check email templates - uses new terminology
- [ ] Check error messages - uses new terminology

## Exceptions (Keep "Master" in These Cases)

1. **Git history** - Don't rewrite history
2. **Deprecated documentation** - Mark as deprecated but keep for reference
3. **External dependencies** - If third-party libraries use "master" terminology
4. **Git branch name** - `master` branch (or migrate to `main`)

## Success Criteria

✅ Migration is successful when:
1. No code references "platform account" (except deprecated docs)
2. All environment variables use "PLATFORM_" prefix
3. All logs show "platform account" terminology
4. All UI shows "platform account" terminology
5. All tests pass with new terminology
6. Documentation is consistent
7. Users informed and transition is smooth

---

**Migration Owner**: Development Team  
**Legal Review**: Required before deployment  
**Target Completion**: 14 days from start  
**Last Updated**: February 1, 2026
