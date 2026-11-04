#!/usr/bin/env python3
"""Reproduce advisory triage from offline pip-audit and GitHub severity exports."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
from typing import Any

RUNTIME_PACKAGES = frozenset({
    "anyio", "certifi", "cryptography", "ecdsa", "eventlet", "flask-cors", "idna",
    "pyjwt", "python-socketio", "requests", "starlette", "tornado", "urllib3", "werkzeug",
})
RANK = {"UNKNOWN": 0, "LOW": 1, "MODERATE": 2, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}


def build_triage(
    audit: dict[str, Any], severities: dict[str, Any], pins: dict[str, str],
    resolved_audit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Preserve every primary ID, original fix branches and unknown severity."""
    nodes = severities.get("data")
    if severities.get("errors") or not isinstance(nodes, dict):
        raise ValueError("complete_github_severity_export_required")
    by_ghsa = {node["ghsaId"]: node for node in nodes.values() if isinstance(node, dict)}
    grouped: dict[tuple[str, str, str], dict[str, Any]] = {}
    dependencies = audit["dependencies"]
    current_dependencies = (
        {dependency["name"]: dependency for dependency in resolved_audit["dependencies"]}
        if resolved_audit is not None else None
    )
    for dependency in dependencies:
        name, version = dependency["name"], dependency["version"]
        for vulnerability in dependency.get("vulns", []):
            key = (name, version, vulnerability["id"])
            entry = grouped.setdefault(key, {"aliases": set(), "fix_versions": set()})
            entry["aliases"].update(vulnerability.get("aliases", []))
            entry["fix_versions"].update(vulnerability.get("fix_versions", []))
    rows = []
    for (name, version, advisory_id), evidence in sorted(grouped.items()):
        ids = sorted({advisory_id, *evidence["aliases"]})
        verified = [by_ghsa[value] for value in ids if value in by_ghsa
                    and by_ghsa[value].get("withdrawnAt") is None]
        severity = max((node["severity"] for node in verified), key=RANK.__getitem__, default="UNKNOWN")
        runtime = name in RUNTIME_PACKAGES
        current = pins.get(name)
        disposition = ("pin_changed_requires_fresh_resolved_audit"
                       if current is not None and current != version else "review_or_compatible_remediation_required")
        if current_dependencies is not None:
            if name not in current_dependencies:
                disposition = "not_installed_in_fresh_resolved_audit"
            else:
                current_ids = {
                    identity for vulnerability in current_dependencies[name].get("vulns", [])
                    for identity in (vulnerability["id"], *vulnerability.get("aliases", []))
                }
                disposition = ("still_reported_by_fresh_resolved_audit" if current_ids.intersection(ids)
                               else "not_reported_by_fresh_resolved_audit")
        rows.append({
            "package": name, "audited_version": version, "primary_advisory_id": advisory_id,
            "aliases": sorted(evidence["aliases"]), "severity": severity,
            "severity_source_ids": sorted(node["ghsaId"] for node in verified),
            "production_exposure": (
                "installed_trading_model_library_vulnerable_vectorizer_path_not_established"
                if name == "scikit-learn" else "installed_runtime_network_or_auth_stack" if runtime
                else "installed_tooling_or_library_exposure_unconfirmed"
            ),
            "exploitability": "conditional_browser_private_network_path_confirmed"
            if "CVE-2024-6221" in ids else "specific_trigger_not_established",
            "priority": "P1" if runtime and RANK[severity] >= 3 else (
                "P2" if RANK[severity] >= 3 else "P3" if severity != "UNKNOWN" else "UNVERIFIED"),
            "reported_fix_versions": sorted(evidence["fix_versions"]),
            "current_direct_pin": current,
            "disposition": disposition,
        })
    return {
        "format": "nija-offline-dependency-triage-v1",
        "resolved_package_count": len(dependencies),
        "affected_package_count": len({row["package"] for row in rows}),
        "raw_advisory_record_count": sum(len(dep.get("vulns", [])) for dep in dependencies),
        "unique_primary_advisory_ids": len({row["primary_advisory_id"] for row in rows}),
        "unknown_severity_rows": sum(row["severity"] == "UNKNOWN" for row in rows),
        "note": "Primary IDs are not alias-deduplicated incidents. Pin changes are not a clean rescan.",
        "advisories": rows,
    }


def main() -> None:
    """Print reproducible sanitized metadata, never scan a production service."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--github-severities", type=Path, required=True)
    parser.add_argument("--requirements", type=Path, required=True)
    parser.add_argument("--resolved-audit", type=Path)
    args = parser.parse_args()
    pins = {}
    for line in args.requirements.read_text().splitlines():
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)(?:\[[^\]]+\])?==([^\s#]+)", line.strip())
        if match:
            pins[re.sub(r"[-_.]+", "-", match[1]).lower()] = match[2]
    audit_raw = args.audit.read_bytes()
    severity_raw = args.github_severities.read_bytes()
    resolved_raw = args.resolved_audit.read_bytes() if args.resolved_audit is not None else None
    result = build_triage(
        json.loads(audit_raw), json.loads(severity_raw), pins,
        json.loads(resolved_raw) if resolved_raw is not None else None,
    )
    result["input_sha256"] = {
        "pip_audit_content_id": hashlib.sha256(audit_raw).hexdigest(),
        "github_severities_content_id": hashlib.sha256(severity_raw).hexdigest(),
    }
    if resolved_raw is not None:
        result["input_sha256"]["fresh_resolved_audit_content_id"] = hashlib.sha256(resolved_raw).hexdigest()
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
