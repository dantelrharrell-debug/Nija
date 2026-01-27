#!/bin/bash

# NIJA Kubernetes Quick Deploy Script
# Automates the deployment of the NIJA platform to Kubernetes

set -e

echo "🚀 NIJA Kubernetes Quick Deploy"
echo "================================"
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check prerequisites
echo "📋 Checking prerequisites..."

if ! command -v kubectl &> /dev/null; then
    echo -e "${RED}❌ kubectl not found. Please install kubectl first.${NC}"
    exit 1
fi

if ! command -v docker &> /dev/null; then
    echo -e "${RED}❌ docker not found. Please install Docker first.${NC}"
    exit 1
fi

echo -e "${GREEN}✅ Prerequisites met${NC}"
echo ""

# Generate secrets
echo "🔐 Generating secure secrets..."

POSTGRES_PASSWORD=$(openssl rand -base64 32)
REDIS_PASSWORD=$(openssl rand -base64 32)
JWT_SECRET=$(openssl rand -base64 64)
ENCRYPTION_KEY=$(python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())" 2>/dev/null || echo "GENERATE_MANUALLY")

echo -e "${GREEN}✅ Secrets generated${NC}"
echo ""

# Create secrets file
echo "📝 Creating secrets file..."

cat > k8s/base/secrets.yaml <<EOF
apiVersion: v1
kind: Secret
metadata:
  name: postgres-credentials
  namespace: nija-platform
type: Opaque
stringData:
  username: nija_user
  password: $POSTGRES_PASSWORD
---
apiVersion: v1
kind: Secret
metadata:
  name: redis-credentials
  namespace: nija-platform
type: Opaque
stringData:
  password: $REDIS_PASSWORD
---
apiVersion: v1
kind: Secret
metadata:
  name: jwt-secret
  namespace: nija-platform
type: Opaque
stringData:
  secret-key: $JWT_SECRET
---
apiVersion: v1
kind: Secret
metadata:
  name: nija-encryption-key
  namespace: nija-platform
type: Opaque
stringData:
  encryption-key: $ENCRYPTION_KEY
EOF

echo -e "${GREEN}✅ Secrets file created${NC}"
echo ""

# Check if user wants to proceed
echo -e "${YELLOW}⚠️  This will deploy NIJA to your Kubernetes cluster.${NC}"
echo "Current cluster context: $(kubectl config current-context)"
echo ""
read -p "Do you want to proceed? (yes/no): " -r
echo ""
if [[ ! $REPLY =~ ^[Yy](es)?$ ]]; then
    echo "Deployment cancelled."
    exit 0
fi

# Deploy to Kubernetes
echo "🚢 Deploying to Kubernetes..."

kubectl apply -k k8s/base/

echo -e "${GREEN}✅ Deployment initiated${NC}"
echo ""

# Wait for deployments to be ready
echo "⏳ Waiting for deployments to be ready..."

kubectl wait --for=condition=ready pod \
  -l app=postgres \
  -n nija-platform \
  --timeout=300s

kubectl wait --for=condition=ready pod \
  -l app=redis \
  -n nija-platform \
  --timeout=300s

kubectl wait --for=condition=ready pod \
  -l app=nija-api \
  -n nija-platform \
  --timeout=300s

kubectl wait --for=condition=ready pod \
  -l app=founder-dashboard \
  -n nija-platform \
  --timeout=300s

echo -e "${GREEN}✅ All pods are ready${NC}"
echo ""

# Get service information
echo "📊 Service Information:"
echo "======================"

kubectl get svc -n nija-platform

echo ""
echo -e "${GREEN}✅ Deployment complete!${NC}"
echo ""

# Get dashboard URL
DASHBOARD_IP=$(kubectl get svc founder-dashboard -n nija-platform -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null || echo "pending")

if [ "$DASHBOARD_IP" != "pending" ] && [ -n "$DASHBOARD_IP" ]; then
    echo -e "${GREEN}🎉 Founder Dashboard accessible at: http://$DASHBOARD_IP${NC}"
else
    echo -e "${YELLOW}⏳ Waiting for LoadBalancer IP...${NC}"
    echo "Run this command to check status:"
    echo "  kubectl get svc founder-dashboard -n nija-platform"
fi

echo ""
echo "📖 Next steps:"
echo "  1. Access the Founder Dashboard"
echo "  2. Generate alpha user invitation codes"
echo "  3. Configure Stripe API keys (optional)"
echo "  4. Monitor system: kubectl get all -n nija-platform"
echo ""

# Save credentials
echo "🔑 Credentials saved to: k8s/base/secrets.yaml"
echo -e "${RED}⚠️  IMPORTANT: Do NOT commit secrets.yaml to version control!${NC}"
echo ""
