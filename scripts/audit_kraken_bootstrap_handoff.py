#!/usr/bin/env python3
"""Read-only structural audit for an operator-supplied protected Kraken bootstrap.

This is intentionally NOT a certification tool. It parses a private file locally
and emits only fixed non-sensitive diagnostic labels. Never print source lines,
paths, environment values, exception text, or credentials.
"""
from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path

REGISTRATION_NAMES = frozenset({
    "register_signed_kraken_startup",
    "register_reviewed_startup_binding",
    "register_canonical_kraken_collector_startup",
})
EXEC_NAMES = frozenset({
    "os.execv", "os.execve", "os.execvp", "os.execvpe",
    "os.execl", "os.execle", "os.execlp", "os.execlpe",
})


def _name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _name(node.value)
        return prefix + "." + node.attr if prefix else node.attr
    return ""


def classify_source(source: str) -> dict[str, object]:
    """Return conservative structure only. A clean audit NEVER approves orders."""
    tree = ast.parse(source)
    registrations = []
    replacements = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _name(node.func)
        if name.split(".")[-1] in REGISTRATION_NAMES:
            registrations.append(node.lineno)
        if name in EXEC_NAMES or name.split(".")[-1] in {
            "execv", "execve", "execvp", "execvpe", "execl", "execle", "execlp", "execlpe",
        }:
            replacements.append(node.lineno)
    # Seeing a registration symbol does not prove its branch executes or
    # that its factory, sources, signatures, account or release are genuine.
    pre_exec_registration = bool(
        registrations and replacements and min(registrations) < max(replacements)
    )
    if pre_exec_registration:
        status = "possible_registration_lost_at_process_replacement"
    elif replacements:
        status = "process_replacement_requires_final_interpreter_registration"
    elif not registrations:
        status = "no_registration_visible"
    else:
        status = "registration_visible_not_certified"
    return {
        "status": status,
        "registration_reference_visible": bool(registrations),
        "process_replacement_visible": bool(replacements),
        "pre_exec_registration_reference_visible": pre_exec_registration,
        "collector_certified": False,
        "orders_authorized": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit protected Kraken startup without revealing source")
    parser.add_argument("bootstrap", help="Local protected bootstrap path; NEVER commit or upload it")
    args = parser.parse_args()
    try:
        raw = Path(args.bootstrap).read_text(encoding="utf-8")
        outcome = classify_source(raw)
    except (OSError, UnicodeError, SyntaxError, ValueError):
        outcome = {
            "status": "audit_unavailable",
            "registration_reference_visible": False,
            "process_replacement_visible": False,
            "pre_exec_registration_reference_visible": False,
            "collector_certified": False,
            "orders_authorized": False,
        }
    print(json.dumps(outcome, sort_keys=True))
    # A static source inspection is insufficient for certification in every case.
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
