# API Gateway Deployment Guide

This guide explains how to deploy the NIJA API Gateway for mobile and web app integration.

## Overview

The API Gateway provides a clean REST API layer on top of the NIJA trading bot, enabling:
- Remote control via mobile apps (iOS/Android)
- Web dashboard integration
- Third-party system integration
- Multi-user support with authentication

**Strategy Lock**: API Gateway only exposes v7.2 profitability logic. No unauthorized modifications possible.

## Deployment Options

### Option 1: Deploy with Trading Bot (Recommended for Single User)

Run the API Gateway alongside the trading bot on the same server.

```bash
# In one terminal: Start trading bot
./start.sh

# In another terminal: Start API Gateway
./start_api_gateway.sh
```

**Pros:**
- Simple setup
- Single deployment
- Shared resources

**Cons:**
- Single point of failure
- Can't scale API independently

### Option 2: Separate Deployment (Recommended for Multi-User)

Deploy API Gateway as a separate microservice.

```bash
# Deploy API Gateway on dedicated server/container
docker build -f Dockerfile.gateway -t nija-api-gateway .
docker run -d \
  -p 8000:8000 \
  -e JWT_SECRET_KEY=your-secret-key-here \
  -e JWT_EXPIRATION_HOURS=24 \
  --name nija-api \
  nija-api-gateway
```

**Pros:**
- Independent scaling
- Better isolation
- Easier load balancing
- Can serve multiple trading bot instances

**Cons:**
- More complex setup
- Requires network configuration

## Railway Deployment

### 1. Create New Service

```bash
# Option A: Deploy from Dockerfile
# In Railway dashboard:
# 1. Create new service
# 2. Connect GitHub repo
# 3. Set root directory to /
# 4. Use Dockerfile.gateway

# Option B: Deploy using CLI
railway up --dockerfile Dockerfile.gateway
```

### 2. Configure Environment Variables

In Railway dashboard, add these variables:

```bash
# Required
JWT_SECRET_KEY=<generate-strong-random-key>
PORT=8000

# Optional
JWT_EXPIRATION_HOURS=24
```

### 3. Generate JWT Secret

```bash
# Generate a secure JWT secret
python -c "import secrets; print(secrets.token_hex(32))"
```

### 4. Deploy

Railway will automatically deploy when you push to your branch.

```bash
git push origin main
```

## Render Deployment

### 1. Create Web Service

1. Go to Render Dashboard
2. Click "New +" → "Web Service"
3. Connect your GitHub repository
4. Configure:
   - **Name**: nija-api-gateway
   - **Environment**: Docker
   - **Dockerfile Path**: Dockerfile.gateway
   - **Plan**: Free (or higher for production)

### 2. Environment Variables

Add in Render dashboard:

```bash
JWT_SECRET_KEY=<your-secure-secret>
PORT=8000
JWT_EXPIRATION_HOURS=24
```

### 3. Deploy

Click "Create Web Service" - Render will build and deploy automatically.

## Docker Compose (Local Development)

Create `docker-compose.api.yml`:

```yaml
version: '3.8'

services:
  api-gateway:
    build:
      context: .
      dockerfile: Dockerfile.gateway
    ports:
      - "8000:8000"
    environment:
      - JWT_SECRET_KEY=${JWT_SECRET_KEY}
      - JWT_EXPIRATION_HOURS=24
      - PORT=8000
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s
```

Run with:

```bash
# Create .env file with JWT_SECRET_KEY
echo "JWT_SECRET_KEY=$(python -c 'import secrets; print(secrets.token_hex(32))')" > .env

# Start
docker-compose -f docker-compose.api.yml up -d

# View logs
docker-compose -f docker-compose.api.yml logs -f

# Stop
docker-compose -f docker-compose.api.yml down
```

## Kubernetes Deployment

### 1. Create Secret

```bash
# Generate secret
kubectl create secret generic nija-api-secrets \
  --from-literal=jwt-secret-key=$(python -c 'import secrets; print(secrets.token_hex(32))')
```

### 2. Create Deployment

Create `k8s/api-gateway-deployment.yaml`:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: nija-api-gateway
spec:
  replicas: 2
  selector:
    matchLabels:
      app: nija-api-gateway
  template:
    metadata:
      labels:
        app: nija-api-gateway
    spec:
      containers:
      - name: api-gateway
        image: your-registry/nija-api-gateway:latest
        ports:
        - containerPort: 8000
        env:
        - name: JWT_SECRET_KEY
          valueFrom:
            secretKeyRef:
              name: nija-api-secrets
              key: jwt-secret-key
        - name: PORT
          value: "8000"
        - name: JWT_EXPIRATION_HOURS
          value: "24"
        resources:
          requests:
            memory: "256Mi"
            cpu: "250m"
          limits:
            memory: "512Mi"
            cpu: "500m"
        livenessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 30
          periodSeconds: 10
        readinessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 5
          periodSeconds: 5
---
apiVersion: v1
kind: Service
metadata:
  name: nija-api-gateway
spec:
  type: LoadBalancer
  selector:
    app: nija-api-gateway
  ports:
  - port: 80
    targetPort: 8000
    protocol: TCP
```

### 3. Deploy to Kubernetes

```bash
kubectl apply -f k8s/api-gateway-deployment.yaml
```

## Environment Variables Reference

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `JWT_SECRET_KEY` | Yes | - | Secret key for JWT signing (must be secure in production) |
| `PORT` | No | 8000 | Port to run API Gateway |
| `JWT_EXPIRATION_HOURS` | No | 24 | JWT token expiration time in hours |

## Security Best Practices

### 1. JWT Secret

**CRITICAL**: Use a strong, random JWT secret in production.

```bash
# Generate secure secret (64 characters)
python -c "import secrets; print(secrets.token_hex(32))"
```

**Never:**
- Use default or weak secrets
- Commit secrets to Git
- Share secrets in logs or error messages

### 2. HTTPS Only

Always use HTTPS in production. Configure your reverse proxy (nginx, Traefik, etc.) or cloud platform to enforce HTTPS.

```nginx
# Example nginx configuration
server {
    listen 80;
    server_name api.nija.example.com;
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl;
    server_name api.nija.example.com;
    
    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;
    
    location / {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### 3. CORS Configuration

In production, restrict CORS to your app domains:

```python
# Edit api_gateway.py
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://app.nija.example.com",
        "https://mobile.nija.example.com",
    ],  # Replace with your domains
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)
```

### 4. Rate Limiting (Optional)

For production, add rate limiting to prevent abuse:

```bash
pip install slowapi
```

```python
# Add to api_gateway.py
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Apply to endpoints
@app.post("/api/v1/start")
@limiter.limit("10/minute")  # 10 requests per minute
async def start_trading(...):
    ...
```

## Monitoring

### Health Check

```bash
# Check if API is running
curl http://localhost:8000/health

# Expected response:
# {"status":"healthy","timestamp":"2026-01-27T22:23:53.510Z"}
```

### Logs

```bash
# Docker logs
docker logs -f nija-api-gateway

# Docker Compose logs
docker-compose -f docker-compose.api.yml logs -f api-gateway

# Kubernetes logs
kubectl logs -f deployment/nija-api-gateway
```

### Metrics (Optional)

Add Prometheus metrics for production monitoring:

```bash
pip install prometheus-fastapi-instrumentator
```

```python
# Add to api_gateway.py
from prometheus_fastapi_instrumentator import Instrumentator

# After app creation
Instrumentator().instrument(app).expose(app)
```

Access metrics at: `http://localhost:8000/metrics`

## Testing the Deployment

### 1. Check Health

```bash
curl http://your-deployment-url/health
```

### 2. Get API Info

```bash
curl http://your-deployment-url/
```

### 3. Test Authentication (requires JWT token)

```bash
# This should return 401 Unauthorized (expected without token)
curl -X POST http://your-deployment-url/api/v1/start

# With token (replace YOUR_JWT_TOKEN)
curl -X POST http://your-deployment-url/api/v1/start \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{}'
```

### 4. Access API Documentation

Visit in browser:
- Swagger UI: `http://your-deployment-url/api/v1/docs`
- ReDoc: `http://your-deployment-url/api/v1/redoc`

## Troubleshooting

### API Gateway Won't Start

**Check Python Dependencies:**
```bash
pip install -r requirements.txt
```

**Check Port Availability:**
```bash
# Linux/Mac
lsof -i :8000

# Windows
netstat -ano | findstr :8000
```

### 401 Unauthorized Errors

**Check JWT Token:**
- Ensure token is not expired
- Verify JWT_SECRET_KEY matches between token generation and API
- Check Authorization header format: `Bearer <token>`

### CORS Errors

**Update CORS Settings:**
- Add your app domain to `allow_origins` in `api_gateway.py`
- Ensure credentials are enabled if using cookies

### Connection Refused

**Check Firewall:**
```bash
# Allow port 8000
sudo ufw allow 8000/tcp
```

**Check Container Networking:**
```bash
docker network ls
docker network inspect bridge
```

## Scaling Considerations

### Horizontal Scaling

Deploy multiple API Gateway instances behind a load balancer:

```yaml
# Kubernetes scaling
kubectl scale deployment nija-api-gateway --replicas=5
```

### Vertical Scaling

Increase resources for each instance:

```yaml
resources:
  requests:
    memory: "512Mi"
    cpu: "500m"
  limits:
    memory: "1Gi"
    cpu: "1000m"
```

### Caching

Add Redis for session caching (future enhancement):

```python
# Example with Redis
import redis
r = redis.Redis(host='localhost', port=6379, db=0)
```

## Next Steps

1. ✅ Deploy API Gateway
2. 🔄 Generate JWT tokens for users
3. 🔄 Build mobile app using React Native/Flutter
4. 🔄 Add authentication endpoints (login/signup)
5. 🔄 Implement user management system
6. 🔄 Add WebSocket support for real-time updates

## Support

- **Documentation**: [MOBILE_APP_SETUP.md](MOBILE_APP_SETUP.md)
- **API Spec**: [api_gateway_openapi.json](api_gateway_openapi.json)
- **Source Code**: [api_gateway.py](api_gateway.py)

---

**Version**: 1.0.0  
**Strategy**: v7.2 (Locked - Profitability Mode)  
**Last Updated**: January 27, 2026
