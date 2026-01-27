# NIJA Platform - Deployment Guide

## 🚀 Production Deployment with Recommended Stack

This guide shows how to deploy the NIJA platform using the recommended production stack:
- **Backend**: FastAPI + PostgreSQL + Redis
- **Frontend**: Next.js + React + Tailwind (coming soon)
- **Mobile**: Flutter or React Native (coming soon)
- **Infrastructure**: Docker + Kubernetes

---

## 📋 Prerequisites

- Docker & Docker Compose installed
- Python 3.11+
- Git
- 4GB+ RAM
- 10GB+ disk space

---

## 🏃 Quick Start (Docker Compose)

### 1. Clone and Setup

```bash
cd /home/runner/work/Nija/Nija

# Generate secure JWT secret
export JWT_SECRET_KEY=$(python -c "import secrets; print(secrets.token_hex(32))")

# Set PostgreSQL password
export POSTGRES_PASSWORD=$(python -c "import secrets; print(secrets.token_hex(16))")

# Optional: Add your master trading account credentials
export COINBASE_API_KEY="your_key_here"
export COINBASE_API_SECRET="your_secret_here"
```

### 2. Start Services

```bash
# Start all services (API, PostgreSQL, Redis)
docker-compose up -d

# Check status
docker-compose ps

# View logs
docker-compose logs -f api
```

### 3. Verify Deployment

```bash
# Check API health
curl http://localhost:8000/health

# Check API docs
open http://localhost:8000/api/docs
```

You should see:
```json
{
  "status": "healthy",
  "timestamp": "2026-01-27T...",
  "service": "NIJA FastAPI Backend",
  "version": "2.0.0"
}
```

### 4. Test API Endpoints

```bash
# Register a new user
curl -X POST http://localhost:8000/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{
    "email": "test@example.com",
    "password": "secure_password_123",
    "subscription_tier": "basic"
  }'

# Login (returns JWT token)
curl -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "email": "test@example.com",
    "password": "secure_password_123"
  }'

# Use the token from login response
export TOKEN="your_jwt_token_here"

# Get user profile
curl -X GET http://localhost:8000/api/user/profile \
  -H "Authorization: Bearer $TOKEN"

# Start NIJA bot
curl -X POST http://localhost:8000/api/start_bot \
  -H "Authorization: Bearer $TOKEN"

# Check bot status
curl -X GET http://localhost:8000/api/status \
  -H "Authorization: Bearer $TOKEN"
```

---

## 🛠️ Local Development (Without Docker)

### 1. Install Dependencies

```bash
cd /home/runner/work/Nija/Nija
pip install -r requirements.txt
```

### 2. Set Environment Variables

```bash
export JWT_SECRET_KEY=$(python -c "import secrets; print(secrets.token_hex(32))")
export PORT=8000
export DEBUG=true
```

### 3. Start FastAPI Server

```bash
# Using uvicorn directly
uvicorn fastapi_backend:app --reload --port 8000

# Or using the Python script
python fastapi_backend.py
```

### 4. Access Services

- **API**: http://localhost:8000
- **API Docs (Swagger)**: http://localhost:8000/api/docs
- **API Docs (ReDoc)**: http://localhost:8000/api/redoc
- **Frontend**: http://localhost:8000/ (if frontend built)

---

## 🔧 Environment Variables

### Required

```bash
# JWT Secret (MUST be set for production)
JWT_SECRET_KEY=your_secret_key_here

# PostgreSQL (if using Docker Compose)
POSTGRES_PASSWORD=your_postgres_password
```

### Optional

```bash
# Server Configuration
PORT=8000
DEBUG=false
JWT_EXPIRATION_HOURS=24

# Database URLs (auto-configured in Docker Compose)
DATABASE_URL=postgresql://user:pass@localhost:5432/nija
REDIS_URL=redis://localhost:6379/0

# Master Trading Account (optional)
COINBASE_API_KEY=...
COINBASE_API_SECRET=...
KRAKEN_MASTER_API_KEY=...
KRAKEN_MASTER_API_SECRET=...
```

---

## 📦 Docker Commands

### Build

```bash
# Build API container
docker-compose build api

# Build with no cache
docker-compose build --no-cache api
```

### Run

```bash
# Start all services
docker-compose up -d

# Start specific service
docker-compose up -d api

# View logs
docker-compose logs -f api

# Follow logs for all services
docker-compose logs -f
```

### Stop & Clean

```bash
# Stop all services
docker-compose down

# Stop and remove volumes (⚠️ deletes database)
docker-compose down -v

# Remove all containers, networks, images
docker-compose down --rmi all -v
```

### Database Management

```bash
# Access PostgreSQL
docker-compose exec postgres psql -U nija_user -d nija

# Run SQL commands
docker-compose exec postgres psql -U nija_user -d nija -c "SELECT * FROM users;"

# Backup database
docker-compose exec postgres pg_dump -U nija_user nija > backup.sql

# Restore database
docker-compose exec -T postgres psql -U nija_user nija < backup.sql
```

### Redis Management

```bash
# Access Redis CLI
docker-compose exec redis redis-cli

# Check keys
docker-compose exec redis redis-cli KEYS '*'

# Flush all data (⚠️ destructive)
docker-compose exec redis redis-cli FLUSHALL
```

---

## ☸️ Kubernetes Deployment (Future)

For production at scale, deploy to Kubernetes:

```yaml
# TODO: Create K8s manifests
# - Deployment for API (multiple replicas)
# - StatefulSet for user execution pods
# - Service for load balancing
# - Ingress for HTTPS
# - PostgreSQL operator or managed service
# - Redis cluster
```

---

## 🌐 Production Best Practices

### Security

1. **HTTPS/TLS**: Use Let's Encrypt or managed certificates
2. **Secret Management**: Use Kubernetes secrets or AWS Secrets Manager
3. **API Rate Limiting**: Implement rate limiting (TODO)
4. **Database Backups**: Automated daily backups
5. **Monitoring**: Prometheus + Grafana

### Performance

1. **Horizontal Scaling**: Run 3+ API instances behind load balancer
2. **Database Optimization**: Connection pooling, read replicas
3. **Caching**: Use Redis for session data and frequently accessed data
4. **CDN**: CloudFlare for static assets

### Reliability

1. **Health Checks**: Kubernetes liveness and readiness probes
2. **Graceful Shutdown**: Handle SIGTERM properly
3. **Circuit Breakers**: For external API calls
4. **Retry Logic**: With exponential backoff

---

## 📊 Monitoring & Logging

### Health Checks

```bash
# API health
curl http://localhost:8000/health

# Database health
docker-compose exec postgres pg_isready -U nija_user

# Redis health
docker-compose exec redis redis-cli ping
```

### Logs

```bash
# API logs
docker-compose logs -f api

# PostgreSQL logs
docker-compose logs -f postgres

# Redis logs
docker-compose logs -f redis

# All logs
docker-compose logs -f
```

### Metrics (TODO)

```python
# Add Prometheus metrics
from prometheus_fastapi_instrumentator import Instrumentator

instrumentator = Instrumentator()
instrumentator.instrument(app).expose(app)
```

---

## 🐛 Troubleshooting

### "Port already in use"

```bash
# Find process using port 8000
lsof -i :8000

# Kill process
kill -9 <PID>

# Or use different port
export PORT=8080
```

### "Database connection failed"

```bash
# Check PostgreSQL status
docker-compose ps postgres

# Restart PostgreSQL
docker-compose restart postgres

# Check logs
docker-compose logs postgres
```

### "Redis connection failed"

```bash
# Check Redis status
docker-compose exec redis redis-cli ping

# Should return: PONG
```

### "Module not found" errors

```bash
# Rebuild container
docker-compose build --no-cache api

# Or reinstall dependencies locally
pip install -r requirements.txt
```

---

## 🔄 Updates & Migrations

### Update Code

```bash
# Pull latest code
git pull origin main

# Rebuild and restart
docker-compose down
docker-compose build
docker-compose up -d
```

### Database Migrations (TODO: Add Alembic)

```bash
# Install Alembic
pip install alembic

# Initialize
alembic init migrations

# Create migration
alembic revision --autogenerate -m "description"

# Apply migration
alembic upgrade head
```

---

## 📱 Next Steps

### 1. Web Dashboard (Next.js)

```bash
# Create Next.js app
npx create-next-app@latest web-dashboard --typescript --tailwind

# Install dependencies
cd web-dashboard
npm install axios socket.io-client

# Configure API URL
# .env.local:
NEXT_PUBLIC_API_URL=http://localhost:8000
```

### 2. Mobile App (Flutter)

```bash
# Create Flutter app
flutter create nija_mobile

# Add dependencies
# pubspec.yaml:
dependencies:
  http: ^1.1.0
  provider: ^6.1.1
  flutter_secure_storage: ^9.0.0
```

### 3. Deploy to Cloud

**AWS:**
- ECS/Fargate for containers
- RDS for PostgreSQL
- ElastiCache for Redis
- ALB for load balancing
- Route 53 for DNS

**GCP:**
- Cloud Run for containers
- Cloud SQL for PostgreSQL
- Memorystore for Redis
- Cloud Load Balancing

**Azure:**
- Container Instances
- Azure Database for PostgreSQL
- Azure Cache for Redis
- Application Gateway

---

## 📚 Additional Resources

- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [PostgreSQL Documentation](https://www.postgresql.org/docs/)
- [Redis Documentation](https://redis.io/documentation)
- [Docker Documentation](https://docs.docker.com/)
- [Kubernetes Documentation](https://kubernetes.io/docs/)

---

## 🎓 Architecture Recap

```
┌─────────────────────────────────────┐
│   Mobile App / Web Dashboard        │
├─────────────────────────────────────┤
│   Flutter/RN  |  Next.js + React    │
└─────────────────────────────────────┘
               ↓
┌─────────────────────────────────────┐
│   FastAPI Backend (Layer 3)         │
├─────────────────────────────────────┤
│   /api/start_bot                    │
│   /api/stop_bot                     │
│   /api/status                       │
│   /api/positions                    │
│   /api/pnl                          │
│   /api/config                       │
└─────────────────────────────────────┘
               ↓
┌─────────────────────────────────────┐
│   User Control Backend (Layer 2)    │
├─────────────────────────────────────┤
│   Isolated execution per user       │
│   Risk management                   │
│   Position tracking                 │
└─────────────────────────────────────┘
               ↓
┌─────────────────────────────────────┐
│   NIJA Core Brain (Layer 1)         │
├─────────────────────────────────────┤
│   🔒 PRIVATE - Strategy Logic       │
│   🔒 PRIVATE - AI Models            │
└─────────────────────────────────────┘
               ↓
┌─────────────────────────────────────┐
│   Exchanges (Coinbase, Kraken...)   │
└─────────────────────────────────────┘
```

---

**🚀 Your NIJA engine is now wrapped as a headless microservice!**

Users can start/stop trading, view stats, and manage settings without ever seeing your proprietary strategy logic.
