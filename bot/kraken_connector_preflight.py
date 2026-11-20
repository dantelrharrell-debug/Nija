"""Inspect protected Kraken connector files without executing their Python."""
from __future__ import annotations

import hashlib
import json

from bot.kraken_protected_startup_root import (
    MANIFEST_NAME,
    SOURCE_NAME,
    ProtectedStartupDenied,
    _manifest,
    _read_protected,
)
from bot.kraken_startup_receipts import _receipt, verify_startup_receipt_set

PASS = "protected_artifact_signatures_and_source_digest_match"


def inspect_protected_artifacts() -> str:
    """Return a fixed status, not a collector or trading-readiness verdict.

    The caller must use the intended service/release environment and separately
    authenticate its trust anchors, exact image, source owners and underlying
    evidence. The protected source is read as bytes only, never imported.
    """
    try:
        manifest_bytes = _read_protected(MANIFEST_NAME, 65536)
    except FileNotFoundError:
        return "protected_manifest_missing"
    except (OSError, ValueError):
        return "protected_manifest_unreadable_or_unsafe"

    try:
        trust, receipts = _manifest(manifest_bytes)
    except (ValueError, TypeError, OverflowError, RecursionError):
        return "protected_manifest_invalid"

    if not verify_startup_receipt_set(receipts, trust):
        return "protected_receipts_or_runtime_scope_denied"

    try:
        source = _read_protected(SOURCE_NAME, 131072)
    except FileNotFoundError:
        return "protected_source_missing"
    except (OSError, ProtectedStartupDenied):
        return "protected_source_unreadable_or_unsafe"

    review = _receipt(receipts["independent_review"])["payload"]
    if review["artifact_sha256"] != hashlib.sha256(source).hexdigest():
        return "protected_source_digest_mismatch"
    if not verify_startup_receipt_set(receipts, trust):
        return "protected_receipts_or_runtime_scope_denied"
    return PASS


def main() -> int:
    """Print only status labels; configuration and evidence never leave the host."""
    status = inspect_protected_artifacts()
    print(json.dumps({
        "status": status,
        "source_executed": False,
        "collector_checked": False,
        "authorizes_orders": False,
    }, sort_keys=True))
    return 0 if status == PASS else 1


if __name__ == "__main__":
    raise SystemExit(main())
