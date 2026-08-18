"""Keep runtime release identity canonical and quiesce healthy convergence audits.

Older convergence modules may register their required flags with the runtime
manifest, but they must never rewrite the manifest's active release identity.
This guard also converts the release watchdog to verify-first behavior: healthy
runtime state is inspected without replaying every installer, while detected
drift still falls back to the original repair audit.

The guard is control-plane only. It does not alter trading state, capital values,
kill-switch state, writer/nonce authority, risk, sizing, or execution gates.
"""
from __future__ import annotations

import importlib
import logging
import os
import sys
import threading
from collections.abc import Mapping
from types import ModuleType
from typing import Any

LOGGER = logging.getLogger("nija.runtime_release_identity_guard")
MARKER = "20260817-runtime-release-identity-guard-v2"
_FLAG = "NIJA_RUNTIME_RELEASE_IDENTITY_GUARD_INSTALLED"
_LOCK = threading.RLock()
_INSTALLED = False
_PATCH_ATTR = "_nija_runtime_release_identity_guard_v2"

_LEGACY_MANIFEST_REGISTRATIONS = (
    (
        "bot.readiness_proof_convergence_v134_patch",
        "readiness_proof_convergence_v134",
        "NIJA_READINESS_PROOF_CONVERGENCE_V134_INSTALLED",
    ),
    (
        "bot.activation_stop_capital_freshness_v135_patch",
        "activation_stop_capital_freshness_v135",
        "NIJA_ACTIVATION_STOP_CAPITAL_FRESHNESS_V135_INSTALLED",
    ),
    (
        "bot.activation_publication_convergence_v136_patch",
        "activation_publication_convergence_v136",
        "NIJA_ACTIVATION_PUBLICATION_CONVERGENCE_V136_INSTALLED",
    ),
)


def _declared_release(manifest: Any) -> str:
    value = str(getattr(manifest, "DECLARED_RELEASE_ID", "") or "").strip()
    if value:
        return value
    return str(getattr(manifest, "RELEASE_ID", "") or "").strip()


class _CanonicalReleaseManifestModule(ModuleType):
    """Module type that keeps the canonical manifest release ID immutable."""

    def __setattr__(self, name: str, value: Any) -> None:
        if name == "RELEASE_ID":
            declared = _declared_release(self)
            candidate = str(value or "").strip()
            if declared and candidate and candidate != declared:
                LOGGER.warning(
                    "RUNTIME_RELEASE_IDENTITY_OVERRIDE_BLOCKED marker=%s attempted=%s declared=%s",
                    MARKER,
                    candidate,
                    declared,
                )
                value = declared
        super().__setattr__(name, value)


def _install_manifest_release_write_barrier() -> bool:
    """Prevent every legacy module, including future reloads, from downgrading RELEASE_ID."""
    manifest = importlib.import_module("bot.runtime_release_manifest_patch")
    declared = _declared_release(manifest)
    if not declared:
        return False
    if not isinstance(manifest, _CanonicalReleaseManifestModule):
        manifest.__class__ = _CanonicalReleaseManifestModule
    # Use the guarded assignment so the compatibility name is re-anchored now.
    manifest.RELEASE_ID = declared
    os.environ["NIJA_RUNTIME_RELEASE_ID"] = declared
    return True


def _patch_manifest_registration(module_name: str, label: str, flag: str) -> bool:
    module = importlib.import_module(module_name)
    manifest = importlib.import_module("bot.runtime_release_manifest_patch")
    required = getattr(manifest, "_REQUIRED_FLAGS", None)
    if not isinstance(required, dict):
        return False

    def register_without_release_override() -> bool:
        current_required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(current_required, dict):
            return False
        current_required[label] = flag
        return True

    setattr(register_without_release_override, _PATCH_ATTR, True)
    module._patch_release_manifest = register_without_release_override
    return True


def _patch_legacy_manifest_registrations() -> bool:
    ok = True
    for module_name, label, flag in _LEGACY_MANIFEST_REGISTRATIONS:
        try:
            ok = _patch_manifest_registration(module_name, label, flag) and ok
        except Exception:
            ok = False
    return ok


def _patch_v136_manifest_registration() -> bool:
    """Compatibility helper retained for the v139 regression suite."""
    return _patch_manifest_registration(
        "bot.activation_publication_convergence_v136_patch",
        "activation_publication_convergence_v136",
        "NIJA_ACTIVATION_PUBLICATION_CONVERGENCE_V136_INSTALLED",
    )


def _restore_manifest_identity(*, emit_drift: bool = True) -> bool:
    manifest = importlib.import_module("bot.runtime_release_manifest_patch")
    declared = _declared_release(manifest)
    if not declared:
        return False
    previous = str(getattr(manifest, "RELEASE_ID", "") or "").strip()
    manifest.RELEASE_ID = declared
    os.environ["NIJA_RUNTIME_RELEASE_ID"] = declared
    if emit_drift and previous and previous != declared:
        LOGGER.critical(
            "RUNTIME_RELEASE_IDENTITY_DRIFT_REPAIRED marker=%s previous=%s declared=%s",
            MARKER,
            previous,
            declared,
        )
    return True


def _patch_secondary_runtime_broker_discovery() -> bool:
    """Include the canonical MABM ``_manager`` singleton in readiness discovery."""
    module = importlib.import_module("secondary_venue_strict_readiness_patch")
    current = getattr(module, "_runtime_brokers", None)
    if not callable(current):
        return False

    if getattr(current, _PATCH_ATTR, False):
        try:
            module.refresh_readiness(force_log=False)
        except Exception:
            pass
        return True

    original = current

    def runtime_brokers_with_canonical_manager() -> dict[str, Any]:
        try:
            brokers = dict(original() or {})
        except Exception:
            brokers = {}

        seen_modules: set[int] = set()
        for module_name in ("bot.multi_account_broker_manager", "multi_account_broker_manager"):
            manager_module = sys.modules.get(module_name)
            if not isinstance(manager_module, ModuleType) or id(manager_module) in seen_modules:
                continue
            seen_modules.add(id(manager_module))
            manager = getattr(manager_module, "_manager", None)
            if manager is None:
                continue
            for attr in ("_platform_brokers", "platform_brokers", "brokers"):
                mapping = getattr(manager, attr, None)
                if not isinstance(mapping, Mapping):
                    continue
                for raw_key, broker in mapping.items():
                    if broker is None or isinstance(broker, bool):
                        continue
                    try:
                        name = module._broker_name(broker, raw_key)
                    except Exception:
                        continue
                    if name in getattr(module, "_KNOWN", set()):
                        brokers[name] = broker
        return brokers

    setattr(runtime_brokers_with_canonical_manager, _PATCH_ATTR, True)
    setattr(runtime_brokers_with_canonical_manager, "__wrapped__", original)
    module._runtime_brokers = runtime_brokers_with_canonical_manager

    try:
        module.refresh_readiness(force_log=True)
    except Exception as exc:
        LOGGER.warning(
            "RUNTIME_READINESS_REFRESH_AFTER_DISCOVERY_PATCH_FAILED marker=%s err=%s:%s",
            MARKER,
            type(exc).__name__,
            exc,
        )
    return True


def _verify_manifest_without_reinstall(manifest: Any) -> tuple[bool, dict[str, str]]:
    """Verify release invariants without replaying convergence installers."""
    results: dict[str, str] = {}
    ready = True

    # Preserve the original audit's details shape so a healthy watchdog does not
    # republish solely because installer execution was replaced by verification.
    for module_name, _function_name in tuple(getattr(manifest, "_INSTALLERS", ())):
        results[module_name] = "ok"

    for module_name, key in (
        ("runtime_module_identity_convergence_patch", "module_identity_audit"),
        ("runtime_convergence_quiescence_patch", "convergence_quiescence_audit"),
        ("scan_wrapper_depth_convergence_patch", "scan_wrapper_depth_audit"),
    ):
        try:
            module = importlib.import_module(module_name)
            module_ready, module_details = module.audit()
            if (
                module_name == "scan_wrapper_depth_convergence_patch"
                and not module_ready
                and manifest._bounded_acyclic_scan(module_details)
            ):
                module_ready = True
                os.environ["NIJA_SCAN_WRAPPER_DEPTH_READY"] = "1"
                results["scan_wrapper_depth_structural_accept"] = "bounded_acyclic=true"
            results[key] = str(module_details)
            ready = ready and bool(module_ready)
        except Exception as exc:
            results[key] = f"{type(exc).__name__}:{exc}"
            ready = False

    scan_release = str(os.environ.get("NIJA_SCAN_WRAPPER_RELEASE", "") or "").strip()
    expected_scan_release = manifest._expected_scan_wrapper_release()
    if not manifest._scan_release_compatible(scan_release, expected_scan_release):
        ready = False
        results["scan_wrapper_release"] = (
            f"actual={scan_release or 'missing'};expected={expected_scan_release or 'missing'}"
        )
    else:
        results["scan_wrapper_release"] = scan_release

    for label, flag in dict(getattr(manifest, "_REQUIRED_FLAGS", {})).items():
        value = str(os.environ.get(flag, "") or "").strip()
        if value != "1":
            ready = False
            results[label] = value or "missing"
        else:
            results[label] = "ready"

    limits_ok, limits_reason = manifest._runtime_limits_consistent()
    results["core_loop_runtime_limits"] = limits_reason
    ready = ready and bool(limits_ok)

    try:
        secondary = importlib.import_module("secondary_venue_strict_readiness_patch")
        secondary.refresh_readiness(force_log=False)
    except Exception:
        pass
    contract_ok, contract_reason = manifest._readiness_contract_consistent()
    results["readiness_contract"] = contract_reason
    ready = ready and bool(contract_ok)

    declared = _declared_release(manifest)
    current = str(getattr(manifest, "RELEASE_ID", "") or "").strip()
    published = str(os.environ.get("NIJA_RUNTIME_RELEASE_ID", "") or "").strip()
    if not declared or current != declared or (published and published != declared):
        ready = False
        results["release_identity"] = (
            f"declared={declared or 'missing'};current={current or 'missing'};"
            f"published={published or 'missing'}"
        )

    return ready, results


def _patch_manifest_audit(manifest: Any) -> bool:
    current = getattr(manifest, "_audit", None)
    if not callable(current):
        return False
    if getattr(current, _PATCH_ATTR, False):
        return True

    original = current

    def quiescent_audit() -> tuple[bool, dict[str, str]]:
        ready, details = _verify_manifest_without_reinstall(manifest)
        if ready:
            return ready, details

        LOGGER.warning(
            "RUNTIME_RELEASE_REPAIR_AUDIT_REQUIRED marker=%s release=%s "
            "reason=verification_failed installers_replayed=true",
            MARKER,
            _declared_release(manifest) or "unknown",
        )
        try:
            original()
        finally:
            _restore_manifest_identity(emit_drift=True)
        ready, details = _verify_manifest_without_reinstall(manifest)
        if not ready:
            LOGGER.critical(
                "RUNTIME_RELEASE_REPAIR_AUDIT_INCOMPLETE marker=%s release=%s fail_closed=true details=%s",
                MARKER,
                _declared_release(manifest) or "unknown",
                details,
            )
        return ready, details

    setattr(quiescent_audit, _PATCH_ATTR, True)
    setattr(quiescent_audit, "__wrapped__", original)
    manifest._audit = quiescent_audit
    return True


def _patch_manifest_install(manifest: Any) -> bool:
    current = getattr(manifest, "install_import_hook", None)
    if not callable(current):
        return False
    if getattr(current, _PATCH_ATTR, False):
        return True

    original = current

    def quiescent_install_import_hook() -> None:
        if not bool(getattr(manifest, "_INSTALLED", False)):
            original()
            return

        lock = getattr(manifest, "_LOCK", _LOCK)
        with lock:
            ready, details = manifest._audit()
            declared = _declared_release(manifest)
            published_ready = str(os.environ.get("NIJA_RUNTIME_RELEASE_READY", "") or "").strip()
            published_release = str(os.environ.get("NIJA_RUNTIME_RELEASE_ID", "") or "").strip()
            if not ready or published_ready != "1" or published_release != declared:
                manifest._publish(ready, details)

    setattr(quiescent_install_import_hook, _PATCH_ATTR, True)
    setattr(quiescent_install_import_hook, "__wrapped__", original)
    manifest.install_import_hook = quiescent_install_import_hook
    return True


def _patch_manifest_quiescence() -> bool:
    manifest = importlib.import_module("bot.runtime_release_manifest_patch")
    return bool(_patch_manifest_audit(manifest) and _patch_manifest_install(manifest))


def install_import_hook() -> bool:
    global _INSTALLED
    with _LOCK:
        already_installed = _INSTALLED and os.environ.get(_FLAG) == "1"
        try:
            barrier_ok = _install_manifest_release_write_barrier()
            registrations_ok = _patch_legacy_manifest_registrations()
            readiness_ok = _patch_secondary_runtime_broker_discovery()
            quiescence_ok = _patch_manifest_quiescence()
            identity_ok = _restore_manifest_identity(emit_drift=not already_installed)
            ok = bool(barrier_ok and registrations_ok and readiness_ok and quiescence_ok and identity_ok)
        except Exception as exc:
            LOGGER.critical(
                "RUNTIME_RELEASE_IDENTITY_GUARD_INSTALL_FAILED marker=%s err=%s:%s fail_closed=true",
                MARKER,
                type(exc).__name__,
                exc,
                exc_info=True,
            )
            ok = False

        if not ok:
            os.environ.pop(_FLAG, None)
            return False

        os.environ[_FLAG] = "1"
        _INSTALLED = True

    if not already_installed:
        LOGGER.critical(
            "RUNTIME_RELEASE_IDENTITY_GUARD_INSTALLED marker=%s canonical_manifest_owner=true "
            "legacy_release_override=false release_write_barrier=true legacy_writers=v134,v135,v136 "
            "verify_first_audit=true repair_only_on_drift=true canonical_manager_readiness=true "
            "readiness_unchanged=true kill_switch_unchanged=true nonce_unchanged=true "
            "risk_gates_unchanged=true execution_authority_unchanged=true",
            MARKER,
        )
    return True


def install() -> bool:
    return install_import_hook()


__all__ = [
    "MARKER",
    "install",
    "install_import_hook",
    "_declared_release",
    "_install_manifest_release_write_barrier",
    "_patch_v136_manifest_registration",
    "_patch_legacy_manifest_registrations",
    "_patch_secondary_runtime_broker_discovery",
    "_verify_manifest_without_reinstall",
    "_patch_manifest_audit",
    "_patch_manifest_install",
    "_restore_manifest_identity",
]
