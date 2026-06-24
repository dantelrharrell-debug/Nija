from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("nija.pre_trade_risk_engine")


@dataclass
class PreTradeRiskDecision:
    approved: bool
    reason: str
    details: Dict[str, Any] = field(default_factory=dict)


class PreTradeRiskEngine:
    """Centralized pre-dispatch risk checks for exposure and correlation.

    Exposure cap logic
    ------------------
    The engine tracks *open* position exposure per account in USD.  On each
    ``assess()`` call it checks whether adding ``size_usd`` to the running
    total would breach ``max_total_exposure_pct`` of the available balance.

    Key design decisions:
    * ``current_total_exposure`` is the sum of *already-open* positions, NOT
      the new order size.  The new order is only added hypothetically
      (``next_total``) to decide whether to approve.
    * Exposure is decremented by ``record_execution()`` when a ``sell`` /
      ``close`` side fills successfully, so the cap naturally relaxes as
      positions are closed.
    * When ``available_balance_usd`` is None or zero the cap check is skipped
      entirely (fail-open) to avoid blocking orders when balance data is
      temporarily unavailable.
    * The default cap is read from the ``NIJA_MAX_TOTAL_EXPOSURE_PCT``
      environment variable (default 0.80 = 80 %) so it matches the
      portfolio-level risk configuration without requiring a code change.
    """

    def __init__(
        self,
        max_symbol_exposure_pct: float = 0.25,
        max_total_exposure_pct: Optional[float] = None,
    ) -> None:
        # Allow the exposure cap to be tuned via environment variable so the
        # production value (80 %) is respected without a code change.
        if max_total_exposure_pct is None:
            _env_cap = os.getenv("NIJA_MAX_TOTAL_EXPOSURE_PCT", "").strip()
            try:
                max_total_exposure_pct = float(_env_cap) if _env_cap else 0.80
            except (TypeError, ValueError):
                max_total_exposure_pct = 0.80
        self.max_symbol_exposure_pct = float(max_symbol_exposure_pct)
        self.max_total_exposure_pct = float(max_total_exposure_pct)
        self._lock = threading.RLock()
        self._symbol_exposure_usd: Dict[str, Dict[str, float]] = {}
        self._correlation_filter = self._load_correlation_filter()
        self._global_risk_engine = self._load_global_risk_engine()
        logger.info(
            "PreTradeRiskEngine initialised | max_total_exposure_pct=%.0f%% "
            "max_symbol_exposure_pct=%.0f%%",
            self.max_total_exposure_pct * 100,
            self.max_symbol_exposure_pct * 100,
        )

    # ------------------------------------------------------------------
    # Exposure diagnostics helpers
    # ------------------------------------------------------------------

    def get_exposure_summary(self, account_id: str) -> Dict[str, Any]:
        """Return a snapshot of current exposure for *account_id*.

        Useful for logging before each order attempt so operators can see
        exactly how much headroom remains before the cap fires.
        """
        with self._lock:
            account_key = account_id or "default"
            exposures = self._symbol_exposure_usd.get(account_key, {})
            total = float(sum(exposures.values()))
            return {
                "account_id": account_key,
                "total_exposure_usd": total,
                "symbol_count": len(exposures),
                "symbols": dict(exposures),
                "max_total_exposure_pct": self.max_total_exposure_pct,
            }

    def get_remaining_headroom_usd(
        self, account_id: str, available_balance_usd: float
    ) -> float:
        """Return how many USD of new exposure can be added before the cap fires."""
        with self._lock:
            account_key = account_id or "default"
            exposures = self._symbol_exposure_usd.get(account_key, {})
            current_total = float(sum(exposures.values()))
            cap_usd = max(0.0, float(available_balance_usd)) * self.max_total_exposure_pct
            return max(0.0, cap_usd - current_total)

    def reset_account_exposure(self, account_id: str) -> None:
        """Clear all tracked exposure for *account_id*.

        Call this when the position ledger is reconciled from the broker so
        stale in-memory exposure does not permanently block new orders.
        """
        with self._lock:
            account_key = account_id or "default"
            removed = self._symbol_exposure_usd.pop(account_key, {})
            if removed:
                logger.info(
                    "PreTradeRiskEngine: exposure reset for account=%s "
                    "(cleared %d symbols, total_usd=%.2f)",
                    account_key,
                    len(removed),
                    sum(removed.values()),
                )

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

            # ── Diagnostic: log exposure state before every check ──────────
            if balance > 0:
                current_pct = (current_total_exposure / balance * 100.0) if balance > 0 else 0.0
                cap_usd = balance * self.max_total_exposure_pct
                headroom_usd = max(0.0, cap_usd - current_total_exposure)
                logger.info(
                    "📊 [PreTradeRisk] EXPOSURE_CHECK | account=%s symbol=%s "
                    "order_size_usd=%.2f current_exposure_usd=%.2f (%.1f%%) "
                    "cap_usd=%.2f (%.0f%%) headroom_usd=%.2f balance_usd=%.2f",
                    account_key,
                    symbol,
                    float(size_usd),
                    current_total_exposure,
                    current_pct,
                    cap_usd,
                    self.max_total_exposure_pct * 100,
                    headroom_usd,
                    balance,
                )

            if balance > 0:
                next_total = current_total_exposure + float(size_usd)
                if next_total > balance * self.max_total_exposure_pct:
                    headroom = max(0.0, balance * self.max_total_exposure_pct - current_total_exposure)
                    logger.warning(
                        "🚫 [PreTradeRisk] GLOBAL_EXPOSURE_CAP | account=%s symbol=%s "
                        "order_size_usd=%.2f current_total_usd=%.2f next_total_usd=%.2f "
                        "cap_usd=%.2f headroom_usd=%.2f balance_usd=%.2f limit_pct=%.0f%% — "
                        "reduce order size to ≤%.2f USD or close existing positions first",
                        account_key,
                        symbol,
                        float(size_usd),
                        current_total_exposure,
                        next_total,
                        balance * self.max_total_exposure_pct,
                        headroom,
                        balance,
                        self.max_total_exposure_pct * 100,
                        headroom,
                    )
                    return PreTradeRiskDecision(
                        approved=False,
                        reason="GLOBAL_EXPOSURE_CAP",
                        details={
                            "current_total_exposure_usd": current_total_exposure,
                            "next_total_exposure_usd": next_total,
                            "balance_usd": balance,
                            "limit_pct": self.max_total_exposure_pct,
                            "headroom_usd": headroom,
                            "cap_usd": balance * self.max_total_exposure_pct,
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
            _side = side.lower().strip()
            # Treat "sell", "close", "short" (closing a long) as exposure reduction.
            # Treat "buy", "long", "open" as exposure addition.
            if _side in ("sell", "close", "exit", "reduce"):
                exposures[symbol] = max(0.0, float(exposures.get(symbol, 0.0)) - delta)
            else:
                exposures[symbol] = float(exposures.get(symbol, 0.0)) + delta

            if exposures.get(symbol, 0.0) <= 0:
                exposures.pop(symbol, None)

            _new_total = float(sum(exposures.values()))
            logger.debug(
                "PreTradeRiskEngine.record_execution | account=%s symbol=%s side=%s "
                "size_usd=%.2f new_total_exposure_usd=%.2f",
                account_key, symbol, side, delta, _new_total,
            )

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