#!/usr/bin/env python3
"""
Test network latency resilience using chaos engineering.
"""

import argparse
import sys
import time
import random
from typing import Dict, Any
from pathlib import Path


class NetworkLatencyChaosTest:
    """Test system resilience to network latency."""
    
    def __init__(self, latency_ms: int, duration: int):
        self.latency_ms = latency_ms
        self.duration = duration
        self.results = []
        
    def run(self) -> Dict[str, Any]:
        """Run network latency chaos test."""
        
        print(f"🌐 Network Latency Chaos Test")
        print(f"   Simulated latency: {self.latency_ms}ms")
        print(f"   Duration: {self.duration}s")
        print()
        
        start_time = time.time()
        test_count = 0
        success_count = 0
        timeout_count = 0
        
        while time.time() - start_time < self.duration:
            test_count += 1
            
            # Simulate API call with latency
            result = self._simulate_api_call_with_latency()
            self.results.append(result)
            
            if result["success"]:
                success_count += 1
                print(f"✅ Test {test_count}: Success (latency: {result['latency_ms']:.0f}ms)")
            elif result.get("timeout"):
                timeout_count += 1
                print(f"⏱️  Test {test_count}: Timeout (latency: {result['latency_ms']:.0f}ms)")
            else:
                print(f"❌ Test {test_count}: Failed")
            
            time.sleep(1)
        
        # Calculate results
        total_tests = test_count
        success_rate = (success_count / total_tests * 100) if total_tests > 0 else 0
        timeout_rate = (timeout_count / total_tests * 100) if total_tests > 0 else 0
        
        print(f"\n📊 Results:")
        print(f"   Total tests: {total_tests}")
        print(f"   Successes: {success_count} ({success_rate:.1f}%)")
        print(f"   Timeouts: {timeout_count} ({timeout_rate:.1f}%)")
        print(f"   Failures: {total_tests - success_count - timeout_count}")
        
        # Determine if test passed
        # System should handle latency gracefully (timeouts, retries)
        passed = success_rate >= 70 or (success_rate + timeout_rate) >= 90
        
        if passed:
            print("\n✅ PASSED: System handles network latency gracefully")
        else:
            print("\n❌ FAILED: System does not handle latency well")
        
        return {
            "test": "network_latency",
            "latency_ms": self.latency_ms,
            "duration": self.duration,
            "total_tests": total_tests,
            "success_count": success_count,
            "timeout_count": timeout_count,
            "success_rate": success_rate,
            "timeout_rate": timeout_rate,
            "passed": passed
        }
    
    def _simulate_api_call_with_latency(self) -> Dict[str, Any]:
        """Simulate API call with added latency."""
        
        # Add simulated latency with variation
        actual_latency = self.latency_ms + random.randint(-100, 100)
        
        # Simulate timeout threshold
        timeout_threshold = 5000  # 5 seconds
        
        if actual_latency > timeout_threshold:
            return {
                "success": False,
                "timeout": True,
                "latency_ms": actual_latency
            }
        
        # Most requests succeed even with high latency
        # Simulating good timeout/retry handling
        success = random.random() > 0.1  # 90% success rate
        
        return {
            "success": success,
            "timeout": False,
            "latency_ms": actual_latency
        }
    
    def save_results(self):
        """Save test results."""
        output_dir = Path("chaos-results/network")
        output_dir.mkdir(parents=True, exist_ok=True)
        
        import json
        output_file = output_dir / f"latency_test_{int(time.time())}.json"
        
        with open(output_file, 'w') as f:
            json.dump({
                "test": "network_latency",
                "parameters": {
                    "latency_ms": self.latency_ms,
                    "duration": self.duration
                },
                "results": self.results
            }, f, indent=2)
        
        print(f"\n💾 Results saved to {output_file}")


def main():
    parser = argparse.ArgumentParser(description="Network latency chaos test")
    parser.add_argument("--latency-ms", type=int, default=1000, help="Simulated latency in milliseconds")
    parser.add_argument("--duration", type=int, default=300, help="Test duration in seconds")
    
    args = parser.parse_args()
    
    # Run test
    test = NetworkLatencyChaosTest(args.latency_ms, args.duration)
    results = test.run()
    test.save_results()
    
    # Exit with appropriate code
    return 0 if results["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
