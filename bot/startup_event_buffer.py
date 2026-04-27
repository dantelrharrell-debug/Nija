"""
NIJA Startup Event Buffer  (Requirement A)
==========================================

Single-emitter gate for startup logging.  Buffers all console log records
during each startup phase and flushes them in one burst per phase, eliminating
the Railway log-throttle bursts that occur when 50+ modules each emit their
own ``logger.info("X initialized")`` lines independently.

Key design points
-----------------
* The *file* handler is never intercepted — file writes remain immediate so
  nothing is ever lost.
* ``flush_phase(name)`` emits all buffered records in a single call; the
  console sees one compact block per phase rather than a slow drip.
* ``StartupSnapshot`` (Requirement D) provides structured output: instead of
  N separate "X initialized" INFO lines, callers collect component statuses
  and call ``snapshot.emit(logger)`` once — a ~70-90 % log-volume reduction.
* All public objects are thread-safe.

Usage
-----
::

    # In bot.py, immediately after the console handler is added to the logger:
    from bot.startup_event_buffer import install_startup_buffer
    _startup_buffer = install_startup_buffer(logger, console_handler)

    # … startup phase code …
    _startup_buffer.flush_phase("ENV_VALIDATION")

    # D — snapshot pattern (Execution Layer example):
    snap = StartupSnapshot("Execution Layer")
    snap.record("slippage_model", ok=True)
    snap.record("spread_predictor", ok=True)
    snap.record("liquidity_analyzer", ok=True)
    snap.record("market_impact", ok=True)
    snap.emit(logger)
    # → one INFO line:
    # ✅ Execution Layer Ready {"slippage_model": true, "spread_predictor": true, …}

    # When startup is fully complete, restore normal per-line logging:
    _startup_buffer.uninstall()

Author: NIJA Trading Systems
"""
from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Internal buffering handler
# ---------------------------------------------------------------------------

class _BufferingHandler(logging.Handler):
    """Forwards every LogRecord to StartupEventBuffer instead of emitting."""

    def __init__(self, buf: "StartupEventBuffer") -> None:
        super().__init__()
        self._buf = buf

    def emit(self, record: logging.LogRecord) -> None:
        self._buf._buffer(record)


# ---------------------------------------------------------------------------
# StartupEventBuffer
# ---------------------------------------------------------------------------

class StartupEventBuffer:
    """
    Buffers startup console log records and flushes them in per-phase batches.

    Install once after the logger is configured.  Call ``flush_phase(name)``
    at each natural startup phase boundary to emit a single burst of buffered
    output.  Call ``uninstall()`` before entering the main trading loop to
    restore normal immediate (unbuffered) logging.
    """

    def __init__(self, real_console_handler: logging.Handler) -> None:
        self._real = real_console_handler
        self._records: List[logging.LogRecord] = []
        self._lock = threading.Lock()
        self._shim: Optional[_BufferingHandler] = None
        self._installed_on: Optional[logging.Logger] = None
        self._phase_count = 0
        self._max_lines_per_flush = 0
        self._startup_started_at = time.time()

    def configure(self, *, max_lines_per_flush: int = 0) -> None:
        """Configure phase flush granularity.

        Args:
            max_lines_per_flush: Maximum buffered records to emit per burst.
                ``0`` means emit all records in one burst (default behavior).
        """
        with self._lock:
            self._max_lines_per_flush = max(0, int(max_lines_per_flush))

    # ------------------------------------------------------------------
    # Install / uninstall
    # ------------------------------------------------------------------

    def install(self, log: logging.Logger) -> None:
        """Replace the console handler on *log* with a buffering shim."""
        if self._installed_on is not None:
            return  # already installed; idempotent
        self._shim = _BufferingHandler(self)
        self._shim.setFormatter(self._real.formatter)
        self._shim.setLevel(self._real.level)
        log.removeHandler(self._real)
        log.addHandler(self._shim)
        self._installed_on = log

    def uninstall(self) -> None:
        """
        Flush any remaining buffered records and restore the real console
        handler.  Safe to call multiple times (idempotent after first call).
        """
        if self._shim is None or self._installed_on is None:
            return  # not installed or already uninstalled
        self.flush_phase("STARTUP_COMPLETE")
        log = self._installed_on
        log.removeHandler(self._shim)
        log.addHandler(self._real)
        self._shim = None
        self._installed_on = None

    @property
    def is_installed(self) -> bool:
        return self._installed_on is not None

    # ------------------------------------------------------------------
    # Buffer + flush
    # ------------------------------------------------------------------

    def _buffer(self, record: logging.LogRecord) -> None:
        """Called by _BufferingHandler.emit() — appends to the internal queue."""
        with self._lock:
            self._records.append(record)

    def flush_phase(self, phase_name: str) -> None:
        """
        Emit all buffered records to the real console handler in one burst.

        A single-line phase separator is prepended so operators can see where
        each startup phase begins in the Railway log stream.

        Args:
            phase_name: Human-readable label for the phase just completed,
                        e.g. ``"ENV_VALIDATION"`` or ``"BROKER_REGISTRY"``.
        """
        with self._lock:
            records = self._records[:]
            self._records.clear()

        if not records:
            return

        # Snapshot current chunk size so flush semantics are stable for this phase.
        with self._lock:
            chunk_size = self._max_lines_per_flush

        if chunk_size <= 0:
            chunks = [records]
        else:
            chunks = [records[i:i + chunk_size] for i in range(0, len(records), chunk_size)]

        for idx, chunk in enumerate(chunks, start=1):
            self._phase_count += 1
            elapsed_s = max(0.0, float(chunk[0].created) - self._startup_started_at)
            if len(chunks) == 1:
                sep_msg = (
                    f"{'─' * 16} phase:{phase_name} "
                    f"t+{elapsed_s:.1f}s ({len(chunk)} lines) {'─' * 16}"
                )
            else:
                sep_msg = (
                    f"{'─' * 12} phase:{phase_name} chunk:{idx}/{len(chunks)} "
                    f"t+{elapsed_s:.1f}s ({len(chunk)} lines) {'─' * 12}"
                )

            sep_record = logging.LogRecord(
                name="nija.startup",
                level=logging.INFO,
                pathname="",
                lineno=0,
                msg=sep_msg,
                args=(),
                exc_info=None,
            )
            # Timestamp separator to the first record in the chunk.
            sep_record.created = chunk[0].created
            sep_record.msecs = chunk[0].msecs

            self._real.emit(sep_record)
            for record in chunk:
                self._real.emit(record)

    def buffered_count(self) -> int:
        """Return the number of records currently waiting in the buffer."""
        with self._lock:
            return len(self._records)


# ---------------------------------------------------------------------------
# StartupSnapshot  (Requirement D)
# ---------------------------------------------------------------------------

class StartupSnapshot:
    """
    Collects component initialisation statuses and emits a *single* structured
    INFO line — replacing N × ``logger.info("X initialized")`` calls.

    Example output::

        ✅ Execution Layer Ready {"slippage_model": true, "spread_predictor": true, …}
        ⚠️  Execution Layer Ready {"slippage_model": true, "liquidity_analyzer": "fail: import error"}

    Usage::

        snap = StartupSnapshot("Execution Layer")
        snap.record("slippage_model", True)
        snap.record("spread_predictor", True)
        snap.record("liquidity_analyzer", False, detail="import error")
        snap.emit(logger)
    """

    def __init__(self, layer_name: str) -> None:
        self._name = layer_name
        self._components: Dict[str, Any] = {}

    def record(self, component: str, ok: bool, *, detail: str = "") -> None:
        """
        Register a component's initialisation outcome.

        Args:
            component: Short snake_case component identifier.
            ok:        True if the component initialised successfully.
            detail:    Optional human-readable detail appended on failure.
        """
        if detail:
            self._components[component] = f"{'ok' if ok else 'fail'}: {detail}"
        else:
            self._components[component] = ok

    def all_ok(self) -> bool:
        """Return True only if every recorded component succeeded."""
        return all(v is True for v in self._components.values())

    def emit(self, log: logging.Logger, level: int = logging.INFO) -> None:
        """
        Emit a single structured snapshot line to *log* at *level*.

        The line format is::

            {icon} {LayerName} Ready {json_payload}
        """
        icon = "✅" if self.all_ok() else "⚠️"
        payload = json.dumps(self._components, separators=(", ", ": "))
        log.log(level, "%s %s Ready %s", icon, self._name, payload)

    def as_dict(self) -> Dict[str, Any]:
        """Return a copy of the component-status mapping."""
        return dict(self._components)


# ---------------------------------------------------------------------------
# Process-wide singleton
# ---------------------------------------------------------------------------

_instance: Optional[StartupEventBuffer] = None
_instance_lock = threading.Lock()


def get_startup_buffer() -> Optional[StartupEventBuffer]:
    """Return the process-wide StartupEventBuffer, or None if not installed."""
    return _instance


def install_startup_buffer(
    log: logging.Logger,
    console_handler: logging.Handler,
) -> StartupEventBuffer:
    """
    Create (if needed), install, and return the process-wide
    ``StartupEventBuffer``.

    Safe to call multiple times — only the first call installs the buffer;
    subsequent calls return the existing instance.

    Args:
        log:             The ``logging.Logger`` whose console handler to wrap.
        console_handler: The ``logging.StreamHandler`` targeting stdout that
                         should be temporarily replaced by the buffering shim.
    """
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = StartupEventBuffer(console_handler)
            _instance.install(log)
    return _instance
