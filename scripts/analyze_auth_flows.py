#!/usr/bin/env python3
"""
Analyze authentication flows for security review.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, Any, List


class AuthFlowAnalyzer:
    """Analyze authentication flows and security."""
    
    def __init__(self, auth_dir: str):
        self.auth_dir = Path(auth_dir)
        self.flows = []
        
    def analyze(self) -> Dict[str, Any]:
        """Analyze authentication flows."""
        
        print("🔐 Analyzing Authentication Flows...")
        
        if not self.auth_dir.exists():
            print(f"⚠️  Auth directory not found: {self.auth_dir}")
            return self._empty_analysis()
        
        # Identify auth components
        auth_files = list(self.auth_dir.glob("*.py"))
        
        print(f"Found {len(auth_files)} auth files")
        
        # Analyze each component
        for auth_file in auth_files:
            flow = self._analyze_file(auth_file)
            if flow:
                self.flows.append(flow)
        
        # Security assessment
        assessment = self._assess_security()
        
        print(f"✅ Analyzed {len(self.flows)} authentication flows")
        
        return {
            "flows": self.flows,
            "security_assessment": assessment
        }
    
    def _analyze_file(self, file_path: Path) -> Dict[str, Any]:
        """Analyze a single auth file."""
        
        try:
            content = file_path.read_text()
            
            # Identify security features
            features = {
                "encryption": "encrypt" in content or "Fernet" in content,
                "hashing": "hash" in content or "bcrypt" in content or "argon2" in content,
                "jwt": "jwt" in content or "JWT" in content,
                "session": "session" in content,
                "mfa": "mfa" in content or "2fa" in content or "totp" in content,
                "rate_limiting": "rate_limit" in content or "RateLimiter" in content,
                "secure_storage": "secure" in content and "store" in content
            }
            
            return {
                "file": file_path.name,
                "features": features,
                "security_score": sum(1 for v in features.values() if v)
            }
        
        except Exception as e:
            print(f"Warning: Could not analyze {file_path}: {e}")
            return None
    
    def _assess_security(self) -> Dict[str, Any]:
        """Assess overall authentication security."""
        
        if not self.flows:
            return {
                "overall_score": 0,
                "recommendations": ["Implement authentication system"]
            }
        
        # Aggregate features
        all_features = {}
        for flow in self.flows:
            for feature, present in flow["features"].items():
                if present:
                    all_features[feature] = True
        
        # Security requirements
        requirements = {
            "encryption": "Encryption for sensitive data",
            "hashing": "Password hashing",
            "jwt": "Token-based authentication",
            "rate_limiting": "Rate limiting protection",
            "secure_storage": "Secure credential storage"
        }
        
        # Check which requirements are met
        met = []
        missing = []
        
        for req, description in requirements.items():
            if all_features.get(req, False):
                met.append(description)
            else:
                missing.append(description)
        
        # Calculate score
        score = len(met) / len(requirements) * 100
        
        recommendations = []
        if missing:
            recommendations.append("Implement missing security features:")
            recommendations.extend([f"  - {m}" for m in missing])
        
        if score < 80:
            recommendations.append("Security score below 80 - immediate attention required")
        
        return {
            "overall_score": round(score, 2),
            "requirements_met": met,
            "requirements_missing": missing,
            "recommendations": recommendations
        }
    
    def _empty_analysis(self) -> Dict[str, Any]:
        """Return empty analysis when auth directory doesn't exist."""
        return {
            "flows": [],
            "security_assessment": {
                "overall_score": 0,
                "requirements_met": [],
                "requirements_missing": ["No authentication system found"],
                "recommendations": ["Implement authentication system"]
            }
        }


def main():
    parser = argparse.ArgumentParser(description="Analyze authentication flows")
    parser.add_argument("--auth-dir", required=True, help="Authentication directory")
    parser.add_argument("--output", required=True, help="Output file for analysis")
    
    args = parser.parse_args()
    
    # Create analyzer
    analyzer = AuthFlowAnalyzer(args.auth_dir)
    analysis = analyzer.analyze()
    
    # Save results
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, 'w') as f:
        json.dump(analysis, f, indent=2)
    
    print(f"\n✅ Analysis saved to {output_path}")
    
    assessment = analysis["security_assessment"]
    print(f"\n📊 Security Score: {assessment['overall_score']}/100")
    
    if assessment.get("recommendations"):
        print("\n💡 Recommendations:")
        for rec in assessment["recommendations"]:
            print(f"   {rec}")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
