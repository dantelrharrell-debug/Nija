"""Canonical NIJA profitability authority chain.

The verified v324 economics live in ``runtime_all_in_profitability_authority_v324_core``.
This canonical import path applies current U.S. public fee fallbacks and requires
all execution/profitability hardening through v354 in the same writer process.
"""
from __future__ import annotations

import importlib
import logging
import os

from bot.runtime_all_in_profitability_authority_v324_core import *  # noqa: F401,F403
from bot import runtime_all_in_profitability_authority_v324_core as _core

LOGGER = logging.getLogger("nija.runtime_all_in_profitability_authority_v324_chain")
MARKER = _core.MARKER
_ORIGINAL_BASE_FEES = _core._current_base_fees


def _current_base_fees(broker_name: str, symbol: str):
    broker = str(broker_name or "").strip().lower().replace(" ", "_")
    upper_symbol = str(symbol or "").strip().upper()
    derivative = any(token in upper_symbol for token in ("PERP", "FUT", "SWAP"))
    if broker == "coinbase" and not derivative:
        return 0.0040, 0.0060, "coinbase_advanced_public_base_20260831"
    if broker == "okx" and not derivative:
        return 0.0020, 0.0035, "okx_us_regular_2026"
    return _ORIGINAL_BASE_FEES(broker_name, symbol)


_core._current_base_fees = _current_base_fees


def _install_required(module_name: str, ready_env: str) -> bool:
    module = importlib.import_module(module_name)
    installer = getattr(module, "install_import_hook", None) or getattr(module, "install", None)
    if not callable(installer) or installer() is False:
        return False
    return os.environ.get(ready_env) == "1"


def install_import_hook() -> bool:
    core_ready = bool(_core.install_import_hook())
    stages = (
        ("v325", "bot.runtime_kraken_short_margin_profit_v325_patch", "NIJA_RUNTIME_KRAKEN_SHORT_MARGIN_PROFIT_V325_READY"),
        ("v326", "bot.runtime_kraken_short_terminal_integrity_v326_patch", "NIJA_RUNTIME_KRAKEN_SHORT_TERMINAL_V326_READY"),
        ("v327", "bot.runtime_execution_cost_routing_v327_patch", "NIJA_RUNTIME_EXECUTION_COST_ROUTING_V327_READY"),
        ("v328", "bot.runtime_confirmed_fill_profitability_v328_patch", "NIJA_RUNTIME_CONFIRMED_FILL_PROFITABILITY_V328_READY"),
        ("v329", "bot.runtime_authoritative_fee_ledger_v329_patch", "NIJA_RUNTIME_AUTHORITATIVE_FEE_LEDGER_V329_READY"),
        ("v330", "bot.runtime_capital_recycling_exit_v330_patch", "NIJA_RUNTIME_CAPITAL_RECYCLING_EXIT_V330_READY"),
        ("v331", "bot.runtime_universal_exit_broker_rebinding_v331_patch", "NIJA_RUNTIME_UNIVERSAL_EXIT_BROKER_REBINDING_V331_READY"),
        ("v332", "bot.runtime_exit_jit_conflict_recovery_v332_patch", "NIJA_RUNTIME_EXIT_JIT_CONFLICT_RECOVERY_V332_READY"),
        ("v333", "bot.runtime_exit_market_price_convergence_v333_patch", "NIJA_RUNTIME_EXIT_MARKET_PRICE_CONVERGENCE_V333_READY"),
        ("v334", "bot.runtime_canonical_exit_submission_v334_patch", "NIJA_RUNTIME_CANONICAL_EXIT_SUBMISSION_V334_READY"),
        ("v335", "bot.runtime_exit_capability_semantics_v335_patch", "NIJA_RUNTIME_EXIT_CAPABILITY_SEMANTICS_V335_READY"),
        ("v336", "bot.runtime_exit_submission_failure_truth_v336_patch", "NIJA_RUNTIME_EXIT_SUBMISSION_FAILURE_TRUTH_V336_READY"),
        ("v337", "bot.runtime_protective_exit_authority_bridge_v337_patch", "NIJA_RUNTIME_PROTECTIVE_EXIT_AUTHORITY_BRIDGE_V337_READY"),
        ("v338", "bot.runtime_exit_pipeline_late_binding_v338_patch", "NIJA_RUNTIME_EXIT_PIPELINE_LATE_BINDING_V338_READY"),
        ("v339", "bot.runtime_protective_exit_broker_health_v339_patch", "NIJA_RUNTIME_PROTECTIVE_EXIT_BROKER_HEALTH_V339_READY"),
        ("v340", "bot.runtime_protective_exit_state_machine_bridge_v340_patch", "NIJA_RUNTIME_PROTECTIVE_EXIT_STATE_MACHINE_BRIDGE_V340_READY"),
        ("v341", "bot.runtime_protective_exit_base_quantity_v341_patch", "NIJA_RUNTIME_PROTECTIVE_EXIT_BASE_QUANTITY_V341_READY"),
        ("v342", "bot.runtime_execution_terminal_recovery_v342_patch", "NIJA_RUNTIME_EXECUTION_TERMINAL_RECOVERY_V342_READY"),
        ("v343", "bot.runtime_exit_quantity_safety_v343_patch", "NIJA_RUNTIME_EXIT_QUANTITY_SAFETY_V343_READY"),
        ("v344", "bot.runtime_coinbase_exit_recovery_v344_patch", "NIJA_RUNTIME_COINBASE_EXIT_RECOVERY_V344_READY"),
        ("v345", "bot.runtime_coinbase_fill_truth_v345_patch", "NIJA_RUNTIME_COINBASE_FILL_TRUTH_V345_READY"),
        ("v346", "bot.runtime_execution_position_readiness_v346_patch", "NIJA_RUNTIME_EXECUTION_POSITION_READINESS_V346_READY"),
        ("v347", "bot.runtime_execution_activation_protection_v347_patch", "NIJA_RUNTIME_EXECUTION_ACTIVATION_PROTECTION_V347_READY"),
        ("v348", "bot.runtime_position_protection_liveness_v348_patch", "NIJA_RUNTIME_POSITION_PROTECTION_LIVENESS_V348_READY"),
        ("v349", "bot.runtime_terminal_exit_heartbeat_truth_v349_patch", "NIJA_RUNTIME_TERMINAL_EXIT_HEARTBEAT_TRUTH_V349_READY"),
        ("v350", "bot.runtime_terminal_exit_alias_quality_v350_patch", "NIJA_RUNTIME_TERMINAL_EXIT_ALIAS_QUALITY_V350_READY"),
        ("v351", "bot.runtime_heartbeat_verification_truth_v351_patch", "NIJA_RUNTIME_HEARTBEAT_VERIFICATION_TRUTH_V351_READY"),
        ("v352", "bot.runtime_kraken_btnl_reduce_only_v352_patch", "NIJA_RUNTIME_KRAKEN_BTNL_REDUCE_ONLY_V352_READY"),
        ("v353", "bot.runtime_kraken_btnl_leveraged_v353_patch", "NIJA_RUNTIME_KRAKEN_BTNL_LEVERAGED_V353_READY"),
        ("v354", "bot.runtime_kraken_margin_exit_authority_v354_patch", "NIJA_RUNTIME_KRAKEN_MARGIN_EXIT_AUTHORITY_V354_READY"),
    )
    outcomes = {}
    previous = core_ready
    for label, module_name, ready_env in stages:
        result = False
        if previous:
            try:
                result = _install_required(module_name, ready_env)
            except Exception:
                LOGGER.exception("PROFITABILITY_CHAIN_V324_%s_FAILED marker=%s", label.upper(), MARKER)
        outcomes[label] = bool(result)
        previous = bool(previous and result)

    ready = bool(core_ready and all(outcomes.values()))
    os.environ["NIJA_RUNTIME_ALL_IN_PROFITABILITY_V324_READY"] = "1" if ready else "0"
    os.environ["NIJA_CANONICAL_PROFITABILITY_CHAIN_READY"] = "1" if ready else "0"
    if ready:
        LOGGER.critical(
            "CANONICAL_PROFITABILITY_CHAIN_READY marker=%s "
            "v324=true v325=true v326=true v327=true v328=true v329=true v330=true v331=true "
            "v332=true v333=true v334=true v335=true v336=true v337=true v338=true v339=true "
            "v340=true v341=true v342=true v343=true v344=true v345=true v346=true v347=true v348=true v349=true v350=true v351=true v352=true v353=true v354=true "
            "confirmed_fill_truth=true measured_slippage_learning=true authoritative_entry_fee=true "
            "capital_recycling_exit=true canonical_exit_broker_rebinding=true canonical_exit_market_price=true "
            "canonical_exit_pipeline_submission=true rejected_submission_not_fill=true "
            "protective_exit_startup_authority_bridge=true exact_writer_nonce_health_required=true "
            "protective_exit_state_machine_bridge=true protective_exit_base_quantity_terminal=true "
            "oversell_guard=true verified_position_caps_exit=true post_ecel_holdings_firewall=true "
            "all_pipeline_identities_firewalled=true protective_exit_quality_optimizer_scoped=true "
            "below_min_exit_deferred=true ambiguous_typeerror_retry=false "
            "coinbase_missing_increment_repaired=true deterministic_exit_rejects_not_exchange_health=true "
            "nested_coinbase_order_id=true coinbase_read_only_fill_reconciliation=true ack_alone_not_fill=true "
            "canonical_confirmed_fill_execution_proof=true stale_platform_snapshot_authoritative_refresh=true "
            "confirmed_fill_immediate_activation_wakeup=true terminal_v108_stale_snapshot_dispatch=true "
            "heartbeat_local_deferral_not_exchange_rejection=true heartbeat_ack_timeout_not_exchange_rejection=true "
            "heartbeat_stage_helpers_terminal_reasserted=true kraken_btnl_non_ecp_retry=true "
            "kraken_btnl_all_leveraged_non_ecp_retry=true pending_open_not_margin_exit_authority=true "
            "explicit_other_exchange_rejections_unchanged=true "
            "take_profit_preserved=true stop_loss_preserved=true trailing_take_profit_preserved=true "
            "trailing_stop_preserved=true auto_exit_reconciler_preserved=true dust_policy_unchanged=true "
            "snapshot_ttl_unchanged=true stale_promoted=false forced_trade=false forced_activation=false "
            "execution_proof_fabricated=false safety_gates_bypassed=false",
            MARKER,
        )
    else:
        LOGGER.critical(
            "CANONICAL_PROFITABILITY_CHAIN_INCOMPLETE marker=%s core=%s outcomes=%s fail_closed=true",
            MARKER, core_ready, outcomes,
        )
    return ready


def install() -> bool:
    return install_import_hook()


__all__ = list(getattr(_core, "__all__", ()))
for _name in ("MARKER", "install", "install_import_hook", "_current_base_fees"):
    if _name not in __all__:
        __all__.append(_name)
