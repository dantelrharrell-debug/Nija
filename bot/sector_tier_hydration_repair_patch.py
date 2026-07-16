from __future__ import annotations

import builtins
import logging
import sys
from types import ModuleType
from typing import Any, Callable, Optional

logger = logging.getLogger("nija.sector_tier_hydration_repair")
_MARKER = "20260706a"
_PATCHED_ATTR = "_nija_sector_tier_hydration_repair_20260706a"
_ORIGINAL_IMPORT: Optional[Callable[..., Any]] = None
_TARGETS = {"bot.tier_config", "tier_config", "bot.crypto_sector_taxonomy", "crypto_sector_taxonomy"}


def _install_position_adoption_exit_integrity() -> None:
    try:
        try:
            from bot.position_adoption_exit_integrity_patch import install_import_hook
        except ImportError:
            from position_adoption_exit_integrity_patch import install_import_hook  # type: ignore[import]
        install_import_hook()
        logger.critical(
            "POSITION_ADOPTION_EXIT_INTEGRITY_CHAINED marker=20260716-position-adoption-exit-integrity-v1"
        )
    except Exception as exc:
        logger.critical(
            "POSITION_ADOPTION_EXIT_INTEGRITY_CHAIN_FAILED marker=20260716-position-adoption-exit-integrity-v1 error=%s",
            exc,
        )


def _norm_symbol(value: Any) -> str:
    text = str(value or "").strip().upper().replace("/", "-").replace("_", "-")
    while "--" in text:
        text = text.replace("--", "-")
    return text


def _split_symbol(symbol: Any) -> tuple[str, str]:
    norm = _norm_symbol(symbol)
    if "-" in norm:
        return norm.rsplit("-", 1)
    for suffix in ("USDT", "USDC", "USD", "BTC", "ETH"):
        if norm.endswith(suffix) and len(norm) > len(suffix):
            return norm[: -len(suffix)], suffix
    return norm, ""


def _canonical_symbol(symbol: Any, module: ModuleType | None = None) -> str:
    norm = _norm_symbol(symbol)
    symbols = getattr(module, "SYMBOL_TO_SECTOR", {}) if module is not None else {}
    if norm in symbols:
        return norm
    base, quote = _split_symbol(norm)
    if quote and base.startswith("OK") and len(base) > 2:
        candidate = f"{base[2:]}-{quote}"
        if candidate in symbols:
            return candidate
    return norm


def _live_capital_usd() -> float:
    best = 0.0
    for module_name in ("bot.capital_authority", "capital_authority"):
        try:
            mod = __import__(module_name, fromlist=["get_capital_authority"])
            getter = getattr(mod, "get_capital_authority", None)
            if not callable(getter):
                continue
            ca = getter()
            for attr in ("total_capital", "real_capital", "usable_capital"):
                try:
                    best = max(best, float(getattr(ca, attr, 0.0) or 0.0))
                except Exception:
                    pass
            usable = getattr(ca, "get_usable_capital", None)
            if callable(usable):
                try:
                    best = max(best, float(usable() or 0.0))
                except Exception:
                    pass
        except Exception:
            continue
    return best


def _select_tier(module: ModuleType, balance: float) -> Any:
    TradingTier = getattr(module, "TradingTier", None)
    TIER_CONFIGS = getattr(module, "TIER_CONFIGS", {})
    if TradingTier is None or not TIER_CONFIGS:
        return None
    if balance <= 0.0:
        return getattr(TradingTier, "NO_CAPITAL", None)
    starter = TIER_CONFIGS.get(getattr(TradingTier, "STARTER", None))
    if starter is not None and balance < float(getattr(starter, "capital_min", 50.0)):
        return getattr(TradingTier, "NANO_PLATFORM", None)
    for name in ("BALLER", "LIVABLE", "INCOME", "INVESTOR", "SAVER", "STARTER"):
        tier = getattr(TradingTier, name, None)
        cfg = TIER_CONFIGS.get(tier)
        if tier is not None and cfg is not None and balance >= float(getattr(cfg, "capital_min", 0.0)):
            return tier
    return getattr(TradingTier, "NANO_PLATFORM", None)


def _patch_tier_config(module: ModuleType) -> bool:
    original = getattr(module, "get_tier_from_balance_internal", None)
    if not callable(original) or getattr(original, _PATCHED_ATTR, False):
        return False

    def patched(balance: float):
        try:
            requested = float(balance or 0.0)
        except Exception:
            requested = 0.0
        live = _live_capital_usd()
        effective = max(requested, live)
        if effective > 0.0:
            tier = _select_tier(module, effective)
            if tier is not None:
                logger.warning(
                    "TIER_HYDRATION_FALLBACK_APPLIED marker=%s requested_balance=%.2f live_capital=%.2f effective_balance=%.2f tier=%s",
                    _MARKER,
                    requested,
                    live,
                    effective,
                    getattr(tier, "value", tier),
                )
                return tier
        return original(balance)

    setattr(patched, _PATCHED_ATTR, True)
    setattr(module, "get_tier_from_balance_internal", patched)
    logger.warning("SECTOR_TIER_HYDRATION_REPAIR_PATCHED marker=%s target=tier_config", _MARKER)
    return True


def _patch_sector_taxonomy(module: ModuleType) -> bool:
    original = getattr(module, "get_sector", None)
    if not callable(original) or getattr(original, _PATCHED_ATTR, False):
        return False

    def patched(symbol: str):
        canonical = _canonical_symbol(symbol, module)
        old = _norm_symbol(symbol)
        if canonical != old:
            logger.warning("SECTOR_SYMBOL_ALIAS_REPAIRED marker=%s old_symbol=%s canonical_symbol=%s", _MARKER, old, canonical)
        return original(canonical)

    setattr(patched, _PATCHED_ATTR, True)
    setattr(module, "get_sector", patched)
    logger.warning("SECTOR_TIER_HYDRATION_REPAIR_PATCHED marker=%s target=crypto_sector_taxonomy", _MARKER)
    return True


def _try_patch_loaded() -> None:
    for name in tuple(_TARGETS):
        module = sys.modules.get(name)
        if not isinstance(module, ModuleType):
            continue
        if name in {"bot.tier_config", "tier_config"}:
            _patch_tier_config(module)
        elif name in {"bot.crypto_sector_taxonomy", "crypto_sector_taxonomy"}:
            _patch_sector_taxonomy(module)


def install_import_hook() -> None:
    global _ORIGINAL_IMPORT
    _install_position_adoption_exit_integrity()
    _try_patch_loaded()
    if getattr(builtins, "_NIJA_SECTOR_TIER_HYDRATION_REPAIR_HOOK", False):
        return
    _ORIGINAL_IMPORT = builtins.__import__

    def guarded_import(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
        module = _ORIGINAL_IMPORT(name, globals, locals, fromlist, level)  # type: ignore[misc]
        try:
            if name in _TARGETS or name.endswith(("tier_config", "crypto_sector_taxonomy")):
                _try_patch_loaded()
        except Exception as exc:
            logger.warning("SECTOR_TIER_HYDRATION_REPAIR_IMPORT_HOOK_FAILED marker=%s name=%s err=%s", _MARKER, name, exc)
        return module

    builtins.__import__ = guarded_import
    setattr(builtins, "_NIJA_SECTOR_TIER_HYDRATION_REPAIR_HOOK", True)
    logger.warning("SECTOR_TIER_HYDRATION_REPAIR_IMPORT_HOOK marker=%s", _MARKER)


def install() -> None:
    install_import_hook()
