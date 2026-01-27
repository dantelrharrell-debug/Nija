# Global Risk Engine + Production Infrastructure - Quick Start

This guide helps you quickly get started with the new NIJA production infrastructure.

## What's New? 🎉

The NIJA platform now includes:

1. **🎛️ Founder Control Dashboard** - Monitor and control the entire platform
2. **☸️ Kubernetes Deployment** - Production-grade container orchestration
3. **👥 Alpha User Onboarding** - Streamlined user acquisition system
4. **💰 SaaS Monetization** - Subscription billing with Stripe

## Quick Start Options

### Option 1: Run Demo (No Deployment)

Test all components locally without Kubernetes:

```bash
# Install dependencies
pip install -r requirements.txt

# Run integration demo
python examples/platform_integration_demo.py
```

This will demonstrate:
- Generating invitation codes
- User onboarding workflow
- Subscription management
- Risk monitoring
- Dashboard overview

### Option 2: Deploy to Kubernetes

Deploy the full platform to your Kubernetes cluster:

```bash
# Prerequisites: kubectl, docker, kubernetes cluster

# Quick deploy (automated)
./scripts/deploy_k8s.sh

# Manual deploy
kubectl apply -k k8s/base/

# Check status
kubectl get all -n nija-platform

# Get dashboard URL
kubectl get svc founder-dashboard -n nija-platform
```

### Option 3: Run Founder Dashboard Locally

Run just the Founder Dashboard:

```bash
# Set environment variables
export DATABASE_URL="postgresql://user:pass@localhost:5432/nija"
export REDIS_URL="redis://localhost:6379/0"
export JWT_SECRET_KEY="your-secret-key"
export PORT=5001

# Start dashboard
python founder_dashboard.py

# Access at http://localhost:5001
```

## Key Components

### 1. Founder Dashboard

**File**: `founder_dashboard.py`

Access comprehensive platform monitoring:

```bash
# Get overview
curl http://localhost:5001/api/founder/overview

# Get all users
curl http://localhost:5001/api/founder/users

# Get system health
curl http://localhost:5001/api/founder/health

# Get revenue metrics
curl http://localhost:5001/api/founder/revenue
```

### 2. Alpha Onboarding

**File**: `alpha_onboarding.py`

Manage user onboarding:

```python
from alpha_onboarding import get_onboarding_system

system = get_onboarding_system()

# Generate invitation
inv = system.generate_invitation_code("user@example.com", tier="alpha")

# Register user
success, error, user_id = system.register_user(
    invitation_code=inv.code,
    email="user@example.com",
    password_hash="hashed"
)

# Track progress
status = system.get_onboarding_status(user_id)
print(f"Progress: {status.get_progress_percent()}%")
```

### 3. Monetization Engine

**File**: `monetization_engine.py`

Manage subscriptions and billing:

```python
from monetization_engine import get_monetization_engine, SubscriptionTier

engine = get_monetization_engine(stripe_api_key="sk_test_...")

# Create subscription
success, error, sub = engine.create_subscription(
    user_id="user_123",
    tier=SubscriptionTier.PRO,
    trial_days=14
)

# Track usage
engine.track_usage("user_123", "trades_executed", 1)

# Get revenue metrics
revenue = engine.calculate_revenue_metrics()
print(f"MRR: ${revenue['monthly_recurring_revenue']}")
```

### 4. Kubernetes Deployment

**Directory**: `k8s/`

Production Kubernetes manifests:

```bash
k8s/
├── base/
│   ├── namespace.yaml       # Namespace and quotas
│   ├── secrets.yaml         # Secrets (DO NOT COMMIT)
│   └── kustomization.yaml   # Kustomize config
├── components/
│   ├── postgres/           # PostgreSQL StatefulSet
│   ├── redis/              # Redis Deployment
│   ├── api/                # API Gateway
│   └── dashboard/          # Founder Dashboard
└── README.md               # Detailed K8s guide
```

## Architecture Overview

```
┌─────────────────────────────────────────┐
│        Founder Dashboard (Flask)        │
│  Monitoring, Controls, User Management  │
└───────────────┬─────────────────────────┘
                │
    ┌───────────┼───────────┐
    │           │           │
    ▼           ▼           ▼
┌─────────┐ ┌─────────┐ ┌──────────┐
│ Alpha   │ │Monetize │ │  Global  │
│Onboard  │ │ Engine  │ │   Risk   │
└─────────┘ └─────────┘ └──────────┘
                │
        ┌───────┴────────┐
        │                │
        ▼                ▼
  ┌──────────┐     ┌──────────┐
  │PostgreSQL│     │  Redis   │
  └──────────┘     └──────────┘
```

## Subscription Tiers

| Tier | Monthly | Max Positions | Max Brokers | Features |
|------|---------|---------------|-------------|----------|
| Free | $0 | 3 | 1 | Basic trading |
| Basic | $29.99 | 10 | 2 | Advanced strategies |
| Pro | $99.99 | 50 | Unlimited | API access, analytics |
| Enterprise | $499.99 | Unlimited | Unlimited | Custom development |
| Alpha | $0 | 50 | 5 | Free Pro access |

## API Endpoints

### Founder Dashboard

```
GET  /api/health                         - Health check
GET  /api/founder/overview               - Platform overview
GET  /api/founder/users                  - All users
GET  /api/founder/users/<id>             - User details
POST /api/founder/users/<id>/approve     - Approve alpha user
GET  /api/founder/health                 - System health
GET  /api/founder/risk/events            - Risk events
POST /api/founder/emergency/shutdown     - Emergency stop
GET  /api/founder/revenue                - Revenue metrics
```

## Environment Variables

### Required

```bash
# Database
DATABASE_URL=postgresql://user:pass@localhost:5432/nija

# Redis
REDIS_URL=redis://localhost:6379/0

# Security
JWT_SECRET_KEY=<your-256-bit-key>
NIJA_ENCRYPTION_KEY=<your-fernet-key>

# Application
PORT=5001
LOG_LEVEL=INFO
UPDATE_INTERVAL=5

# Optional: Monetization
STRIPE_API_KEY=sk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
```

### Generate Secure Keys

```bash
# PostgreSQL password
openssl rand -base64 32

# Redis password
openssl rand -base64 32

# JWT secret
openssl rand -base64 64

# Fernet encryption key
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

## Testing

### Run Integration Demo

```bash
python examples/platform_integration_demo.py
```

### Test Individual Components

```bash
# Test onboarding
python -c "
from alpha_onboarding import get_onboarding_system
system = get_onboarding_system()
inv = system.generate_invitation_code('test@example.com')
print('Invitation:', inv.code)
"

# Test monetization
python -c "
from monetization_engine import get_monetization_engine
engine = get_monetization_engine()
for tier in engine.get_all_pricing():
    print(f'{tier.tier.value}: \${tier.monthly_price}/mo')
"

# Test dashboard (requires services running)
curl http://localhost:5001/api/health
```

## Monitoring

### Kubernetes

```bash
# Check pod status
kubectl get pods -n nija-platform

# View logs
kubectl logs -f deployment/founder-dashboard -n nija-platform

# Check resource usage
kubectl top pods -n nija-platform

# Port forward for local access
kubectl port-forward svc/founder-dashboard 5001:80 -n nija-platform
```

### Dashboard

Access the Founder Dashboard to monitor:
- User metrics
- Trading activity
- Risk events
- System health
- Revenue

## Next Steps

1. **Deploy Infrastructure**
   ```bash
   ./scripts/deploy_k8s.sh
   ```

2. **Configure Stripe** (optional)
   - Create Stripe account
   - Get API keys
   - Set `STRIPE_API_KEY` environment variable

3. **Generate Invitation Codes**
   ```python
   from alpha_onboarding import get_onboarding_system
   system = get_onboarding_system()
   inv = system.generate_invitation_code("alpha@user.com", tier="alpha")
   print(f"Send this code to user: {inv.code}")
   ```

4. **Onboard Alpha Users**
   - Send invitation codes
   - Users register at `/onboard`
   - Approve via Founder Dashboard

5. **Monitor Platform**
   - Access Founder Dashboard
   - Monitor risk events
   - Track revenue growth

## Troubleshooting

### Common Issues

**Pods not starting**:
```bash
kubectl describe pod <pod-name> -n nija-platform
kubectl logs <pod-name> -n nija-platform
```

**Database connection failed**:
```bash
# Test connection
kubectl exec -it postgres-0 -n nija-platform -- psql -U nija_user -d nija
```

**Dashboard not accessible**:
```bash
# Check service
kubectl get svc founder-dashboard -n nija-platform

# Port forward
kubectl port-forward svc/founder-dashboard 5001:80 -n nija-platform
```

## Documentation

- **Complete Guide**: [GLOBAL_RISK_ENGINE_IMPLEMENTATION.md](GLOBAL_RISK_ENGINE_IMPLEMENTATION.md)
- **Kubernetes Guide**: [k8s/README.md](k8s/README.md)
- **Architecture**: [MULTI_USER_PLATFORM_ARCHITECTURE.md](MULTI_USER_PLATFORM_ARCHITECTURE.md)
- **Infrastructure**: [INFRASTRUCTURE_IMPLEMENTATION_SUMMARY.md](INFRASTRUCTURE_IMPLEMENTATION_SUMMARY.md)

## Support

For questions or issues:
1. Check documentation in `*.md` files
2. Run demo: `python examples/platform_integration_demo.py`
3. View logs: `kubectl logs <pod-name> -n nija-platform`
4. Review architecture diagrams in documentation

---

**Version**: 1.0  
**Last Updated**: January 27, 2026  
**Status**: ✅ Production Ready
