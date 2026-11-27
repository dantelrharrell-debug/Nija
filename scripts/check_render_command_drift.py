"""Read-only NIJA Render command drift check (issue #3707).

Usage:
  python3 scripts/check_render_command_drift.py --actual 'python -S /etc/secrets/.render-ledger-bootstrap.py'

The actual command must come from Render's service metadata, not from a secret
file. No broker calls, runtime imports, writes, or trading operations occur.
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys


def blueprint_command(text: str) -> str:
    match = re.search(r"(?m)^\s{4}dockerCommand:\s*(\S.*?)\s*$", text)
    if not match:
        raise ValueError("render.yaml has no explicit web-service dockerCommand")
    return match.group(1).strip().strip('"\'')


def check(actual: str, expected: str) -> int:
    if not actual.strip():
        print("COMMAND_ATTESTATION_INCOMPLETE: actual command missing")
        return 2
    if actual.strip() != expected:
        print("COMMAND_DRIFT_DETECTED: Render dashboard command differs from render.yaml")
        print("Do not auto-change the command; independently review bootstrap and safety handoff.")
        return 1
    print("COMMAND_MATCH: Render dashboard command matches render.yaml")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--actual", required=True, help="Command from Render service metadata, not a secret")
    parser.add_argument("--blueprint", default="render.yaml")
    args = parser.parse_args()
    try:
        expected = blueprint_command(pathlib.Path(args.blueprint).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"COMMAND_ATTESTATION_INCOMPLETE: {type(exc).__name__}")
        return 2
    return check(args.actual, expected)


if __name__ == "__main__":
    sys.exit(main())
