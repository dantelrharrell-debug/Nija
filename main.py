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
import os
import runpy
import sys

_ROOT = os.path.dirname(os.path.abspath(__file__))


def main() -> None:
    """Delegate to bot.py's __main__ block."""
    # Ensure project root is importable so bot.py's relative imports work.
    if _ROOT not in sys.path:
        sys.path.insert(0, _ROOT)

    runpy.run_path(os.path.join(_ROOT, "bot.py"), run_name="__main__")


if __name__ == "__main__":
    main()
