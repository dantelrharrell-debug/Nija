# NIJA Security Documentation

## Overview

NIJA's layered architecture implements multiple security layers to protect both users and the platform. This document outlines security best practices and the security mechanisms built into the system.

## Security Architecture

### 1. Layer Isolation

**Core Layer Protection** (Layer 1):
- ✅ Strategy logic is completely private
- ✅ Cannot be accessed by users
- ✅ Cannot be modified without admin access
- ✅ Import validation prevents unauthorized access
- ❌ No external API exposure

**Execution Layer Controls** (Layer 2):
- ✅ User permissions validated before each action
- ✅ Rate limiting prevents API abuse
- ✅ Position caps enforced
- ✅ All trades logged with user attribution
- ✅ Encrypted API key storage

**UI Layer Restrictions** (Layer 3):
- ✅ Read-only access to strategy performance
- ✅ Users can only view their own data
- ✅ Settings changes limited to allowed parameters
- ❌ No access to other users' data
- ❌ No access to core strategy logic

## API Key Security

### ❌ INSECURE (Old Way)

```python
# DO NOT DO THIS - NEVER commit API keys to code
COINBASE_API_KEY = "actual_api_key_here"
COINBASE_API_SECRET = "actual_secret_here"

# DO NOT DO THIS - sharing master keys
# User A, B, C all use the same master API key
```

**Risks**:
- Keys exposed in version control
- Keys visible in logs
- Single point of failure
- Cannot revoke individual user access
- Cannot track which user made which trade

### ✅ SECURE (New Way)

```python
from auth import get_api_key_manager

# 1. Initialize with encryption
api_manager = get_api_key_manager()

# 2. Store each user's keys encrypted
api_manager.store_user_api_key(
    user_id="user_A",
    broker="coinbase",
    api_key="user_A_specific_key",  # Encrypted automatically
    api_secret="user_A_specific_secret"
)

# 3. Retrieve when needed (decrypts on demand)
creds = api_manager.get_user_api_key("user_A", "coinbase")
```

**Benefits**:
- Keys encrypted at rest using Fernet (symmetric encryption)
- Each user has their own API keys
- Keys never stored in plain text
- Can revoke individual user access
- Full audit trail per user

### Encryption Details

NIJA uses **Fernet symmetric encryption**:
- Algorithm: AES 128 in CBC mode
- Authentication: HMAC using SHA256
- Keys: 32-byte (256-bit) encryption key
- Secure: Industry-standard encryption

**Encryption Key Management**:
```python
from cryptography.fernet import Fernet

# Generate encryption key (one time, store securely!)
encryption_key = Fernet.generate_key()
# Save this: export NIJA_ENCRYPTION_KEY=<key>

# Initialize API manager with key
api_manager = get_api_key_manager(encryption_key)
```

**⚠️ CRITICAL**: The encryption key must be:
- Generated once and stored securely
- Never committed to version control
- Stored in environment variables or secret manager
- Backed up securely (losing it means losing all encrypted keys)

## User Permission Model

### Permission Scoping

Each user has specific permissions that limit what they can do:

```python
from execution import UserPermissions

UserPermissions(
    user_id="user123",
    allowed_pairs=["BTC-USD", "ETH-USD"],  # Whitelist
    max_position_size_usd=100.0,           # Hard cap
    max_daily_loss_usd=50.0,               # Daily limit
    max_positions=3,                        # Concurrent limit
    trade_only=True,                        # Cannot modify strategy
    enabled=True                            # Trading enabled
)
```

**Validation Flow**:
1. Check if user is enabled
2. Check if pair is in allowed list
3. Check if position size is within limits
4. Check if user hasn't exceeded daily loss limit
5. Check if kill switches are active
6. Only then execute trade

### Strategy Locking

**🔒 Strategy is ALWAYS locked for users**:

```python
from controls import get_hard_controls

controls = get_hard_controls()
is_locked = controls.is_strategy_locked()  # Always True
```

**What This Means**:
- Users CANNOT modify:
  - Entry/exit logic
  - Risk calculations
  - Indicator parameters
  - Position sizing formulas
  - Stop loss/take profit algorithms

- Users CAN configure:
  - Which pairs to trade
  - Position size limits (within hard limits)
  - Risk tolerance level (low/medium/high)
  - Notification preferences

## Hard Controls (Mandatory Limits)

### Position Sizing Limits

**Enforced for ALL users** (cannot be bypassed):

```python
MIN_POSITION_PCT = 0.02   # 2% minimum per trade
MAX_POSITION_PCT = 0.10   # 10% maximum per trade
```

**Example**:
- Account balance: $1,000
- Minimum position: $20 (2%)
- Maximum position: $100 (10%)
- User requests $150: ❌ REJECTED
- User requests $50: ✅ ALLOWED

### Daily Limits

```python
MAX_DAILY_TRADES = 50     # Per user
MAX_DAILY_LOSS = configurable per user
```

**Auto-Disable Triggers**:
1. Daily loss limit exceeded
2. Daily trade count exceeded
3. Excessive API errors (5+ errors)
4. Kill switch activated

## Kill Switches

### Global Kill Switch

**Purpose**: Stop ALL trading across ALL users immediately.

**Use Cases**:
- Market emergency (flash crash, exchange outage)
- System bug detected
- Security incident
- Regulatory requirement

```python
from controls import get_hard_controls

controls = get_hard_controls()

# Trigger global kill switch
controls.trigger_global_kill_switch("Market emergency")

# All users immediately stopped
# No trades can be placed until reset

# Manual reset required (admin only)
controls.reset_global_kill_switch()
```

### Per-User Kill Switch

**Purpose**: Stop trading for specific user.

**Use Cases**:
- User exceeds loss limits
- Suspicious activity detected
- User requests account pause
- API key compromised

```python
# Trigger user kill switch
controls.trigger_user_kill_switch("user123", "Daily loss limit exceeded")

# User blocked from trading
# Other users unaffected

# Reset when issue resolved
controls.reset_user_kill_switch("user123")
```

## Error Handling & Auto-Disable

### API Error Tracking

```python
ERROR_THRESHOLD = 5  # Max errors before auto-disable
```

**Flow**:
1. API call fails
2. Error recorded for user
3. If error count >= 5:
   - User kill switch triggered automatically
   - User notified
   - Admin alerted
4. Manual intervention required to reset

**Example**:
```python
from controls import get_hard_controls

controls = get_hard_controls()

# Record API error
should_disable = controls.record_api_error("user123")

if should_disable:
    # User automatically disabled
    # Kill switch triggered
    # Admin notification sent
    pass
```

## Audit Logging

### Trade Logging

Every trade is logged with:
- User ID
- Timestamp
- Trading pair
- Position size
- Order type (buy/sell)
- Result (success/failure)
- Error message (if failed)

### Access Logging

Every permission check is logged:
- User ID attempting action
- Action type
- Permission check result
- Reason for denial (if denied)

### Security Events

Security events are logged at WARNING or CRITICAL level:
- Kill switch activations
- Permission denials
- API errors
- Auto-disable triggers
- Suspicious activity

## Best Practices

### For Administrators

1. **Encryption Key**:
   - Generate once, store securely
   - Never commit to version control
   - Back up in secure location
   - Rotate periodically

2. **User Onboarding**:
   - Start with conservative limits
   - Increase gradually based on performance
   - Require API keys with minimal permissions
   - Monitor for first 30 days

3. **Monitoring**:
   - Review logs daily
   - Monitor kill switch triggers
   - Track error rates per user
   - Alert on anomalies

4. **Incident Response**:
   - Have global kill switch procedure documented
   - Test kill switches regularly
   - Know how to reset user access
   - Maintain communication channels

### For Users

1. **API Keys**:
   - Create exchange API keys with minimal permissions
   - Trade-only permission (no withdrawals)
   - Limit to specific IPs if possible
   - Enable 2FA on exchange account

2. **Risk Management**:
   - Start with small position sizes
   - Set conservative daily loss limits
   - Monitor positions regularly
   - Understand that limits protect you

3. **Security**:
   - Never share your user credentials
   - Never share your API keys
   - Report suspicious activity immediately
   - Keep email secure (password reset vector)

## Security Checklist

### Pre-Deployment

- [ ] Encryption key generated and stored securely
- [ ] `.env` file not committed to version control
- [ ] Hard controls configured and tested
- [ ] Kill switches tested
- [ ] Logging configured
- [ ] Admin procedures documented

### User Setup

- [ ] User created with correct permissions
- [ ] API keys encrypted and stored
- [ ] Permissions validated
- [ ] Initial position limits set
- [ ] User notified of limits
- [ ] Kill switch tested for user

### Ongoing

- [ ] Monitor error rates
- [ ] Review logs weekly
- [ ] Test kill switches monthly
- [ ] Rotate encryption key annually
- [ ] Audit user permissions quarterly
- [ ] Update security procedures as needed

## Vulnerability Reporting

If you discover a security vulnerability:

1. **DO NOT** open a public GitHub issue
2. **DO** email security@nija.example.com (replace with actual)
3. Include:
   - Description of vulnerability
   - Steps to reproduce
   - Potential impact
   - Suggested fix (if any)

We will:
- Acknowledge within 24 hours
- Investigate immediately
- Patch critical issues within 48 hours
- Credit responsible disclosure

## Compliance

### Data Protection

- User API keys encrypted at rest
- No plaintext storage of credentials
- User data isolated per user
- Logs sanitized (no API keys in logs)

### Financial Regulations

- All trades logged with timestamps
- User attribution for all trades
- Ability to halt trading immediately
- Position limits enforced

### Access Control

- Role-based access control (RBAC)
- Least privilege principle
- Strategy logic access restricted
- Admin actions logged

## Security Updates

This security model will be updated as:
- New threats are identified
- Regulatory requirements change
- Best practices evolve
- User feedback is received

**Last Updated**: January 29, 2026
**Version**: 2.0
**Status**: ✅ Enhanced with God Mode CI Hardening

## God Mode CI - Advanced Security Hardening

**NEW**: NIJA now includes next-level security hardening with comprehensive artifact scanning, pre-commit hooks, and organization-wide secret policies.

### 1️⃣ Artifact Scanning

**Docker Image Scanning**:
- Trivy vulnerability scanner (CRITICAL/HIGH severity)
- Grype comprehensive security scanning
- Automated SARIF upload to GitHub Security
- Weekly scheduled scans

**Python Package Scanning**:
- pip-audit for known vulnerabilities
- GuardDog for malicious package detection
- SBOM (Software Bill of Materials) generation
- License compliance checking

**Build Artifact Validation**:
- Wheel integrity verification
- Dependency tree analysis
- License conflict detection

**Configuration**: `.github/workflows/artifact-scanning.yml`

### 2️⃣ Pre-Commit Secret Hooks

**Prevention at the Source**:
- Secrets blocked before they reach GitHub
- Multiple redundant scanners for defense in depth
- Custom NIJA-specific checks
- Automatic validation on every commit

**Installed Hooks**:
- **detect-secrets**: Baseline-driven secret detection
- **gitleaks**: Comprehensive secret scanning with custom rules
- **trufflehog**: Verified-only secret detection
- **detect-private-key**: SSH/PEM key detection
- **detect-aws-credentials**: AWS credential detection
- **Custom checks**: .env files, API keys, PEM files

**Additional Checks**:
- Code quality (trailing whitespace, EOF, YAML/JSON syntax)
- Python security (Bandit linting)
- Large file detection (>5MB)
- Merge conflict detection

**Setup**: See [.github/PRE_COMMIT_SETUP.md](.github/PRE_COMMIT_SETUP.md)

**Quick Start**:
```bash
pip install pre-commit
pre-commit install
pre-commit run --all-files
```

### 3️⃣ Organization-Wide Secret Policy

**Centralized Enforcement**:
- Consistent rules across all NIJA projects
- Custom patterns for trading APIs (Coinbase, Kraken, Alpaca)
- Allowlisted templates and documentation
- Multi-layer defense (pre-commit + CI + GitHub native)

**Configuration Files**:
- `.gitleaks.toml`: Organization-wide gitleaks rules
- `.secrets.baseline`: Known false positives
- `.bandit.yml`: Python security linting rules
- `.pre-commit-config.yaml`: Pre-commit hook configuration

**Policy Documentation**: [.github/SECRET_SCANNING_POLICY.md](.github/SECRET_SCANNING_POLICY.md)

**Enforcement Layers**:
1. Developer machine (pre-commit hooks)
2. CI/CD pipeline (GitHub Actions)
3. GitHub native secret scanning
4. Artifact and build scanning

### Security Scanning Matrix

| Scanner | Layer | Frequency | Coverage |
|---------|-------|-----------|----------|
| detect-secrets | Pre-commit + CI | Every commit | Baseline-driven |
| gitleaks | Pre-commit + CI | Every commit + Weekly | Comprehensive |
| trufflehog | Pre-commit + CI | Every commit + Weekly | Verified only |
| GitHub Secret Scanning | Native | Continuous | Partner patterns |
| Trivy | CI | On build + Weekly | Docker images |
| Grype | CI | On build | Docker images |
| pip-audit | CI | Every build | Python packages |
| GuardDog | CI | Every build | Malicious packages |
| Bandit | Pre-commit + CI | Every commit | Python security |

### Incident Response

**If Secret Detected**:
1. ❌ Commit blocked by pre-commit hook
2. 🔧 Remove secret from code
3. 🔄 Rotate credential immediately
4. ✅ Verify not in git history
5. 📝 Document incident

**If Secret Reaches GitHub**:
1. 🚨 IMMEDIATE: Revoke credential (within 1 hour)
2. 🔍 Audit for unauthorized access
3. 🧹 Remove from git history (BFG Repo-Cleaner)
4. 📢 Notify security team
5. 📊 Postmortem and prevention

**Tools**:
- [BFG Repo-Cleaner](https://rtyley.github.io/bfg-repo-cleaner/)
- [GitHub: Removing Sensitive Data](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository)

### Developer Requirements

**All developers must**:
1. Install pre-commit hooks: `pre-commit install`
2. Read security documentation
3. Never commit real credentials
4. Use .env.example templates only
5. Report security concerns immediately

### Compliance Checklist

**Repository Security**:
- [x] Pre-commit hooks configured
- [x] Gitleaks organization config
- [x] Secrets baseline maintained
- [x] .gitignore excludes credentials
- [x] CI security scans enabled
- [x] Artifact scanning enabled
- [x] Docker image scanning enabled
- [x] Python package scanning enabled
- [x] License compliance checking
- [x] SBOM generation
- [x] Organization-wide policy documented

**Ongoing**:
- [x] Daily: CI scans on commits/PRs
- [x] Weekly: Scheduled full scans
- [ ] Monthly: Configuration review
- [ ] Quarterly: Policy updates
- [ ] Annually: Complete security audit

---

**Remember**: Multiple layers of defense ensure secrets never reach production. Each layer is independent and redundant.

---

**Remember**: Security is not a one-time setup, it's an ongoing process. Regular monitoring, testing, and updates are essential.
