from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List

logger = logging.getLogger("nija.pre_trade_risk_engine")


@dataclass
class PreTradeRiskDecision:
    approved: bool
    reason: str
    details: Dict[str, Any] = field(default_factory=dict)


class PreTradeRiskEngine:
    """Centralized pre-dispatch risk checks for exposure and correlation."""

    def __init__(
        self,
        max_symbol_exposure_pct: float = 0.25,
        max_total_exposure_pct: float = 0.90,
    ) -> None:
        self.max_symbol_exposure_pct = float(max_symbol_exposure_pct)
        self.max_total_exposure_pct = float(max_total_exposure_pct)
        self._lock = threading.RLock()
        self._symbol_exposure_usd: Dict[str, Dict[str, float]] = {}
        self._correlation_filter = self._load_correlation_filter()
        self._global_risk_engine = self._load_global_risk_engine()

    def assess(
        self,
        *,
        account_id: str,
        symbol: str,
        size_usd: float,
        available_balance_usd: float | None,
    ) -> PreTradeRiskDecision:
        with self._lock:
            account_key = account_id or "default"
            exposures = self._symbol_exposure_usd.setdefault(account_key, {})
            current_symbol_exposure = float(exposures.get(symbol, 0.0))
            current_total_exposure = float(sum(exposures.values()))
            balance = float(available_balance_usd or 0.0)

            if balance > 0:
                next_total = current_total_exposure + float(size_usd)
                if next_total > balance * self.max_total_exposure_pct:
                    return PreTradeRiskDecision(
                        approved=False,
                        reason="GLOBAL_EXPOSURE_CAP",
                        details={
                            "current_total_exposure_usd": current_total_exposure,
                            "next_total_exposure_usd": next_total,
                            "balance_usd": balance,
                            "limit_pct": self.max_total_exposure_pct,
                        },
                    )

                next_symbol = current_symbol_exposure + float(size_usd)
                if next_symbol > balance * self.max_symbol_exposure_pct:
                    return PreTradeRiskDecision(
                        approved=False,
                        reason="SYMBOL_AGGREGATION_CAP",
                        details={
                            "symbol_exposure_usd": current_symbol_exposure,
                            "next_symbol_exposure_usd": next_symbol,
                            "balance_usd": balance,
                            "limit_pct": self.max_symbol_exposure_pct,
                        },
                    )

            if self._global_risk_engine is not None:
                try:
                    allowed, reason = self._global_risk_engine.can_open_position(account_key, float(size_usd))
                    if not allowed:
                        return PreTradeRiskDecision(
                            approved=False,
                            reason=reason,
                            details={"source": "global_risk_engine"},
                        )
                except Exception as exc:
                    logger.warning("PreTradeRiskEngine: global risk probe failed: %s", exc)

            if self._correlation_filter is not None:
                try:
                    corr = self._correlation_filter.check(symbol, list(exposures.keys()))
                    if not corr.passed:
                        return PreTradeRiskDecision(
                            approved=False,
                            reason=corr.reason,
                            details={"source": "correlation_filter", **corr.details},
                        )
                except Exception as exc:
                    logger.warning("PreTradeRiskEngine: correlation check failed: %s", exc)

            return PreTradeRiskDecision(
                approved=True,
                reason="approved",
                details={
                    "symbol_exposure_usd": current_symbol_exposure,
                    "total_exposure_usd": current_total_exposure,
                },
            )

    def record_execution(
        self,
        *,
        account_id: str,
        symbol: str,
        side: str,
        size_usd: float,
        success: bool,
    ) -> None:
        if not success:
            return

        with self._lock:
            account_key = account_id or "default"
            exposures = self._symbol_exposure_usd.setdefault(account_key, {})
            delta = float(size_usd)
            if side.lower() == "sell":
                exposures[symbol] = max(0.0, float(exposures.get(symbol, 0.0)) - delta)
            else:
                exposures[symbol] = float(exposures.get(symbol, 0.0)) + delta

            if exposures.get(symbol, 0.0) <= 0:
                exposures.pop(symbol, None)

    @staticmethod
    def _load_correlation_filter():
        for mod_name in ("bot.entry_guardrails", "entry_guardrails"):
            try:
                mod = __import__(mod_name, fromlist=["PortfolioCorrelationFilter"])
                return mod.PortfolioCorrelationFilter()
            except Exception:
                continue
        return None

    @staticmethod
    def _load_global_risk_engine():
        for mod_name in ("core.global_risk_engine", "bot.global_risk_engine", "global_risk_engine"):
            try:
                mod = __import__(mod_name, fromlist=["get_global_risk_engine"])
                getter = getattr(mod, "get_global_risk_engine", None)
                if callable(getter):
                    return getter()
            except Exception:
                continue
        return None


_instance: PreTradeRiskEngine | None = None
_instance_lock = threading.Lock()


def get_pre_trade_risk_engine() -> PreTradeRiskEngine:
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = PreTradeRiskEngine()
    return _instance