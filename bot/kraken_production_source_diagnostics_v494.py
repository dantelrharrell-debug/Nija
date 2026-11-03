"""Read-only diagnostics for the six missing Kraken production evidence sources.

This module does not produce v452 attestations, install a collector, mutate
ledger or risk state, or authorize orders. It inspects only caller-owned live
objects and the existing read-only ledger preflight. Unsupported evidence
sources remain explicitly blocked rather than being inferred from health flags.
"""
from __future__ import annotations

import json
import os
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from bot.kraken_existing_risk_governor_diagnostic_v492 import (
    inspect_existing_risk_governor,
)
from bot.kraken_sqlite_readonly_preflight_v488 import inspect_kraken_ledger
from bot.pretrade_attestation_validation_v452 import REQUIRED
from scripts.nija_kraken_readonly_history_collector_v441 import (
    _broker_account_scope,
)

_SIX_FIELDS = (
    "position_ledger_reconciliation",
    "duplicate_order_fence",
    "operator_authorization",
    "kill_switch_clear",
    "risk_limits",
    "position_sync",
)


def _result(ready: bool, reason: str, **details: Any) -> dict[str, Any]:
    return {"ready": ready, "reason": reason, **details}


def _valid_identifier(value: Any) -> bool:
    return (
        isinstance(value, str) and bool(value) and value == value.strip()
        and not any(character.isspace() for character in value)
    )


def _inspect_kill_switch(
    kill_switch: Any, redis_client: Any, *, now_epoch: float,
) -> dict[str, Any]:
    """Observe stops without changing them or asserting independent clearance.

    is_active() is deliberately NEVER called: the operational kill switch
    can persist a newly detected filesystem stop from that method. Missing
    Redis records are not clearance evidence. Even a structurally valid
    explicit clear still needs a separately approved account-bound digest and
    reviewer before the v452 kill_switch_clear field can be certified.
    """
    if kill_switch is None or redis_client is None:
        return _result(False, "existing_kill_switch_or_shared_redis_missing")
    key = getattr(kill_switch, "DURABLE_REDIS_KEY", None)
    if not isinstance(key, str) or not key or key != key.strip():
        return _result(False, "durable_kill_switch_key_unavailable")
    try:
        if redis_client.ping() is not True:
            return _result(False, "shared_redis_ping_unverified")
        status_a = kill_switch.get_status()
        status_b = kill_switch.get_status()
        if status_a != status_b:
            return _result(False, "local_kill_switch_changed_during_read")
        if (not isinstance(status_a, Mapping)
                or status_a.get("is_active") is not False
                or status_a.get("kill_file_exists") is not False):
            return _result(False, "local_and_shared_kill_switch_state_not_proven_clear")
        if os.environ.get("NIJA_KILL_SWITCH", "").strip().lower() in {
            "1", "true", "yes", "on",
        }:
            return _result(False, "deployment_kill_switch_active")

        first = redis_client.get(key)
        second = redis_client.get(key)
        if first != second:
            return _result(False, "durable_kill_switch_changed_during_read")
        if first is None:
            return _result(False, "explicit_durable_clearance_record_missing")
        # The same strict parser used by the independently pinned provider
        # rejects active/malformed/duplicate-key/expired-looking clearance
        # payloads. This diagnostic DOES NOT approve the resulting digest.
        from bot.kraken_kill_switch_evidence import (
            KrakenKillSwitchDenied, _clearance,
        )
        try:
            _clearance(first, float(now_epoch))
        except KrakenKillSwitchDenied as exc:
            if str(exc) == "durable_clearance_not_clear":
                return _result(False, "durable_kill_switch_active")
            return _result(False, "durable_kill_switch_record_unverified")
        # A concurrent stop update must not be reported as a stable read.
        if redis_client.get(key) != first or kill_switch.get_status() != status_a:
            return _result(False, "kill_switch_changed_during_read")

        return _result(
            False, "independent_durable_clearance_binding_required",
            observed_at_epoch=float(now_epoch),
            shared_redis_verified=True,
            explicit_clearance_record_observed=True,
            local_kill_file_absent=True,
            independent_clearance_approved=False,
        )
    except Exception:
        # Never print the raw Redis record, local paths, identities, or secrets.
        return _result(False, "kill_switch_read_unverified")


def _inspect_position_sync(
    broker: Any, identity_provider: Any, account_scope: str, *, now_epoch: float,
) -> dict[str, Any]:
    if broker is None or not callable(identity_provider):
        return _result(False, "broker_or_pinned_identity_provider_missing")
    try:
        if _broker_account_scope(broker) != account_scope:
            return _result(False, "broker_account_scope_mismatch")
        identity = identity_provider()
        provenance = identity.get("provenance") if isinstance(identity, Mapping) else None
        stamp = identity.get("observed_at_epoch") if isinstance(identity, Mapping) else None
        if (not isinstance(identity, Mapping)
                or identity.get("account") != account_scope
                or identity.get("source") != "authenticated_broker"
                or identity.get("verified") is not True
                or identity.get("read_only") is not True
                or identity.get("scope_verified") is not True
                or not _valid_identifier(identity.get("provider_id"))
                or not _valid_identifier(identity.get("evidence_id"))
                or not isinstance(provenance, Mapping)
                or any(provenance.get(field) is not True for field in (
                    "account_scope_verified", "collector_identity_verified",
                    "snapshot_complete", "authenticated_broker_read_verified",
                    "complete_pagination_verified",
                ))
                or isinstance(stamp, bool)
                or not isinstance(stamp, (int, float))
                or not 0 <= now_epoch - stamp <= 60):
            return _result(False, "authenticated_account_identity_unverified")
        from bot.runtime_authoritative_position_coverage_v285_patch import (
            _snapshot_max_age_s,
            _snapshot_status,
            _strong_broker_proof,
        )

        snapshot_ok, reason, rows, age_s, generation = _snapshot_status(broker)
        startup_ok, startup_reason = _strong_broker_proof(broker)
        wall_stamp = getattr(
            broker, "_nija_authoritative_position_snapshot_at_wall_v285", None,
        )
    except Exception as exc:
        return _result(False, f"position_sync_read_failed:{type(exc).__name__}")
    if not snapshot_ok:
        return _result(False, f"authoritative_snapshot_unverified:{reason}")
    if not startup_ok:
        return _result(False, f"startup_position_sync_unverified:{startup_reason}")
    if (isinstance(wall_stamp, bool) or not isinstance(wall_stamp, (int, float))
            or not 0 <= now_epoch - wall_stamp <= _snapshot_max_age_s()):
        return _result(False, "authoritative_snapshot_wall_clock_stale_or_invalid")
    if (getattr(broker, "_startup_position_sync_fetch_ok", None) is not True
            or getattr(broker, "_startup_position_sync_adopted", None) is not True
            or type(generation) is not int or generation <= 0):
        return _result(False, "position_snapshot_not_fully_adopted")
    return _result(
        False, "reconciled_ledger_unavailable_for_position_comparison",
        observed_at_epoch=float(wall_stamp),
        snapshot_age_s=max(0.0, now_epoch - float(wall_stamp)),
        position_count=len(rows),
        snapshot_generation=generation,
        identity_verified=True,
        snapshot_verified=True,
        ledger_consistency_verified=False,
        account_scope=account_scope,
    )


def inspect_kraken_production_sources(
    *,
    account_scope: str,
    ledger_path: Path,
    persistent_root: Path,
    broker: Any = None,
    identity_provider: Any = None,
    idempotency_registry: Any = None,
    redis_client: Any = None,
    kill_switch: Any = None,
    risk_governor: Any = None,
    now_epoch: float | None = None,
) -> dict[str, Any]:
    """Report source readiness without creating providers or changing runtime state.

    The diagnostic intentionally does not accept caller-supplied ``ready``
    booleans or approval records. A clean local ledger audit is not exchange
    reconciliation; Redis reachability is not a complete account-scoped intent
    inventory; a bounded startup plan is not general live-order approval; and
    a healthy global governor snapshot is not account-bound risk proof.
    """
    now = time.time() if now_epoch is None else now_epoch
    if (isinstance(now, bool) or not isinstance(now, (int, float))
            or not (0 < float(now) < float("inf"))):
        raise ValueError("diagnostic_clock_invalid")
    if (not isinstance(account_scope, str) or not account_scope
            or account_scope != account_scope.strip()
            or account_scope != "platform:kraken"):
        raise ValueError("platform_kraken_scope_required")

    ledger = inspect_kraken_ledger(
        Path(ledger_path), persistent_root=Path(persistent_root),
    )
    ledger_issues = ledger.get("issues")
    if not isinstance(ledger_issues, list):
        ledger_issues = ["ledger_preflight_result_invalid"]
    ledger_blockers = list(ledger_issues)
    ledger_blockers.extend(ledger.get("requires", []))
    sources: dict[str, dict[str, Any]] = {
        "position_ledger_reconciliation": _result(
            False, "read_only_local_ledger_is_not_broker_reconciliation",
            local_ledger_issues=ledger_blockers,
            broker_history_reconciled=ledger.get("broker_history_reconciled") is True,
            protective_exits_broker_verified=(
                ledger.get("protective_exits_broker_verified") is True
            ),
        ),
    }

    shared_redis_ok = False
    if redis_client is not None:
        try:
            shared_redis_ok = redis_client.ping() is True
        except Exception:
            shared_redis_ok = False
    registry_redis = (
        getattr(idempotency_registry, "_redis", None)
        if idempotency_registry is not None else None
    )
    if not shared_redis_ok:
        duplicate = _result(False, "shared_redis_unavailable")
    elif registry_redis is not redis_client:
        duplicate = _result(False, "idempotency_registry_not_bound_to_verified_redis")
    else:
        duplicate = _result(
            False, "account_scoped_unresolved_intent_inventory_unavailable",
            shared_redis_verified=True,
            registry_local_cache_not_used=True,
        )
    sources["duplicate_order_fence"] = duplicate

    # StartupVerificationPlan authorizes only a bounded, single-symbol startup
    # plan. There is no general live-order authorization source in this release.
    sources["operator_authorization"] = _result(
        False, "general_live_order_authorization_source_missing",
        bounded_startup_plan_is_not_general_authorization=True,
    )
    sources["kill_switch_clear"] = _inspect_kill_switch(
        kill_switch, redis_client, now_epoch=float(now),
    )

    governor = inspect_existing_risk_governor(risk_governor)
    sources["risk_limits"] = _result(
        False, "account_scoped_current_risk_and_capital_proof_missing",
        existing_governor_snapshot_healthy=governor.get("ready") is True,
        governor_failures=governor.get("failures", []),
        independent_certification=False,
    )
    sources["position_sync"] = _inspect_position_sync(
        broker, identity_provider, account_scope, now_epoch=float(now),
    )

    checks = {
        field: sources[field].get("ready") is True for field in _SIX_FIELDS
    }
    return {
        "account_scope": account_scope,
        "checks": checks,
        "sources": sources,
        "all_six_ready": all(checks.values()),
        "diagnostic_only": True,
        "collector_registration_attempted": False,
        "authorizes_orders": False,
        "execution_authority_changed": False,
        "missing_v452_checks": [
            field for field in REQUIRED if field in _SIX_FIELDS and not checks[field]
        ],
    }


__all__ = ["inspect_kraken_production_sources"]
