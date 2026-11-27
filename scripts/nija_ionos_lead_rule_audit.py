#!/usr/bin/env python3
"""Fail-closed audit of exported IONOS PocketBase lead collection rules.

Accepts an admin-exported JSON array of collection metadata, or an object
containing a 'collections' array. Does not connect to production or send leads.
PocketBase rule semantics: null = superuser only, "" = public, expression =
conditional access (requires separate human review).
"""
import argparse
import json
import sys

SENSITIVE = {
    "nija_lead_delivery": ("createRule", "updateRule", "deleteRule"),
    "nija_lead_dispatch": ("listRule", "viewRule", "createRule", "updateRule", "deleteRule"),
    "nija_consent_events": ("updateRule", "deleteRule"),
}

def audit(data):
    collections = data if isinstance(data, list) else data.get("collections", [])
    if not isinstance(collections, list):
        raise ValueError("Expected a collection list")
    by_name = {c.get("name"): c for c in collections if isinstance(c, dict)}
    failures = []
    for name, fields in SENSITIVE.items():
        collection = by_name.get(name)
        if collection is None:
            failures.append(f"{name}: missing collection metadata")
            continue
        for field in fields:
            if field not in collection:
                failures.append(f"{name}.{field}: missing rule metadata")
            elif collection[field] is not None:
                failures.append(f"{name}.{field}: not superuser-only; review required")
    return failures

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("metadata_json", help="Local admin-exported collection metadata JSON")
    args = parser.parse_args()
    try:
        with open(args.metadata_json, encoding="utf-8") as handle:
            failures = audit(json.load(handle))
    except (OSError, ValueError, TypeError) as exc:
        print(f"BLOCKED: unable to verify collection rules: {exc}", file=sys.stderr)
        return 2
    if failures:
        for failure in failures:
            print("BLOCKED:", failure)
        return 1
    print("PASS: specified sensitive PocketBase rules are superuser-only")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
