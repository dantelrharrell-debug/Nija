"""Runtime authority/position convergence repair v175.

Production after v174 showed two fail-closed liveness gaps:

* strategy publication could wait on process-local writer token/generation aliases
  even while the canonical EntrypointWriterAuthority still held an exact Redis
  lease; and
* the v161 position monitor could select an empty compatibility manager before a
  populated canonical manager, publishing ``ready=false pending=[] status={}``.

v175 repairs those gaps without creating authority or synthesizing readiness.
Writer lineage is republished only after v77 proves exact current Redis ownership.
Position monitoring selects the manager with the strongest live connected-broker
view and still requires every connected broker to carry a real adopted startup
position snapshot.
"""
from __future__ import annotations

import importlib
import logging
import os
import sys
import threading
from functools import wraps
from types import ModuleType
from typing import Any

LOGGER = logging.getLogger("nija.runtime_authority_position_convergence_v175")
MARKER = "20260821-runtime-authority-position-convergence-v175"
RELEASE_ID = "20260821-runtime-convergence-v175"
_READY_FLAG = "NIJA_RUNTIME_AUTHORITY_POSITION_CONVERGENCE_V175_READY"
_PATCH_ATTR = "_nija_runtime_authority_position_convergence_v175"
_LOCK = threading.RLock()
_INSTALLED = False


def _writer_env_complete() -> bool:
    return bool(
        str(os.environ.get("NIJA_WRITER_FENCING_TOKEN", "") or "").strip()
        and str(os.environ.get("NIJA_WRITER_LEASE_GENERATION", "") or "").strip()
    )


def restore_writer_lineage_from_exact_owner(source: str = "runtime") -> tuple[bool, str]:
    """Restore local writer aliases only from v77 exact-owner proof."""
    if _writer_env_complete():
        return True, "already_complete"
    try:
        v77 = importlib.import_module("bot.writer_authority_reconstitution_v77_patch")
        proof, reason = v77.exact_owner_proof()
        if proof is None:
            LOGGER.warning(
                "WRITER_V175_LINEAGE_RESTORE_BLOCKED marker=%s source=%s reason=%s "
                "authority_synthesized=false trading_fail_closed=true",
                MARKER,
                source,
                reason,
            )
            return False, str(reason)
        ok, generation, detail = v77.publish_local_lineage(
            proof,
            f"v175:{source}",
        )
        complete = bool(ok and generation > 0 and _writer_env_complete())
        if complete:
            LOGGER.critical(
                "WRITER_V175_LINEAGE_RESTORED marker=%s source=%s generation=%s "
                "exact_owner=true redis_mutation=false token_fabricated=false",
                MARKER,
                source,
                generation,
            )
            return True, str(detail)
        return False, "v77_publication_incomplete"
    except Exception as exc:
        LOGGER.warning(
            "WRITER_V175_LINEAGE_RESTORE_ERROR marker=%s source=%s error=%s:%s "
            "trading_fail_closed=true",
            MARKER,
            source,
            type(exc).__name__,
            exc,
        )
        return False, f"{type(exc).__name__}:{exc}"


def _patch_strategy_publication() -> bool:
    try:
        module = importlib.import_module("bot.strategy_publication_patch")
    except Exception:
        return False
    current = getattr(module, "_ready", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True
    original = current

    @wraps(original)
    def ready_v175():
        ready, reason = original()
        if ready or reason not in {"writer_token_missing", "writer_generation_missing"}:
            return ready, reason
        restored, detail = restore_writer_lineage_from_exact_owner(
            f"strategy_publication:{reason}"
        )
        if not restored:
            return False, reason
        ready2, reason2 = original()
        LOGGER.info(
            "STRATEGY_V175_AUTHORITY_RECHECK marker=%s initial_reason=%s restored=true "
            "ready=%s detail=%s authority_bypass=false",
            MARKER,
            reason,
            str(bool(ready2)).lower(),
            detail,
        )
        return ready2, reason2

    setattr(ready_v175, _PATCH_ATTR, True)
    setattr(ready_v175, "__wrapped__", original)
    module._ready = ready_v175
    return True


def _candidate_managers() -> list[Any]:
    candidates: list[Any] = []
    seen: set[int] = set()
    for name in ("bot.multi_account_broker_manager", "multi_account_broker_manager"):
        module = sys.modules.get(name)
        if not isinstance(module, ModuleType):
            try:
                module = importlib.import_module(name)
            except Exception:
                continue
        getter = getattr(module, "get_broker_manager", None)
        if callable(getter):
            try:
                value = getter()
                if value is not None and id(value) not in seen:
                    seen.add(id(value))
                    candidates.append(value)
            except Exception:
                pass
        for attr in ("multi_account_broker_manager", "_manager"):
            value = getattr(module, attr, None)
            if value is not None and id(value) not in seen:
                seen.add(id(value))
                candidates.append(value)
    return candidates


def _manager_connected_count(manager: Any) -> int:
    try:
        v95 = importlib.import_module("bot.position_sync_core_handoff_v95_patch")
        connected = getattr(v95, "_connected_brokers", None)
        if callable(connected):
            return len(dict(connected(manager) or {}))
    except Exception:
        pass
    return 0


def canonical_manager_with_live_brokers() -> Any:
    """Prefer the current manager carrying the largest connected-broker view."""
    candidates = _candidate_managers()
    if not candidates:
        return None
    ranked = sorted(
        candidates,
        key=lambda manager: _manager_connected_count(manager),
        reverse=True,
    )
    winner = ranked[0]
    LOGGER.debug(
        "POSITION_SYNC_V175_MANAGER_SELECTED marker=%s candidates=%d connected=%d",
        MARKER,
        len(candidates),
        _manager_connected_count(winner),
    )
    return winner


def _patch_v161_manager_selection() -> bool:
    try:
        v161 = importlib.import_module("bot.runtime_capital_position_convergence_v161_patch")
    except Exception:
        return False
    current = getattr(v161, "_canonical_manager", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True
    original = current

    @wraps(original)
    def canonical_manager_v175():
        selected = canonical_manager_with_live_brokers()
        if selected is not None and _manager_connected_count(selected) > 0:
            return selected
        return original()

    setattr(canonical_manager_v175, _PATCH_ATTR, True)
    setattr(canonical_manager_v175, "__wrapped__", original)
    v161._canonical_manager = canonical_manager_v175
    return True


def _patch_release_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_authority_position_convergence_v175"] = _READY_FLAG
        return True
    except Exception:
        return False


def install() -> bool:
    global _INSTALLED
    with _LOCK:
        strategy_ok = _patch_strategy_publication()
        position_ok = _patch_v161_manager_selection()
        manifest_ok = _patch_release_manifest()
        ready = bool(strategy_ok and position_ok and manifest_ok)
        os.environ[_READY_FLAG] = "1" if ready else "0"
        if not ready:
            LOGGER.critical(
                "RUNTIME_AUTHORITY_POSITION_CONVERGENCE_V175_FAILED marker=%s "
                "strategy_ok=%s position_ok=%s manifest_ok=%s trading_fail_closed=true",
                MARKER,
                str(strategy_ok).lower(),
                str(position_ok).lower(),
                str(manifest_ok).lower(),
            )
            return False
        _INSTALLED = True
        LOGGER.critical(
            "RUNTIME_AUTHORITY_POSITION_CONVERGENCE_V175 marker=%s ready=true "
            "writer_exact_owner_only=true writer_token_fabricated=false redis_mutation=false "
            "position_manager_live_broker_preference=true empty_status_promoted=false "
            "position_snapshot_requirement_unchanged=true safety_gates_bypassed=false",
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
    "restore_writer_lineage_from_exact_owner",
    "canonical_manager_with_live_brokers",
    "_manager_connected_count",
    "_patch_strategy_publication",
    "_patch_v161_manager_selection",
]
