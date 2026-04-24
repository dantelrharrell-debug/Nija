#!/usr/bin/env python3
"""
Calculate security score based on threat model and vulnerability scans.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, Any


class SecurityScoreCalculator:
    """Calculate overall security score."""
    
    def __init__(self):
        self.scores = {}
        
    def calculate(self, dependency_report: str, threat_model: str) -> Dict[str, Any]:
        """Calculate comprehensive security score."""
        
        print("🔒 Calculating Security Score...")
        
        # Load reports
        threat_data = self._load_json(threat_model) if threat_model else {}
        dependency_data = self._load_json(dependency_report) if dependency_report else {}
        
        # Calculate component scores
        threat_score = self._calculate_threat_score(threat_data)
        dependency_score = self._calculate_dependency_score(dependency_data)
        
        # Calculate overall score (0-100, higher is better)
        overall_score = (threat_score * 0.6) + (dependency_score * 0.4)
        
        result = {
            "overall_score": round(overall_score, 2),
            "grade": self._get_grade(overall_score),
            "component_scores": {
                "threat_mitigation": round(threat_score, 2),
                "dependency_security": round(dependency_score, 2)
            },
            "recommendations": self._generate_recommendations(threat_data, dependency_data)
        }
        
        # Display results
        self._display_results(result)
        
        return result
    
    def _calculate_threat_score(self, threat_data: Dict[str, Any]) -> float:
        """Calculate score based on threat mitigation."""
        
        if not threat_data or "risk_assessment" not in threat_data:
            return 50.0  # Neutral score if no data
        
        risk_assessment = threat_data["risk_assessment"]
        mitigation_pct = risk_assessment.get("mitigation_percentage", 0)
        
        # Score is based on mitigation percentage
        return mitigation_pct
    
    def _calculate_dependency_score(self, dependency_data: Dict[str, Any]) -> float:
        """Calculate score based on dependency vulnerabilities."""
        
        # If no vulnerabilities found, perfect score
        if not dependency_data:
            return 100.0
        
        # Count vulnerabilities by severity
        critical = dependency_data.get("vulnerabilities", {}).get("critical", 0)
        high = dependency_data.get("vulnerabilities", {}).get("high", 0)
        medium = dependency_data.get("vulnerabilities", {}).get("medium", 0)
        low = dependency_data.get("vulnerabilities", {}).get("low", 0)
        
        # Calculate penalty based on severity
        penalty = (critical * 20) + (high * 10) + (medium * 5) + (low * 2)
        
        # Start with 100 and subtract penalties
        score = max(0, 100 - penalty)
        
        return score
    
    def _get_grade(self, score: float) -> str:
        """Convert score to letter grade."""
        if score >= 90:
            return "A"
        elif score >= 80:
            return "B"
        elif score >= 70:
            return "C"
        elif score >= 60:
            return "D"
        else:
            return "F"
    
    def _generate_recommendations(self, threat_data: Dict, dependency_data: Dict) -> list:
        """Generate security recommendations."""
        
        recommendations = []
        
        # Check threat mitigation
        if threat_data and "risk_assessment" in threat_data:
            mitigation_pct = threat_data["risk_assessment"].get("mitigation_percentage", 0)
            if mitigation_pct < 90:
                recommendations.append("Improve threat mitigation coverage - currently at {:.1f}%".format(mitigation_pct))
        
        # Check dependency vulnerabilities
        if dependency_data:
            vulns = dependency_data.get("vulnerabilities", {})
            if vulns.get("critical", 0) > 0:
                recommendations.append("CRITICAL: Update dependencies with critical vulnerabilities immediately")
            if vulns.get("high", 0) > 0:
                recommendations.append("Update dependencies with high severity vulnerabilities")
        
        # General recommendations
        if not recommendations:
            recommendations.append("Maintain current security posture with regular scans")
        
        return recommendations
    
    def _display_results(self, result: Dict[str, Any]):
        """Display security score results."""
        
        print(f"\n{'='*60}")
        print(f"🛡️  SECURITY SCORE REPORT")
        print(f"{'='*60}")
        print(f"\nOverall Score: {result['overall_score']}/100 (Grade: {result['grade']})")
        print(f"\nComponent Scores:")
        print(f"  - Threat Mitigation: {result['component_scores']['threat_mitigation']}/100")
        print(f"  - Dependency Security: {result['component_scores']['dependency_security']}/100")
        
        if result["recommendations"]:
            print(f"\n📋 Recommendations:")
            for i, rec in enumerate(result["recommendations"], 1):
                print(f"  {i}. {rec}")
        
        print(f"\n{'='*60}")
    
    def _load_json(self, file_path: str) -> Dict:
        """Load JSON file."""
        try:
            path = Path(file_path)
            if path.exists():
                with open(path) as f:
                    return json.load(f)
        except Exception as e:
            print(f"Warning: Could not load {file_path}: {e}")
        return {}


def main():
    parser = argparse.ArgumentParser(description="Calculate security score")
    parser.add_argument("--dependency-report", help="Path to dependency scan report")
    parser.add_argument("--threat-model", help="Path to threat model")
    parser.add_argument("--output", required=True, help="Output file for security score")
    
    args = parser.parse_args()
    
    # Calculate score
    calculator = SecurityScoreCalculator()
    result = calculator.calculate(
        dependency_report=args.dependency_report,
        threat_model=args.threat_model
    )
    
    # Save results
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, 'w') as f:
        json.dump(result, f, indent=2)
    
    print(f"\n💾 Security score saved to {output_path}")
    
    # Exit with code based on score
    if result["overall_score"] >= 70:
        return 0
    else:
        print("\n⚠️  WARNING: Security score below threshold (70)")
        return 1


if __name__ == "__main__":
    sys.exit(main())
