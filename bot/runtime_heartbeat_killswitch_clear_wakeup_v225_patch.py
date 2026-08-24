"""Wake a sleeping heartbeat verifier when the canonical kill switch clears (v225).

Production on 2026-08-24 showed the canonical exchange stop clearing after
platform position sync had already become ready. v202 only shortens the normal
heartbeat retry sleep for a position_sync_ready false->true transition, so a
heartbeat that failed while the stop was active can otherwise remain asleep
until its normal retry interval even though the blocker has disappeared.

v225 makes one liveness-only change: while a heartbeat retry is already sleeping
and the canonical kill switch was active at the start of that sleep, wake the
sleep as soon as the same canonical switch is observed inactive. The next loop
iteration executes the unchanged heartbeat verification path and must still pass
writer, nonce, reconciliation, capital, risk, broker-health, ECEL, min-notional,
exchange acknowledgement, and fill-verification gates.

This patch never deactivates the kill switch, never marks readiness, never grants
execution authority, never fabricates heartbeat/order/fill proof, and never
forces LIVE_ACTIVE. v202's existing position-sync wakeup behavior is preserved.
"""
from __future__ import annotations

import builtins
import importlib
import logging
import os
import sys
import time
from functools import wraps
from types import ModuleType
from typing import Any, Callable

LOGGER = logging.getLogger("nija.runtime_heartbeat_killswitch_clear_wakeup_v225")
MARKER = "20260824-heartbeat-killswitch-clear-wakeup-v225"
_READY_FLAG = "NIJA_HEARTBEAT_KILLSWITCH_CLEAR_WAKEUP_V225_READY"
_PATCH_ATTR = "_nija_heartbeat_killswitch_clear_wakeup_v225"
_IMPORT_HOOK_ATTR = "_NIJA_HEARTBEAT_KILLSWITCH_CLEAR_WAKEUP_V225_IMPORT_HOOK"
_TARGET_SUFFIX = "runtime_heartbeat_position_sync_wakeup_v202_patch"
_POLL_S = 0.25


def _canonical_kill_switch_active() -> tuple[bool, bool]:
    """Return (known, active) from the canonical KillSwitch singleton."""
    try:
        module = sys.modules.get("bot.kill_switch") or sys.modules.get("kill_switch")
        if not isinstance(module, ModuleType):
            module = importlib.import_module("bot.kill_switch")
        getter = getattr(module, "get_kill_switch", None)
        if not callable(getter):
            return False, False
        kill_switch = getter()
        probe = getattr(kill_switch, "is_active", None)
        if not callable(probe):
            return False, False
        return True, bool(probe())
    except Exception:
        return False, False


def _patch_v202(module: ModuleType) -> bool:
    """Extend v202's sleep helper without changing its runner or probe logic."""
    current = getattr(module, "_wait_for_retry_or_position_sync", None)
    position_reader = getattr(module, "_position_sync_ready", None)
    if not callable(current) or not callable(position_reader):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True

    @wraps(current)
    def wait_v225(sleep_s: float) -> bool:
        duration = max(0.0, float(sleep_s or 0.0))
        if duration <= 0.0:
            return False

        # If the kill switch is not known-active at the start of the retry sleep,
        # preserve v202 exactly. This prevents rapid retries for unrelated errors.
        kill_known, kill_active = _canonical_kill_switch_active()
        if not kill_known or not kill_active:
            return bool(current(duration))

        try:
            pos_known, pos_ready = position_reader()
        except Exception:
            pos_known, pos_ready = False, False

        deadline = time.monotonic() + duration
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0.0:
                return False
            time.sleep(min(_POLL_S, remaining))

            # Preserve v202's existing false->true position-sync transition.
            if pos_known and not pos_ready:
                try:
                    current_pos_known, current_pos_ready = position_reader()
                except Exception:
                    current_pos_known, current_pos_ready = False, False
                if current_pos_known and current_pos_ready:
                    return True

            current_kill_known, current_kill_active = _canonical_kill_switch_active()
            if current_kill_known and not current_kill_active:
                LOGGER.critical(
                    "HEARTBEAT_KILLSWITCH_CLEAR_WAKEUP_V225_TRIGGERED marker=%s "
                    "kill_switch_transition=true_to_false retry_sleep_shortened=true "
                    "next_probe_unchanged=true readiness_fabricated=false "
                    "execution_authority_granted=false proof_fabricated=false "
                    "writer_nonce_risk_reconciliation_capital_broker_health_ecel_min_notional_order_fill_gates_unchanged=true "
                    "forced_activation=false safety_gates_bypassed=false",
                    MARKER,
                )
                # Return False intentionally: the v202 runner will continue to
                # its next attempt immediately, but will not mislabel this wake as
                # a position-sync transition in its own diagnostic.
                return False

    setattr(wait_v225, _PATCH_ATTR, True)
    setattr(wait_v225, "__wrapped__", current)
    setattr(module, "_wait_for_retry_or_position_sync", wait_v225)
    installed = getattr(module, "_wait_for_retry_or_position_sync", None)
    return bool(callable(installed) and getattr(installed, _PATCH_ATTR, False))


def _patch_loaded_v202() -> bool:
    patched = False
    for name in (
        "bot.runtime_heartbeat_position_sync_wakeup_v202_patch",
        "runtime_heartbeat_position_sync_wakeup_v202_patch",
    ):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            patched = _patch_v202(module) or patched
    return patched


def _register_manifest_if_loaded() -> bool:
    manifest = sys.modules.get("bot.runtime_release_manifest_patch")
    if not isinstance(manifest, ModuleType):
        return True
    required = getattr(manifest, "_REQUIRED_FLAGS", None)
    installers = getattr(manifest, "_INSTALLERS", None)
    if not isinstance(required, dict):
        return False
    required["heartbeat_killswitch_clear_wakeup_v225"] = _READY_FLAG
    own = ("bot.runtime_heartbeat_killswitch_clear_wakeup_v225_patch", "install_import_hook")
    if isinstance(installers, tuple) and own not in installers:
        manifest._INSTALLERS = tuple(installers) + (own,)
    return True


def _install_import_hook() -> bool:
    if bool(getattr(builtins, _IMPORT_HOOK_ATTR, False)):
        return True
    original_import: Callable[..., Any] = builtins.__import__

    def importing(name: str, globals: Any = None, locals: Any = None, fromlist: Any = (), level: int = 0) -> Any:
        result = original_import(name, globals, locals, fromlist, level)
        imported_name = str(name or "")
        if imported_name.endswith(_TARGET_SUFFIX):
            try:
                _patch_loaded_v202()
            except Exception as exc:
                LOGGER.warning(
                    "HEARTBEAT_KILLSWITCH_CLEAR_WAKEUP_V225_REASSERT_ERROR marker=%s "
                    "imported=%s err=%s:%s trading_fail_closed=true",
                    MARKER,
                    imported_name,
                    type(exc).__name__,
                    exc,
                )
        if imported_name.endswith("runtime_release_manifest_patch"):
            try:
                _register_manifest_if_loaded()
            except Exception:
                pass
        return result

    builtins.__import__ = importing
    setattr(builtins, _IMPORT_HOOK_ATTR, True)
    return True


def install() -> bool:
    hook_ok = _install_import_hook()
    patch_ok = _patch_loaded_v202()
    manifest_ok = _register_manifest_if_loaded()
    # v202 may legitimately not be imported yet. In that case the import hook is
    # the installation and will patch v202 immediately after its later import.
    v202_loaded = any(
        isinstance(sys.modules.get(name), ModuleType)
        for name in (
            "bot.runtime_heartbeat_position_sync_wakeup_v202_patch",
            "runtime_heartbeat_position_sync_wakeup_v202_patch",
        )
    )
    ready = bool(hook_ok and manifest_ok and (patch_ok or not v202_loaded))
    os.environ[_READY_FLAG] = "1" if ready else "0"
    if not ready:
        LOGGER.critical(
            "HEARTBEAT_KILLSWITCH_CLEAR_WAKEUP_V225_FAILED marker=%s hook=%s patch=%s manifest=%s "
            "v202_loaded=%s trading_fail_closed=true",
            MARKER,
            str(hook_ok).lower(),
            str(patch_ok).lower(),
            str(manifest_ok).lower(),
            str(v202_loaded).lower(),
        )
        return False

    LOGGER.critical(
        "HEARTBEAT_KILLSWITCH_CLEAR_WAKEUP_V225_READY marker=%s ready=true "
        "kill_switch_clear_wakeup=true position_sync_v202_preserved=true "
        "retry_only=true kill_switch_mutated=false readiness_fabricated=false "
        "execution_authority_granted=false proof_fabricated=false forced_activation=false "
        "safety_gates_bypassed=false",
        MARKER,
    )
    return True


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "install",
    "install_import_hook",
    "_canonical_kill_switch_active",
    "_patch_v202",
]
