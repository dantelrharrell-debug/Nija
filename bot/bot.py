"""Compatibility entrypoint for Railway/main.py.

The canonical Render launcher keeps package-wide runtime hooks deferred while
``main.py`` installs the audited safety set explicitly. Replaying every
historical compatibility installer here delayed ``bot_main.main()`` for many
minutes while the health server reported the service as live. The canonical
fast path therefore installs only narrow guards that are not already owned by
``main.py``, then hands off immediately.

Direct/non-canonical launches retain the legacy installer set for compatibility.
"""

from __future__ import annotations

import importlib
import logging
import os
import sys
from typing import Iterable

logger = logging.getLogger("nija.bot_entrypoint")
_FAST_PATH_MARKER = "20260816-canonical-fast-entrypoint-v110"
_PRECORE_STRATEGY_OWNER_MARKER = "20260822-precore-strategy-publication-owner-v190"

_FAST_PATH_INSTALLERS = (
    # The Render liveness server is a sibling process, so canonical runtime
    # state must be published through the existing atomic bridge.  The legacy
    # main.py fanout installs this bridge, but the canonical fast path skips
    # that fanout by design.
    ("render_readiness_state_bridge", "RENDER_READINESS_STATE_BRIDGE"),
    ("bot.writer_reelection_loss_reason_v46_patch", "WRITER_REELECTION_LOSS_REASON_V46"),
    ("bot.writer_generation_state_gate_v50_patch", "WRITER_GENERATION_STATE_GATE_V50"),
    ("bot.writer_distributed_loss_watchdog_v52_patch", "WRITER_DISTRIBUTED_LOSS_WATCHDOG_V52"),
    ("bot.writer_release_state_consistency_v53_patch", "WRITER_RELEASE_STATE_V53"),
    ("bot.writer_runtime_lifecycle_supervisor_v54_patch", "WRITER_RUNTIME_LIFECYCLE_V54"),
    ("bot.writer_recovery_callback_guard_v55_patch", "WRITER_RECOVERY_CALLBACK_V55"),
    ("bot.writer_runtime_core_thread_backstop_v56_patch", "WRITER_RUNTIME_CORE_THREAD_BACKSTOP_V56"),
    ("bot.writer_authority_generation_convergence_v57_patch", "WRITER_AUTHORITY_GENERATION_CONVERGENCE_V57"),
    ("bot.zero_signal_streak_cap_repair_v51_patch", "ZERO_SIGNAL_STREAK_CAP_V51"),
    ("bot.heartbeat_authority_single_source_patch", "HEARTBEAT_AUTHORITY_SINGLE_SOURCE"),
    ("bot.precore_authority_heartbeat_v63_patch", "PRECORE_AUTHORITY_HEARTBEAT_V63"),
    ("bot.canonical_self_healing_handoff_v124_patch", "CANONICAL_SELF_HEALING_HANDOFF_V124"),
    ("bot.activation_convergence_v17_patch", "ACTIVATION_CONVERGENCE_V17"),
    ("bot.activation_convergence_v17_importlib_bridge", "ACTIVATION_CONVERGENCE_V17_IMPORTLIB_BRIDGE"),
    ("bot.okx_patch_churn_guard_patch", "OKX_PATCH_CHURN_GUARD"),
    ("bot.disconnected_coinbase_balance_guard_patch", "COINBASE_BALANCE_DISCONNECTED_GUARD"),
    ("bot.live_capital_first_snapshot_latch_patch", "LIVE_CAPITAL_FIRST_SNAPSHOT_LATCH"),
    ("bot.startup_authority_prereq_repair_patch", "STARTUP_AUTHORITY_PREREQ_REPAIR"),
    ("bot.okx_execution_min_notional_lift_patch", "OKX_EXECUTION_MIN_NOTIONAL_LIFT"),
    ("bot.okx_order_instid_payload_repair_patch", "OKX_ORDER_INSTID_PAYLOAD_REPAIR"),
    ("bot.okx_final_order_submission_bridge_patch", "OKX_FINAL_ORDER_SUBMISSION_BRIDGE"),
    ("bot.stalled_writer_release_guard_v22", "STALLED_WRITER_RELEASE_GUARD_V22"),
    ("bot.capital_refresh_live_continuity_v78_patch", "CAPITAL_REFRESH_FRESHNESS_BOUNDED_V78"),
    ("bot.activation_capital_convergence_v62_patch", "ACTIVATION_CAPITAL_CONVERGENCE_V62"),
    ("bot.live_capital_freshness_v64_patch", "LIVE_CAPITAL_FRESHNESS_V64"),
    ("bot.production_freshness_scan_convergence_v93_patch", "PRODUCTION_FRESHNESS_SCAN_V93"),
    ("bot.position_sync_core_handoff_v95_patch", "POSITION_SYNC_CORE_HANDOFF_V95"),
    ("bot.position_sync_timeout_v98_patch", "POSITION_SYNC_TIMEOUT_V98"),
    ("bot.position_sync_dispatch_authority_v96_patch", "POSITION_SYNC_DISPATCH_AUTHORITY_V96"),
    ("bot.runtime_truth_convergence_v97_patch", "RUNTIME_TRUTH_CONVERGENCE_V97"),
    ("bot.trading_engine_strategy_wrapper_patch", "TRADING_ENGINE_STRATEGY_WRAPPER"),
    ("bot.trading_strategy_apex_wiring_patch", "TRADING_STRATEGY_APEX_WIRING"),
    ("bot.runtime_truth_convergence_v97_patch", "RUNTIME_TRUTH_CONVERGENCE_V97"),
    ("bot.position_sync_failure_truth_v98_patch", "POSITION_SYNC_FAILURE_TRUTH_V98"),
    ("bot.runtime_kraken_precore_liveness_v318_patch", "KRAKEN_PRECORE_LIVENESS_V318"),
    ("bot.strategy_runtime_integrity_patch", "STRATEGY_RUNTIME_INTEGRITY"),
    ("bot.final_production_activation_repair_v58_patch", "FINAL_PRODUCTION_ACTIVATION_V58"),
    ("bot.final_production_activation_repair_v61_patch", "FINAL_PRODUCTION_ACTIVATION_V61"),
    ("bot.final_production_activation_repair_v59_patch", "FINAL_PRODUCTION_ACTIVATION_V59"),
    ("bot.final_activation_v60_v16_compat_v113_patch", "FINAL_ACTIVATION_V60_V16_COMPAT_V113"),
    ("bot.final_production_activation_repair_v60_patch", "FINAL_PRODUCTION_ACTIVATION_V60"),
    ("bot.live_active_dispatch_commit_v92_patch", "LIVE_ACTIVE_DISPATCH_COMMIT_V92"),
    ("bot.canonical_core_import_handoff_v125_patch", "CANONICAL_CORE_IMPORT_HANDOFF_V125"),
    ("bot.canonical_strategy_fast_start_v126_patch", "CANONICAL_STRATEGY_FAST_START_V126"),
    ("bot.canonical_publication_direct_v127_patch", "CANONICAL_PUBLICATION_DIRECT_V127"),
    ("bot.seak_nonce_causality_v128_patch", "SEAK_NONCE_CAUSALITY_V128"),
    ("bot.authority_heartbeat_startup_grace_v129_patch", "AUTHORITY_HEARTBEAT_STARTUP_GRACE_V129"),
    ("bot.kill_switch_stale_heartbeat_recovery_v130_patch", "KILL_SWITCH_STALE_HEARTBEAT_RECOVERY_V130"),
    ("bot.readiness_killswitch_causality_v131_patch", "READINESS_KILLSWITCH_CAUSALITY_V131"),
)

_FAST_PATH_COMPAT_OPTIONAL_GUARDS = frozenset({
    "WRITER_REELECTION_LOSS_REASON_V46",
    "ACTIVATION_CONVERGENCE_V17_IMPORTLIB_BRIDGE",
})

_LEGACY_INSTALLERS = (
    *_FAST_PATH_INSTALLERS,
    ("bot.bootstrap_i12_capital_authority_repair_patch", "BOOTSTRAP_I12_CAPITAL_AUTHORITY_REPAIR"),
    ("bot.live_entry_scan_adoption_timeout_patch", "SCAN_POSITION_ADOPTION_TIMEOUT"),
    ("bot.writer_heartbeat_stale_repair_patch", "WRITER_HEARTBEAT_STALE_REPAIR"),
    ("bot.ecel_okx_synthetic_contract_patch", "ECEL_OKX_SYNTHETIC_CONTRACT"),
    ("bot.fallback_strict_score_floor_adaptive_patch", "FALLBACK_FLOOR_CALIBRATION"),
    ("bot.canonical_broker_main_entry_guard_v20", "CANONICAL_BROKER_MAIN_GUARD"),
    ("bot.canonical_broker_prebootstrap_v22", "CANONICAL_BROKER_PREBOOTSTRAP_V22"),
)


def _truthy(name: str) -> bool:
    return str(os.environ.get(name, "")).strip().lower() in {"1", "true", "yes", "on", "enabled", "y"}


def _canonical_fast_path_enabled() -> bool:
    return bool(_truthy("NIJA_CANONICAL_ENTRYPOINT_FAST_PATH") and _truthy("NIJA_DEFER_RUNTIME_SITE_HOOKS") and os.environ.get("NIJA_CANONICAL_RUNTIME_LAUNCHER_V26_READY") == "1")


def _canonical_fast_import(module_name: str):
    bootstrap = getattr(importlib, "_bootstrap", None)
    gcd_import = getattr(bootstrap, "_gcd_import", None) if bootstrap is not None else None
    if not callable(gcd_import):
        raise RuntimeError("canonical_import_primitive_unavailable")
    return gcd_import(module_name)


def _install_guards(specs: Iterable[tuple[str, str]], *, mode: str, optional_labels: frozenset[str] | None = None) -> bool:
    ready = True
    installed: list[str] = []
    optional_labels = optional_labels or frozenset()
    for module_name, label in specs:
        try:
            module = _canonical_fast_import(module_name) if mode == "canonical_fast" else importlib.import_module(module_name)
            installer = getattr(module, "install_import_hook", None) or getattr(module, "install", None)
            if not callable(installer):
                raise RuntimeError("installer_missing")
            result = installer()
            if result is False:
                raise RuntimeError("installer_returned_false")
            installed.append(label)
            logger.warning("%s_INSTALL_REQUESTED source=bot_entrypoint mode=%s", label, mode)
        except Exception as exc:
            if label in optional_labels:
                logger.warning("%s_INSTALL_SKIPPED_OPTIONAL source=bot_entrypoint mode=%s err=%s", label, mode, exc)
                continue
            ready = False
            logger.critical("%s_INSTALL_FAILED source=bot_entrypoint mode=%s err=%s", label, mode, exc, exc_info=True)
    logger.critical("BOT_ENTRYPOINT_GUARD_BUNDLE_COMPLETE marker=%s mode=%s ready=%s installed=%s", _FAST_PATH_MARKER, mode, ready, ",".join(installed) or "none")
    return ready


def _install_canonical_import_shield_v123() -> bool:
    try:
        module = _canonical_fast_import("bot.canonical_import_shield_v123_patch")
        installer = getattr(module, "install_import_hook", None) or getattr(module, "install", None)
        if not callable(installer) or installer() is False:
            raise RuntimeError("canonical import shield v123 installer unavailable or returned false")
        logger.critical("CANONICAL_IMPORT_SHIELD_V123_EARLY_READY source=bot_entrypoint before_fast_guard_bundle=true")
        return True
    except Exception as exc:
        logger.critical("CANONICAL_IMPORT_SHIELD_V123_EARLY_FAILED source=bot_entrypoint err=%s trading_fail_closed=true", exc, exc_info=True)
        return False


def _install_capital_v180_early(*, mode: str) -> bool:
    """Arm only v180's CapitalAuthority guard before bot_main can refresh capital.

    The full v180 installer also edits the release manifest, which belongs to the
    later post-import convergence chain. At the entrypoint we need only the
    idempotent CapitalAuthority.refresh wrapper so the first post-bootstrap
    private fallback cannot become a second capital writer.
    """
    try:
        module_name = "bot.runtime_capital_direct_refresh_downgrade_v180_patch"
        module = _canonical_fast_import(module_name) if mode == "canonical_fast" else importlib.import_module(module_name)
        patcher = getattr(module, "_patch_capital_authority", None)
        if not callable(patcher) or patcher() is False:
            raise RuntimeError("v180 capital authority patcher unavailable or returned false")
        logger.critical(
            "CAPITAL_V180_EARLY_ENTRYPOINT_READY source=bot_entrypoint mode=%s "
            "before_bot_main=true release_manifest_deferred=true "
            "freshness_extended=false safety_gates_unchanged=true",
            mode,
        )
        return True
    except Exception as exc:
        logger.critical(
            "CAPITAL_V180_EARLY_ENTRYPOINT_FAILED source=bot_entrypoint mode=%s "
            "err=%s trading_fail_closed=true",
            mode,
            exc,
            exc_info=True,
        )
        return False


def _install_precore_strategy_publication_owner_v190() -> bool:
    """Keep canonical Step 2.5 as the sole pre-core strategy publisher.

    The proof-based preactivation monitor normally starts the generic strategy
    publication monitor on every activation probe.  On the canonical fast path
    that creates a second publisher before bot_main reaches its direct v127
    Step 2.5 handoff.  Both publishers can contend on the same strategy
    construction locks and leave core registration waiting behind a publication
    timeout.  Defer only that background monitor until bot_main has completed
    startup; bot_main's real v127 publisher remains unchanged and all execution
    gates remain fail closed.
    """
    try:
        module = _canonical_fast_import("preactivation_readiness_convergence_v16_patch")
        current = getattr(module, "_ensure_strategy_publication_monitor", None)
        if not callable(current):
            raise RuntimeError("preactivation strategy monitor helper unavailable")
        patch_attr = "_nija_precore_strategy_publication_owner_v190"
        if bool(getattr(current, patch_attr, False)):
            return True

        def _owned_strategy_monitor_start():
            bot_main = sys.modules.get("bot.bot_main")
            startup_complete = bool(
                bot_main is not None and getattr(bot_main, "_startup_complete", False)
            )
            if not startup_complete:
                logger.info(
                    "PRECORE_STRATEGY_PUBLICATION_V190_DEFERRED marker=%s "
                    "owner=bot_main_step2_5 background_monitor_started=false "
                    "strategy_readiness_synthetic=false execution_authority_unchanged=true",
                    _PRECORE_STRATEGY_OWNER_MARKER,
                )
                return True, "deferred_to_bot_main_step2_5"
            return current()

        setattr(_owned_strategy_monitor_start, patch_attr, True)
        setattr(_owned_strategy_monitor_start, "__wrapped__", current)
        module._ensure_strategy_publication_monitor = _owned_strategy_monitor_start
        os.environ["NIJA_PRECORE_STRATEGY_PUBLICATION_OWNER_V190_READY"] = "1"
        logger.critical(
            "PRECORE_STRATEGY_PUBLICATION_OWNER_V190_READY marker=%s "
            "canonical_step2_5_single_owner=true background_precore_publisher=false "
            "v127_direct_publisher_unchanged=true forced_activation=false "
            "signal_thresholds_unchanged=true safety_gates_bypassed=false",
            _PRECORE_STRATEGY_OWNER_MARKER,
        )
        return True
    except Exception as exc:
        os.environ["NIJA_PRECORE_STRATEGY_PUBLICATION_OWNER_V190_READY"] = "0"
        logger.critical(
            "PRECORE_STRATEGY_PUBLICATION_OWNER_V190_FAILED marker=%s err=%s:%s "
            "trading_fail_closed=true",
            _PRECORE_STRATEGY_OWNER_MARKER,
            type(exc).__name__,
            exc,
            exc_info=True,
        )
        return False


def _fail_closed_startup(reason: str) -> None:
    os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] = "0"
    os.environ["NIJA_RUNTIME_TRADING_STATE"] = "OFF"
    raise RuntimeError(reason)


if _canonical_fast_path_enabled():
    if not _install_canonical_import_shield_v123():
        _fail_closed_startup("canonical import shield failed; trading remains fail closed")
    if not _install_capital_v180_early(mode="canonical_fast"):
        _fail_closed_startup("v180 early capital guard failed; trading remains fail closed")
    if not _install_precore_strategy_publication_owner_v190():
        _fail_closed_startup("v190 pre-core strategy publication owner guard failed; trading remains fail closed")
    if not _install_guards(_FAST_PATH_INSTALLERS, mode="canonical_fast", optional_labels=_FAST_PATH_COMPAT_OPTIONAL_GUARDS):
        _fail_closed_startup("canonical fast-path safety guards failed; trading remains fail closed")
    logger.critical(
        "CANONICAL_ENTRYPOINT_FAST_PATH_READY marker=%s import_loader=frozen_bootstrap "
        "package_hook_fanout=deferred import_shield_v123=true capital_v180_early=true "
        "precore_strategy_owner_v190=true handoff=bot.bot_main",
        _FAST_PATH_MARKER,
    )
else:
    logger.warning("BOT_ENTRYPOINT_LEGACY_COMPATIBILITY_PATH marker=%s canonical_fast_path=false", _FAST_PATH_MARKER)
    if not _install_capital_v180_early(mode="legacy_compatibility"):
        _fail_closed_startup("v180 early capital guard failed; trading remains fail closed")
    _install_guards(_LEGACY_INSTALLERS, mode="legacy_compatibility")

from bot.bot_main import main

if __name__ == "__main__":
    sys.exit(main())