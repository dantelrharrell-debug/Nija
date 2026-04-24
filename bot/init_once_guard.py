"""
NIJA Init-Once Guard  (Requirement C)
======================================

Prevents any subsystem from being initialised more than once per process
lifetime, eliminating:

* duplicated startup log lines ("X initialized" printed twice)
* overlapping broker-registration paths
* repeated singleton setup calls caused by multiple import paths

Usage — as a decorator
-----------------------
::

    from bot.init_once_guard import init_once_guard

    class BrokerManager:
        @init_once_guard("broker_manager")
        def __init__(self, ...):
            ...

Usage — inline guard
---------------------
When you cannot decorate ``__init__`` directly (e.g. the class is in a
third-party module, or you need a conditional skip rather than an error)::

    from bot.init_once_guard import check_init_once

    def _setup_broker_registry():
        if not check_init_once("broker_registry"):
            return   # already initialised; skip silently
        ...

Behaviour
---------
* **First call**: claimed → function runs normally.
* **Subsequent calls**:
  - ``@init_once_guard(soft=False)``  (default): raises ``InitAlreadyDoneError``.
  - ``@init_once_guard(soft=True)``            : logs WARNING, returns ``None``.
  - ``check_init_once``                        : logs WARNING, returns ``False``.

Thread safety
-------------
All registry mutations are protected by a ``threading.Lock``.

Author: NIJA Trading Systems
"""
from __future__ import annotations

import functools
import logging
import threading
import traceback
from typing import Callable, Dict, Optional, Set, TypeVar

logger = logging.getLogger("nija.init_once_guard")

_F = TypeVar("_F", bound=Callable)


# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------

class InitAlreadyDoneError(RuntimeError):
    """Raised when a hard-guarded component is initialised for a second time."""


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

class _InitRegistry:
    """Thread-safe set of claimed component names plus their first-init stacks."""

    def __init__(self) -> None:
        self._done: Set[str] = set()
        self._traces: Dict[str, str] = {}
        self._lock = threading.Lock()

    def try_claim(self, name: str) -> bool:
        """
        Attempt to claim *name*.

        Returns:
            ``True``  — first call; component may proceed with initialisation.
            ``False`` — already claimed; caller should abort or warn.
        """
        with self._lock:
            if name in self._done:
                return False
            self._done.add(name)
            self._traces[name] = "".join(traceback.format_stack(limit=10))
            return True

    def is_done(self, name: str) -> bool:
        with self._lock:
            return name in self._done

    def first_trace(self, name: str) -> str:
        """Return the call-stack captured at the first (valid) init call."""
        with self._lock:
            return self._traces.get(name, "<no trace recorded>")

    def reset(self, name: str) -> None:
        """
        Allow *name* to be re-initialised.

        Intended **only** for unit tests and clean-restart scenarios.
        Do not call in production code paths.
        """
        with self._lock:
            self._done.discard(name)
            self._traces.pop(name, None)

    def reset_all(self) -> None:
        """Clear all claims (unit-test utility only)."""
        with self._lock:
            self._done.clear()
            self._traces.clear()

    def all_claimed(self) -> Set[str]:
        """Return a snapshot of all currently claimed component names."""
        with self._lock:
            return set(self._done)


# ---------------------------------------------------------------------------
# Singleton factory
# ---------------------------------------------------------------------------

_registry: Optional[_InitRegistry] = None
_registry_lock = threading.Lock()


def get_init_registry() -> _InitRegistry:
    """Return (creating if needed) the process-wide _InitRegistry singleton."""
    global _registry
    if _registry is None:
        with _registry_lock:
            if _registry is None:
                _registry = _InitRegistry()
    return _registry


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def init_once_guard(
    name: str,
    *,
    soft: bool = False,
) -> Callable[[_F], _F]:
    """
    Decorator: ensure the wrapped function runs **at most once** per process.

    Args:
        name: Unique registry key for this component.  Use a stable,
              human-readable string, e.g. ``"broker_manager"`` or
              ``"capital_authority"``.
        soft: When ``True``, a duplicate call logs a WARNING and returns
              ``None`` instead of raising ``InitAlreadyDoneError``.

    Raises:
        InitAlreadyDoneError: On a second call when ``soft=False`` (default).

    Example::

        class BrokerManager:
            @init_once_guard("broker_manager")
            def __init__(self):
                ...
    """
    def decorator(fn: _F) -> _F:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            reg = get_init_registry()
            if not reg.try_claim(name):
                msg = (
                    f"[init_once_guard] '{name}' initialised more than once. "
                    f"First-init call stack:\n{reg.first_trace(name)}"
                )
                if soft:
                    logger.warning(msg)
                    return None  # type: ignore[return-value]
                raise InitAlreadyDoneError(msg)
            return fn(*args, **kwargs)
        return wrapper  # type: ignore[return-value]
    return decorator


def check_init_once(name: str) -> bool:
    """
    Inline (non-decorator) guard for use inside ``__init__`` or factory
    functions when a decorator is not convenient.

    Claims *name* and returns ``True`` on the first call.
    Returns ``False`` (and logs a WARNING) on every subsequent call.

    Example::

        def _setup_broker_registry():
            if not check_init_once("broker_registry"):
                return   # duplicate call; already initialised
            ...   # first-time setup only

    Args:
        name: Component registry key (same as used in ``@init_once_guard``).

    Returns:
        ``True`` if this is the first call for *name*; ``False`` otherwise.
    """
    reg = get_init_registry()
    if not reg.try_claim(name):
        logger.warning(
            "[init_once_guard] '%s' already initialised — skipping duplicate "
            "init. First-init stack:\n%s",
            name,
            reg.first_trace(name),
        )
        return False
    return True
