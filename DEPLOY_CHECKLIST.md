# 🚀 NIJA Deploy Checklist - Infrastructure & Monitoring

**Last Updated:** February 4, 2026  
**Version:** 2.0 (Comprehensive)  
**Purpose:** Production deployment validation with infrastructure and monitoring focus

---

## 📋 Overview

This checklist ensures safe, reliable deployment of NIJA to production with comprehensive infrastructure setup and monitoring.

**Use this checklist for:**
- ✅ Initial production deployments
- ✅ Major version upgrades
- ✅ Infrastructure changes
- ✅ Platform migrations
- ✅ Disaster recovery setup

---

## 🔐 Pre-Deployment: Security & Credentials

### ✅ Environment Variables & Secrets

**Critical secrets that MUST be set:**

```bash
# Generate encryption keys (run these commands)
python3 -c "from cryptography.fernet import Fernet; print(f'VAULT_ENCRYPTION_KEY={Fernet.generate_key().decode()}')"
python3 -c "import secrets; print(f'JWT_SECRET_KEY={secrets.token_hex(32)}')"
```

**Required environment variables:**

- [ ] `VAULT_ENCRYPTION_KEY` - Vault encryption (generated above)
- [ ] `JWT_SECRET_KEY` - JWT signing (generated above)
- [ ] `DATABASE_URL` - Database connection string
- [ ] `PORT` - Application port (default: 8000)
- [ ] `ENVIRONMENT` - Set to "production"
- [ ] `LOG_LEVEL` - Set to "INFO" (or "WARNING" for quieter logs)

**Exchange API credentials (per user, stored encrypted):**
- [ ] Coinbase API keys (if using)
- [ ] Kraken API keys (if using)
- [ ] Other exchange credentials (as needed)

**⚠️ CRITICAL WARNINGS:**
- ❌ **NEVER** commit secrets to git
- ❌ **NEVER** expose secrets in logs
- ❌ **NEVER** share encryption keys
- ✅ Store secrets in environment variables or secrets manager
- ✅ Backup encryption keys securely (encrypted password manager or vault)
- ✅ Rotate keys periodically (every 90 days recommended)

### ✅ Security Validation

- [ ] API keys have **trading-only permissions** (no withdrawal rights)
- [ ] TLS/HTTPS enabled (production only)
- [ ] CORS configured for production domains only
- [ ] Rate limiting enabled on authentication endpoints
- [ ] Firewall rules configured (if applicable)
- [ ] `.gitignore` excludes: `.env`, `*.db`, `*.pem`, `__pycache__/`, `vault.db`, `users.db`
- [ ] Pre-commit hooks active (if using)
- [ ] Secrets scanning enabled (gitleaks, detect-secrets)

**Security scan commands:**
```bash
# Run security scanner
python3 -m bandit -r bot/ -ll

# Check for secrets in code
detect-secrets scan --baseline .secrets.baseline

# Validate .gitignore effectiveness
git status --ignored
```

---

## 🗄️ Database Setup & Validation

### ✅ Database Configuration

**For Production (PostgreSQL recommended):**
```bash
export DATABASE_URL="postgresql://user:password@host:5432/nija_production"
```

**For Development/Testing (SQLite acceptable):**
```bash
export DATABASE_URL="sqlite:///nija.db"
```

### ✅ Database Initialization

- [ ] Database created
- [ ] Connection string validated
- [ ] Database migrations applied (if using Alembic)
- [ ] Initial tables created: `vault`, `users`, `audit_log`, `login_history`
- [ ] Indexes created for performance
- [ ] Database user has appropriate permissions (not root)

**Initialization commands:**
```bash
# Initialize database
python3 init_database.py

# Verify tables exist
sqlite3 nija.db ".tables"  # For SQLite
# OR
psql $DATABASE_URL -c "\dt"  # For PostgreSQL
```

### ✅ Database Backups

- [ ] Backup schedule configured (daily minimum)
- [ ] Backup retention policy set (30 days minimum)
- [ ] Backup restoration tested
- [ ] Point-in-time recovery configured (if using PostgreSQL)
- [ ] Backup encryption enabled
- [ ] Off-site backup storage configured

**Backup commands:**
```bash
# SQLite backup
cp vault.db vault.db.backup.$(date +%Y%m%d-%H%M%S)
cp users.db users.db.backup.$(date +%Y%m%d-%H%M%S)

# PostgreSQL backup
pg_dump $DATABASE_URL > nija_backup_$(date +%Y%m%d-%H%M%S).sql
```

---

## 🧪 Pre-Deployment Testing

### ✅ Component Tests

**Run comprehensive test suite:**
```bash
# MVP components test
python3 test_mvp_components.py

# Expected output:
# ✅ Tests Passed: 4/4 (100.0%)
# ❌ Tests Failed: 0
```

### ✅ Integration Tests

- [ ] Vault encryption/decryption working
- [ ] User authentication working (register, login, JWT)
- [ ] Execution router broker selection working
- [ ] API endpoints responding correctly
- [ ] Health check endpoint returning 200

**Integration test commands:**
```bash
# Test vault functionality
python3 -c "from vault.secure_api_vault import SecureAPIVault; v = SecureAPIVault(); print('✅ Vault OK')"

# Test authentication
python3 test_authentication.py  # If test file exists

# Test API health
curl http://localhost:8000/health
# Expected: {"status": "healthy", ...}
```

### ✅ Security Tests

- [ ] SQL injection tests passed
- [ ] XSS vulnerability tests passed
- [ ] Path traversal tests passed
- [ ] API rate limiting validated
- [ ] Authentication bypass tests passed

**Security testing:**
```bash
# Run security-specific tests
python3 test_security_fixes.py

# CodeQL scan (if available)
codeql database analyze
```

---

## 🏗️ Infrastructure Setup

### ✅ Platform Configuration

**Choose deployment platform and configure:**

#### **Option 1: Railway**
- [ ] Railway project created
- [ ] Environment variables set in Railway dashboard
- [ ] `railway.json` configuration validated
- [ ] Start command configured: `bash start.sh`
- [ ] Port configuration: `PORT=5000` (or Railway-assigned)
- [ ] Database plugin added (PostgreSQL recommended)
- [ ] Deployment region selected
- [ ] Auto-deploy from git configured (optional)

**Railway deployment:**
```bash
# Install Railway CLI
npm install -g @railway/cli

# Login
railway login

# Link to project
railway link

# Set environment variables
railway variables set VAULT_ENCRYPTION_KEY=<key>
railway variables set JWT_SECRET_KEY=<key>

# Deploy
railway up
```

#### **Option 2: Docker**
- [ ] Dockerfile validated
- [ ] Docker image builds successfully
- [ ] Container starts without errors
- [ ] Environment variables mounted correctly
- [ ] Volume mounts configured (for database persistence)
- [ ] Health check configured in Dockerfile
- [ ] Resource limits set (CPU, memory)

**Docker deployment:**
```bash
# Build image
docker build -t nija-production:latest .

# Run with environment variables
docker run -d \
  --name nija-app \
  -p 8000:8000 \
  -e VAULT_ENCRYPTION_KEY=$VAULT_ENCRYPTION_KEY \
  -e JWT_SECRET_KEY=$JWT_SECRET_KEY \
  -e DATABASE_URL=$DATABASE_URL \
  -v $(pwd)/data:/app/data \
  --restart unless-stopped \
  nija-production:latest

# Verify container running
docker ps | grep nija-app
```

#### **Option 3: Kubernetes**
- [ ] Kubernetes cluster available
- [ ] Namespace created: `nija-production`
- [ ] ConfigMaps created for non-secret config
- [ ] Secrets created for sensitive data
- [ ] Deployment manifest configured
- [ ] Service manifest configured (LoadBalancer or ClusterIP)
- [ ] Ingress configured (if using)
- [ ] Persistent Volume Claims created (for database)
- [ ] Resource quotas set
- [ ] Pod Security Policy configured

**Kubernetes deployment:**
```bash
# Create namespace
kubectl create namespace nija-production

# Create secrets
kubectl create secret generic nija-secrets \
  --from-literal=VAULT_ENCRYPTION_KEY=$VAULT_ENCRYPTION_KEY \
  --from-literal=JWT_SECRET_KEY=$JWT_SECRET_KEY \
  -n nija-production

# Apply manifests
kubectl apply -f k8s/deployment.yaml -n nija-production
kubectl apply -f k8s/service.yaml -n nija-production

# Verify deployment
kubectl get pods -n nija-production
```

#### **Option 4: Traditional Server (VPS/Cloud VM)**
- [ ] Server provisioned (Ubuntu 22.04 LTS recommended)
- [ ] Python 3.11 installed
- [ ] Dependencies installed from `requirements.txt`
- [ ] Systemd service configured
- [ ] Nginx/Apache reverse proxy configured
- [ ] SSL certificate installed (Let's Encrypt)
- [ ] Firewall configured (UFW or iptables)
- [ ] Auto-restart on failure configured

**Traditional server setup:**
```bash
# Install dependencies
sudo apt update
sudo apt install -y python3.11 python3-pip nginx certbot

# Install Python packages
pip3 install -r requirements.txt

# Create systemd service
sudo nano /etc/systemd/system/nija.service
```

**Systemd service file example:**
```ini
[Unit]
Description=NIJA Trading Platform
After=network.target

[Service]
User=nija
WorkingDirectory=/opt/nija
Environment="VAULT_ENCRYPTION_KEY=<your-key>"
Environment="JWT_SECRET_KEY=<your-key>"
Environment="DATABASE_URL=postgresql://..."
ExecStart=/usr/bin/gunicorn fastapi_backend:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
# Enable and start service
sudo systemctl enable nija
sudo systemctl start nija
sudo systemctl status nija
```

### ✅ Network & DNS

- [ ] Domain name configured (if applicable)
- [ ] DNS records pointing to production server/load balancer
- [ ] SSL/TLS certificate installed and valid
- [ ] HTTPS redirect configured (HTTP → HTTPS)
- [ ] CDN configured (if using, e.g., CloudFlare)
- [ ] DDoS protection enabled (if applicable)

---

## 📊 Monitoring & Observability

### ✅ Application Monitoring

**Health check endpoint:**
- [ ] `/health` endpoint returns 200 OK
- [ ] Health check includes: timestamp, service name, version, status
- [ ] Health check monitored every 1-5 minutes

**Test health endpoint:**
```bash
curl https://your-domain.com/health
# Expected: {"status": "healthy", "timestamp": "...", "service": "NIJA FastAPI Backend", "version": "2.0.0"}
```

### ✅ Logging Configuration

**Log levels and destinations:**
- [ ] Application logs configured (INFO level for production)
- [ ] Error logs captured (ERROR and CRITICAL)
- [ ] Access logs enabled (HTTP requests)
- [ ] Audit logs enabled (security events, user actions)
- [ ] Log rotation configured (daily or by size)
- [ ] Log retention policy set (30-90 days)
- [ ] Centralized logging configured (optional: ELK, Datadog, CloudWatch)

**Log locations:**
```bash
# Application logs
/var/log/nija/application.log

# Error logs
/var/log/nija/error.log

# Audit logs (vault operations)
SELECT * FROM audit_log ORDER BY timestamp DESC LIMIT 100;

# Login history
SELECT * FROM login_history WHERE timestamp > datetime('now', '-1 day');
```

**Configure log rotation (logrotate):**
```bash
sudo nano /etc/logrotate.d/nija
```

**Logrotate config:**
```
/var/log/nija/*.log {
    daily
    rotate 30
    compress
    delaycompress
    notifempty
    create 0640 nija nija
    sharedscripts
    postrotate
        systemctl reload nija
    endscript
}
```

### ✅ Performance Monitoring

**Key metrics to track:**
- [ ] Response time (API endpoints)
  - Target: < 200ms for health check
  - Target: < 500ms for authentication
  - Target: < 1s for trading operations
- [ ] Request rate (requests/second)
- [ ] Error rate (errors/requests)
- [ ] CPU usage (should be < 70% average)
- [ ] Memory usage (should be < 80% of available)
- [ ] Database connections (active, idle)
- [ ] Disk usage (should have 20%+ free)

**Monitoring tools (choose one or more):**
- [ ] Prometheus + Grafana (open source)
- [ ] Datadog (SaaS)
- [ ] New Relic (SaaS)
- [ ] AWS CloudWatch (if on AWS)
- [ ] Railway metrics (if using Railway)

### ✅ Trading-Specific Monitoring

**Critical trading metrics:**
- [ ] Active positions count
- [ ] Daily P&L tracking
- [ ] Order success/failure rate
- [ ] Exchange API latency
- [ ] Exchange API error rate
- [ ] Stop-loss execution rate
- [ ] Daily loss limit triggers

**Custom monitoring script:**
```python
# Example: Monitor vault operations
from vault.secure_api_vault import SecureAPIVault

vault = SecureAPIVault()
recent_operations = vault.get_audit_log(limit=100)
failed_ops = [op for op in recent_operations if op['status'] == 'failed']

if len(failed_ops) > 10:
    alert("High vault failure rate detected!")
```

### ✅ Alerting Configuration

**Set up alerts for:**

**Critical (immediate response required):**
- [ ] Service down (health check fails)
- [ ] Database connection lost
- [ ] Disk space < 10%
- [ ] Memory usage > 90%
- [ ] Error rate spike (> 10%)
- [ ] Authentication failures spike
- [ ] Exchange API errors

**Warning (investigate within hours):**
- [ ] Response time > 2s
- [ ] CPU usage > 80%
- [ ] Database query slow (> 5s)
- [ ] Daily loss limit approaching
- [ ] High vault failure rate

**Info (review daily):**
- [ ] New user registrations
- [ ] Unusual trading patterns
- [ ] Backup failures
- [ ] Certificate expiration (30 days warning)

**Alert channels:**
- [ ] Email alerts configured
- [ ] SMS alerts for critical issues (optional)
- [ ] Slack/Discord webhook (optional)
- [ ] PagerDuty integration (optional)

**Example alert configuration (Prometheus Alertmanager):**
```yaml
groups:
  - name: nija_alerts
    rules:
      - alert: ServiceDown
        expr: up{job="nija"} == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "NIJA service is down"
          
      - alert: HighErrorRate
        expr: rate(http_requests_total{status=~"5.."}[5m]) > 0.1
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High error rate detected"
```

### ✅ Uptime Monitoring

**External uptime monitoring:**
- [ ] UptimeRobot configured (or similar service)
- [ ] Monitoring frequency: 1-5 minutes
- [ ] Multiple geographic locations monitored
- [ ] Status page created (optional: status.nija.app)

**Configure UptimeRobot (or similar):**
- Service: NIJA Production
- URL: https://your-domain.com/health
- Check interval: 5 minutes
- Alert contacts: your-email@domain.com

---

## 🧯 Disaster Recovery & Backup

### ✅ Backup Strategy

**What to backup:**
- [ ] Database (vault.db, users.db, or PostgreSQL)
- [ ] Encryption keys (securely stored separately)
- [ ] Configuration files (.env, secrets)
- [ ] Application code (git repository)
- [ ] User data (trading history, if stored)

**Backup frequency:**
- [ ] Database: Daily (automated)
- [ ] Encryption keys: After any change (manual + secure storage)
- [ ] Configuration: After any change (version controlled)
- [ ] Code: Every commit (git)

**Backup retention:**
- [ ] Daily backups: 7 days
- [ ] Weekly backups: 4 weeks
- [ ] Monthly backups: 12 months
- [ ] Critical backups (keys): Indefinite

**Backup locations:**
- [ ] On-site backup (same datacenter, different server)
- [ ] Off-site backup (different datacenter or cloud region)
- [ ] Cloud storage (S3, Google Cloud Storage, etc.)
- [ ] Encrypted backup (all backups encrypted at rest)

**Backup verification:**
```bash
# Test database restore
# 1. Create test backup
cp vault.db vault.db.test.backup

# 2. Restore to test environment
cp vault.db.test.backup vault_test.db

# 3. Verify data integrity
python3 -c "from vault.secure_api_vault import SecureAPIVault; v = SecureAPIVault('vault_test.db'); print('✅ Restore successful' if v.get_audit_log() else '❌ Restore failed')"
```

### ✅ Recovery Procedures

**Document recovery steps:**
- [ ] Database restoration procedure documented
- [ ] Service restart procedure documented
- [ ] Rollback procedure documented (code version)
- [ ] Emergency contacts listed
- [ ] Recovery time objective (RTO) defined: Target < 4 hours
- [ ] Recovery point objective (RPO) defined: Target < 24 hours

**Recovery procedure example:**
```bash
# 1. Stop service
systemctl stop nija

# 2. Restore database
cp /backups/vault.db.backup.20260204 vault.db
cp /backups/users.db.backup.20260204 users.db

# 3. Verify encryption key
export VAULT_ENCRYPTION_KEY=<from-secure-storage>

# 4. Test database
python3 test_mvp_components.py

# 5. Restart service
systemctl start nija

# 6. Verify health
curl http://localhost:8000/health
```

---

## 🚀 Deployment Execution

### ✅ Deployment Steps

**1. Final pre-deployment checks:**
- [ ] All tests passing (100%)
- [ ] Security scans passed
- [ ] Code review completed
- [ ] Database backup created
- [ ] Rollback plan prepared

**2. Deploy application:**

```bash
# Pull latest code
git pull origin main

# Install/update dependencies
pip install -r requirements.txt

# Run database migrations (if any)
# alembic upgrade head

# Restart service
systemctl restart nija  # Systemd
# OR
railway up  # Railway
# OR
kubectl rollout restart deployment/nija -n nija-production  # Kubernetes
# OR
docker restart nija-app  # Docker
```

**3. Post-deployment verification:**
- [ ] Health check returns 200 OK
- [ ] Test user registration works
- [ ] Test user login works
- [ ] Test API endpoints respond correctly
- [ ] Database connections established
- [ ] Logs show no errors

**Post-deployment test commands:**
```bash
# 1. Health check
curl https://your-domain.com/health

# 2. Test registration
curl -X POST https://your-domain.com/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"test@example.com","password":"TestPass123!","subscription_tier":"basic"}'

# 3. Test login
curl -X POST https://your-domain.com/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"test@example.com","password":"TestPass123!"}'

# 4. Check logs for errors
tail -f /var/log/nija/error.log
# OR
railway logs  # Railway
# OR
kubectl logs -f deployment/nija -n nija-production  # Kubernetes
```

### ✅ Smoke Testing

**Run basic smoke tests:**
- [ ] Homepage loads
- [ ] Login page loads
- [ ] API responds to authenticated requests
- [ ] Trading control toggle works (if UI available)
- [ ] No JavaScript errors in console

### ✅ Production Traffic Cutover

**If migrating from existing deployment:**
- [ ] DNS TTL reduced to 5 minutes (24 hours before cutover)
- [ ] New deployment fully tested
- [ ] Load balancer configured (if using)
- [ ] Traffic gradually shifted (0% → 10% → 50% → 100%)
- [ ] Monitoring active during cutover
- [ ] Rollback plan ready

**Canary deployment (recommended):**
```bash
# Kubernetes example
kubectl set image deployment/nija nija=nija:v2.0.0 -n nija-production
kubectl rollout pause deployment/nija -n nija-production  # Pause at 10%
# Monitor metrics for 15 minutes
kubectl rollout resume deployment/nija -n nija-production  # Continue rollout
```

---

## 📋 Post-Deployment Monitoring

### ✅ First 24 Hours

**Monitor closely:**
- [ ] Health check every 5 minutes (automated)
- [ ] Error logs reviewed every 1 hour (manual)
- [ ] Performance metrics reviewed every 2 hours
- [ ] User feedback monitored (support email, app reviews)
- [ ] Database performance checked
- [ ] Backup completed successfully

**Metrics to watch:**
- Response time (should be stable)
- Error rate (should be < 1%)
- CPU/Memory usage (should be normal)
- Active users (should match expected)
- Trade execution success rate (should be > 95%)

### ✅ First Week

**Weekly review:**
- [ ] No critical alerts triggered
- [ ] All backups completed successfully
- [ ] Log analysis for patterns
- [ ] Performance trends reviewed
- [ ] User feedback addressed
- [ ] Resource usage trending (CPU, memory, disk)

### ✅ Ongoing Maintenance

**Monthly tasks:**
- [ ] Security updates applied (OS, dependencies)
- [ ] SSL certificate expiration checked (auto-renew verified)
- [ ] Backup restoration test performed
- [ ] Log retention cleanup (old logs archived or deleted)
- [ ] Performance optimization review
- [ ] Cost analysis (if on cloud platform)

**Quarterly tasks:**
- [ ] Security audit performed
- [ ] Disaster recovery plan tested (full system restore)
- [ ] Capacity planning review (scaling needs)
- [ ] Dependency updates reviewed (major versions)

---

## 🎯 Success Criteria

**Deployment is successful when:**

- ✅ Health check returns 200 OK
- ✅ All tests passing (100%)
- ✅ No critical errors in logs
- ✅ Response time < 500ms (average)
- ✅ Error rate < 1%
- ✅ Uptime > 99.9%
- ✅ Monitoring and alerts active
- ✅ Backups configured and tested
- ✅ Security validated (no vulnerabilities)
- ✅ Users can register, login, and trade

---

## 🚨 Rollback Procedure

**If deployment fails:**

1. **Immediate rollback:**
```bash
# Systemd
git checkout <previous-commit>
systemctl restart nija

# Railway
railway rollback

# Kubernetes
kubectl rollout undo deployment/nija -n nija-production

# Docker
docker stop nija-app
docker run -d --name nija-app nija-production:previous-version
```

2. **Restore database (if needed):**
```bash
systemctl stop nija
cp /backups/vault.db.backup.<timestamp> vault.db
cp /backups/users.db.backup.<timestamp> users.db
systemctl start nija
```

3. **Verify rollback:**
```bash
curl http://localhost:8000/health
python3 test_mvp_components.py
```

4. **Post-rollback:**
- [ ] Incident report created
- [ ] Root cause analysis performed
- [ ] Fix implemented
- [ ] Re-test in staging
- [ ] Schedule new deployment

---

## 📞 Emergency Contacts

**Deployment team:**
- Primary contact: [name] - [email] - [phone]
- Secondary contact: [name] - [email] - [phone]
- Database admin: [name] - [email] - [phone]

**External vendors:**
- Cloud provider support: [contact info]
- DNS provider support: [contact info]
- SSL certificate provider: [contact info]

**Escalation:**
- Business hours: [contact primary]
- After hours: [contact on-call]
- Critical outage: [contact all]

---

## ✅ Final Checklist Summary

**Before going live, verify:**

- [ ] ✅ All secrets and environment variables configured
- [ ] ✅ Database initialized and backed up
- [ ] ✅ All tests passing (100%)
- [ ] ✅ Security validated (no critical vulnerabilities)
- [ ] ✅ Infrastructure configured (platform, network, DNS)
- [ ] ✅ Monitoring and alerting active
- [ ] ✅ Logging configured and working
- [ ] ✅ Backup and recovery tested
- [ ] ✅ Health check endpoint responding
- [ ] ✅ Post-deployment tests passed
- [ ] ✅ Rollback procedure documented and ready
- [ ] ✅ Team notified of deployment

**Production is ready when ALL checkboxes are checked.**

---

## 📚 Related Documentation

- **[DEPLOYMENT_CHECKLIST.md](DEPLOYMENT_CHECKLIST.md)** - Original deployment checklist (MVP focus)
- **[DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md)** - Detailed deployment instructions
- **[MONITORING_GUIDE_V4_RELAXATION.md](MONITORING_GUIDE_V4_RELAXATION.md)** - Monitoring guidelines
- **[SECURITY.md](SECURITY.md)** - Security architecture and best practices
- **[PRODUCTION_DEPLOYMENT.md](PRODUCTION_DEPLOYMENT.md)** - Production-specific guidance
- **[NIJA_SAFETY_GUARANTEES.md](NIJA_SAFETY_GUARANTEES.md)** - User safety documentation

---

**Document Version:** 2.0  
**Last Updated:** February 4, 2026  
**Maintainer:** NIJA DevOps Team

---

**Questions or Issues?**  
📧 Email: devops@nija.app  
📖 Docs: See related documentation above  
🐛 Issues: Report to development team
