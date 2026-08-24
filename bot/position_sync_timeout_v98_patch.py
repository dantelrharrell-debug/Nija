"""Tune startup position synchronization without weakening activation safety.

v98 raises the default broker-position fetch timeout to 12 seconds while
preserving an explicit ``NIJA_POSITION_FETCH_TIMEOUT_S`` override. Later repairs
are installed from this canonical slot in dependency order. v119 adds canonical
position-sync observation to preactivation truth. v120 preserves canonical
TradingLoop liveness while exact-writer supervised activation remains pending.
v121 bounds read-only Kraken HTTP calls, v122 requires that timeout layer before
v108 may dispatch a Kraken platform reconciliation worker, v123 keeps the
canonical fast path behind the process-wide import-chain compactor, and v124
bounds synchronous canonical strategy publication work before core startup.
v192 preserves a healthy supervised writer/core process while recoverable
post-core readiness remains pending instead of converting that wait into a
process restart; execution remains fail closed until v191's exact proof passes.
v194 defers v193 transactional kill-switch recovery until the canonical
kill-switch coordinator and v143 provenance chain are both ready, so v193 cannot
make the pre-core v98 umbrella fail before its dependencies exist.
v213 patches kill-switch file persistence before the deferred recovery chain is
armed so an existing EMERGENCY_STOP marker is never rewritten on restart.
"""
from __future__ import annotations

import logging
import os

LOGGER = logging.getLogger("nija.position_sync_timeout_v98")
MARKER = "20260815-position-sync-timeout-v98"
_DEFAULT_TIMEOUT_S = 12.0
_INSTALLED = False


def _timeout_s_v98() -> float:
    raw = os.environ.get("NIJA_POSITION_FETCH_TIMEOUT_S")
    if raw is None or not str(raw).strip():
        return _DEFAULT_TIMEOUT_S
    try:
        return max(0.1, float(raw))
    except (TypeError, ValueError):
        return _DEFAULT_TIMEOUT_S


def _install_module(name: str) -> bool:
    try:
        module = __import__(f"bot.{name}", fromlist=[name])
    except ImportError:
        module = __import__(name)
    installer = getattr(module, "install_import_hook", None) or getattr(module, "install", None)
    return callable(installer) and installer() is not False


def install() -> bool:
    global _INSTALLED
    try:
        from bot import position_sync_core_handoff_v95_patch as v95
    except ImportError:
        import position_sync_core_handoff_v95_patch as v95  # type: ignore[import]

    setattr(v95, "_timeout_s", _timeout_s_v98)
    ordered = [
        ("position_sync_account_isolation_v99_patch", "V99"),
        ("startup_publication_bootstrap_v105_patch", "V105"),
        ("capital_refresh_reentrancy_v106_patch", "V106"),
        ("startup_hook_nonce_v107_patch", "V107"),
        # Kraken's concrete read timeout must exist before v108 can dispatch the
        # first platform position worker. v122 then makes that ordering a hard
        # runtime prerequisite rather than relying on installer sequence alone.
        ("kraken_read_timeout_v121_patch", "V121"),
        ("kraken_position_sync_prereq_v122_patch", "V122"),
        ("platform_position_sync_v108_patch", "V108"),
        ("runtime_convergence_v116_patch", "V116"),
        ("position_fetch_generation_v117_patch", "V117"),
        # v192 extends the already-installed v117/v191 dispatch before bot_main
        # is imported. It adds no new global import hook and preserves the exact
        # execution proof while suppressing restart for healthy pending states.
        ("post_core_recoverable_pending_v192_patch", "V192"),
        # v213 must attach before deferred kill-switch recovery so every later
        # FILE_SYSTEM persistence check preserves the original marker bytes.
        # It never clears a stop or changes recovery eligibility.
        ("kill_switch_file_provenance_v213_patch", "V213"),
        # v193 depends on the later kill-switch coordinator/v143 chain. Arm a
        # non-blocking deferred installer here instead of importing v193 directly
        # in the pre-core v98 umbrella.
        ("kill_switch_transactional_recovery_v194_deferred_patch", "V194"),
        ("terminal_writer_loss_seak_v118_patch", "V118"),
        ("preactivation_position_sync_v119_patch", "V119"),
        ("core_supervised_pending_v120_patch", "V120"),
        ("canonical_import_shield_v123_patch", "V123"),
        # v124 must be installed before the canonical strategy import-cycle and
        # recovery layers can trigger synchronous TradingStrategy construction.
        ("canonical_strategy_startup_bound_v124_patch", "V124"),
        ("startup_strategy_import_cycle_v104_patch", "V104"),
        ("canonical_strategy_class_recovery_v100_patch", "V100"),
        ("canonical_strategy_class_recovery_v102_patch", "V102"),
        ("startup_convergence_v103_patch", "V103"),
    ]
    for module_name, label in ordered:
        if not _install_module(module_name):
            LOGGER.critical(
                "POSITION_SYNC_TIMEOUT_V98_%s_INSTALL_FAILED marker=%s trading_fail_closed=true",
                label,
                MARKER,
            )
            return False

    if _INSTALLED:
        return True
    os.environ["NIJA_POSITION_SYNC_TIMEOUT_V98_INSTALLED"] = "1"
    _INSTALLED = True
    LOGGER.critical(
        "POSITION_SYNC_TIMEOUT_V98_INSTALLED marker=%s default_timeout_s=%.1f explicit_env_override_preserved=true account_isolation_v99=true startup_publication_bootstrap_v105=true capital_refresh_reentrancy_v106=true startup_hook_nonce_v107=true kraken_read_timeout_v121=true kraken_position_sync_prereq_v122=true platform_position_sync_v108=true runtime_convergence_v116=true position_fetch_generation_v117=true post_core_recoverable_pending_v192=true kill_switch_file_provenance_v213=true kill_switch_transactional_recovery_v194_deferred=true terminal_writer_loss_seak_v118=true preactivation_position_sync_v119=true core_supervised_pending_v120=true canonical_import_shield_v123=true canonical_strategy_startup_bound_v124=true strategy_import_cycle_v104=true strategy_class_recovery_v100=true passive_strategy_recovery_v102=true startup_convergence_v103=true safety_gates_unchanged=true",
        MARKER,
        _DEFAULT_TIMEOUT_S,
    )
    return True


def install_import_hook() -> bool:
    return install()


__all__ = ["MARKER", "install", "install_import_hook", "_timeout_s_v98"]
