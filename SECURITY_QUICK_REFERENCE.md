# Quick Reference: Advanced Security & Deployment

## 🚀 Quick Start

### Running Threat Modeling

```bash
# Generate threat model
python scripts/generate_threat_model.py --output security-reports/threat-model.json

# Calculate security score
python scripts/calculate_security_score.py \
  --threat-model security-reports/threat-model.json \
  --output security-reports/security-score.json

# Check for critical threats
python scripts/check_critical_threats.py \
  --security-score security-reports/security-score.json \
  --threshold 70
```

### Running Chaos Tests

```bash
# Network latency test
python scripts/chaos/test_network_latency.py --latency-ms 1000 --duration 60

# Network failure test
python scripts/chaos/test_network_failure.py --failure-rate 0.3 --duration 60

# Auth failure test
python scripts/chaos/test_invalid_credentials.py
```

### Canary Deployment

```bash
# Trigger canary deployment via GitHub Actions
gh workflow run canary-deployment.yml \
  -f environment=staging \
  -f canary_percentage=10

# Monitor canary health (manual)
python scripts/canary_health_check.py \
  --namespace nija \
  --deployment nija-canary \
  --duration 300 \
  --error-threshold 5
```

### Docker with Security Hardening

```bash
# Build with security
docker build -t nija-secure .

# Run with full security stack
docker run --rm \
  --user 1000:1000 \
  --read-only \
  --cap-drop=ALL \
  --security-opt=no-new-privileges:true \
  --security-opt=seccomp=security/seccomp-profile.json \
  --tmpfs /tmp \
  --tmpfs /app/cache \
  --tmpfs /app/logs \
  nija-secure

# Or use docker-compose
docker-compose up
```

### Kubernetes Security

```bash
# Apply security policies
kubectl apply -f k8s/security/

# Deploy with canary
kubectl apply -f k8s/canary/deployment-canary.yaml

# Check security context
kubectl get pod -n nija -o jsonpath='{.items[0].spec.securityContext}'
```

## 📊 GitHub Workflows

### Manual Triggers

```bash
# Threat modeling
gh workflow run threat-modeling.yml

# Chaos testing
gh workflow run chaos-security-testing.yml -f chaos_type=network

# Canary deployment
gh workflow run canary-deployment.yml -f environment=staging

# Zero-trust CI (automatic on PR)
```

## 🛡️ Security Checks

### Verify Container Security

```bash
# Check user
docker run nija-secure id
# Expected: uid=1000(nija) gid=1000(nija)

# Try to write to code (should fail)
docker run nija-secure touch /app/bot/test.py
# Expected: Permission denied

# Check capabilities
docker run nija-secure capsh --print
# Expected: No capabilities
```

### Test Seccomp Profile

```bash
# Allowed syscall
docker run --security-opt seccomp=security/seccomp-profile.json \
  nija-secure python -c "import os; print(os.getpid())"
# Expected: Success

# Blocked syscall (mount)
docker run --security-opt seccomp=security/seccomp-profile.json \
  nija-secure mount
# Expected: Operation not permitted
```

## 📈 Monitoring

### Check Security Score

```bash
# View latest score
cat security-reports/security-score.json | jq '.overall_score'

# View grade
cat security-reports/security-score.json | jq '.grade'

# View recommendations
cat security-reports/security-score.json | jq '.recommendations[]'
```

### View Chaos Test Results

```bash
# Latest results
ls -lt chaos-results/*/

# View specific test
cat chaos-results/network/latency_test_*.json | jq
```

### Canary Metrics

```bash
# View latest metrics
cat canary-metrics-*.json | jq '.metrics'
```

## 🔧 Troubleshooting

### Threat Modeling Issues

```bash
# Check if reports exist
ls -la security-reports/

# View threat model
cat security-reports/threat-model.json | jq '.risk_assessment'

# Debug mode
python scripts/generate_threat_model.py --output /tmp/test.json 2>&1 | head -20
```

### Canary Deployment Issues

```bash
# Check canary pod status
kubectl get pods -n nija -l version=canary

# View canary logs
kubectl logs -n nija -l version=canary --tail=100

# Check traffic split
kubectl get virtualservice -n nija nija-traffic-split -o yaml
```

### Chaos Test Failures

```bash
# View test output
python scripts/chaos/test_network_latency.py --duration 10

# Check results directory
ls -la chaos-results/

# View specific failure
cat chaos-results/network/*.json | jq 'select(.passed == false)'
```

## 🎯 Common Commands

### Daily Security Check

```bash
# Run full security analysis
python scripts/generate_threat_model.py --output security-reports/threat-model.json && \
python scripts/calculate_security_score.py \
  --threat-model security-reports/threat-model.json \
  --output security-reports/security-score.json && \
python scripts/check_critical_threats.py \
  --security-score security-reports/security-score.json
```

### Weekly Chaos Test

```bash
# Run all chaos tests
for test in scripts/chaos/test_*.py; do
  echo "Running $test"
  python "$test" || echo "FAILED: $test"
done

# Generate report
python scripts/generate_chaos_report.py \
  --results-dir chaos-results \
  --output CHAOS_TEST_REPORT.md
```

### Pre-Deployment Checklist

```bash
# 1. Security score check
python scripts/calculate_security_score.py \
  --threat-model security-reports/threat-model.json \
  --output security-reports/security-score.json

# 2. Build with security
docker build -t nija-deploy:latest .

# 3. Security scan
docker run --rm \
  aquasecurity/trivy image \
  nija-deploy:latest

# 4. Test in staging
gh workflow run canary-deployment.yml -f environment=staging

# 5. Monitor canary
python scripts/canary_health_check.py \
  --namespace nija-staging \
  --deployment nija-canary \
  --duration 300
```

## 📚 Documentation Links

- [Complete Guide](ADVANCED_SECURITY_DEPLOYMENT.md)
- [Security Profiles](security/README.md)
- [Dockerfile](Dockerfile)
- [Docker Compose](docker-compose.yml)
- [Kubernetes Configs](k8s/)

## 🆘 Support

1. Check logs: `docker logs <container>` or `kubectl logs <pod>`
2. Review documentation: `ADVANCED_SECURITY_DEPLOYMENT.md`
3. Check workflow runs: GitHub Actions tab
4. View security reports: `security-reports/` directory
5. Test scripts locally before running in CI

## 💡 Best Practices

- ✅ Run threat modeling daily
- ✅ Run chaos tests weekly
- ✅ Use canary deployments for production
- ✅ Monitor security scores
- ✅ Review and address findings promptly
- ✅ Keep security profiles updated
- ✅ Test in staging before production
- ✅ Document security exceptions

---

**Quick Reference v1.0** | Updated: 2026-01-29
