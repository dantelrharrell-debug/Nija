"""Explicit trusted-root handoff for the existing diagnostic collector.

Registration is in-process only: never load a factory or approvals from an
environment variable. The protected deployment root must supply real reviewed
providers and an authenticated receipt verifier. This module creates neither.
"""
from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
import threading
from types import MappingProxyType
from typing import Any

RECEIPTS = frozenset({"independent_review", "backup_restore", "broker_ledger_exits"})


@dataclass(frozen=True)
class ReviewedStartupBinding:
    manager: Any
    strategy: Any
    broker: Any
    providers: Mapping[str, Callable]
    reviewed_provider_ids: Mapping[str, str]
    receipts: Mapping[str, Any]

    def __post_init__(self) -> None:
        # Freeze the registries before review so the installed registry is the
        # same one examined by the trusted verifier. Receipt authentication,
        # expiry, release, account and credential scope remain its responsibility.
        for name in ("providers", "reviewed_provider_ids", "receipts"):
            object.__setattr__(self, name, MappingProxyType(dict(getattr(self, name))))


_factory: Callable | None = None
_verify_receipts: Callable | None = None
_registration_lock = threading.RLock()
_source_import_active = False


def startup_binding_registration_state() -> str:
    """Report registration presence only, never certification or order readiness."""
    with _registration_lock:
        if _factory is None and _verify_receipts is None:
            return "missing"
        if callable(_factory) and callable(_verify_receipts):
            return "registered"
        return "incomplete"


@contextmanager
def protected_source_import_guard() -> Iterator[None]:
    """Prevent accidental registration side effects while approved code loads.

    This is not a sandbox for approved Python code. Its complete implementation
    still requires independent review before its signature or provisioning.
    """
    global _source_import_active
    with _registration_lock:
        if _source_import_active or startup_binding_registration_state() != "missing":
            raise ValueError("protected_source_import_conflict")
        _source_import_active = True
    try:
        yield
    finally:
        with _registration_lock:
            _source_import_active = False


def register_reviewed_startup_binding(
    factory: Callable, *, verify_receipts: Callable,
) -> None:
    """Called once by the independently reviewed protected composition root.

    The verifier must authenticate all three receipts against this exact binding
    and deployed release. Returning True is an approval, never evidence by itself.
    There is intentionally no default verifier or permissive fallback.
    """
    global _factory, _verify_receipts
    with _registration_lock:
        if _source_import_active:
            raise ValueError("registration_during_protected_source_import_denied")
        if _factory is not None or _verify_receipts is not None:
            raise ValueError("startup_binding_already_registered")
        if not callable(factory) or not callable(verify_receipts):
            raise TypeError("reviewed_factory_and_receipt_verifier_required")
        _factory, _verify_receipts = factory, verify_receipts


def install_from_canonical_startup(manager: Any, strategy: Any) -> str:
    """Observe and install using existing validation; never grants order authority.

    A fixed denial leaves the current registry untouched. Startup can continue
    monitoring; canonical evidence/admission gates retain their existing duties.
    Do not treat this status as execution proof, certification or activation.
    """
    factory, verifier = _factory, _verify_receipts
    if not callable(factory) or not callable(verifier):
        return "trusted_startup_binding_missing"
    failure_status = "reviewed_startup_binding_denied"
    try:
        from bot.broker_manager import KrakenBroker
        from bot.kraken_authenticated_account_identity_v478 import _broker_account_scope
        from bot.kraken_collector_composition_v487 import install_reviewed_kraken_collector

        failure_status = "startup_binding_factory_failed"
        binding = factory(manager=manager, strategy=strategy)
        failure_status = "reviewed_startup_binding_denied"
        if (type(binding) is not ReviewedStartupBinding
                or binding.manager is not manager or binding.strategy is not strategy
                or manager is None or strategy is None):
            return "canonical_runtime_binding_mismatch"
        brokers = getattr(manager, "platform_brokers", None)
        if callable(brokers):
            brokers = brokers()
        if not isinstance(brokers, Mapping):
            return "canonical_kraken_binding_missing"
        matches = [value for key, value in brokers.items()
                   if getattr(key, "value", key) == "kraken"]
        broker = binding.broker
        if (len(matches) != 1 or matches[0] is not broker
                or type(broker) is not KrakenBroker
                or getattr(broker, "connected", False) is not True
                or _broker_account_scope(broker) != "platform:kraken"):
            return "canonical_kraken_binding_mismatch"
        failure_status = "release_receipt_verification_failed"
        if (set(binding.receipts) != RECEIPTS
                or any(value is None for value in binding.receipts.values())
                or verifier(binding) is not True):
            return "authenticated_release_receipts_required"
        failure_status = "collector_registration_failed"
        install_reviewed_kraken_collector(
            providers=binding.providers,
            reviewed_provider_ids=binding.reviewed_provider_ids,
            independently_reviewed=True,
            backup_restore_certified=True,
            broker_ledger_exits_certified=True,
        )
        return "diagnostic_collector_installed"
    except Exception:
        # Provider exceptions can include credentials or private exchange data.
        return failure_status
