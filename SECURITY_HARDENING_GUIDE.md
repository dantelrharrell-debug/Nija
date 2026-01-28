# Security Hardening Guide

## Overview

This document outlines the security hardening measures implemented in NIJA to protect the trading bot, user data, and API credentials.

## Automated Security Scanning

### CodeQL Analysis

NIJA uses GitHub's CodeQL to perform automated security scanning of the codebase.

**Workflow**: `.github/workflows/codeql.yml`

**Features:**
- ✅ Scans Python and JavaScript code
- ✅ Runs on every push to main/develop branches
- ✅ Runs on all pull requests
- ✅ Weekly scheduled scans (Mondays at 6am UTC)
- ✅ Detects security vulnerabilities, coding errors, and code smells

**View Results:**
- Navigate to: `Security > Code scanning alerts` in GitHub
- Review and address any high/critical severity findings

### Dependency Vulnerability Scanning

**Workflow**: `.github/workflows/security-scan.yml`

**Tools Used:**
1. **Safety** - Python dependency vulnerability scanner
2. **Bandit** - Python security linting
3. **TruffleHog** - Secret scanning in git history

**Scanning Schedule:**
- On every push to main/develop
- On all pull requests
- Weekly scheduled scans (Sundays at 2am UTC)

## Security Best Practices Checklist

### ✅ API Key Security

- [x] Never commit API keys to version control
- [x] Use environment variables for all secrets
- [x] Store secrets in `.env` file (gitignored)
- [x] Rotate API keys regularly (recommended: every 90 days)
- [x] Use separate API keys for development and production
- [x] Implement encryption for stored credentials (Fernet encryption)

**Required Environment Variables:**
```bash
COINBASE_API_KEY=your_key_here
COINBASE_API_SECRET=your_secret_here
COINBASE_PEM_CONTENT=your_pem_content_here
```

### ✅ Input Validation

- [x] Validate all webhook inputs
- [x] Sanitize user inputs before processing
- [x] Use Pydantic models for API request validation
- [x] Implement rate limiting on webhook endpoints

**Example:**
```python
from pydantic import BaseModel, validator

class WebhookSignal(BaseModel):
    symbol: str
    action: str
    price: float
    
    @validator('action')
    def validate_action(cls, v):
        if v not in ['buy', 'sell']:
            raise ValueError('Invalid action')
        return v
```

### ✅ Network Security

- [x] Use HTTPS for all external API calls
- [x] Implement TLS/SSL for webhook servers
- [x] Validate webhook signatures
- [x] Use CORS restrictions for API endpoints
- [x] Implement JWT authentication for API gateway

### ✅ Error Handling

- [x] Never expose sensitive data in error messages
- [x] Log errors securely without exposing credentials
- [x] Implement proper exception handling for API calls
- [x] Use structured logging (JSON format)

**Example:**
```python
import logging

logger = logging.getLogger(__name__)

try:
    response = api_call()
except Exception as e:
    # DON'T: logger.error(f"API failed: {api_key}")
    # DO: logger.error(f"API call failed: {type(e).__name__}")
```

### ✅ Access Control

- [x] Implement user authentication for all API endpoints
- [x] Use role-based access control (RBAC)
- [x] Separate admin and user permissions
- [x] Implement session management with timeouts
- [x] Log all authentication attempts

### ✅ Code Security

- [x] Run Bandit security linting on all Python code
- [x] Fix all high/critical security findings
- [x] Use parameterized queries (avoid SQL injection)
- [x] Validate file paths to prevent directory traversal
- [x] Implement CSP headers for web interfaces

### ✅ Trading Security

- [x] Implement position size limits
- [x] Add maximum daily loss circuit breakers
- [x] Validate all trade parameters before execution
- [x] Implement emergency stop mechanism
- [x] Log all trade executions with full audit trail
- [x] Rate limit API calls to prevent account lockouts

**Example:**
```python
from bot.risk_manager import RiskManager

risk_manager = RiskManager(
    max_position_size_pct=5.0,
    max_daily_loss_pct=5.0,
    max_drawdown_pct=12.0
)

# Validate trade before execution
if not risk_manager.validate_trade(size, price):
    logger.warning("Trade rejected by risk manager")
    return
```

## Security Monitoring

### Real-Time Alerts

Configure alerts for:
- Failed authentication attempts
- Unusual API activity
- Large withdrawals or transfers
- Circuit breaker triggers
- Error rate spikes

### Security Logs

Monitor these log files:
- `logs/security.log` - Authentication and authorization events
- `logs/api.log` - API call history
- `logs/trades.log` - Trade execution audit trail
- `logs/errors.log` - Application errors

**Log Retention:**
- Keep logs for minimum 90 days
- Archive important logs for compliance
- Implement log rotation to prevent disk fill

## Incident Response

### Security Incident Steps

1. **Immediate Actions:**
   - Stop the trading bot: `./stop_bot.sh`
   - Disable API keys in broker account
   - Assess the scope of the incident

2. **Investigation:**
   - Review security logs
   - Check recent trade history
   - Identify compromised credentials
   - Document timeline of events

3. **Remediation:**
   - Rotate all API keys and secrets
   - Update `.env` file with new credentials
   - Patch identified vulnerabilities
   - Review and update security policies

4. **Recovery:**
   - Test bot with new credentials
   - Restart trading in paper mode first
   - Monitor closely for 24-48 hours
   - Document lessons learned

### Emergency Contacts

- **Security Issues:** Create issue in GitHub with `security` label
- **Trading Issues:** Check `RECOVERY_GUIDE.md`
- **API Issues:** Refer to broker support documentation

## Security Updates

### Dependency Updates

**Monthly Security Updates:**
```bash
# Check for outdated packages
pip list --outdated

# Update specific vulnerable packages
pip install --upgrade package-name

# Update requirements.txt
pip freeze > requirements.txt
```

### Security Patch Process

1. Monitor GitHub Security Advisories
2. Review Dependabot alerts weekly
3. Test patches in development environment
4. Deploy to production with monitoring

## Compliance Considerations

### Data Protection

- **Encryption at rest:** User credentials encrypted with Fernet
- **Encryption in transit:** HTTPS for all API calls
- **Data minimization:** Only store necessary trading data
- **Right to deletion:** Provide mechanism to delete user data

### Audit Trail

- All trades logged with timestamp and user ID
- API key usage tracked
- Authentication events recorded
- Position changes documented

### Regulatory Compliance

- Comply with broker terms of service
- Follow financial regulation requirements
- Maintain records as required by law
- Implement KYC/AML as needed

## Security Review Schedule

- **Daily:** Review security scan results
- **Weekly:** Check Dependabot alerts
- **Monthly:** Update dependencies
- **Quarterly:** Rotate API keys
- **Annually:** Full security audit

## Additional Resources

- [OWASP Top 10](https://owasp.org/www-project-top-ten/)
- [Python Security Best Practices](https://python.readthedocs.io/en/stable/library/security_warnings.html)
- [GitHub Security Best Practices](https://docs.github.com/en/code-security)
- [Coinbase API Security](https://docs.cloud.coinbase.com/advanced-trade-api/docs/auth)

## Questions or Issues?

If you discover a security vulnerability:
1. **DO NOT** open a public issue
2. Email security contact privately
3. Provide detailed information
4. Allow time for patch before disclosure

For general security questions, refer to [SECURITY.md](SECURITY.md).
