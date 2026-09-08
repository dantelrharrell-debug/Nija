#!/usr/bin/env python3
"""Preserve a still-current Kraken authoritative snapshot across transient refresh failure.

v285 currently marks fetch_ok=false immediately when a proactive Kraken position
refresh fails. That revokes readiness even when the previous authenticated
snapshot remains inside the unchanged authoritative snapshot TTL. Production
logs show this causes platform:kraken readiness oscillation between successful
reads.

v399 narrows that behavior only for Kraken: if a prior v285 snapshot is already
authenticated/current, the broker remains connected, rows are present, and the
snapshot has not exceeded the existing max-age policy, a transient refresh
failure records diagnostic error state without invalidating that still-current
proof. Once the original TTL expires, or connectivity is lost, the existing
fail-closed invalidation remains unchanged.
"""
from __future__ import annotations

import py_compile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "bot" / "runtime_authoritative_position_coverage_v285_patch.py"
MARKER = "20260907-kraken-refresh-failure-preserve-current-v399"

OLD = '''def _record_snapshot_failure(broker: Any, reason: str) -> None:\n    try:\n        setattr(broker, "_nija_authoritative_position_snapshot_fetch_ok_v285", False)\n        setattr(broker, "_nija_authoritative_position_snapshot_error_v285", str(reason or "position_snapshot_failed"))\n    except Exception:\n        pass\n'''

NEW = '''def _record_snapshot_failure(broker: Any, reason: str) -> None:\n    # v399: a proactive Kraken refresh failure must not invalidate a previous\n    # authenticated snapshot that is still inside the unchanged v285 TTL.\n    # This preserves existing proof only; it never extends freshness or grants\n    # readiness after expiry/disconnect. Other brokers retain original behavior.\n    try:\n        broker_name = type(broker).__name__.lower()\n        is_kraken = "kraken" in broker_name\n        previously_ok = getattr(broker, "_nija_authoritative_position_snapshot_fetch_ok_v285", None) is True\n        has_rows = hasattr(broker, "_nija_authoritative_position_snapshot_rows_v285")\n        at = _float(getattr(broker, "_nija_authoritative_position_snapshot_at_monotonic_v285", 0.0))\n        age = max(0.0, time.monotonic() - at) if at > 0 else float("inf")\n        max_age = _snapshot_max_age_s()\n        if is_kraken and previously_ok and has_rows and _connected(broker) and at > 0 and age <= max_age:\n            setattr(broker, "_nija_authoritative_position_snapshot_last_refresh_error_v399", str(reason or "position_snapshot_failed"))\n            setattr(broker, "_nija_authoritative_position_snapshot_last_refresh_error_at_v399", time.time())\n            LOGGER.warning(\n                "KRAKEN_POSITION_REFRESH_FAILURE_V399_PRESERVED marker=20260907-kraken-refresh-failure-preserve-current-v399 "\n                "age_s=%.3f max_age_s=%.3f existing_authenticated_snapshot=true freshness_extended=false "\n                "readiness_fabricated=false disconnected_bypass=false safety_gates_bypassed=false reason=%s",\n                age,\n                max_age,\n                str(reason or "position_snapshot_failed"),\n            )\n            return\n        setattr(broker, "_nija_authoritative_position_snapshot_fetch_ok_v285", False)\n        setattr(broker, "_nija_authoritative_position_snapshot_error_v285", str(reason or "position_snapshot_failed"))\n    except Exception:\n        try:\n            setattr(broker, "_nija_authoritative_position_snapshot_fetch_ok_v285", False)\n            setattr(broker, "_nija_authoritative_position_snapshot_error_v285", str(reason or "position_snapshot_failed"))\n        except Exception:\n            pass\n'''


def main() -> int:
    text = TARGET.read_text(encoding="utf-8")
    if NEW in text:
        print(
            f"KRAKEN_REFRESH_FAILURE_PRESERVE_CURRENT_V399_READY marker={MARKER} "
            "kraken_only=true snapshot_ttl_unchanged=true freshness_extended=false "
            "disconnected_fail_closed=true expired_fail_closed=true readiness_fabricated=false "
            "orders_submitted=false safety_gates_bypassed=false"
        )
        return 0
    if text.count(OLD) != 1:
        raise SystemExit("v399 expected exactly one v285 _record_snapshot_failure block")
    TARGET.write_text(text.replace(OLD, NEW, 1), encoding="utf-8")
    py_compile.compile(str(TARGET), doraise=True)
    print(
        f"KRAKEN_REFRESH_FAILURE_PRESERVE_CURRENT_V399_READY marker={MARKER} "
        "kraken_only=true snapshot_ttl_unchanged=true freshness_extended=false "
        "disconnected_fail_closed=true expired_fail_closed=true readiness_fabricated=false "
        "orders_submitted=false safety_gates_bypassed=false"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
