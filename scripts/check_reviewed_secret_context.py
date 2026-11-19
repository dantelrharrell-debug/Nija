"""Invalidate reviewed false positives whenever their complete source changes."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import re


MANIFEST = "docs/security/exact-source-secret-review-20261117.json"


def _unique(pairs):
    output = {}
    for key, value in pairs:
        if key in output:
            raise ValueError("duplicate_review_field")
        output[key] = value
    return output


def check_context(root: Path, manifest_path: str = MANIFEST) -> bool:
    """Require the exact reviewed files; disclose no source or candidate values."""
    try:
        root = root.resolve()
        manifest = json.loads((root / manifest_path).read_text(), object_pairs_hook=_unique)
        files, entries = manifest["files"], manifest["entries"]
        if (manifest["schema_version"] != 1 or not isinstance(files, dict)
                or not files or not isinstance(entries, list) or not entries):
            return False
        if {item["path"] for item in entries} != set(files):
            return False
        for name, digest in files.items():
            path = PurePosixPath(name)
            if (path.is_absolute() or ".." in path.parts or str(path) != name
                    or not isinstance(digest, str)
                    or not re.fullmatch(r"(?:[0-9a-f]{2}:){31}[0-9a-f]{2}", digest)):
                return False
            target = root / name
            if target.resolve() != target.absolute() or not target.is_file():
                return False
            if hashlib.sha256(target.read_bytes()).hexdigest() != digest.replace(":", ""):
                return False
        return True
    except (OSError, ValueError, TypeError, KeyError, RecursionError):
        return False



# Supplemental exact-source review is intentionally separate from the historical
# 142-candidate ledger. No baseline-only exception is accepted without its
# complete source-byte pin, matching detector identity, and human review.
TIQ72_MANIFEST = "docs/security/tiq72-exact-source-secret-review-20261118.json"


def check_all_context(root: Path) -> bool:
    """Validate each configured review and its exact baseline candidate bindings."""
    try:
        root = root.resolve()
        baseline = json.loads(
            (root / ".secrets.baseline").read_text(), object_pairs_hook=_unique
        )
        if baseline.get("reviewed_context_manifest") != MANIFEST:
            return False
        if not check_context(root):
            return False
        additional = baseline.get("reviewed_additional_context_manifest")
        if additional is None:
            return True
        if additional != TIQ72_MANIFEST or not check_context(root, additional):
            return False
        review = json.loads(
            (root / additional).read_text(), object_pairs_hook=_unique
        )
        entries = review["entries"]
        if (review.get("schema_version") != 1 or
                len(entries) != 6 or len(review["files"]) != 6):
            return False
        identities = set()
        for item in entries:
            path, line, kind, hashed = (
                item["path"], item["line"], item["type"], item["hashed_secret"]
            )
            if (not isinstance(line, int) or line < 1 or
                    not isinstance(hashed, str) or
                    not re.fullmatch(r"[0-9a-f]{40}", hashed)):
                return False
            identity = (path, line, kind)
            if identity in identities:
                return False
            identities.add(identity)
            matching = [
                row for row in baseline["results"].get(path, [])
                if (row.get("line_number"), row.get("type"),
                    row.get("hashed_secret")) == (line, kind, hashed)
                and row.get("is_secret") is False
                and row.get("is_verified") is False
            ]
            if len(matching) != 1:
                return False
        if {item["path"] for item in entries} != set(review["files"]):
            return False
        stale = review["replaced_stale_identity"]
        rows = baseline["results"].get(stale["path"], [])
        if any(
            row.get("line_number") == stale["line"]
            and row.get("type") == stale["type"]
            and row.get("hashed_secret") == stale["old_hashed_secret"]
            for row in rows
        ):
            return False
        return True
    except (OSError, ValueError, TypeError, KeyError, RecursionError):
        return False

if __name__ == "__main__":
    valid = check_all_context(Path.cwd())
    print("Reviewed source context: " + ("unchanged" if valid else "changed or invalid; review required"))
    raise SystemExit(0 if valid else 2)
