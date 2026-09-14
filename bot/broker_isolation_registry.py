"""NIJA broker-cell isolation registry.

A broker cell is the hard fault/risk/account boundary for one venue. Cells
share read-only observability but do not share execution state, circuit-breaker
state, user membership, strategy selection, shutdown state, or capital state.
"""
from __future__ import annotations

import copy
import logging
import sys
import threading
import time
import weakref
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

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
    """Complete policy + state for exactly one broker cell."""
    broker_name: str
    policy: IsolationPolicy
    capital: CapitalProfile = field(default_factory=CapitalProfile)
    risk: RiskProfile = field(default_factory=RiskProfile)
    strategy: StrategyProfile = field(default_factory=StrategyProfile)
    symbol_filter: Optional[Callable[[List[str]], List[str]]] = None
    description: str = ""
    state: BrokerCellState = field(default_factory=BrokerCellState)

    def is_entry_allowed(self) -> bool:
        return self.policy in IsolationPolicy.entry_allowed() and self.state.health not in {
            CellHealth.HALTED,
            CellHealth.DISABLED,
        }

    def is_exit_allowed(self) -> bool:
        return self.policy in IsolationPolicy.exit_allowed()

    def skip_execution(self) -> bool:
        return self.policy in IsolationPolicy.execution_blocked() or self.state.health in {
            CellHealth.HALTED,
            CellHealth.DISABLED,
        }

    def skip_risk_gate(self) -> bool:
        return False

    def log_risk_only(self) -> bool:
        return False

    def filter_symbols(self, candidates: List[str]) -> List[str]:
        return candidates if self.symbol_filter is None else self.symbol_filter(candidates)


def _copy_entry(entry: IsolationEntry) -> IsolationEntry:
    """Return a detached read snapshot so callers cannot mutate registry state."""
    return IsolationEntry(
        broker_name=entry.broker_name,
        policy=entry.policy,
        capital=entry.capital,
        risk=entry.risk,
        strategy=entry.strategy,
        symbol_filter=entry.symbol_filter,
        description=entry.description,
        state=BrokerCellState(
            health=entry.state.health,
            halted_reason=entry.state.halted_reason,
            consecutive_failures=entry.state.consecutive_failures,
            last_failure=entry.state.last_failure,
            last_failure_ts=entry.state.last_failure_ts,
            last_success_ts=entry.state.last_success_ts,
            users=set(entry.state.users),
        ),
    )


class BrokerIsolationRegistry:
    """Thread-safe collection of independent broker cells."""

    def __init__(self) -> None:
        self._entries: Dict[str, IsolationEntry] = {}
        self._brokers: Dict[str, weakref.WeakSet[Any]] = {}
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
            self._entries[name] = IsolationEntry(
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

        logger.info(
            "BROKER_CELL_REGISTRY_READY count=%d cells=%s shared_execution_state=false",
            len(self._entries),
            ",".join(f"{n}:{e.policy.value}" for n, e in sorted(self._entries.items())),
        )

    def register(self, entry: IsolationEntry) -> None:
        name = entry.broker_name.lower()
        with self._lock:
            self._entries[name] = _copy_entry(entry)
        logger.info("BROKER_CELL_UPDATED broker=%s policy=%s", name, entry.policy.value)

    def get(self, broker_name: str) -> Optional[IsolationEntry]:
        """Return a detached snapshot; all mutation goes through registry methods."""
        with self._lock:
            entry = self._entries.get(str(broker_name).lower())
            return _copy_entry(entry) if entry is not None else None

    def get_or_default(self, broker_name: str) -> IsolationEntry:
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

    def _tracked_brokers(self, broker_name: str) -> List[Any]:
        with self._lock:
            tracked = self._brokers.get(str(broker_name).lower())
            return list(tracked) if tracked is not None else []

    def _reapply_tracked(self, broker_name: str) -> None:
        for broker in self._tracked_brokers(broker_name):
            try:
                self.apply_to_broker(broker)
            except Exception as exc:
                logger.warning("BROKER_CELL_REAPPLY_FAILED broker=%s error=%s:%s", broker_name, type(exc).__name__, exc)

    def halt_cell(self, broker_name: str, reason: str) -> bool:
        name = str(broker_name).lower()
        with self._lock:
            entry = self._entries.get(name)
            if entry is None or entry.policy == IsolationPolicy.DISABLED:
                return False
            entry.state.health = CellHealth.HALTED
            entry.state.halted_reason = str(reason)[:240]
        self._reapply_tracked(name)
        logger.critical("BROKER_CELL_HALTED broker=%s reason=%s global_shutdown=false", name, str(reason)[:240])
        return True

    def resume_cell(self, broker_name: str) -> bool:
        name = str(broker_name).lower()
        with self._lock:
            entry = self._entries.get(name)
            if entry is None or entry.policy == IsolationPolicy.DISABLED:
                return False
            entry.state.health = CellHealth.READY
            entry.state.halted_reason = ""
            entry.state.consecutive_failures = 0
            entry.state.last_failure = ""
        self._reapply_tracked(name)
        logger.info("BROKER_CELL_RESUMED broker=%s other_cells_affected=false", name)
        return True

    def record_failure(self, broker_name: str, reason: str, halt_after: int = 5) -> bool:
        name = str(broker_name).lower()
        halted = False
        with self._lock:
            entry = self._entries.get(name)
            if entry is None or entry.policy == IsolationPolicy.DISABLED:
                return False
            entry.state.consecutive_failures += 1
            entry.state.last_failure = str(reason)[:240]
            entry.state.last_failure_ts = time.time()
            if entry.state.health != CellHealth.HALTED:
                entry.state.health = CellHealth.DEGRADED
            if halt_after > 0 and entry.state.consecutive_failures >= halt_after and entry.state.health != CellHealth.HALTED:
                entry.state.health = CellHealth.HALTED
                entry.state.halted_reason = f"circuit_breaker:{entry.state.last_failure}"
                halted = True
        if halted:
            self._reapply_tracked(name)
            logger.critical(
                "BROKER_CELL_CIRCUIT_OPEN broker=%s other_cells_affected=false",
                name,
            )
        return halted

    def record_success(self, broker_name: str) -> bool:
        name = str(broker_name).lower()
        with self._lock:
            entry = self._entries.get(name)
            if entry is None or entry.policy == IsolationPolicy.DISABLED:
                return False
            entry.state.last_success_ts = time.time()
            entry.state.consecutive_failures = 0
            if entry.state.health == CellHealth.DEGRADED:
                entry.state.health = CellHealth.READY
            return True

    def get_active_entries(self) -> List[IsolationEntry]:
        with self._lock:
            return [_copy_entry(e) for e in self._entries.values() if e.is_entry_allowed()]

    def get_execution_eligible(self) -> List[IsolationEntry]:
        with self._lock:
            return [_copy_entry(e) for e in self._entries.values() if not e.skip_execution()]

    def get_capital_eligible(self) -> List[IsolationEntry]:
        with self._lock:
            return [_copy_entry(e) for e in self._entries.values() if e.capital.include_in_execution_capital]

    def apply_to_broker(self, broker: Any) -> None:
        name = _broker_name(broker)
        with self._lock:
            try:
                self._brokers.setdefault(name, weakref.WeakSet()).add(broker)
            except TypeError:
                pass
            entry = self._entries.get(name)
            entry_snapshot = _copy_entry(entry) if entry is not None else None

        if entry_snapshot is None:
            entry_snapshot = self.get_or_default(name)

        forced_by_cell = bool(getattr(broker, "_nija_cell_forced_passive", False))
        if entry_snapshot.skip_execution():
            broker.exit_only_mode = True
            if getattr(broker, "mode", None) != "PASSIVE":
                broker.mode = "PASSIVE"
                setattr(broker, "_nija_cell_forced_passive", True)
            elif not hasattr(broker, "_nija_cell_forced_passive"):
                setattr(broker, "_nija_cell_forced_passive", False)
        elif entry_snapshot.policy == IsolationPolicy.ISOLATED:
            broker.exit_only_mode = True
            if forced_by_cell:
                broker.mode = "ACTIVE"
                setattr(broker, "_nija_cell_forced_passive", False)
        else:
            broker.exit_only_mode = False
            if forced_by_cell:
                broker.mode = "ACTIVE"
                setattr(broker, "_nija_cell_forced_passive", False)

        try:
            broker.nija_broker_cell = name
        except Exception:
            pass

    def apply_to_all_brokers(self, broker_manager: Any) -> None:
        for _broker_type, broker in getattr(broker_manager, "brokers", {}).items():
            self.apply_to_broker(broker)

    def check_execution(self, broker_name: str, side: str) -> Optional[Dict]:
        entry = self.get_or_default(broker_name)
        side_lower = str(side).lower()
        if entry.skip_execution():
            if side_lower in {"sell", "close", "exit"} and entry.is_exit_allowed():
                return None
            logger.warning(
                "BROKER_CELL_EXECUTION_BLOCK broker=%s side=%s health=%s",
                broker_name,
                side_lower,
                entry.state.health.value,
            )
            return dict(
                _SKIP_RESULT,
                broker_cell=entry.broker_name,
                reason=entry.state.halted_reason or entry.policy.value,
            )
        if side_lower == "buy" and not entry.is_entry_allowed():
            return dict(_SKIP_RESULT, broker_cell=entry.broker_name, reason="entry_not_allowed")
        return None

    def snapshot(self) -> Dict[str, Dict[str, Any]]:
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


def _broker_name(broker: Any) -> str:
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


def _broker_account_key(broker: Any) -> Tuple[str, str]:
    """Return a stable runtime key that separates users on the same venue."""
    name = _broker_name(broker)
    for attr in (
        "nija_account_scope",
        "account_id",
        "user_id",
        "nija_user_id",
        "portfolio_id",
        "subaccount_id",
        "account_uuid",
        "profile_id",
    ):
        value = getattr(broker, attr, None)
        if value not in (None, ""):
            return name, str(value)
    account_type = getattr(getattr(broker, "account_type", None), "value", None)
    if account_type:
        return name, f"{account_type}:object:{id(broker)}"
    return name, f"object:{id(broker)}"


@dataclass
class BrokerAccountRuntime:
    key: Tuple[str, str]
    broker_name: str
    strategy: Any
    apex: Any
    core_loop: Any
    lock: threading.RLock = field(default_factory=threading.RLock)
    created_at: float = field(default_factory=time.time)


class BrokerCellRuntimeManager:
    """Own one APEX/CoreLoop runtime per broker account, never process-global."""

    def __init__(self) -> None:
        self._runtimes: Dict[Tuple[str, str], BrokerAccountRuntime] = {}
        self._lock = threading.RLock()

    @staticmethod
    def _strategy_config(name: str, entry: IsolationEntry) -> Dict[str, Any]:
        cfg: Dict[str, Any] = {
            "broker_cell": name,
            "max_position_pct": min(max(float(entry.risk.max_position_pct), 0.001), 0.30),
            "enable_take_profit": True,
            "broker_max_positions": int(entry.risk.max_positions),
            "broker_stop_loss_pct": float(entry.risk.stop_loss_pct),
            "broker_max_hold_hours": float(entry.strategy.max_hold_hours),
            "broker_bidirectional": bool(entry.strategy.bidirectional),
        }
        try:
            from bot.broker_configs.strategy_selector import STRATEGY_SELECTOR
            broker_cfg = STRATEGY_SELECTOR.get_config(name)
        except Exception:
            broker_cfg = None
        if broker_cfg is not None:
            for attr, target in (
                ("min_position_pct", "min_position_pct"),
                ("max_position_pct", "max_position_pct"),
                ("min_adx", "min_adx"),
                ("volume_threshold", "volume_threshold"),
                ("volume_min_threshold", "volume_min_threshold"),
            ):
                value = getattr(broker_cfg, attr, None)
                if value is not None:
                    cfg[target] = value
        return cfg

    @staticmethod
    def _detach_clone_state(clone: Any, broker: Any) -> None:
        clone.broker = broker
        clone.independent_trader = None

        for attr in ("symbols",):
            value = getattr(clone, attr, None)
            if isinstance(value, list):
                setattr(clone, attr, list(value))
        for attr in (
            "_symbols_by_broker",
            "_symbol_scan_cursor",
            "failed_brokers",
            "_last_known_balances",
            "_broker_balance_cache",
        ):
            value = getattr(clone, attr, None)
            if isinstance(value, dict):
                detached: Dict[Any, Any] = {}
                for key, item in value.items():
                    if isinstance(item, list):
                        detached[key] = list(item)
                    elif isinstance(item, dict):
                        detached[key] = dict(item)
                    else:
                        try:
                            detached[key] = copy.copy(item)
                        except Exception:
                            detached[key] = item
                setattr(clone, attr, detached)

        for attr in (
            "_wiring_recovery_lock",
            "_heartbeat_trade_lock",
            "_symbol_refresh_lock",
            "_symbol_universe_lock",
        ):
            if hasattr(clone, attr):
                setattr(clone, attr, threading.RLock())

        if hasattr(clone, "_heartbeat_trade_thread"):
            clone._heartbeat_trade_thread = None
        if hasattr(clone, "_heartbeat_trade_completed"):
            clone._heartbeat_trade_completed = False
        if hasattr(clone, "_heartbeat_trade_success"):
            clone._heartbeat_trade_success = False
        if hasattr(clone, "_heartbeat_trade_enabled"):
            clone._heartbeat_trade_enabled = False

    def get_or_create(self, owner_strategy: Any, broker: Any) -> BrokerAccountRuntime:
        key = _broker_account_key(broker)
        with self._lock:
            existing = self._runtimes.get(key)
            if existing is not None and existing.strategy is not None:
                existing.strategy.broker = broker
                try:
                    existing.apex.broker_client = broker
                    if hasattr(existing.apex, "execution_engine"):
                        existing.apex.execution_engine.broker_client = broker
                except Exception:
                    pass
                return existing

            registry = get_broker_isolation_registry()
            entry = registry.get_or_default(key[0])
            if entry.policy == IsolationPolicy.DISABLED:
                raise RuntimeError(f"unregistered/disabled broker cell: {key[0]}")

            try:
                from bot.nija_apex_strategy_v71 import NIJAApexStrategyV71
                from bot.nija_core_loop import NijaCoreLoop
            except ImportError:
                from nija_apex_strategy_v71 import NIJAApexStrategyV71  # type: ignore[import]
                from nija_core_loop import NijaCoreLoop  # type: ignore[import]

            clone = copy.copy(owner_strategy)
            self._detach_clone_state(clone, broker)
            apex_cfg = self._strategy_config(key[0], entry)
            apex = NIJAApexStrategyV71(broker_client=broker, config=apex_cfg)
            broker_cfg = None
            try:
                from bot.broker_configs.strategy_selector import STRATEGY_SELECTOR
                broker_cfg = STRATEGY_SELECTOR.get_config(key[0])
            except Exception:
                pass
            setattr(apex, "broker_config", broker_cfg)
            setattr(apex, "broker_cell", key[0])
            setattr(apex, "broker_account_key", key[1])
            core_loop = NijaCoreLoop(
                apex_strategy=apex,
                max_positions=max(1, int(entry.risk.max_positions)),
            )

            clone.apex = apex
            clone.execution_engine = getattr(apex, "execution_engine", None)
            clone.nija_core_loop = core_loop
            clone._nija_broker_cell_runtime = True
            clone._nija_broker_cell_key = key

            runtime = BrokerAccountRuntime(
                key=key,
                broker_name=key[0],
                strategy=clone,
                apex=apex,
                core_loop=core_loop,
            )
            self._runtimes[key] = runtime
            logger.critical(
                "BROKER_ACCOUNT_RUNTIME_CREATED broker=%s account=%s strategy_id=%s apex_id=%s core_loop_id=%s shared_state=false",
                key[0],
                key[1],
                id(clone),
                id(apex),
                id(core_loop),
            )
            return runtime

    def snapshot(self) -> Dict[str, Dict[str, Any]]:
        with self._lock:
            return {
                f"{broker}:{account}": {
                    "broker": broker,
                    "account": account,
                    "strategy_id": id(runtime.strategy),
                    "apex_id": id(runtime.apex),
                    "core_loop_id": id(runtime.core_loop),
                    "created_at": runtime.created_at,
                }
                for (broker, account), runtime in self._runtimes.items()
            }

    def drop(self, broker: Any) -> None:
        with self._lock:
            self._runtimes.pop(_broker_account_key(broker), None)


_instance: Optional[BrokerIsolationRegistry] = None
_instance_lock = threading.Lock()
_runtime_manager: Optional[BrokerCellRuntimeManager] = None
_runtime_manager_lock = threading.Lock()
_strategy_router_lock = threading.Lock()


def get_broker_cell_runtime_manager() -> BrokerCellRuntimeManager:
    global _runtime_manager
    if _runtime_manager is None:
        with _runtime_manager_lock:
            if _runtime_manager is None:
                _runtime_manager = BrokerCellRuntimeManager()
    return _runtime_manager


def _install_strategy_cell_router() -> bool:
    """Route TradingStrategy.run_cycle through per-account runtimes when loaded."""
    with _strategy_router_lock:
        module = sys.modules.get("bot.trading_strategy") or sys.modules.get("trading_strategy")
        cls = getattr(module, "TradingStrategy", None) if module is not None else None
        if not isinstance(cls, type):
            return False
        current = getattr(cls, "run_cycle", None)
        if not callable(current):
            return False
        if getattr(current, "_nija_broker_cell_router_v420", False):
            return True

        original = current

        def _cell_routed_run_cycle(self, broker: Any = None, user_mode: bool = False) -> int:
            if broker is None or bool(getattr(self, "_nija_broker_cell_runtime", False)):
                return int(original(self, broker=broker, user_mode=user_mode) or 150)
            name = _broker_name(broker)
            registry = get_broker_isolation_registry()
            runtime = get_broker_cell_runtime_manager().get_or_create(self, broker)
            registry.apply_to_broker(broker)
            with runtime.lock:
                try:
                    result = int(original(runtime.strategy, broker=broker, user_mode=user_mode) or 150)
                    registry.record_success(name)
                    return result
                except Exception as exc:
                    registry.record_failure(name, f"{type(exc).__name__}:{exc}")
                    raise

        setattr(_cell_routed_run_cycle, "_nija_broker_cell_router_v420", True)
        setattr(_cell_routed_run_cycle, "__wrapped__", original)
        cls.run_cycle = _cell_routed_run_cycle
        logger.critical(
            "BROKER_CELL_STRATEGY_ROUTER_INSTALLED per_account_strategy=true per_account_core_loop=true"
        )
        return True


def get_broker_isolation_registry() -> BrokerIsolationRegistry:
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = BrokerIsolationRegistry()
    try:
        _install_strategy_cell_router()
    except Exception as exc:
        logger.debug("BROKER_CELL_STRATEGY_ROUTER_DEFERRED error=%s", exc)
    return _instance
