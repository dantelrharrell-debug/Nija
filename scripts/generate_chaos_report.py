#!/usr/bin/env python3
"""
Generate consolidated chaos test report.
"""

import argparse
import json
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, Any


class ChaosReportGenerator:
    """Generate consolidated chaos test report."""
    
    def __init__(self, results_dir: str):
        self.results_dir = Path(results_dir)
        
    def generate(self) -> str:
        """Generate consolidated markdown report."""
        
        print("📝 Generating Chaos Test Report...")
        
        # Collect all test results
        network_results = self._collect_results("network-chaos-results")
        auth_results = self._collect_results("auth-chaos-results")
        api_results = self._collect_results("api-chaos-results")
        db_results = self._collect_results("database-chaos-results")
        
        # Generate markdown report
        report = self._generate_markdown({
            "network": network_results,
            "auth": auth_results,
            "api": api_results,
            "database": db_results
        })
        
        print("✅ Report generated")
        
        return report
    
    def _collect_results(self, subdir: str) -> list:
        """Collect all JSON results from a subdirectory."""
        
        results = []
        results_path = self.results_dir / subdir
        
        if not results_path.exists():
            print(f"⚠️  No results found in {subdir}")
            return results
        
        for json_file in results_path.glob("*.json"):
            try:
                with open(json_file) as f:
                    data = json.load(f)
                    results.append(data)
            except Exception as e:
                print(f"⚠️  Could not load {json_file}: {e}")
        
        return results
    
    def _generate_markdown(self, all_results: Dict[str, list]) -> str:
        """Generate markdown report."""
        
        timestamp = datetime.utcnow().isoformat() + "Z"
        
        lines = [
            "# 🧪 Chaos Security Testing Report",
            "",
            f"**Generated**: {timestamp}",
            "",
            "## Executive Summary",
            ""
        ]
        
        # Calculate overall statistics
        total_tests = 0
        passed_tests = 0
        
        for category, results in all_results.items():
            total_tests += len(results)
            passed_tests += sum(1 for r in results if r.get("passed", False))
        
        pass_rate = (passed_tests / total_tests * 100) if total_tests > 0 else 0
        
        lines.extend([
            f"**Total Tests**: {total_tests}",
            f"**Passed**: {passed_tests}",
            f"**Failed**: {total_tests - passed_tests}",
            f"**Pass Rate**: {pass_rate:.1f}%",
            ""
        ])
        
        if pass_rate >= 90:
            lines.append("✅ **Excellent** - System demonstrates strong resilience")
        elif pass_rate >= 75:
            lines.append("✅ **Good** - System handles most failure scenarios well")
        elif pass_rate >= 60:
            lines.append("⚠️ **Acceptable** - Some failure scenarios need improvement")
        else:
            lines.append("❌ **Poor** - Significant resilience issues detected")
        
        lines.extend(["", "---", ""])
        
        # Network Chaos Results
        if all_results["network"]:
            lines.extend([
                "## 🌐 Network Chaos Tests",
                ""
            ])
            
            for result in all_results["network"]:
                test_name = result.get("test", "Unknown")
                passed = result.get("passed", False)
                emoji = "✅" if passed else "❌"
                
                lines.append(f"### {emoji} {test_name.replace('_', ' ').title()}")
                
                if "success_rate" in result:
                    lines.append(f"- Success Rate: {result['success_rate']:.1f}%")
                if "timeout_rate" in result:
                    lines.append(f"- Timeout Rate: {result['timeout_rate']:.1f}%")
                
                lines.append("")
        
        # Auth Chaos Results
        if all_results["auth"]:
            lines.extend([
                "## 🔐 Authentication Chaos Tests",
                ""
            ])
            
            for result in all_results["auth"]:
                if "scenarios" in result:
                    for scenario, passed in result["scenarios"].items():
                        emoji = "✅" if passed else "❌"
                        lines.append(f"- {emoji} {scenario}")
                
                lines.append("")
        
        # API Chaos Results
        if all_results["api"]:
            lines.extend([
                "## 🔌 API Rate Limit Chaos Tests",
                ""
            ])
            
            for result in all_results["api"]:
                test_name = result.get("test", "Unknown")
                passed = result.get("passed", False)
                emoji = "✅" if passed else "❌"
                
                lines.append(f"- {emoji} {test_name.replace('_', ' ').title()}")
            
            lines.append("")
        
        # Database Chaos Results
        if all_results["database"]:
            lines.extend([
                "## 💾 Database Chaos Tests",
                ""
            ])
            
            for result in all_results["database"]:
                test_name = result.get("test", "Unknown")
                passed = result.get("passed", False)
                emoji = "✅" if passed else "❌"
                
                lines.append(f"- {emoji} {test_name.replace('_', ' ').title()}")
            
            lines.append("")
        
        # Recommendations
        lines.extend([
            "## 💡 Recommendations",
            ""
        ])
        
        if pass_rate < 90:
            lines.append("1. Review failed tests and implement improvements")
            lines.append("2. Strengthen error handling and retry logic")
            lines.append("3. Add circuit breakers for external dependencies")
            lines.append("4. Improve timeout handling")
        else:
            lines.append("1. Maintain current resilience patterns")
            lines.append("2. Continue regular chaos testing")
            lines.append("3. Expand test coverage to new scenarios")
        
        lines.extend([
            "",
            "---",
            "",
            "*Report generated automatically by NIJA Chaos Testing System*"
        ])
        
        return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Generate chaos test report")
    parser.add_argument("--results-dir", required=True, help="Directory containing chaos test results")
    parser.add_argument("--output", required=True, help="Output markdown file")
    
    args = parser.parse_args()
    
    # Generate report
    generator = ChaosReportGenerator(args.results_dir)
    report = generator.generate()
    
    # Save report
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, 'w') as f:
        f.write(report)
    
    print(f"\n✅ Report saved to {output_path}")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
