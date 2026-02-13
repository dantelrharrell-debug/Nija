# NIJA Mobile Backend - Cloud Deployment Guide

This guide provides deployment instructions for major cloud platforms.

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [AWS Deployment](#aws-deployment)
3. [Google Cloud Platform (GCP)](#gcp-deployment)
4. [Microsoft Azure](#azure-deployment)
5. [Railway (Easiest)](#railway-deployment)
6. [Environment Variables](#environment-variables)
7. [Database Setup](#database-setup)
8. [Monitoring & Logging](#monitoring)

---

## Prerequisites

Before deploying, ensure you have:

- [ ] Cloud account (AWS/GCP/Azure/Railway)
- [ ] Domain name (optional but recommended)
- [ ] SSL certificate or use cloud provider's auto-SSL
- [ ] PostgreSQL database (can use cloud provider's managed DB)
- [ ] Redis instance (for caching and WebSocket)
- [ ] Apple Developer Account ($99/year) for iOS app
- [ ] Google Play Developer Account ($25 one-time) for Android app
- [ ] Stripe account for payment processing

---

## AWS Deployment

### Option 1: AWS Elastic Beanstalk (Easiest)

1. **Install AWS CLI and EB CLI:**
```bash
pip install awsebcli
```

2. **Initialize Elastic Beanstalk:**
```bash
cd /path/to/Nija
eb init -p python-3.11 nija-mobile-api --region us-east-1
```

3. **Create environment:**
```bash
eb create nija-production \
  --instance-type t3.small \
  --database.engine postgres \
  --database.size 5 \
  --envvars \
    DATABASE_URL=postgresql://... \
    JWT_SECRET_KEY=your-secret-key \
    STRIPE_SECRET_KEY=sk_live_...
```

4. **Deploy:**
```bash
eb deploy
```

5. **Open app:**
```bash
eb open
```

### Option 2: AWS ECS with Fargate (Production-Grade)

1. **Build and push Docker image:**
```bash
# Login to ECR
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin <account-id>.dkr.ecr.us-east-1.amazonaws.com

# Build image
docker build -t nija-mobile-api -f Dockerfile.api .

# Tag and push
docker tag nija-mobile-api:latest <account-id>.dkr.ecr.us-east-1.amazonaws.com/nija-mobile-api:latest
docker push <account-id>.dkr.ecr.us-east-1.amazonaws.com/nija-mobile-api:latest
```

2. **Create ECS task definition** (`ecs-task-definition.json`):
```json
{
  "family": "nija-mobile-api",
  "networkMode": "awsvpc",
  "requiresCompatibilities": ["FARGATE"],
  "cpu": "1024",
  "memory": "2048",
  "containerDefinitions": [
    {
      "name": "api",
      "image": "<account-id>.dkr.ecr.us-east-1.amazonaws.com/nija-mobile-api:latest",
      "portMappings": [
        {
          "containerPort": 5000,
          "protocol": "tcp"
        }
      ],
      "environment": [
        {"name": "PORT", "value": "5000"},
        {"name": "FLASK_ENV", "value": "production"}
      ],
      "secrets": [
        {"name": "DATABASE_URL", "valueFrom": "arn:aws:secretsmanager:..."},
        {"name": "JWT_SECRET_KEY", "valueFrom": "arn:aws:secretsmanager:..."}
      ],
      "logConfiguration": {
        "logDriver": "awslogs",
        "options": {
          "awslogs-group": "/ecs/nija-mobile-api",
          "awslogs-region": "us-east-1",
          "awslogs-stream-prefix": "api"
        }
      }
    }
  ]
}
```

3. **Create ECS service:**
```bash
aws ecs create-service \
  --cluster nija-cluster \
  --service-name nija-api-service \
  --task-definition nija-mobile-api \
  --desired-count 2 \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[subnet-xxx],securityGroups=[sg-xxx],assignPublicIp=ENABLED}" \
  --load-balancer targetGroupArn=arn:aws:elasticloadbalancing:...,containerName=api,containerPort=5000
```

### AWS RDS for PostgreSQL

```bash
aws rds create-db-instance \
  --db-instance-identifier nija-postgres \
  --db-instance-class db.t3.micro \
  --engine postgres \
  --engine-version 15.3 \
  --master-username nija_admin \
  --master-user-password <secure-password> \
  --allocated-storage 20 \
  --backup-retention-period 7 \
  --publicly-accessible \
  --vpc-security-group-ids sg-xxx
```

---

## GCP Deployment

### Option 1: Google Cloud Run (Serverless)

1. **Build and push to Google Container Registry:**
```bash
# Set project
gcloud config set project nija-mobile-prod

# Build image
gcloud builds submit --tag gcr.io/nija-mobile-prod/api

# Or build locally and push
docker build -t gcr.io/nija-mobile-prod/api -f Dockerfile.api .
docker push gcr.io/nija-mobile-prod/api
```

2. **Deploy to Cloud Run:**
```bash
gcloud run deploy nija-api \
  --image gcr.io/nija-mobile-prod/api \
  --platform managed \
  --region us-central1 \
  --allow-unauthenticated \
  --set-env-vars "FLASK_ENV=production,PORT=8080" \
  --set-secrets "DATABASE_URL=nija-db-url:latest,JWT_SECRET_KEY=jwt-secret:latest" \
  --min-instances 1 \
  --max-instances 10 \
  --memory 2Gi \
  --cpu 2 \
  --timeout 300
```

3. **Set up Cloud SQL (PostgreSQL):**
```bash
gcloud sql instances create nija-postgres \
  --database-version=POSTGRES_15 \
  --tier=db-f1-micro \
  --region=us-central1 \
  --root-password=<secure-password>

# Create database
gcloud sql databases create nija --instance=nija-postgres

# Connect Cloud Run to Cloud SQL
gcloud run services update nija-api \
  --add-cloudsql-instances nija-mobile-prod:us-central1:nija-postgres
```

### Option 2: Google Kubernetes Engine (GKE)

1. **Create GKE cluster:**
```bash
gcloud container clusters create nija-cluster \
  --region us-central1 \
  --num-nodes 2 \
  --machine-type n1-standard-2 \
  --enable-autoscaling \
  --min-nodes 1 \
  --max-nodes 5
```

2. **Deploy using existing k8s configs:**
```bash
kubectl apply -f k8s/base/
kubectl apply -f k8s/components/api/
```

---

## Azure Deployment

### Option 1: Azure App Service

1. **Create resource group:**
```bash
az group create --name nija-rg --location eastus
```

2. **Create App Service plan:**
```bash
az appservice plan create \
  --name nija-plan \
  --resource-group nija-rg \
  --sku B1 \
  --is-linux
```

3. **Create web app:**
```bash
az webapp create \
  --resource-group nija-rg \
  --plan nija-plan \
  --name nija-mobile-api \
  --deployment-container-image-name <your-dockerhub>/nija-mobile-api:latest
```

4. **Configure app settings:**
```bash
az webapp config appsettings set \
  --resource-group nija-rg \
  --name nija-mobile-api \
  --settings \
    FLASK_ENV=production \
    PORT=8000 \
    DATABASE_URL=<postgres-connection-string> \
    JWT_SECRET_KEY=<your-secret>
```

### Option 2: Azure Container Instances (ACI)

```bash
az container create \
  --resource-group nija-rg \
  --name nija-api \
  --image <your-dockerhub>/nija-mobile-api:latest \
  --cpu 2 \
  --memory 4 \
  --ports 5000 \
  --environment-variables \
    FLASK_ENV=production \
    PORT=5000 \
  --secure-environment-variables \
    DATABASE_URL=<connection-string> \
    JWT_SECRET_KEY=<secret>
```

### Azure Database for PostgreSQL

```bash
az postgres server create \
  --resource-group nija-rg \
  --name nija-postgres \
  --location eastus \
  --admin-user nija_admin \
  --admin-password <secure-password> \
  --sku-name B_Gen5_1 \
  --version 15
```

---

## Railway Deployment (Easiest & Recommended for Getting Started)

1. **Install Railway CLI:**
```bash
npm install -g @railway/cli
```

2. **Login to Railway:**
```bash
railway login
```

3. **Initialize project:**
```bash
cd /path/to/Nija
railway init
```

4. **Add PostgreSQL database:**
```bash
railway add postgresql
```

5. **Add Redis:**
```bash
railway add redis
```

6. **Deploy:**
```bash
railway up
```

7. **Set environment variables in Railway dashboard:**
```
JWT_SECRET_KEY=your-secret-key-here
STRIPE_SECRET_KEY=sk_live_xxx
APPLE_SHARED_SECRET=xxx
GOOGLE_SERVICE_ACCOUNT_JSON={"type":"service_account",...}
ALLOWED_ORIGINS=https://your-domain.com
```

8. **Access logs:**
```bash
railway logs
```

**Railway Configuration** (already exists in `railway.json`):
```json
{
  "$schema": "https://railway.app/railway.schema.json",
  "build": {
    "builder": "DOCKERFILE",
    "dockerfilePath": "Dockerfile.api"
  },
  "deploy": {
    "startCommand": "python mobile_backend_server.py",
    "restartPolicyType": "ON_FAILURE",
    "restartPolicyMaxRetries": 10
  }
}
```

---

## Environment Variables

**Required:**
```bash
# Database
DATABASE_URL=postgresql://user:password@host:5432/nija
REDIS_URL=redis://host:6379/0

# JWT Authentication
JWT_SECRET_KEY=your-secure-random-secret-key
JWT_EXPIRATION_HOURS=24

# Stripe Payment
STRIPE_SECRET_KEY=sk_live_xxxxx
STRIPE_WEBHOOK_SECRET=whsec_xxxxx

# Apple IAP
APPLE_SHARED_SECRET=xxxxx

# Google Play
GOOGLE_PLAY_PACKAGE_NAME=com.nija.trading
GOOGLE_SERVICE_ACCOUNT_JSON={"type":"service_account",...}

# Server
PORT=5000
FLASK_ENV=production
DEBUG=false
ALLOWED_ORIGINS=https://your-domain.com,https://app.nija.io
```

**Optional:**
```bash
# Rate Limiting
RATE_LIMIT_REQUESTS=100
RATE_LIMIT_WINDOW=60

# Logging
LOG_LEVEL=INFO
SENTRY_DSN=https://xxx@sentry.io/xxx

# Exchange API Keys (for master account - optional)
COINBASE_API_KEY=organizations/xxx/apiKeys/xxx
COINBASE_API_SECRET=-----BEGIN EC PRIVATE KEY-----
KRAKEN_MASTER_API_KEY=xxx
KRAKEN_MASTER_API_SECRET=xxx
```

---

## Database Setup

1. **Run migrations:**
```bash
# Initialize Alembic (if not already done)
alembic init alembic

# Create initial migration
alembic revision --autogenerate -m "Initial migration"

# Apply migrations
alembic upgrade head
```

2. **Or run init script:**
```bash
python init_database.py
```

---

## Monitoring & Logging

### CloudWatch (AWS)

```bash
# View logs
aws logs tail /aws/elasticbeanstalk/nija-production/var/log/eb-engine.log --follow
```

### Google Cloud Logging

```bash
# View logs
gcloud logging read "resource.type=cloud_run_revision" --limit 50
```

### Azure Monitor

```bash
# View logs
az webapp log tail --name nija-mobile-api --resource-group nija-rg
```

### Application Performance Monitoring

**Add Sentry for error tracking:**
```python
# Add to mobile_backend_server.py
import sentry_sdk
from sentry_sdk.integrations.flask import FlaskIntegration

sentry_sdk.init(
    dsn=os.getenv('SENTRY_DSN'),
    integrations=[FlaskIntegration()],
    environment=os.getenv('FLASK_ENV', 'development'),
    traces_sample_rate=1.0
)
```

---

## SSL/TLS Configuration

All cloud providers offer automatic SSL:

- **AWS**: Use AWS Certificate Manager (ACM) with ALB
- **GCP**: Cloud Run and Cloud Load Balancer auto-provision SSL
- **Azure**: App Service provides free SSL certificates
- **Railway**: Automatic SSL for all deployments

---

## Health Checks & Auto-Scaling

### AWS ALB Health Check
```json
{
  "HealthCheckPath": "/health",
  "HealthCheckIntervalSeconds": 30,
  "HealthCheckTimeoutSeconds": 5,
  "HealthyThresholdCount": 2,
  "UnhealthyThresholdCount": 3
}
```

### GCP Cloud Run Auto-Scaling
```yaml
apiVersion: serving.knative.dev/v1
kind: Service
metadata:
  name: nija-api
spec:
  template:
    metadata:
      annotations:
        autoscaling.knative.dev/minScale: "1"
        autoscaling.knative.dev/maxScale: "10"
        autoscaling.knative.dev/target: "80"
```

---

## Cost Estimates

### Railway (Recommended for Starter)
- **Free tier**: $0/month (500 hours)
- **Hobby**: $5/month (unlimited)
- **Pro**: $20/month (better resources)

### AWS (Production)
- **Elastic Beanstalk**: ~$25-50/month (t3.small)
- **ECS Fargate**: ~$40-80/month (2 tasks)
- **RDS PostgreSQL**: ~$15-30/month (db.t3.micro)

### GCP (Production)
- **Cloud Run**: ~$20-40/month (pay-per-use)
- **Cloud SQL**: ~$10-25/month (db-f1-micro)

### Azure (Production)
- **App Service**: ~$55/month (B1)
- **Azure Database**: ~$30/month (Basic tier)

---

## Next Steps

1. Choose a cloud provider based on your needs and budget
2. Set up database and Redis
3. Configure environment variables
4. Deploy backend API
5. Test all endpoints
6. Set up monitoring and alerts
7. Configure auto-scaling
8. Prepare for App Store submission

---

## Support

- Documentation: https://docs.nija.app
- GitHub Issues: https://github.com/dantelrharrell-debug/Nija/issues
- Email: support@nija.app
