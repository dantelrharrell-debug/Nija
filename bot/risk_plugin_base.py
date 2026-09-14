"""NIJA per-exchange risk plugins.

Every live entry uses active fail-closed risk evaluation. Mutable risk state is
scoped to one broker/account pair so balances, drawdown and exposure cannot
bleed between brokerages or users.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass

logger = logging.getLogger("nija.risk_plugin")


@dataclass
class RiskContext:
    """Input context for a per-broker, per-account risk evaluation."""
    score: float
    symbol: str = ""
    side: str = "buy"
    size_usd: float = 0.0
    broker_name: str = ""
    balance: float = 0.0
    account_scope: str = "platform"


@dataclass
class RiskResult:
    passed: bool
    score: float
    reason: str = ""


class RiskPlugin(ABC):
    @abstractmethod
    def evaluate(self, context: RiskContext) -> RiskResult:
        """Evaluate risk for *context*."""


class ActiveRiskPlugin(RiskPlugin):
    """Full account-scoped risk evaluation that fails closed for entries."""

    def evaluate(self, context: RiskContext) -> RiskResult:
        try:
            from bot.broker_account_risk_registry import get_broker_account_risk_engine

            if context.balance <= 0 or context.size_usd <= 0:
                raise RuntimeError("positive balance and order size are required")
            broker_name = str(context.broker_name or "unknown").strip().lower()
            account_scope = str(context.account_scope or "platform").strip().lower()
            engine = get_broker_account_risk_engine(
                broker_name=broker_name,
                account_scope=account_scope,
                balance=context.balance,
            )
            if engine is None:
                raise RuntimeError("account-scoped risk engine unavailable")
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
                    reason=(
                        f"RISK_ENGINE[{broker_name}:{account_scope}]: {result.reason}"
                    ),
                )
        except Exception as exc:
            if str(context.side or "").lower() in {"sell", "exit", "close"}:
                logger.warning(
                    "ActiveRiskPlugin: protective exit allowed while scoped risk "
                    "engine is unavailable (%s)",
                    exc,
                )
                return RiskResult(
                    passed=True,
                    score=context.score,
                    reason="PROTECTIVE_EXIT_RISK_ENGINE_UNAVAILABLE",
                )
            logger.error(
                "ActiveRiskPlugin: entry rejected broker=%s account=%s (%s)",
                context.broker_name,
                context.account_scope,
                exc,
            )
            return RiskResult(
                passed=False,
                score=context.score,
                reason=f"RISK_ENGINE_UNAVAILABLE: {exc}",
            )

        return RiskResult(
            passed=True,
            score=context.score,
            reason=f"ACTIVE_PASS:{context.broker_name}:{context.account_scope or 'platform'}",
        )


class BypassRiskPlugin(RiskPlugin):
    """Compatibility name; live risk is never bypassed."""

    def evaluate(self, context: RiskContext) -> RiskResult:
        logger.warning("BypassRiskPlugin compatibility path uses active scoped risk")
        return ActiveRiskPlugin().evaluate(context)


class IsolatedRiskPlugin(RiskPlugin):
    """Compatibility name; isolated brokers still use active risk."""

    def evaluate(self, context: RiskContext) -> RiskResult:
        logger.warning("IsolatedRiskPlugin compatibility path uses active scoped risk")
        return ActiveRiskPlugin().evaluate(context)


class DisabledRiskPlugin(RiskPlugin):
    """Always rejects entries for PASSIVE / DISABLED brokers."""

    def evaluate(self, context: RiskContext) -> RiskResult:
        logger.warning(
            "DisabledRiskPlugin [%s]: order rejected - broker PASSIVE/DISABLED",
            context.broker_name,
        )
        return RiskResult(
            passed=False,
            score=context.score,
            reason=f"BROKER_DISABLED: {context.broker_name}",
        )


class RiskPluginFactory:
    _MAP = {
        "active": ActiveRiskPlugin,
        "micro_cap": ActiveRiskPlugin,
        "bypass": ActiveRiskPlugin,
        "isolated": ActiveRiskPlugin,
        "passive": DisabledRiskPlugin,
        "disabled": DisabledRiskPlugin,
    }

    @classmethod
    def for_policy(cls, policy: str) -> RiskPlugin:
        klass = cls._MAP.get(str(policy or "active").lower(), ActiveRiskPlugin)
        return klass()

    @classmethod
    def for_broker(cls, broker_name: str) -> RiskPlugin:
        try:
            from bot.broker_profiles import get_broker_profile
        except ImportError:
            from broker_profiles import get_broker_profile  # type: ignore[import]
        profile = get_broker_profile(broker_name)
        risk_mode = profile.get("risk_mode", "active")
        return cls.for_policy(risk_mode)
