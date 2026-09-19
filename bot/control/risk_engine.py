"""
NIJA Control Layer — Risk Engine
==================================

Validates every trade against institutional-grade risk rules before
execution.  Rules are loaded from environment variables and stored in
Redis so they can be updated at runtime without a redeploy.

Risk Rules (all configurable via env / Redis)
---------------------------------------------
max_concurrent_positions   — default 8  (env: NIJA_MAX_CONCURRENT_POSITIONS or MAX_CONCURRENT_POSITIONS)
max_position_size_pct      — default 50 % of portfolio  (env: NIJA_MAX_POSITION_SIZE_PCT or MAX_POSITION_PCT)
max_daily_loss_pct         — default 2 % of portfolio   (env: NIJA_MAX_DAILY_LOSS_PCT)
max_drawdown_pct           — default 2 % of portfolio   (env: NIJA_MAX_DRAWDOWN_PCT)
max_correlation            — default 0.80
min_time_between_trades_ms — default 1 000 ms

Usage
-----
::

    from bot.control.risk_engine import get_risk_engine

    engine = get_risk_engine()
    approved, notes = engine.validate_trade(
        symbol="BTC-USD",
        side="buy",
        size_usd=500.0,
        portfolio_value_usd=10_000.0,
        current_positions=[...],
        daily_pnl=-200.0,
        peak_portfolio_value=11_000.0,
    )
    if not approved:
        logger.warning("Trade blocked: %s", notes)

Author: NIJA Trading Systems
Phase:  1 — Control Layer
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from bot.control.trading_context import TradingContext

logger = logging.getLogger("nija.control.risk")

# ---------------------------------------------------------------------------
# Environment-driven defaults
# ---------------------------------------------------------------------------

_RISK_ENGINE_ENABLED: bool = (
    os.getenv("NIJA_RISK_ENGINE_ENABLED", "true").lower() == "true"
)

_ENV_RULES: Dict[str, Any] = {
    "max_concurrent_positions":    int(float(
        os.getenv("NIJA_MAX_CONCURRENT_POSITIONS", "")
        or os.getenv("MAX_CONCURRENT_POSITIONS", "")
        or "8"
    )),
    "max_position_size_pct":       float(
        os.getenv("NIJA_MAX_POSITION_SIZE_PCT", "")
        or os.getenv("MAX_POSITION_PCT", "")
        or "50.0"
    ),
    "max_daily_loss_pct":          float(os.getenv("NIJA_MAX_DAILY_LOSS_PCT",              "2.0")),
    "max_drawdown_pct":            float(os.getenv("NIJA_MAX_DRAWDOWN_PCT",                "2.0")),
    "max_correlation":             float(os.getenv("NIJA_MAX_CORRELATION",                 "0.80")),
    "min_time_between_trades_ms":  int(float(os.getenv("NIJA_MIN_TIME_BETWEEN_TRADES_MS", "1000"))),
}

# Redis key for live rule overrides
_REDIS_RULES_KEY = "nija:control:risk_rules"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class RiskRules:
    """Snapshot of active risk rules."""
    max_concurrent_positions:   int   = 8
    max_position_size_pct:      float = 50.0
    max_daily_loss_pct:         float = 2.0
    max_drawdown_pct:           float = 2.0
    max_correlation:            float = 0.80
    min_time_between_trades_ms: int   = 1000

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "RiskRules":
        return cls(
            max_concurrent_positions=int(d.get("max_concurrent_positions", 8)),
            max_position_size_pct=float(d.get("max_position_size_pct", 50.0)),
            max_daily_loss_pct=float(d.get("max_daily_loss_pct", 2.0)),
            max_drawdown_pct=float(d.get("max_drawdown_pct", 2.0)),
            max_correlation=float(d.get("max_correlation", 0.80)),
            min_time_between_trades_ms=int(d.get("min_time_between_trades_ms", 1000)),
        )


# ---------------------------------------------------------------------------
# RiskEngine
# ---------------------------------------------------------------------------

class RiskEngine:
    """
    Validates trades against configurable risk rules.

    Thread-safe.  Use ``get_risk_engine()`` for the process singleton.
    """

    def __init__(self, redis_client=None) -> None:
        self._redis = redis_client
        self._lock  = threading.Lock()
        self._rules = RiskRules(**_ENV_RULES)
        self._last_trade_ts: Dict[str, float] = {}   # context|symbol → last trade timestamp
        self._platform_kill_switch: bool = False
        self._platform_kill_switch_reason: str = ""
        self._user_kill_switches: Dict[str, str] = {}
        self._account_kill_switches: Dict[Tuple[str, str, str, str], str] = {}
        self._strategy_kill_switches: Dict[Tuple[str, str, str, str], str] = {}
        self._broker_connection_kill_switches: Dict[Tuple[str, str, str], str] = {}
        self._broker_failure_counters: Dict[Tuple[str, str, str], int] = {}
        self._store_rules_to_redis()
        logger.info(
            "RiskEngine initialised | max_pos=%d max_size_pct=%.1f%% "
            "max_daily_loss=%.1f%% max_dd=%.1f%%",
            self._rules.max_concurrent_positions,
            self._rules.max_position_size_pct,
            self._rules.max_daily_loss_pct,
            self._rules.max_drawdown_pct,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def validate_trade(
        self,
        symbol: str,
        side: str,
        size_usd: float,
        portfolio_value_usd: float,
        current_positions: List[Dict[str, Any]],
        user_id: str = "",
        account_id: str = "default",
        broker: str = "",
        authoritative_position_proven: bool = True,
        daily_pnl: float = 0.0,
        peak_portfolio_value: Optional[float] = None,
        returns_series: Optional[List[float]] = None,
        trading_context: Optional[TradingContext] = None,
        enforce_isolation: bool = False,
        enforce_platform_kill_switch: bool = True,
    ) -> Tuple[bool, List[str]]:
        """
        Validate a proposed trade against all active risk rules.

        Parameters
        ----------
        symbol               : Instrument identifier.
        side                 : "buy" or "sell".
        size_usd             : Proposed position size in USD.
        portfolio_value_usd  : Current total portfolio value.
        current_positions    : List of open position dicts, each with at
                               least {"symbol": str, "size_usd": float}.
        daily_pnl            : Realised + unrealised P&L today (negative = loss).
        peak_portfolio_value : All-time high portfolio value for drawdown calc.
        returns_series       : Recent return series for correlation check.

        Returns
        -------
        (approved: bool, notes: List[str])
        """
        if not _RISK_ENGINE_ENABLED:
            return True, ["risk_engine_disabled:pass_through"]

        # Reload rules from Redis (non-blocking; falls back to cached)
        rules = self._load_rules()
        notes: List[str] = []
        if trading_context is None and enforce_isolation:
            return False, ["context_missing:missing_trading_context"]
        if trading_context is None:
            request_nonce = f"{threading.get_ident()}_{int(time.time() * 1000)}"
            trading_context = TradingContext(
                user_id=f"legacy_{request_nonce}",
                trading_account_id=f"legacy_account_{request_nonce}",
                broker="legacy",
                broker_account_id=f"legacy_broker_account_{request_nonce}",
                strategy_instance_id="legacy_strategy",
                portfolio_id="legacy_portfolio",
                request_id=f"legacy_request_{request_nonce}",
                correlation_id=f"legacy_correlation_{request_nonce}",
                environment="legacy",
                mode="paper",
            )

        ok, note = self._check_kill_switches(trading_context, enforce_platform_kill_switch=enforce_platform_kill_switch)
        if not ok:
            return False, [note]

        if enforce_isolation:
            mismatch = self._first_position_scope_mismatch(current_positions, trading_context)
            if mismatch:
                return False, [f"position_scope_mismatch:{mismatch}"]
        scoped_positions = self._filter_positions_for_context(
            current_positions,
            trading_context,
            include_unscoped=not enforce_isolation,
        )

        if not authoritative_position_proven:
            notes.append("AUTHORITATIVE_POSITION_UNPROVEN")
            return False, notes

        # 1. Position count
        ok, note = self._check_position_count(scoped_positions, rules)
        if not ok:
            notes.append(note)
            return False, notes

        # 2. Position size
        ok, note = self._check_position_size(size_usd, portfolio_value_usd, rules)
        if not ok:
            notes.append(note)
            return False, notes

        # 3. Daily loss
        ok, note = self._check_daily_loss(daily_pnl, portfolio_value_usd, rules)
        if not ok:
            notes.append(note)
            return False, notes

        # 4. Drawdown
        if peak_portfolio_value is not None:
            ok, note = self._check_drawdown(portfolio_value_usd, peak_portfolio_value, rules)
            if not ok:
                notes.append(note)
                return False, notes

        # 5. Correlation
        if returns_series is not None and len(returns_series) > 10:
            ok, note = self._check_correlation(symbol, returns_series, scoped_positions, rules)
            if not ok:
                notes.append(note)
                return False, notes

        # 6. Time between trades (per broker/account/symbol)
        ok, note = self._check_trade_frequency(
            symbol,
            account_id=account_id,
            broker=broker,
            rules=rules,
            trading_context=trading_context,
        )
        if not ok:
            notes.append(note)
            return False, notes

        # All checks passed
        self._record_trade(symbol, account_id, broker)
        notes.append("all_risk_checks_passed")
        return True, notes

    def set_platform_kill_switch(self, active: bool, reason: str = "") -> None:
        with self._lock:
            self._platform_kill_switch = bool(active)
            self._platform_kill_switch_reason = str(reason or "").strip()

    def set_user_kill_switch(self, user_id: str, active: bool, reason: str = "") -> None:
        key = str(user_id or "").strip()
        if not key:
            return
        with self._lock:
            if active:
                self._user_kill_switches[key] = str(reason or "user_kill_switch")
            else:
                self._user_kill_switches.pop(key, None)

    def set_account_kill_switch(self, context: TradingContext, active: bool, reason: str = "") -> None:
        key = (context.user_id, context.trading_account_id, context.broker, context.broker_account_id)
        with self._lock:
            if active:
                self._account_kill_switches[key] = str(reason or "account_kill_switch")
            else:
                self._account_kill_switches.pop(key, None)

    def set_strategy_kill_switch(self, context: TradingContext, active: bool, reason: str = "") -> None:
        key = (
            context.user_id,
            context.trading_account_id,
            context.broker,
            context.broker_account_id,
            context.strategy_instance_id,
        )
        with self._lock:
            if active:
                self._strategy_kill_switches[key] = str(reason or "strategy_kill_switch")
            else:
                self._strategy_kill_switches.pop(key, None)

    def set_broker_connection_kill_switch(self, context: TradingContext, active: bool, reason: str = "") -> None:
        key = (context.user_id, context.broker, context.broker_account_id)
        with self._lock:
            if active:
                self._broker_connection_kill_switches[key] = str(reason or "broker_connection_kill_switch")
            else:
                self._broker_connection_kill_switches.pop(key, None)

    def record_broker_failure(self, context: TradingContext) -> None:
        key = (context.user_id, context.broker, context.broker_account_id)
        with self._lock:
            self._broker_failure_counters[key] = int(self._broker_failure_counters.get(key, 0)) + 1

    def clear_broker_failures(self, context: TradingContext) -> None:
        key = (context.user_id, context.broker, context.broker_account_id)
        with self._lock:
            self._broker_failure_counters.pop(key, None)

    def update_rules(self, overrides: Dict[str, Any]) -> RiskRules:
        """Apply rule overrides and persist to Redis."""
        with self._lock:
            current = self._rules.to_dict()
            current.update(overrides)
            self._rules = RiskRules.from_dict(current)
        self._store_rules_to_redis()
        logger.info("RiskEngine: rules updated: %s", overrides)
        return self._rules

    def get_rules(self) -> RiskRules:
        return self._load_rules()

    # ------------------------------------------------------------------
    # Individual checks
    # ------------------------------------------------------------------

    @staticmethod
    def _check_position_count(
        positions: List[Dict[str, Any]],
        rules: RiskRules,
    ) -> Tuple[bool, str]:
        count = len(positions)
        if count >= rules.max_concurrent_positions:
            return False, (
                f"position_count_limit:{count}>={rules.max_concurrent_positions}"
            )
        return True, ""

    @staticmethod
    def _check_position_size(
        size_usd: float,
        portfolio_value_usd: float,
        rules: RiskRules,
    ) -> Tuple[bool, str]:
        if portfolio_value_usd <= 0:
            return True, ""
        pct = (size_usd / portfolio_value_usd) * 100.0
        if pct > rules.max_position_size_pct:
            return False, (
                f"position_size_limit:{pct:.2f}%>{rules.max_position_size_pct}%"
            )
        return True, ""

    @staticmethod
    def _check_daily_loss(
        daily_pnl: float,
        portfolio_value_usd: float,
        rules: RiskRules,
    ) -> Tuple[bool, str]:
        if portfolio_value_usd <= 0 or daily_pnl >= 0:
            return True, ""
        loss_pct = abs(daily_pnl) / portfolio_value_usd * 100.0
        if loss_pct >= rules.max_daily_loss_pct:
            return False, (
                f"daily_loss_limit:{loss_pct:.2f}%>={rules.max_daily_loss_pct}%"
            )
        return True, ""

    @staticmethod
    def _check_drawdown(
        current_value: float,
        peak_value: float,
        rules: RiskRules,
    ) -> Tuple[bool, str]:
        if peak_value <= 0:
            return True, ""
        dd_pct = (peak_value - current_value) / peak_value * 100.0
        if dd_pct >= rules.max_drawdown_pct:
            return False, (
                f"drawdown_limit:{dd_pct:.2f}%>={rules.max_drawdown_pct}%"
            )
        return True, ""

    @staticmethod
    def _check_correlation(
        symbol: str,
        returns_series: List[float],
        current_positions: List[Dict[str, Any]],
        rules: RiskRules,
    ) -> Tuple[bool, str]:
        """
        Reject if the proposed symbol's returns are highly correlated with
        any existing position's returns.
        """
        if not current_positions:
            return True, ""

        new_returns = np.array(returns_series, dtype=float)
        if len(new_returns) < 10 or np.std(new_returns) == 0:
            return True, ""

        for pos in current_positions:
            pos_returns = pos.get("returns_series")
            if pos_returns is None or len(pos_returns) < 10:
                continue
            pos_arr = np.array(pos_returns, dtype=float)
            min_len = min(len(new_returns), len(pos_arr))
            if min_len < 10:
                continue
            corr = float(np.corrcoef(new_returns[-min_len:], pos_arr[-min_len:])[0, 1])
            if abs(corr) >= rules.max_correlation:
                pos_symbol = pos.get("symbol", "unknown")
                return False, (
                    f"correlation_limit:{symbol}↔{pos_symbol}:"
                    f"corr={corr:.3f}>={rules.max_correlation}"
                )
        return True, ""

    def _check_trade_frequency(
        self,
        symbol: str,
        account_id: str,
        broker: str,
        rules: RiskRules,
        *,
        trading_context: TradingContext,
    ) -> Tuple[bool, str]:
        now_ms = time.time() * 1000
        frequency_key = self._trade_frequency_key(symbol, account_id, broker)
        with self._lock:
            last_ms = self._last_trade_ts.get(frequency_key, 0.0)
        elapsed_ms = now_ms - last_ms
        if elapsed_ms < rules.min_time_between_trades_ms:
            return False, (
                f"trade_frequency_limit:{frequency_key}:"
        key = self._trade_frequency_key(symbol, trading_context=trading_context)
        with self._lock:
            last_ms = self._last_trade_ts.get(key, 0.0)
        elapsed_ms = now_ms - last_ms
        if elapsed_ms < rules.min_time_between_trades_ms:
            return False, (
                f"trade_frequency_limit:{key}:"
                f"elapsed={elapsed_ms:.0f}ms<{rules.min_time_between_trades_ms}ms"
            )
        return True, ""

    @staticmethod
    def _trade_frequency_key(symbol: str, account_id: str, broker: str) -> str:
        broker_key = str(broker or "unknown").strip().lower() or "unknown"
        account_key = str(account_id or "default").strip().lower() or "default"
        return f"{broker_key}:{account_key}:{symbol.upper()}"

    def _record_trade(self, symbol: str, account_id: str, broker: str) -> None:
        frequency_key = self._trade_frequency_key(symbol, account_id, broker)
        with self._lock:
            self._last_trade_ts[frequency_key] = time.time() * 1000
    def _record_trade(self, symbol: str, *, trading_context: TradingContext) -> None:
        key = self._trade_frequency_key(symbol, trading_context=trading_context)
        with self._lock:
            self._last_trade_ts[key] = time.time() * 1000

    @staticmethod
    def _trade_frequency_key(symbol: str, *, trading_context: TradingContext) -> str:
        return f"{trading_context.scope_key}|{str(symbol or '').upper()}"

    @staticmethod
    def _position_owner_key(position: Dict[str, Any]) -> Optional[Tuple[str, str, str, str]]:
        if not isinstance(position, dict):
            return None
        context = position.get("trading_context")
        if isinstance(context, TradingContext):
            return (context.user_id, context.trading_account_id, context.broker, context.broker_account_id)
        if isinstance(context, dict):
            try:
                parsed = TradingContext.from_mapping(context)
                return (parsed.user_id, parsed.trading_account_id, parsed.broker, parsed.broker_account_id)
            except Exception:
                return None
        user_id = str(position.get("user_id") or "").strip()
        account_id = str(position.get("trading_account_id") or "").strip()
        broker = str(position.get("broker") or "").strip().lower()
        broker_account_id = str(position.get("broker_account_id") or "").strip()
        if user_id and account_id and broker and broker_account_id:
            return (user_id, account_id, broker, broker_account_id)
        return None

    def _filter_positions_for_context(
        self,
        positions: List[Dict[str, Any]],
        trading_context: TradingContext,
        *,
        include_unscoped: bool = True,
    ) -> List[Dict[str, Any]]:
        expected = (
            trading_context.user_id,
            trading_context.trading_account_id,
            trading_context.broker,
            trading_context.broker_account_id,
        )
        scoped: List[Dict[str, Any]] = []
        for pos in positions or []:
            owner = self._position_owner_key(pos)
            if owner == expected:
                scoped.append(pos)
                continue
            if include_unscoped and owner is None:
                scoped.append(pos)
        return scoped

    def _first_position_scope_mismatch(
        self,
        positions: List[Dict[str, Any]],
        trading_context: TradingContext,
    ) -> str:
        expected = (
            trading_context.user_id,
            trading_context.trading_account_id,
            trading_context.broker,
            trading_context.broker_account_id,
        )
        for idx, pos in enumerate(positions or []):
            owner = self._position_owner_key(pos)
            if owner is None:
                return f"missing_owner_metadata:index={idx}"
            if owner != expected:
                return f"owner_mismatch:index={idx}"
        return ""

    def _check_kill_switches(
        self,
        context: TradingContext,
        *,
        enforce_platform_kill_switch: bool,
    ) -> Tuple[bool, str]:
        account_key = (context.user_id, context.trading_account_id, context.broker, context.broker_account_id)
        broker_key = (context.user_id, context.broker, context.broker_account_id)
        with self._lock:
            if enforce_platform_kill_switch and self._platform_kill_switch:
                return False, f"platform_kill_switch:{self._platform_kill_switch_reason or 'active'}"
            if context.user_id in self._user_kill_switches:
                return False, f"user_kill_switch:{self._user_kill_switches[context.user_id]}"
            if account_key in self._account_kill_switches:
                return False, f"account_kill_switch:{self._account_kill_switches[account_key]}"
            strategy_key = (
                context.user_id,
                context.trading_account_id,
                context.broker,
                context.broker_account_id,
                context.strategy_instance_id,
            )
            if strategy_key in self._strategy_kill_switches:
                return False, f"strategy_kill_switch:{self._strategy_kill_switches[strategy_key]}"
            if broker_key in self._broker_connection_kill_switches:
                return False, f"broker_connection_kill_switch:{self._broker_connection_kill_switches[broker_key]}"
        return True, ""

    # ------------------------------------------------------------------
    # Redis helpers
    # ------------------------------------------------------------------

    def _load_rules(self) -> RiskRules:
        """Load rules from Redis if available, else return cached."""
        if self._redis is None:
            with self._lock:
                return self._rules
        try:
            data = self._redis.get(_REDIS_RULES_KEY)
            if data:
                d = json.loads(data)
                return RiskRules.from_dict(d)
        except Exception as exc:
            logger.debug("RiskEngine: Redis rule load failed: %s", exc)
        with self._lock:
            return self._rules

    def _store_rules_to_redis(self) -> None:
        if self._redis is None:
            return
        try:
            with self._lock:
                rules_dict = self._rules.to_dict()
            self._redis.set(_REDIS_RULES_KEY, json.dumps(rules_dict))
        except Exception as exc:
            logger.debug("RiskEngine: Redis rule store failed: %s", exc)

    # ------------------------------------------------------------------
    # Observability
    # ------------------------------------------------------------------

    def get_health(self) -> Dict[str, Any]:
        rules = self.get_rules()
        with self._lock:
            platform = self._platform_kill_switch
            user_count = len(self._user_kill_switches)
            account_count = len(self._account_kill_switches)
            strategy_count = len(self._strategy_kill_switches)
            broker_count = len(self._broker_connection_kill_switches)
        return {
            "available":    True,
            "enabled":      _RISK_ENGINE_ENABLED,
            "active_rules": rules.to_dict(),
            "kill_switches": {
                "platform": platform,
                "user_count": user_count,
                "account_count": account_count,
                "strategy_count": strategy_count,
                "broker_connection_count": broker_count,
            },
        }


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_singleton: Optional[RiskEngine] = None
_singleton_lock = threading.Lock()


def get_risk_engine(redis_client=None) -> RiskEngine:
    """Return the process-level RiskEngine singleton."""
    global _singleton
    if _singleton is None:
        with _singleton_lock:
            if _singleton is None:
                _singleton = RiskEngine(redis_client=redis_client)
    return _singleton
