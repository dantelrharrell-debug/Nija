# NIJA Platform - Quick Start Guide

Get NIJA running in production in 5 minutes!

## Prerequisites

- Docker and Docker Compose installed
- PostgreSQL database (or use included Docker Compose setup)
- Domain name with DNS configured (for production)

## 🚀 Quick Start (5 Minutes)

### 1. Clone Repository

```bash
git clone https://github.com/your-org/nija.git
cd nija
```

### 2. Configure Environment

```bash
# Copy production environment template
cp .env.production.example .env

# Generate secure secrets
python -c "import secrets; print('JWT_SECRET_KEY=' + secrets.token_hex(32))" >> .env
python -c "import secrets; print('POSTGRES_PASSWORD=' + secrets.token_urlsafe(32))" >> .env

# Edit .env and configure your domain
nano .env
```

**Minimum required configuration:**
- `JWT_SECRET_KEY` - Generated above
- `POSTGRES_PASSWORD` - Generated above
- `ALLOWED_ORIGINS` - Your domain (e.g., https://yourdomain.com)

### 3. Start Services

```bash
# Start all services in background
docker-compose up -d

# View logs
docker-compose logs -f
```

### 4. Verify Installation

```bash
# Check service health
curl http://localhost:8000/health

# Access API documentation
open http://localhost:8000/api/docs

# Access dashboard
open http://localhost:8000/
```

### 5. Create First User

Option A: Via Web Dashboard
- Navigate to http://localhost:8000/
- Click "Register"
- Fill in email and password
- Select subscription tier

Option B: Via API
```bash
curl -X POST http://localhost:8000/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{
    "email": "admin@yourdomain.com",
    "password": "SecurePassword123!",
    "subscription_tier": "pro"
  }'
```

## 🌐 Production Deployment

### Railway (Easiest)

1. **Install Railway CLI**:
   ```bash
   npm install -g @railway/cli
   railway login
   ```

2. **Deploy**:
   ```bash
   railway up
   ```

3. **Add PostgreSQL**:
   ```bash
   railway add postgresql
   ```

4. **Configure Environment**:
   - Go to Railway dashboard
   - Add environment variables from `.env.production.example`
   - Railway automatically sets `DATABASE_URL`

5. **Access Your App**:
   - Railway provides automatic HTTPS domain
   - Update `ALLOWED_ORIGINS` with your Railway domain

### Docker + VPS (AWS/DigitalOcean/etc)

1. **Launch Server**:
   - Ubuntu 22.04 LTS
   - 2GB+ RAM
   - Open ports: 80, 443

2. **Install Dependencies**:
   ```bash
   # Update system
   sudo apt update && sudo apt upgrade -y

   # Install Docker
   curl -fsSL https://get.docker.com -o get-docker.sh
   sudo sh get-docker.sh

   # Install Docker Compose
   sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
   sudo chmod +x /usr/local/bin/docker-compose
   ```

3. **Deploy Application**:
   ```bash
   git clone https://github.com/your-org/nija.git
   cd nija
   cp .env.production.example .env
   nano .env  # Configure
   docker-compose up -d
   ```

4. **Setup HTTPS (with Nginx)**:
   ```bash
   # Install Nginx and Certbot
   sudo apt install nginx certbot python3-certbot-nginx -y

   # Configure Nginx (see PRODUCTION_DEPLOYMENT.md)
   # Get SSL certificate
   sudo certbot --nginx -d yourdomain.com
   ```

## 📊 Accessing the Platform

### Web Dashboard
- URL: `https://yourdomain.com/`
- Features:
  - User registration and login
  - Trading bot control (start/stop)
  - Performance analytics
  - Broker account linking
  - Settings management

### API Documentation
- Swagger UI: `https://yourdomain.com/api/docs`
- ReDoc: `https://yourdomain.com/api/redoc`
- OpenAPI JSON: `https://yourdomain.com/openapi.json`

### Key API Endpoints

**Authentication**
- `POST /api/auth/register` - Register new user
- `POST /api/auth/login` - Login and get JWT token
- `GET /api/user/profile` - Get user profile

**Trading Control**
- `POST /api/start_bot` - Start trading bot
- `POST /api/stop_bot` - Stop trading bot
- `GET /api/status` - Get bot status

**Brokers**
- `GET /api/user/brokers` - List connected brokers
- `POST /api/user/brokers/{broker}` - Add broker credentials
- `DELETE /api/user/brokers/{broker}` - Remove broker

**Analytics**
- `GET /api/pnl` - Get profit/loss statistics
- `GET /api/positions` - Get active positions
- `GET /api/analytics/trades` - Get trade history
- `GET /api/analytics/performance` - Get performance metrics

## 🔧 Common Tasks

### View Logs

```bash
# All services
docker-compose logs -f

# API only
docker-compose logs -f api

# Last 100 lines
docker-compose logs --tail=100 api
```

### Restart Services

```bash
# Restart all
docker-compose restart

# Restart API only
docker-compose restart api
```

### Database Backup

```bash
# Create backup
docker-compose exec postgres pg_dump -U nija_user nija > backup_$(date +%Y%m%d).sql

# Restore backup
docker-compose exec -T postgres psql -U nija_user nija < backup_20260129.sql
```

### Update Application

```bash
# Pull latest code
git pull

# Rebuild and restart
docker-compose down
docker-compose build --no-cache
docker-compose up -d
```

### Scale API Servers

```bash
# Run 3 API instances
docker-compose up -d --scale api=3
```

## 🔒 Security Checklist

Before production:
- [ ] Change all default passwords
- [ ] Generate unique JWT secret
- [ ] Configure CORS for your domain only
- [ ] Enable HTTPS with valid SSL certificate
- [ ] Set up firewall rules
- [ ] Configure rate limiting
- [ ] Review database access permissions
- [ ] Enable automated backups
- [ ] Set up monitoring/alerting

## 🆘 Troubleshooting

### API won't start
```bash
# Check logs
docker-compose logs api

# Common fix: Database not ready
# Solution: Wait 30 seconds and try again
docker-compose restart api
```

### Can't connect to database
```bash
# Test database connection
docker-compose exec postgres psql -U nija_user -d nija

# Check if database is running
docker-compose ps postgres
```

### "CORS policy" error
- Update `ALLOWED_ORIGINS` in `.env` with your frontend domain
- Restart API: `docker-compose restart api`

### Port already in use
```bash
# Change PORT in .env
# Example: PORT=8001

# Or stop conflicting service
sudo lsof -ti:8000 | xargs kill
```

## 📚 Additional Resources

- **Full Deployment Guide**: `PRODUCTION_DEPLOYMENT.md`
- **Database Setup**: `DATABASE_SETUP.md`
- **Architecture**: `MULTI_USER_PLATFORM_ARCHITECTURE.md`
- **API Documentation**: `/api/docs` (when running)

## 🎯 Next Steps

1. **Configure Brokers**: Add your exchange API credentials
2. **Start Trading**: Enable the trading bot from dashboard
3. **Monitor Performance**: Check analytics regularly
4. **Scale**: Add more API instances as user base grows
5. **Customize**: Adjust trading parameters for your strategy

## 💬 Support

For issues or questions:
- Check logs: `docker-compose logs`
- Review documentation in repository
- Check API docs: `/api/docs`
- Test health endpoint: `curl http://localhost:8000/health`

---

**Quick Start Version**: 1.0
**Last Updated**: January 29, 2026
**Ready for**: Production Deployment
