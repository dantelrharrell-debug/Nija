"""Patch every loaded CapitalAuthority publisher alias with V209/V229 completeness logic.

Production on 2026-08-25 showed V229 ready while canonical publication still
failed closed as incomplete_broker_aggregation:2/3 and heartbeat execution was
blocked by capital_snapshot_stale. V209 patches bot.capital_authority only; a
separately loaded capital_authority module can therefore publish without V209's
same-cycle exact-zero augmentation.

V230 patches publish_snapshot on every loaded CapitalAuthority class reachable
through bot.capital_authority and capital_authority. Duplicate module/class
identities are deduplicated. The wrapper delegates augmentation to V209, whose
provenance reader is hardened by V229 before V230 is installed from V229. Thus
only a same-cycle live exact zero can restore a missing broker entry; positive,
stale, timeout, error, excluded or conflicting observations remain fail closed.

Wrapper-order hardening
-----------------------
Production at 05:30 UTC showed both V230 aliases patched yet V170 still rejected
raw 2/3 snapshots before any V229 diagnostic/restoration ran. The cause was
``functools.wraps`` marker inheritance: when a later wrapper (for example V170)
wrapped V230, it copied V230's custom marker into its own ``__dict__``. The old
idempotence test used ``getattr(current, _PATCH_ATTR)`` and therefore mistook the
outer non-V230 wrapper for the active V230 boundary. V230 now tracks the exact
wrapper function objects it owns in a WeakSet. If another wrapper is replayed
outside V230, the reassert worker detects that the current method is not a direct
V230 wrapper and re-anchors augmentation outside it. This preserves every inner
safety/rejection gate while ensuring completeness augmentation runs first.
After V230's publisher aliases are converged, V231 is installed to keep current
writer-authority truth independent from Kraken nonce maturity and to remove the
legacy Coinbase-only nonce shortcut when Kraken is an active connected broker.

V230 never fabricates positive capital, changes capital totals, freshness TTL,
completeness thresholds, writer/nonce/risk/kill-switch state, execution proof,
order/fill proof, or activation state.
"""
from __future__ import annotations

import importlib
import logging
import os
import sys
import threading
import time
import weakref
from functools import wraps
from types import ModuleType
from typing import Any, Callable

LOGGER = logging.getLogger("nija.runtime_capital_authority_alias_v230")
MARKER = "20260825-runtime-capital-authority-alias-v230"
RELEASE_ID = "20260825-runtime-convergence-v230"
_READY_FLAG = "NIJA_RUNTIME_CAPITAL_AUTHORITY_ALIAS_V230_READY"
_PATCH_ATTR = "_nija_runtime_capital_authority_alias_v230"
_LOCK = threading.RLock()
_THREAD: threading.Thread | None = None
_AUTHORITY_NAMES = ("bot.capital_authority", "capital_authority")
_DIRECT_WRAPPERS: weakref.WeakSet[Callable[..., Any]] = weakref.WeakSet()


def _loaded_authority_classes() -> list[tuple[str, type]]:
    """Return distinct loaded CapitalAuthority classes across canonical aliases."""
    rows: list[tuple[str, type]] = []
    seen: set[int] = set()
    for name in _AUTHORITY_NAMES:
        module = sys.modules.get(name)
        if not isinstance(module, ModuleType):
            continue
        cls = getattr(module, "CapitalAuthority", None)
        if not isinstance(cls, type) or id(cls) in seen:
            continue
        seen.add(id(cls))
        rows.append((name, cls))
    return rows


def _is_direct_wrapper(method: Any) -> bool:
    """Return True only when *method itself* is a V230-owned outer wrapper.

    Do not trust a copied custom attribute here. ``functools.wraps`` propagates
    the wrapped function's ``__dict__`` to a new outer wrapper, which is exactly
    the production ordering failure this check prevents.
    """
    try:
        return method in _DIRECT_WRAPPERS
    except TypeError:
        return False


def _patch_class(alias: str, cls: type) -> bool:
    current = getattr(cls, "publish_snapshot", None)
    if not callable(current):
        return False
    if _is_direct_wrapper(current):
        return True

    inherited_marker = bool(getattr(current, _PATCH_ATTR, False))

    @wraps(current)
    def publish_v230(self: Any, snapshot: Any, writer_id: str) -> bool:
        try:
            v209 = importlib.import_module("bot.runtime_zero_balance_completeness_v209_patch")
            augment = getattr(v209, "_augment_snapshot", None)
            if not callable(augment):
                raise RuntimeError("v209_augment_missing")
            augmented, additions = augment(snapshot)
        except Exception as exc:
            LOGGER.error(
                "CAPITAL_AUTHORITY_ALIAS_V230_AUGMENT_FAILED marker=%s alias=%s error=%s:%s "
                "snapshot_unchanged=true trading_fail_closed=true",
                MARKER, alias, type(exc).__name__, exc,
            )
            augmented, additions = snapshot, ()

        if additions:
            LOGGER.critical(
                "CAPITAL_AUTHORITY_ALIAS_V230_RESTORED marker=%s alias=%s brokers=%s "
                "exact_same_cycle_zero_only=true positive_balance_fabricated=false "
                "capital_total_unchanged=true freshness_extended=false "
                "completeness_threshold_unchanged=true execution_authority_granted=false "
                "forced_trade=false safety_gates_bypassed=false",
                MARKER, alias, list(additions),
            )
        return bool(current(self, augmented, writer_id))

    setattr(publish_v230, _PATCH_ATTR, True)
    setattr(publish_v230, "__wrapped__", current)
    _DIRECT_WRAPPERS.add(publish_v230)
    cls.publish_snapshot = publish_v230

    if inherited_marker:
        LOGGER.warning(
            "CAPITAL_AUTHORITY_ALIAS_V230_REANCHORED marker=%s alias=%s "
            "copied_marker_detected=true outer_wrapper_repaired=true "
            "augmentation_runs_before_inner_gates=true completeness_threshold_unchanged=true "
            "trading_fail_closed=true",
            MARKER,
            alias,
        )
    return _is_direct_wrapper(cls.publish_snapshot)


def _patch_loaded_aliases() -> tuple[int, int]:
    rows = _loaded_authority_classes()
    patched = 0
    for alias, cls in rows:
        if _patch_class(alias, cls):
            patched += 1
    return patched, len(rows)


def _register_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_capital_authority_alias_v230"] = _READY_FLAG
        return True
    except Exception:
        return False


def _install_v231() -> bool:
    """Install authority/nonce truth convergence after V230 is established."""
    try:
        module = importlib.import_module("bot.runtime_authority_nonce_truth_convergence_v231_patch")
        installer = getattr(module, "install", None)
        return bool(callable(installer) and installer())
    except Exception as exc:
        LOGGER.error(
            "RUNTIME_AUTHORITY_NONCE_TRUTH_V231_INSTALL_ERROR marker=%s error=%s:%s trading_fail_closed=true",
            MARKER,
            type(exc).__name__,
            exc,
        )
        return False


def _worker() -> None:
    while True:
        try:
            _patch_loaded_aliases()
            _register_manifest()
            _install_v231()
        except Exception as exc:
            LOGGER.warning(
                "CAPITAL_AUTHORITY_ALIAS_V230_REASSERT_ERROR marker=%s error=%s:%s "
                "trading_fail_closed=true",
                MARKER, type(exc).__name__, exc,
            )
        time.sleep(max(1.0, float(os.environ.get("NIJA_CAPITAL_AUTHORITY_ALIAS_V230_INTERVAL_S", "5") or 5)))


def install() -> bool:
    global _THREAD
    with _LOCK:
        # V229 invokes V230 only after V209 and V229 provenance hooks are ready.
        v209 = importlib.import_module("bot.runtime_zero_balance_completeness_v209_patch")
        if getattr(v209, "install", lambda: False)() is False:
            os.environ[_READY_FLAG] = "0"
            return False

        importlib.import_module("bot.capital_authority")
        patched, loaded = _patch_loaded_aliases()
        manifest_ok = _register_manifest()
        base_ready = bool(loaded >= 1 and patched == loaded and manifest_ok)
        # Install V231 only after V230's own publisher safety boundary is ready.
        v231_ok = bool(base_ready and _install_v231())
        ready = bool(base_ready and v231_ok)
        os.environ[_READY_FLAG] = "1" if ready else "0"
        if ready and (_THREAD is None or not _THREAD.is_alive()):
            _THREAD = threading.Thread(
                target=_worker,
                name="RuntimeCapitalAuthorityAliasV230",
                daemon=True,
            )
            _THREAD.start()
        LOGGER.critical(
            "RUNTIME_CAPITAL_AUTHORITY_ALIAS_V230 marker=%s ready=%s loaded_alias_classes=%d "
            "patched_alias_classes=%d duplicate_identity_dedup=true direct_wrapper_identity=true "
            "wraps_marker_inheritance_safe=true v209_v229_required=true "
            "exact_same_cycle_zero_only=true positive_balance_fabricated=false stale_balance_reused=false "
            "patched_alias_classes=%d duplicate_identity_dedup=true v209_v229_required=true "
            "v231_authority_nonce_truth=%s exact_same_cycle_zero_only=true "
            "positive_balance_fabricated=false stale_balance_reused=false "
            "freshness_extended=false completeness_threshold_unchanged=true "
            "writer_nonce_risk_killswitch_order_fill_gates_unchanged=true forced_activation=false "
            "safety_gates_bypassed=false",
            MARKER, str(ready).lower(), loaded, patched, str(v231_ok).lower(),
        )
        return ready


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "RELEASE_ID",
    "install",
    "install_import_hook",
    "_loaded_authority_classes",
    "_is_direct_wrapper",
    "_patch_class",
    "_patch_loaded_aliases",
    "_install_v231",
]
