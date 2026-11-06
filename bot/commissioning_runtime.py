"""Explicit production composition for the review-gated Kraken commissioning path.

Importing this module performs no broker I/O, migration, collector installation,
pipeline mutation, key generation, or order submission. Runtime activation is a
separate operator-reviewed step and remains disabled by default.
"""
from __future__ import annotations

import base64
import json
import os
import sqlite3
import stat
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Protocol

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from bot.account_order_admission import AdmissionDenied, Collector, Fence
from bot.commissioning_gate import CommissioningGate, ExecutionReader, Observations
from bot.execution_dispatch_contract import INTERNAL_DISPATCH_FAILURE
from bot.kraken_operator_authorization import (
    GeneralApprovalBinding, make_general_operator_authorization_provider,
)
from bot.order_admission_policy import Candidate
from bot.pretrade_attestation_validation_v452 import REQUIRED
from bot.startup_verification_plan import StartupPlanError, StartupVerificationPlan, decimal_value

MAX_TRUST_FILE_BYTES = 65536


class CommissioningCompositionDenied(ValueError):
    """Fixed, non-sensitive commissioning composition failure."""


def _terminal_denial(reason: str) -> AdmissionDenied:
    return AdmissionDenied(f"{INTERNAL_DISPATCH_FAILURE}: {reason}")


class Ed25519SigningService(Protocol):
    """Opaque hardware/KMS signer interface; implementations retain private keys."""

    def sign(self, key_id: str, message: bytes) -> bytes:
        """Return a raw Ed25519 signature without exporting key material."""


class SigningKeyCustodian:
    """Verify signatures returned by an opaque HSM/KMS without holding private keys."""

    def __init__(
        self, signer: Ed25519SigningService, public_keys: Mapping[str, bytes],
    ) -> None:
        keys = dict(public_keys)
        if (not callable(getattr(signer, "sign", None)) or not keys
                or any(not isinstance(key_id, str) or not key_id.strip()
                       or type(key) is not bytes or len(key) != 32
                       for key_id, key in keys.items())):
            raise CommissioningCompositionDenied("external_signer_and_public_keys_required")
        self._signer = signer
        self._public_keys = MappingProxyType(keys)

    def sign(self, key_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Sign canonical JSON via the opaque signer and verify its response."""
        public_key = self._public_keys.get(key_id)
        if public_key is None or not isinstance(payload, Mapping):
            raise CommissioningCompositionDenied("signing_identity_or_payload_invalid")
        try:
            canonical = _canonical(dict(payload))
            signature = self._signer.sign(key_id, canonical)
            if type(signature) is not bytes or len(signature) != 64:
                raise ValueError("signature_shape_invalid")
            Ed25519PublicKey.from_public_bytes(public_key).verify(signature, canonical)
        except (ValueError, TypeError, InvalidSignature):
            raise CommissioningCompositionDenied("external_signature_verification_failed") from None
        return {
            "payload": json.loads(canonical),
            "signature": base64.b64encode(signature).decode("ascii"),
        }


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError):
        raise CommissioningCompositionDenied("signed_payload_not_canonical_json") from None


def _decimal_matches(left: Any, right: Any) -> bool:
    try:
        return decimal_value(left) == decimal_value(right)
    except StartupPlanError:
        return False


def _read_private_json(path: Path, *, limit: int = MAX_TRUST_FILE_BYTES) -> Any:
    """Read one owner-only regular JSON file through a no-follow descriptor."""
    target = Path(path)
    if not target.is_absolute() or target.is_symlink():
        raise CommissioningCompositionDenied("trust_file_path_invalid")
    descriptor = -1
    try:
        descriptor = os.open(target, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        info = os.fstat(descriptor)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) & 0o077 or info.st_size > limit):
            raise CommissioningCompositionDenied("trust_file_permissions_or_size_invalid")
        with os.fdopen(descriptor, "rb") as handle:
            descriptor = -1
            raw = handle.read(limit + 1)
        if len(raw) > limit:
            raise CommissioningCompositionDenied("trust_file_oversized")
        return json.loads(raw.decode("utf-8"))
    except CommissioningCompositionDenied:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise CommissioningCompositionDenied("trust_file_unavailable_or_invalid") from None
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def load_operator_public_keys(path: Path) -> Mapping[str, bytes]:
    """Load owner-only base64 Ed25519 public keys; no private key is accepted."""
    raw = _read_private_json(path)
    if not isinstance(raw, dict) or not raw or len(raw) > 32:
        raise CommissioningCompositionDenied("operator_public_key_registry_invalid")
    keys: dict[str, bytes] = {}
    try:
        for key_id, encoded in raw.items():
            if (not isinstance(key_id, str) or not key_id.strip()
                    or not isinstance(encoded, str)):
                raise ValueError("key_record_invalid")
            key = base64.b64decode(encoded, validate=True)
            if len(key) != 32:
                raise ValueError("key_size_invalid")
            keys[key_id] = key
    except (ValueError, TypeError):
        raise CommissioningCompositionDenied("operator_public_key_registry_invalid") from None
    return MappingProxyType(keys)


def load_status_public_key(path: Path) -> bytes:
    """Load one owner-only base64 Ed25519 public status-verification key."""
    raw = _read_private_json(path, limit=4096)
    if not isinstance(raw, dict) or set(raw) != {"status_public_key"}:
        raise CommissioningCompositionDenied("status_public_key_record_invalid")
    try:
        key = base64.b64decode(raw["status_public_key"], validate=True)
    except (ValueError, TypeError):
        raise CommissioningCompositionDenied("status_public_key_record_invalid") from None
    if len(key) != 32:
        raise CommissioningCompositionDenied("status_public_key_record_invalid")
    return key


def make_signed_record_reader(path: Path) -> Callable[[], Mapping[str, Any]]:
    """Build a reread-on-every-call reader for signed approval and status records."""
    target = Path(path)

    def read_records() -> Mapping[str, Any]:
        value = _read_private_json(target)
        if not isinstance(value, dict) or set(value) != {"approval", "status"}:
            raise CommissioningCompositionDenied("signed_approval_and_status_required")
        return value

    return read_records


def make_observations(
    providers: Mapping[str, Callable[[], Mapping[str, Any]]],
) -> Observations:
    """Collect every independently reviewed pretrade source exactly once."""
    if (not isinstance(providers, Mapping) or set(providers) != set(REQUIRED)
            or any(not callable(provider) for provider in providers.values())
            or len({id(provider) for provider in providers.values()}) != len(REQUIRED)):
        raise CommissioningCompositionDenied("complete_reviewed_provider_registry_required")
    frozen = MappingProxyType(dict(providers))

    def observe(candidate: Candidate, _ledger: sqlite3.Connection) -> Mapping[str, Any]:
        if type(candidate) is not Candidate:
            raise AdmissionDenied("commissioning_candidate_invalid")
        rows: dict[str, Mapping[str, Any]] = {}
        for field in REQUIRED:
            row = frozen[field]()
            if not isinstance(row, Mapping):
                raise AdmissionDenied("commissioning_evidence_invalid:" + field)
            rows[field] = row
        return MappingProxyType(rows)

    return observe


class CommissioningDispatchAdapter:
    """Disabled-by-default exact-plan admission hook for canonical dispatch.

    This adapter only consumes the durable first-trade permission. It never
    submits an order. It must be invoked from the established canonical
    dispatch path after its existing state, coordinator, authority, risk and
    terminal checks; an arbitrary caller must not install it.
    """

    def __init__(
        self,
        gate: CommissioningGate,
        plan: StartupVerificationPlan,
        candidate_for_request: Callable[[Any], Candidate],
        enabled: bool = False,
    ) -> None:
        if type(enabled) is not bool or not callable(candidate_for_request):
            raise CommissioningCompositionDenied("commissioning_adapter_configuration_invalid")
        self.gate = gate
        self.plan = plan
        self.candidate_for_request = candidate_for_request
        self.enabled = enabled
        self._armed = False
        self._lock = threading.Lock()
        # Consumers may wait on admission I/O, but transport validators must
        # never wait on that work. Only consumers acquire this outer lock;
        # _lock protects the short in-memory _armed transitions below.
        self._consumer_lock = threading.Lock()
        self._terminal_broker: Any = None

    def __call__(self, method: str, params: Mapping[str, Any]) -> None:
        """Serve as the terminal broker's exact-order validation callback."""
        self.validate_kraken_order_request(method, params)

    def validate_pipeline_request(self, request: Any) -> None:
        """Require one exact, Kraken-only spot request matching the approved plan."""
        plan = self.plan
        plan.validate()
        if (not self.enabled or getattr(request, "symbol", None) != plan.symbol
                or str(getattr(request, "side", "")).lower() != "buy"
                or str(getattr(request, "preferred_broker", "")).lower() != "kraken"
                or tuple(getattr(request, "allowed_brokers", ()) or ()) != ("kraken",)
                or str(getattr(request, "intent_type", "")).lower() != "entry"
                or str(getattr(request, "order_type", "")).lower() != "limit"
                or str(getattr(request, "time_in_force", "")).upper() != "FOK"
                or getattr(request, "reduce_only", False) is not False
                or getattr(request, "short_sell", None) not in (None, False)
                or getattr(request, "borrow_intent", None) not in (None, "", "none")
                or getattr(request, "margin_mode", None) not in (None, "", "spot")
                or getattr(request, "leverage", None) not in (None, 1, 1.0)
                or not _decimal_matches(getattr(request, "limit_price", None), plan.entry_limit)
                or not _decimal_matches(
                    getattr(request, "size_usd", None),
                    decimal_value(plan.entry_limit) * decimal_value(plan.base_quantity),
                )):
            raise AdmissionDenied("commissioning_pipeline_request_binding_mismatch")
        quantity_fields = (
            ("shares", getattr(request, "shares", None)),
            ("units", getattr(request, "units", None)),
        )
        supplied = [(name, value) for name, value in quantity_fields if value is not None]
        if (len(supplied) != 1
                or not _decimal_matches(supplied[0][1], plan.base_quantity)
                or getattr(request, "quantity_mode", None) not in {"shares", "base", "units"}):
            raise AdmissionDenied("commissioning_pipeline_quantity_binding_mismatch")

    def validate_kraken_order_request(self, method: str, params: Mapping[str, Any]) -> None:
        """Bind the one armed buy to the exact approved Kraken request at transport."""
        if not self.enabled or method != "AddOrder" or not isinstance(params, Mapping):
            raise _terminal_denial("commissioning_kraken_method_or_request_invalid")
        with self._lock:
            armed = self._armed
            if armed:
                self._armed = False
        if not armed:
            # Existing canonical exit routes keep their normal terminal
            # controls when no first-trade permission is awaiting transport.
            if params.get("type") == "sell":
                return
            raise _terminal_denial("commissioning_transport_attempt_not_armed")
        expected = self.plan.order_parameters("entry")
        expected.update({
            "close[ordertype]": "stop-loss-limit",
            "close[price]": self.plan.stop_trigger,
            "close[price2]": self.plan.stop_limit,
        })
        if type(params) is not dict or params != expected:
            raise _terminal_denial("commissioning_kraken_order_parameters_mismatch")

    def consume(self, request: Any) -> None:
        """Consume the exact first-trade permission; do not dispatch or retry."""
        self.validate_pipeline_request(request)
        candidate = self.candidate_for_request(request)
        if type(candidate) is not Candidate:
            raise AdmissionDenied("commissioning_candidate_invalid")
        # Serialize consumers through durable consumption AND transport arming.
        # Never hold the transport-state lock across admission/database I/O.
        # The durable gate remains authoritative after transport disarms and
        # across adapter instances/restarts; a failed gate never arms transport.
        with self._consumer_lock:
            with self._lock:
                if self._armed:
                    raise AdmissionDenied("commissioning_transport_attempt_already_armed")
            self.gate.consume_first_trade(candidate, self.plan)
            with self._lock:
                self._armed = True


@dataclass(frozen=True)
class CommissioningRuntime:
    """Fully wired but inert gate and dispatch adapter."""

    gate: CommissioningGate
    dispatch_adapter: CommissioningDispatchAdapter


def compose_commissioning_runtime(
    *,
    ledger: Path,
    collector: Collector,
    fence: Fence,
    providers: Mapping[str, Callable[[], Mapping[str, Any]]],
    trusted_provider_ids: Mapping[str, str],
    execution_reader: ExecutionReader,
    approval_records_path: Path,
    general_approval_records_path: Path,
    operator_public_key_path: Path,
    status_public_key_path: Path,
    general_status_public_key_path: Path,
    general_approval_binding: GeneralApprovalBinding,
    candidate_for_request: Callable[[Any], Candidate],
    plan: StartupVerificationPlan,
    release_id: str,
    maximum_cash_debit_usd: str,
    account_scope: str,
    account_fingerprint: str,
    credential_fingerprint: str,
    independently_reviewed: bool = False,
) -> CommissioningRuntime:
    """Compose existing audited sources without installing or enabling dispatch."""
    if independently_reviewed is not True:
        raise CommissioningCompositionDenied("independent_review_required")
    if not callable(candidate_for_request):
        raise CommissioningCompositionDenied("trusted_candidate_provider_required")
    if not isinstance(providers, Mapping):
        raise CommissioningCompositionDenied("reviewed_broker_and_runtime_sources_incomplete")
    provider_fields = frozenset(providers)
    if provider_fields not in {
        frozenset(REQUIRED), frozenset(REQUIRED) - {"operator_authorization"},
    }:
        raise CommissioningCompositionDenied("reviewed_broker_and_runtime_sources_incomplete")
    plan.validate()
    operator_keys = load_operator_public_keys(operator_public_key_path)
    status_key = load_status_public_key(status_public_key_path)
    general_status_key = load_status_public_key(general_status_public_key_path)
    if status_key == general_status_key:
        raise CommissioningCompositionDenied("separate_status_signing_roots_required")
    if (type(general_approval_binding) is not GeneralApprovalBinding
            or general_approval_binding.provider_id != trusted_provider_ids.get("operator_authorization")):
        raise CommissioningCompositionDenied("general_authorization_binding_mismatch")
    provider_registry = dict(providers)
    provider_registry["operator_authorization"] = make_general_operator_authorization_provider(
        binding=general_approval_binding, operator_public_keys=operator_keys,
        revocation_public_key=general_status_key,
        read_records=make_signed_record_reader(general_approval_records_path),
        independently_reviewed=True,
    )
    observations = make_observations(provider_registry)
    gate = CommissioningGate(
        ledger, collector, fence, observations=observations,
        trusted_provider_ids=trusted_provider_ids,
        execution_reader=execution_reader,
        read_approval=make_signed_record_reader(approval_records_path),
        operator_public_keys=operator_keys, status_public_key=status_key,
        release_id=release_id, maximum_cash_debit_usd=maximum_cash_debit_usd,
        account_scope=account_scope, account_fingerprint=account_fingerprint,
        credential_fingerprint=credential_fingerprint, independently_reviewed=True,
    )
    adapter = CommissioningDispatchAdapter(
        gate=gate, plan=plan, candidate_for_request=candidate_for_request,
    )
    return CommissioningRuntime(gate=gate, dispatch_adapter=adapter)


def install_commissioning_dispatch_adapter(
    pipeline: Any,
    adapter: CommissioningDispatchAdapter,
    broker: Any,
    *,
    activation_reviewed: bool = False,
) -> None:
    """Explicitly attach the inert hook to an existing pipeline instance.

    The adapter itself defaults to disabled and requires explicit activation
    review before installation. This function does not alter FSM state,
    coordinator state, authority, or safety controls.
    """
    if (activation_reviewed is not True or type(adapter) is not CommissioningDispatchAdapter
            or adapter.enabled is not True):
        raise CommissioningCompositionDenied("explicit_activation_review_required")
    if not callable(getattr(pipeline, "_dispatch", None)):
        raise CommissioningCompositionDenied("canonical_execution_pipeline_required")
    if getattr(pipeline, "_commissioning_dispatch_adapter", None) is not None:
        raise CommissioningCompositionDenied("commissioning_adapter_already_installed")
    admission = getattr(pipeline, "_account_order_admission", None)
    candidate_provider = getattr(pipeline, "_trusted_entry_candidate_provider", None)
    if (admission is None
            or getattr(admission, "collector", None) is not adapter.gate.collector
            or getattr(admission, "fence", None) is not adapter.gate.fence
            or Path(getattr(admission, "ledger", "")).resolve() != adapter.gate.ledger.resolve()
            or candidate_provider is not adapter.candidate_for_request):
        raise CommissioningCompositionDenied("canonical_entry_admission_binding_mismatch")
    if (not callable(getattr(broker, "_kraken_private_call", None))
            or getattr(broker, "_gateway_url", "")
            or getattr(broker, "_gateway_only_mode", False)
            or getattr(broker, "_commissioning_order_request_validator", None) is not None):
        raise CommissioningCompositionDenied("direct_kraken_terminal_binding_required")
    try:
        from bot.broker_manager import KrakenBroker
        from bot.kraken_authenticated_account_identity_v478 import _broker_account_scope
        if (type(broker) is not KrakenBroker
                or _broker_account_scope(broker) != adapter.gate.account_scope):
            raise CommissioningCompositionDenied("reviewed_kraken_broker_scope_required")
    except CommissioningCompositionDenied:
        raise
    except (AttributeError, ValueError):
        raise CommissioningCompositionDenied("reviewed_kraken_broker_scope_required") from None
    try:
        broker._commissioning_order_request_validator = adapter
        pipeline._commissioning_dispatch_adapter = adapter
    except (AttributeError, TypeError):
        if getattr(broker, "_commissioning_order_request_validator", None) is adapter:
            del broker._commissioning_order_request_validator
        raise CommissioningCompositionDenied("commissioning_adapter_install_failed") from None
    adapter._terminal_broker = broker


__all__ = [
    "CommissioningCompositionDenied", "CommissioningDispatchAdapter", "CommissioningRuntime",
    "Ed25519SigningService", "SigningKeyCustodian", "compose_commissioning_runtime",
    "install_commissioning_dispatch_adapter", "load_operator_public_keys",
    "load_status_public_key", "make_observations", "make_signed_record_reader",
]
