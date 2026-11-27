"""Private, immutable response archives for interrupted Kraken history reads.

Archives preserve input for later reconciliation. They are never completion,
identity, current-holdings or trading certificates and are never replayed into
the live collector. Only the existing broker performs network reads.
"""
from __future__ import annotations

from collections.abc import Mapping
import json
import math
import os
from pathlib import Path
import stat
from typing import Any
import uuid

MAX_RESPONSE_BYTES = 1024 * 1024
MAX_JOURNAL_BYTES = 64 * 1024 * 1024
READ_ENDPOINTS = frozenset({"Balance", "TradesHistory", "ClosedOrders", "Ledgers", "OpenOrders"})


class PrivateHistoryResponseJournal:
    """Fsync each successful read before collection advances to another read.

    Final names are created exclusively; a restarted request cannot replace
    earlier inputs. The caller's existing permanent claim still prevents replay.
    Quotas bound new writes per journal, and persistence failures stop collection.
    """

    def __init__(self, root: Path, request_id: str, account_scope: str) -> None:
        if (type(request_id) is not str or len(request_id) != 32
                or any(c not in "0123456789abcdef" for c in request_id)):
            raise ValueError("history_journal_request_invalid")
        if not (account_scope == "platform:kraken" or (
                isinstance(account_scope, str) and account_scope.startswith("user:")
                and account_scope.endswith(":kraken") and len(account_scope.split(":")) == 3
                and bool(account_scope.split(":")[1]) and not any(c.isspace() for c in account_scope))):
            raise ValueError("history_journal_scope_invalid")
        self._root = Path(root)
        if not self._root.is_absolute() or self._root.resolve() != self._root or self._root.is_symlink():
            raise ValueError("history_journal_directory_invalid")
        info = self._root.stat()
        self._require_private_directory(info)
        self._directory_identity = (info.st_dev, info.st_ino)
        self._request_id = request_id
        self._account_scope = account_scope
        self._sequence = 0
        self._bytes = 0

    @staticmethod
    def _require_private_directory(info: os.stat_result) -> None:
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid()
                or stat.S_IMODE(info.st_mode) & 0o077):
            raise ValueError("history_journal_directory_not_private")

    def append(self, endpoint: str, result: Mapping[str, Any], started: float, finished: float) -> None:
        """Archive detached result data without headers, credentials or API errors.

        Endpoint schemas and whole-history consistency are checked by the
        collector afterward. This archive explicitly does not certify either.
        """
        if (endpoint not in READ_ENDPOINTS or not isinstance(result, Mapping)
                or any(type(t) not in (int, float) or not math.isfinite(t) for t in (started, finished))
                or not 0 < started <= finished):
            raise ValueError("history_journal_response_invalid")
        sequence = self._sequence + 1
        payload = {
            "version": 1, "request_id": self._request_id,
            "account_scope_asserted_by_caller": self._account_scope,
            "sequence": sequence, "endpoint": endpoint,
            "request_started_at": started, "response_finished_at": finished,
            "result": dict(result), "diagnostic_only": True,
            "response_schema_verified": False, "complete_collection": False,
            "authenticated_identity_independently_verified": False,
            "trading_authorized": False,
        }
        encoded = json.dumps(payload, sort_keys=True, allow_nan=False).encode("utf-8")
        if len(encoded) > MAX_RESPONSE_BYTES or self._bytes + len(encoded) > MAX_JOURNAL_BYTES:
            raise ValueError("history_journal_size_limit")
        directory = os.open(self._root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        temporary = ".history-response-" + uuid.uuid4().hex + ".tmp"
        created = False
        try:
            info = os.fstat(directory)
            self._require_private_directory(info)
            if (info.st_dev, info.st_ino) != self._directory_identity:
                raise ValueError("history_journal_directory_changed")
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o600, dir_fd=directory)
            created = True
            with os.fdopen(fd, "wb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            target = f"{self._request_id}.response.{sequence:06d}.json"
            os.link(temporary, target, src_dir_fd=directory, dst_dir_fd=directory, follow_symlinks=False)
            os.unlink(temporary, dir_fd=directory)
            created = False
            os.fsync(directory)
            self._sequence = sequence
            self._bytes += len(encoded)
        finally:
            try:
                if created:
                    os.unlink(temporary, dir_fd=directory)
            finally:
                os.close(directory)
