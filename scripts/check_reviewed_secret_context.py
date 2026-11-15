"""Invalidate reviewed false positives whenever their complete source changes."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import re


MANIFEST = "docs/security/exact-source-secret-review-20261113.json"


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


if __name__ == "__main__":
    valid = check_context(Path.cwd())
    print("Reviewed source context: " + ("unchanged" if valid else "changed or invalid; review required"))
    raise SystemExit(0 if valid else 2)
