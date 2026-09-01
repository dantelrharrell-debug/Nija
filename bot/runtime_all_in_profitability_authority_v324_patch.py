"""Canonical NIJA profitability authority chain.

The verified v324 economics live in ``runtime_all_in_profitability_authority_v324_core``.
This canonical import path applies current U.S. public fee fallbacks and then
requires the proof-gated Kraken short path (v325), terminal short integrity
(v326), current-cost broker routing (v327), confirmed-fill/slippage truth
(v328), authoritative entry-fee/short-ledger bookkeeping (v329), capital
recycling / just-in-time exit proof (v330), canonical exit broker rebinding
(v331), JIT reconciliation-conflict recovery (v332), canonical public
market-price convergence for exits (v333), canonical protective-exit
submission through the explicit exit pipeline (v334), and protective-close
capability semantics (v335) in the same writer process.
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
    """Current conservative public fallback; authenticated account fees still win."""
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
            "CANONICAL_PROFITABILITY_CHAIN_READY marker=%s v324=true v325=true v326=true v327=true v328=true v329=true v330=true v331=true v332=true v333=true v334=true v335=true "
            "current_cost_economics=true current_us_fee_fallbacks=true short_margin_proof=true "
            "terminal_margin_integrity=true cost_aware_routing=true confirmed_fill_truth=true "
            "measured_slippage_learning=true unknown_slippage_not_zero=true authoritative_entry_fee=true "
            "authoritative_short_ledger_side=true capital_recycling_exit=true jit_exit_position_proof=true "
            "aged_profit_target_decay=true entry_free_cash_reserve=true canonical_exit_broker_rebinding=true "
            "jit_symbol_absence_reproof=true jit_quantity_conflict_reproof=true canonical_exit_market_price=true "
            "canonical_exit_pipeline_submission=true base_quantity_compilation=true empty_order_id_pending_blocked=true "
            "sell_to_close_not_short_entry=true ordinary_spot_short_gate_preserved=true "
            "spot_fallback=false confirmed_short_fill_required=true safety_gates_bypassed=false",
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
