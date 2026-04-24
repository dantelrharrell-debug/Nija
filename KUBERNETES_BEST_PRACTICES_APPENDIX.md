# Kubernetes Best Practices Appendix
## Health Checks, Metrics, Alerting, and SLOs for NIJA Trading Bot

This appendix provides production-ready Kubernetes configurations, Prometheus metrics, alerting rules, and Service Level Objectives (SLOs) for the NIJA trading bot infrastructure.

---

## Table of Contents

1. [Health Check Configuration](#health-check-configuration)
2. [Prometheus Metrics](#prometheus-metrics)
3. [ServiceMonitor Configuration](#servicemonitor-configuration)
4. [Alerting Rules](#alerting-rules)
5. [Service Level Objectives (SLOs)](#service-level-objectives-slos)
6. [Grafana Dashboards](#grafana-dashboards)
7. [PodDisruptionBudget](#poddisruptionbudget)
8. [Resource Quotas](#resource-quotas)

---

## Health Check Configuration

### Recommended Probe Settings

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: nija-trading-bot
  namespace: nija-platform
spec:
  replicas: 3
  template:
    spec:
      containers:
      - name: nija
        image: nija-bot:latest
        ports:
        - containerPort: 8080
          name: http
          protocol: TCP
        
        # Liveness Probe - Detects deadlocked processes
        livenessProbe:
          httpGet:
            path: /healthz
            port: http
            scheme: HTTP
          initialDelaySeconds: 30      # Wait for startup
          periodSeconds: 10             # Check every 10s
          timeoutSeconds: 5             # 5s timeout
          successThreshold: 1           # 1 success = healthy
          failureThreshold: 3           # 3 failures = restart (30s total)
        
        # Readiness Probe - Detects if service can handle traffic
        readinessProbe:
          httpGet:
            path: /ready
            port: http
            scheme: HTTP
          initialDelaySeconds: 10       # Start checking sooner
          periodSeconds: 5              # Check more frequently
          timeoutSeconds: 3             # Faster timeout
          successThreshold: 1           # 1 success = ready
          failureThreshold: 3           # 3 failures = not ready (15s total)
        
        # Startup Probe - For slow-starting containers (optional)
        startupProbe:
          httpGet:
            path: /healthz
            port: http
            scheme: HTTP
          initialDelaySeconds: 0
          periodSeconds: 10
          timeoutSeconds: 3
          successThreshold: 1
          failureThreshold: 30          # 5 minutes for startup (30 * 10s)
        
        resources:
          requests:
            cpu: 500m
            memory: 1Gi
          limits:
            cpu: 2000m
            memory: 4Gi
```

### Why These Settings?

**Liveness Probe**:
- `initialDelaySeconds: 30` - Gives service time to initialize
- `periodSeconds: 10` - Balance between responsiveness and overhead
- `failureThreshold: 3` - Prevents false positives from temporary issues
- Only restarts if process is actually dead/deadlocked

**Readiness Probe**:
- `initialDelaySeconds: 10` - Start checking readiness earlier
- `periodSeconds: 5` - More frequent checks for faster traffic routing
- `failureThreshold: 3` - Quick removal from load balancer (15s)
- Doesn't restart on configuration errors (returns 503)

**Startup Probe** (Optional):
- Allows up to 5 minutes for slow startup
- Prevents liveness probe from killing slow-starting containers
- Use if containers take >30s to start

---

## Prometheus Metrics

### Available Metrics

The `/metrics` endpoint exposes the following Prometheus metrics:

#### Health and Availability Metrics

```promql
# Service is up and running
nija_up{} gauge
  1 = service is alive
  0 = service is down

# Service is ready to handle traffic
nija_ready{} gauge
  1 = ready to accept traffic
  0 = not ready

# Configuration is valid
nija_configuration_valid{} gauge
  1 = configuration valid
  0 = configuration invalid
```

#### Configuration Error Metrics (SLO-Critical)

```promql
# Time spent in configuration error state (seconds)
nija_configuration_error_duration_seconds{} gauge
  Tracks how long service has been blocked by configuration errors
  
# State transition count
nija_readiness_state_changes_total{} counter
  Number of times readiness state has changed
  High values indicate flapping
```

#### Uptime and Availability Metrics

```promql
# Service uptime
nija_uptime_seconds{} gauge
  Total time service has been running

# Time spent in ready state
nija_ready_time_seconds{} counter
  Cumulative time service was ready

# Time spent in not-ready state
nija_not_ready_time_seconds{} counter
  Cumulative time service was not ready
```

#### Exchange Connectivity Metrics

```promql
# Number of exchanges connected
nija_exchanges_connected{} gauge

# Number of exchanges expected
nija_exchanges_expected{} gauge
```

#### Trading Metrics

```promql
# Trading is enabled
nija_trading_enabled{} gauge
  1 = trading enabled
  0 = trading disabled

# Active positions
nija_active_positions{} gauge
  Current number of open positions

# Total errors
nija_error_count_total{} counter
  Total number of errors encountered
```

### Example PromQL Queries

```promql
# Availability rate (percentage of time service was ready)
100 * rate(nija_ready_time_seconds[5m]) / rate(nija_uptime_seconds[5m])

# Configuration error rate
rate(nija_configuration_error_duration_seconds[5m]) > 0

# Exchange connectivity ratio
nija_exchanges_connected / nija_exchanges_expected

# Error rate
rate(nija_error_count_total[5m])

# State flapping detection (high transition rate)
rate(nija_readiness_state_changes_total[5m]) > 0.1
```

---

## ServiceMonitor Configuration

For Prometheus Operator to scrape metrics:

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: nija-trading-bot
  namespace: nija-platform
  labels:
    app: nija-trading-bot
    prometheus: kube-prometheus
spec:
  selector:
    matchLabels:
      app: nija-trading-bot
  endpoints:
  - port: http
    path: /metrics
    interval: 30s
    scrapeTimeout: 10s
    scheme: http
```

---

## Alerting Rules

### PrometheusRule Configuration

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: nija-trading-bot-alerts
  namespace: nija-platform
  labels:
    prometheus: kube-prometheus
    role: alert-rules
spec:
  groups:
  - name: nija-trading-bot.rules
    interval: 30s
    rules:
    
    # CRITICAL: Service is down
    - alert: NijaTradingBotDown
      expr: up{job="nija-trading-bot"} == 0
      for: 2m
      labels:
        severity: critical
        component: nija-trading-bot
      annotations:
        summary: "NIJA Trading Bot is down"
        description: "NIJA Trading Bot has been down for more than 2 minutes. Pod: {{ $labels.pod }}"
        runbook_url: "https://docs.nija.io/runbooks/service-down"
    
    # CRITICAL: Configuration error blocking trading
    - alert: NijaBlo ckedByConfigurationError
      expr: nija_configuration_error_duration_seconds > 300
      for: 5m
      labels:
        severity: critical
        component: nija-trading-bot
        slo: availability
      annotations:
        summary: "NIJA blocked by configuration error for {{ $value | humanizeDuration }}"
        description: "NIJA has been in configuration error state for {{ $value | humanizeDuration }}. This impacts availability SLO. Immediate action required."
        runbook_url: "https://docs.nija.io/runbooks/configuration-error"
    
    # WARNING: Configuration error detected
    - alert: NijaConfigurationError
      expr: nija_configuration_valid == 0
      for: 1m
      labels:
        severity: warning
        component: nija-trading-bot
      annotations:
        summary: "NIJA configuration is invalid"
        description: "NIJA configuration validation failed. Check credentials and environment variables. Pod: {{ $labels.pod }}"
        runbook_url: "https://docs.nija.io/runbooks/configuration-validation"
    
    # CRITICAL: Not ready for extended period
    - alert: NijaNotReady
      expr: nija_ready == 0
      for: 10m
      labels:
        severity: critical
        component: nija-trading-bot
        slo: availability
      annotations:
        summary: "NIJA not ready for {{ $value | humanizeDuration }}"
        description: "NIJA has been not ready for over 10 minutes. Check readiness probe and exchange connectivity. Pod: {{ $labels.pod }}"
        runbook_url: "https://docs.nija.io/runbooks/not-ready"
    
    # WARNING: Exchange connectivity degraded
    - alert: NijaExchangeConnectivityDegraded
      expr: (nija_exchanges_connected / nija_exchanges_expected) < 0.5
      for: 5m
      labels:
        severity: warning
        component: nija-trading-bot
      annotations:
        summary: "NIJA exchange connectivity degraded ({{ $value | humanizePercentage }})"
        description: "Less than 50% of expected exchanges are connected. Connected: {{ $labels.connected }}, Expected: {{ $labels.expected }}. Pod: {{ $labels.pod }}"
        runbook_url: "https://docs.nija.io/runbooks/exchange-connectivity"
    
    # CRITICAL: No exchanges connected
    - alert: NijaNoExchangesConnected
      expr: nija_exchanges_connected == 0 and nija_exchanges_expected > 0
      for: 3m
      labels:
        severity: critical
        component: nija-trading-bot
      annotations:
        summary: "NIJA has no exchanges connected"
        description: "All exchange connections have failed. Trading cannot occur. Pod: {{ $labels.pod }}"
        runbook_url: "https://docs.nija.io/runbooks/no-exchanges"
    
    # WARNING: High error rate
    - alert: NijaHighErrorRate
      expr: rate(nija_error_count_total[5m]) > 0.1
      for: 5m
      labels:
        severity: warning
        component: nija-trading-bot
      annotations:
        summary: "NIJA experiencing high error rate ({{ $value | humanize }} errors/sec)"
        description: "Error rate is elevated. Investigate logs for root cause. Pod: {{ $labels.pod }}"
        runbook_url: "https://docs.nija.io/runbooks/high-error-rate"
    
    # WARNING: Readiness state flapping
    - alert: NijaReadinessStateFlapping
      expr: rate(nija_readiness_state_changes_total[10m]) > 0.1
      for: 10m
      labels:
        severity: warning
        component: nija-trading-bot
      annotations:
        summary: "NIJA readiness state is flapping"
        description: "Readiness state is changing frequently ({{ $value | humanize }} changes/sec). This may indicate instability. Pod: {{ $labels.pod }}"
        runbook_url: "https://docs.nija.io/runbooks/state-flapping"
    
    # INFO: Trading disabled
    - alert: NijaTradingDisabled
      expr: nija_trading_enabled == 0
      for: 15m
      labels:
        severity: info
        component: nija-trading-bot
      annotations:
        summary: "NIJA trading is disabled"
        description: "Trading has been disabled for over 15 minutes. This may be intentional. Pod: {{ $labels.pod }}"
        runbook_url: "https://docs.nija.io/runbooks/trading-disabled"
```

---

## Service Level Objectives (SLOs)

### Availability SLO: 99.9% (Three Nines)

**Definition**: Service is ready to handle trading requests 99.9% of the time over a 30-day window.

**Error Budget**: 43 minutes of downtime per month

**Measurement**:
```promql
# Availability calculation (percentage of time ready)
100 * (
  sum(rate(nija_ready_time_seconds[30d]))
  /
  sum(rate(nija_uptime_seconds[30d]))
)

# Error budget remaining (minutes)
(0.001 * 30 * 24 * 60) - (
  sum(increase(nija_not_ready_time_seconds[30d])) / 60
)
```

**SLO PrometheusRule**:
```yaml
- alert: NijaAvailabilitySLOViolation
  expr: |
    100 * (
      sum(rate(nija_ready_time_seconds[30d]))
      /
      sum(rate(nija_uptime_seconds[30d]))
    ) < 99.9
  for: 5m
  labels:
    severity: critical
    slo: availability
    slo_target: "99.9"
  annotations:
    summary: "NIJA Availability SLO violated ({{ $value | humanizePercentage }})"
    description: "Service availability is below 99.9% SLO target. Current: {{ $value | humanizePercentage }}. Error budget may be exhausted."

- alert: NijaAvailabilityErrorBudgetCritical
  expr: |
    (0.001 * 30 * 24 * 60) - (
      sum(increase(nija_not_ready_time_seconds[30d])) / 60
    ) < 10
  for: 1m
  labels:
    severity: warning
    slo: availability
  annotations:
    summary: "NIJA Availability error budget critical ({{ $value | humanize }} minutes remaining)"
    description: "Less than 10 minutes of error budget remaining for this 30-day window. Avoid further incidents."
```

### Configuration Error Duration SLO: < 5 minutes

**Definition**: Configuration errors must be resolved within 5 minutes of detection.

**Measurement**:
```promql
# Maximum configuration error duration
max(nija_configuration_error_duration_seconds)

# Configuration errors exceeding 5 minutes
count(nija_configuration_error_duration_seconds > 300)
```

**SLO PrometheusRule**:
```yaml
- alert: NijaConfigurationErrorSLOViolation
  expr: nija_configuration_error_duration_seconds > 300
  for: 1m
  labels:
    severity: critical
    slo: configuration_recovery
    slo_target: "5m"
  annotations:
    summary: "NIJA Configuration Error SLO violated ({{ $value | humanizeDuration }})"
    description: "Configuration error has persisted for {{ $value | humanizeDuration }}, exceeding 5-minute SLO. Immediate intervention required."
```

### Exchange Connectivity SLO: ≥ 80%

**Definition**: At least 80% of expected exchanges must be connected at all times.

**Measurement**:
```promql
# Exchange connectivity percentage
100 * (nija_exchanges_connected / nija_exchanges_expected)
```

**SLO PrometheusRule**:
```yaml
- alert: NijaExchangeConnectivitySLOViolation
  expr: (nija_exchanges_connected / nija_exchanges_expected) < 0.8
  for: 5m
  labels:
    severity: warning
    slo: exchange_connectivity
    slo_target: "80"
  annotations:
    summary: "NIJA Exchange Connectivity SLO violated ({{ $value | humanizePercentage }})"
    description: "Exchange connectivity is below 80% SLO target. Current: {{ $value | humanizePercentage }}."
```

---

## Grafana Dashboards

### Main Dashboard JSON

```json
{
  "dashboard": {
    "title": "NIJA Trading Bot - Health & SLOs",
    "panels": [
      {
        "title": "Service Status",
        "type": "stat",
        "targets": [{
          "expr": "nija_up"
        }],
        "thresholds": {
          "mode": "absolute",
          "steps": [
            { "value": 0, "color": "red" },
            { "value": 1, "color": "green" }
          ]
        }
      },
      {
        "title": "Availability SLO (30d)",
        "type": "gauge",
        "targets": [{
          "expr": "100 * (sum(rate(nija_ready_time_seconds[30d])) / sum(rate(nija_uptime_seconds[30d])))"
        }],
        "thresholds": {
          "mode": "absolute",
          "steps": [
            { "value": 0, "color": "red" },
            { "value": 99.0, "color": "yellow" },
            { "value": 99.9, "color": "green" }
          ]
        }
      },
      {
        "title": "Configuration Error Duration",
        "type": "graph",
        "targets": [{
          "expr": "nija_configuration_error_duration_seconds",
          "legendFormat": "{{pod}}"
        }],
        "alert": {
          "conditions": [{
            "evaluator": { "params": [300], "type": "gt" },
            "operator": { "type": "and" },
            "query": { "params": ["A", "5m", "now"] },
            "reducer": { "type": "avg" },
            "type": "query"
          }]
        }
      },
      {
        "title": "Exchange Connectivity",
        "type": "graph",
        "targets": [
          {
            "expr": "nija_exchanges_connected",
            "legendFormat": "Connected"
          },
          {
            "expr": "nija_exchanges_expected",
            "legendFormat": "Expected"
          }
        ]
      },
      {
        "title": "Error Budget Remaining (30d)",
        "type": "stat",
        "targets": [{
          "expr": "(0.001 * 30 * 24 * 60) - (sum(increase(nija_not_ready_time_seconds[30d])) / 60)"
        }],
        "unit": "m"
      }
    ]
  }
}
```

---

## PodDisruptionBudget

Prevent too many pods from being disrupted simultaneously:

```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: nija-trading-bot-pdb
  namespace: nija-platform
spec:
  minAvailable: 2  # Always keep 2 pods running
  selector:
    matchLabels:
      app: nija-trading-bot
```

---

## Resource Quotas

Ensure fair resource allocation:

```yaml
apiVersion: v1
kind: ResourceQuota
metadata:
  name: nija-platform-quota
  namespace: nija-platform
spec:
  hard:
    requests.cpu: "20"
    requests.memory: 40Gi
    limits.cpu: "40"
    limits.memory: 80Gi
    pods: "50"
    services: "20"
```

---

## Summary

This appendix provides:

✅ **Production-ready health check configuration**
- Separate liveness, readiness, and startup probes
- Tuned timeouts and thresholds
- Prevents false restarts

✅ **Comprehensive Prometheus metrics**
- Health and availability metrics
- Configuration error duration tracking
- Exchange connectivity monitoring
- Trading status metrics

✅ **Actionable alerting rules**
- Critical alerts for service down, configuration errors
- Warning alerts for degraded states
- SLO violation alerts

✅ **Service Level Objectives**
- 99.9% availability SLO
- <5 minute configuration error recovery SLO
- ≥80% exchange connectivity SLO

✅ **Operational best practices**
- PodDisruptionBudgets for high availability
- Resource quotas for fair allocation
- Grafana dashboards for visibility

This configuration ensures NIJA operates as a **production-grade, observable, and reliable** trading platform.
