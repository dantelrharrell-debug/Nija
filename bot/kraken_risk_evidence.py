"""Account-specific, read-only ``risk_limits`` evidence for the v452 contract.

No runtime source is installed or discovered here. The composition root must
separately review and bind a source exposing ``read_snapshot(account, key_pin)``.
That method must return an atomic, detached snapshot, with a monotonically
increasing revision covering *all* account, capital, exposure and policy changes
(including changes subsequently reverted). Reads must not refresh/mutate state.
The source must authenticate the account/key binding and completeness itself;
this module never upgrades missing provenance to verified provenance.

Snapshot contract:
* The envelope and capital/exposure/policy records have account, broker=kraken,
  api_key_sha256, source_id, revision, observed_at_epoch, verified, read_only,
  scope_verified and the four PROVENANCE flags. Each record has its own pinned
  source identity and independent observation timestamp. Percentages use 0..100.
* Capital supplies hydrated/registered/is_real, real_capital, usable_capital.
* Exposure supplies hydrated, positions, total_gross_exposure_usd, total_risk_usd.
  Positions include pending orders/reservations, without netting short exposure.
  snapshot_complete must attest that all account obligations are included.
* Policy supplies account-specific limits and current drawdown/loss restrictions;
  see _validate_risk for required fields. All fields are required; no defaults.

Source gaps in existing APIs: CapitalAuthority.get_snapshot/get_raw_per_broker
has broker keys but no authenticated account/API-key provenance or per-account
observation revision. PortfolioExposureAggregator.get_full_report has neither
account ownership, hydration, nor an observation timestamp (its timestamp is
report generation time). GlobalRiskGovernor.get_status and the global drawdown
report are portfolio-wide, not account clearance. Adaptive leverage calculations
and entry approval methods mutate state; they are deliberately never called.
ProtectiveExitMonitor.snapshot is a lifecycle read, not complete authenticated
account protection proof. These gaps require the reviewed snapshot source.

Optional existing CapitalAuthority and GlobalRiskGovernor objects are read via
their public APIs as additional vetoes only. Never infer an account allocation
from global capital, exposure, or governor health. No client creation, broker
calls, collector installation, execution authority, or production mutation.
"""
from __future__ import annotations

import copy
import math
import re
import time
import uuid
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any, Protocol

PROVENANCE = (
    "account_scope_verified", "collector_identity_verified",
    "snapshot_complete", "risk_state_verified",
)
_RECORDS = ("capital", "exposure", "policy")
_MAX_AGE_S = 60.0


class KrakenRiskEvidenceDenied(ValueError):
    """Fixed, non-sensitive failure code; source payloads are never exposed."""


class AccountRiskSnapshotSource(Protocol):
    """Separately reviewed atomic source; revisions include reverted changes."""

    def read_snapshot(self, account: str, api_key_sha256: str) -> Mapping[str, Any]:
        """Read a complete authenticated account snapshot without refreshing it."""
        ...


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise KrakenRiskEvidenceDenied(code)


def _identifier(value: Any) -> bool:
    return (isinstance(value, str) and bool(value) and value == value.strip()
            and not any(char.isspace() for char in value))


def _number(value: Any, *, minimum: float = 0.0, positive: bool = False) -> float:
    _require(type(value) in (float, int), "numeric_type_invalid")
    try:
        result = float(value)
    except (ValueError, OverflowError):
        raise KrakenRiskEvidenceDenied("numeric_value_invalid") from None
    _require(math.isfinite(result) and result >= minimum
             and (not positive or result > 0), "numeric_value_invalid")
    return result


def _integer(value: Any, *, positive: bool = False) -> int:
    _require(type(value) is int and value >= (1 if positive else 0), "integer_type_invalid")
    _number(value, positive=positive)
    return value


def _percent(value: Any) -> float:
    result = _number(value, positive=True)
    _require(result <= 100, "percentage_invalid")
    return result


def _stamp(value: Any, now: float) -> float:
    stamp = _number(value, positive=True)
    _require(0 <= now - stamp <= _MAX_AGE_S, "risk_observation_stale")
    return stamp


def _validate_risk(snapshot: Mapping[str, Any]) -> None:
    capital, exposure, policy = (snapshot[key] for key in _RECORDS)
    _require(all(capital.get(key) is True for key in ("hydrated", "registered", "is_real")),
             "capital_unhydrated_or_unregistered")
    equity = _number(capital.get("real_capital"), positive=True)
    usable = _number(capital.get("usable_capital"), positive=True)
    _require(usable <= equity, "capital_inconsistent")
    _require(exposure.get("hydrated") is True, "exposure_unhydrated")
    _require(policy.get("trading_allowed") is True and policy.get("halt_active") is False,
             "account_risk_halted")
    _require(policy.get("protective_exits_required") is True, "protective_policy_missing")
    for key in ("leverage_allowed", "short_allowed", "reduce_only_required"):
        _require(type(policy.get(key)) is bool, "policy_boolean_invalid")

    max_positions = _integer(policy.get("max_open_positions"), positive=True)
    max_losses = _integer(policy.get("max_consecutive_losses"), positive=True)
    losses = _integer(policy.get("consecutive_losses"))
    _require(losses < max_losses, "consecutive_loss_limit")
    multiplier = _number(policy.get("position_size_multiplier"), positive=True)
    _require(multiplier <= 1, "position_multiplier_invalid")
    max_position = _percent(policy.get("max_position_pct")) * multiplier
    max_asset = _percent(policy.get("max_single_asset_pct"))
    max_risk = _percent(policy.get("max_total_risk_pct"))
    max_drawdown = _percent(policy.get("max_drawdown_pct"))
    max_daily_loss = _percent(policy.get("max_daily_loss_pct"))
    max_stop = _percent(policy.get("max_stop_distance_pct"))
    max_exposure = _number(policy.get("max_total_exposure_pct"), positive=True)
    max_leverage = _number(policy.get("max_leverage"), minimum=1)
    absolute_max = _number(policy.get("absolute_max_leverage"), minimum=1)
    leverage_limit = min(max_leverage, absolute_max) if policy["leverage_allowed"] else 1.0
    class_limits = policy.get("max_asset_class_pct")
    _require(isinstance(class_limits, Mapping) and bool(class_limits), "asset_class_policy_missing")
    class_limits = {key: _percent(value) for key, value in class_limits.items()
                    if _identifier(key)}
    _require(len(class_limits) == len(policy["max_asset_class_pct"]), "asset_class_policy_invalid")

    peak = _number(policy.get("peak_equity_usd"), positive=True)
    drawdown = _number(policy.get("drawdown_pct"))
    _require(peak >= equity and drawdown <= 100
             and math.isclose(drawdown, (peak - equity) / peak * 100, abs_tol=1e-8),
             "drawdown_inconsistent")
    daily_pnl = _number(policy.get("daily_pnl_usd"), minimum=-float("inf"))
    _require(drawdown < max_drawdown and max(0, -daily_pnl) / equity * 100 < max_daily_loss,
             "drawdown_or_daily_loss_limit")

    positions = exposure.get("positions")
    _require(type(positions) is list, "positions_incomplete")
    _require(len(positions) < max_positions, "position_count_limit")
    total = risk = 0.0
    symbols: dict[str, float] = {}
    classes: dict[str, float] = {}
    seen: set[str] = set()
    for position in positions:
        _require(isinstance(position, Mapping), "position_invalid")
        identity = position.get("position_id")
        symbol = position.get("symbol")
        asset_class = position.get("asset_class")
        _require(_identifier(identity) and identity not in seen and _identifier(symbol),
                 "position_identity_invalid")
        seen.add(identity)
        _require(position.get("state") in ("open", "pending")
                 and position.get("direction") in ("long", "short")
                 and _identifier(asset_class) and asset_class in class_limits, "position_scope_invalid")
        _require(position["direction"] != "short" or policy["short_allowed"], "short_restricted")
        notional = _number(position.get("notional_usd"), positive=True)
        position_risk = _number(position.get("risk_usd"), positive=True)
        leverage = _number(position.get("leverage"), minimum=1)
        stop = _percent(position.get("stop_distance_pct"))
        quantity = _number(position.get("quantity"), positive=True)
        protected = _number(position.get("protected_quantity"), positive=True)
        _require(position.get("protective_exit_verified") is True
                 and position.get("broker_acknowledged") is True
                 and (not policy["reduce_only_required"] or position.get("reduce_only") is True)
                 and protected >= quantity and stop <= max_stop
                 and position_risk >= notional * stop / 100, "protective_constraint_failed")
        _require(leverage <= leverage_limit and notional / equity * 100 <= max_position,
                 "position_or_leverage_limit")
        total += notional
        risk += position_risk
        symbols[symbol] = symbols.get(symbol, 0) + notional
        classes[asset_class] = classes.get(asset_class, 0) + notional
    gross = _number(exposure.get("total_gross_exposure_usd"))
    reported_risk = _number(exposure.get("total_risk_usd"))
    _require(math.isfinite(total) and math.isfinite(risk)
             and math.isclose(total, gross, rel_tol=1e-10, abs_tol=1e-8)
             and math.isclose(risk, reported_risk, rel_tol=1e-10, abs_tol=1e-8),
             "exposure_totals_inconsistent")
    _require(gross / equity <= leverage_limit and gross / equity * 100 <= max_exposure
             and risk / equity * 100 < max_risk and risk <= usable,
             "aggregate_exposure_limit")
    _require(all(value / equity * 100 <= max_asset for value in symbols.values())
             and all(value / equity * 100 <= class_limits[key] for key, value in classes.items()),
             "concentration_limit")


def make_kraken_risk_limits_provider(
    snapshot_source: AccountRiskSnapshotSource, *, account_scope: str,
    approved_api_key_sha256: str, reviewed_provider_id: str,
    reviewed_snapshot_source_id: str, reviewed_record_source_ids: Mapping[str, str],
    independently_reviewed: bool = False, capital_authority: Any = None,
    reviewed_capital_broker_id: str | None = None, global_governor: Any = None,
    clock: Callable[[], float] = time.time,
) -> Callable[[], Mapping[str, Any]]:
    """Bind a reviewed account source and return a non-authorizing v452 provider.

    Provider/source IDs and fingerprint MUST come from a separately audited
    composition root, never from the snapshot being checked. Distinct capital,
    exposure and policy source IDs identify independently reviewed records, not
    relabelled global statistics. No default trusted identity or source exists.
    Optional capital broker-ID attribution also requires external review.
    """
    _require(independently_reviewed is True, "independent_review_required")
    _require(_identifier(account_scope) and account_scope.endswith(":kraken")
             and len(account_scope) > len(":kraken"), "kraken_account_scope_required")
    _require(isinstance(approved_api_key_sha256, str)
             and re.fullmatch(r"[0-9a-f]{64}", approved_api_key_sha256) is not None,
             "reviewed_key_pin_required")
    _require(_identifier(reviewed_provider_id) and _identifier(reviewed_snapshot_source_id),
             "reviewed_source_binding_required")
    _require(isinstance(reviewed_record_source_ids, Mapping)
             and set(reviewed_record_source_ids) == set(_RECORDS)
             and all(_identifier(value) for value in reviewed_record_source_ids.values())
             and len(set(reviewed_record_source_ids.values())) == len(_RECORDS),
             "independent_record_bindings_required")
    bindings = dict(reviewed_record_source_ids)
    _require(callable(getattr(snapshot_source, "read_snapshot", None)) and callable(clock),
             "snapshot_read_api_required")
    if capital_authority is not None:
        _require(_identifier(reviewed_capital_broker_id), "capital_account_binding_required")

    def validate(snapshot: Any, now: float) -> float:
        _require(isinstance(snapshot, Mapping), "account_snapshot_missing")
        stamps = []
        for key in (None, *_RECORDS):
            row = snapshot if key is None else snapshot.get(key)
            _require(isinstance(row, Mapping), "account_record_missing")
            source_id = reviewed_snapshot_source_id if key is None else bindings[key]
            _require(row.get("account") == account_scope and row.get("broker") == "kraken"
                     and row.get("api_key_sha256") == approved_api_key_sha256,
                     "account_or_key_mismatch")
            _require(row.get("source_id") == source_id, "source_identity_mismatch")
            _integer(row.get("revision"), positive=True)
            _require(all(row.get(flag) is True for flag in ("verified", "read_only", "scope_verified")),
                     "source_unverified")
            provenance = row.get("provenance")
            _require(isinstance(provenance, Mapping)
                     and all(provenance.get(flag) is True for flag in PROVENANCE),
                     "source_provenance_unverified")
            stamps.append(_stamp(row.get("observed_at_epoch"), now))
        _validate_risk(snapshot)
        return min(stamps)

    def local_capital(snapshot: Mapping[str, Any], now: float) -> Any:
        if capital_authority is None:
            return None
        authority = capital_authority
        _require(authority.is_hydrated is True
                 and authority.is_registered(reviewed_capital_broker_id) is True
                 and authority.is_fresh(ttl_s=_MAX_AGE_S) is True
                 and authority.is_brokers_complete() is True, "capital_authority_not_ready")
        row = authority.get_snapshot()
        _require(isinstance(row, Mapping), "capital_authority_snapshot_missing")
        stamp = datetime.fromisoformat(row["last_updated"])
        _require(stamp.tzinfo is not None, "capital_clock_unverified")
        _stamp(stamp.timestamp(), now)
        balances = row.get("broker_balances")
        _require(isinstance(balances, Mapping) and reviewed_capital_broker_id in balances,
                 "capital_account_unregistered")
        raw = _number(authority.get_raw_per_broker(reviewed_capital_broker_id), positive=True)
        usable = _number(authority.get_per_broker(reviewed_capital_broker_id), positive=True)
        _require(raw == balances[reviewed_capital_broker_id]
                 and raw == snapshot["capital"]["real_capital"]
                 and usable == snapshot["capital"]["usable_capital"], "capital_account_mismatch")
        return (stamp.timestamp(), raw, usable, dict(balances))

    def governor_status() -> Any:
        if global_governor is None:
            return None
        status = copy.deepcopy(global_governor.get_status())
        _require(isinstance(status, Mapping) and status.get("halt_active") is False,
                 "global_governor_halted_or_unavailable")
        return status

    def read() -> Mapping[str, Any]:
        try:
            started = _number(clock(), positive=True)
            first = copy.deepcopy(snapshot_source.read_snapshot(account_scope, approved_api_key_sha256))
            validate(first, started)
            capital_before = local_capital(first, started)
            governor_before = governor_status()
            capital_after = local_capital(first, started)
            governor_after = governor_status()
            second = copy.deepcopy(snapshot_source.read_snapshot(account_scope, approved_api_key_sha256))
            finished = _number(clock(), positive=True)
            _require(0 <= finished - started <= _MAX_AGE_S, "risk_read_clock_changed")
            observed = validate(second, finished)
            _require(first == second and capital_before == capital_after
                     and governor_before == governor_after, "concurrent_risk_change")
            if capital_after is not None:
                _stamp(capital_after[0], finished)
            # Verification is preserved only after all supplied proofs have been
            # checked; no report-generation timestamp replaces observation age.
            return {
                "account": account_scope, "api_key_sha256": approved_api_key_sha256,
                "source": "risk_governor", "provider_id": reviewed_provider_id,
                "evidence_id": uuid.uuid4().hex, "observed_at_epoch": observed,
                "snapshot_source_id": reviewed_snapshot_source_id,
                "snapshot_revision": second["revision"],
                "record_revisions": {key: second[key]["revision"] for key in _RECORDS},
                "verified": second["verified"], "read_only": second["read_only"],
                "scope_verified": second["scope_verified"], "authorizes_orders": False,
                "provenance": {flag: second["provenance"][flag] for flag in PROVENANCE},
            }
        except KrakenRiskEvidenceDenied:
            raise
        except Exception:
            raise KrakenRiskEvidenceDenied("risk_source_read_failed") from None

    return read


__all__ = [
    "AccountRiskSnapshotSource", "KrakenRiskEvidenceDenied", "PROVENANCE",
    "make_kraken_risk_limits_provider",
]
