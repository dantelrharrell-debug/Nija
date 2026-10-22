"""Opt-in historical reads through an already running Kraken broker.

No broker construction, credentials, network listener, ledger mutation or
authorization. Private local requests are claimed before any authenticated
read. Interrupted requests remain claimed for operator review, never replayed.
The evidence retains the collector's explicit identity/completeness limits.
"""
from __future__ import annotations

import fcntl
import json
import logging
import math
import os
from pathlib import Path
import stat
import time
from typing import Any, Iterable

from .durable_recovery_state import write_recovery_state
from scripts.nija_kraken_readonly_history_collector_v441 import (
    _broker_account_scope, collect_from_existing_broker, history_failure_diagnostic,
)

LOGGER = logging.getLogger(__name__)

MAX_REQUEST_BYTES = 4096
MAX_PAGES = 10
REQUEST_TTL_S = 300


def _private_regular(fd: int) -> None:
    """Reject shared, foreign-owned and nonregular request/lock files."""
    info = os.fstat(fd)
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) & 0o077 or info.st_nlink != 1):
        raise ValueError("recovery_file_not_private_regular")


def _unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("recovery_request_duplicate_key")
        result[key] = value
    return result


def _request(root: Path, now: float, filename: str = "request.json") -> dict[str, Any] | None:
    """Read one bounded, private request; do not create an empty replacement."""
    try:
        fd = os.open(root / filename, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return None
    try:
        _private_regular(fd)
        before = os.fstat(fd)
        if before.st_size > MAX_REQUEST_BYTES:
            raise ValueError("recovery_request_too_large")
        raw = os.read(fd, MAX_REQUEST_BYTES + 1)
        after = os.fstat(fd)
        if (before.st_size != len(raw) or len(raw) > MAX_REQUEST_BYTES
                or before.st_mtime_ns != after.st_mtime_ns
                or before.st_ctime_ns != after.st_ctime_ns):
            raise ValueError("recovery_request_changed")
    finally:
        os.close(fd)
    row = json.loads(raw, object_pairs_hook=_unique_keys)
    if not isinstance(row, dict) or set(row) != {"request_id", "account_scope", "created_at", "max_pages"}:
        raise ValueError("recovery_request_schema_invalid")
    identity = row["request_id"]
    scope = row["account_scope"]
    stamp = row["created_at"]
    pages = row["max_pages"]
    if (not isinstance(identity, str) or len(identity) != 32
            or any(c not in "0123456789abcdef" for c in identity)):
        raise ValueError("recovery_request_id_invalid")
    if (not isinstance(scope, str) or not scope or any(c.isspace() for c in scope)
            or not (scope == "platform:kraken" or (
                len(scope.split(":")) == 3 and scope.startswith("user:")
                and scope.endswith(":kraken") and scope.split(":")[1]))):
        raise ValueError("recovery_request_scope_invalid")
    if (type(stamp) not in (int, float) or not math.isfinite(stamp)
            or type(now) not in (int, float) or not math.isfinite(now)
            or not 0 < stamp <= now or now - stamp > REQUEST_TTL_S):
        raise ValueError("recovery_request_expired_or_invalid")
    if type(pages) is not int or not 1 <= pages <= MAX_PAGES:
        raise ValueError("recovery_request_pages_invalid")
    return row


def collect_requested_history(
    directory: Path, brokers: Iterable[Any], *, monitoring_category: Any,
    now: float | None = None,
) -> bool:
    """Service at most one explicit request using the unique existing broker.

    The composition root supplies existing broker objects and their canonical
    monitoring enum. Scope metadata selects routing; it does not independently
    authenticate brokerage ownership. Output can support later reconciliation,
    but never calls a fill verifier, grants authority or clears pending records.
    """
    root = Path(directory)
    if not root.is_absolute() or root.is_symlink() or root.resolve() != root:
        raise ValueError("recovery_directory_must_be_canonical")
    info = root.stat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) & 0o077):
        raise ValueError("recovery_directory_not_private")
    fd = os.open(root / "collector.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        _private_regular(fd)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        request = _request(root, time.time() if now is None else now)
        if request is None:
            return False
        selected = []
        for broker in brokers:
            try:
                matches = (_broker_account_scope(broker) == request["account_scope"]
                           and getattr(broker, "connected", False) is True)
            except (ValueError, AttributeError):
                matches = False
            if matches and all(broker is not other for other in selected):
                selected.append(broker)
        if len(selected) != 1 or monitoring_category is None:
            # Leave the request pending until a unique canonical client exists.
            return False
        identity = request["request_id"]
        claim = root / (identity + ".claimed.json")
        output = root / (identity + ".evidence.json")
        if claim.exists() or claim.is_symlink() or output.exists() or output.is_symlink():
            raise ValueError("recovery_request_replay")
        # Hard-link creates exclusively. A repeated request ID can never replace
        # a prior claim. Private directory + process lock serializes consumers.
        os.link(root / "request.json", claim, follow_symlinks=False)
        (root / "request.json").unlink()
        dirfd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(dirfd)
        finally:
            os.close(dirfd)
        if _request(root, time.time() if now is None else now, claim.name) != request:
            raise ValueError("recovery_request_changed_before_claim")
        started = time.time()
        try:
            evidence = collect_from_existing_broker(
                selected[0], account_scope=request["account_scope"],
                monitoring_category=monitoring_category,
                max_pages=request["max_pages"], include_balance=True,
            )
        except Exception as exc:
            # Persist only fixed collector-owned diagnostic labels.
            diagnostic = history_failure_diagnostic(exc)
            write_recovery_state(output, {
                "request_id": identity, "collection_succeeded": False,
                "error_type": type(exc).__name__, "trading_authorized": False,
                **diagnostic,
            })
            LOGGER.warning(
                "KRAKEN_HISTORY_COLLECTION_FAILED request_id=%s error_code=%s "
                "error_endpoint=%s trading_authorized=false",
                identity, diagnostic.get("error_code", "unexpected_exception"),
                diagnostic.get("error_endpoint", "unknown"),
            )
            return True
        write_recovery_state(output, {
            "request_id": identity, "collection_succeeded": True,
            "collection_started_at": started, "collection_finished_at": time.time(),
            "evidence": evidence, "trading_authorized": False,
        })
        LOGGER.info("KRAKEN_HISTORY_COLLECTION_COMPLETED request_id=%s trading_authorized=false", identity)
        return True
    finally:
        os.close(fd)
