"""Canonical profitability authority chain.

This wrapper preserves the verified v324 economic implementation in
``runtime_all_in_profitability_authority_v324_core`` and makes the existing
canonical v324 startup attestation require the proof-gated Kraken short path
(v325) and terminal no-spot-fallback integrity (v326) in the same process.
"""
from __future__ import annotations

import importlib
import logging
import os

from bot.runtime_all_in_profitability_authority_v324_core import *  # noqa: F401,F403
from bot import runtime_all_in_profitability_authority_v324_core as _core

LOGGER = logging.getLogger("nija.runtime_all_in_profitability_authority_v324_chain")
MARKER = _core.MARKER


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

    ready = bool(core_ready and v325_ready and v326_ready)
    os.environ["NIJA_RUNTIME_ALL_IN_PROFITABILITY_V324_READY"] = "1" if ready else "0"
    os.environ["NIJA_CANONICAL_PROFITABILITY_CHAIN_READY"] = "1" if ready else "0"
    if ready:
        LOGGER.critical(
            "CANONICAL_PROFITABILITY_CHAIN_READY marker=%s v324=true v325=true v326=true "
            "current_cost_economics=true short_margin_proof=true terminal_margin_integrity=true "
            "spot_fallback=false confirmed_short_fill_required=true safety_gates_bypassed=false",
            MARKER,
        )
    else:
        LOGGER.critical(
            "CANONICAL_PROFITABILITY_CHAIN_INCOMPLETE marker=%s v324=%s v325=%s v326=%s fail_closed=true",
            MARKER, core_ready, v325_ready, v326_ready,
        )
    return ready


def install() -> bool:
    return install_import_hook()


# Preserve the original public surface plus the chained installers.
__all__ = list(getattr(_core, "__all__", ()))
for _name in ("MARKER", "install", "install_import_hook"):
    if _name not in __all__:
        __all__.append(_name)
