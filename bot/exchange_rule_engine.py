"""
NIJA Unified Rule Abstraction Layer
=====================================

Rules are composable, independently-testable units.  Each rule evaluates
one specific aspect of an order and returns a :class:`RuleResult`.

Rules are assembled into per-exchange :class:`RuleChain` objects and
evaluated left-to-right.  The first failing rule short-circuits the chain
(unless *stop_on_fail=False* is set on the chain).

Built-in rules
--------------
MinOrderRule            order.usd_size >= min_order_usd
MaxOrderRule            order.usd_size <= max_order_usd
CapitalFloorRule        account_balance >= min_capital_usd
IsolationRule           broker is not PASSIVE / DISABLED
SymbolAllowlistRule     symbol in allowed set (empty = all allowed)
ForceSellBypassRule     SELL orders always skip subsequent rules
GlobalBuyGuardRule      HARD_BUY_OFF env / TRADING_EMERGENCY_STOP.conf

Usage
-----
    from bot.exchange_rule_engine import build_default_chain, RuleContext

    chain = build_default_chain("coinbase")
    ctx   = RuleContext(symbol="BTC-USD", side="buy", usd_size=5.0,
                        balance=50.0, broker_name="coinbase")
    result = chain.evaluate(ctx)
    if not result.passed:
        logger.warning("Order blocked: %s", result.reason)
"""

from __future__ import annotations

import logging
import os
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("nija.exchange_rule_engine")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class RuleContext:
    """All information a rule needs to evaluate an order."""
    symbol: str
    side: str                       # "buy" | "sell"
    usd_size: float
    balance: float = 0.0            # current account balance in USD
    broker_name: str = ""
    isolation_policy: str = ""      # from IsolationEntry.policy.value
    extra: Dict = field(default_factory=dict)


@dataclass
class RuleResult:
    """Outcome of a single rule evaluation."""
    passed: bool
    rule_name: str = ""
    reason: str = ""
    skip_remaining: bool = False    # when True, no further rules run


# ---------------------------------------------------------------------------
# Rule ABC
# ---------------------------------------------------------------------------

class ExchangeRule(ABC):
    """A single, independently-testable compliance rule."""

    @property
    def name(self) -> str:
        return type(self).__name__

    @abstractmethod
    def evaluate(self, ctx: RuleContext) -> RuleResult:
        """Evaluate the rule against *ctx*."""


# ---------------------------------------------------------------------------
# Built-in rules
# ---------------------------------------------------------------------------

class ForceSellBypassRule(ExchangeRule):
    """SELL orders always pass and short-circuit the rest of the chain.

    Protective exits must never be blocked by balance / size / isolation
    rules.  Any rule placed *after* this one is skipped for SELL orders.
    """

    def evaluate(self, ctx: RuleContext) -> RuleResult:
        if ctx.side.lower() == "sell":
            return RuleResult(
                passed=True,
                rule_name=self.name,
                reason="SELL_BYPASS",
                skip_remaining=True,
            )
        return RuleResult(passed=True, rule_name=self.name, reason="not_sell")


class GlobalBuyGuardRule(ExchangeRule):
    """Block BUY orders when HARD_BUY_OFF=1 or TRADING_EMERGENCY_STOP.conf exists."""

    def evaluate(self, ctx: RuleContext) -> RuleResult:
        if ctx.side.lower() != "buy":
            return RuleResult(passed=True, rule_name=self.name, reason="not_buy")
        hard_off = os.getenv("HARD_BUY_OFF", "0") in ("1", "true", "True")
        stop_file = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "TRADING_EMERGENCY_STOP.conf",
        )
        if hard_off or os.path.exists(stop_file):
            return RuleResult(
                passed=False,
                rule_name=self.name,
                reason="GLOBAL_BUY_GUARD: HARD_BUY_OFF or EMERGENCY_STOP active",
            )
        return RuleResult(passed=True, rule_name=self.name, reason="ok")


class IsolationRule(ExchangeRule):
    """Block BUY orders when the broker isolation policy prevents entries."""

    _ENTRY_BLOCKED = frozenset({"passive", "disabled", "isolated"})

    def evaluate(self, ctx: RuleContext) -> RuleResult:
        if ctx.side.lower() != "buy":
            return RuleResult(passed=True, rule_name=self.name, reason="not_buy")
        policy = ctx.isolation_policy.lower()
        if policy in self._ENTRY_BLOCKED:
            return RuleResult(
                passed=False,
                rule_name=self.name,
                reason=f"BROKER_ISOLATED: policy={policy}",
            )
        return RuleResult(passed=True, rule_name=self.name, reason="ok")


class CapitalFloorRule(ExchangeRule):
    """Block BUY orders when balance is below the exchange capital floor."""

    def __init__(self, min_capital_usd: float) -> None:
        self._floor = min_capital_usd

    def evaluate(self, ctx: RuleContext) -> RuleResult:
        if ctx.side.lower() != "buy":
            return RuleResult(passed=True, rule_name=self.name, reason="not_buy")
        if ctx.balance > 0 and ctx.balance < self._floor:
            return RuleResult(
                passed=False,
                rule_name=self.name,
                reason=(
                    f"CAPITAL_FLOOR: balance ${ctx.balance:.2f} < "
                    f"min ${self._floor:.2f}"
                ),
            )
        return RuleResult(passed=True, rule_name=self.name, reason="ok")


class MinOrderRule(ExchangeRule):
    """Block orders below the exchange minimum order size."""

    def __init__(self, min_order_usd: float) -> None:
        self._min = min_order_usd

    def evaluate(self, ctx: RuleContext) -> RuleResult:
        if ctx.usd_size > 0 and ctx.usd_size < self._min:
            return RuleResult(
                passed=False,
                rule_name=self.name,
                reason=(
                    f"MIN_ORDER: ${ctx.usd_size:.2f} < min ${self._min:.2f} "
                    f"on {ctx.broker_name}"
                ),
            )
        return RuleResult(passed=True, rule_name=self.name, reason="ok")


class MaxOrderRule(ExchangeRule):
    """Block orders above the exchange maximum order size."""

    def __init__(self, max_order_usd: float = 1_000_000.0) -> None:
        self._max = max_order_usd

    def evaluate(self, ctx: RuleContext) -> RuleResult:
        if ctx.usd_size > self._max:
            return RuleResult(
                passed=False,
                rule_name=self.name,
                reason=(
                    f"MAX_ORDER: ${ctx.usd_size:.2f} > max ${self._max:.2f} "
                    f"on {ctx.broker_name}"
                ),
            )
        return RuleResult(passed=True, rule_name=self.name, reason="ok")


class SymbolAllowlistRule(ExchangeRule):
    """Block orders on symbols not in the allowlist (empty = allow all)."""

    def __init__(self, allowed: Optional[List[str]] = None) -> None:
        self._allowed: frozenset = (
            frozenset(s.upper() for s in allowed) if allowed else frozenset()
        )

    def evaluate(self, ctx: RuleContext) -> RuleResult:
        if not self._allowed:
            return RuleResult(passed=True, rule_name=self.name, reason="no_allowlist")
        if ctx.symbol.upper() not in self._allowed:
            return RuleResult(
                passed=False,
                rule_name=self.name,
                reason=f"SYMBOL_NOT_ALLOWED: {ctx.symbol} not in allowlist",
            )
        return RuleResult(passed=True, rule_name=self.name, reason="ok")


class MicroCapBypassRule(ExchangeRule):
    """When micro_cap_enabled, allow orders below the normal min_order floor.

    Placed BEFORE MinOrderRule in the chain to short-circuit it for
    micro-cap mode brokers (Coinbase).
    """

    def __init__(self, micro_cap_enabled: bool) -> None:
        self._enabled = micro_cap_enabled

    def evaluate(self, ctx: RuleContext) -> RuleResult:
        if self._enabled:
            logger.debug(
                "MicroCapBypassRule: skipping size floor for %s (micro_cap_enabled)",
                ctx.broker_name,
            )
            return RuleResult(
                passed=True,
                rule_name=self.name,
                reason="MICRO_CAP_BYPASS",
                skip_remaining=False,   # other rules (isolation, symbol) still run
            )
        return RuleResult(passed=True, rule_name=self.name, reason="not_micro_cap")


# ---------------------------------------------------------------------------
# Rule chain
# ---------------------------------------------------------------------------

class RuleChain:
    """Ordered sequence of rules evaluated left-to-right.

    Parameters
    ----------
    broker_name:
        Used in log messages.
    stop_on_fail:
        When *True* (default) the chain stops at the first failing rule.
    """

    def __init__(
        self,
        broker_name: str,
        rules: Optional[List[ExchangeRule]] = None,
        stop_on_fail: bool = True,
    ) -> None:
        self._broker = broker_name
        self._rules: List[ExchangeRule] = list(rules or [])
        self._stop_on_fail = stop_on_fail

    def add(self, rule: ExchangeRule) -> "RuleChain":
        """Append *rule* and return self for chaining."""
        self._rules.append(rule)
        return self

    def evaluate(self, ctx: RuleContext) -> RuleResult:
        """Run all rules and return the first failure, or a final pass."""
        for rule in self._rules:
            result = rule.evaluate(ctx)
            result.rule_name = rule.name  # ensure name is set
            if result.skip_remaining:
                logger.debug(
                    "RuleChain[%s]: %s → skip_remaining (%s)",
                    self._broker, rule.name, result.reason,
                )
                return result
            if not result.passed:
                logger.info(
                    "RuleChain[%s]: %s → FAIL (%s)",
                    self._broker, rule.name, result.reason,
                )
                if self._stop_on_fail:
                    return result
        return RuleResult(
            passed=True,
            rule_name="ALL_RULES",
            reason=f"{len(self._rules)} rules passed",
        )


# ---------------------------------------------------------------------------
# Rule chain factory
# ---------------------------------------------------------------------------

class ExchangeRuleEngine:
    """Builds and stores per-exchange rule chains.

    Chains are built once from :data:`BROKER_PROFILES` and cached.
    Call :meth:`evaluate` to run the chain for any (broker, order) pair.
    """

    def __init__(self) -> None:
        self._chains: Dict[str, RuleChain] = {}
        self._lock = threading.Lock()
        self._build_all()

    def _build_all(self) -> None:
        try:
            from bot.broker_profiles import BROKER_PROFILES
        except ImportError:
            from broker_profiles import BROKER_PROFILES  # type: ignore[no-redef]

        try:
            from bot.coinbase_controller import COINBASE_MICRO_CAP_SYMBOLS
        except ImportError:
            try:
                from coinbase_controller import COINBASE_MICRO_CAP_SYMBOLS  # type: ignore
            except ImportError:
                COINBASE_MICRO_CAP_SYMBOLS = []

        for name, profile in BROKER_PROFILES.items():
            self._chains[name] = self._build_chain(name, profile, COINBASE_MICRO_CAP_SYMBOLS)

    @staticmethod
    def _build_chain(
        name: str,
        profile: dict,
        coinbase_symbols: list,
    ) -> RuleChain:
        chain = RuleChain(broker_name=name)

        # 1. SELL always bypasses remaining rules
        chain.add(ForceSellBypassRule())

        # 2. Global emergency buy guard
        chain.add(GlobalBuyGuardRule())

        # 3. Broker isolation gate (blocks BUY for isolated/passive/disabled)
        chain.add(IsolationRule())

        # 4. Micro-cap bypass (skips min-order floor for micro-cap brokers)
        chain.add(MicroCapBypassRule(profile.get("micro_cap_enabled", False)))

        # 5. Minimum order size
        chain.add(MinOrderRule(profile.get("min_order_usd", 1.0)))

        # 6. Maximum order size
        chain.add(MaxOrderRule())

        # 7. Capital floor (only enforced when ignore_global_capital_floor is False)
        if not profile.get("ignore_global_capital_floor", False):
            chain.add(CapitalFloorRule(profile.get("min_capital_usd", 1.0)))

        # 8. Symbol allowlist (Coinbase: micro-cap universe only)
        if name == "coinbase" and coinbase_symbols:
            chain.add(SymbolAllowlistRule(coinbase_symbols))

        return chain

    def evaluate(
        self,
        broker_name: str,
        ctx: RuleContext,
    ) -> RuleResult:
        """Evaluate the rule chain for *broker_name* against *ctx*."""
        chain = self._chains.get(broker_name.lower())
        if chain is None:
            # Unknown broker: build a permissive passthrough chain
            chain = RuleChain(broker_name=broker_name)
            chain.add(ForceSellBypassRule())
            chain.add(GlobalBuyGuardRule())
        return chain.evaluate(ctx)

    def get_chain(self, broker_name: str) -> Optional[RuleChain]:
        return self._chains.get(broker_name.lower())

    def rebuild(self) -> None:
        """Rebuild all chains (call after changing BROKER_PROFILES at runtime)."""
        with self._lock:
            self._build_all()


# ---------------------------------------------------------------------------
# Module-level singleton + convenience function
# ---------------------------------------------------------------------------

_engine: Optional[ExchangeRuleEngine] = None
_engine_lock = threading.Lock()


def get_rule_engine() -> ExchangeRuleEngine:
    """Return (or create) the process-wide :class:`ExchangeRuleEngine`."""
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                _engine = ExchangeRuleEngine()
    return _engine


def build_default_chain(broker_name: str) -> RuleChain:
    """Convenience: return the pre-built chain for *broker_name*."""
    return get_rule_engine().get_chain(broker_name) or RuleChain(broker_name)
