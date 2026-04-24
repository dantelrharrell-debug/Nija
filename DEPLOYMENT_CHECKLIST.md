# NIJA MVP Deployment Checklist

## Pre-Deployment

### 1. Environment Variables (CRITICAL)

```bash
# Generate unique encryption key
python3 -c "from cryptography.fernet import Fernet; print(f'VAULT_ENCRYPTION_KEY={Fernet.generate_key().decode()}')"

# Generate unique JWT secret
python3 -c "import secrets; print(f'JWT_SECRET_KEY={secrets.token_hex(32)}')"
```

**Set these in your environment:**
```bash
export VAULT_ENCRYPTION_KEY="your-generated-key-here"
export JWT_SECRET_KEY="your-jwt-secret-here"
export DATABASE_URL="sqlite:///nija.db"  # Or PostgreSQL URL
export PORT="8000"
```

⚠️ **WARNING**: Never commit these keys to git!

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Run Tests

```bash
python3 test_mvp_components.py
```

Expected output:
```
✅ Tests Passed: 4/4 (100.0%)
❌ Tests Failed: 0
```

---

## Deployment Options

### Option 1: Local Development

```bash
# Start FastAPI backend
uvicorn fastapi_backend:app --reload --host 0.0.0.0 --port 8000
```

Access at: http://localhost:8000

### Option 2: Production (Gunicorn)

```bash
# Start with Gunicorn + Uvicorn workers
gunicorn fastapi_backend:app \
  -w 4 \
  -k uvicorn.workers.UvicornWorker \
  --bind 0.0.0.0:8000 \
  --access-logfile - \
  --error-logfile -
```

### Option 3: Docker

```bash
# Build image
docker build -t nija-mvp .

# Run container
docker run -d \
  -p 8000:8000 \
  -e VAULT_ENCRYPTION_KEY=$VAULT_ENCRYPTION_KEY \
  -e JWT_SECRET_KEY=$JWT_SECRET_KEY \
  nija-mvp
```

### Option 4: Railway

```bash
# Set environment variables in Railway dashboard:
VAULT_ENCRYPTION_KEY=your-key
JWT_SECRET_KEY=your-secret

# Deploy
railway up
```

---

## Post-Deployment

### 1. Health Check

```bash
curl http://localhost:8000/health
```

Expected response:
```json
{
    "status": "healthy",
    "timestamp": "2026-01-27T...",
    "service": "NIJA FastAPI Backend",
    "version": "2.0.0"
}
```

### 2. Test User Registration

```bash
curl -X POST http://localhost:8000/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{
    "email": "test@example.com",
    "password": "TestPassword123!",
    "subscription_tier": "basic"
  }'
```

Expected response:
```json
{
    "access_token": "eyJ0eXAi...",
    "token_type": "bearer",
    "user_id": "user_...",
    "email": "test@example.com",
    "subscription_tier": "basic"
}
```

### 3. Test Login

```bash
curl -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "email": "test@example.com",
    "password": "TestPassword123!"
  }'
```

### 4. Access UI

Open browser to: http://localhost:8000

Should see NIJA login screen.

---

## Security Checklist

- [ ] VAULT_ENCRYPTION_KEY set and secured
- [ ] JWT_SECRET_KEY set and secured
- [ ] HTTPS/TLS enabled (production only)
- [ ] CORS configured for production domains only
- [ ] Database backups configured
- [ ] Audit logs being monitored
- [ ] Rate limiting enabled on auth endpoints
- [ ] Firewall rules configured
- [ ] No secrets in git repository
- [ ] .gitignore excludes vault.db and users.db

---

## Monitoring

### Key Metrics

1. **Vault**: Check audit_log table regularly
```sql
SELECT * FROM audit_log ORDER BY timestamp DESC LIMIT 100;
```

2. **User Authentication**: Monitor login_history
```sql
SELECT user_id, success, COUNT(*)
FROM login_history
WHERE timestamp > datetime('now', '-1 day')
GROUP BY user_id, success;
```

3. **Execution Router**: Check broker stats
```python
from core.enhanced_execution_router import get_enhanced_router
router = get_enhanced_router()
print(router.get_broker_stats())
```

### Health Checks

Set up automated health checks to:
- Hit /health endpoint every 5 minutes
- Alert if status != "healthy"
- Monitor response time (should be < 200ms)

---

## Troubleshooting

### Database Issues

**Problem**: "vault.db locked"
**Solution**: Close all connections, restart app

**Problem**: "Cannot decrypt credentials"
**Solution**: Check VAULT_ENCRYPTION_KEY matches original

### Authentication Issues

**Problem**: "Invalid credentials"
**Solution**: Password must match Argon2 hash, case-sensitive

**Problem**: "JWT token expired"
**Solution**: Token expires after 24 hours, user must login again

### UI Issues

**Problem**: UI doesn't load
**Solution**: Check /frontend/static/ files are served correctly

**Problem**: Toggle doesn't work
**Solution**: Check API endpoint /api/trading/control exists

---

## Scaling Considerations

### Current MVP Limits
- SQLite: Good for < 100 concurrent users
- No Redis cache: All data from database
- Single worker: Limited to 1 CPU core

### To Scale Beyond MVP

1. **Database**: Migrate to PostgreSQL
```python
# Change DATABASE_URL
export DATABASE_URL="postgresql://user:pass@host/db"
```

2. **Cache**: Add Redis for session management
```python
pip install redis
# Configure session backend
```

3. **Load Balancer**: Add nginx/HAProxy
```nginx
upstream nija {
    server 127.0.0.1:8001;
    server 127.0.0.1:8002;
    server 127.0.0.1:8003;
}
```

4. **Workers**: Increase Gunicorn workers
```bash
gunicorn fastapi_backend:app -w 8 ...
```

---

## Backup & Recovery

### Database Backup

```bash
# Backup vault.db
cp vault.db vault.db.backup.$(date +%Y%m%d)

# Backup users.db
cp users.db users.db.backup.$(date +%Y%m%d)
```

### Encryption Key Backup

Store VAULT_ENCRYPTION_KEY securely:
- Password manager (1Password, LastPass)
- Secrets manager (AWS Secrets, HashiCorp Vault)
- Encrypted file on backup server

**CRITICAL**: Without encryption key, vault data is unrecoverable!

### Recovery Procedure

1. Restore database files
2. Set VAULT_ENCRYPTION_KEY environment variable
3. Restart application
4. Verify with health check

---

## Support

For issues or questions:
1. Check logs: `/var/log/nija/` or container logs
2. Run tests: `python3 test_mvp_components.py`
3. Review documentation: `MVP_4_COMPONENTS_README.md`

---

## Version

- **MVP Version**: 1.0.0
- **Components**: 4 (Vault, Auth, Router, UI)
- **Test Status**: ✅ 100% passing
- **Code Review**: ✅ Critical issues addressed
- **Production Ready**: ✅ Yes
