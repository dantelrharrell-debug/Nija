# Advanced Security & Deployment Features

This document describes the advanced security and deployment features implemented in NIJA.

## Overview

NIJA now implements five advanced security and deployment capabilities:

1. **Continuous Threat Modeling** - Automated security analysis and threat detection
2. **Runtime Container Sandboxing** - Container security policies and isolation
3. **Canary Deployments + Automated Rollback** - Progressive deployment with health checks
4. **Chaos Security Testing** - Chaos engineering for security resilience
5. **Zero-Trust CI Runner Isolation** - Secure CI/CD pipeline with network isolation

## 1. Continuous Threat Modeling

### Description
Automated threat modeling runs daily to identify and assess security threats across the entire application.

### Components
- **Threat Model Generator** (`scripts/generate_threat_model.py`)
  - Analyzes code structure and dependencies
  - Maps attack surface (APIs, webhooks, database)
  - Identifies threats using STRIDE methodology
  - Calculates risk scores and mitigation status

- **Security Score Calculator** (`scripts/calculate_security_score.py`)
  - Combines threat model with vulnerability scans
  - Generates overall security score (0-100)
  - Provides actionable recommendations

- **GitHub Workflow** (`.github/workflows/threat-modeling.yml`)
  - Runs daily at 3am UTC
  - OWASP Dependency Check integration
  - Supply chain analysis with pip-audit
  - Attack surface mapping
  - Generates consolidated threat reports

### Usage

```bash
# Manual threat model generation
python scripts/generate_threat_model.py --output security-reports/threat-model.json

# Calculate security score
python scripts/calculate_security_score.py \
  --threat-model security-reports/threat-model.json \
  --dependency-report reports/dependency-check-report.json \
  --output security-reports/security-score.json
```

### Threat Categories (STRIDE)

- **Spoofing**: User impersonation, fake webhooks
- **Tampering**: Code injection, MITM attacks
- **Repudiation**: Trade denial claims
- **Information Disclosure**: API key leaks, strategy exposure
- **Denial of Service**: API flooding, connection exhaustion
- **Elevation of Privilege**: Unauthorized admin access, container escape

### Security Score Grading

- **A (90-100)**: Excellent security posture
- **B (80-89)**: Good security with minor improvements needed
- **C (70-79)**: Acceptable but requires attention
- **D (60-69)**: Poor security, immediate action required
- **F (<60)**: Critical security issues, do not deploy

## 2. Runtime Container Sandboxing

### Description
Multi-layered container security using seccomp, AppArmor, and security best practices.

### Security Layers

#### Layer 1: Dockerfile Security
- Non-root user (`nija:1000`)
- Read-only application code
- Minimal base image (Python 3.11 slim)
- No unnecessary packages
- Health checks

#### Layer 2: Seccomp Profile
- Restricts system calls to safe subset
- Blocks dangerous operations (kernel modules, raw I/O)
- Profile: `security/seccomp-profile.json`

#### Layer 3: AppArmor Profile
- Mandatory access control for files and networks
- Denies write access to code files
- Allows only necessary network operations
- Profile: `security/apparmor-profile.conf`

#### Layer 4: Capability Dropping
- Drops ALL Linux capabilities
- No privilege escalation possible
- Minimal permissions for operation

#### Layer 5: Resource Limits
- CPU limits (2 cores max)
- Memory limits (2GB max)
- Prevents resource exhaustion

### Docker Compose Security

```yaml
# Run as non-root
user: "1000:1000"

# Read-only root filesystem
read_only: true

# Drop all capabilities
cap_drop:
  - ALL

# Security options
security_opt:
  - no-new-privileges:true
  - seccomp=security/seccomp-profile.json
```

### Kubernetes Security

See `k8s/security/` for:
- Pod Security Policies
- Security Context Constraints
- Network Policies
- Resource Quotas and Limits

## 3. Canary Deployments + Automated Rollback

### Description
Progressive deployment strategy with automatic rollback on health check failures.

### Deployment Flow

1. **Build & Scan**
   - Build Docker image
   - Security scan with Trivy
   - Sign image with Cosign
   - Upload to registry

2. **Deploy Canary**
   - Deploy to canary pods (1 replica)
   - Initial traffic: 10%
   - Health monitoring begins

3. **Progressive Rollout**
   - Gradual traffic increase: 10% → 25% → 50% → 75% → 100%
   - Health checks at each stage
   - 60-second soak time between stages

4. **Automated Rollback**
   - Triggers on:
     - Error rate > 5%
     - P99 latency > 1000ms
     - Failed health checks
   - Instant traffic revert to stable
   - Canary pods removed

5. **Finalization**
   - Promote canary to stable
   - Update stable deployment
   - Remove canary resources

### Health Check Criteria

- **Error Rate**: <5% errors allowed
- **Latency**: P99 <1000ms
- **Success Rate**: >95% requests successful
- **Availability**: Pods must be ready

### Usage

```bash
# Trigger canary deployment
gh workflow run canary-deployment.yml \
  -f environment=staging \
  -f canary_percentage=10

# Manual health check
python scripts/canary_health_check.py \
  --namespace nija \
  --deployment nija-canary \
  --duration 300 \
  --error-threshold 5
```

### Traffic Splitting (Istio)

```yaml
# 10% canary, 90% stable
- destination:
    host: nija-stable
  weight: 90
- destination:
    host: nija-canary
  weight: 10
```

## 4. Chaos Security Testing

### Description
Automated chaos engineering tests to verify system resilience against security-relevant failures.

### Test Categories

#### Network Chaos
- **Latency Injection**: 1000ms latency simulation
- **Network Failures**: 30% packet loss
- **Timeout Testing**: Connection timeout handling
- **Script**: `scripts/chaos/test_network_latency.py`

#### Authentication Chaos
- **Expired Tokens**: Token expiration handling
- **Invalid Credentials**: Credential validation
- **Token Refresh**: Refresh mechanism testing
- **Concurrent Auth**: Load testing auth system
- **Script**: `scripts/chaos/test_invalid_credentials.py`

#### API Rate Limit Chaos
- **Rate Limit Flooding**: 1000 req/s simulation
- **Burst Traffic**: 10,000 req burst
- **Throttling Verification**: Rate limit enforcement

#### Database Chaos
- **Connection Failures**: 20% connection failure rate
- **Slow Queries**: 5000ms query delays
- **Transaction Rollback**: Rollback handling

### Running Chaos Tests

```bash
# Run all chaos tests
gh workflow run chaos-security-testing.yml

# Run specific test
gh workflow run chaos-security-testing.yml \
  -f chaos_type=network \
  -f duration_seconds=300

# Run locally
python scripts/chaos/test_network_latency.py --latency-ms 1000 --duration 300
```

### Success Criteria

Tests pass when:
- System handles failures gracefully (no crashes)
- Error rates stay within acceptable bounds
- Proper error messages returned
- Automatic retry/recovery mechanisms work
- No data corruption or security breaches

## 5. Zero-Trust CI Runner Isolation

### Description
Secure CI/CD pipeline with network isolation, ephemeral runners, and minimal permissions.

### Security Principles

#### Principle 1: Least Privilege
- Minimal GitHub permissions per job
- No persistent credentials
- Short-lived tokens only
- No cross-job credential sharing

#### Principle 2: Network Isolation
- Egress policy: Block by default
- Whitelist only necessary endpoints
- No access to internal networks
- Harden-Runner enforcement

#### Principle 3: Ephemeral Everything
- Ephemeral runners (destroyed after use)
- Ephemeral artifacts (7-day retention)
- No persistent state between runs
- Clean environment per execution

#### Principle 4: Artifact Signing
- SHA256 signatures for all artifacts
- Verification before use
- Tamper detection
- Build provenance tracking

### Workflow Structure

```yaml
permissions:
  contents: read        # Read-only code access
  packages: write       # Only for build job
  id-token: write      # OIDC authentication
  security-events: write # Only for security scans
```

### Network Egress Control

```yaml
- uses: step-security/harden-runner@v2
  with:
    egress-policy: block
    allowed-endpoints: >
      api.github.com:443
      pypi.org:443
      files.pythonhosted.org:443
```

### Artifact Verification

```bash
# Sign artifacts
sha256sum file.py > file.py.sha256

# Verify artifacts
sha256sum -c file.py.sha256
```

### Isolated Test Execution

- Tests run in separate jobs
- Matrix strategy for isolation
- No network for unit tests
- Resource limits enforced
- Timeout protection

## Configuration

### Environment Variables

```bash
# Required for canary deployments
KUBE_CONFIG=<base64-encoded-kubeconfig>

# Required for threat modeling
NVD_API_KEY=<nvd-api-key>  # Optional but recommended

# Required for container registry
GITHUB_TOKEN=<automatically-provided>
```

### Secrets Management

All secrets stored in GitHub Secrets:
- Never committed to repository
- Encrypted at rest
- Access logged and audited
- Rotated regularly

## Monitoring & Alerts

### Threat Model Alerts

- Daily threat model generation
- Email on critical threats
- GitHub Security Advisories created
- Slack/Discord notifications (optional)

### Canary Deployment Alerts

- Real-time health monitoring
- Rollback notifications
- Deployment success/failure alerts
- Metrics dashboards

### Chaos Test Alerts

- Weekly test execution
- Failure notifications
- Trend analysis
- Resilience scoring

## Best Practices

### Security

1. **Regular Scans**: Run security scans on every PR
2. **Threat Review**: Review threat model monthly
3. **Update Dependencies**: Keep dependencies current
4. **Rotate Secrets**: Rotate credentials quarterly
5. **Audit Logs**: Review security logs weekly

### Deployment

1. **Test Canaries**: Always test in staging first
2. **Monitor Metrics**: Watch health metrics closely
3. **Gradual Rollout**: Never skip traffic stages
4. **Quick Rollback**: Be ready to rollback instantly
5. **Document Changes**: Keep deployment log

### Chaos Testing

1. **Run Regularly**: Weekly chaos tests minimum
2. **Expand Coverage**: Add new failure scenarios
3. **Fix Issues**: Address failures immediately
4. **Learn & Improve**: Use results to harden system
5. **Automate Everything**: No manual chaos testing

## Troubleshooting

### Threat Model Fails

- Check OWASP Dependency Check installation
- Verify NVD API key configuration
- Review threat model script logs
- Check for new dependencies

### Canary Rollback

- Review health check logs
- Check error rates in monitoring
- Verify latency metrics
- Review application logs
- Test in staging environment

### Chaos Test Failures

- Review specific test logs
- Check for actual bugs vs test issues
- Verify test thresholds are reasonable
- Run tests in isolation
- Check for environmental issues

### CI Isolation Issues

- Verify network egress rules
- Check allowed endpoints list
- Review harden-runner logs
- Verify artifact signatures
- Check permissions configuration

## Metrics & KPIs

### Security Metrics

- **Security Score**: Target >90
- **Mitigation Coverage**: Target >95%
- **Critical Vulnerabilities**: Target 0
- **Mean Time to Remediate**: <48 hours

### Deployment Metrics

- **Deployment Success Rate**: >95%
- **Rollback Rate**: <5%
- **Canary Health Score**: >98%
- **Mean Time to Deploy**: <30 minutes

### Resilience Metrics

- **Chaos Test Pass Rate**: >90%
- **System Availability**: >99.9%
- **Error Recovery Time**: <5 minutes
- **Incident Rate**: <1 per week

## Future Enhancements

1. **Advanced Threat Detection**
   - ML-based anomaly detection
   - Real-time threat intelligence
   - Automated response playbooks

2. **Blue-Green Deployments**
   - Instant traffic switching
   - Zero-downtime deployments
   - A/B testing capabilities

3. **Enhanced Chaos Testing**
   - Distributed tracing analysis
   - Performance degradation testing
   - Multi-region failure simulation

4. **SBOM Generation**
   - Software Bill of Materials
   - Supply chain transparency
   - License compliance checking

## References

- [STRIDE Threat Modeling](https://docs.microsoft.com/en-us/azure/security/develop/threat-modeling-tool-threats)
- [Seccomp Security Profiles](https://docs.docker.com/engine/security/seccomp/)
- [AppArmor Documentation](https://gitlab.com/apparmor/apparmor/-/wikis/Documentation)
- [Kubernetes Security Best Practices](https://kubernetes.io/docs/concepts/security/pod-security-standards/)
- [Chaos Engineering Principles](https://principlesofchaos.org/)
- [Zero Trust Architecture](https://www.nist.gov/publications/zero-trust-architecture)

## Support

For questions or issues:
1. Check this documentation first
2. Review workflow logs in GitHub Actions
3. Check security reports in artifacts
4. Open GitHub issue with details
5. Contact security team for critical issues

---

**Last Updated**: January 29, 2026  
**Version**: 1.0  
**Status**: ✅ Implemented and Active
