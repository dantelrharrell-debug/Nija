"""Runtime execution-proof and capital-publication integrity repair v169.

Production on 2026-08-20 exposed two correctness gaps after v168:

* writer-authority heartbeat code refreshed ``heartbeat_verified.flag`` with
  ``FILL_VERIFY`` even though no order/fill occurred.  This conflated process
  liveness with execution proof and could make an authority heartbeat satisfy
  ORDER/FILL activation policy;
* a bounded capital refresh could publish 2/3 brokers while a connected broker
  still held a genuinely fresh, timestamped broker-owned balance.  v161 already
  knows how to seed v35 observations from that exact evidence, but the seed ran
  only when a new balance batch was constructed, leaving a race immediately
  before v43/v164 publication augmentation.

v169 keeps those domains separate:

* authority heartbeats write only an authority-liveness marker on a separate
  path; they never write the execution-verification marker;
* execution markers written by TradingStrategy are provenance-tagged as
  ``source=heartbeat_trade`` and ``proof_kind=execution_probe``;
* ORDER_VERIFY/FILL_VERIFY are accepted only from that genuine execution-probe
  source.  Pre-v169 authority-generated FILL_VERIFY markers fail closed;
* stale/detached module objects are patched too, so an older authority monitor
  cannot keep writing execution proof after module-identity convergence removes
  its import alias from ``sys.modules``;
* target imports reassert the patch so late imports cannot silently restore the
  legacy authority-to-execution marker bridge;
* immediately before v43/v164 augmentation, connected platform brokers are
  offered to v161's existing timestamp/freshness-checked observation seeder.
  Stale or missing broker timestamps remain excluded.

This patch does not extend capital freshness/publication expiry, fabricate a
balance, change the v168 three-thread absolute ceiling, force a trade, clear a
kill switch, weaken nonce/writer authority, or bypass risk/order gates.
"""
from __future__ import annotations

import builtins
import gc
import importlib
import json
import logging
import os
import sys
import threading
import time
from functools import wraps
from pathlib import Path
from types import ModuleType
from typing import Any, Iterator

LOGGER = logging.getLogger("nija.runtime_execution_capital_integrity_v169")
MARKER = "20260820-runtime-execution-capital-integrity-v169"
_READY_FLAG = "NIJA_RUNTIME_EXECUTION_CAPITAL_INTEGRITY_V169_READY"
_PATCH_ATTR = "_nija_runtime_execution_capital_integrity_v169"
_IMPORT_HOOK_ATTR = "_NIJA_RUNTIME_EXECUTION_CAPITAL_INTEGRITY_V169_IMPORT_HOOK"
_LOCK = threading.RLock()

_STAGE_ORDER = {"AUTH_VERIFY": 1, "ORDER_VERIFY": 2, "FILL_VERIFY": 3}
_EXECUTION_SOURCE = "heartbeat_trade"
_EXECUTION_KIND = "execution_probe"
_AUTHORITY_SOURCE = "authority_heartbeat"
_AUTHORITY_KIND = "authority_liveness"
_TARGET_IMPORT_SUFFIXES = (
    "authority_heartbeat",
    "heartbeat_authority_single_source_patch",
    "trading_strategy",
    "trading_state_machine",
)


def _authority_marker_path() -> Path:
    return Path(
        os.environ.get(
            "NIJA_AUTHORITY_LIVENESS_MARKER_PATH",
            "./data/authority_heartbeat.flag",
        )
    )


def _execution_marker_path() -> Path:
    return Path(os.environ.get("HEARTBEAT_MARKER_PATH", "./data/heartbeat_verified.flag"))


def _atomic_json_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def _write_authority_liveness_marker(
    *,
    epoch_ts: float | None = None,
    source: str = _AUTHORITY_SOURCE,
) -> None:
    """Publish authority liveness without mutating execution verification proof."""
    ts = float(epoch_ts if epoch_ts is not None else time.time())
    payload = {
        "stage": "AUTH_VERIFY",
        "verified_at_epoch": ts,
        "source": str(source or _AUTHORITY_SOURCE),
        "proof_kind": _AUTHORITY_KIND,
        "writer_generation": str(
            os.environ.get("NIJA_WRITER_LEASE_GENERATION", "")
            or os.environ.get("NIJA_WRITER_GENERATION", "")
            or ""
        ),
    }
    _atomic_json_write(_authority_marker_path(), payload)


def _module_candidates(*names: str) -> Iterator[ModuleType]:
    """Yield live and detached module objects for one runtime surface.

    Module-identity convergence can remove a duplicate alias from ``sys.modules``
    while a background thread still references functions whose ``__globals__``
    belong to that detached module object.  Inspecting GC-tracked modules closes
    that gap without changing import identity or resurrecting an alias.
    """
    wanted = {str(name or "").strip() for name in names if str(name or "").strip()}
    leaf_names = {name.rsplit(".", 1)[-1] for name in wanted}
    seen: set[int] = set()

    for name in names:
        module = sys.modules.get(name)
        if isinstance(module, ModuleType) and id(module) not in seen:
            seen.add(id(module))
            yield module

    if not seen and names:
        try:
            module = importlib.import_module(names[0])
        except Exception:
            module = None
        if isinstance(module, ModuleType) and id(module) not in seen:
            seen.add(id(module))
            yield module

    for obj in gc.get_objects():
        try:
            if not isinstance(obj, ModuleType) or id(obj) in seen:
                continue
            module_name = str(getattr(obj, "__name__", "") or "")
            module_file = str(getattr(obj, "__file__", "") or "")
            module_leaf = Path(module_file).stem if module_file else ""
            if module_name not in wanted and module_leaf not in leaf_names:
                continue
            seen.add(id(obj))
            yield obj
        except Exception:
            continue


def _patch_authority_heartbeat_writer() -> bool:
    matched = False
    for module in _module_candidates("bot.authority_heartbeat", "authority_heartbeat"):
        current = getattr(module, "_write_heartbeat_marker", None)
        if not callable(current):
            continue
        matched = True
        if bool(getattr(current, _PATCH_ATTR, False)):
            if hasattr(module, "_DEFAULT_MARKER_STAGE"):
                module._DEFAULT_MARKER_STAGE = "AUTH_VERIFY"
            continue

        @wraps(current)
        def authority_only() -> None:
            _write_authority_liveness_marker(source="authority_heartbeat")
            LOGGER.info(
                "EXECUTION_PROOF_V169_AUTHORITY_MARKER_ISOLATED marker=%s authority_path=%s "
                "execution_marker_mutated=false stage=AUTH_VERIFY",
                MARKER,
                _authority_marker_path(),
            )

        setattr(authority_only, _PATCH_ATTR, True)
        setattr(authority_only, "__wrapped__", current)
        module._write_heartbeat_marker = authority_only
        if hasattr(module, "_DEFAULT_MARKER_STAGE"):
            module._DEFAULT_MARKER_STAGE = "AUTH_VERIFY"
    return matched


def _patch_single_source_authority_writer() -> bool:
    """Stop canonical and detached single-source bridges from writing execution proof."""
    matched = False
    for module in _module_candidates(
        "bot.heartbeat_authority_single_source_patch",
        "heartbeat_authority_single_source_patch",
    ):
        current = getattr(module, "_write_marker", None)
        if not callable(current):
            continue
        matched = True
        if bool(getattr(current, _PATCH_ATTR, False)):
            module._marker_path = _authority_marker_path
            module._marker_stage = lambda: "AUTH_VERIFY"
            continue

        @wraps(current)
        def authority_only(epoch_ts: float) -> None:
            _write_authority_liveness_marker(
                epoch_ts=float(epoch_ts),
                source="heartbeat_authority_single_source",
            )

        setattr(authority_only, _PATCH_ATTR, True)
        setattr(authority_only, "__wrapped__", current)
        module._write_marker = authority_only
        module._marker_path = _authority_marker_path
        module._marker_stage = lambda: "AUTH_VERIFY"
    return matched


def _patch_trading_strategy_provenance() -> bool:
    """Tag genuine heartbeat-trade markers with unambiguous provenance."""
    matched = False
    for module in _module_candidates("bot.trading_strategy", "trading_strategy"):
        cls = getattr(module, "TradingStrategy", None)
        if not isinstance(cls, type):
            continue
        current = getattr(cls, "_persist_heartbeat_marker", None)
        if not callable(current):
            continue
        matched = True
        if bool(getattr(current, _PATCH_ATTR, False)):
            continue

        def _make_persist_wrapper(original: Any) -> Any:
            @wraps(original)
            def persist_v169(self: Any, *, stage: str, details: Any = None) -> None:
                normalized = str(stage or "").strip().upper()
                if normalized not in _STAGE_ORDER:
                    raise ValueError(f"invalid heartbeat execution stage: {normalized or 'missing'}")
                original(self, stage=normalized, details=details)
                path = _execution_marker_path()
                raw = path.read_text(encoding="utf-8").strip()
                payload = json.loads(raw) if raw.startswith("{") else {}
                payload["stage"] = normalized
                payload["source"] = _EXECUTION_SOURCE
                payload["proof_kind"] = _EXECUTION_KIND
                payload.setdefault("verified_at_epoch", time.time())
                _atomic_json_write(path, payload)
                LOGGER.critical(
                    "EXECUTION_PROOF_V169_RECORDED marker=%s stage=%s source=%s proof_kind=%s",
                    MARKER,
                    normalized,
                    _EXECUTION_SOURCE,
                    _EXECUTION_KIND,
                )

            setattr(persist_v169, _PATCH_ATTR, True)
            setattr(persist_v169, "__wrapped__", original)
            return persist_v169

        cls._persist_heartbeat_marker = _make_persist_wrapper(current)
    return matched


def _execution_provenance_valid(
    payload: dict[str, Any],
    required_stage: str,
) -> tuple[bool, str]:
    """Require genuine execution provenance for ORDER/FILL verification."""
    required = str(required_stage or "ORDER_VERIFY").strip().upper()
    if required not in _STAGE_ORDER:
        required = "ORDER_VERIFY"
    if _STAGE_ORDER[required] < _STAGE_ORDER["ORDER_VERIFY"]:
        return True, "auth_only_policy"

    source = str(payload.get("source", "") or "").strip().lower()
    kind = str(payload.get("proof_kind", "") or "").strip().lower()
    if source != _EXECUTION_SOURCE or kind != _EXECUTION_KIND:
        return False, (
            "execution_proof_source_invalid:"
            f"source={source or 'missing'}:kind={kind or 'missing'}"
        )
    return True, "execution_probe_provenance_ok"


def _patch_tsm_execution_provenance() -> bool:
    matched = False
    for module in _module_candidates("bot.trading_state_machine", "trading_state_machine"):
        current = getattr(module, "_heartbeat_verification_status", None)
        if not callable(current):
            continue
        matched = True
        if bool(getattr(current, _PATCH_ATTR, False)):
            continue

        def _make_status_wrapper(original: Any) -> Any:
            @wraps(original)
            def status_v169() -> tuple[bool, str, dict[str, Any]]:
                ok, reason, meta = original()
                meta = dict(meta or {})
                if not ok:
                    return bool(ok), str(reason or ""), meta
                try:
                    path = _execution_marker_path()
                    raw = path.read_text(encoding="utf-8").strip()
                    payload = json.loads(raw) if raw.startswith("{") else {}
                except Exception as exc:
                    return False, f"execution_proof_read_failed:{type(exc).__name__}:{exc}", meta

                required = str(meta.get("required_stage", "ORDER_VERIFY") or "ORDER_VERIFY")
                provenance_ok, provenance_reason = _execution_provenance_valid(payload, required)
                meta["source"] = str(payload.get("source", "") or "")
                meta["proof_kind"] = str(payload.get("proof_kind", "") or "")
                meta["v169_provenance"] = provenance_reason
                if not provenance_ok:
                    LOGGER.critical(
                        "EXECUTION_PROOF_V169_REJECTED marker=%s required_stage=%s stage=%s source=%s "
                        "proof_kind=%s reason=%s trading_fail_closed=true",
                        MARKER,
                        required,
                        meta.get("stage", payload.get("stage", "unknown")),
                        meta["source"] or "missing",
                        meta["proof_kind"] or "missing",
                        provenance_reason,
                    )
                    return False, provenance_reason, meta
                return True, "", meta

            setattr(status_v169, _PATCH_ATTR, True)
            setattr(status_v169, "__wrapped__", original)
            return status_v169

        module._heartbeat_verification_status = _make_status_wrapper(current)
    return matched


def _patch_execution_surfaces() -> bool:
    """Patch every execution/authority surface, including detached module objects."""
    authority_ok = _patch_authority_heartbeat_writer()
    single_source_ok = _patch_single_source_authority_writer()
    strategy_ok = _patch_trading_strategy_provenance()
    tsm_ok = _patch_tsm_execution_provenance()
    return bool(authority_ok and single_source_ok and strategy_ok and tsm_ok)


def _install_import_reassertion_hook() -> bool:
    """Reassert v169 after late imports of execution/authority surfaces."""
    if bool(getattr(builtins, _IMPORT_HOOK_ATTR, False)):
        return True

    original_import = builtins.__import__

    def guarded_import(
        name: str,
        globals: Any = None,
        locals: Any = None,
        fromlist: Any = (),
        level: int = 0,
    ) -> Any:
        module = original_import(name, globals, locals, fromlist, level)
        if any(str(name or "").endswith(suffix) for suffix in _TARGET_IMPORT_SUFFIXES):
            try:
                _patch_execution_surfaces()
            except Exception as exc:
                LOGGER.error(
                    "EXECUTION_PROOF_V169_IMPORT_REASSERT_FAILED marker=%s imported=%s error=%s:%s "
                    "trading_fail_closed=true",
                    MARKER,
                    name,
                    type(exc).__name__,
                    exc,
                )
        return module

    builtins.__import__ = guarded_import
    setattr(builtins, _IMPORT_HOOK_ATTR, True)
    return True


def _preseed_connected_platform_observations() -> tuple[int, int]:
    """Seed only broker-owned, timestamped, still-fresh observations via v161."""
    try:
        v164 = importlib.import_module("bot.runtime_capital_publication_liveness_v164_patch")
        v161 = importlib.import_module("bot.runtime_capital_position_convergence_v161_patch")
        manager = v164._canonical_manager()
        mapping = v164._manager_platform_mapping(manager)
        guard = v161._guard_module()
    except Exception:
        return 0, 0

    attempted = 0
    seeded = 0
    for key, broker in dict(mapping or {}).items():
        if broker is None:
            continue
        try:
            if not bool(v164._manager_connected(manager, key, broker)):
                continue
            broker_id = v164._normalize_broker_name(
                getattr(broker, "broker_type", None)
                or getattr(broker, "broker_name", None)
                or getattr(broker, "name", None)
                or key
            )
            if not broker_id:
                continue
            attempted += 1
            if bool(v161._seed_fresh_broker_observation(guard, broker_id, broker)):
                seeded += 1
        except Exception:
            continue
    return attempted, seeded


def _patch_v164_publish_preseed() -> bool:
    """Close the race between batch construction and v43/v164 augmentation."""
    try:
        v164 = importlib.import_module("bot.runtime_capital_publication_liveness_v164_patch")
    except Exception:
        return False
    current = getattr(v164, "_augment_candidate", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True

    @wraps(current)
    def augment_v169(snapshot: Any) -> Any:
        attempted, seeded = _preseed_connected_platform_observations()
        if attempted:
            LOGGER.info(
                "CAPITAL_V169_PREPUBLICATION_SEED marker=%s attempted=%d seeded=%d "
                "source=broker_timestamped_last_known freshness_extended=false",
                MARKER,
                attempted,
                seeded,
            )
        return current(snapshot)

    setattr(augment_v169, _PATCH_ATTR, True)
    setattr(augment_v169, "__wrapped__", current)
    v164._augment_candidate = augment_v169
    return True


def _patch_release_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_execution_capital_integrity_v169"] = _READY_FLAG
        return True
    except Exception:
        return False


def install() -> bool:
    with _LOCK:
        surfaces_ok = _patch_execution_surfaces()
        import_hook_ok = _install_import_reassertion_hook()
        capital_ok = _patch_v164_publish_preseed()
        manifest_ok = _patch_release_manifest()
        ready = bool(surfaces_ok and import_hook_ok and capital_ok and manifest_ok)
        os.environ[_READY_FLAG] = "1" if ready else "0"
        if not ready:
            LOGGER.critical(
                "RUNTIME_EXECUTION_CAPITAL_INTEGRITY_V169_FAILED marker=%s surfaces_ok=%s "
                "import_hook_ok=%s capital_ok=%s manifest_ok=%s trading_fail_closed=true",
                MARKER,
                str(surfaces_ok).lower(),
                str(import_hook_ok).lower(),
                str(capital_ok).lower(),
                str(manifest_ok).lower(),
            )
            return False

        LOGGER.critical(
            "RUNTIME_EXECUTION_CAPITAL_INTEGRITY_V169 marker=%s ready=true "
            "authority_execution_marker_isolated=true execution_provenance_required=true "
            "detached_module_repair=true import_reassertion=true "
            "prepublication_broker_timestamp_seed=true capital_thread_limit_unchanged=true "
            "freshness_extended=false publication_expiry_extended=false stale_promoted=false "
            "forced_trade=false safety_gates_bypassed=false",
            MARKER,
        )
        return True


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "install",
    "install_import_hook",
    "_authority_marker_path",
    "_execution_marker_path",
    "_write_authority_liveness_marker",
    "_module_candidates",
    "_execution_provenance_valid",
    "_preseed_connected_platform_observations",
]
