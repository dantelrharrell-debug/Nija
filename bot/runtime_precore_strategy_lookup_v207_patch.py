"""Keep pre-core strategy discovery and construction nonblocking.

Production deployment 22cde3c showed an 85 second startup stall between the
v190 pre-core publication deferral and v203's IMMEDIATE_SKIPPED result while the
canonical runtime was still generation 0 / BOOT_INIT. v207 originally narrowed
v203's install-time lookup so it observes only already-loaded strategy pointers.

Production deployment b02a2238 later exposed the next pre-core liveness edge:
TradingStrategy construction can synchronously perform broker market discovery
before bot_main can start and register the canonical core thread. v269 bounds
that read-only discovery. This module chains v269 at the narrowest safe point:
after the TradingStrategy class has already loaded and immediately before the
canonical builder invokes its constructor. That avoids a new early import fanout
while guaranteeing the constructor cannot enter unbounded market discovery.

The production bot.py path also imports the same source as top-level
``trading_strategy`` and constructs that class directly.  v271 closes that alias
race with a narrow import loader: after the top-level module executes, but before
``from trading_strategy import TradingStrategy`` returns to bot.py, v269 is
applied to every loaded strategy alias.  The loader performs no strategy
construction and grants no runtime authority.

Neither repair constructs or publishes a strategy during install, starts a
second publisher, grants execution authority, nor changes writer/nonce/risk/
kill-switch/capital/position/order/fill or activation gates.
"""
from __future__ import annotations

import importlib
import importlib.abc
import importlib.machinery
import logging
import os
import sys
import threading
from functools import wraps
from types import ModuleType
from typing import Any

LOGGER = logging.getLogger("nija.runtime_precore_strategy_lookup_v207")
MARKER = "20260824-precore-strategy-lookup-v207"
_READY_FLAG = "NIJA_PRECORE_STRATEGY_LOOKUP_V207_READY"
_PATCH_ATTR = "_nija_precore_strategy_lookup_v207"
_BUILD_PATCH_ATTR = "_nija_precore_strategy_builder_v269"
_ALIAS_LOADER_ATTR = "_nija_precore_strategy_alias_loader_v271"
_LOCK = threading.RLock()
_ALIAS_FINDER: Any = None


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
        # Use the publication object supplied by v203 when available. The
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


def _patch_loaded_strategy_aliases() -> bool:
    """Apply v269 to any TradingStrategy modules already resident in memory."""
    try:
        from bot.runtime_precore_symbol_discovery_liveness_v269_patch import (
            _patch_trading_strategy as patch_v269,
        )
    except Exception as exc:
        LOGGER.warning(
            "PRECORE_STRATEGY_ALIAS_V271_V269_IMPORT_FAILED marker=%s error=%s:%s",
            MARKER,
            type(exc).__name__,
            exc,
        )
        return False
    try:
        return bool(patch_v269())
    except Exception as exc:
        LOGGER.warning(
            "PRECORE_STRATEGY_ALIAS_V271_PATCH_FAILED marker=%s error=%s:%s",
            MARKER,
            type(exc).__name__,
            exc,
        )
        return False


class _TradingStrategyAliasLoader(importlib.abc.Loader):
    """Delegate module execution, then patch the loaded top-level strategy alias."""

    def __init__(self, wrapped: Any) -> None:
        self._wrapped = wrapped
        setattr(self, _ALIAS_LOADER_ATTR, True)

    def create_module(self, spec: Any) -> Any:
        creator = getattr(self._wrapped, "create_module", None)
        if callable(creator):
            return creator(spec)
        return None

    def exec_module(self, module: Any) -> None:
        executor = getattr(self._wrapped, "exec_module", None)
        if not callable(executor):
            raise ImportError("trading_strategy loader has no exec_module")
        executor(module)
        if not _patch_loaded_strategy_aliases():
            raise ImportError("precore_strategy_alias_v271_patch_failed")
        LOGGER.critical(
            "PRECORE_STRATEGY_ALIAS_V271_PATCHED marker=%s module=%s "
            "constructor_not_started=true market_discovery_bounded=true "
            "execution_authority_unchanged=true safety_gates_bypassed=false",
            MARKER,
            getattr(module, "__name__", "trading_strategy"),
        )

    def __getattr__(self, name: str) -> Any:
        return getattr(self._wrapped, name)


class _TradingStrategyAliasFinder(importlib.abc.MetaPathFinder):
    """Wrap only the top-level trading_strategy loader without broad imports."""

    def find_spec(self, fullname: str, path: Any = None, target: Any = None) -> Any:
        if fullname != "trading_strategy":
            return None
        spec = importlib.machinery.PathFinder.find_spec(fullname, path)
        if spec is None or spec.loader is None:
            return spec
        if bool(getattr(spec.loader, _ALIAS_LOADER_ATTR, False)):
            return spec
        spec.loader = _TradingStrategyAliasLoader(spec.loader)
        return spec


def _install_strategy_alias_guard() -> bool:
    """Guarantee v269 is applied before bot.py receives top-level TradingStrategy."""
    global _ALIAS_FINDER

    # If the direct-entry alias is already loaded, patch synchronously now.
    if isinstance(sys.modules.get("trading_strategy"), ModuleType):
        return _patch_loaded_strategy_aliases()

    # Reuse an existing finder across re-installs/import aliases.
    for finder in list(sys.meta_path):
        if isinstance(finder, _TradingStrategyAliasFinder):
            _ALIAS_FINDER = finder
            return True

    finder = _TradingStrategyAliasFinder()
    sys.meta_path.insert(0, finder)
    _ALIAS_FINDER = finder
    LOGGER.critical(
        "PRECORE_STRATEGY_ALIAS_V271_ARMED marker=%s target=trading_strategy "
        "post_exec_pre_constructor=true early_strategy_import=false "
        "execution_authority_unchanged=true safety_gates_bypassed=false",
        MARKER,
    )
    return True


def _patch_strategy_builder() -> bool:
    """Install v269 immediately before the canonical strategy constructor runs."""
    try:
        import bot.strategy_publication_patch as publication
    except Exception as exc:
        LOGGER.critical(
            "PRECORE_STRATEGY_BUILDER_V269_IMPORT_FAILED marker=%s error=%s:%s "
            "trading_fail_closed=true",
            MARKER,
            type(exc).__name__,
            exc,
        )
        return False

    current = getattr(publication, "_build_strategy", None)
    if not callable(current):
        return False
    if bool(getattr(current, _BUILD_PATCH_ATTR, False)):
        return True
    previous = current

    @wraps(previous)
    def _build_strategy_with_v269(cls: type, brokers: dict[Any, dict[str, Any]]) -> Any:
        # publish_canonical_strategy resolves cls before reaching this builder,
        # so a strategy module is already loaded. v269 patches every resident
        # alias and does not create a second production strategy class.
        try:
            from bot.runtime_precore_symbol_discovery_liveness_v269_patch import (
                install as install_v269,
            )
        except Exception as exc:
            raise RuntimeError(
                f"precore_symbol_discovery_v269_import_failed:{type(exc).__name__}:{exc}"
            ) from exc
        if not install_v269():
            raise RuntimeError("precore_symbol_discovery_v269_install_failed")
        LOGGER.critical(
            "PRECORE_STRATEGY_BUILDER_V269_ARMED marker=%s "
            "constructor_next=true early_import_fanout=false trading_fail_closed=true",
            MARKER,
        )
        return previous(cls, brokers)

    setattr(_build_strategy_with_v269, _BUILD_PATCH_ATTR, True)
    setattr(_build_strategy_with_v269, "__wrapped__", previous)
    publication._build_strategy = _build_strategy_with_v269
    return True


def install() -> bool:
    with _LOCK:
        lookup_ready = _patch_v203()
        builder_ready = _patch_strategy_builder()
        alias_guard_ready = _install_strategy_alias_guard()
        ready = bool(lookup_ready and builder_ready and alias_guard_ready)
        os.environ[_READY_FLAG] = "1" if ready else "0"
        if not ready:
            LOGGER.critical(
                "PRECORE_STRATEGY_LOOKUP_V207_FAILED marker=%s lookup_ready=%s "
                "builder_v269_ready=%s alias_guard_v271_ready=%s trading_fail_closed=true",
                MARKER,
                str(lookup_ready).lower(),
                str(builder_ready).lower(),
                str(alias_guard_ready).lower(),
            )
            return False
        LOGGER.critical(
            "PRECORE_STRATEGY_LOOKUP_V207_READY marker=%s ready=true "
            "install_time_lookup_nonblocking=true broad_existing_scan=false "
            "already_loaded_pointers_only=true v127_cached_pointer_allowed=true "
            "step2_5_single_owner_preserved=true strategy_constructor_v269_guarded=true "
            "top_level_strategy_alias_v271_guarded=true post_exec_pre_constructor_patch=true "
            "early_trading_strategy_import=false strategy_constructed=false "
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
    "_patch_strategy_builder",
    "_patch_loaded_strategy_aliases",
    "_install_strategy_alias_guard",
]
