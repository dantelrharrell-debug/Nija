"""
Minimal append-only execution journal.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("nija.execution.journal")

ALLOWED_EVENT_TYPES = frozenset(
    {
        "intent_created",
        "intent_accepted",
        "order_submitted",
        "broker_ack",
        "fill_received",
        "final_state",
    }
)


class ExecutionJournal:
    """Append-only execution intent ledger."""

    def __init__(self, path: Optional[str] = None) -> None:
        self._path = str(path if path is not None else os.getenv("NIJA_EXECUTION_JOURNAL_PATH", "")).strip()
        self._lock = threading.Lock()
        self._in_memory_events: List[Dict[str, Any]] = []

    def append(
        self,
        event_type: str,
        intent_id: str,
        payload: Optional[Dict[str, Any]] = None,
        ts: Optional[str] = None,
    ) -> Dict[str, Any]:
        event_name = str(event_type or "").strip()
        if event_name not in ALLOWED_EVENT_TYPES:
            raise ValueError(f"unsupported execution journal event_type: {event_name}")

        record: Dict[str, Any] = {
            "event_type": event_name,
            "intent_id": str(intent_id or "").strip(),
            "ts": ts or datetime.now(timezone.utc).isoformat(),
            "payload": payload or {},
        }

        with self._lock:
            if self._path:
                try:
                    os.makedirs(os.path.dirname(self._path) or ".", exist_ok=True)
                    with open(self._path, "a", encoding="utf-8") as fh:
                        fh.write(json.dumps(record, sort_keys=True) + "\n")
                except Exception as exc:
                    logger.warning("ExecutionJournal file append failed; using in-memory fallback: %s", exc)
                    self._in_memory_events.append(record)
            else:
                self._in_memory_events.append(record)

        return dict(record)


_journal_singleton: Optional[ExecutionJournal] = None
_singleton_lock = threading.Lock()


def get_execution_journal() -> ExecutionJournal:
    global _journal_singleton
    if _journal_singleton is not None:
        return _journal_singleton
    with _singleton_lock:
        if _journal_singleton is None:
            _journal_singleton = ExecutionJournal()
    return _journal_singleton


def append_execution_journal_event(
    event_type: str,
    intent_id: str,
    payload: Optional[Dict[str, Any]] = None,
    ts: Optional[str] = None,
) -> None:
    try:
        get_execution_journal().append(event_type=event_type, intent_id=intent_id, payload=payload, ts=ts)
    except Exception:
        logger.debug("ExecutionJournal append failed", exc_info=True)

