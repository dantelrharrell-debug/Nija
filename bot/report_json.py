"""Atomic strict JSON persistence for analysis reports, without certification."""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
from typing import Any


def write_report_json(destination: Path, payload: Any) -> None:
    """Reject invalid data before opening a file; replace only a complete report.

    Unsupported objects and non-finite numbers remain errors. They are never
    coerced into metrics, passing results, or certification evidence.
    """
    encoded = json.dumps(payload, indent=2, allow_nan=False) + "\n"
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n",
                                         dir=destination.parent, prefix="." + destination.name + ".",
                                         suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
