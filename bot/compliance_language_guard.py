"""
NIJA Compliance Language Guard - Financial Language Firewall

CRITICAL COMPLIANCE MODULE - Prevents use of forbidden financial language.

This module scans and enforces compliant language across:
    - Code comments and strings
    - UI text
    - Log messages
    - Documentation
    - Marketing materials

Forbidden language that triggers App Store rejection:
    ❌ "Guaranteed profits"
    ❌ "Passive income"
    ❌ "AI trades for you"
    ❌ "Automatic money"
    ❌ And 50+ more...

Required language:
    ✅ "User-directed"
    ✅ "Independent trading"
    ✅ "No guarantees"
    ✅ "Risk of loss"

Author: NIJA Trading Systems
Version: 1.0
Date: February 2026
"""

import re
import os
import logging
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("nija.compliance_language_guard")


@dataclass
class ViolationInstance:
    """Represents a language compliance violation"""
    term: str
    context: str
    file_path: Optional[str] = None
    line_number: Optional[int] = None
    severity: str = "HIGH"  # HIGH, MEDIUM, LOW


class ComplianceLanguageGuard:
    """
    Financial Language Firewall - Ensures App Store compliance.
    
    Scans for forbidden terms and enforces compliant alternatives.
    """
    
    # FORBIDDEN TERMS - These will cause instant App Store rejection
    FORBIDDEN_TERMS = [
        # Guaranteed returns
        r"\bguaranteed?\s+(profit|return|income|gain|money|roi)\b",
        r"\b(profit|return|income|gain|money)\s+guaranteed?\b",
        r"\bguaranteed?\s+to\s+(make|earn|generate)\b",
        r"\b100%\s+(win|profit|success|roi)\b",
        r"\bcannot?\s+lose\b",
        r"\brisk-?free\b",
        r"\bno\s+risk\b",
        r"\bzero\s+risk\b",
        
        # Passive income claims
        r"\bpassive\s+income\b",
        r"\bmake\s+money\s+(while|when)\s+you\s+sleep\b",
        r"\bautomated?\s+income\b",
        r"\beffortless\s+(money|profit|income)\b",
        r"\bset\s+and\s+forget\b",
        r"\bset\s+it\s+and\s+forget\s+it\b",
        
        # Automatic trading without user control
        r"\bAI\s+trades?\s+for\s+you\b",
        r"\bauto-?trades?\s+for\s+you\b",
        r"\bbot\s+trades?\s+for\s+you\b",
        r"\bautomated?\s+trading\s+system\b",
        r"\bfully\s+automated?\b",
        r"\bcompletely\s+automated?\b",
        
        # Financial freedom / get rich
        r"\bfinancial\s+freedom\b",
        r"\bget\s+rich\b",
        r"\bmake\s+you\s+rich\b",
        r"\bwealth\s+generation\b",
        r"\breplace\s+your\s+(job|income|salary)\b",
        r"\bquit\s+your\s+job\b",
        
        # Unrealistic claims
        r"\balways\s+(profitable|wins?|succeeds?)\b",
        r"\bnever\s+loses?\b",
        r"\bconsistent\s+(returns?|profits?|gains?)\b",
        r"\bsteady\s+(returns?|income|profit)\b",
        r"\bpredictable\s+(returns?|profit)\b",
        
        # Misleading percentage claims
        r"\b\d+%\s+(guaranteed|assured|certain)\b",
        r"\b100%\s+(accuracy|success)\b",
        
        # Investment advice
        r"\bwe\s+recommend\s+buying\b",
        r"\byou\s+should\s+buy\b",
        r"\binvestment\s+(advice|recommendation)\b",
        
        # Specific prohibited phrases
        r"\btoo\s+good\s+to\s+be\s+true\b",
        r"\bsecret\s+(strategy|formula|method)\b",
        r"\bholy\s+grail\b",
        r"\bproven\s+system\b",
        
        # Compounding/exponential claims
        r"\bexponential\s+growth\b",
        r"\bcompounding\s+returns?\b",
        r"\bdouble\s+your\s+money\b",
        r"\btriple\s+your\s+(investment|capital)\b",
        
        # Professional misrepresentation
        r"\bprofessional\s+trader\s+performance\b",
        r"\bhedge\s+fund\s+(returns?|performance)\b",
        r"\bbeat\s+the\s+market\b",
        
        # Urgency/scarcity tactics
        r"\blimited\s+time\s+offer\b",
        r"\bact\s+now\b",
        r"\bdon't\s+miss\s+out\b",
    ]
    
    # REQUIRED TERMS - These should appear in key locations
    REQUIRED_TERMS = [
        r"\buser-?directed\b",
        r"\bindependent\s+trading\b",
        r"\brisk\s+of\s+loss\b",
        r"\bno\s+guarantee",
        r"\bpast\s+performance.*not.*guarantee.*future\b",
        r"\bsolely\s+responsible\b",
    ]
    
    # COMPLIANT ALTERNATIVES
    COMPLIANT_ALTERNATIVES = {
        "guaranteed profit": "potential for profit (with risk of loss)",
        "passive income": "user-directed trading activity",
        "AI trades for you": "AI-assisted signal generation requiring user approval",
        "automatic trading": "user-configured automated execution",
        "set and forget": "configurable strategy execution",
        "financial freedom": "trading tool for independent investors",
        "get rich": "potential to generate returns (with substantial risk)",
        "always profitable": "designed to identify favorable risk/reward opportunities",
        "never loses": "includes stop-loss protection (losses still possible)",
        "consistent returns": "systematic approach to trading (results vary)",
        "guaranteed returns": "no guaranteed returns; past performance does not indicate future results",
    }
    
    def __init__(self):
        """Initialize compliance language guard"""
        self._compiled_forbidden = [
            (pattern, re.compile(pattern, re.IGNORECASE))
            for pattern in self.FORBIDDEN_TERMS
        ]
        self._compiled_required = [
            (pattern, re.compile(pattern, re.IGNORECASE))
            for pattern in self.REQUIRED_TERMS
        ]
        
    def scan_text(self, text: str, context: str = "unknown") -> List[ViolationInstance]:
        """
        Scan text for forbidden terms.
        
        Args:
            text: Text to scan
            context: Context description (e.g., "UI button", "README.md")
            
        Returns:
            List of violation instances
        """
        violations = []
        
        for pattern_str, pattern in self._compiled_forbidden:
            matches = pattern.finditer(text)
            for match in matches:
                # Get surrounding context
                start = max(0, match.start() - 40)
                end = min(len(text), match.end() + 40)
                surrounding = text[start:end]
                
                violations.append(ViolationInstance(
                    term=match.group(0),
                    context=f"...{surrounding}...",
                    severity="HIGH"
                ))
                
        return violations
        
    def scan_file(self, file_path: str) -> List[ViolationInstance]:
        """
        Scan a file for forbidden terms.
        
        Args:
            file_path: Path to file to scan
            
        Returns:
            List of violation instances with file/line info
        """
        violations = []
        
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                for line_num, line in enumerate(f, 1):
                    line_violations = self.scan_text(line, f"File: {file_path}")
                    for v in line_violations:
                        v.file_path = file_path
                        v.line_number = line_num
                        violations.append(v)
        except Exception as e:
            logger.error(f"Error scanning {file_path}: {e}")
            
        return violations
        
    def scan_directory(
        self,
        directory: str,
        extensions: Optional[List[str]] = None,
        exclude_dirs: Optional[List[str]] = None
    ) -> List[ViolationInstance]:
        """
        Recursively scan directory for forbidden terms.
        
        Args:
            directory: Directory to scan
            extensions: File extensions to scan (default: .py, .md, .txt, .json)
            exclude_dirs: Directories to exclude (default: .git, __pycache__, node_modules)
            
        Returns:
            List of all violations found
        """
        if extensions is None:
            extensions = ['.py', '.md', '.txt', '.json', '.yaml', '.yml', '.html', '.js']
        if exclude_dirs is None:
            exclude_dirs = ['.git', '__pycache__', 'node_modules', 'venv', '.env']
            
        all_violations = []
        
        for root, dirs, files in os.walk(directory):
            # Exclude certain directories
            dirs[:] = [d for d in dirs if d not in exclude_dirs]
            
            for file in files:
                if any(file.endswith(ext) for ext in extensions):
                    file_path = os.path.join(root, file)
                    violations = self.scan_file(file_path)
                    all_violations.extend(violations)
                    
        return all_violations
        
    def check_required_terms(self, text: str) -> Dict[str, bool]:
        """
        Check if required compliant terms are present.
        
        Args:
            text: Text to check
            
        Returns:
            Dict mapping required term patterns to whether they were found
        """
        results = {}
        
        for pattern_str, pattern in self._compiled_required:
            results[pattern_str] = bool(pattern.search(text))
            
        return results
        
    def suggest_alternative(self, forbidden_term: str) -> Optional[str]:
        """
        Suggest compliant alternative for a forbidden term.
        
        Args:
            forbidden_term: The forbidden term found
            
        Returns:
            Suggested compliant alternative, or None if no specific suggestion
        """
        term_lower = forbidden_term.lower()
        
        for forbidden, alternative in self.COMPLIANT_ALTERNATIVES.items():
            if forbidden in term_lower:
                return alternative
                
        return None
        
    def generate_report(self, violations: List[ViolationInstance]) -> str:
        """
        Generate a human-readable compliance report.
        
        Args:
            violations: List of violations
            
        Returns:
            Formatted report string
        """
        if not violations:
            return "✅ No compliance violations found!"
            
        report = f"\n{'=' * 80}\n"
        report += "🚨 COMPLIANCE LANGUAGE VIOLATIONS DETECTED\n"
        report += f"{'=' * 80}\n\n"
        report += f"Total violations: {len(violations)}\n"
        report += "These terms will likely cause App Store rejection.\n\n"
        
        # Group by file
        by_file = {}
        for v in violations:
            file_key = v.file_path or "Direct text scan"
            if file_key not in by_file:
                by_file[file_key] = []
            by_file[file_key].append(v)
            
        for file_path, file_violations in by_file.items():
            report += f"\n📄 {file_path}\n"
            report += "-" * 80 + "\n"
            
            for v in file_violations:
                line_info = f"Line {v.line_number}: " if v.line_number else ""
                report += f"  ❌ {line_info}{v.term}\n"
                report += f"     Context: {v.context}\n"
                
                suggestion = self.suggest_alternative(v.term)
                if suggestion:
                    report += f"     ✅ Suggested: {suggestion}\n"
                    
                report += "\n"
                
        report += "=" * 80 + "\n"
        report += "⚠️  CRITICAL: Fix these violations before App Store submission!\n"
        report += "=" * 80 + "\n"
        
        return report


# Global singleton instance
_compliance_guard: Optional[ComplianceLanguageGuard] = None


def get_compliance_guard() -> ComplianceLanguageGuard:
    """Get the global compliance language guard instance (singleton)"""
    global _compliance_guard
    
    if _compliance_guard is None:
        _compliance_guard = ComplianceLanguageGuard()
        
    return _compliance_guard


def check_text_compliance(text: str, context: str = "unknown") -> Tuple[bool, List[ViolationInstance]]:
    """
    Quick check if text is compliant.
    
    Returns:
        Tuple of (is_compliant, violations)
    """
    guard = get_compliance_guard()
    violations = guard.scan_text(text, context)
    return (len(violations) == 0, violations)


# Example usage and testing
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    print("\n=== Compliance Language Guard Test ===\n")
    
    guard = get_compliance_guard()
    
    # Test forbidden terms
    test_texts = [
        "Our AI trades for you with guaranteed profits!",
        "Generate passive income while you sleep.",
        "This is a user-directed trading tool with risk of loss.",
        "Set and forget automated trading system.",
        "100% win rate guaranteed!",
    ]
    
    for i, text in enumerate(test_texts, 1):
        print(f"\nTest {i}: {text}")
        violations = guard.scan_text(text, f"Test {i}")
        
        if violations:
            print(f"  ❌ VIOLATIONS: {len(violations)}")
            for v in violations:
                print(f"     - {v.term}")
                suggestion = guard.suggest_alternative(v.term)
                if suggestion:
                    print(f"       Suggest: {suggestion}")
        else:
            print("  ✅ COMPLIANT")
            
    # Test directory scanning
    print("\n\n=== Scanning Current Directory ===")
    print("(This is a demo - would scan actual project files)")
