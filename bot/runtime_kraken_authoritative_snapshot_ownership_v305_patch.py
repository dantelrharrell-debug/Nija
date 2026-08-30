"""Kraken authoritative position snapshot ownership isolation v305.

Production generation 5022 on 2026-08-30 proved that authenticated Kraken
Balance reconciliation can establish a complete current platform position proof
and then lose that proof while the next maintenance refresh is merely in flight.
The authority split introduced by v286 is correct: startup position truth for
Kraken comes from v286's authenticated Balance proxy, not the strategy-oriented
KrakenBroker.get_positions/OpenPositions view.  However v285's generic broker
wrapper still surrounds KrakenBroker.get_positions and mutates the same v285
authoritative snapshot fields on every ordinary success or exception.  A routine
OpenPositions lock/contention failure can therefore revoke a still-current
Balance-derived snapshot before its original 90-second TTL expires.

v305 makes that ownership boundary explicit.  Ordinary KrakenBroker.get_positions
calls are left behaviorally unchanged -- their return values and exceptions pass
through exactly -- but any side effect those calls make to v285's authoritative
snapshot fields is restored to the exact pre-call state.  v286's authenticated
Balance path does not call KrakenBroker.get_positions; it records v285 success or
failure directly, so genuine authoritative Balance observations remain able to
advance/revoke the snapshot.

No snapshot timestamp or generation is advanced, no stale proof is relabeled
fresh, no exception is converted to success, and no position/cost basis is
fabricated.  Writer, nonce, capital, risk, kill-switch, broker health, position
cap, minimum-notional, order acknowledgement/fill confirmation, exit rules and
all exchange semantics remain unchanged.
"""
from __future__ import annotations

import importlib
import logging
import os
import sys
from functools import wraps
from types import ModuleType
from typing import Any, Callable

LOGGER = logging.getLogger("nija.runtime_kraken_authoritative_snapshot_ownership_v305")
MARKER = "20260830-kraken-authoritative-snapshot-ownership-v305"
RELEASE_ID = "20260830-runtime-convergence-v305"
_READY_FLAG = "NIJA_RUNTIME_KRAKEN_AUTHORITATIVE_SNAPSHOT_OWNERSHIP_V305_READY"
_PATCH_ATTR = "_nija_kraken_authoritative_snapshot_ownership_v305"
_MISSING = object()

# These are the complete v285 authoritative snapshot state fields.  v305 restores
# exactly what existed before an ordinary Kraken get_positions call; it never
# manufactures or refreshes any of them.
_SNAPSHOT_FIELDS = (
    "_nija_authoritative_position_snapshot_rows_v285",
    "_nija_authoritative_position_snapshot_at_monotonic_v285",
    "_nija_authoritative_position_snapshot_at_wall_v285",
    "_nija_authoritative_position_snapshot_generation_v285",
    "_nija_authoritative_position_snapshot_fetch_ok_v285",
    "_nija_authoritative_position_snapshot_error_v285",
)


def _snapshot_fields(broker: Any) -> dict[str, Any]:
    state: dict[str, Any] = {}
    for name in _SNAPSHOT_FIELDS:
        try:
            state[name] = getattr(broker, name)
        except AttributeError:
            state[name] = _MISSING
        except Exception:
            # Failing to inspect authority state must never produce a synthetic
            # replacement.  Treat the field as missing and let restore fail
            # closed on that field if the object rejects mutation.
            state[name] = _MISSING
    return state


def _restore_fields(broker: Any, state: dict[str, Any]) -> bool:
    ok = True
    for name in _SNAPSHOT_FIELDS:
        value = state.get(name, _MISSING)
        try:
            if value is _MISSING:
                try:
                    delattr(broker, name)
                except AttributeError:
                    pass
            else:
                setattr(broker, name, value)
        except Exception:
            ok = False
    return ok


def _state_changed(before: dict[str, Any], after: dict[str, Any]) -> bool:
    try:
        for name in _SNAPSHOT_FIELDS:
            left = before.get(name, _MISSING)
            right = after.get(name, _MISSING)
            if left is _MISSING or right is _MISSING:
                if left is not right:
                    return True
                continue
            if left != right:
                return True
    except Exception:
        # Conservative diagnostic only; restore happens regardless.
        return True
    return False


def _wrap_get_positions(current: Callable[..., Any]) -> Callable[..., Any]:
    if bool(getattr(current, _PATCH_ATTR, False)):
        return current

    @wraps(current)
    def get_positions_v305(self: Any, *args: Any, **kwargs: Any) -> Any:
        before = _snapshot_fields(self)
        try:
            return current(self, *args, **kwargs)
        finally:
            after = _snapshot_fields(self)
            changed = _state_changed(before, after)
            restored = _restore_fields(self, before)
            if changed:
                log = LOGGER.info if restored else LOGGER.error
                log(
                    "KRAKEN_AUTHORITATIVE_SNAPSHOT_V305_ORDINARY_READ_ISOLATED marker=%s account=%s "
                    "ordinary_get_positions_result_unchanged=true exception_unchanged=true "
                    "precall_snapshot_restored=%s snapshot_timestamp_advanced=false "
                    "snapshot_generation_advanced=false authoritative_balance_owner_v286=true "
                    "stale_promoted=false position_success_fabricated=false cost_basis_fabricated=false "
                    "execution_proof_fabricated=false safety_gates_bypassed=false",
                    MARKER,
                    str(getattr(self, "account_identifier", "unknown") or "unknown"),
                    str(restored).lower(),
                )

    setattr(get_positions_v305, _PATCH_ATTR, True)
    setattr(get_positions_v305, "__wrapped__", current)
    return get_positions_v305


def _patch_module(module: ModuleType) -> bool:
    cls = getattr(module, "KrakenBroker", None)
    if not isinstance(cls, type):
        return False
    current = getattr(cls, "get_positions", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True
    cls.get_positions = _wrap_get_positions(current)
    return bool(getattr(getattr(cls, "get_positions", None), _PATCH_ATTR, False))


def _patch_loaded_surfaces() -> tuple[bool, tuple[str, ...]]:
    try:
        importlib.import_module("bot.broker_manager")
    except Exception as exc:
        LOGGER.warning(
            "KRAKEN_AUTHORITATIVE_SNAPSHOT_V305_BROKER_IMPORT_DEFERRED marker=%s error=%s:%s",
            MARKER,
            type(exc).__name__,
            exc,
        )

    patched: list[str] = []
    seen: set[int] = set()
    for name in ("bot.broker_manager", "broker_manager"):
        module = sys.modules.get(name)
        if not isinstance(module, ModuleType) or id(module) in seen:
            continue
        seen.add(id(module))
        if _patch_module(module):
            patched.append(name)
    return bool(patched), tuple(sorted(set(patched)))


def _v286_authority_ready() -> bool:
    try:
        v286 = importlib.import_module("bot.runtime_kraken_position_refresh_liveness_v286_patch")
        proxy = getattr(v286, "_KrakenAuthoritativeProxy", None)
        fetch = getattr(v286, "_fetch_authoritative_rows_sync", None)
        return isinstance(proxy, type) and callable(fetch)
    except Exception:
        return False


def _register_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_kraken_authoritative_snapshot_ownership_v305"] = _READY_FLAG
        return True
    except Exception:
        return False


def reconcile_once() -> dict[str, Any]:
    patched, surfaces = _patch_loaded_surfaces()
    v286_ready = _v286_authority_ready()
    return {
        "ready": bool(patched and v286_ready),
        "broker_surfaces": surfaces,
        "v286_balance_authority": bool(v286_ready),
    }


def install() -> bool:
    manifest_ok = _register_manifest()
    try:
        state = reconcile_once()
    except Exception as exc:
        state = {
            "ready": False,
            "broker_surfaces": (),
            "v286_balance_authority": False,
            "error": f"{type(exc).__name__}:{exc}",
        }

    ready = bool(manifest_ok and state.get("ready"))
    os.environ[_READY_FLAG] = "1" if ready else "0"
    log = LOGGER.critical if ready else LOGGER.error
    log(
        "RUNTIME_KRAKEN_AUTHORITATIVE_SNAPSHOT_OWNERSHIP_V305_%s marker=%s ready=%s surfaces=%s "
        "v286_balance_authority=%s ordinary_get_positions_state_isolated=true "
        "ordinary_results_unchanged=true ordinary_exceptions_unchanged=true "
        "snapshot_ttl_unchanged=true timestamp_refresh=false generation_refresh=false "
        "stale_promoted=false synthetic_success=false position_cost_basis_fabricated=false "
        "forced_trade=false forced_activation=false "
        "writer_nonce_capital_risk_killswitch_broker_health_position_cap_min_notional_order_ack_fill_gates_unchanged=true "
        "safety_gates_bypassed=false",
        "READY" if ready else "NOT_READY",
        MARKER,
        str(ready).lower(),
        ",".join(state.get("broker_surfaces", ()) or ()) or "none",
        str(bool(state.get("v286_balance_authority"))).lower(),
    )
    return ready


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "RELEASE_ID",
    "install",
    "install_import_hook",
    "reconcile_once",
    "_SNAPSHOT_FIELDS",
    "_snapshot_fields",
    "_restore_fields",
    "_wrap_get_positions",
    "_patch_module",
    "_patch_loaded_surfaces",
]
