"""Keep v203 install-time strategy discovery non-importing during pre-core startup.

Production deployment 22cde3c showed an 85 second startup stall between the
v190 pre-core publication deferral and v203's IMMEDIATE_SKIPPED result while the
canonical runtime was still generation 0 / BOOT_INIT.  v203's fallback called
strategy_publication_patch._existing(), whose helper may import a broad set of
runtime modules.  That is inappropriate inside the pre-core installer path: the
real canonical strategy belongs to bot_main Step 2.5 and v190 intentionally
keeps that path single-owner.

v207 narrows only v203's install-time *lookup*.  It can observe:
* the current publication module's existing _PUBLISHED pointer;
* strategy pointers already present in already-loaded modules/state dictionaries;
* v127's already-loaded cached publication closure via v203's existing helper.

It never imports modules merely to discover a strategy, never constructs or
publishes a strategy, never starts a second publisher, and never changes any
writer/nonce/risk/kill-switch/capital/position/order/fill or activation gate.
Future canonical Step 2.5 publication remains wrapped by v203 and therefore
re-arms the existing heartbeat scheduler normally after real publication.
"""
from __future__ import annotations

import logging
import os
import sys
import threading
from types import ModuleType
from typing import Any

LOGGER = logging.getLogger("nija.runtime_precore_strategy_lookup_v207")
MARKER = "20260824-precore-strategy-lookup-v207"
_READY_FLAG = "NIJA_PRECORE_STRATEGY_LOOKUP_V207_READY"
_PATCH_ATTR = "_nija_precore_strategy_lookup_v207"
_LOCK = threading.RLock()


def _valid_strategy(candidate: Any) -> bool:
    return bool(candidate is not None and callable(getattr(candidate, "run_cycle", None)))


def _loaded_strategy_pointer() -> Any:
    """Inspect only modules already resident in sys.modules; perform no imports."""
    seen: set[int] = set()
    for module_name in (
        "bot.bot_main",
        "bot.bot",
        "bot.trading_strategy",
        "trading_strategy",
        "__main__",
    ):
        module = sys.modules.get(module_name)
        if not isinstance(module, ModuleType) or id(module) in seen:
            continue
        seen.add(id(module))

        state = getattr(module, "_initialized_state", None)
        if isinstance(state, dict):
            for key in ("strategy", "trading_strategy"):
                candidate = state.get(key)
                if _valid_strategy(candidate):
                    return candidate

        for attr in ("nija_live_strategy", "trading_strategy", "strategy"):
            candidate = getattr(module, attr, None)
            if _valid_strategy(candidate):
                return candidate
    return None


def _nonblocking_existing_strategy(publication: Any, v203: Any) -> Any:
    """Return only an already-existing strategy without broad discovery imports."""
    strategy = getattr(publication, "_PUBLISHED", None)
    if _valid_strategy(strategy):
        return strategy

    strategy = _loaded_strategy_pointer()
    if _valid_strategy(strategy):
        LOGGER.info(
            "PRECORE_STRATEGY_LOOKUP_V207_LOADED_POINTER marker=%s "
            "existing_strategy=true strategy_replaced=false",
            MARKER,
        )
        return strategy

    cached = getattr(v203, "_strategy_from_cached_runtime_publisher", None)
    if callable(cached):
        try:
            strategy = cached()
        except Exception as exc:
            LOGGER.warning(
                "PRECORE_STRATEGY_LOOKUP_V207_CACHED_LOOKUP_FAILED marker=%s "
                "error=%s:%s action=defer_to_future_publication",
                MARKER,
                type(exc).__name__,
                exc,
            )
            return None
        if _valid_strategy(strategy):
            return strategy

    return None


def _patch_v203() -> bool:
    # v196 imports this companion before invoking v203.install(). Importing the
    # module object itself is safe; the broad finder is avoided by replacing the
    # lookup before v203 performs its immediate re-arm check.
    try:
        import bot.runtime_existing_strategy_heartbeat_rearm_v203_patch as v203
        import bot.strategy_publication_patch as publication
    except Exception as exc:
        LOGGER.critical(
            "PRECORE_STRATEGY_LOOKUP_V207_IMPORT_FAILED marker=%s error=%s:%s "
            "trading_fail_closed=true",
            MARKER,
            type(exc).__name__,
            exc,
        )
        return False

    current = getattr(v203, "_already_published_strategy", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True

    previous = current

    def _already_published_strategy_nonblocking(module: Any) -> Any:
        # Use the publication object supplied by v203 when available.  The
        # imported canonical object above is only a safe fallback and is already
        # loaded by v196/v203's normal install chain.
        target = module if module is not None else publication
        return _nonblocking_existing_strategy(target, v203)

    setattr(_already_published_strategy_nonblocking, _PATCH_ATTR, True)
    setattr(_already_published_strategy_nonblocking, "__wrapped__", previous)
    setattr(v203, "_nija_v207_previous_already_published_strategy", previous)
    v203._already_published_strategy = _already_published_strategy_nonblocking

    installed = getattr(v203, "_already_published_strategy", None)
    return bool(callable(installed) and getattr(installed, _PATCH_ATTR, False))


def install() -> bool:
    with _LOCK:
        ready = _patch_v203()
        os.environ[_READY_FLAG] = "1" if ready else "0"
        if not ready:
            LOGGER.critical(
                "PRECORE_STRATEGY_LOOKUP_V207_FAILED marker=%s trading_fail_closed=true",
                MARKER,
            )
            return False
        LOGGER.critical(
            "PRECORE_STRATEGY_LOOKUP_V207_READY marker=%s ready=true "
            "install_time_lookup_nonblocking=true broad_existing_scan=false "
            "already_loaded_pointers_only=true v127_cached_pointer_allowed=true "
            "step2_5_single_owner_preserved=true strategy_constructed=false "
            "strategy_published=false execution_authority_granted=false "
            "proof_fabricated=false forced_activation=false "
            "writer_nonce_risk_killswitch_capital_position_order_fill_gates_unchanged=true "
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
    "_valid_strategy",
    "_loaded_strategy_pointer",
    "_nonblocking_existing_strategy",
]
