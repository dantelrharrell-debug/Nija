"""
bot/init_registry.py — Global Initialization Authority Layer
=============================================================

Single source of truth for which subsystems have been initialized.
All module bootstraps MUST go through InitRegistry.run_once(); direct
initialization calls are forbidden after this module is adopted.

Usage
-----
    from bot.init_registry import InitRegistry

    def _do_ecel_init() -> None:
        from bot.ecel_execution_compiler import get_ecel_execution_compiler
        get_ecel_execution_compiler()   # triggers lazy singleton build

    InitRegistry.run_once("ECEL", _do_ecel_init)

Design rules
------------
- Exactly one call to fn() per key, across all threads, for the lifetime of the process.
- All calls are serialized through a single lock; callers in parallel get one winner and
  all others are no-ops.
- Detection logging: every call prints a clear ✅ or ⚠️ line so duplicate init attempts
  are immediately visible in logs.
- Keys are UPPER_SNAKE_CASE strings (e.g. "ECEL", "MABM", "RISK").
"""

from __future__ import annotations

import logging
import threading
from typing import Callable, Set

logger = logging.getLogger("nija.init_registry")


class InitRegistry:
    """Process-global initialization registry.

    Thread-safe.  All public methods are class-methods — no instance required.
    """

    _initialized: Set[str] = set()
    _lock: threading.Lock = threading.Lock()

    @classmethod
    def run_once(cls, key: str, fn: Callable[[], None]) -> bool:
        """Run *fn* exactly once for *key*.

        Returns
        -------
        True  — fn was executed (first call for this key).
        False — key was already initialized; fn was NOT called.
        """
        with cls._lock:
            if key in cls._initialized:
                logger.warning("⚠️  SKIPPING DUPLICATE INIT: %s", key)
                return False

            logger.info("✅ INITIALIZING: %s", key)
            try:
                fn()
            except Exception as exc:
                # Do NOT add key to _initialized so a retry is possible after fixing the
                # root cause; but re-raise so the caller's error path is triggered.
                logger.error("❌ INIT FAILED: %s — %s", key, exc)
                raise
            cls._initialized.add(key)
            return True

    @classmethod
    def is_initialized(cls, key: str) -> bool:
        """Return True if *key* has already been initialized."""
        with cls._lock:
            return key in cls._initialized

    @classmethod
    def reset(cls) -> None:
        """Reset registry state (test use only — never call from production code)."""
        with cls._lock:
            cls._initialized.clear()
            logger.warning("⚠️  InitRegistry.reset() called — only valid in tests")
