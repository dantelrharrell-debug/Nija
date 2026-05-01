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


def hard_exit(msg: str) -> None:
    """Print a highly visible error with a stack trace then exit with code 1.

    Use this instead of bare exit(0) / sys.exit(0) for any *unexpected* early
    exit so the line that triggered the stop is always visible in Railway logs.
    """
    print(f"❌ HARD EXIT: {msg}", flush=True)
    _sys.stderr.write(f"❌ HARD EXIT: {msg}\n")
    _sys.stderr.flush()
    traceback.print_stack()
    _sys.exit(1)


def main() -> None:
    """Delegate execution to bot.py while preserving visible startup logs."""
    print("🔥 BOOT START", flush=True)
    logger.critical("🔥 BOOT START")

    print("STEP 1: imports done", flush=True)

    # Ensure project root is importable so bot.py's relative imports work.
    if _ROOT not in _sys.path:
        _sys.path.insert(0, _ROOT)

    print("STEP 2: loading bot.py...", flush=True)
    runpy.run_path(os.path.join(_ROOT, "bot.py"), run_name="__main__")
    print("STEP 3: bot.py returned (process will exit normally)", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        raise
