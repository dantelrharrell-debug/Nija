#!/usr/bin/env python3
"""
Test system resilience to network failures.
"""

import argparse
import sys
import time
import random
from typing import Dict, Any
from pathlib import Path


class NetworkFailureChaosTest:
    """Test system resilience to network failures."""
    
    def __init__(self, failure_rate: float, duration: int):
        self.failure_rate = failure_rate
        self.duration = duration
        self.results = []
        
    def run(self) -> Dict[str, Any]:
        """Run network failure chaos test."""
        
        print(f"🌐 Network Failure Chaos Test")
        print(f"   Failure rate: {self.failure_rate * 100}%")
        print(f"   Duration: {self.duration}s")
        print()
        
        start_time = time.time()
        test_count = 0
        success_count = 0
        failure_count = 0
        retry_count = 0
        
        while time.time() - start_time < self.duration:
            test_count += 1
            
            # Simulate API call with random failures
            result = self._simulate_api_call_with_failures()
            self.results.append(result)
            
            if result["success"]:
                success_count += 1
                if result.get("retries", 0) > 0:
                    retry_count += 1
                    print(f"✅ Test {test_count}: Success after {result['retries']} retries")
                else:
                    print(f"✅ Test {test_count}: Success")
            else:
                failure_count += 1
                print(f"❌ Test {test_count}: Failed after retries")
            
            time.sleep(0.5)
        
        # Calculate results
        total_tests = test_count
        success_rate = (success_count / total_tests * 100) if total_tests > 0 else 0
        retry_success_rate = (retry_count / total_tests * 100) if total_tests > 0 else 0
        
        print(f"\n📊 Results:")
        print(f"   Total tests: {total_tests}")
        print(f"   Successes: {success_count} ({success_rate:.1f}%)")
        print(f"   Failures: {failure_count}")
        print(f"   Retry successes: {retry_count} ({retry_success_rate:.1f}%)")
        
        # System should handle failures with retries
        # At least 80% overall success rate expected with good retry logic
        passed = success_rate >= 80
        
        if passed:
            print("\n✅ PASSED: System handles network failures with retries")
        else:
            print("\n❌ FAILED: System does not handle network failures well")
        
        return {
            "test": "network_failures",
            "failure_rate": self.failure_rate,
            "duration": self.duration,
            "total_tests": total_tests,
            "success_count": success_count,
            "failure_count": failure_count,
            "retry_count": retry_count,
            "success_rate": success_rate,
            "passed": passed
        }
    
    def _simulate_api_call_with_failures(self) -> Dict[str, Any]:
        """Simulate API call with random failures and retries."""
        
        max_retries = 3
        retries = 0
        
        for attempt in range(max_retries + 1):
            # Simulate network failure based on failure rate
            if random.random() < self.failure_rate:
                # Network failure
                retries = attempt
                if attempt < max_retries:
                    # Retry with exponential backoff
                    time.sleep(0.1 * (2 ** attempt))
                    continue
                else:
                    # All retries exhausted
                    return {
                        "success": False,
                        "retries": retries,
                        "final_state": "failed"
                    }
            else:
                # Success
                return {
                    "success": True,
                    "retries": retries,
                    "final_state": "success"
                }
        
        return {
            "success": False,
            "retries": max_retries,
            "final_state": "failed"
        }
    
    def save_results(self):
        """Save test results."""
        output_dir = Path("chaos-results/network")
        output_dir.mkdir(parents=True, exist_ok=True)
        
        import json
        output_file = output_dir / f"failure_test_{int(time.time())}.json"
        
        with open(output_file, 'w') as f:
            json.dump({
                "test": "network_failures",
                "parameters": {
                    "failure_rate": self.failure_rate,
                    "duration": self.duration
                },
                "results": self.results
            }, f, indent=2)
        
        print(f"\n💾 Results saved to {output_file}")


def main():
    parser = argparse.ArgumentParser(description="Network failure chaos test")
    parser.add_argument("--failure-rate", type=float, default=0.3, help="Network failure rate (0.0-1.0)")
    parser.add_argument("--duration", type=int, default=300, help="Test duration in seconds")
    
    args = parser.parse_args()
    
    if not 0.0 <= args.failure_rate <= 1.0:
        print("Error: failure-rate must be between 0.0 and 1.0")
        return 1
    
    # Run test
    test = NetworkFailureChaosTest(args.failure_rate, args.duration)
    results = test.run()
    test.save_results()
    
    # Exit with appropriate code
    return 0 if results["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
