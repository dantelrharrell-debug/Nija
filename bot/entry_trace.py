"""
NIJA Entry-to-Order Trace
=========================

Mandatory runtime trace that guarantees every trading cycle emits exactly
one of four terminal outcomes, providing an auditable log of the full
entry decision path from scan start to order placement (or rejection).

Terminal Outcomes
-----------------
  SCAN_STARTED
      Opening event – emitted at the beginning of every scan cycle before
      any entry decisions are made.  If this is the *only* trace event in
      a cycle the scan was aborted before any entry evaluation ran (e.g.
      no broker connection).

  ENTRY_VETOED(reason=<str>)
      Entry was blocked before or after scanning.  Reasons include the
      portfolio-level safety gate, position-cap enforcement, explicit
      user_mode (management-only), or a Trade Permission Engine rejection.

  ORDER_PLACED(symbol=<str>, side=<str>, score=<float>)
      An order was successfully submitted to the exchange.  Emitted once
      for each order placed, so a cycle that opens two positions emits
      this outcome twice.

  ORDER_REJECTED(symbol=<str>, reason=<str>)
      An order attempt reached the broker but was rejected (execute_action
      returned False).  Causes include broker-side rejection, nonce pause,
      or a downstream filter block.  Emitted once per failed submission.

  SCAN_COMPLETE_NO_SIGNAL(symbols_scored=<int>)
      The full market scan finished but produced no qualifying entry
      signal.  Emitted once at the end of a cycle when entries_taken == 0
      and the scan phase actually ran (i.e. no up-front veto fired).

Guarantee
---------
Every call to ``NijaCoreLoop.run_scan_phase()`` where a broker is
connected will emit ``SCAN_STARTED`` followed by **exactly one** of the
three terminal outcomes above.

All trace lines are written to the ``nija.cycle_trace`` logger at INFO
level, making them easy to filter:

    grep "CYCLE_TRACE" /path/to/nija.log

Author: NIJA Trading Systems
Version: 1.0
Date: April 2026
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any

# Dedicated logger – operators can route this to a separate file or
# monitoring system by configuring the ``nija.cycle_trace`` logger.
_trace_log = logging.getLogger("nija.cycle_trace")


class CycleOutcome(str, Enum):
    """Five possible outcomes of a trading cycle (one opening + four terminal)."""

    SCAN_STARTED = "SCAN_STARTED"
    ENTRY_VETOED = "ENTRY_VETOED"
    ORDER_PLACED = "ORDER_PLACED"
    ORDER_REJECTED = "ORDER_REJECTED"
    SCAN_COMPLETE_NO_SIGNAL = "SCAN_COMPLETE_NO_SIGNAL"


def emit_cycle_trace(outcome: CycleOutcome, **kwargs: Any) -> None:
    """Emit a structured cycle trace log line.

    The line is always written at INFO level to the ``nija.cycle_trace``
    logger so it appears in the main log stream and can be filtered with::

        grep "\\[CYCLE_TRACE\\]"

    Parameters
    ----------
    outcome:
        One of the four ``CycleOutcome`` values.
    **kwargs:
        Arbitrary key=value pairs appended to the trace line.
        Common keys by outcome:

        * ``SCAN_STARTED``            → ``balance``, ``open_positions``, ``symbols``
        * ``ENTRY_VETOED``            → ``reason``
        * ``ORDER_PLACED``            → ``symbol``, ``side``, ``score``
        * ``SCAN_COMPLETE_NO_SIGNAL`` → ``symbols_scored``

    Examples
    --------
    >>> emit_cycle_trace(CycleOutcome.SCAN_STARTED, balance=150.0, open_positions=1, symbols=732)
    >>> emit_cycle_trace(CycleOutcome.ORDER_PLACED, symbol="BTC-USD", side="long", score=87.3)
    >>> emit_cycle_trace(CycleOutcome.ORDER_REJECTED, symbol="ETH-USD", reason="broker_rejection")
    >>> emit_cycle_trace(CycleOutcome.ENTRY_VETOED, reason="safety_gate")
    >>> emit_cycle_trace(CycleOutcome.SCAN_COMPLETE_NO_SIGNAL, symbols_scored=445)
    """
    parts = [outcome.value]
    for key, value in kwargs.items():
        parts.append(f"{key}={value!r}")
    _trace_log.info("[CYCLE_TRACE] %s", " ".join(parts))
