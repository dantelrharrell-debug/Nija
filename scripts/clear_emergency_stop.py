#!/usr/bin/env python3
"""Safely clear NIJA filesystem emergency-stop files after operator approval.

This does not bypass risk gates, writer locks, or activation checks. It only moves
stale emergency-stop files out of the active path when the operator supplies the
exact approval environment variables.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot.operator_emergency_stop_clear_patch import run_once


if __name__ == "__main__":
    cleared = run_once()
    print(f"clear_emergency_stop complete: cleared={cleared}")
    raise SystemExit(0)
