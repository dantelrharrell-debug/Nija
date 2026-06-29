"""User-level startup defaults for NIJA runtime."""

from __future__ import annotations

import logging
import os
import sys
import threading
import time
from types import SimpleNamespace

logger = logging.getLogger("nija.usercustomize")

# US OKX accounts require the US regional API host. Keep an explicit Railway
# OKX_BASE_URL override if one is provided; otherwise default to us.okx.com.
os.environ.setdefault("OKX_BASE_URL", "https://us.okx.com")
os.environ.setdefault("OKX_US_REGION", "true")

# Conservative execution defaults: NIJA cannot guarantee profit, but it should
# require fee/slippage-aware positive expectancy before entry orders are allowed.
os.environ.setdefault("NIJA_PROFITABILITY_GUARD_ENABLED", "true")
os.environ.setdefault("NIJA_MIN_EXPECTANCY_THRESHOLD_PCT", "0.15")
os.environ.setdefault("MIN_EXPECTANCY_THRESHOLD_PCT", "0.15")
os.environ.setdefault("NIJA_MIN_EDGE_THRESHOLD", "0.0015")
os.environ.setdefault("MIN_EDGE_THRESHOLD", "0.0015")
os.environ.setdefault("NIJA_LOG_TRADE_DECISIONS", "true")


def _install_position_sync_hook() -> bool:
    for module_name in ("bot.multi_account_broker_manager", "multi_account_broker_manager"):
        module = sys.modules.get(module_name)
        cls = getattr(module, "MultiAccountBrokerManager", None) if module else None
        if cls is None:
            continue

        original = getattr(cls, "refresh_capital_authority", None)
        if original is None or getattr(original, "_position_sync_hooked", False):
            return bool(original)

        def wrapped_refresh(self, *args, **kwargs):
            result = original(self, *args, **kwargs)
            try:
                if getattr(self, "_startup_position_sync_done", False):
                    return result
                ready = isinstance(result, dict) and float(result.get("ready", 0.0) or 0.0) > 0.0
                capital = float(result.get("total_capital", 0.0) or 0.0) if isinstance(result, dict) else 0.0
                trigger = str(kwargs.get("trigger", "refresh_capital_authority"))
                if not ready or capital <= 0.0:
                    logger.info("EXCHANGE_POSITION_SYNC pending trigger=%s ready=%s capital=%.2f", trigger, ready, capital)
                    return result

                setattr(self, "_startup_position_sync_done", True)
                try:
                    from bot.startup_position_sync import sync_exchange_positions_on_startup
                except ImportError:
                    from startup_position_sync import sync_exchange_positions_on_startup  # type: ignore
                logger.warning("EXCHANGE_POSITION_SYNC invocation starting trigger=%s", trigger)
                adopted = sync_exchange_positions_on_startup(SimpleNamespace(multi_account_manager=self))
                logger.warning("EXCHANGE_POSITION_SYNC invocation complete adopted=%s trigger=%s", adopted, trigger)
            except Exception as exc:
                logger.exception("EXCHANGE_POSITION_SYNC invocation failed: %s", exc)
            return result

        wrapped_refresh._position_sync_hooked = True
        cls.refresh_capital_authority = wrapped_refresh
        logger.warning("EXCHANGE_POSITION_SYNC hook installed on %s", module_name)
        return True
    return False


def _position_sync_hook_watchdog() -> None:
    deadline = time.time() + float(os.getenv("NIJA_POSITION_SYNC_HOOK_TIMEOUT_S", "90"))
    while time.time() < deadline:
        if _install_position_sync_hook():
            return
        time.sleep(0.25)
    logger.warning("EXCHANGE_POSITION_SYNC hook not installed before timeout")


threading.Thread(target=_position_sync_hook_watchdog, name="position-sync-hook", daemon=True).start()
