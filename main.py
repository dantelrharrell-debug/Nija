"""Production Python entrypoint for NIJA."""

import sys as _sys

print("🔥 PYTHON ENTRYPOINT HIT", flush=True)

import importlib
import logging
import os
import runpy
import traceback
import threading

_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in _sys.path:
    _sys.path.insert(0, _ROOT)

logger = logging.getLogger(__name__)


def _run_pre_startup_sanitization() -> None:
    """Sanitize live Redis bypass flags before startup safety initializes."""

    try:
        sanitizer = importlib.import_module("bot.strict_live_startup_sanitizer")
        sanitizer.sanitize("main_pre_startup_runtime_safety")
    except Exception as exc:
        logger.warning("Strict live startup sanitizer unavailable before startup safety init: %s", exc)


def _install_strategy_publication() -> None:
    """Install the live strategy publication hook before bot.py is executed."""

    try:
        publisher = importlib.import_module("bot.strategy_publication_patch")
        installer = getattr(publisher, "install_import_hook", None)
        if callable(installer):
            installer()
            print("STRATEGY_PUBLICATION_INSTALL_REQUESTED", flush=True)
            logger.warning("STRATEGY_PUBLICATION_INSTALL_REQUESTED")
        else:
            logger.warning("STRATEGY_PUBLICATION_INSTALL_SKIPPED installer_missing")
    except Exception as exc:
        logger.warning("STRATEGY_PUBLICATION_INSTALL_FAILED err=%s", exc)


_run_pre_startup_sanitization()
_install_strategy_publication()
from bot.startup_runtime_safety import normalize_runtime_startup_env

# ── MODULE-LEVEL STARTUP DIAGNOSTICS ─────────────────────────────────────────
# Emitted at import time so we can confirm main.py is being loaded and identify
# the Python version, PID, and thread context before any bot code runs.
import sys as _sys_diag
print(
    f"DIAG_MAIN_MODULE_IMPORT: main.py imported "
    f"pid={os.getpid()} "
    f"python={_sys_diag.version.split()[0]} "
    f"thread={threading.current_thread().name} "
    f"thread_id={threading.get_ident()} "
    f"__name__={__name__!r} "
    f"__file__={__file__!r}",
    flush=True,
)
for _note in normalize_runtime_startup_env(os.environ):
    print(f"STARTUP_ENV_SAFETY: {_note}", flush=True)
print(
    f"DIAG_MAIN_ENV_STARTUP: "
    f"RAILWAY_DEPLOYMENT_ID={os.environ.get('RAILWAY_DEPLOYMENT_ID', '<unset>')} "
    f"RAILWAY_SERVICE_ID={os.environ.get('RAILWAY_SERVICE_ID', '<unset>')} "
    f"RAILWAY_REPLICA_ID={os.environ.get('RAILWAY_REPLICA_ID', '<unset>')} "
    f"LIVE_CAPITAL_VERIFIED={os.environ.get('LIVE_CAPITAL_VERIFIED', '<unset>')} "
    f"DRY_RUN_MODE={os.environ.get('DRY_RUN_MODE', '<unset>')} "
    f"FORCE_TRADE={os.environ.get('FORCE_TRADE', '<unset>')} "
    f"HF_SCALP_MODE={os.environ.get('HF_SCALP_MODE', '<unset')}",
    flush=True,
)


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
    print(
        f"DIAG_MAIN_FUNC_ENTRY: main() called in main.py "
        f"pid={os.getpid()} "
        f"thread={threading.current_thread().name} "
        f"thread_id={threading.get_ident()}",
        flush=True,
    )

    print("STEP 1: imports done", flush=True)

    # Ensure project root is importable so bot.py's relative imports work.
    if _ROOT not in _sys.path:
        _sys.path.insert(0, _ROOT)

    print("STEP 2: loading bot.py...", flush=True)
    print(
        f"DIAG_RUNPY_BEFORE: about to call runpy.run_path('bot.py', run_name='__main__') "
        f"pid={os.getpid()} "
        f"thread={threading.current_thread().name}",
        flush=True,
    )
    runpy.run_path(os.path.join(_ROOT, "bot.py"), run_name="__main__")
    print("STEP 3: bot.py returned (process will exit normally)", flush=True)
    print(
        f"DIAG_RUNPY_AFTER: runpy.run_path('bot.py') returned normally "
        f"pid={os.getpid()} "
        f"thread={threading.current_thread().name}",
        flush=True,
    )


if __name__ == "__main__":
    print(
        f"DIAG_MAIN_PY_DUNDER_MAIN: __name__=='__main__' block executing in main.py "
        f"pid={os.getpid()} "
        f"thread={threading.current_thread().name}",
        flush=True,
    )
    try:
        main()
    except Exception:
        traceback.print_exc()
        raise
