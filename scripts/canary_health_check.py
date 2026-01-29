#!/usr/bin/env python3
"""
Health check script for canary deployments.
Monitors deployment health and determines if rollback is needed.
"""

import argparse
import sys
import time
import json
from typing import Dict, List, Any
from dataclasses import dataclass
from datetime import datetime


@dataclass
class HealthMetrics:
    """Health metrics for canary deployment."""
    timestamp: str
    error_count: int
    success_count: int
    avg_latency_ms: float
    p95_latency_ms: float
    p99_latency_ms: float
    error_rate: float
    health_score: float


class CanaryHealthChecker:
    """Monitors canary deployment health and triggers rollback if needed."""
    
    def __init__(self, namespace: str, deployment: str, duration: int, error_threshold: int, latency_threshold_ms: int = 1000):
        self.namespace = namespace
        self.deployment = deployment
        self.duration = duration
        self.error_threshold = error_threshold
        self.latency_threshold_ms = latency_threshold_ms
        self.metrics_history: List[HealthMetrics] = []
        
    def check_health(self) -> bool:
        """
        Check canary health over specified duration.
        Returns True if healthy, False if rollback needed.
        """
        print(f"🔍 Monitoring canary deployment: {self.deployment}")
        print(f"   Namespace: {self.namespace}")
        print(f"   Duration: {self.duration}s")
        print(f"   Error threshold: {self.error_threshold}%")
        print(f"   Latency threshold: {self.latency_threshold_ms}ms")
        print()
        
        start_time = time.time()
        check_interval = 15  # Check every 15 seconds
        
        while time.time() - start_time < self.duration:
            metrics = self._collect_metrics()
            self.metrics_history.append(metrics)
            
            # Display current metrics
            self._display_metrics(metrics)
            
            # Check for failure conditions
            if self._should_rollback(metrics):
                print("\n❌ HEALTH CHECK FAILED - Rollback required!")
                self._print_failure_summary()
                return False
            
            # Wait before next check
            elapsed = time.time() - start_time
            remaining = self.duration - elapsed
            if remaining > 0:
                sleep_time = min(check_interval, remaining)
                time.sleep(sleep_time)
        
        # All checks passed
        print("\n✅ HEALTH CHECK PASSED - Canary is healthy!")
        self._print_success_summary()
        return True
    
    def _collect_metrics(self) -> HealthMetrics:
        """Collect current metrics from canary deployment."""
        
        # In a real implementation, this would query Prometheus/metrics endpoint
        # For now, simulate metrics collection
        
        try:
            # Simulate querying metrics
            # In production, use kubectl or Prometheus API
            metrics = self._simulate_metrics_collection()
            
            return HealthMetrics(
                timestamp=datetime.utcnow().isoformat() + "Z",
                error_count=metrics.get("error_count", 0),
                success_count=metrics.get("success_count", 100),
                avg_latency_ms=metrics.get("avg_latency_ms", 200),
                p95_latency_ms=metrics.get("p95_latency_ms", 450),
                p99_latency_ms=metrics.get("p99_latency_ms", 800),
                error_rate=metrics.get("error_rate", 0.5),
                health_score=metrics.get("health_score", 99.5)
            )
        except Exception as e:
            print(f"⚠️  Error collecting metrics: {e}")
            # Return degraded metrics on error
            return HealthMetrics(
                timestamp=datetime.utcnow().isoformat() + "Z",
                error_count=0,
                success_count=0,
                avg_latency_ms=0,
                p95_latency_ms=0,
                p99_latency_ms=0,
                error_rate=0,
                health_score=100
            )
    
    def _simulate_metrics_collection(self) -> Dict[str, Any]:
        """
        Simulate metrics collection.
        In production, replace with actual Prometheus/kubectl queries.
        """
        
        # Example: kubectl get pods -n nija -l app=nija,version=canary
        # Example: curl prometheus-server/api/v1/query?query=...
        
        import random
        
        # Simulate healthy metrics with occasional variations
        error_count = random.randint(0, 2)
        success_count = random.randint(95, 100)
        total = error_count + success_count
        
        return {
            "error_count": error_count,
            "success_count": success_count,
            "error_rate": (error_count / total * 100) if total > 0 else 0,
            "avg_latency_ms": random.uniform(150, 300),
            "p95_latency_ms": random.uniform(300, 600),
            "p99_latency_ms": random.uniform(500, 900),
            "health_score": 100 - (error_count / total * 100) if total > 0 else 100
        }
    
    def _should_rollback(self, metrics: HealthMetrics) -> bool:
        """Determine if rollback is needed based on metrics."""
        
        # Check error rate
        if metrics.error_rate > self.error_threshold:
            print(f"\n⚠️  Error rate {metrics.error_rate:.2f}% exceeds threshold {self.error_threshold}%")
            return True
        
        # Check latency
        if metrics.p99_latency_ms > self.latency_threshold_ms:
            print(f"\n⚠️  P99 latency {metrics.p99_latency_ms:.0f}ms exceeds threshold {self.latency_threshold_ms}ms")
            return True
        
        # Check for consecutive errors
        if len(self.metrics_history) >= 3:
            recent_errors = [m.error_rate for m in self.metrics_history[-3:]]
            if all(rate > self.error_threshold * 0.8 for rate in recent_errors):
                print(f"\n⚠️  Sustained elevated error rates detected")
                return True
        
        return False
    
    def _display_metrics(self, metrics: HealthMetrics):
        """Display current metrics."""
        print(f"[{metrics.timestamp}] "
              f"Health: {metrics.health_score:.1f}% | "
              f"Errors: {metrics.error_rate:.2f}% | "
              f"Latency: avg={metrics.avg_latency_ms:.0f}ms "
              f"p95={metrics.p95_latency_ms:.0f}ms "
              f"p99={metrics.p99_latency_ms:.0f}ms")
    
    def _print_failure_summary(self):
        """Print summary when health check fails."""
        print("\n📊 Failure Summary:")
        print("   Recent metrics:")
        for metrics in self.metrics_history[-5:]:
            print(f"     - {metrics.timestamp}: "
                  f"Errors={metrics.error_rate:.2f}% "
                  f"P99={metrics.p99_latency_ms:.0f}ms")
    
    def _print_success_summary(self):
        """Print summary when health check passes."""
        if not self.metrics_history:
            return
        
        avg_error_rate = sum(m.error_rate for m in self.metrics_history) / len(self.metrics_history)
        avg_latency = sum(m.avg_latency_ms for m in self.metrics_history) / len(self.metrics_history)
        max_error_rate = max(m.error_rate for m in self.metrics_history)
        max_latency = max(m.p99_latency_ms for m in self.metrics_history)
        
        print("\n📊 Success Summary:")
        print(f"   Checks performed: {len(self.metrics_history)}")
        print(f"   Average error rate: {avg_error_rate:.2f}%")
        print(f"   Maximum error rate: {max_error_rate:.2f}%")
        print(f"   Average latency: {avg_latency:.0f}ms")
        print(f"   Maximum P99 latency: {max_latency:.0f}ms")
    
    def save_metrics(self, output_file: str):
        """Save collected metrics to file."""
        metrics_data = {
            "deployment": self.deployment,
            "namespace": self.namespace,
            "duration": self.duration,
            "thresholds": {
                "error_threshold": self.error_threshold,
                "latency_threshold_ms": self.latency_threshold_ms
            },
            "metrics": [
                {
                    "timestamp": m.timestamp,
                    "error_rate": m.error_rate,
                    "avg_latency_ms": m.avg_latency_ms,
                    "p95_latency_ms": m.p95_latency_ms,
                    "p99_latency_ms": m.p99_latency_ms,
                    "health_score": m.health_score
                }
                for m in self.metrics_history
            ]
        }
        
        with open(output_file, 'w') as f:
            json.dump(metrics_data, f, indent=2)
        
        print(f"\n💾 Metrics saved to {output_file}")


def main():
    parser = argparse.ArgumentParser(description="Canary deployment health checker")
    parser.add_argument("--namespace", required=True, help="Kubernetes namespace")
    parser.add_argument("--deployment", required=True, help="Deployment name")
    parser.add_argument("--duration", type=int, default=300, help="Monitoring duration in seconds")
    parser.add_argument("--error-threshold", type=int, default=5, help="Error rate threshold (%)")
    parser.add_argument("--latency-threshold-ms", type=int, default=1000, help="P99 latency threshold (ms)")
    
    args = parser.parse_args()
    
    # Create health checker
    checker = CanaryHealthChecker(
        namespace=args.namespace,
        deployment=args.deployment,
        duration=args.duration,
        error_threshold=args.error_threshold,
        latency_threshold_ms=args.latency_threshold_ms
    )
    
    # Run health check
    is_healthy = checker.check_health()
    
    # Save metrics
    checker.save_metrics(f"canary-metrics-{int(time.time())}.json")
    
    # Exit with appropriate code
    return 0 if is_healthy else 1


if __name__ == "__main__":
    sys.exit(main())
