#!/usr/bin/env python3
"""Preserve last-good Kraken position readiness only during the exact active refresh.

Production after v398 proved the remaining readiness oscillation is not a stale
snapshot problem. v286 begins a genuine authenticated Kraken refresh while a
previous v285 snapshot is still current; legacy startup reconciliation can
transiently clear the adoption/fetch flags before that same flight completes.
v285 therefore reports platform:kraken unready during the read pre-wait even
though no completed broker failure has occurred.

v399 narrows that classification gap. A transiently cleared startup flag may be
ignored only when ALL of the following remain true:
  * broker is Kraken;
  * v286's last completed strong proof for this exact broker was ready;
  * the existing v285 authoritative snapshot is still current under the original
    unchanged TTL;
  * the exact v286 authoritative flight for this broker is still active;
  * the flight has no error and its completion event is not set.

A completed error, missing prior-good proof, absent flight, disconnected broker,
or stale snapshot still fails closed immediately. v399 never advances snapshot
time/generation, never creates a position, never submits/cancels an order, and
never changes Kraken rate limits, transport timeouts, risk, kill-switch, writer,
nonce, capital, execution, order/fill or protective-exit gates.

v407 additionally repairs a restart/reconciliation liveness defect in v288. A
genuine authenticated bulk cost-basis result was cached by Python object id, so
recreated user broker objects could miss the completed result and start another
history flight forever. v407 changes only that cache/single-flight identity to
the stable Kraken account_identifier when present. It does not create, infer,
or alter any cost basis; every reused value must still originate from v288/v304
authenticated history and remain within the unchanged v288 cache TTL.
"""
from __future__ import annotations

import py_compile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "bot" / "runtime_authoritative_position_coverage_v285_patch.py"
TARGET_V288 = ROOT / "bot" / "runtime_kraken_cost_basis_bulk_v288_patch.py"
MARKER = "20260907-kraken-inflight-readiness-v399"
V407_MARKER = "20260908-kraken-cost-basis-stable-account-cache-v407"

OLD = '''def _strong_broker_proof(broker: Any) -> tuple[bool, str]:\n    if broker is None:\n        return False, "broker_missing"\n    if not _connected(broker):\n        return False, "disconnected"\n    if getattr(broker, "_startup_position_sync_fetch_ok", None) is not True:\n        exact = str(getattr(broker, "_startup_position_sync_error", "") or "").strip()\n        return False, exact or "authoritative_position_fetch_unproven"\n    if getattr(broker, "_startup_position_sync_adopted", None) is not True:\n        exact = str(getattr(broker, "_startup_position_sync_error", "") or "").strip()\n        return False, exact or "position_snapshot_not_adopted"\n    if not hasattr(broker, "_startup_position_sync_symbols"):\n        return False, "authoritative_snapshot_symbols_missing"\n    snapshot_ok, reason, _rows, _age, _generation = _snapshot_status(broker)\n    if not snapshot_ok:\n        return False, reason\n    return True, "authoritative_current_position_snapshot_adopted"\n'''

NEW = '''def _v399_current_snapshot_refresh_inflight(broker: Any) -> bool:\n    # Preserve only already-proven truth while the same authenticated Kraken\n    # refresh is genuinely still running. This is not a grace period: v285's\n    # original snapshot TTL remains authoritative and no timestamp is advanced.\n    if broker is None or not _connected(broker):\n        return False\n    broker_type = _label(getattr(broker, "broker_type", ""))\n    if broker_type != "kraken" and type(broker).__name__.lower() != "krakenbroker":\n        return False\n    snapshot_ok, _reason, _rows, _age, _generation = _snapshot_status(broker)\n    if not snapshot_ok:\n        return False\n    try:\n        v286 = importlib.import_module("bot.runtime_kraken_position_refresh_liveness_v286_patch")\n        last_ready = getattr(v286, "_LAST_PROOF_READY", None)\n        flights = getattr(v286, "_AUTH_FLIGHTS", None)\n        lock = getattr(v286, "_AUTH_LOCK", None)\n        if not isinstance(last_ready, dict) or last_ready.get(id(broker)) is not True:\n            return False\n        if not isinstance(flights, dict) or lock is None:\n            return False\n        with lock:\n            flight = flights.get(id(broker))\n            if not isinstance(flight, dict):\n                return False\n            event = flight.get("event")\n            if event is None or not callable(getattr(event, "is_set", None)):\n                return False\n            if bool(event.is_set()) or flight.get("error") is not None:\n                return False\n            started = _float(flight.get("started_at"), 0.0)\n            return started > 0.0\n    except Exception:\n        return False\n\n\ndef _strong_broker_proof(broker: Any) -> tuple[bool, str]:\n    if broker is None:\n        return False, "broker_missing"\n    if not _connected(broker):\n        return False, "disconnected"\n    if getattr(broker, "_startup_position_sync_fetch_ok", None) is not True:\n        if _v399_current_snapshot_refresh_inflight(broker):\n            return True, "authoritative_current_position_snapshot_refresh_inflight_v399"\n        exact = str(getattr(broker, "_startup_position_sync_error", "") or "").strip()\n        return False, exact or "authoritative_position_fetch_unproven"\n    if getattr(broker, "_startup_position_sync_adopted", None) is not True:\n        if _v399_current_snapshot_refresh_inflight(broker):\n            return True, "authoritative_current_position_snapshot_refresh_inflight_v399"\n        exact = str(getattr(broker, "_startup_position_sync_error", "") or "").strip()\n        return False, exact or "position_snapshot_not_adopted"\n    if not hasattr(broker, "_startup_position_sync_symbols"):\n        return False, "authoritative_snapshot_symbols_missing"\n    snapshot_ok, reason, _rows, _age, _generation = _snapshot_status(broker)\n    if not snapshot_ok:\n        return False, reason\n    return True, "authoritative_current_position_snapshot_adopted"\n'''


def _patch_v407_stable_cost_basis_cache() -> bool:
    text = TARGET_V288.read_text(encoding="utf-8")
    if V407_MARKER in text:
        return False

    anchor = '''def _is_kraken(broker: Any) -> bool:\n    real = _real_broker(broker)\n    if real is None:\n        return False\n    if _label(getattr(real, "broker_type", "")) == "kraken":\n        return True\n    return type(real).__name__.lower() == "krakenbroker"\n\n\n'''
    if anchor not in text:
        raise SystemExit("v407 expected v288 kraken identity anchor missing")

    helper = anchor + '''# v407: a completed genuine authenticated history result follows the Kraken\n# account across reconciliation wrapper recreation. This key carries identity\n# only and never supplies, validates, or fabricates an entry price.\ndef _stable_bulk_key_v407(real: Any) -> Any:\n    account = str(getattr(real, "account_identifier", "") or "").strip().lower()\n    if account:\n        return ("kraken-account", account)\n    return ("broker-object", id(real))\n\n\n'''
    text = text.replace(anchor, helper, 1)

    old_key = "    key = id(real)\n"
    if text.count(old_key) < 1:
        raise SystemExit("v407 expected v288 object-id cache key missing")
    text = text.replace(old_key, "    key = _stable_bulk_key_v407(real)\n", 1)

    marker_anchor = 'MARKER = "20260830-kraken-cost-basis-bulk-v288"\n'
    if marker_anchor not in text:
        raise SystemExit("v407 expected v288 marker anchor missing")
    text = text.replace(
        marker_anchor,
        marker_anchor + f'V407_STABLE_ACCOUNT_CACHE_MARKER = "{V407_MARKER}"\n',
        1,
    )
    TARGET_V288.write_text(text, encoding="utf-8")
    py_compile.compile(str(TARGET_V288), doraise=True)
    return True


def main() -> int:
    text = TARGET.read_text(encoding="utf-8")
    if NEW not in text:
        if text.count(OLD) != 1:
            raise SystemExit("v399 expected exactly one v285 _strong_broker_proof block")
        TARGET.write_text(text.replace(OLD, NEW, 1), encoding="utf-8")
        py_compile.compile(str(TARGET), doraise=True)

    changed_v407 = _patch_v407_stable_cost_basis_cache()
    print(
        f"KRAKEN_INFLIGHT_READINESS_V399_READY marker={MARKER} "
        "prior_good_required=true current_snapshot_required=true exact_active_flight_required=true "
        "completed_failure_preserved=true snapshot_ttl_unchanged=true snapshot_timestamp_unchanged=true "
        "orders_submitted=false orders_cancelled=false readiness_fabricated=false safety_gates_bypassed=false"
    )
    print(
        f"KRAKEN_COST_BASIS_STABLE_ACCOUNT_CACHE_V407_READY marker={V407_MARKER} "
        f"changed={str(changed_v407).lower()} stable_account_identity=true authenticated_history_only=true "
        "cache_ttl_unchanged=true snapshot_ttl_unchanged=true kraken_rate_limits_unchanged=true "
        "orders_submitted=false cost_basis_fabricated=false readiness_fabricated=false "
        "eligibility_fabricated=false safety_gates_bypassed=false"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())