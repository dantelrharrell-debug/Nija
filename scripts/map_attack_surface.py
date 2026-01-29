#!/usr/bin/env python3
"""
Map API attack surface for threat modeling.
"""

import argparse
import json
import sys
import re
from pathlib import Path
from typing import List, Dict, Any


class AttackSurfaceMapper:
    """Map external attack surface of the application."""
    
    def __init__(self, project_root: str, api_patterns: List[str]):
        self.project_root = Path(project_root)
        self.api_patterns = api_patterns
        self.endpoints = []
        
    def map(self) -> Dict[str, Any]:
        """Map the attack surface."""
        
        print("🗺️  Mapping API Attack Surface...")
        
        # Find API files
        api_files = []
        for pattern in self.api_patterns:
            api_files.extend(self.project_root.glob(pattern))
        
        print(f"Found {len(api_files)} API files")
        
        # Extract endpoints from each file
        for api_file in api_files:
            endpoints = self._extract_endpoints_from_file(api_file)
            self.endpoints.extend(endpoints)
        
        print(f"✅ Mapped {len(self.endpoints)} endpoints")
        
        # Categorize endpoints
        categorized = self._categorize_endpoints()
        
        return {
            "total_endpoints": len(self.endpoints),
            "endpoints": self.endpoints,
            "by_method": categorized["by_method"],
            "by_auth": categorized["by_auth"],
            "by_exposure": categorized["by_exposure"]
        }
    
    def _extract_endpoints_from_file(self, file_path: Path) -> List[Dict[str, Any]]:
        """Extract API endpoints from a file."""
        
        endpoints = []
        
        try:
            content = file_path.read_text()
            
            # FastAPI route patterns
            route_patterns = [
                (r'@app\.(get|post|put|delete|patch)\(["\'](.+?)["\']\)', 'public'),
                (r'@router\.(get|post|put|delete|patch)\(["\'](.+?)["\']\)', 'public'),
            ]
            
            for pattern, exposure in route_patterns:
                matches = re.finditer(pattern, content, re.MULTILINE)
                for match in matches:
                    method = match.group(1).upper()
                    path = match.group(2)
                    
                    # Check if authentication required
                    # Look for @requires_auth decorator or similar
                    auth_required = self._check_auth_required(content, match.start())
                    
                    endpoints.append({
                        "file": str(file_path.relative_to(self.project_root)),
                        "method": method,
                        "path": path,
                        "exposure": exposure,
                        "authentication_required": auth_required,
                        "full_endpoint": f"{method} {path}"
                    })
        
        except Exception as e:
            print(f"Warning: Could not parse {file_path}: {e}")
        
        return endpoints
    
    def _check_auth_required(self, content: str, position: int) -> bool:
        """Check if authentication is required for an endpoint."""
        
        # Look backwards for authentication decorators
        before = content[max(0, position-500):position]
        
        auth_indicators = [
            '@requires_auth',
            '@login_required',
            '@authenticated',
            'Depends(get_current_user)',
            'Depends(verify_token)'
        ]
        
        return any(indicator in before for indicator in auth_indicators)
    
    def _categorize_endpoints(self) -> Dict[str, Any]:
        """Categorize endpoints by various criteria."""
        
        by_method = {}
        by_auth = {"authenticated": 0, "public": 0}
        by_exposure = {}
        
        for endpoint in self.endpoints:
            # By HTTP method
            method = endpoint["method"]
            by_method[method] = by_method.get(method, 0) + 1
            
            # By authentication
            if endpoint["authentication_required"]:
                by_auth["authenticated"] += 1
            else:
                by_auth["public"] += 1
            
            # By exposure
            exposure = endpoint["exposure"]
            by_exposure[exposure] = by_exposure.get(exposure, 0) + 1
        
        return {
            "by_method": by_method,
            "by_auth": by_auth,
            "by_exposure": by_exposure
        }


def main():
    parser = argparse.ArgumentParser(description="Map API attack surface")
    parser.add_argument("--api-files", required=True, help="Comma-separated glob patterns for API files")
    parser.add_argument("--output", required=True, help="Output file for attack surface map")
    parser.add_argument("--project-root", default=".", help="Project root directory")
    
    args = parser.parse_args()
    
    # Parse API file patterns
    api_patterns = [p.strip() for p in args.api_files.split(',')]
    
    # Create mapper
    mapper = AttackSurfaceMapper(args.project_root, api_patterns)
    attack_surface = mapper.map()
    
    # Save results
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, 'w') as f:
        json.dump(attack_surface, f, indent=2)
    
    print(f"\n✅ Attack surface map saved to {output_path}")
    print(f"\n📊 Summary:")
    print(f"   Total endpoints: {attack_surface['total_endpoints']}")
    print(f"   Authenticated: {attack_surface['by_auth']['authenticated']}")
    print(f"   Public: {attack_surface['by_auth']['public']}")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
