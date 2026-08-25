"""Patch every loaded CapitalAuthority publisher alias with V209/V229 completeness logic.

Production on 2026-08-25 showed V229 ready while canonical publication still
failed closed as incomplete_broker_aggregation:2/3 and heartbeat execution was
blocked by capital_snapshot_stale.  V209 patches bot.capital_authority only; a
separately loaded capital_authority module can therefore publish without V209's
same-cycle exact-zero augmentation.

V230 patches publish_snapshot on every loaded CapitalAuthority class reachable
through bot.capital_authority and capital_authority.  Duplicate module/class
identities are deduplicated.  The wrapper delegates augmentation to V209, whose
provenance reader is hardened by V229.  Therefore only a same-cycle live exact
zero can restore a missing broker entry; positive, stale, timeout, error,
excluded or conflicting observations remain fail closed.

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
from functools import wraps
from types import ModuleType
from typing import Any

LOGGER = logging.getLogger("nija.runtime_capital_authority_alias_v230")
MARKER = "20260825-runtime-capital-authority-alias-v230"
RELEASE_ID = "20260825-runtime-convergence-v230"
_READY_FLAG = "NIJA_RUNTIME_CAPITAL_AUTHORITY_ALIAS_V230_READY"
_PATCH_ATTR = "_nija_runtime_capital_authority_alias_v230"
_LOCK = threading.RLock()
_THREAD: threading.Thread | None = None
_AUTHORITY_NAMES = ("bot.capital_authority", "capital_authority")


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


def _patch_class(alias: str, cls: type) -> bool:
    current = getattr(cls, "publish_snapshot", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True

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
    cls.publish_snapshot = publish_v230
    return True


def _patch_loaded_aliases() -> tuple[int, int]:
    """Patch every distinct currently loaded publisher class."""
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


def _worker() -> None:
    while True:
        try:
            _patch_loaded_aliases()
            _register_manifest()
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
        # Ensure V209 then V229 are attached before this publisher wrapper.
        v209 = importlib.import_module("bot.runtime_zero_balance_completeness_v209_patch")
        v229 = importlib.import_module("bot.runtime_capital_provenance_alias_convergence_v229_patch")
        if getattr(v209, "install", lambda: False)() is False:
            os.environ[_READY_FLAG] = "0"
            return False
        if getattr(v229, "install", lambda: False)() is False:
            os.environ[_READY_FLAG] = "0"
            return False

        # Import canonical authority so at least one real publisher must exist.
        importlib.import_module("bot.capital_authority")
        patched, loaded = _patch_loaded_aliases()
        manifest_ok = _register_manifest()
        ready = bool(loaded >= 1 and patched == loaded and manifest_ok)
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
            "patched_alias_classes=%d duplicate_identity_dedup=true v209_v229_required=true "
            "exact_same_cycle_zero_only=true positive_balance_fabricated=false stale_balance_reused=false "
            "freshness_extended=false completeness_threshold_unchanged=true "
            "writer_nonce_risk_killswitch_order_fill_gates_unchanged=true forced_activation=false "
            "safety_gates_bypassed=false",
            MARKER, str(ready).lower(), loaded, patched,
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
    "_patch_loaded_aliases",
]
