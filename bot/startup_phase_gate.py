"""
NIJA Startup Phase Gate  (Requirement B)
=========================================

Hard-gates the six startup phases so no subsystem can initialise outside
its assigned phase window.  Currently bot.py only *logs* phases; this
module *enforces* them.

Phases
------
  0  ENV_VALIDATION    – environment variables present and verified
  1  BROKER_REGISTRY   – broker clients created and registered
  2  CAPITAL_BRAIN     – CapitalAuthority / global capital brain hydrated
  3  STRATEGY_ENGINE   – TradingStrategy fully initialised
  4  EXECUTION_LAYER   – ExecutionEngine and all trading threads started
  5  LIVE_ENABLE       – capital gate passed; live trading enabled

Enforcement
-----------
Decorate any subsystem initialiser with ``@require_phase(Phase.X)`` to
make it raise ``PhaseViolationError`` if called before phase X has been
reached::

    from bot.startup_phase_gate import require_phase, Phase

    class CapitalAuthority:
        @require_phase(Phase.BROKER_REGISTRY)
        def __init__(self, ...):
            ...

``advance_phase(to, reason=...)`` is called by ``bot.py`` at each confirmed
transition point.  Phase regressions are rejected.

Thread safety
-------------
All state mutations are protected by a ``threading.Lock``.

Author: NIJA Trading Systems
"""
from __future__ import annotations

import enum
import functools
import logging
import threading
from typing import Callable, Optional, TypeVar

logger = logging.getLogger("nija.startup_phase_gate")

_F = TypeVar("_F", bound=Callable)


# ---------------------------------------------------------------------------
# Phase enum
# ---------------------------------------------------------------------------

class Phase(enum.IntEnum):
    ENV_VALIDATION  = 0   # env vars verified; broker connections may begin
    BROKER_REGISTRY = 1   # brokers registered; capital brain may begin
    CAPITAL_BRAIN   = 2   # capital authority hydrated; strategy engine may begin
    STRATEGY_ENGINE = 3   # strategy fully initialised; execution layer may begin
    EXECUTION_LAYER = 4   # trading threads live; live-enable gate may open
    LIVE_ENABLE     = 5   # live trading enabled


# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------

class PhaseViolationError(RuntimeError):
    """
    Raised when a component attempts to initialise before its required
    startup phase has been reached.
    """


# ---------------------------------------------------------------------------
# _PhaseGate
# ---------------------------------------------------------------------------

class _PhaseGate:
    """Thread-safe singleton tracking and enforcing the current startup phase."""

    def __init__(self) -> None:
        self._current: Phase = Phase.ENV_VALIDATION
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    @property
    def current(self) -> Phase:
        with self._lock:
            return self._current

    def is_at_least(self, minimum: Phase) -> bool:
        """Return True if the gate has already reached or passed *minimum*."""
        with self._lock:
            return self._current >= minimum

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def advance(self, to: Phase, *, reason: str = "") -> None:
        """
        Advance the gate to *to*.

        No-op when already at *to*.  Raises ``PhaseViolationError`` on any
        attempt to regress to an earlier phase.

        Args:
            to:     Target phase.
            reason: Human-readable note logged with the transition.
        """
        with self._lock:
            if to < self._current:
                raise PhaseViolationError(
                    f"Cannot regress startup phase from "
                    f"{self._current.name}({int(self._current)}) to "
                    f"{to.name}({int(to)})"
                )
            if to == self._current:
                return  # idempotent
            prev = self._current
            self._current = to

        logger.info(
            "⚡ [PhaseGate] %s(%d) → %s(%d)%s",
            prev.name, int(prev),
            to.name, int(to),
            f" — {reason}" if reason else "",
        )

    # ------------------------------------------------------------------
    # Enforce
    # ------------------------------------------------------------------

    def require(self, minimum: Phase) -> None:
        """
        Raise ``PhaseViolationError`` if the current phase is below *minimum*.

        Typically called at the very start of a subsystem's ``__init__``
        (or via the ``@require_phase`` decorator) to prevent out-of-order
        initialisation.

        Args:
            minimum: The earliest phase at which the caller is permitted to run.
        """
        with self._lock:
            current = self._current
        if current < minimum:
            raise PhaseViolationError(
                f"Startup phase violation: requires {minimum.name}({int(minimum)}) "
                f"but current phase is {current.name}({int(current)}). "
                f"This component was initialised too early in the boot sequence."
            )


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_gate: Optional[_PhaseGate] = None
_gate_lock = threading.Lock()


def get_phase_gate() -> _PhaseGate:
    """Return (creating if needed) the process-wide _PhaseGate singleton."""
    global _gate
    if _gate is None:
        with _gate_lock:
            if _gate is None:
                _gate = _PhaseGate()
    return _gate


# ---------------------------------------------------------------------------
# Public convenience helpers
# ---------------------------------------------------------------------------

def advance_phase(to: Phase, *, reason: str = "") -> None:
    """
    Convenience wrapper: ``get_phase_gate().advance(to, reason=reason)``.

    Called by ``bot.py`` at confirmed phase-transition checkpoints.
    """
    get_phase_gate().advance(to, reason=reason)


def require_phase(minimum: Phase) -> Callable[[_F], _F]:
    """
    Decorator: raise ``PhaseViolationError`` if the decorated function is
    called before startup phase *minimum* has been reached.

    Example::

        from bot.startup_phase_gate import require_phase, Phase

        class CapitalAuthority:
            @require_phase(Phase.BROKER_REGISTRY)
            def __init__(self):
                ...

    Args:
        minimum: The phase that must be active (or past) before the
                 decorated function is allowed to run.
    """
    def decorator(fn: _F) -> _F:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            get_phase_gate().require(minimum)
            return fn(*args, **kwargs)
        return wrapper  # type: ignore[return-value]
    return decorator
