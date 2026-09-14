"""NIJA broker-cell isolation registry.

A broker cell is the hard fault/risk/account boundary for one venue.  Cells
share read-only observability but do not share execution state, circuit-breaker
state, user membership, strategy selection or broker shutdown state.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set

logger = logging.getLogger("nija.broker_isolation_registry")


class IsolationPolicy(Enum):
    ACTIVE = "active"
    MICRO_CAP = "micro_cap"
    ISOLATED = "isolated"
    PASSIVE = "passive"
    DISABLED = "disabled"

    @classmethod
    def entry_allowed(cls):
        return frozenset({cls.ACTIVE, cls.MICRO_CAP})

    @classmethod
    def exit_allowed(cls):
        return frozenset({cls.ACTIVE, cls.MICRO_CAP, cls.ISOLATED})

    @classmethod
    def execution_blocked(cls):
        return frozenset({cls.PASSIVE, cls.DISABLED})


class CellHealth(Enum):
    READY = "ready"
    DEGRADED = "degraded"
    HALTED = "halted"
    DISABLED = "disabled"


@dataclass(frozen=True)
class CapitalProfile:
    min_capital_usd: float = 1.0
    min_order_usd: float = 1.0
    include_in_execution_capital: bool = True
    ignore_global_capital_floor: bool = False
    base_execution_weight: float = 1.0


@dataclass(frozen=True)
class RiskProfile:
    max_positions: int = 5
    max_position_pct: float = 0.20
    max_daily_loss_pct: float = 0.03
    stop_loss_pct: float = 0.01
    risk_mode: str = "active"


@dataclass(frozen=True)
class StrategyProfile:
    strategy_name: str = "broker_default"
    config_class: str = ""
    bidirectional: bool = False
    max_hold_hours: float = 12.0


@dataclass
class BrokerCellState:
    health: CellHealth = CellHealth.READY
    halted_reason: str = ""
    consecutive_failures: int = 0
    last_failure: str = ""
    last_failure_ts: float = 0.0
    last_success_ts: float = 0.0
    users: Set[str] = field(default_factory=set)


@dataclass
class IsolationEntry:
    """Complete immutable policy + mutable state for exactly one broker cell."""
    broker_name: str
    policy: IsolationPolicy
    capital: CapitalProfile = field(default_factory=CapitalProfile)
    risk: RiskProfile = field(default_factory=RiskProfile)
    strategy: StrategyProfile = field(default_factory=StrategyProfile)
    symbol_filter: Optional[Callable[[List[str]], List[str]]] = None
    description: str = ""
    state: BrokerCellState = field(default_factory=BrokerCellState)

    def is_entry_allowed(self) -> bool:
        return self.policy in IsolationPolicy.entry_allowed() and self.state.health not in {CellHealth.HALTED, CellHealth.DISABLED}

    def is_exit_allowed(self) -> bool:
        return self.policy in IsolationPolicy.exit_allowed()

    def skip_execution(self) -> bool:
        return self.policy in IsolationPolicy.execution_blocked() or self.state.health in {CellHealth.HALTED, CellHealth.DISABLED}

    def skip_risk_gate(self) -> bool:
        return False

    def log_risk_only(self) -> bool:
        return False

    def filter_symbols(self, candidates: List[str]) -> List[str]:
        return candidates if self.symbol_filter is None else self.symbol_filter(candidates)


class BrokerIsolationRegistry:
    """Thread-safe collection of independent broker cells."""

    def __init__(self) -> None:
        self._entries: Dict[str, IsolationEntry] = {}
        self._lock = threading.RLock()
        self._initialize_defaults()

    @staticmethod
    def _policy(name: str, profile: Dict[str, Any], coinbase_micro: bool, kraken_disabled: bool) -> IsolationPolicy:
        mode = str(profile.get("execution_mode", "passive")).lower()
        if name == "coinbase" and coinbase_micro:
            return IsolationPolicy.MICRO_CAP
        if name == "kraken" and kraken_disabled:
            return IsolationPolicy.PASSIVE
        return {
            "active": IsolationPolicy.ACTIVE,
            "micro_cap": IsolationPolicy.MICRO_CAP,
            "isolated": IsolationPolicy.ISOLATED,
            "passive": IsolationPolicy.PASSIVE,
            "disabled": IsolationPolicy.DISABLED,
        }.get(mode, IsolationPolicy.PASSIVE)

    def _initialize_defaults(self) -> None:
        try:
            from bot.broker_profiles import BROKER_PROFILES, COINBASE_MICRO_CAP_MODE, KRAKEN_EXECUTION_DISABLED
        except ImportError:
            from broker_profiles import BROKER_PROFILES, COINBASE_MICRO_CAP_MODE, KRAKEN_EXECUTION_DISABLED  # type: ignore[import]

        try:
            from bot.broker_configs.strategy_selector import STRATEGY_SELECTOR
        except ImportError:
            try:
                from broker_configs.strategy_selector import STRATEGY_SELECTOR  # type: ignore[import]
            except ImportError:
                STRATEGY_SELECTOR = None  # type: ignore[assignment]

        for name, profile in BROKER_PROFILES.items():
            policy = self._policy(name, profile, COINBASE_MICRO_CAP_MODE, KRAKEN_EXECUTION_DISABLED)
            config = STRATEGY_SELECTOR.get_config(name) if STRATEGY_SELECTOR is not None else None
            symbol_filter = None
            if name == "coinbase":
                try:
                    from bot.coinbase_controller import get_coinbase_controller
                    symbol_filter = get_coinbase_controller().filter_symbols
                except Exception:
                    symbol_filter = None

            health = CellHealth.DISABLED if policy == IsolationPolicy.DISABLED else CellHealth.READY
            entry = IsolationEntry(
                broker_name=name,
                policy=policy,
                capital=CapitalProfile(
                    min_capital_usd=float(profile.get("min_capital_usd", 1.0)),
                    min_order_usd=float(profile.get("min_order_usd", 1.0)),
                    include_in_execution_capital=bool(profile.get("include_in_execution_capital", True)),
                    ignore_global_capital_floor=bool(profile.get("ignore_global_capital_floor", False)),
                    base_execution_weight=float(profile.get("base_execution_weight", 1.0)),
                ),
                risk=RiskProfile(
                    max_positions=int(profile.get("max_positions", getattr(config, "max_positions", 5) or 5)),
                    max_position_pct=float(profile.get("max_position_pct", 0.20)),
                    max_daily_loss_pct=float(profile.get("max_daily_loss_pct", 0.03)),
                    stop_loss_pct=abs(float(profile.get("stop_loss_pct", getattr(config, "stop_loss", -0.01) or -0.01))),
                    risk_mode=str(profile.get("risk_mode", "active")),
                ),
                strategy=StrategyProfile(
                    strategy_name=str(profile.get("strategy_name", name + "_strategy")),
                    config_class=type(config).__name__ if config is not None else "",
                    bidirectional=bool(getattr(config, "bidirectional", False)),
                    max_hold_hours=float(getattr(config, "max_hold_hours", 12.0) or 12.0),
                ),
                symbol_filter=symbol_filter,
                description=f"Broker cell {name} ({policy.value})",
                state=BrokerCellState(health=health),
            )
            self._entries[name] = entry

        logger.info(
            "BROKER_CELL_REGISTRY_READY count=%d cells=%s shared_execution_state=false",
            len(self._entries),
            ",".join(f"{n}:{e.policy.value}" for n, e in sorted(self._entries.items())),
        )

    def register(self, entry: IsolationEntry) -> None:
        with self._lock:
            self._entries[entry.broker_name.lower()] = entry
        logger.info("BROKER_CELL_UPDATED broker=%s policy=%s", entry.broker_name, entry.policy.value)

    def get(self, broker_name: str) -> Optional[IsolationEntry]:
        with self._lock:
            return self._entries.get(str(broker_name).lower())

    def get_or_default(self, broker_name: str) -> IsolationEntry:
        """Unknown brokers fail closed rather than inheriting live authority."""
        found = self.get(broker_name)
        if found is not None:
            return found
        return IsolationEntry(
            broker_name=str(broker_name).lower(),
            policy=IsolationPolicy.DISABLED,
            description="unregistered broker cell — fail closed",
            state=BrokerCellState(health=CellHealth.DISABLED, halted_reason="unregistered_broker"),
        )

    def register_user(self, broker_name: str, user_id: str) -> bool:
        with self._lock:
            entry = self._entries.get(str(broker_name).lower())
            if entry is None:
                return False
            entry.state.users.add(str(user_id))
            return True

    def unregister_user(self, broker_name: str, user_id: str) -> bool:
        with self._lock:
            entry = self._entries.get(str(broker_name).lower())
            if entry is None:
                return False
            entry.state.users.discard(str(user_id))
            return True

    def halt_cell(self, broker_name: str, reason: str) -> bool:
        """Halt one broker only. Protective exits remain policy-eligible."""
        with self._lock:
            entry = self._entries.get(str(broker_name).lower())
            if entry is None:
                return False
            entry.state.health = CellHealth.HALTED
            entry.state.halted_reason = str(reason)[:240]
            logger.critical("BROKER_CELL_HALTED broker=%s reason=%s global_shutdown=false", broker_name, entry.state.halted_reason)
            return True

    def resume_cell(self, broker_name: str) -> bool:
        with self._lock:
            entry = self._entries.get(str(broker_name).lower())
            if entry is None or entry.policy == IsolationPolicy.DISABLED:
                return False
            entry.state.health = CellHealth.READY
            entry.state.halted_reason = ""
            entry.state.consecutive_failures = 0
            return True

    def record_failure(self, broker_name: str, reason: str, halt_after: int = 5) -> bool:
        """Record a failure only inside the named cell; returns whether it halted."""
        with self._lock:
            entry = self._entries.get(str(broker_name).lower())
            if entry is None:
                return False
            entry.state.consecutive_failures += 1
            entry.state.last_failure = str(reason)[:240]
            entry.state.last_failure_ts = time.time()
            if entry.state.health != CellHealth.HALTED:
                entry.state.health = CellHealth.DEGRADED
            if halt_after > 0 and entry.state.consecutive_failures >= halt_after:
                entry.state.health = CellHealth.HALTED
                entry.state.halted_reason = f"circuit_breaker:{entry.state.last_failure}"
                logger.critical("BROKER_CELL_CIRCUIT_OPEN broker=%s failures=%d other_cells_affected=false", broker_name, entry.state.consecutive_failures)
                return True
            return False

    def record_success(self, broker_name: str) -> bool:
        with self._lock:
            entry = self._entries.get(str(broker_name).lower())
            if entry is None:
                return False
            entry.state.last_success_ts = time.time()
            entry.state.consecutive_failures = 0
            if entry.state.health == CellHealth.DEGRADED:
                entry.state.health = CellHealth.READY
            return True

    def get_active_entries(self) -> List[IsolationEntry]:
        with self._lock:
            return [e for e in self._entries.values() if e.is_entry_allowed()]

    def get_execution_eligible(self) -> List[IsolationEntry]:
        with self._lock:
            return [e for e in self._entries.values() if not e.skip_execution()]

    def get_capital_eligible(self) -> List[IsolationEntry]:
        with self._lock:
            return [e for e in self._entries.values() if e.capital.include_in_execution_capital]

    def apply_to_broker(self, broker) -> None:
        name = _broker_name(broker)
        entry = self.get_or_default(name)
        if entry.skip_execution():
            broker.exit_only_mode = True
            broker.mode = "PASSIVE"
        elif entry.policy == IsolationPolicy.ISOLATED:
            broker.exit_only_mode = True
        else:
            broker.exit_only_mode = False
        try:
            broker.nija_broker_cell = name
        except Exception:
            pass

    def apply_to_all_brokers(self, broker_manager) -> None:
        for _broker_type, broker in getattr(broker_manager, "brokers", {}).items():
            self.apply_to_broker(broker)

    def check_execution(self, broker_name: str, side: str) -> Optional[Dict]:
        entry = self.get_or_default(broker_name)
        side_lower = str(side).lower()
        if entry.skip_execution():
            # A halted cell still permits SELL/protective exits when its policy does.
            if side_lower in {"sell", "close", "exit"} and entry.is_exit_allowed():
                return None
            logger.warning("BROKER_CELL_EXECUTION_BLOCK broker=%s side=%s health=%s", broker_name, side_lower, entry.state.health.value)
            return dict(_SKIP_RESULT, broker_cell=entry.broker_name, reason=entry.state.halted_reason or entry.policy.value)
        if side_lower == "buy" and not entry.is_entry_allowed():
            return dict(_SKIP_RESULT, broker_cell=entry.broker_name, reason="entry_not_allowed")
        return None

    def snapshot(self) -> Dict[str, Dict[str, Any]]:
        """Independent per-cell telemetry for dashboards/accounting."""
        with self._lock:
            return {
                name: {
                    "policy": entry.policy.value,
                    "health": entry.state.health.value,
                    "halted_reason": entry.state.halted_reason,
                    "consecutive_failures": entry.state.consecutive_failures,
                    "users": sorted(entry.state.users),
                    "strategy": entry.strategy.strategy_name,
                    "strategy_config": entry.strategy.config_class,
                    "risk_mode": entry.risk.risk_mode,
                    "max_positions": entry.risk.max_positions,
                    "min_capital_usd": entry.capital.min_capital_usd,
                    "min_order_usd": entry.capital.min_order_usd,
                }
                for name, entry in sorted(self._entries.items())
            }


_SKIP_RESULT: Dict[str, Any] = {
    "status": "broker_isolated_skip",
    "partial_fill": False,
    "filled_pct": 0.0,
}


def _broker_name(broker) -> str:
    if isinstance(broker, str):
        return broker.lower()
    bt = getattr(broker, "broker_type", None)
    if bt is not None:
        value = getattr(bt, "value", None)
        if value is not None:
            return str(value).lower()
    name = getattr(broker, "broker_name", None) or getattr(broker, "NAME", None)
    if name:
        return str(name).lower()
    return type(broker).__name__.replace("Broker", "").lower()


_instance: Optional[BrokerIsolationRegistry] = None
_instance_lock = threading.Lock()


def get_broker_isolation_registry() -> BrokerIsolationRegistry:
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = BrokerIsolationRegistry()
    return _instance
