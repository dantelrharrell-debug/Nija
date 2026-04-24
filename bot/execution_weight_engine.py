"""
NIJA Execution Weight Engine
===============================

Computes per-broker execution weights for dynamic capital allocation.

Only brokers flagged ``include_in_execution_capital=True`` in
:data:`BROKER_PROFILES` are included.  Kraken and all
ISOLATED / PASSIVE / DISABLED brokers are excluded.

Weighting formula
-----------------
::

    raw_weight[broker] = live_balance[broker]
                         × entry.capital.base_execution_weight

    execution_weight[broker] = raw_weight[broker]
                                ÷ sum(raw_weight.values())

Usage
-----
    from bot.execution_weight_engine import get_execution_weight_engine

    engine = get_execution_weight_engine()
    capital = engine.get_execution_capital(broker_manager)
    weights = engine.get_execution_weights(broker_manager)
    # → {"coinbase": 1.0, ...}  (Kraken absent)
"""

from __future__ import annotations

import logging
import threading
from typing import Dict, Optional

logger = logging.getLogger("nija.execution_weight_engine")


class ExecutionWeightEngine:
    """Dynamic execution capital + weight calculator.

    Parameters
    ----------
    registry:
        :class:`BrokerIsolationRegistry` instance.  Defaults to the
        module-level singleton when *None*.
    """

    def __init__(self, registry=None) -> None:
        if registry is None:
            try:
                from bot.broker_isolation_registry import get_broker_isolation_registry
            except ImportError:
                from broker_isolation_registry import get_broker_isolation_registry  # type: ignore
            registry = get_broker_isolation_registry()
        self._registry = registry

    # ------------------------------------------------------------------
    # Step 4: Execution capital (Kraken excluded)
    # ------------------------------------------------------------------

    def get_execution_capital(
        self,
        broker_manager=None,
    ) -> Dict[str, float]:
        """Return ``{broker_name: live_balance}`` for execution-eligible
        brokers only.  Kraken and any ISOLATED/PASSIVE/DISABLED broker
        are excluded.

        Parameters
        ----------
        broker_manager:
            Optional :class:`BrokerManager` — when provided, live
            balances are fetched via ``broker.get_account_balance()``.
            When *None*, returns a skeleton with zero balances.
        """
        eligible = {
            e.broker_name
            for e in self._registry.get_capital_eligible()
            if e.is_entry_allowed()   # ACTIVE or MICRO_CAP only
        }

        result: Dict[str, float] = {}

        if broker_manager is not None:
            for broker_type, broker in getattr(broker_manager, "brokers", {}).items():
                name: str = broker_type.value.lower()
                if name not in eligible:
                    logger.debug(
                        "get_execution_capital: %s excluded (not capital-eligible)", name
                    )
                    continue
                try:
                    balance: float = broker.get_account_balance()
                    result[name] = balance
                    logger.debug("get_execution_capital: %s = $%.2f", name, balance)
                except Exception as exc:
                    logger.warning(
                        "get_execution_capital: could not fetch %s balance — %s",
                        name, exc,
                    )
                    result[name] = 0.0
        else:
            for name in eligible:
                result[name] = 0.0

        logger.info(
            "💰 Execution capital (isolated brokers excluded): %s",
            {k: f"${v:,.2f}" for k, v in result.items()},
        )
        return result

    # ------------------------------------------------------------------
    # Dynamic weighting
    # ------------------------------------------------------------------

    def get_execution_weights(
        self,
        broker_manager=None,
    ) -> Dict[str, float]:
        """Return normalised execution weights for active brokers.

        Weights are proportional to ``balance × base_execution_weight``.
        All values sum to 1.0 (or 0.0 if total capital is zero).
        """
        capital = self.get_execution_capital(broker_manager)
        entries = {
            e.broker_name: e
            for e in self._registry.get_active_entries()
        }

        raw: Dict[str, float] = {}
        for name, balance in capital.items():
            entry = entries.get(name)
            weight = entry.capital.base_execution_weight if entry else 1.0
            raw[name] = balance * weight

        total = sum(raw.values())
        if total <= 0:
            return {k: 0.0 for k in raw}

        normalised = {k: v / total for k, v in raw.items()}
        logger.debug("Execution weights: %s", {k: f"{v:.2%}" for k, v in normalised.items()})
        return normalised

    # ------------------------------------------------------------------
    # Convenience: capital summary for logging
    # ------------------------------------------------------------------

    def log_execution_capital_summary(self, broker_manager=None) -> None:
        capital = self.get_execution_capital(broker_manager)
        weights = self.get_execution_weights(broker_manager)
        total = sum(capital.values())
        logger.info("=" * 60)
        logger.info("💰 EXECUTION CAPITAL SUMMARY (Kraken excluded)")
        logger.info("   Total: $%.2f", total)
        for name, bal in capital.items():
            w = weights.get(name, 0.0)
            logger.info("   %-20s $%10.2f  (weight %.1f%%)", name.upper(), bal, w * 100)
        logger.info("=" * 60)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_instance: Optional[ExecutionWeightEngine] = None
_instance_lock = threading.Lock()


def get_execution_weight_engine() -> ExecutionWeightEngine:
    """Return (or create) the process-wide :class:`ExecutionWeightEngine`."""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = ExecutionWeightEngine()
    return _instance
