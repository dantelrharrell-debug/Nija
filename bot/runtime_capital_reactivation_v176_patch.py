"""Runtime capital reactivation convergence v176.

Production evidence showed a successful complete capital publication could land
milliseconds after v133 had revoked ``capital_ready`` and transitioned
``LIVE_ACTIVE -> OFF``. The next normal monitor tick eventually re-probes the
same facts, but during that gap execution remains fail-closed even though the
canonical CapitalAuthority already holds a fresh accepted snapshot.

v176 closes only that synchronization gap. It wraps the canonical
``CapitalRefreshCoordinator.execute_refresh`` return path and, after a non-None
accepted snapshot, asks the existing v16 proof collector/activation path to
re-evaluate immediately. v16's readiness writer is still owned by v133, so a
false proof is still revoked and LIVE state still fails closed. No freshness
TTL, capital value, safety gate, signal threshold, nonce rule, kill switch, or
execution permission is altered.

The 2026-08-21 follow-ups install v179, v178, v180, and v181 before the
coordinator wrapper. v179 converges bootstrap-seed generation identity plus the
canonical hydration event invariant; v178 repairs only the exact
same-canonical-publication status-poisoning case for ``snapshot_not_newer``;
v180 prevents a private direct refresh fallback from replacing a previously
complete canonical broker set after bootstrap; v181 restores v142 generation
context only for the exact current canonical coordinator worker after rollover.
None of these patches broadens freshness or activation policy.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
from functools import wraps
from typing import Any

LOGGER = logging.getLogger("nija.runtime_capital_reactivation_v176")
MARKER = "20260821-runtime-capital-reactivation-v176"
RELEASE_ID = "20260821-runtime-convergence-v176"
_READY_FLAG = "NIJA_RUNTIME_CAPITAL_REACTIVATION_V176_READY"
_PATCH_ATTR = "_nija_runtime_capital_reactivation_v176"
_LOCK = threading.RLock()


def _publication_is_fresh() -> tuple[bool, str]:
    try:
        authority_mod = importlib.import_module("bot.capital_authority")
        authority = authority_mod.get_capital_authority()
        status_fn = getattr(authority, "get_snapshot_publication_status", None)
        if callable(status_fn):
            status = status_fn()
            if status is None:
                return False, "publication_status_missing"
            if bool(getattr(status, "stale", True)):
                return False, "publication_stale"
        stale_fn = getattr(authority, "is_stale", None)
        if callable(stale_fn) and bool(stale_fn()):
            return False, "authority_stale"
        real = 0.0
        for attr in ("total_capital", "real_capital", "available_capital"):
            try:
                real = max(real, float(getattr(authority, attr, 0.0) or 0.0))
            except Exception:
                pass
        for method_name in ("get_real_capital", "get_total_capital", "get_usable_capital"):
            method = getattr(authority, method_name, None)
            if callable(method):
                try:
                    real = max(real, float(method() or 0.0))
                except Exception:
                    pass
        if real <= 0.0:
            return False, "capital_not_positive"
        return True, "fresh_positive_publication"
    except Exception as exc:
        return False, f"publication_probe_error:{type(exc).__name__}:{exc}"


def _rearm_after_publication(trigger: str) -> tuple[bool, str]:
    fresh, reason = _publication_is_fresh()
    if not fresh:
        LOGGER.warning(
            "CAPITAL_V176_REARM_BLOCKED marker=%s trigger=%s reason=%s "
            "trading_fail_closed=true freshness_extended=false stale_promoted=false",
            MARKER,
            trigger,
            reason,
        )
        return False, reason
    try:
        v16 = importlib.import_module("preactivation_readiness_convergence_v16_patch")
        attempt = getattr(v16, "_attempt_activation", None)
        if not callable(attempt):
            return False, "v16_attempt_activation_missing"
        active, details = attempt()
        pending = list(details.get("pending") or []) if isinstance(details, dict) else []
        state_after = details.get("state_after") if isinstance(details, dict) else None
        state_before = details.get("state_before") if isinstance(details, dict) else None
        LOGGER.critical(
            "CAPITAL_V176_POST_PUBLICATION_REARM marker=%s trigger=%s active=%s "
            "pending=%s state_before=%s state_after=%s canonical_commit_only=true "
            "force_activation=false freshness_extended=false stale_promoted=false "
            "safety_gates_bypassed=false",
            MARKER,
            trigger,
            str(bool(active)).lower(),
            pending,
            state_before,
            state_after,
        )
        return bool(active), "active" if active else f"pending:{','.join(pending) or 'commit_not_active'}"
    except Exception as exc:
        LOGGER.warning(
            "CAPITAL_V176_REARM_ERROR marker=%s trigger=%s error=%s:%s "
            "trading_fail_closed=true",
            MARKER,
            trigger,
            type(exc).__name__,
            exc,
        )
        return False, f"{type(exc).__name__}:{exc}"


def _install_named(module_name: str, label: str) -> bool:
    try:
        module = importlib.import_module(module_name)
        installer = getattr(module, "install", None) or getattr(module, "install_import_hook", None)
        if not callable(installer):
            return False
        return bool(installer())
    except Exception as exc:
        LOGGER.error(
            "%s_INSTALL_ERROR marker=%s module=%s error=%s:%s trading_fail_closed=true",
            label,
            MARKER,
            module_name,
            type(exc).__name__,
            exc,
        )
        return False


def _install_v179_bootstrap_capital_publication() -> bool:
    return _install_named(
        "bot.runtime_bootstrap_capital_publication_v179_patch",
        "RUNTIME_BOOTSTRAP_CAPITAL_PUBLICATION_V179",
    )


def _install_v178_publication_identity() -> bool:
    return _install_named(
        "bot.runtime_capital_publication_identity_v178_patch",
        "RUNTIME_CAPITAL_PUBLICATION_IDENTITY_V178",
    )


def _install_v180_direct_refresh_downgrade() -> bool:
    return _install_named(
        "bot.runtime_capital_direct_refresh_downgrade_v180_patch",
        "RUNTIME_CAPITAL_DIRECT_REFRESH_DOWNGRADE_V180",
    )


def _install_v181_generation_context() -> bool:
    return _install_named(
        "bot.runtime_capital_generation_context_v181_patch",
        "RUNTIME_CAPITAL_GENERATION_CONTEXT_V181",
    )


def _patch_coordinator() -> bool:
    try:
        module = importlib.import_module("bot.capital_flow_state_machine")
        cls = getattr(module, "CapitalRefreshCoordinator", None)
        if not isinstance(cls, type):
            return False
        current = getattr(cls, "execute_refresh", None)
        if not callable(current):
            return False
        if bool(getattr(current, _PATCH_ATTR, False)):
            return True
        original = current

        @wraps(original)
        def execute_refresh_v176(self: Any, broker_map: Any, trigger: str = "coordinator", *args: Any, **kwargs: Any):
            snapshot = original(self, broker_map, trigger, *args, **kwargs)
            if snapshot is not None:
                _rearm_after_publication(str(trigger or "coordinator"))
            return snapshot

        setattr(execute_refresh_v176, _PATCH_ATTR, True)
        setattr(execute_refresh_v176, "__wrapped__", original)
        cls.execute_refresh = execute_refresh_v176
        return True
    except Exception:
        return False


def _patch_release_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_capital_reactivation_v176"] = _READY_FLAG
        return True
    except Exception:
        return False


def install() -> bool:
    with _LOCK:
        v179_ok = _install_v179_bootstrap_capital_publication()
        v178_ok = _install_v178_publication_identity()
        v180_ok = _install_v180_direct_refresh_downgrade()
        v181_ok = _install_v181_generation_context()
        coordinator_ok = _patch_coordinator()
        manifest_ok = _patch_release_manifest()
        ready = bool(
            v179_ok and v178_ok and v180_ok and v181_ok and coordinator_ok and manifest_ok
        )
        os.environ[_READY_FLAG] = "1" if ready else "0"
        if not ready:
            LOGGER.critical(
                "RUNTIME_CAPITAL_REACTIVATION_V176_FAILED marker=%s v179_ok=%s v178_ok=%s "
                "v180_ok=%s v181_ok=%s coordinator_ok=%s manifest_ok=%s trading_fail_closed=true",
                MARKER,
                str(v179_ok).lower(),
                str(v178_ok).lower(),
                str(v180_ok).lower(),
                str(v181_ok).lower(),
                str(coordinator_ok).lower(),
                str(manifest_ok).lower(),
            )
            return False
        LOGGER.critical(
            "RUNTIME_CAPITAL_REACTIVATION_V176 marker=%s ready=true "
            "v179_bootstrap_capital_publication=true v178_publication_identity=true "
            "v180_direct_refresh_downgrade=true v181_generation_context=true "
            "post_publication_proof_recheck=true canonical_commit_only=true "
            "v133_fail_closed_preserved=true freshness_ttl_unchanged=true "
            "forced_activation=false safety_gates_bypassed=false",
            MARKER,
        )
        return True


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "RELEASE_ID",
    "install",
    "install_import_hook",
    "_publication_is_fresh",
    "_rearm_after_publication",
    "_install_v179_bootstrap_capital_publication",
    "_install_v178_publication_identity",
    "_install_v180_direct_refresh_downgrade",
    "_install_v181_generation_context",
    "_patch_coordinator",
]
