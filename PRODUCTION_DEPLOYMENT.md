# NIJA Platform Production Deployment Guide

This guide provides step-by-step instructions for deploying the NIJA trading platform to production.

## Overview

NIJA consists of several components that can be deployed together or separately:

1. **PostgreSQL Database** - Data persistence
2. **FastAPI Backend** - REST API server
3. **Frontend Dashboard** - Web UI
4. **Redis** (optional) - Caching and rate limiting
5. **HashiCorp Vault** (optional) - Secrets management

## Quick Start with Docker Compose

The fastest way to get started is using Docker Compose:

```bash
# Clone repository
git clone https://github.com/your-org/nija.git
cd nija

# Copy environment file
cp .env.example .env

# Edit .env with your configuration
nano .env

# Start all services
docker-compose up -d

# Check logs
docker-compose logs -f

# Stop services
docker-compose down
```

## Environment Configuration

### Required Environment Variables

```bash
# JWT Configuration
JWT_SECRET_KEY=your-secure-random-secret-key-here
JWT_EXPIRATION_HOURS=24

# PostgreSQL Database
POSTGRES_HOST=postgres
POSTGRES_PORT=5432
POSTGRES_DB=nija
POSTGRES_USER=nija_user
POSTGRES_PASSWORD=your-secure-password

# Or use single DATABASE_URL
DATABASE_URL=postgresql://nija_user:password@postgres:5432/nija

# API Configuration
PORT=8000
DEBUG=false
ALLOWED_ORIGINS=https://yourdomain.com,https://app.yourdomain.com
TRUSTED_HOSTS=yourdomain.com,app.yourdomain.com

# Rate Limiting
RATE_LIMIT_REQUESTS=100
RATE_LIMIT_WINDOW=60

# Vault (Optional)
VAULT_ADDR=http://vault:8200
VAULT_TOKEN=your-vault-token

# Redis (Optional)
REDIS_URL=redis://redis:6379/0
```

### Generate Secure Secrets

```bash
# Generate JWT secret
python -c "import secrets; print(secrets.token_hex(32))"

# Generate database password
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

## Deployment Options

### Option 1: Railway (Recommended for Easy Start)

Railway provides automatic deployment with PostgreSQL provisioning.

1. **Sign up at [railway.app](https://railway.app)**

2. **Install Railway CLI**:
   ```bash
   npm install -g @railway/cli
   railway login
   ```

3. **Initialize Project**:
   ```bash
   railway init
   railway link
   ```

4. **Add PostgreSQL**:
   ```bash
   railway add postgresql
   ```

5. **Deploy**:
   ```bash
   railway up
   ```

6. **Configure Environment**:
   - Go to Railway dashboard
   - Add environment variables from `.env.example`
   - Set `PORT=8000`

7. **Access Application**:
   - Railway provides automatic HTTPS domain
   - Access API at: `https://your-app.railway.app`
   - Access docs at: `https://your-app.railway.app/api/docs`

### Option 2: Docker + Cloud Provider

#### AWS EC2

1. **Launch EC2 Instance**:
   - Ubuntu 22.04 LTS
   - t3.medium or larger
   - Security group: Allow ports 80, 443, 22

2. **SSH into Instance**:
   ```bash
   ssh -i your-key.pem ubuntu@your-instance-ip
   ```

3. **Install Docker**:
   ```bash
   curl -fsSL https://get.docker.com -o get-docker.sh
   sudo sh get-docker.sh
   sudo usermod -aG docker $USER
   ```

4. **Install Docker Compose**:
   ```bash
   sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
   sudo chmod +x /usr/local/bin/docker-compose
   ```

5. **Deploy Application**:
   ```bash
   git clone https://github.com/your-org/nija.git
   cd nija
   cp .env.example .env
   nano .env  # Edit configuration
   docker-compose up -d
   ```

6. **Setup Nginx Reverse Proxy**:
   ```bash
   sudo apt install nginx certbot python3-certbot-nginx
   ```

   Create `/etc/nginx/sites-available/nija`:
   ```nginx
   server {
       listen 80;
       server_name yourdomain.com;

       location / {
           proxy_pass http://localhost:8000;
           proxy_set_header Host $host;
           proxy_set_header X-Real-IP $remote_addr;
           proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
           proxy_set_header X-Forwarded-Proto $scheme;
       }

       location /ws {
           proxy_pass http://localhost:8000/ws;
           proxy_http_version 1.1;
           proxy_set_header Upgrade $http_upgrade;
           proxy_set_header Connection "upgrade";
       }
   }
   ```

   Enable site and SSL:
   ```bash
   sudo ln -s /etc/nginx/sites-available/nija /etc/nginx/sites-enabled/
   sudo nginx -t
   sudo systemctl restart nginx
   sudo certbot --nginx -d yourdomain.com
   ```

#### Google Cloud Run

1. **Install Google Cloud SDK**:
   ```bash
   curl https://sdk.cloud.google.com | bash
   gcloud init
   ```

2. **Build and Push Container**:
   ```bash
   gcloud builds submit --tag gcr.io/PROJECT-ID/nija-api
   ```

3. **Deploy to Cloud Run**:
   ```bash
   gcloud run deploy nija-api \
     --image gcr.io/PROJECT-ID/nija-api \
     --platform managed \
     --region us-central1 \
     --allow-unauthenticated \
     --set-env-vars DATABASE_URL=$DATABASE_URL,JWT_SECRET_KEY=$JWT_SECRET_KEY
   ```

### Option 3: Kubernetes

For production scale, use Kubernetes:

```bash
# Apply Kubernetes configs
kubectl apply -f k8s/
```

See `k8s/` directory for complete Kubernetes manifests.

## Database Setup

### Initialize Database

```bash
# Using Docker Compose
docker-compose exec api python init_database.py --demo-user

# Or locally
python init_database.py --demo-user
```

### Run Migrations

```bash
# Apply all migrations
alembic upgrade head

# Check current version
alembic current
```

### Backup Database

```bash
# Create backup
docker-compose exec postgres pg_dump -U nija_user nija > backup_$(date +%Y%m%d).sql

# Restore backup
docker-compose exec -T postgres psql -U nija_user nija < backup_20260129.sql
```

## Monitoring & Maintenance

### Health Checks

```bash
# Check API health
curl https://yourdomain.com/health

# Check database health
docker-compose exec api python -c "from database.db_connection import init_database, check_database_health; init_database(); print(check_database_health())"
```

### View Logs

```bash
# All services
docker-compose logs -f

# API only
docker-compose logs -f api

# Database only
docker-compose logs -f postgres

# Last 100 lines
docker-compose logs --tail=100 api
```

### Performance Monitoring

Add these endpoints to your monitoring:

- `GET /health` - Service health
- `GET /api/info` - API info
- Database connection pool metrics

Consider integrating:
- **Prometheus** for metrics
- **Grafana** for dashboards
- **Sentry** for error tracking
- **DataDog** or **New Relic** for APM

## Security Checklist

Before going to production:

- [ ] Change all default passwords
- [ ] Generate strong JWT secret
- [ ] Enable HTTPS (SSL/TLS)
- [ ] Configure CORS for specific domains
- [ ] Set up firewall rules
- [ ] Enable rate limiting
- [ ] Configure trusted hosts
- [ ] Backup encryption keys
- [ ] Set up automated backups
- [ ] Enable audit logging
- [ ] Review and restrict database permissions
- [ ] Implement IP whitelisting for admin endpoints
- [ ] Set up monitoring and alerting

## Scaling

### Horizontal Scaling

Scale API servers:

```bash
# Docker Compose
docker-compose up -d --scale api=3

# Kubernetes
kubectl scale deployment nija-api --replicas=5
```

### Database Scaling

For high load:

1. **Read Replicas**: Create PostgreSQL read replicas for analytics queries
2. **Connection Pooling**: Use PgBouncer for connection pooling
3. **Caching**: Add Redis for frequently accessed data

### Load Balancing

Use a load balancer (Nginx, HAProxy, or cloud LB):

```nginx
upstream nija_backend {
    least_conn;
    server api1:8000;
    server api2:8000;
    server api3:8000;
}

server {
    listen 80;
    location / {
        proxy_pass http://nija_backend;
    }
}
```

## Troubleshooting

### API Not Starting

```bash
# Check logs
docker-compose logs api

# Common issues:
# 1. Database not ready -> Wait for postgres to initialize
# 2. Missing env vars -> Check .env file
# 3. Port already in use -> Change PORT in .env
```

### Database Connection Errors

```bash
# Test database connection
docker-compose exec postgres psql -U nija_user -d nija -c "SELECT 1;"

# Check database is running
docker-compose ps postgres

# Restart database
docker-compose restart postgres
```

### High Memory Usage

```bash
# Check resource usage
docker stats

# Limit container resources in docker-compose.yml:
services:
  api:
    deploy:
      resources:
        limits:
          memory: 512M
```

## Rollback

If deployment fails:

```bash
# Docker Compose
docker-compose down
git checkout previous-working-commit
docker-compose up -d

# Database rollback
alembic downgrade -1
```

## Support & Documentation

- API Documentation: `/api/docs` (Swagger UI)
- Database Setup: `DATABASE_SETUP.md`
- Architecture: `MULTI_USER_PLATFORM_ARCHITECTURE.md`
- Security: `SECURITY.md`

---

**Document Version**: 1.0
**Last Updated**: January 29, 2026
**Status**: Production Ready
