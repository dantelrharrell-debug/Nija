# NIJA Kubernetes Deployment Guide

## Overview

This directory contains Kubernetes manifests for deploying the NIJA trading platform in production.

## Architecture

The NIJA platform consists of the following components:

```
┌─────────────────────────────────────────────────────┐
│                  Kubernetes Cluster                  │
│                                                      │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────┐│
│  │   Founder    │  │   NIJA API   │  │  Trading   ││
│  │  Dashboard   │  │   Gateway    │  │  Workers   ││
│  │  (Flask)     │  │  (FastAPI)   │  │  (Python)  ││
│  └──────────────┘  └──────────────┘  └────────────┘│
│         │                  │                 │      │
│         └──────────────────┼─────────────────┘      │
│                            │                        │
│         ┌──────────────────┴─────────────┐         │
│         │                                 │         │
│  ┌──────▼──────┐                  ┌──────▼──────┐ │
│  │  PostgreSQL │                  │    Redis    │ │
│  │ (StatefulSet)│                  │ (Deployment)│ │
│  └─────────────┘                  └─────────────┘ │
└─────────────────────────────────────────────────────┘
```

## Components

### 1. Namespace (`base/namespace.yaml`)
- Creates `nija-platform` namespace
- Defines resource quotas and limits
- Ensures fair resource distribution

### 2. PostgreSQL (`components/postgres/statefulset.yaml`)
- StatefulSet deployment for data persistence
- 20Gi persistent volume
- Health checks and readiness probes
- Auto-initialized with schema

### 3. Redis (`components/redis/deployment.yaml`)
- Deployment with persistent storage
- 5Gi persistent volume
- Password-protected
- Used for caching and session management

### 4. API Gateway (`components/api/deployment.yaml`)
- FastAPI-based REST API
- Horizontal auto-scaling (3-10 replicas)
- Health checks and monitoring
- Connects to PostgreSQL and Redis

### 5. Founder Dashboard (`components/dashboard/deployment.yaml`)
- Flask-based control dashboard
- LoadBalancer service for external access
- Real-time monitoring and controls
- 2 replicas for high availability

## Prerequisites

Before deploying, ensure you have:

1. **Kubernetes Cluster** (1.24+)
   - Managed cluster (GKE, EKS, AKS) or
   - Self-hosted cluster (k3s, kubeadm, etc.)

2. **kubectl** configured to access your cluster
   ```bash
   kubectl version --client
   kubectl cluster-info
   ```

3. **Kustomize** (built into kubectl 1.14+)
   ```bash
   kubectl kustomize --help
   ```

4. **Docker Images** built and pushed
   ```bash
   docker build -t your-registry/nija-api:latest -f Dockerfile.api .
   docker build -t your-registry/nija-dashboard:latest -f Dockerfile .
   docker push your-registry/nija-api:latest
   docker push your-registry/nija-dashboard:latest
   ```

## Quick Start

### 1. Update Secrets

**IMPORTANT**: Before deploying, update the secrets in `base/secrets.yaml`:

```bash
# Generate secure random passwords
POSTGRES_PASSWORD=$(openssl rand -base64 32)
REDIS_PASSWORD=$(openssl rand -base64 32)
JWT_SECRET=$(openssl rand -base64 64)
ENCRYPTION_KEY=$(python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")

# Create secrets.yaml with actual values
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
```

### 2. Update Image References

Edit `k8s/base/kustomization.yaml` to point to your Docker registry:

```yaml
images:
- name: nija-api
  newName: your-registry/nija-api
  newTag: latest
- name: nija-dashboard
  newName: your-registry/nija-dashboard
  newTag: latest
```

### 3. Deploy to Kubernetes

```bash
# Deploy entire platform
kubectl apply -k k8s/base/

# Verify deployment
kubectl get all -n nija-platform

# Check pod status
kubectl get pods -n nija-platform -w
```

### 4. Access the Dashboard

```bash
# Get LoadBalancer IP (may take a few minutes)
kubectl get svc founder-dashboard -n nija-platform

# Access dashboard at:
# http://<EXTERNAL-IP>
```

## Configuration

### Environment-Specific Overlays

Use Kustomize overlays for different environments:

```bash
# Development
kubectl apply -k k8s/overlays/dev/

# Staging
kubectl apply -k k8s/overlays/staging/

# Production
kubectl apply -k k8s/overlays/prod/
```

### Resource Limits

Adjust resource requests/limits in component manifests:

```yaml
resources:
  requests:
    cpu: 500m      # 0.5 CPU cores
    memory: 1Gi    # 1 GiB RAM
  limits:
    cpu: 2000m     # 2 CPU cores
    memory: 4Gi    # 4 GiB RAM
```

### Auto-Scaling

API gateway auto-scales based on CPU/memory:

```yaml
minReplicas: 3
maxReplicas: 10
metrics:
- type: Resource
  resource:
    name: cpu
    target:
      averageUtilization: 70
```

## Monitoring

### Check Logs

```bash
# View API logs
kubectl logs -f deployment/nija-api -n nija-platform

# View Dashboard logs
kubectl logs -f deployment/founder-dashboard -n nija-platform

# View PostgreSQL logs
kubectl logs -f statefulset/postgres -n nija-platform
```

### Port Forwarding (for testing)

```bash
# Access API locally
kubectl port-forward svc/nija-api 8000:8000 -n nija-platform

# Access Dashboard locally
kubectl port-forward svc/founder-dashboard 5001:80 -n nija-platform

# Access PostgreSQL locally
kubectl port-forward svc/postgres 5432:5432 -n nija-platform
```

## Backup and Recovery

### Database Backup

```bash
# Backup PostgreSQL
kubectl exec -n nija-platform postgres-0 -- \
  pg_dump -U nija_user nija > backup-$(date +%Y%m%d).sql

# Restore from backup
kubectl exec -i -n nija-platform postgres-0 -- \
  psql -U nija_user nija < backup-20260127.sql
```

### Persistent Volume Snapshots

Use your cloud provider's snapshot functionality:

```bash
# GKE example
gcloud compute disks snapshot <disk-name> \
  --snapshot-names=nija-backup-$(date +%Y%m%d)
```

## Scaling

### Manual Scaling

```bash
# Scale API replicas
kubectl scale deployment/nija-api --replicas=5 -n nija-platform

# Scale Dashboard replicas
kubectl scale deployment/founder-dashboard --replicas=3 -n nija-platform
```

### Horizontal Pod Autoscaler

HPA is configured for the API gateway. Monitor with:

```bash
kubectl get hpa -n nija-platform
```

## Troubleshooting

### Pods Not Starting

```bash
# Describe pod for events
kubectl describe pod <pod-name> -n nija-platform

# Check container logs
kubectl logs <pod-name> -n nija-platform

# Check previous container logs (if crashed)
kubectl logs <pod-name> -n nija-platform --previous
```

### Database Connection Issues

```bash
# Test PostgreSQL connection
kubectl exec -it -n nija-platform postgres-0 -- psql -U nija_user -d nija

# Check service DNS
kubectl run -it --rm debug --image=busybox --restart=Never -n nija-platform \
  -- nslookup postgres
```

### Resource Constraints

```bash
# Check resource usage
kubectl top pods -n nija-platform
kubectl top nodes

# Check resource quotas
kubectl describe resourcequota -n nija-platform
```

## Security Best Practices

1. **Secrets Management**
   - Never commit `secrets.yaml` with real values
   - Use Sealed Secrets or External Secrets Operator in production
   - Rotate secrets regularly

2. **Network Policies**
   - Implement network policies to restrict pod-to-pod communication
   - Use egress rules to control outbound traffic

3. **RBAC**
   - Create service accounts with minimal permissions
   - Use RBAC to control access to resources

4. **Image Security**
   - Scan images for vulnerabilities
   - Use specific image tags (not `latest`)
   - Pull from private registry

## Cleanup

To remove the entire deployment:

```bash
# Delete all resources
kubectl delete -k k8s/base/

# Verify deletion
kubectl get all -n nija-platform
```

**Warning**: This will delete all data, including databases!

## Support

For issues or questions:
- Check logs: `kubectl logs <pod-name> -n nija-platform`
- Review events: `kubectl get events -n nija-platform`
- Consult main documentation: [README.md](../README.md)

---

**Version**: 1.0  
**Last Updated**: January 27, 2026  
**Status**: ✅ Production Ready
