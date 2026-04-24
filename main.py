"""
NIJA Trading Bot — main.py
==========================
Production entry point.  Delegates to bot.py which contains the full
startup sequence: health server, broker connections, safety gate activation,
market scanning, and the self-healing trading loop.

Usage
-----
    python main.py          # same as: python bot.py
    bash start.sh           # Railway / Docker production start (also uses bot.py)
"""
# ── Ultra-low-level boot probe (before any imports can block) ─────────────────
import sys as _sys
print("BOOT ENTRY REACHED — interpreter started, pre-import probe OK", flush=True)
_sys.stderr.write("BOOT ENTRY REACHED — pre-import stderr probe OK\n")
_sys.stderr.flush()
# ─────────────────────────────────────────────────────────────────────────────

import logging
import os
import runpy

_ROOT = os.path.dirname(os.path.abspath(__file__))
logger = logging.getLogger(__name__)


def main() -> None:
    """Delegate to bot.py's __main__ block."""
    logger.critical("BOOT ENTRY REACHED main()")

    # Ensure project root is importable so bot.py's relative imports work.
    if _ROOT not in _sys.path:
        _sys.path.insert(0, _ROOT)

    runpy.run_path(os.path.join(_ROOT, "bot.py"), run_name="__main__")


if __name__ == "__main__":
    main()
