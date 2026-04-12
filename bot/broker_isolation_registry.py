"""
NIJA Broker Isolation Registry
================================

Central plug-in registry that maps every broker to its
:class:`IsolationEntry` — the complete execution + risk policy
for that exchange.

Architecture
------------
::

                 BrokerIsolationRegistry
                          │
        ┌─────────────────┼──────────────────┐
        ▼                 ▼                  ▼
  IsolationEntry    IsolationEntry     IsolationEntry
  (coinbase)        (kraken)           (alpaca / binance / okx …)
     policy=MICRO_CAP  policy=ISOLATED    policy=ACTIVE
     risk=Bypass        risk=Isolated      risk=Active
     capital=$1         capital=$25        capital=$5

IsolationPolicy
---------------
ACTIVE     Full execution; full risk evaluation.
MICRO_CAP  Active execution; global risk gate bypassed (Coinbase).
ISOLATED   Exit-only (SELLs); risk logged, not enforced (Kraken STRICT).
PASSIVE    No execution at all.
DISABLED   Fully off; no API calls.

Singleton access
----------------
    from bot.broker_isolation_registry import get_broker_isolation_registry
    reg = get_broker_isolation_registry()
    entry = reg.get("coinbase")
    if not entry.is_entry_allowed():
        ...
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Dict, List, Optional

logger = logging.getLogger("nija.broker_isolation_registry")


# ---------------------------------------------------------------------------
# Policy enum
# ---------------------------------------------------------------------------

class IsolationPolicy(Enum):
    ACTIVE    = "active"
    MICRO_CAP = "micro_cap"
    ISOLATED  = "isolated"
    PASSIVE   = "passive"
    DISABLED  = "disabled"

    # Convenience sets
    @classmethod
    def entry_allowed(cls):
        return frozenset({cls.ACTIVE, cls.MICRO_CAP})

    @classmethod
    def exit_allowed(cls):
        return frozenset({cls.ACTIVE, cls.MICRO_CAP, cls.ISOLATED})

    @classmethod
    def execution_blocked(cls):
        return frozenset({cls.PASSIVE, cls.DISABLED})


# ---------------------------------------------------------------------------
# Capital profile
# ---------------------------------------------------------------------------

@dataclass
class CapitalProfile:
    """Per-broker capital rules."""
    min_capital_usd: float = 1.0
    min_order_usd: float = 1.0
    include_in_execution_capital: bool = True
    ignore_global_capital_floor: bool = False
    base_execution_weight: float = 1.0


# ---------------------------------------------------------------------------
# Isolation entry
# ---------------------------------------------------------------------------

@dataclass
class IsolationEntry:
    """Complete isolation policy for one broker."""
    broker_name: str
    policy: IsolationPolicy
    capital: CapitalProfile = field(default_factory=CapitalProfile)
    symbol_filter: Optional[Callable[[List[str]], List[str]]] = None
    description: str = ""

    # ------------------------------------------------------------------
    # Convenience predicates
    # ------------------------------------------------------------------

    def is_entry_allowed(self) -> bool:
        return self.policy in IsolationPolicy.entry_allowed()

    def is_exit_allowed(self) -> bool:
        return self.policy in IsolationPolicy.exit_allowed()

    def skip_execution(self) -> bool:
        return self.policy in IsolationPolicy.execution_blocked()

    def skip_risk_gate(self) -> bool:
        """True → bypass the global risk engine entirely (MICRO_CAP)."""
        return self.policy == IsolationPolicy.MICRO_CAP

    def log_risk_only(self) -> bool:
        """True → evaluate risk but only log; never block (ISOLATED)."""
        return self.policy == IsolationPolicy.ISOLATED

    def filter_symbols(self, candidates: List[str]) -> List[str]:
        if self.symbol_filter is None:
            return candidates
        return self.symbol_filter(candidates)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

class BrokerIsolationRegistry:
    """Thread-safe registry of :class:`IsolationEntry` objects.

    Default entries for all 8 known brokers are registered at
    construction time.  Entries can be updated at runtime (e.g., after
    receiving a quarantine signal) via :meth:`register`.
    """

    def __init__(self) -> None:
        self._entries: Dict[str, IsolationEntry] = {}
        self._lock = threading.Lock()
        self._initialize_defaults()

    # ------------------------------------------------------------------
    # Default setup
    # ------------------------------------------------------------------

    def _initialize_defaults(self) -> None:
        try:
            from bot.broker_profiles import (
                BROKER_PROFILES,
                COINBASE_MICRO_CAP_MODE,
                KRAKEN_EXECUTION_DISABLED,
            )
        except ImportError:
            from broker_profiles import (  # type: ignore
                BROKER_PROFILES,
                COINBASE_MICRO_CAP_MODE,
                KRAKEN_EXECUTION_DISABLED,
            )

        # Build one IsolationEntry per profile
        for name, profile in BROKER_PROFILES.items():
            exec_mode = profile.get("execution_mode", "active")
            if name == "coinbase":
                policy = IsolationPolicy.MICRO_CAP if COINBASE_MICRO_CAP_MODE else IsolationPolicy.ACTIVE
            elif name == "kraken":
                if KRAKEN_EXECUTION_DISABLED:
                    policy = IsolationPolicy.PASSIVE
                elif exec_mode == "isolated":
                    policy = IsolationPolicy.ISOLATED
                else:
                    policy = IsolationPolicy.ACTIVE
            else:
                _MAP = {
                    "active":    IsolationPolicy.ACTIVE,
                    "micro_cap": IsolationPolicy.MICRO_CAP,
                    "isolated":  IsolationPolicy.ISOLATED,
                    "passive":   IsolationPolicy.PASSIVE,
                    "disabled":  IsolationPolicy.DISABLED,
                }
                policy = _MAP.get(exec_mode, IsolationPolicy.PASSIVE)

            capital = CapitalProfile(
                min_capital_usd=profile.get("min_capital_usd", 1.0),
                min_order_usd=profile.get("min_order_usd", 1.0),
                include_in_execution_capital=profile.get("include_in_execution_capital", True),
                ignore_global_capital_floor=profile.get("ignore_global_capital_floor", False),
                base_execution_weight=profile.get("base_execution_weight", 1.0),
            )

            # Coinbase: attach symbol allowlist filter
            symbol_filter = None
            if name == "coinbase":
                try:
                    from bot.coinbase_controller import get_coinbase_controller
                    ctrl = get_coinbase_controller()
                    symbol_filter = ctrl.filter_symbols
                except Exception:
                    pass

            self._entries[name] = IsolationEntry(
                broker_name=name,
                policy=policy,
                capital=capital,
                symbol_filter=symbol_filter,
                description=f"Default entry for {name} ({policy.value})",
            )
            logger.debug(
                "BrokerIsolationRegistry: %s → %s (min_order=$%.2f)",
                name, policy.value, capital.min_order_usd,
            )

        logger.info(
            "BrokerIsolationRegistry: %d entries loaded (%s)",
            len(self._entries),
            ", ".join(f"{n}={e.policy.value}" for n, e in self._entries.items()),
        )

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def register(self, entry: IsolationEntry) -> None:
        """Register (or replace) a broker entry."""
        with self._lock:
            self._entries[entry.broker_name.lower()] = entry
        logger.info(
            "BrokerIsolationRegistry: %s → %s (updated)",
            entry.broker_name, entry.policy.value,
        )

    def get(self, broker_name: str) -> Optional[IsolationEntry]:
        """Return the entry for *broker_name*, or *None* if not registered."""
        return self._entries.get(broker_name.lower())

    def get_or_default(self, broker_name: str) -> IsolationEntry:
        """Return the entry or a permissive ACTIVE default."""
        return self._entries.get(broker_name.lower()) or IsolationEntry(
            broker_name=broker_name,
            policy=IsolationPolicy.ACTIVE,
            description="auto-default (not in registry)",
        )

    # ------------------------------------------------------------------
    # Bulk queries
    # ------------------------------------------------------------------

    def get_active_entries(self) -> List[IsolationEntry]:
        """Entries with policy ACTIVE or MICRO_CAP."""
        return [
            e for e in self._entries.values()
            if e.policy in IsolationPolicy.entry_allowed()
        ]

    def get_execution_eligible(self) -> List[IsolationEntry]:
        """Entries that may receive orders (not PASSIVE / DISABLED)."""
        return [
            e for e in self._entries.values()
            if not e.skip_execution()
        ]

    def get_capital_eligible(self) -> List[IsolationEntry]:
        """Entries included in execution capital weighting."""
        return [
            e for e in self._entries.values()
            if e.capital.include_in_execution_capital
        ]

    # ------------------------------------------------------------------
    # Broker integration
    # ------------------------------------------------------------------

    def apply_to_broker(self, broker) -> None:
        """Apply the isolation policy to a live broker instance.

        Sets ``exit_only_mode`` and ``mode`` attributes on *broker*
        so the existing KrakenBroker / CoinbaseBroker guards fire
        independently of the GlobalController.
        """
        name = _broker_name(broker)
        entry = self.get(name)
        if entry is None:
            return

        if entry.skip_execution():
            broker.exit_only_mode = True
            broker.mode = "PASSIVE"
            logger.info("Registry: %s → PASSIVE applied", name)
        elif entry.policy == IsolationPolicy.ISOLATED:
            broker.exit_only_mode = True
            logger.info("Registry: %s → exit_only_mode=True (ISOLATED)", name)
        elif entry.policy in (IsolationPolicy.ACTIVE, IsolationPolicy.MICRO_CAP):
            broker.exit_only_mode = False
            logger.info("Registry: %s → exit_only_mode=False (%s)", name, entry.policy.value)

    def apply_to_all_brokers(self, broker_manager) -> None:
        """Apply policies to every broker registered in *broker_manager*."""
        for broker_type, broker in getattr(broker_manager, "brokers", {}).items():
            self.apply_to_broker(broker)

    # ------------------------------------------------------------------
    # Isolation check (used by broker_manager._check_broker_isolation)
    # ------------------------------------------------------------------

    def check_execution(self, broker_name: str, side: str) -> Optional[Dict]:
        """Return a skip-result dict if execution should be blocked, else None.

        This is the hot-path check called at the top of every
        ``place_market_order`` implementation.
        """
        entry = self.get(broker_name)
        if entry is None:
            return None

        if entry.skip_execution():
            logger.warning(
                "Broker isolated mode: non-execution broker (%s) — %s skipped",
                broker_name, side.upper(),
            )
            return _SKIP_RESULT

        if side.lower() == "buy" and not entry.is_entry_allowed():
            logger.warning(
                "Broker isolated mode: non-execution broker (%s) — BUY blocked",
                broker_name,
            )
            return _SKIP_RESULT

        return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SKIP_RESULT: Dict = {
    "status": "broker_isolated_skip",
    "partial_fill": False,
    "filled_pct": 0.0,
}


def _broker_name(broker) -> str:
    if isinstance(broker, str):
        return broker.lower()
    bt = getattr(broker, "broker_type", None)
    if bt is not None:
        val = getattr(bt, "value", None)
        if val is not None:
            return str(val).lower()
    return str(broker).lower()


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_instance: Optional[BrokerIsolationRegistry] = None
_instance_lock = threading.Lock()


def get_broker_isolation_registry() -> BrokerIsolationRegistry:
    """Return (or create) the process-wide :class:`BrokerIsolationRegistry`."""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = BrokerIsolationRegistry()
    return _instance
