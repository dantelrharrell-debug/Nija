#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
from pathlib import Path

BANNED = [
    "risk-free",
    "guaranteed profits",
    "guaranteed returns",
    "passive income",
    "financial freedom",
    "稳赚",
    "稳赚不赔",
]

EXCLUDE_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
}

# These files define the compliance rules themselves, so they necessarily
# contain the prohibited phrases as data/patterns. Scanning them makes the
# repository fail simply because the guardrails exist. Only rule-definition
# files are exempt; user-facing and runtime content remains scanned.
EXCLUDE_FILES = {
    Path("scripts/compliance_scan.py"),
    Path("bot/compliance_language_guard.py"),
}


def is_binary(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            chunk = handle.read(2048)
        return b"\0" in chunk
    except OSError:
        return True


def scan_file(path: Path, banned_phrases: list[str]) -> list[str]:
    if is_binary(path):
        return []
    try:
        content = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []
    matches: list[str] = []
    for line_number, line in enumerate(content.splitlines(), start=1):
        lower_line = line.lower()
        for phrase in banned_phrases:
            if phrase in lower_line:
                matches.append(f"{path}:{line_number}: {phrase}")
    return matches


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    banned_phrases = [phrase.lower() for phrase in BANNED]
    failures: list[str] = []

    for root, dirs, files in os.walk(repo_root):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        for file_name in files:
            path = Path(root) / file_name
            try:
                relative_path = path.resolve().relative_to(repo_root.resolve())
            except (OSError, ValueError):
                relative_path = path
            if relative_path in EXCLUDE_FILES:
                continue
            failures.extend(scan_file(path, banned_phrases))

    if failures:
        print("Compliance phrase scan failed. Banned phrases found:")
        for entry in failures:
            print(f" - {entry}")
        return 1

    print("Compliance phrase scan passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
