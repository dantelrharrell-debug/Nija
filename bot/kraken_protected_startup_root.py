"""Fixed-path, signed protected-root handoff in the final canonical interpreter.

The protected manifest is an independently provisioned trust anchor, not proof
that its own keys were approved. Review/provisioning is an external deployment
requirement. Approved Python executes with runtime privileges; this is not a
sandbox. No environment-selected code, signer, provider or path is accepted.
Missing/invalid artifacts never install a collector or authorize orders.
"""
from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
import hashlib
import importlib.machinery
import importlib.util
import json
import logging
import os
from pathlib import Path
import stat
import sys
from types import MappingProxyType, ModuleType
from typing import Any

from bot.kraken_canonical_startup_factory import (
    ReviewedCanonicalKrakenSources, make_canonical_kraken_startup_factory,
    register_canonical_kraken_collector_startup,
)
from bot.kraken_startup_evidence_binding import (
    ReviewedStartupBinding, protected_source_import_guard, report_recovery_observations,
    startup_binding_registration_state,
)
from bot.kraken_startup_receipts import (
    StartupReceiptTrust, _unique_object, approved_source_digest, register_signed_kraken_startup,
    verify_owner_diagnostic_receipt, verify_startup_receipt_set,
)

LOGGER = logging.getLogger(__name__)
SECRET_ROOT = Path("/etc/secrets")
MANIFEST_NAME = ".render-kraken-startup-binding.json"
SOURCE_NAME = ".render-kraken-startup-root.py"
CONTRACT = "nija.kraken-protected-startup-binding.v1"
MODULE_NAME = "nija_reviewed_kraken_protected_root"
_TRUST_FIELDS = frozenset({
    "service_id", "release_id", "image_sha256", "account_iiban_sha256", "api_key_sha256",
    "reviewed_provider_ids", "public_keys", "maximum_receipt_age_s",
})


class ProtectedStartupDenied(ValueError):
    """Fixed denial only; protected contents never enter diagnostics."""


class _ArtifactReadReason(Enum):
    OUTSIDE_MOUNT = "outside_mount"
    NOT_REGULAR = "not_regular"
    WRITABLE_BY_OTHERS = "writable_by_others"
    OWNER_NOT_ALLOWED = "owner_not_allowed"
    SIZE_INVALID = "size_invalid"


class _ArtifactSizeCase(Enum):
    FILE_EMPTY = "file_empty"
    FILE_OVER_LIMIT = "file_over_limit"
    READ_EMPTY = "read_empty"
    READ_OVER_LIMIT = "read_over_limit"


class _ArtifactReadDenied(ProtectedStartupDenied):
    def __init__(self, reason: _ArtifactReadReason, *, size_case: _ArtifactSizeCase | None = None) -> None:
        super().__init__("protected_file_denied")
        self.reason = reason
        self.size_case = size_case


def _read_protected(name: str, maximum_bytes: int) -> bytes:
    # Render secret volumes may use symlinks into a versioned directory. Follow
    # those only inside the fixed protected root; read/hash/compile the same bytes.
    path = SECRET_ROOT / name
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(SECRET_ROOT.resolve(strict=True)):
        raise _ArtifactReadDenied(_ArtifactReadReason.OUTSIDE_MOUNT)
    descriptor = os.open(resolved, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        # Classify the opened file before wrapping it; fdopen can reject a
        # directory itself before the regular-file check is reached.
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise _ArtifactReadDenied(_ArtifactReadReason.NOT_REGULAR)
        if metadata.st_mode & 0o022:
            raise _ArtifactReadDenied(_ArtifactReadReason.WRITABLE_BY_OTHERS)
        if metadata.st_uid not in {0, os.geteuid()}:
            raise _ArtifactReadDenied(_ArtifactReadReason.OWNER_NOT_ALLOWED)
        if metadata.st_size <= 0:
            raise _ArtifactReadDenied(_ArtifactReadReason.SIZE_INVALID, size_case=_ArtifactSizeCase.FILE_EMPTY)
        if metadata.st_size > maximum_bytes:
            raise _ArtifactReadDenied(_ArtifactReadReason.SIZE_INVALID, size_case=_ArtifactSizeCase.FILE_OVER_LIMIT)
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            source = stream.read(maximum_bytes + 1)
    finally:
        os.close(descriptor)
    if not source:
        raise _ArtifactReadDenied(_ArtifactReadReason.SIZE_INVALID, size_case=_ArtifactSizeCase.READ_EMPTY)
    if len(source) > maximum_bytes:
        raise _ArtifactReadDenied(_ArtifactReadReason.SIZE_INVALID, size_case=_ArtifactSizeCase.READ_OVER_LIMIT)
    return source


def _manifest(raw: bytes) -> tuple[StartupReceiptTrust, Mapping[str, str]]:
    manifest = json.loads(raw, object_pairs_hook=_unique_object)
    if (type(manifest) is not dict or set(manifest) != {"contract", "trust", "receipts"}
            or manifest["contract"] != CONTRACT):
        raise ProtectedStartupDenied("protected_manifest_denied")
    pins = manifest["trust"]
    receipts = manifest["receipts"]
    if type(pins) is not dict or set(pins) != _TRUST_FIELDS or type(receipts) is not dict:
        raise ProtectedStartupDenied("protected_manifest_denied")
    keys = pins["public_keys"]
    if (type(keys) is not dict or any(type(value) is not str or len(value) != 64
                                    or any(c not in "0123456789abcdef" for c in value)
                                    for value in keys.values())):
        raise ProtectedStartupDenied("protected_manifest_denied")
    trust = StartupReceiptTrust(**{**pins, "public_keys": {
        role: bytes.fromhex(value) for role, value in keys.items()
    }})
    return trust, MappingProxyType(dict(receipts))


class _VerifiedSourceLoader(importlib.machinery.SourceFileLoader):
    """Compile only the immutable bytes authenticated before module execution."""

    def __init__(self, source: bytes) -> None:
        super().__init__(MODULE_NAME, str(SECRET_ROOT / SOURCE_NAME))
        self._verified_source = source

    def get_code(self, fullname: str) -> Any:
        # No bytecode cache or second path read can replace the reviewed bytes.
        return self.source_to_code(self._verified_source, self.path)


def _load_verified_source(source: bytes) -> ModuleType:
    loader = _VerifiedSourceLoader(source)
    spec = importlib.util.spec_from_loader(loader.name, loader)
    if spec is None:
        raise ProtectedStartupDenied("protected_source_denied")
    module = importlib.util.module_from_spec(spec)
    if spec.name in sys.modules:
        raise ProtectedStartupDenied("protected_module_identity_conflict")
    sys.modules[spec.name] = module
    try:
        loader.exec_module(module)
    except BaseException:
        if sys.modules.get(spec.name) is module:
            del sys.modules[spec.name]
        raise
    return module


def register_from_protected_root() -> str:
    """Register the existing signed factory; never observe or install providers.

    Called only after canonical writer/broker/strategy startup by bot_main, in
    the same interpreter as its existing atomic installer. Trust anchors and
    complete root code must be independently reviewed and provisioned first.
    """
    state = startup_binding_registration_state()
    if state == "registered":
        return "existing_startup_binding_preserved"
    if state != "missing":
        return "incomplete_startup_binding_preserved"
    module = None
    registered_here = False
    stage = "manifest_read"
    try:
        manifest_bytes = _read_protected(MANIFEST_NAME, 65536)
        stage = "manifest_parse"
        trust, receipts = _manifest(manifest_bytes)
        stage = "receipt_validation"
        verify_receipts = verify_startup_receipt_set
        if not verify_receipts(receipts, trust):
            verify_receipts = verify_owner_diagnostic_receipt
            if not verify_receipts(receipts, trust):
                return "protected_startup_receipts_denied"
        stage = "source_read"
        source = _read_protected(SOURCE_NAME, 131072)
        stage = "source_digest"
        if approved_source_digest(receipts) != hashlib.sha256(source).hexdigest():
            return "protected_startup_source_digest_denied"
        stage = "source_import"
        with protected_source_import_guard():
            module = _load_verified_source(source)
        stage = "source_interface"
        resolver = getattr(module, "resolve_sources", None)
        reviewer = getattr(module, "review_sources", None)
        if not callable(resolver) or not callable(reviewer):
            return "protected_startup_source_interface_denied"
        stage = "receipt_revalidation"
        if not verify_receipts(receipts, trust):
            return "protected_startup_receipts_denied"

        def resolve_sources(**canonical: Any) -> ReviewedCanonicalKrakenSources:
            sources = resolver(**canonical, trust=trust, receipts=receipts)
            if (type(sources) is not ReviewedCanonicalKrakenSources
                    or dict(sources.receipts) != dict(receipts)):
                raise ProtectedStartupDenied("protected_source_receipts_mismatch")
            return sources

        def review_sources(sources: ReviewedCanonicalKrakenSources) -> Any:
            return reviewer(sources, trust=trust)

        stage = "canonical_registration"
        if verify_receipts is verify_owner_diagnostic_receipt:
            factory = make_canonical_kraken_startup_factory(
                trust=trust, resolve_sources=resolve_sources, review_sources=review_sources,
            )

            def recovery_factory(**canonical: Any) -> ReviewedStartupBinding:
                if not verify_owner_diagnostic_receipt(receipts, trust):
                    raise ProtectedStartupDenied("protected_diagnostic_receipt_denied")
                binding = factory(**canonical)
                if not verify_owner_diagnostic_receipt(receipts, trust):
                    raise ProtectedStartupDenied("protected_diagnostic_receipt_denied")
                report_recovery_observations(binding)
                return binding

            # Its normal verifier rejects diagnostic receipts regardless of sample results.
            register_signed_kraken_startup(recovery_factory, trust)
            registered_here = True
            return "protected_startup_recovery_diagnostics_registered"
        register_canonical_kraken_collector_startup(
            trust=trust, resolve_sources=resolve_sources, review_sources=review_sources,
        )
        registered_here = True
        return "protected_startup_factory_registered"
    except PermissionError:
        return "protected_startup_permission_denied"
    except FileNotFoundError:
        return "protected_startup_artifacts_missing"
    except _ArtifactReadDenied as denial:
        # Only the reader's closed set of labels is safe to include here.
        if stage in {"manifest_read", "source_read"} and type(denial.reason) is _ArtifactReadReason:
            if denial.reason is _ArtifactReadReason.SIZE_INVALID and type(denial.size_case) is _ArtifactSizeCase:
                LOGGER.warning(
                    "KRAKEN_PROTECTED_STARTUP_ARTIFACT_DENIED stage=%s reason=%s size_case=%s authorizes_orders=false",
                    stage, denial.reason.value, denial.size_case.value,
                )
            else:
                LOGGER.warning(
                    "KRAKEN_PROTECTED_STARTUP_ARTIFACT_DENIED stage=%s reason=%s authorizes_orders=false",
                    stage, denial.reason.value,
                )
        else:
            LOGGER.warning("KRAKEN_PROTECTED_STARTUP_STAGE_DENIED stage=%s authorizes_orders=false", stage)
        return "protected_startup_registration_denied"
    except (Exception, SystemExit):
        # Only an internal literal is logged; never include the exception or
        # protected paths, values, source contents or receipt details.
        LOGGER.warning("KRAKEN_PROTECTED_STARTUP_STAGE_DENIED stage=%s authorizes_orders=false", stage)
        return "protected_startup_registration_denied"
    finally:
        if module is not None and not registered_here and sys.modules.get(MODULE_NAME) is module:
            del sys.modules[MODULE_NAME]
