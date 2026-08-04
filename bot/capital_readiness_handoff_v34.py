"""Capital readiness handoff v34.

Publishes canonical capital readiness only after CapitalCSMv2 has accepted a
fresh, positive live snapshot and entered READY. This closes the observer gap
where the CSM was READY while three_venue_execution_readiness still reported
capital_ready=False. It does not synthesize capital or force activation.
"""
from __future__ import annotations

import importlib
import logging
import os
import sys
import threading
import time
from types import ModuleType
from typing import Any

LOGGER = logging.getLogger("nija.capital_readiness_handoff_v34")
MARKER = "20260727-capital-readiness-handoff-v34"
_TARGETS = ("bot.capital_csm_v2", "capital_csm_v2")
_LOCK = threading.RLock()
_STARTED = False


def _state_ready(state: Any) -> bool:
    value = str(getattr(state, "value", state) or "").strip().upper()
    return value == "READY" or value.endswith(".READY")


def _snapshot_valid(snapshot: Any) -> bool:
    try:
        capital = float(getattr(snapshot, "real_capital", 0.0) or 0.0)
        broker_count = int(getattr(snapshot, "broker_count", 0) or 0)
        stale = bool(getattr(snapshot, "is_stale", True))
        return capital > 0.0 and broker_count > 0 and not stale
    except Exception:
        return False


def _publish_ready(source: str, snapshot: Any) -> None:
    capital = float(getattr(snapshot, "real_capital", 0.0) or 0.0)
    broker_count = int(getattr(snapshot, "broker_count", 0) or 0)
    os.environ["CAPITAL_SYSTEM_READY"] = "1"
    os.environ["NIJA_CAPITAL_READY"] = "1"
    os.environ["NIJA_CAPITAL_READINESS_SOURCE"] = source
    os.environ["NIJA_CAPITAL_READINESS_HANDOFF_V34"] = "1"
    LOGGER.info(
        "CAPITAL_READINESS_HANDOFF_V34_READY marker=%s source=%s capital=%.2f broker_count=%d fresh=true",
        MARKER,
        source,
        capital,
        broker_count,
    )
    try:
        readiness = importlib.import_module("three_venue_execution_readiness")
        publish = getattr(readiness, "publish_once", None)
        if callable(publish):
            publish(force=True)
    except Exception as exc:
        LOGGER.warning(
            "CAPITAL_READINESS_HANDOFF_V34_REEVALUATION_DEFERRED marker=%s error=%s:%s",
            MARKER,
            type(exc).__name__,
            exc,
        )


def _patch(module: ModuleType) -> bool:
    cls = getattr(module, "CapitalCSMv2", None)
    if not isinstance(cls, type):
        return False
    original = getattr(cls, "ingest_snapshot", None)
    if not callable(original):
        return False
    if getattr(original, "_nija_capital_readiness_handoff_v34", False):
        return True

    def ingest_snapshot_with_handoff(self: Any, snapshot: Any):
        state = original(self, snapshot)
        latched = bool(getattr(self, "first_snap_accepted", False))
        if latched and _state_ready(state) and _snapshot_valid(snapshot):
            _publish_ready(module.__name__, snapshot)
        return state

    ingest_snapshot_with_handoff._nija_capital_readiness_handoff_v34 = True
    cls.ingest_snapshot = ingest_snapshot_with_handoff
    LOGGER.warning(
        "CAPITAL_READINESS_HANDOFF_V34_PATCHED marker=%s module=%s",
        MARKER,
        module.__name__,
    )
    return True


def _monitor() -> None:
    while True:
        patched = False
        for name in _TARGETS:
            module = sys.modules.get(name)
            if isinstance(module, ModuleType):
                patched = _patch(module) or patched
        if patched:
            os.environ["NIJA_CAPITAL_READINESS_HANDOFF_V34_PATCHED"] = "1"
        time.sleep(1.0)


def install() -> bool:
    global _STARTED
    with _LOCK:
        if not _STARTED:
            thread = threading.Thread(
                target=_monitor,
                name="capital-readiness-handoff-v34",
                daemon=True,
            )
            thread.start()
            _STARTED = thread.is_alive()
    if not _STARTED:
        return False
    os.environ["NIJA_CAPITAL_READINESS_HANDOFF_V34_INSTALLED"] = "1"
    LOGGER.info(
        "CAPITAL_READINESS_HANDOFF_V34_INSTALLED marker=%s fail_closed=true",
        MARKER,
    )
    return True


install_import_hook = install
