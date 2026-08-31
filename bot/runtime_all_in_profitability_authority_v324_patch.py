"""Canonical NIJA profitability authority chain.

The verified v324 economics live in ``runtime_all_in_profitability_authority_v324_core``.
This canonical import path applies current U.S. public fee fallbacks and then
requires the proof-gated Kraken short path (v325), terminal short integrity
(v326), current-cost broker routing (v327), confirmed-fill/slippage truth
(v328), and authoritative entry-fee/short-ledger bookkeeping (v329) in the same
writer process.
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
        # Public Coinbase Advanced base tier: 40 bps maker / 60 bps taker.
        return 0.0040, 0.0060, "coinbase_advanced_public_base_20260831"
    if broker == "okx" and not derivative:
        # OKX United States regular tier: 20 bps maker / 35 bps taker.
        return 0.0020, 0.0035, "okx_us_regular_2026"
    return _ORIGINAL_BASE_FEES(broker_name, symbol)


# Core v324 functions resolve this global dynamically. Patch it before the
# installer updates legacy fee profiles, risk sizing, entry, and exit economics.
_core._current_base_fees = _current_base_fees


def _install_required(module_name: str, ready_env: str) -> bool:
    module = importlib.import_module(module_name)
    installer = getattr(module, "install_import_hook", None) or getattr(module, "install", None)
    if not callable(installer) or installer() is False:
        return False
    return os.environ.get(ready_env) == "1"


def install_import_hook() -> bool:
    core_ready = bool(_core.install_import_hook())
    v325_ready = False
    v326_ready = False
    v327_ready = False
    v328_ready = False
    v329_ready = False
    if core_ready:
        try:
            v325_ready = _install_required(
                "bot.runtime_kraken_short_margin_profit_v325_patch",
                "NIJA_RUNTIME_KRAKEN_SHORT_MARGIN_PROFIT_V325_READY",
            )
        except Exception:
            LOGGER.exception("PROFITABILITY_CHAIN_V324_V325_FAILED marker=%s", MARKER)
    if core_ready and v325_ready:
        try:
            v326_ready = _install_required(
                "bot.runtime_kraken_short_terminal_integrity_v326_patch",
                "NIJA_RUNTIME_KRAKEN_SHORT_TERMINAL_V326_READY",
            )
        except Exception:
            LOGGER.exception("PROFITABILITY_CHAIN_V324_V326_FAILED marker=%s", MARKER)
    if core_ready and v325_ready and v326_ready:
        try:
            v327_ready = _install_required(
                "bot.runtime_execution_cost_routing_v327_patch",
                "NIJA_RUNTIME_EXECUTION_COST_ROUTING_V327_READY",
            )
        except Exception:
            LOGGER.exception("PROFITABILITY_CHAIN_V324_V327_FAILED marker=%s", MARKER)
    if core_ready and v325_ready and v326_ready and v327_ready:
        try:
            v328_ready = _install_required(
                "bot.runtime_confirmed_fill_profitability_v328_patch",
                "NIJA_RUNTIME_CONFIRMED_FILL_PROFITABILITY_V328_READY",
            )
        except Exception:
            LOGGER.exception("PROFITABILITY_CHAIN_V324_V328_FAILED marker=%s", MARKER)
    if core_ready and v325_ready and v326_ready and v327_ready and v328_ready:
        try:
            v329_ready = _install_required(
                "bot.runtime_authoritative_fee_ledger_v329_patch",
                "NIJA_RUNTIME_AUTHORITATIVE_FEE_LEDGER_V329_READY",
            )
        except Exception:
            LOGGER.exception("PROFITABILITY_CHAIN_V324_V329_FAILED marker=%s", MARKER)

    ready = bool(
        core_ready and v325_ready and v326_ready and v327_ready and v328_ready and v329_ready
    )
    os.environ["NIJA_RUNTIME_ALL_IN_PROFITABILITY_V324_READY"] = "1" if ready else "0"
    os.environ["NIJA_CANONICAL_PROFITABILITY_CHAIN_READY"] = "1" if ready else "0"
    if ready:
        LOGGER.critical(
            "CANONICAL_PROFITABILITY_CHAIN_READY marker=%s v324=true v325=true v326=true v327=true v328=true v329=true "
            "current_cost_economics=true current_us_fee_fallbacks=true short_margin_proof=true "
            "terminal_margin_integrity=true cost_aware_routing=true confirmed_fill_truth=true "
            "measured_slippage_learning=true unknown_slippage_not_zero=true authoritative_entry_fee=true "
            "authoritative_short_ledger_side=true spot_fallback=false confirmed_short_fill_required=true "
            "safety_gates_bypassed=false",
            MARKER,
        )
    else:
        LOGGER.critical(
            "CANONICAL_PROFITABILITY_CHAIN_INCOMPLETE marker=%s v324=%s v325=%s v326=%s v327=%s v328=%s v329=%s fail_closed=true",
            MARKER, core_ready, v325_ready, v326_ready, v327_ready, v328_ready, v329_ready,
        )
    return ready


def install() -> bool:
    return install_import_hook()


# Preserve the original public surface plus corrected fee lookup and installers.
__all__ = list(getattr(_core, "__all__", ()))
for _name in ("MARKER", "install", "install_import_hook", "_current_base_fees"):
    if _name not in __all__:
        __all__.append(_name)
