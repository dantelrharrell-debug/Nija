"""Inert, explicitly reviewed composition of the four Kraken evidence families.

No discovery, client creation, registry installation, dispatch or persistence is
performed. A collection supplies six of thirteen pretrade fields, not admission.
The independent reviewer must authenticate the exact dependency objects and pins;
constructing this configuration is not evidence that production sources exist.
"""
from __future__ import annotations

import copy
import math
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Protocol

from bot.kraken_ledger_evidence import ReviewedLedgerBinding, make_kraken_ledger_evidence_provider
from bot.kraken_operator_authorization import GeneralApprovalBinding, make_general_operator_authorization_provider
from bot.kraken_redis_evidence import FIELDS as REDIS_FIELDS, RedisEvidenceReader, ReviewedBinding
from bot.kraken_risk_evidence import AccountRiskSnapshotSource, make_kraken_risk_limits_provider
from bot.pretrade_attestation_validation_v452 import PROOF_BY_SOURCE, SOURCES, evidence_expiry_failure

FIELDS = ("position_ledger_reconciliation", *REDIS_FIELDS, "risk_limits", "operator_authorization")


class KrakenEvidenceCompositionDenied(ValueError):
    """Fixed, redacted failure; a failed collection never returns partial rows."""


class RedisReadClient(Protocol):
    """Existing Redis dependency; the family reader restricts pipeline commands."""

    def pipeline(self, *, transaction: bool) -> Any:
        """Return the existing client's transactional read pipeline."""
        ...


class CapitalReadAuthority(Protocol):
    """Optional canonical capital authority, used only as an additional veto."""

    @property
    def is_hydrated(self) -> bool:
        """Whether the existing authority has hydrated."""
        ...

    def is_registered(self, broker_id: str) -> bool:
        """Check registration without allocating capital."""
        ...

    def is_fresh(self, ttl_s: float) -> bool:
        """Check original capital freshness."""
        ...

    def is_brokers_complete(self) -> bool:
        """Check hydration coverage."""
        ...

    def get_snapshot(self) -> Mapping[str, Any]:
        """Read the canonical capital snapshot."""
        ...

    def get_raw_per_broker(self, broker_id: str) -> float:
        """Read raw attributed capital."""
        ...

    def get_per_broker(self, broker_id: str) -> float:
        """Read usable attributed capital."""
        ...


class GovernorReadAuthority(Protocol):
    """Canonical governor status is a veto, never account clearance."""

    def get_status(self) -> Mapping[str, Any]:
        """Read status without invoking entry approval or changing risk state."""
        ...


@dataclass(frozen=True)
class RiskEvidenceDependencies:
    """Explicit reviewed snapshot provenance and optional canonical vetoes."""

    snapshot_source: AccountRiskSnapshotSource
    snapshot_source_id: str
    record_source_ids: Mapping[str, str]
    capital_authority: CapitalReadAuthority | None = None
    capital_broker_id: str | None = None
    global_governor: GovernorReadAuthority | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "record_source_ids", MappingProxyType(dict(self.record_source_ids)))


@dataclass(frozen=True)
class OperatorEvidenceDependencies:
    """External public trust roots and uncached signed approval/status reader."""

    binding: GeneralApprovalBinding
    operator_public_keys: Mapping[str, bytes]
    status_public_key: bytes
    read_records: Callable[[], Mapping[str, Any]]

    def __post_init__(self) -> None:
        object.__setattr__(self, "operator_public_keys", MappingProxyType(dict(self.operator_public_keys)))


@dataclass(frozen=True, eq=False)
class KrakenEvidenceBinding:
    """Exact objects and external pins authenticated by an independent reviewer.

    Ledger paths must already contain independently persisted scoped provenance.
    No canonical ledger rows are relabelled, imported, or given inferred identity.
    Provider pins cover exactly FIELDS; remaining pretrade sources stay external.
    """

    account: str
    api_key_sha256: str
    account_iiban_sha256: str
    trusted_provider_ids: Mapping[str, str]
    ledger: ReviewedLedgerBinding
    redis_client: RedisReadClient
    redis: ReviewedBinding
    risk: RiskEvidenceDependencies
    operator: OperatorEvidenceDependencies

    def __post_init__(self) -> None:
        object.__setattr__(self, "trusted_provider_ids", MappingProxyType(dict(self.trusted_provider_ids)))


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise KrakenEvidenceCompositionDenied(code)


def _review(binding: KrakenEvidenceBinding, reviewer: Callable[[KrakenEvidenceBinding], bool]) -> None:
    _require(reviewer(binding) is True, "external_binding_review_required")


def _validate_binding(binding: KrakenEvidenceBinding) -> None:
    _require(type(binding) is KrakenEvidenceBinding, "configured_binding_required")
    _require(type(binding.ledger) is ReviewedLedgerBinding
             and type(binding.redis) is ReviewedBinding
             and type(binding.risk) is RiskEvidenceDependencies
             and type(binding.operator) is OperatorEvidenceDependencies
             and type(binding.operator.binding) is GeneralApprovalBinding,
             "configured_family_dependencies_required")
    pins = binding.trusted_provider_ids
    _require(set(pins) == set(FIELDS)
             and all(isinstance(pin, str) and pin and not any(c.isspace() for c in pin)
                     for pin in pins.values())
             and len(set(pins.values())) == len(FIELDS), "external_provider_pins_required")
    _require(all(isinstance(pin, str) and re.fullmatch(r"[a-f0-9]{64}", pin)
                 for pin in (binding.api_key_sha256, binding.account_iiban_sha256)),
             "external_identity_pins_required")
    operator = binding.operator.binding
    _require(binding.account == binding.ledger.account == binding.redis.expected_scope.account == operator.account
             and binding.api_key_sha256 == binding.ledger.api_key_sha256
             == binding.redis.expected_scope.api_key_sha256 == operator.api_key_sha256
             and binding.account_iiban_sha256 == binding.ledger.account_sha256 == operator.account_iiban_sha256,
             "family_identity_binding_mismatch")
    _require(binding.ledger.provider_id == pins["position_ledger_reconciliation"]
             and binding.redis.provider_ids == tuple(pins[field] for field in REDIS_FIELDS)
             and operator.provider_id == pins["operator_authorization"], "family_provider_binding_mismatch")
    _require(callable(getattr(binding.redis_client, "pipeline", None))
             and callable(getattr(binding.risk.snapshot_source, "read_snapshot", None))
             and callable(binding.operator.read_records), "configured_read_dependencies_required")
    _require(binding.risk.capital_authority is not None or binding.risk.capital_broker_id is None,
             "capital_veto_binding_incomplete")
    if binding.risk.capital_authority is not None:
        _require(all(callable(getattr(binding.risk.capital_authority, method, None)) for method in (
            "is_registered", "is_fresh", "is_brokers_complete", "get_snapshot",
            "get_raw_per_broker", "get_per_broker",
        )), "capital_veto_read_api_required")
    if binding.risk.global_governor is not None:
        _require(callable(getattr(binding.risk.global_governor, "get_status", None)),
                 "governor_veto_read_api_required")


class KrakenEvidenceComposition:
    """Read-only six-field batch; deliberately not a per-field provider registry."""

    def __init__(
        self, binding: KrakenEvidenceBinding, reviewer: Callable[[KrakenEvidenceBinding], bool],
        ledger: Callable[[], Mapping[str, Any]], redis: RedisEvidenceReader,
        risk: Callable[[], Mapping[str, Any]], operator: Callable[[], Mapping[str, Any]],
        clock: Callable[[], float],
    ) -> None:
        self._binding = binding
        self._reviewer = reviewer
        self._ledger = ledger
        self._redis = redis
        self._risk = risk
        self._operator = operator
        self._clock = clock

    @property
    def trusted_provider_ids(self) -> Mapping[str, str]:
        """Return immutable external pins, never identities harvested from rows."""
        return self._binding.trusted_provider_ids

    def collect(self) -> Mapping[str, Mapping[str, Any]]:
        """Read each family once, sharing one Redis collection across its fields.

        No cached rows or independently called Redis field closures are exposed.
        Earlier rows must still be fresh after the last family finishes. This
        does not establish cross-store atomicity or fill the other seven fields.
        """
        try:
            _review(self._binding, self._reviewer)
            started = self._clock()
            rows = {
                "position_ledger_reconciliation": self._ledger(),
                **self._redis.collect(),
                "risk_limits": self._risk(),
                "operator_authorization": self._operator(),
            }
            rows = copy.deepcopy(rows)
            _review(self._binding, self._reviewer)
            now = self._clock()
            _require(type(started) in (float, int) and type(now) in (float, int)
                     and math.isfinite(started) and math.isfinite(now)
                     and started > 0 and 0 <= now - started <= 60, "collection_clock_invalid")
            _require(set(rows) == set(FIELDS), "family_fields_incomplete")
            ids = set()
            for field, row in rows.items():
                _require(isinstance(row, Mapping)
                         and row.get("account") == self._binding.account
                         and row.get("provider_id") == self.trusted_provider_ids[field]
                         and row.get("source") == SOURCES[field]
                         and all(row.get(flag) is True for flag in ("verified", "read_only", "scope_verified"))
                         and row.get("authorizes_orders") is False, "family_evidence_denied")
                provenance = row.get("provenance")
                _require(isinstance(provenance, Mapping)
                         and all(provenance.get(flag) is True for flag in (
                             "account_scope_verified", "collector_identity_verified", "snapshot_complete",
                             PROOF_BY_SOURCE[SOURCES[field]],
                         )), "family_provenance_denied")
                stamp = row.get("observed_at_epoch")
                _require(type(stamp) in (float, int) and math.isfinite(stamp)
                         and stamp > 0 and 0 <= now - stamp <= 60
                         and evidence_expiry_failure(row, now_epoch=now) is None,
                         "family_evidence_expired")
                evidence_id = row.get("evidence_id")
                _require(isinstance(evidence_id, str) and evidence_id
                         and not any(c.isspace() for c in evidence_id) and evidence_id not in ids,
                         "family_evidence_identity_invalid")
                ids.add(evidence_id)
            return MappingProxyType(rows)
        except Exception:
            raise KrakenEvidenceCompositionDenied("family_collection_unavailable") from None


def compose_kraken_evidence(
    binding: KrakenEvidenceBinding, *,
    review_binding: Callable[[KrakenEvidenceBinding], bool],
    clock: Callable[[], float] = time.time,
) -> KrakenEvidenceComposition:
    """Bind existing families without reading sources or installing providers.

    The reviewer must consult an out-of-band authenticated binding of these
    exact dependency objects, not accept a boolean flag or compare only strings.
    It is consulted at composition and before/after every complete collection.
    """
    try:
        _validate_binding(binding)
        _require(callable(review_binding) and callable(clock), "configured_review_and_clock_required")
        _review(binding, review_binding)
        ledger = make_kraken_ledger_evidence_provider(
            binding.ledger, review_binding=lambda candidate: (
                candidate is binding.ledger and review_binding(binding) is True
            ), clock=clock,
        )
        redis = RedisEvidenceReader(binding.redis_client, binding.redis, clock=clock)
        risk = make_kraken_risk_limits_provider(
            binding.risk.snapshot_source, account_scope=binding.account,
            approved_api_key_sha256=binding.api_key_sha256,
            reviewed_provider_id=binding.trusted_provider_ids["risk_limits"],
            reviewed_snapshot_source_id=binding.risk.snapshot_source_id,
            reviewed_record_source_ids=binding.risk.record_source_ids,
            independently_reviewed=True, capital_authority=binding.risk.capital_authority,
            reviewed_capital_broker_id=binding.risk.capital_broker_id,
            global_governor=binding.risk.global_governor, clock=clock,
        )
        operator = make_general_operator_authorization_provider(
            binding=binding.operator.binding, operator_public_keys=binding.operator.operator_public_keys,
            revocation_public_key=binding.operator.status_public_key, read_records=binding.operator.read_records,
            independently_reviewed=True, clock=clock,
        )
        return KrakenEvidenceComposition(binding, review_binding, ledger, redis, risk, operator, clock)
    except Exception:
        raise KrakenEvidenceCompositionDenied("family_configuration_invalid") from None
