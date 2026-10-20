"""Strict JSON recovery-state I/O; failed persistence must stop callers.

Fsync and atomic replacement protect a configured filesystem. They do not
prove that the operator placed that filesystem on persistent storage.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
from typing import Any, Mapping


def read_recovery_state(path: Path, bucket: str) -> dict[str, dict[str, Any]]:
    """Read exact records; only a genuinely absent file means no records."""
    if path.is_symlink():
        raise ValueError("recovery_state_symlink")
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    data = json.loads(raw)
    if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get(bucket), dict):
        raise ValueError("recovery_state_schema_invalid")
    rows = data[bucket]
    if any(not isinstance(key, str) or not key.strip() or not isinstance(row, dict)
           for key, row in rows.items()):
        raise ValueError("recovery_state_record_invalid")
    return {key: dict(row) for key, row in rows.items()}


def write_recovery_state(path: Path, payload: Mapping[str, Any]) -> None:
    """Commit complete state or raise; never substitute an in-memory success."""
    encoded = json.dumps(dict(payload), sort_keys=True, allow_nan=False)
    if path.is_symlink():
        raise ValueError("recovery_state_symlink")
    path.parent.mkdir(parents=True, exist_ok=True)
    name: str | None = None
    try:
        fd, name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
        name = None
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if name is not None:
            try:
                os.unlink(name)
            except FileNotFoundError:
                pass
