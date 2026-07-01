from __future__ import annotations

import importlib
import logging
import os
import sys
import threading
import time
from types import ModuleType
from typing import Any, Callable, Optional

logger = logging.getLogger("nija.downstream_risk_governor_equity_repair")
_ORIGINAL_IMPORT_MODULE: Optional[Callable[..., Any]] = None
_PATCHED = False
_MONITOR_STARTED = False
_INSTALL_LOCK = threading.Lock()


def _live_equity_usd() -> float:
    best = 0.0
    try:
        try:
            from bot.capital_authority import get_capital_authority
        except ImportError:
            from capital_authority import get_capital_authority  # type: ignore[import]
        ca = get_capital_authority()
        for attr in ("total_capital", "real_capital"):
            try:
                best = max(best, float(getattr(ca, attr, 0.0) or 0.0))
            except Exception:
                pass
        for meth in ("get_real_capital", "get_usable_capital"):
            getter = getattr(ca, meth, None)
            if callable(getter):
                try:
                    best = max(best, float(getter() or 0.0))
                except Exception:
                    pass
    except Exception:
        pass
    return best


def _install_on_module(module: ModuleType) -> bool:
    global _PATCHED
    cls = getattr(module, "DownstreamBlockerGuard", None)
    if not isinstance(cls, type):
        return False
    original = getattr(cls, "check_risk_governor", None)
    if not callable(original):
        return False
    if getattr(original, "_nija_downstream_risk_governor_equity_repair_wrapped", False):
        _PATCHED = True
        return True

    def _patched_check_risk_governor(self: Any, symbol: str, proposed_risk_usd: float, portfolio_value: float = 0.0, volatility_ratio: float = 1.0):
        live_equity = _live_equity_usd()
        incoming = float(portfolio_value or 0.0)
        repaired_value = max(incoming, live_equity)
        if live_equity > 0.0 and repaired_value > incoming:
            logger.critical(
                "DOWNSTREAM_RISK_GOVERNOR_EQUITY_REPAIR_APPLIED symbol=%s proposed_risk_usd=%.2f incoming_portfolio_value=%.2f live_equity_usd=%.2f repaired_portfolio_value=%.2f",
                symbol,
                float(proposed_risk_usd or 0.0),
                incoming,
                live_equity,
                repaired_value,
            )
            print(
                f"[NIJA-PRINT] DOWNSTREAM_RISK_GOVERNOR_EQUITY_REPAIR_APPLIED | symbol={symbol} proposed=${float(proposed_risk_usd or 0.0):.2f} portfolio_value=${repaired_value:.2f}",
                flush=True,
            )
        return original(self, symbol, proposed_risk_usd, repaired_value, volatility_ratio)

    setattr(_patched_check_risk_governor, "_nija_downstream_risk_governor_equity_repair_wrapped", True)
    setattr(cls, "check_risk_governor", _patched_check_risk_governor)
    _PATCHED = True
    logger.warning("DOWNSTREAM_RISK_GOVERNOR_EQUITY_REPAIR_PATCHED module=%s", getattr(module, "__name__", "<unknown>"))
    return True


def _try_patch_loaded() -> bool:
    patched = False
    for name in ("bot.downstream_blocker_guard", "downstream_blocker_guard"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            patched = _install_on_module(module) or patched
    return patched


def _start_monitor() -> None:
    global _MONITOR_STARTED
    if _MONITOR_STARTED:
        return
    _MONITOR_STARTED = True

    def _monitor() -> None:
        deadline = time.time() + float(os.environ.get("NIJA_PATCH_MONITOR_SECONDS", "240") or "240")
        while time.time() < deadline:
            if _try_patch_loaded():
                return
            time.sleep(0.25)
        logger.warning("DOWNSTREAM_RISK_GOVERNOR_EQUITY_REPAIR_MONITOR_EXPIRED patched=%s", _PATCHED)

    threading.Thread(target=_monitor, name="downstream-risk-governor-equity-repair-monitor", daemon=True).start()
    logger.warning("DOWNSTREAM_RISK_GOVERNOR_EQUITY_REPAIR_MONITOR_STARTED")


def install_import_hook() -> None:
    global _ORIGINAL_IMPORT_MODULE
    with _INSTALL_LOCK:
        _try_patch_loaded()
        _start_monitor()
        if _ORIGINAL_IMPORT_MODULE is not None:
            logger.warning("DOWNSTREAM_RISK_GOVERNOR_EQUITY_REPAIR_INSTALL_COMPLETE already_installed=True patched=%s", _PATCHED)
            return
        _ORIGINAL_IMPORT_MODULE = importlib.import_module

        def _wrapped_import_module(name: str, package: str | None = None):
            module = _ORIGINAL_IMPORT_MODULE(name, package)  # type: ignore[misc]
            if name in {"bot.downstream_blocker_guard", "downstream_blocker_guard"}:
                _install_on_module(module)
            return module

        importlib.import_module = _wrapped_import_module  # type: ignore[assignment]
        logger.warning("DOWNSTREAM_RISK_GOVERNOR_EQUITY_REPAIR_INSTALL_COMPLETE patched=%s", _PATCHED)
