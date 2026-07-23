"""Compatibility entrypoint for Railway/main.py."""

from __future__ import annotations

import logging
import sys

logger = logging.getLogger("nija.bot_entrypoint")

try:
    from bot.okx_patch_churn_guard_patch import install_import_hook as _install_okx_patch_churn_guard
    _install_okx_patch_churn_guard()
    logger.warning("OKX_PATCH_CHURN_GUARD_INSTALL_REQUESTED source=bot_entrypoint")
except Exception as exc:
    logger.warning("OKX_PATCH_CHURN_GUARD_INSTALL_FAILED source=bot_entrypoint err=%s", exc)

try:
    from bot.disconnected_coinbase_balance_guard_patch import install_import_hook as _install_coinbase_balance_guard
    _install_coinbase_balance_guard()
    logger.warning("COINBASE_BALANCE_DISCONNECTED_GUARD_INSTALL_REQUESTED source=bot_entrypoint")
except Exception as exc:
    logger.warning("COINBASE_BALANCE_DISCONNECTED_GUARD_INSTALL_FAILED source=bot_entrypoint err=%s", exc)

try:
    from bot.live_capital_first_snapshot_latch_patch import install_import_hook as _install_live_capital_first_snapshot_latch
    _install_live_capital_first_snapshot_latch()
    logger.warning("LIVE_CAPITAL_FIRST_SNAPSHOT_LATCH_INSTALL_REQUESTED source=bot_entrypoint")
except Exception as exc:
    logger.warning("LIVE_CAPITAL_FIRST_SNAPSHOT_LATCH_INSTALL_FAILED source=bot_entrypoint err=%s", exc)

try:
    from bot.startup_authority_prereq_repair_patch import install_import_hook as _install_startup_authority_repair
    _install_startup_authority_repair()
    logger.warning("STARTUP_AUTHORITY_PREREQ_REPAIR_INSTALL_REQUESTED source=bot_entrypoint")
except Exception as exc:
    logger.warning("STARTUP_AUTHORITY_PREREQ_REPAIR_INSTALL_FAILED source=bot_entrypoint err=%s", exc)

try:
    from bot.bootstrap_i12_capital_authority_repair_patch import install_import_hook as _install_bootstrap_i12_ca_repair
    _install_bootstrap_i12_ca_repair()
    logger.warning("BOOTSTRAP_I12_CAPITAL_AUTHORITY_REPAIR_INSTALL_REQUESTED source=bot_entrypoint")
except Exception as exc:
    logger.warning("BOOTSTRAP_I12_CAPITAL_AUTHORITY_REPAIR_FAILED source=bot_entrypoint err=%s", exc)

try:
    from bot.trading_engine_strategy_wrapper_patch import install_import_hook as _install_strategy_wrapper
    _install_strategy_wrapper()
    logger.warning("TRADING_ENGINE_STRATEGY_WRAPPER_INSTALL_REQUESTED source=bot_entrypoint")
except Exception as exc:
    logger.warning("TRADING_ENGINE_STRATEGY_WRAPPER_INSTALL_FAILED source=bot_entrypoint err=%s", exc)

try:
    from bot.strategy_runtime_integrity_patch import install_import_hook as _install_strategy_runtime_integrity
    _install_strategy_runtime_integrity()
    logger.warning("STRATEGY_RUNTIME_INTEGRITY_INSTALL_REQUESTED source=bot_entrypoint")
except Exception as exc:
    logger.warning("STRATEGY_RUNTIME_INTEGRITY_INSTALL_FAILED source=bot_entrypoint err=%s", exc)

try:
    from bot.live_entry_scan_adoption_timeout_patch import install_import_hook as _install_scan_adoption_timeout
    _install_scan_adoption_timeout()
    logger.warning("SCAN_POSITION_ADOPTION_TIMEOUT_INSTALL_REQUESTED source=bot_entrypoint")
except Exception as exc:
    logger.warning("SCAN_POSITION_ADOPTION_TIMEOUT_INSTALL_FAILED source=bot_entrypoint err=%s", exc)

try:
    from bot.writer_heartbeat_stale_repair_patch import install_import_hook as _install_writer_heartbeat_stale_repair
    _install_writer_heartbeat_stale_repair()
    logger.warning("WRITER_HEARTBEAT_STALE_REPAIR_INSTALL_REQUESTED source=bot_entrypoint")
except Exception as exc:
    logger.warning("WRITER_HEARTBEAT_STALE_REPAIR_FAILED source=bot_entrypoint err=%s", exc)

try:
    from bot.ecel_okx_synthetic_contract_patch import install_import_hook as _install_ecel_okx_contract_repair
    _install_ecel_okx_contract_repair()
    logger.warning("ECEL_OKX_SYNTHETIC_CONTRACT_INSTALL_REQUESTED source=bot_entrypoint")
except Exception as exc:
    logger.warning("ECEL_OKX_SYNTHETIC_CONTRACT_INSTALL_FAILED source=bot_entrypoint err=%s", exc)

try:
    from bot.fallback_strict_score_floor_adaptive_patch import install_import_hook as _install_fallback_floor_calibration
    _install_fallback_floor_calibration()
    logger.warning("FALLBACK_FLOOR_CALIBRATION_INSTALL_REQUESTED source=bot_entrypoint")
except Exception as exc:
    logger.warning("FALLBACK_FLOOR_CALIBRATION_FAILED source=bot_entrypoint err=%s", exc)

try:
    from bot.okx_execution_min_notional_lift_patch import install_import_hook as _install_okx_execution_min_lift
    _install_okx_execution_min_lift()
    logger.warning("OKX_EXECUTION_MIN_NOTIONAL_LIFT_INSTALL_REQUESTED source=bot_entrypoint")
except Exception as exc:
    logger.warning("OKX_EXECUTION_MIN_NOTIONAL_LIFT_FAILED source=bot_entrypoint err=%s", exc)

try:
    from bot.okx_order_instid_payload_repair_patch import install_import_hook as _install_okx_order_instid_payload_repair
    _install_okx_order_instid_payload_repair()
    logger.warning("OKX_ORDER_INSTID_PAYLOAD_REPAIR_INSTALL_REQUESTED source=bot_entrypoint")
except Exception as exc:
    logger.warning("OKX_ORDER_INSTID_PAYLOAD_REPAIR_INSTALL_FAILED source=bot_entrypoint err=%s", exc)

try:
    from bot.okx_final_order_submission_bridge_patch import install_import_hook as _install_okx_final_order_submission_bridge
    _install_okx_final_order_submission_bridge()
    logger.warning("OKX_FINAL_ORDER_SUBMISSION_BRIDGE_INSTALL_REQUESTED source=bot_entrypoint")
except Exception as exc:
    logger.warning("OKX_FINAL_ORDER_SUBMISSION_BRIDGE_INSTALL_FAILED source=bot_entrypoint err=%s", exc)

try:
    from bot.canonical_broker_main_entry_guard_v20 import install_import_hook as _install_canonical_broker_main_guard
    _install_canonical_broker_main_guard()
    logger.warning("CANONICAL_BROKER_MAIN_GUARD_INSTALL_REQUESTED source=bot_entrypoint")
except Exception as exc:
    logger.warning("CANONICAL_BROKER_MAIN_GUARD_INSTALL_FAILED source=bot_entrypoint err=%s", exc)

try:
    from bot.stalled_writer_release_guard_v21 import install_import_hook as _install_stalled_writer_release_guard
    _install_stalled_writer_release_guard()
    logger.warning("STALLED_WRITER_RELEASE_GUARD_INSTALL_REQUESTED source=bot_entrypoint")
except Exception as exc:
    logger.warning("STALLED_WRITER_RELEASE_GUARD_INSTALL_FAILED source=bot_entrypoint err=%s", exc)

from bot.bot_main import main

if __name__ == "__main__":
    sys.exit(main())
