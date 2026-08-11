"""
NIJA Per-Exchange Risk Plugins
================================

Each plugin implements ``evaluate(context) -> RiskResult`` for one broker.
Plugins are pure functions with no side effects beyond logging.

Built-in plugins
----------------
ActiveRiskPlugin    Full fail-closed evaluation via the existing risk engine
BypassRiskPlugin    Compatibility alias that preserves active evaluation
IsolatedRiskPlugin  Compatibility alias that preserves active evaluation
DisabledRiskPlugin  Always fails entry — PASSIVE / DISABLED brokers

Factory
-------
    from bot.risk_plugin_base import RiskPluginFactory, RiskContext
    plugin = RiskPluginFactory.for_policy("micro_cap")
    result = plugin.evaluate(RiskContext(score=0.8, symbol="ADA-USD", side="buy"))
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass

logger = logging.getLogger("nija.risk_plugin")


# ---------------------------------------------------------------------------
# Data structures (re-exported so callers only need this module)
# ---------------------------------------------------------------------------

@dataclass
class RiskContext:
    """Input context for a per-broker risk evaluation."""
    score: float
    symbol: str = ""
    side: str = "buy"
    size_usd: float = 0.0
    broker_name: str = ""
    balance: float = 0.0


@dataclass
class RiskResult:
    """Outcome of a per-broker risk evaluation."""
    passed: bool
    score: float
    reason: str = ""


# ---------------------------------------------------------------------------
# Plugin ABC
# ---------------------------------------------------------------------------

class RiskPlugin(ABC):
    """Per-exchange risk evaluation strategy."""

    @abstractmethod
    def evaluate(self, context: RiskContext) -> RiskResult:
        """Evaluate risk for *context* and return a :class:`RiskResult`."""


# ---------------------------------------------------------------------------
# Built-in plugins
# ---------------------------------------------------------------------------

class ActiveRiskPlugin(RiskPlugin):
    """Full risk evaluation that fails closed for new entries."""

    def evaluate(self, context: RiskContext) -> RiskResult:
        try:
            from bot.risk_engine import get_risk_engine
            engine = get_risk_engine()
            if engine is None:
                raise RuntimeError("risk engine unavailable")
            if context.balance <= 0 or context.size_usd <= 0:
                raise RuntimeError("positive balance and order size are required")
            result = engine.gate_trade(
                symbol=context.symbol,
                side=context.side,
                raw_size_usd=context.size_usd,
                portfolio_value=context.balance,
            )
            if not result.approved:
                return RiskResult(
                    passed=False,
                    score=context.score,
                    reason=f"RISK_ENGINE: {result.reason}",
                )
        except Exception as exc:
            if str(context.side or "").lower() in {"sell", "exit", "close"}:
                logger.warning(
                    "ActiveRiskPlugin: protective exit allowed while risk engine "
                    "is unavailable (%s)",
                    exc,
                )
                return RiskResult(
                    passed=True,
                    score=context.score,
                    reason="PROTECTIVE_EXIT_RISK_ENGINE_UNAVAILABLE",
                )
            logger.error("ActiveRiskPlugin: entry rejected (%s)", exc)
            return RiskResult(
                passed=False,
                score=context.score,
                reason=f"RISK_ENGINE_UNAVAILABLE: {exc}",
            )

        return RiskResult(passed=True, score=context.score, reason="ACTIVE_PASS")


class BypassRiskPlugin(RiskPlugin):
    """Backward-compatible name that no longer bypasses live risk."""

    def evaluate(self, context: RiskContext) -> RiskResult:
        logger.warning("BypassRiskPlugin compatibility path uses active risk")
        return ActiveRiskPlugin().evaluate(context)


class IsolatedRiskPlugin(RiskPlugin):
    """Backward-compatible name that no longer makes risk log-only."""

    def evaluate(self, context: RiskContext) -> RiskResult:
        logger.warning("IsolatedRiskPlugin compatibility path uses active risk")
        return ActiveRiskPlugin().evaluate(context)


class DisabledRiskPlugin(RiskPlugin):
    """Always fails — used for PASSIVE / DISABLED brokers.

    Any call to this plugin means execution was attempted on a broker
    that should never receive orders.  The result is always ``passed=False``
    so the compliance engine rejects the order before it reaches the broker.
    """

    def evaluate(self, context: RiskContext) -> RiskResult:
        logger.warning(
            "🔴 DisabledRiskPlugin [%s]: order rejected — broker PASSIVE/DISABLED",
            context.broker_name,
        )
        return RiskResult(
            passed=False,
            score=context.score,
            reason=f"BROKER_DISABLED: {context.broker_name}",
        )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

class RiskPluginFactory:
    """Maps isolation-policy strings to the correct :class:`RiskPlugin`."""

    _MAP = {
        "active":    ActiveRiskPlugin,
        "micro_cap": ActiveRiskPlugin,
        "bypass":    ActiveRiskPlugin,
        "isolated":  ActiveRiskPlugin,
        "passive":   DisabledRiskPlugin,
        "disabled":  DisabledRiskPlugin,
    }

    @classmethod
    def for_policy(cls, policy: str) -> RiskPlugin:
        """Return a plugin instance for *policy* (case-insensitive)."""
        klass = cls._MAP.get(policy.lower(), ActiveRiskPlugin)
        return klass()

    @classmethod
    def for_broker(cls, broker_name: str) -> RiskPlugin:
        """Return the correct plugin for *broker_name* using BROKER_PROFILES."""
        try:
            from bot.broker_profiles import get_broker_profile
        except ImportError:
            from broker_profiles import get_broker_profile  # type: ignore
        profile = get_broker_profile(broker_name)
        risk_mode = profile.get("risk_mode", "active")
        return cls.for_policy(risk_mode)
