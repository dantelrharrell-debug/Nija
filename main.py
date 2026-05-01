"""Production Python entrypoint for NIJA."""

import sys as _sys

print("🔥 PYTHON ENTRYPOINT HIT", flush=True)
_sys.stderr.write("🔥 PYTHON ENTRYPOINT HIT (stderr)\n")
_sys.stderr.flush()

import logging
import os
import runpy
import traceback

_ROOT = os.path.dirname(os.path.abspath(__file__))
logger = logging.getLogger(__name__)


def main() -> None:
    """Delegate execution to bot.py while preserving visible startup logs."""
    print("🔥 BOOT START", flush=True)
    logger.critical("🔥 BOOT START")

    # Ensure project root is importable so bot.py's relative imports work.
    if _ROOT not in _sys.path:
        _sys.path.insert(0, _ROOT)

    runpy.run_path(os.path.join(_ROOT, "bot.py"), run_name="__main__")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        raise
