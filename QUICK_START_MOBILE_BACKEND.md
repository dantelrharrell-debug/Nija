# NIJA Mobile Backend - Quick Start Guide

Get your NIJA mobile backend running in production in under 10 minutes.

## Option 1: Railway (Easiest - Recommended)

### Step 1: Install Railway CLI
```bash
npm install -g @railway/cli
```

### Step 2: Deploy
```bash
# Login to Railway
railway login

# Navigate to NIJA directory
cd /path/to/Nija

# Initialize project
railway init

# Add PostgreSQL
railway add postgresql

# Add Redis
railway add redis

# Deploy!
railway up
```

### Step 3: Configure Environment Variables

In Railway dashboard (https://railway.app):
1. Go to your project → Variables
2. Add these variables:

```
JWT_SECRET_KEY=your-random-secret-key-here-make-it-long
STRIPE_SECRET_KEY=sk_live_YOUR_STRIPE_KEY
APPLE_SHARED_SECRET=your-apple-shared-secret
GOOGLE_SERVICE_ACCOUNT_JSON={"type":"service_account",...}
ALLOWED_ORIGINS=https://your-domain.com
PORT=5000
FLASK_ENV=production
DEBUG=false
```

### Step 4: Get Your API URL

Railway will provide a URL like: `https://nija-production.up.railway.app`

Test it:
```bash
curl https://nija-production.up.railway.app/health
```

**Done!** Your mobile backend is live. 🎉

---

## Option 2: Docker (Local Testing)

### Step 1: Start Services
```bash
cd /path/to/Nija
docker-compose up -d
```

### Step 2: Test
```bash
# Health check
curl http://localhost:8000/health

# API docs
curl http://localhost:8000/api/docs
```

**Done!** Backend running on http://localhost:8000

---

## Option 3: Local Development

### Step 1: Install Dependencies
```bash
pip install -r requirements.txt
```

### Step 2: Set Environment Variables
```bash
export DATABASE_URL=postgresql://user:pass@localhost:5432/nija
export JWT_SECRET_KEY=your-secret-key
export STRIPE_SECRET_KEY=sk_test_xxx
```

### Step 3: Initialize Database
```bash
python init_database.py
```

### Step 4: Start Server
```bash
python mobile_backend_server.py
```

**Done!** Backend running on http://localhost:5000

---

## Test Your Deployment

### 1. Health Check
```bash
curl https://your-api-url/health
```

Expected response:
```json
{
  "status": "alive",
  "timestamp": "2026-02-13T01:00:00",
  "service": "NIJA Cloud API",
  "version": "1.0.0"
}
```

### 2. API Documentation
```bash
curl https://your-api-url/api/docs
```

### 3. WebSocket Test

Create `test_websocket.html`:
```html
<!DOCTYPE html>
<html>
<head>
    <title>NIJA WebSocket Test</title>
    <script src="https://cdn.socket.io/4.5.4/socket.io.min.js"></script>
</head>
<body>
    <h1>NIJA WebSocket Test</h1>
    <div id="status">Connecting...</div>
    <div id="messages"></div>

    <script>
        const socket = io('https://your-api-url');
        
        socket.on('connect', () => {
            document.getElementById('status').textContent = 'Connected!';
            console.log('Connected to NIJA');
        });
        
        socket.on('disconnect', () => {
            document.getElementById('status').textContent = 'Disconnected';
        });
    </script>
</body>
</html>
```

---

## Configure Mobile App

### iOS (Info.plist)
```xml
<key>API_BASE_URL</key>
<string>https://your-api-url</string>
```

### Android (strings.xml)
```xml
<string name="api_base_url">https://your-api-url</string>
```

### React Native (.env)
```
API_BASE_URL=https://your-api-url
```

---

## Required Secrets

### 1. JWT Secret Key

Generate a secure random key:
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

### 2. Stripe API Keys

Get from: https://dashboard.stripe.com/apikeys

- Test: `sk_test_...`
- Live: `sk_live_...`

### 3. Apple Shared Secret

Get from: https://appstoreconnect.apple.com
1. Go to App Store Connect
2. My Apps → Select App → App Information
3. App-Specific Shared Secret → Generate

### 4. Google Service Account JSON

Get from: https://console.cloud.google.com
1. IAM & Admin → Service Accounts
2. Create Service Account
3. Grant "Service Account User" role
4. Create JSON key
5. Copy entire JSON content

---

## Monitoring

### Check Logs (Railway)
```bash
railway logs
```

### Check Logs (Docker)
```bash
docker-compose logs -f api
```

### Check Health
```bash
# Health endpoint
curl https://your-api-url/health

# Detailed status
curl https://your-api-url/status
```

---

## Troubleshooting

### Issue: "Module not found" error

**Solution:**
```bash
pip install -r requirements.txt
```

### Issue: Database connection error

**Solution:** Check `DATABASE_URL` format:
```
postgresql://username:password@host:port/database
```

### Issue: WebSocket not connecting

**Solution:**
1. Check CORS settings in `mobile_backend_server.py`
2. Ensure `eventlet` worker is used (not threaded)
3. Verify firewall allows WebSocket connections

### Issue: IAP verification fails

**Solution:**
1. Check `APPLE_SHARED_SECRET` is set
2. Verify `GOOGLE_SERVICE_ACCOUNT_JSON` is valid JSON
3. Ensure using correct environment (sandbox vs production)

---

## Production Checklist

Before going live:

- [ ] Set `FLASK_ENV=production`
- [ ] Set `DEBUG=false`
- [ ] Use production database (not development)
- [ ] Enable SSL/HTTPS
- [ ] Set strong `JWT_SECRET_KEY`
- [ ] Configure `ALLOWED_ORIGINS` (not *)
- [ ] Set up monitoring (Sentry recommended)
- [ ] Configure backup strategy
- [ ] Test all API endpoints
- [ ] Test WebSocket connections
- [ ] Test IAP flows (iOS and Android)
- [ ] Review security settings
- [ ] Set up error logging
- [ ] Configure rate limiting

---

## Scaling

### Railway Auto-Scaling

Railway automatically scales based on traffic. Configure in dashboard:
- Min instances: 1
- Max instances: 10

### Manual Scaling (Docker)

```bash
docker-compose up -d --scale api=3
```

### Load Balancer

For production, add load balancer:
- AWS: Application Load Balancer (ALB)
- GCP: Cloud Load Balancing
- Azure: Azure Load Balancer

---

## Cost Estimates

**Railway (Starter):**
- Hobby: $5/month
- Pro: $20/month + usage

**AWS (Production):**
- ECS Fargate: ~$40-80/month
- RDS PostgreSQL: ~$15-30/month
- Total: ~$60-120/month

**GCP (Production):**
- Cloud Run: ~$20-40/month
- Cloud SQL: ~$10-25/month
- Total: ~$30-65/month

---

## Need Help?

- **Documentation:** See MOBILE_READINESS_COMPLETE.md
- **Deployment:** See CLOUD_DEPLOYMENT_GUIDE.md
- **App Stores:** See APP_STORE_SUBMISSION_COMPLETE.md
- **Issues:** https://github.com/dantelrharrell-debug/Nija/issues
- **Email:** support@nija.app

---

## Next Steps

1. ✅ Deploy backend (this guide)
2. 🔄 Integrate IAP in mobile app
3. 🔄 Test end-to-end flows
4. 🔄 Generate app store assets
5. 🔄 Submit to Apple + Google
6. 🔄 Launch! 🚀

**Happy deploying!** 🎉
