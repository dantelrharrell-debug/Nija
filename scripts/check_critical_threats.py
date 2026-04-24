#!/usr/bin/env python3
"""
Check for critical security threats and alert if found.
"""

import argparse
import json
import sys
from pathlib import Path


def check_critical_threats(security_score_file: str, threshold: int) -> int:
    """Check if security score meets threshold."""
    
    print("🔍 Checking for critical security threats...")
    
    if not Path(security_score_file).exists():
        print("⚠️  Security score file not found")
        return 1
    
    try:
        with open(security_score_file) as f:
            data = json.load(f)
        
        score = data.get("overall_score", 0)
        grade = data.get("grade", "F")
        
        print(f"Security Score: {score}/100 (Grade: {grade})")
        
        if score < threshold:
            print(f"\n❌ CRITICAL: Security score {score} below threshold {threshold}")
            print("\n⚠️  Immediate action required:")
            
            if "recommendations" in data:
                for i, rec in enumerate(data["recommendations"], 1):
                    print(f"  {i}. {rec}")
            
            return 1
        else:
            print(f"\n✅ Security score meets threshold ({score} >= {threshold})")
            return 0
    
    except Exception as e:
        print(f"❌ Error checking security score: {e}")
        return 1


def main():
    parser = argparse.ArgumentParser(description="Check for critical security threats")
    parser.add_argument("--security-score", required=True, help="Path to security score file")
    parser.add_argument("--threshold", type=int, default=70, help="Minimum acceptable score")
    
    args = parser.parse_args()
    
    return check_critical_threats(args.security_score, args.threshold)


if __name__ == "__main__":
    sys.exit(main())
