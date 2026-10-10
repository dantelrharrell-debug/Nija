"""Content-free tracker identity diagnostics; never publishes readiness proof."""
from __future__ import annotations

from collections import OrderedDict
import hashlib
import logging
import os
import threading
from typing import Any

LOGGER = logging.getLogger("nija.account_state_diagnostics")
_MAX_TRACKER_READ_SIGNATURES = 2048
_TRACKER_READ_SIGNATURES: OrderedDict[tuple[Any, ...], None] = OrderedDict()
_TRACKER_READ_SIGNATURES_LOCK = threading.Lock()


def log_tracker_read(tracker: Any, read_point: str, *, force: bool = False) -> None:
    """Correlate process-local identities and redacted paths without account contents."""
    if tracker is None:
        return
    try:
        storage = os.path.abspath(str(getattr(tracker, "storage_file", "") or ""))
        store = getattr(tracker, "_nija_account_entry_store_v289", None)
        if store is None:
            store = getattr(tracker, "_eps", None)
        entry = os.path.abspath(str(getattr(store, "_data_file", "") or ""))
        scope = str(getattr(tracker, "_nija_account_scope_v289", "") or "")
        fingerprint = lambda text: hashlib.sha256(text.encode()).hexdigest()
        directory = os.path.dirname(storage)
        location = directory if directory in {
            "/data/positions", "/app/data/positions", "/data", "/app/data"
        } else "other_redacted_directory"
        signature = (
            read_point, id(tracker), id(store) if store is not None else None,
            fingerprint(scope), fingerprint(storage), fingerprint(entry), location,
        )
        with _TRACKER_READ_SIGNATURES_LOCK:
            if signature in _TRACKER_READ_SIGNATURES:
                _TRACKER_READ_SIGNATURES.move_to_end(signature)
                if not force:
                    return
            _TRACKER_READ_SIGNATURES[signature] = None
            if len(_TRACKER_READ_SIGNATURES) > _MAX_TRACKER_READ_SIGNATURES:
                _TRACKER_READ_SIGNATURES.popitem(last=False)
        LOGGER.info(
            "ACCOUNT_STATE_TRACKER_READ point=%s pid=%d tracker_id=%s entry_store_id=%s "
            "scope_sha256=%s storage_sha256=%s entry_storage_sha256=%s "
            "storage_directory=%s legacy_global_file=%s scoping_is_not_protection_or_durability=true",
            read_point, os.getpid(), hex(id(tracker)), hex(id(store)) if store is not None else "missing",
            fingerprint(scope), fingerprint(storage), fingerprint(entry), location,
            str(os.path.basename(storage) == "positions.json").lower(),
        )
    except Exception:
        LOGGER.warning("ACCOUNT_STATE_TRACKER_READ diagnostic_unavailable=true")
