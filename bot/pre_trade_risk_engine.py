from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

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
    The engine tracks open position exposure per account/broker namespace.  The
    cap base is total equity when available, not just free cash.  This matters
    for small live accounts where most capital can be held in active positions:
    using free cash alone makes the cap permanently block new micro entries even
    while account equity is healthy.
    """

    def __init__(
        self,
        max_symbol_exposure_pct: float = 0.35,
        max_total_exposure_pct: Optional[float] = None,
    ) -> None:
        if max_total_exposure_pct is None:
            _env_cap = (
                os.getenv("NIJA_MAX_TOTAL_EXPOSURE_PCT", "").strip()
                or os.getenv("NIJA_MAX_POSITION_SIZE_PCT", "").strip()
                or os.getenv("MAX_POSITION_PCT", "").strip()
            )
            try:
                if _env_cap:
                    _parsed = float(_env_cap)
                    max_total_exposure_pct = _parsed / 100.0 if _parsed > 1.0 else _parsed
                else:
                    # Live micro-cap default: allow staged positions while still
                    # preventing full-account overexposure.
                    max_total_exposure_pct = 0.85
            except (TypeError, ValueError):
                max_total_exposure_pct = 0.85
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

    @staticmethod
    def _bool_env(name: str, default: bool = False) -> bool:
        raw = os.getenv(name)
        if raw is None:
            return default
        return raw.strip().lower() in {"1", "true", "yes", "on", "y"}

    @staticmethod
    def _float_env(name: str, default: float) -> float:
        try:
            return float(os.getenv(name, default))
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _account_key(account_id: str) -> str:
        key = str(account_id or "default").strip() or "default"
        # Prevent platform/user or broker exposure from collapsing into one global
        # bucket when callers pass only a partial identifier.
        return key

    def _cap_base_usd(
        self,
        *,
        available_balance_usd: float | None,
        current_total_exposure: float,
    ) -> float:
        available = float(available_balance_usd or 0.0)
        hinted_equity = 0.0
        for key in (
            "NIJA_ACCOUNT_TOTAL_EQUITY_USD",
            "NIJA_PLATFORM_TOTAL_EQUITY_USD",
            "NIJA_TOTAL_CAPITAL_USD",
        ):
            hinted_equity = max(hinted_equity, self._float_env(key, 0.0))
        # Equity-aware cap base: if existing exposure is real held capital, it
        # should contribute to account equity instead of shrinking the cap base.
        return max(available, hinted_equity, available + max(0.0, current_total_exposure))

    def get_exposure_summary(self, account_id: str) -> Dict[str, Any]:
        with self._lock:
            account_key = self._account_key(account_id)
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
        with self._lock:
            account_key = self._account_key(account_id)
            exposures = self._symbol_exposure_usd.get(account_key, {})
            current_total = float(sum(exposures.values()))
            cap_base = self._cap_base_usd(
                available_balance_usd=available_balance_usd,
                current_total_exposure=current_total,
            )
            cap_usd = max(0.0, cap_base) * self.max_total_exposure_pct
            return max(0.0, cap_usd - current_total)

    def reset_account_exposure(self, account_id: str) -> None:
        with self._lock:
            account_key = self._account_key(account_id)
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
            account_key = self._account_key(account_id)
            exposures = self._symbol_exposure_usd.setdefault(account_key, {})
            current_symbol_exposure = float(exposures.get(symbol, 0.0))
            current_total_exposure = float(sum(exposures.values()))
            available = float(available_balance_usd or 0.0)
            cap_base = self._cap_base_usd(
                available_balance_usd=available,
                current_total_exposure=current_total_exposure,
            )
            requested_size = float(size_usd)

            if cap_base > 0:
                current_pct = (current_total_exposure / cap_base * 100.0) if cap_base > 0 else 0.0
                cap_usd = cap_base * self.max_total_exposure_pct
                headroom_usd = max(0.0, cap_usd - current_total_exposure)
                logger.info(
                    "📊 [PreTradeRisk] EXPOSURE_CHECK | account=%s symbol=%s "
                    "order_size_usd=%.2f current_exposure_usd=%.2f (%.1f%%) "
                    "cap_usd=%.2f (%.0f%%) headroom_usd=%.2f available_cash_usd=%.2f cap_base_usd=%.2f",
                    account_key,
                    symbol,
                    requested_size,
                    current_total_exposure,
                    current_pct,
                    cap_usd,
                    self.max_total_exposure_pct * 100,
                    headroom_usd,
                    available,
                    cap_base,
                )

                next_total = current_total_exposure + requested_size
                if next_total > cap_usd:
                    min_live = self._float_env("MIN_TRADE_USD", 0.0)
                    allow_micro_headroom = self._bool_env("NIJA_ALLOW_MICRO_ENTRY_AT_EXPOSURE_HEADROOM", True)
                    if allow_micro_headroom and headroom_usd >= max(1.0, min_live * 0.25):
                        logger.warning(
                            "⚠️ [PreTradeRisk] GLOBAL_EXPOSURE_HEADROOM_CLIP | account=%s symbol=%s "
                            "requested_size_usd=%.2f approved_headroom_usd=%.2f cap_usd=%.2f cap_base_usd=%.2f — "
                            "approving with downstream sizing expected to cap order to headroom",
                            account_key,
                            symbol,
                            requested_size,
                            headroom_usd,
                            cap_usd,
                            cap_base,
                        )
                    else:
                        logger.warning(
                            "🚫 [PreTradeRisk] GLOBAL_EXPOSURE_CAP | account=%s symbol=%s "
                            "order_size_usd=%.2f current_total_usd=%.2f next_total_usd=%.2f "
                            "cap_usd=%.2f headroom_usd=%.2f available_cash_usd=%.2f cap_base_usd=%.2f limit_pct=%.0f%% — "
                            "reduce order size to ≤%.2f USD or close existing positions first",
                            account_key,
                            symbol,
                            requested_size,
                            current_total_exposure,
                            next_total,
                            cap_usd,
                            headroom_usd,
                            available,
                            cap_base,
                            self.max_total_exposure_pct * 100,
                            headroom_usd,
                        )
                        return PreTradeRiskDecision(
                            approved=False,
                            reason=f"account={account_key} reason=GLOBAL_EXPOSURE_CAP",
                            details={
                                "account_id": account_key,
                                "current_total_exposure_usd": current_total_exposure,
                                "next_total_exposure_usd": next_total,
                                "available_cash_usd": available,
                                "cap_base_usd": cap_base,
                                "limit_pct": self.max_total_exposure_pct,
                                "headroom_usd": headroom_usd,
                                "cap_usd": cap_usd,
                            },
                        )

                next_symbol = current_symbol_exposure + requested_size
                symbol_cap_usd = cap_base * self.max_symbol_exposure_pct
                if next_symbol > symbol_cap_usd:
                    logger.warning(
                        "🚫 [PreTradeRisk] SYMBOL_AGGREGATION_CAP | account=%s symbol=%s "
                        "order_size_usd=%.2f current_symbol_usd=%.2f next_symbol_usd=%.2f "
                        "cap_usd=%.2f limit_pct=%.0f%% cap_base_usd=%.2f",
                        account_key,
                        symbol,
                        requested_size,
                        current_symbol_exposure,
                        next_symbol,
                        symbol_cap_usd,
                        self.max_symbol_exposure_pct * 100,
                        cap_base,
                    )
                    return PreTradeRiskDecision(
                        approved=False,
                        reason=f"account={account_key} reason=SYMBOL_AGGREGATION_CAP",
                        details={
                            "account_id": account_key,
                            "symbol_exposure_usd": current_symbol_exposure,
                            "next_symbol_exposure_usd": next_symbol,
                            "cap_base_usd": cap_base,
                            "limit_pct": self.max_symbol_exposure_pct,
                        },
                    )

            if self._global_risk_engine is not None:
                try:
                    # Use account-scoped key so platform, users, and brokers do
                    # not collapse into one global exposure bucket.
                    scoped_key = account_key
                    allowed, reason = self._global_risk_engine.can_open_position(scoped_key, requested_size)
                    if not allowed:
                        return PreTradeRiskDecision(
                            approved=False,
                            reason=reason,
                            details={"source": "global_risk_engine", "account_id": scoped_key},
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
                    "cap_base_usd": cap_base,
                    "remaining_headroom_usd": max(0.0, (cap_base * self.max_total_exposure_pct) - current_total_exposure),
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
            logger.debug(
                "PreTradeRiskEngine.record_execution | account=%s symbol=%s side=%s "
                "size_usd=%.2f success=False — exposure NOT updated",
                account_id or "default", symbol, side, float(size_usd),
            )
            return

        with self._lock:
            account_key = self._account_key(account_id)
            exposures = self._symbol_exposure_usd.setdefault(account_key, {})
            delta = float(size_usd)
            _side = side.lower().strip()
            if _side in ("sell", "close", "exit", "reduce"):
                exposures[symbol] = max(0.0, float(exposures.get(symbol, 0.0)) - delta)
                _direction = "REDUCED"
            else:
                exposures[symbol] = float(exposures.get(symbol, 0.0)) + delta
                _direction = "INCREASED"

            if exposures.get(symbol, 0.0) <= 0:
                exposures.pop(symbol, None)

            _new_total = float(sum(exposures.values()))
            logger.info(
                "📈 [PreTradeRisk] EXPOSURE_UPDATED | account=%s symbol=%s side=%s "
                "size_usd=%.2f direction=%s new_symbol_exposure_usd=%.2f "
                "new_total_exposure_usd=%.2f",
                account_key, symbol, side, delta, _direction,
                float(exposures.get(symbol, 0.0)),
                _new_total,
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
