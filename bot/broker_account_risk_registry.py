"""Per-broker-account risk-engine registry for NIJA.

Trading accounts share only explicitly global safety infrastructure (writer
coordination and final execution authority). Mutable balance, peak balance,
exposure and portfolio-correlation risk state live inside one account scope.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger("nija.broker_account_risk")


@dataclass(frozen=True)
class RiskScope:
    broker_name: str
    account_scope: str

    @property
    def key(self) -> Tuple[str, str]:
        return self.broker_name, self.account_scope


def _normalize(value: Any, default: str) -> str:
    text = str(value or "").strip().lower()
    return text or default


def _scope(broker_name: str, account_scope: str = "") -> RiskScope:
    return RiskScope(
        broker_name=_normalize(broker_name, "unknown"),
        account_scope=_normalize(account_scope, "platform"),
    )


class BrokerAccountRiskRegistry:
    """Own exactly one mutable RiskEngine per broker/account scope."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._engines: Dict[Tuple[str, str], Any] = {}

    def _new_engine(self, scope: RiskScope):
        from bot.risk_engine import CapitalFloor, RiskEngine

        try:
            from bot.broker_isolation_registry import get_broker_isolation_registry
            cell = get_broker_isolation_registry().get_or_default(scope.broker_name)
            max_position_pct = float(cell.risk.max_position_pct)
            floor_usd = max(0.0, float(cell.capital.min_capital_usd))
        except Exception:
            max_position_pct = 0.20
            floor_usd = 1.0

        floor = CapitalFloor(
            floor_usd=floor_usd,
            warning_usd=max(floor_usd, floor_usd * 1.5),
        )
        engine = RiskEngine(
            capital_floor=floor,
            max_single_position_pct=max(0.001, min(max_position_pct, 0.50)),
            max_total_exposure_pct=0.80,
        )

        # RiskEngine historically wires process singletons. Replace mutable
        # portfolio/account subsystems with scope-local instances. The final
        # execution pipeline still enforces global emergency/writer authority.
        try:
            from bot.portfolio_risk_engine import PortfolioRiskEngine
            engine._pre = PortfolioRiskEngine()
        except Exception as exc:
            engine._pre = None
            logger.warning(
                "BROKER_ACCOUNT_RISK_PRE_UNAVAILABLE scope=%s:%s error=%s:%s",
                scope.broker_name,
                scope.account_scope,
                type(exc).__name__,
                exc,
            )

        try:
            from bot.risk_intelligence_gate import RiskIntelligenceGate
            engine._rig = RiskIntelligenceGate(portfolio_risk_engine=engine._pre)
        except Exception:
            engine._rig = None

        try:
            from bot.liquidity_risk_gate import LiquidityRiskGate
            engine._lrg = LiquidityRiskGate()
        except Exception:
            engine._lrg = None

        try:
            from bot.asset_exposure_correlation_gate import AssetExposureCorrelationGate
            engine._aecg = AssetExposureCorrelationGate()
        except Exception:
            engine._aecg = None

        # The old GlobalRiskController singleton carries account balance and
        # streak state across the entire process. Do not let those mutable
        # values bleed into a broker-account risk cell. Global emergency stops
        # remain enforced downstream by the execution authority / kill-switch
        # boundary, independently of this sizing gate.
        engine._grc = None

        # AutoTuningAILayer also owns process-wide performance state. Market
        # regime can remain shared market intelligence, but performance sizing
        # must not borrow another account's win/loss history.
        try:
            engine._sizer._ata = None
        except Exception:
            pass

        setattr(engine, "nija_broker_name", scope.broker_name)
        setattr(engine, "nija_account_scope", scope.account_scope)
        logger.critical(
            "BROKER_ACCOUNT_RISK_ENGINE_CREATED broker=%s account=%s engine_id=%s "
            "shared_balance=false shared_exposure=false shared_performance=false",
            scope.broker_name,
            scope.account_scope,
            id(engine),
        )
        return engine

    def get_engine(
        self,
        broker_name: str,
        account_scope: str = "",
        balance: Optional[float] = None,
    ):
        scope = _scope(broker_name, account_scope)
        with self._lock:
            engine = self._engines.get(scope.key)
            if engine is None:
                engine = self._new_engine(scope)
                self._engines[scope.key] = engine

        if balance is not None:
            try:
                parsed = float(balance)
            except (TypeError, ValueError, OverflowError):
                parsed = 0.0
            if parsed > 0:
                engine.update_balance(parsed)
        return engine

    def drop(self, broker_name: str, account_scope: str = "") -> None:
        scope = _scope(broker_name, account_scope)
        with self._lock:
            self._engines.pop(scope.key, None)

    def snapshot(self) -> Dict[str, Dict[str, Any]]:
        with self._lock:
            items = list(self._engines.items())
        result: Dict[str, Dict[str, Any]] = {}
        for (broker, account), engine in items:
            try:
                status = engine.get_status()
            except Exception:
                status = {}
            result[f"{broker}:{account}"] = {
                "broker": broker,
                "account": account,
                "engine_id": id(engine),
                "capital": status.get("capital", {}),
                "config": status.get("config", {}),
            }
        return result


_registry: Optional[BrokerAccountRiskRegistry] = None
_registry_lock = threading.Lock()


def get_broker_account_risk_registry() -> BrokerAccountRiskRegistry:
    global _registry
    if _registry is None:
        with _registry_lock:
            if _registry is None:
                _registry = BrokerAccountRiskRegistry()
    return _registry


def get_broker_account_risk_engine(
    broker_name: str,
    account_scope: str = "",
    balance: Optional[float] = None,
):
    return get_broker_account_risk_registry().get_engine(
        broker_name=broker_name,
        account_scope=account_scope,
        balance=balance,
    )


__all__ = [
    "RiskScope",
    "BrokerAccountRiskRegistry",
    "get_broker_account_risk_registry",
    "get_broker_account_risk_engine",
]
