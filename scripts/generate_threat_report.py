#!/usr/bin/env python3
"""
Generate consolidated threat model report from all security scans.
"""

import argparse
import json
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List


class ThreatReportGenerator:
    """Generate consolidated threat model report."""
    
    def __init__(self, reports_dir: str):
        self.reports_dir = Path(reports_dir)
        
    def generate(self) -> str:
        """Generate consolidated markdown report."""
        
        print("📝 Generating Threat Model Report...")
        
        # Load all reports
        threat_model = self._load_report("threat-model-reports/threat-model.json")
        security_score = self._load_report("threat-model-reports/security-score.json")
        attack_surface = self._load_report("attack-surface-reports/attack-surface.json")
        auth_flows = self._load_report("attack-surface-reports/auth-flows.json")
        
        # Generate markdown report
        report = self._generate_markdown(
            threat_model=threat_model,
            security_score=security_score,
            attack_surface=attack_surface,
            auth_flows=auth_flows
        )
        
        print("✅ Report generated")
        
        return report
    
    def _load_report(self, relative_path: str) -> Dict[str, Any]:
        """Load a report file."""
        
        file_path = self.reports_dir / relative_path
        
        if not file_path.exists():
            print(f"⚠️  Report not found: {file_path}")
            return {}
        
        try:
            with open(file_path) as f:
                return json.load(f)
        except Exception as e:
            print(f"⚠️  Could not load {file_path}: {e}")
            return {}
    
    def _generate_markdown(self, threat_model: Dict, security_score: Dict, 
                          attack_surface: Dict, auth_flows: Dict) -> str:
        """Generate markdown report."""
        
        timestamp = datetime.utcnow().isoformat() + "Z"
        
        lines = [
            "# 🛡️ Threat Model Report",
            "",
            f"**Generated**: {timestamp}",
            "",
            "## Executive Summary",
            ""
        ]
        
        # Security Score Section
        if security_score:
            score = security_score.get("overall_score", 0)
            grade = security_score.get("grade", "F")
            
            lines.extend([
                f"### Security Score: {score}/100 (Grade: {grade})",
                ""
            ])
            
            if score >= 90:
                lines.append("✅ **Excellent** - Security posture is strong")
            elif score >= 80:
                lines.append("✅ **Good** - Minor improvements recommended")
            elif score >= 70:
                lines.append("⚠️ **Acceptable** - Several improvements needed")
            else:
                lines.append("❌ **Poor** - Immediate action required")
            
            lines.append("")
            
            # Component scores
            if "component_scores" in security_score:
                lines.extend([
                    "**Component Scores:**",
                    ""
                ])
                for component, score_val in security_score["component_scores"].items():
                    lines.append(f"- {component}: {score_val}/100")
                lines.append("")
        
        # Threat Analysis Section
        if threat_model and "threats" in threat_model:
            threats = threat_model["threats"]
            risk_assessment = threat_model.get("risk_assessment", {})
            
            lines.extend([
                "## Threat Analysis",
                "",
                f"**Total Threats Identified**: {len(threats)}",
                ""
            ])
            
            # Threat breakdown by severity
            if risk_assessment and "threat_counts" in risk_assessment:
                counts = risk_assessment["threat_counts"]
                lines.extend([
                    "### Threats by Severity",
                    ""
                ])
                for severity in ["CRITICAL", "HIGH", "MEDIUM", "LOW"]:
                    count = counts.get(severity, 0)
                    emoji = "🔴" if severity == "CRITICAL" else "🟠" if severity == "HIGH" else "🟡" if severity == "MEDIUM" else "🟢"
                    lines.append(f"- {emoji} **{severity}**: {count}")
                lines.append("")
            
            # Mitigation status
            if risk_assessment and "mitigation_status" in risk_assessment:
                status = risk_assessment["mitigation_status"]
                total = sum(status.values())
                
                lines.extend([
                    "### Mitigation Status",
                    ""
                ])
                
                for state, count in status.items():
                    pct = (count / total * 100) if total > 0 else 0
                    emoji = "✅" if state == "MITIGATED" else "🔄" if state == "PARTIALLY_MITIGATED" else "❌"
                    lines.append(f"- {emoji} **{state}**: {count} ({pct:.1f}%)")
                lines.append("")
        
        # Attack Surface Section
        if attack_surface:
            lines.extend([
                "## Attack Surface",
                "",
                f"**Total Endpoints**: {attack_surface.get('total_endpoints', 0)}",
                ""
            ])
            
            if "by_auth" in attack_surface:
                auth_data = attack_surface["by_auth"]
                total = sum(auth_data.values())
                
                lines.extend([
                    "### Authentication Coverage",
                    ""
                ])
                
                for auth_type, count in auth_data.items():
                    pct = (count / total * 100) if total > 0 else 0
                    emoji = "🔒" if auth_type == "authenticated" else "🌐"
                    lines.append(f"- {emoji} **{auth_type.title()}**: {count} ({pct:.1f}%)")
                lines.append("")
            
            if "by_method" in attack_surface:
                lines.extend([
                    "### Endpoints by HTTP Method",
                    ""
                ])
                
                for method, count in attack_surface["by_method"].items():
                    lines.append(f"- **{method}**: {count}")
                lines.append("")
        
        # Authentication Flows Section
        if auth_flows and "security_assessment" in auth_flows:
            assessment = auth_flows["security_assessment"]
            
            lines.extend([
                "## Authentication Security",
                "",
                f"**Security Score**: {assessment.get('overall_score', 0)}/100",
                ""
            ])
            
            if assessment.get("requirements_met"):
                lines.extend([
                    "### ✅ Requirements Met",
                    ""
                ])
                for req in assessment["requirements_met"]:
                    lines.append(f"- {req}")
                lines.append("")
            
            if assessment.get("requirements_missing"):
                lines.extend([
                    "### ❌ Requirements Missing",
                    ""
                ])
                for req in assessment["requirements_missing"]:
                    lines.append(f"- {req}")
                lines.append("")
        
        # Recommendations Section
        lines.extend([
            "## 💡 Recommendations",
            ""
        ])
        
        recommendations = []
        
        if security_score and "recommendations" in security_score:
            recommendations.extend(security_score["recommendations"])
        
        if auth_flows and "security_assessment" in auth_flows:
            auth_recs = auth_flows["security_assessment"].get("recommendations", [])
            recommendations.extend(auth_recs)
        
        if recommendations:
            for i, rec in enumerate(recommendations, 1):
                lines.append(f"{i}. {rec}")
        else:
            lines.append("No specific recommendations at this time.")
        
        lines.append("")
        
        # Summary
        lines.extend([
            "## Summary",
            "",
            "This automated threat model provides a comprehensive security analysis of the NIJA trading bot.",
            "Regular review and updates are essential to maintain security posture.",
            "",
            "**Next Steps:**",
            "1. Review and address high-priority threats",
            "2. Implement missing security features",
            "3. Schedule regular security reviews",
            "4. Update threat model as system evolves",
            "",
            "---",
            "",
            f"*Report generated automatically by NIJA Threat Modeling System*"
        ])
        
        return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Generate threat model report")
    parser.add_argument("--reports-dir", required=True, help="Directory containing all reports")
    parser.add_argument("--output", required=True, help="Output markdown file")
    
    args = parser.parse_args()
    
    # Generate report
    generator = ThreatReportGenerator(args.reports_dir)
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
