"""Single-use account/key comparison through the existing Kraken nonce owner.

An explicit private request permits one GetApiKeyInfo read. The saved binding
is comparison input, not proof of independent approval. The result never
installs a collector, changes the binding, publishes readiness or permits orders.
"""
from __future__ import annotations

import datetime as dt
import fcntl
import hashlib
import json
import logging
import math
import os
from pathlib import Path
import stat
import time
from typing import Any, Iterable

from bot.durable_recovery_state import write_recovery_state
from bot.kraken_authenticated_identity_v480 import (
    KrakenIdentityDenied, make_kraken_account_identity_provider,
)
from bot.kraken_live_history_recovery import _private_regular, _request, _unique_keys
from scripts.nija_kraken_readonly_history_collector_v441 import _broker_account_scope

LOGGER = logging.getLogger(__name__)
BINDING_NAME = "approved-binding-platform-20261028.json"
PROVIDER_ID = "kraken-account-identity-v480-private-recovery-v491"
_BINDING_FIELDS = {
    "account_scope", "approval_source", "approved_account_iiban_sha256",
    "approved_api_key_sha256", "approved_at_utc", "authenticated_identity_match_verified",
    "independent_statement_reference", "runtime_collector_installed", "trading_authorized",
}
_IDENTITY_DENIALS = frozenset({
    "authenticated_client_unavailable", "broker_scope_mismatch", "broker_scope_changed",
    "authenticated_identity_read_failed", "authenticated_identity_read_unverified",
    "authenticated_api_key_identity_missing", "approved_api_key_identity_mismatch",
    "approved_broker_account_mismatch", "key_expiry_unverified", "key_expired",
    "authenticated_account_identifier_invalid", "observation_clock_invalid",
    "observation_clock_invalid_or_stale",
})


def _binding(root: Path, now: float) -> tuple[dict[str, Any], str]:
    """Read bounded comparison pins without exporting key or account material."""
    fd = os.open(root / BINDING_NAME, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        _private_regular(fd)
        before = os.fstat(fd)
        if before.st_size > 4096:
            raise ValueError("binding_invalid")
        raw = os.read(fd, 4097)
        after = os.fstat(fd)
        if (len(raw) != before.st_size or len(raw) > 4096
                or (before.st_ino, before.st_mtime_ns, before.st_ctime_ns)
                != (after.st_ino, after.st_mtime_ns, after.st_ctime_ns)):
            raise ValueError("binding_invalid")
    finally:
        os.close(fd)
    row = json.loads(raw, object_pairs_hook=_unique_keys)
    if not isinstance(row, dict) or set(row) != _BINDING_FIELDS:
        raise ValueError("binding_invalid")
    if row["account_scope"] != "platform:kraken" or row["trading_authorized"] is not False:
        raise ValueError("binding_invalid")
    for field in ("approved_account_iiban_sha256", "approved_api_key_sha256"):
        value = row[field]
        if (type(value) is not str or len(value) != 64
                or any(c not in "0123456789abcdefABCDEF" for c in value)):
            raise ValueError("binding_invalid")
    for field in ("approval_source", "independent_statement_reference", "approved_at_utc"):
        if type(row[field]) is not str or not row[field].strip() or len(row[field]) > 1024:
            raise ValueError("binding_invalid")
    approved = dt.datetime.fromisoformat(row["approved_at_utc"].replace("Z", "+00:00"))
    if approved.tzinfo is None or not 0 < approved.timestamp() <= now:
        raise ValueError("binding_invalid")
    if any(type(row[field]) is not bool for field in (
        "authenticated_identity_match_verified", "runtime_collector_installed",
    )):
        raise ValueError("binding_invalid")
    return row, hashlib.sha256(raw).hexdigest()


def collect_requested_identity(
    directory: Path, brokers: Iterable[Any], *, monitoring_category: Any,
    now: float | None = None,
) -> bool:
    """Consume one private request; compare the authenticated account and key.

    Use the caller's existing serialized broker and monitoring category. The
    comparison does not independently approve the saved inventory or supply
    any of the other twelve certification fields. Failed claims are never replayed.
    """
    root = Path(directory)
    if not root.is_absolute() or root.is_symlink() or root.resolve() != root:
        raise ValueError("identity_recovery_root_invalid")
    info = root.stat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) & 0o077):
        raise ValueError("identity_recovery_root_not_private")
    fd = os.open(root / "collector.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        _private_regular(fd)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        stamp = time.time() if now is None else now
        if type(stamp) not in (int, float) or not math.isfinite(stamp):
            raise ValueError("identity_recovery_clock_invalid")
        row = _request(root, stamp, filename="identity_request.json")
        if row is None:
            return False
        if (row["account_scope"] != "platform:kraken" or row["max_pages"] != 1
                or row.get("use_cursor", False) is not False):
            raise ValueError("identity_request_scope_or_budget_invalid")
        selected = []
        for broker in brokers:
            try:
                matches = (_broker_account_scope(broker) == "platform:kraken"
                           and getattr(broker, "connected", False) is True)
            except (ValueError, AttributeError):
                matches = False
            if matches and all(broker is not other for other in selected):
                selected.append(broker)
        if len(selected) != 1 or monitoring_category is None:
            return False
        identity = row["request_id"]
        claim = root / (identity + ".identity.claimed.json")
        output = root / (identity + ".identity.evidence.json")
        if any(path.exists() or path.is_symlink() for path in (claim, output)):
            raise ValueError("identity_request_replay")
        os.link(root / "identity_request.json", claim, follow_symlinks=False)
        (root / "identity_request.json").unlink()
        dirfd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(dirfd)
        finally:
            os.close(dirfd)
        if _request(root, stamp, filename=claim.name) != row:
            raise ValueError("identity_claim_changed")
        receipt = {
            "request_id": identity, "account_scope": "platform:kraken",
            "diagnostic_only": True, "independent_certification_complete": False,
            "collector_installed": False, "trading_authorized": False,
        }
        try:
            binding, digest = _binding(root, stamp)
            provider = make_kraken_account_identity_provider(
                selected[0], account_scope="platform:kraken",
                approved_api_key_sha256=binding["approved_api_key_sha256"],
                approved_iban_sha256=binding["approved_account_iiban_sha256"],
                reviewed_provider_id=PROVIDER_ID, monitoring_category=monitoring_category,
            )
            observation = provider()
            # Detect replacement of approved inputs during the authenticated read.
            if _binding(root, time.time())[1] != digest:
                raise ValueError("binding_changed")
            receipt.update({
                "collection_succeeded": True, "configured_account_and_key_match": True,
                "binding_record_sha256": digest, "observation": dict(observation),
            })
        except Exception as exc:
            code = "identity_comparison_failed"
            if type(exc) is KrakenIdentityDenied and str(exc) in _IDENTITY_DENIALS:
                code = str(exc)
            receipt.update({"collection_succeeded": False, "failure_code": code})
        write_recovery_state(output, receipt)
        LOGGER.info(
            "KRAKEN_IDENTITY_RECOVERY_FINISHED succeeded=%s diagnostic_only=true trading_authorized=false",
            receipt["collection_succeeded"],
        )
        return True
    finally:
        os.close(fd)
