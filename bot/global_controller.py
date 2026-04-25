"""
NIJA Global Controller — Non-Blocking Orchestrator
====================================================

Top-level coordinator for multi-broker execution.  Routes risk checks,
trade execution, and capital queries to the appropriate per-broker
controller **without blocking the caller**.

Architecture
------------
::

                    GLOBAL CONTROLLER  (this module)
                           ↓
        ┌──────────────────┴──────────────────┐
        ↓                                     ↓
  COINBASE CONTROLLER                 KRAKEN CONTROLLER
  (micro-cap enabled)               (risk isolated / passive)
        ↓                                     ↓
  EXECUTION PATH                    NO EXECUTION / STRICT MODE

Key APIs
--------
risk_check(broker, context)
    Per-broker risk gate (Step 3).  Coinbase micro-cap trades bypass the
    global risk engine.  Kraken risk events are logged only — never block.

execute_trade(broker, order)
    Execution router (Step 4 / Step 1).  Coinbase orders are forwarded to
    the broker.  Kraken orders are skipped and return a sentinel result.

get_execution_capital(broker_manager)
    Capital aggregation (Step 4).  Returns only brokers flagged
    ``include_in_execution_capital=True`` (Coinbase).  Kraken balance is
    excluded from execution weighting.

filter_symbols(broker_name, candidates)
    Symbol filtering delegated to the appropriate controller.

apply_to_broker_manager(broker_manager)
    One-shot startup call that applies all controller policies to every
    registered broker.

Singleton access
----------------
    from bot.global_controller import get_global_controller
    gc = get_global_controller()
"""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger("nija.global_controller")

try:
    from bot.execution_pipeline import get_execution_pipeline, PipelineRequest
except ImportError:
    try:
        from execution_pipeline import get_execution_pipeline, PipelineRequest
    except ImportError:
        get_execution_pipeline = None  # type: ignore
        PipelineRequest = None         # type: ignore

# ---------------------------------------------------------------------------
# Import sibling controllers and profile registry
# ---------------------------------------------------------------------------
try:
    from bot.broker_profiles import BROKER_PROFILES, get_broker_profile
    from bot.coinbase_controller import CoinbaseController, get_coinbase_controller
    from bot.kraken_controller import (
        KrakenController, KrakenMode, get_kraken_controller,
        KRAKEN_ISOLATED_SKIP,
    )
except ImportError:
    from broker_profiles import BROKER_PROFILES, get_broker_profile  # type: ignore[no-redef]
    from coinbase_controller import CoinbaseController, get_coinbase_controller  # type: ignore[no-redef]
    from kraken_controller import (  # type: ignore[no-redef]
        KrakenController, KrakenMode, get_kraken_controller,
        KRAKEN_ISOLATED_SKIP,
    )


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class RiskContext:
    """Input context passed to :meth:`GlobalController.risk_check`."""
    score: float
    symbol: str = ""
    side: str = "buy"
    size_usd: float = 0.0
    broker_name: str = ""


@dataclass
class RiskResult:
    """Result returned by :meth:`GlobalController.risk_check`."""
    passed: bool
    score: float
    reason: str = ""


@dataclass
class Order:
    """Minimal order descriptor used by :meth:`GlobalController.execute_trade`.

    Callers may pass a broker's native order dict — ``execute_trade`` unpacks
    the relevant fields.
    """
    symbol: str
    side: str
    usd_size: float
    quantity: Optional[float] = None
    extra: Dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# GlobalController
# ---------------------------------------------------------------------------

class GlobalController:
    """Non-blocking global orchestrator for multi-broker execution.

    Parameters
    ----------
    coinbase_controller:
        :class:`CoinbaseController` instance.  Defaults to the module
        singleton when *None*.
    kraken_controller:
        :class:`KrakenController` instance.  Defaults to the module
        singleton when *None*.
    """

    def __init__(
        self,
        coinbase_controller: Optional[CoinbaseController] = None,
        kraken_controller: Optional[KrakenController] = None,
    ) -> None:
        self._coinbase: CoinbaseController = (
            coinbase_controller or get_coinbase_controller()
        )
        self._kraken: KrakenController = (
            kraken_controller or get_kraken_controller()
        )
        self._lock = threading.Lock()

        logger.info("=" * 60)
        logger.info("🧠 GlobalController initialised (non-blocking)")
        logger.info("   Coinbase → %s", self._coinbase.EXECUTION_MODE.upper())
        logger.info("   Kraken   → %s", self._kraken.EXECUTION_MODE.upper())
        logger.info("=" * 60)

    # ------------------------------------------------------------------
    # Step 3: Per-broker risk check
    # ------------------------------------------------------------------

    def risk_check(self, broker, context: RiskContext) -> RiskResult:
        """Evaluate risk for *broker* using its per-broker profile.

        Coinbase (micro-cap enabled)
            Bypasses the global risk engine.  The trade is approved
            with reason ``MICRO_CAP_COINBASE_BYPASS``.

        Kraken (isolated)
            Risk is evaluated in log-only mode.  The check always
            passes with reason ``KRAKEN_ISOLATED`` so Kraken risk
            events never cascade to or block other brokers.

        All other brokers
            Delegates to :meth:`_default_risk_check`.
        """
        broker_name: str = self._broker_name(broker)
        profile: dict = get_broker_profile(broker_name)

        if broker_name == "coinbase" and profile.get("micro_cap_enabled"):
            logger.debug(
                "🟢 risk_check: Coinbase micro-cap bypass (score=%.2f, symbol=%s)",
                context.score, context.symbol,
            )
            return RiskResult(
                passed=True,
                score=context.score,
                reason="MICRO_CAP_COINBASE_BYPASS",
            )

        if broker_name == "kraken":
            logger.warning(
                "⚠️  risk_check: Kraken risk evaluation (isolated mode) "
                "score=%.2f symbol=%s — logging only, not blocking",
                context.score, context.symbol,
            )
            return RiskResult(
                passed=True,
                score=context.score,
                reason="KRAKEN_ISOLATED",
            )

        return self._default_risk_check(context)

    def _default_risk_check(self, context: RiskContext) -> RiskResult:
        """Permissive fallback risk check for unknown brokers."""
        return RiskResult(
            passed=True,
            score=context.score,
            reason="DEFAULT_PASS",
        )

    # ------------------------------------------------------------------
    # Step 1 / 4: Execution router
    # ------------------------------------------------------------------

    def execute_trade(self, broker, order: Order) -> dict:
        """Route *order* to the correct execution path for *broker*.

        Coinbase
            Order is forwarded to ``ExecutionPipeline.execute()``.
            Sub-minimum order sizes are logged then allowed (micro-cap).

        Kraken (isolated)
            Order is **not forwarded**.  Returns :data:`KRAKEN_ISOLATED_SKIP`
            immediately so callers can handle the skip without an exception.

        Other brokers
            Order is forwarded unchanged.
        """
        broker_name: str = self._broker_name(broker)
        profile: dict = get_broker_profile(broker_name)

        if broker_name == "coinbase":
            if order.usd_size < profile.get("min_order_usd", 1.0):
                logger.info(
                    "🟢 execute_trade: Coinbase micro-cap execution allowed "
                    "(size=$%.2f < min_order=$%.2f)",
                    order.usd_size, profile.get("min_order_usd", 1.0),
                )
            return self._forward_order(broker, order)

        if broker_name == "kraken":
            logger.info(
                "🔴 execute_trade: Kraken isolated mode — NO EXECUTION "
                "(symbol=%s side=%s size=$%.2f)",
                order.symbol, order.side, order.usd_size,
            )
            return KRAKEN_ISOLATED_SKIP

        # Generic path for any other registered broker
        return self._forward_order(broker, order)

    def _forward_order(self, broker, order: Order) -> dict:
        """Forward orders via ExecutionPipeline; block direct broker bypass in strict mode."""
        try:
            if get_execution_pipeline is not None and PipelineRequest is not None:
                broker_name = self._broker_name(broker)
                price_hint = None
                try:
                    if hasattr(broker, "get_current_price"):
                        px = float(broker.get_current_price(order.symbol) or 0.0)
                        if px > 0:
                            price_hint = px
                except Exception:
                    price_hint = None

                res = get_execution_pipeline().execute(
                    PipelineRequest(
                        strategy="GlobalController",
                        symbol=order.symbol,
                        side=order.side,
                        size_usd=order.usd_size,
                        order_type="MARKET",
                        preferred_broker=broker_name,
                        price_hint_usd=price_hint,
                    )
                )
                if res.success:
                    return {
                        "status": "filled",
                        "broker": res.broker or broker_name,
                        "filled_price": res.fill_price,
                        "filled_size_usd": res.filled_size_usd,
                        "order_id": "pipeline",
                    }
                return {"status": "error", "error": res.error or "Execution pipeline rejected order"}

            return {
                "status": "error",
                "error": "ExecutionPipeline unavailable and direct broker bypass blocked",
            }
        except Exception as exc:
            logger.error(
                "❌ execute_trade: %s order failed — %s",
                self._broker_name(broker), exc,
            )
            return {"status": "error", "error": str(exc)}

    # ------------------------------------------------------------------
    # Step 4: Execution capital (Kraken excluded)
    # ------------------------------------------------------------------

    def get_execution_capital(self, broker_manager=None) -> Dict[str, float]:
        """Return a mapping of broker→balance for execution weighting.

        Only brokers flagged ``include_in_execution_capital=True`` in
        :data:`BROKER_PROFILES` are included.  **Kraken is excluded.**

        Parameters
        ----------
        broker_manager:
            Optional :class:`BrokerManager` instance.  When provided its
            connected brokers are queried for live balances.  When *None*
            the method returns a profile-driven skeleton with zero balances.
        """
        result: Dict[str, float] = {}

        if broker_manager is not None:
            for broker_type, broker in getattr(broker_manager, "brokers", {}).items():
                name: str = broker_type.value.lower()
                profile: dict = get_broker_profile(name)
                if not profile.get("include_in_execution_capital", True):
                    logger.debug(
                        "get_execution_capital: %s excluded (isolated)", name
                    )
                    continue
                try:
                    balance: float = broker.get_account_balance()
                    result[name] = balance
                    logger.debug(
                        "get_execution_capital: %s=$%.2f", name, balance
                    )
                except Exception as exc:
                    logger.warning(
                        "get_execution_capital: could not fetch %s balance — %s",
                        name, exc,
                    )
                    result[name] = 0.0
        else:
            # Return profile skeleton without live broker queries
            for name, profile in BROKER_PROFILES.items():
                if profile.get("include_in_execution_capital", True):
                    result[name] = 0.0

        logger.info(
            "💰 Execution capital (Kraken excluded): %s",
            {k: f"${v:,.2f}" for k, v in result.items()},
        )
        return result

    # ------------------------------------------------------------------
    # Symbol filtering
    # ------------------------------------------------------------------

    def filter_symbols(self, broker_name: str, candidates: List[str]) -> List[str]:
        """Return the subset of *candidates* allowed for *broker_name*.

        Coinbase — restricted to the micro-cap universe.
        Kraken   — returns an empty list (no new entries).
        Others   — candidates passed through unchanged.
        """
        name = broker_name.lower()
        if name == "coinbase":
            filtered = self._coinbase.filter_symbols(candidates)
            logger.debug(
                "filter_symbols: Coinbase micro-cap: %d/%d passed",
                len(filtered), len(candidates),
            )
            return filtered
        if name == "kraken":
            logger.debug("filter_symbols: Kraken isolated — all symbols blocked")
            return []
        return candidates

    def is_entry_allowed(self, broker_name: str, balance: float = 0.0) -> bool:
        """Return *True* if the broker may open a new position."""
        name = broker_name.lower()
        if name == "coinbase":
            return self._coinbase.can_execute_entry(balance)
        if name == "kraken":
            return False
        return True

    # ------------------------------------------------------------------
    # Startup: apply policies to all registered brokers
    # ------------------------------------------------------------------

    def apply_to_broker_manager(self, broker_manager) -> None:
        """Apply per-broker policies to every broker in *broker_manager*.

        Call this once at bot startup after all brokers are connected.
        """
        if broker_manager is None:
            return

        try:
            from bot.broker_manager import BrokerType
        except ImportError:
            from broker_manager import BrokerType  # type: ignore[no-redef]

        for broker_type, broker in getattr(broker_manager, "brokers", {}).items():
            name: str = broker_type.value.lower()
            if name == "coinbase":
                self._coinbase.apply_to_broker(broker)
                logger.info(
                    "✅ GlobalController: Coinbase policy applied (active, micro-cap)"
                )
            elif name == "kraken":
                self._kraken.apply_to_broker(broker)
                logger.info(
                    "✅ GlobalController: Kraken policy applied (isolated, exit-only)"
                )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _broker_name(broker) -> str:
        """Extract lower-case broker name from a broker instance or string."""
        if isinstance(broker, str):
            return broker.lower()
        bt = getattr(broker, "broker_type", None)
        if bt is not None:
            val = getattr(bt, "value", None)
            if val is not None:
                return str(val).lower()
        return str(broker).lower()

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def get_status(self) -> dict:
        return {
            "coinbase": self._coinbase.get_status(),
            "kraken": self._kraken.get_status(),
        }


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_instance: Optional[GlobalController] = None
_instance_lock = threading.Lock()


def get_global_controller() -> GlobalController:
    """Return (or create) the process-wide :class:`GlobalController` singleton."""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = GlobalController()
    return _instance
