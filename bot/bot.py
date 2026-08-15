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
_FAST_PATH_MARKER = "20260815-canonical-fast-entrypoint-v65"

_FAST_PATH_INSTALLERS = (
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
    # The writer heartbeat truthfully publishes CORE_THREAD_ALIVE=0 before the
    # real core is launched. Keep the independent authority heartbeat aligned
    # with that documented startup grace while preserving post-core fail-closed
    # liveness checks.
    ("bot.precore_authority_heartbeat_v63_patch", "PRECORE_AUTHORITY_HEARTBEAT_V63"),
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
    # Keep synchronous capital publication inside the canonical freshness TTL.
    # Slow venue workers continue asynchronously and can contribute on a later
    # refresh once their observations are still fresh.
    ("bot.capital_refresh_live_continuity_v78_patch", "CAPITAL_REFRESH_FRESHNESS_BOUNDED_V78"),
    # Synchronize canonical bootstrap/capital/readiness state before any
    # compatibility activation proof is evaluated. This is state convergence,
    # not a bypass; all writer/nonce/risk/kill-switch gates remain authoritative.
    ("bot.activation_capital_convergence_v62_patch", "ACTIVATION_CAPITAL_CONVERGENCE_V62"),
    # Keep every post-activation observer and new-risk dispatch path on the same
    # canonical CapitalAuthority freshness contract. Protective reduce/exit
    # intents remain available when freshness is lost.
    ("bot.live_capital_freshness_v64_patch", "LIVE_CAPITAL_FRESHNESS_V64"),
    # Close the remaining production liveness gaps without weakening execution:
    # bound watchdog-driven refresh completion inside freshness, bridge v64
    # across importlib, expose publication expiry dynamically, and reclaim scan
    # ownership only when the recorded owner thread is actually gone.
    ("bot.production_freshness_scan_convergence_v93_patch", "PRODUCTION_FRESHNESS_SCAN_V93"),
    # Bound startup position snapshots so a slow venue cannot hold the main
    # startup thread indefinitely. v95 also makes position-sync completion a
    # fail-closed activation prerequisite rather than pre-latching success.
    ("bot.position_sync_core_handoff_v95_patch", "POSITION_SYNC_CORE_HANDOFF_V95"),
    # Publish position-sync truth into canonical readiness so an unsynced
    # connected broker also revokes any stale coordinator dispatch commit.
    ("bot.position_sync_dispatch_authority_v96_patch", "POSITION_SYNC_DISPATCH_AUTHORITY_V96"),
    # The production core invokes TradingStrategy directly. These three guards
    # must be present on the canonical fast path, not only the legacy path:
    # wrapper creates the runtime, APEX wiring repairs missing backrefs, and
    # integrity refuses to publish an incomplete live strategy.
    ("bot.trading_engine_strategy_wrapper_patch", "TRADING_ENGINE_STRATEGY_WRAPPER"),
    ("bot.trading_strategy_apex_wiring_patch", "TRADING_STRATEGY_APEX_WIRING"),
    ("bot.strategy_runtime_integrity_patch", "STRATEGY_RUNTIME_INTEGRITY"),
    ("bot.final_production_activation_repair_v58_patch", "FINAL_PRODUCTION_ACTIVATION_V58"),
    # v61 must install before v59/v60 start their reconciliation/activation
    # monitors. It guards v60's request boundary and makes v16 readiness reflect
    # current proof truth before any activation attempt is permitted.
    ("bot.final_production_activation_repair_v61_patch", "FINAL_PRODUCTION_ACTIVATION_V61"),
    ("bot.final_production_activation_repair_v59_patch", "FINAL_PRODUCTION_ACTIVATION_V59"),
    ("bot.final_production_activation_repair_v60_patch", "FINAL_PRODUCTION_ACTIVATION_V60"),
    # A local LIVE_ACTIVE state is not sufficient for broker order dispatch.
    # Require the canonical StartupCoordinator dispatch commit as well; v92
    # repairs only that commit after the existing readiness proof passes.
    ("bot.live_active_dispatch_commit_v92_patch", "LIVE_ACTIVE_DISPATCH_COMMIT_V92"),
)

_FAST_PATH_COMPAT_OPTIONAL_GUARDS = frozenset(
    {
        "WRITER_REELECTION_LOSS_REASON_V46",
        "ACTIVATION_CONVERGENCE_V17_IMPORTLIB_BRIDGE",
    }
)

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
    return str(os.environ.get(name, "")).strip().lower() in {
        "1", "true", "yes", "on", "enabled", "y",
    }


def _canonical_fast_path_enabled() -> bool:
    return bool(
        _truthy("NIJA_CANONICAL_ENTRYPOINT_FAST_PATH")
        and _truthy("NIJA_DEFER_RUNTIME_SITE_HOOKS")
        and os.environ.get("NIJA_CANONICAL_RUNTIME_LAUNCHER_V26_READY") == "1"
    )


def _install_guards(
    specs: Iterable[tuple[str, str]],
    *,
    mode: str,
    optional_labels: frozenset[str] | None = None,
) -> bool:
    ready = True
    installed: list[str] = []
    optional_labels = optional_labels or frozenset()
    for module_name, label in specs:
        try:
            module = importlib.import_module(module_name)
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
                logger.warning(
                    "%s_INSTALL_SKIPPED_OPTIONAL source=bot_entrypoint mode=%s err=%s",
                    label, mode, exc,
                )
                continue
            ready = False
            logger.critical(
                "%s_INSTALL_FAILED source=bot_entrypoint mode=%s err=%s", label, mode, exc, exc_info=True,
            )
    logger.critical(
        "BOT_ENTRYPOINT_GUARD_BUNDLE_COMPLETE marker=%s mode=%s ready=%s installed=%s",
        _FAST_PATH_MARKER, mode, ready, ",".join(installed) or "none",
    )
    return ready


if _canonical_fast_path_enabled():
    if not _install_guards(
        _FAST_PATH_INSTALLERS,
        mode="canonical_fast",
        optional_labels=_FAST_PATH_COMPAT_OPTIONAL_GUARDS,
    ):
        os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] = "0"
        os.environ["NIJA_RUNTIME_TRADING_STATE"] = "OFF"
        raise RuntimeError("canonical fast-path safety guards failed; trading remains fail closed")
    logger.critical(
        "CANONICAL_ENTRYPOINT_FAST_PATH_READY marker=%s package_hook_fanout=deferred handoff=bot.bot_main",
        _FAST_PATH_MARKER,
    )
else:
    logger.warning(
        "BOT_ENTRYPOINT_LEGACY_COMPATIBILITY_PATH marker=%s canonical_fast_path=false",
        _FAST_PATH_MARKER,
    )
    _install_guards(_LEGACY_INSTALLERS, mode="legacy_compatibility")

from bot.bot_main import main

if __name__ == "__main__":
    sys.exit(main())
