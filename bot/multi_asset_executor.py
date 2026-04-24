"""
NIJA Multi-Asset Execution Coordinator
=======================================

Coordinates simultaneous trading across multiple asset classes:
  - Crypto (via Coinbase / Kraken adapters)
  - Equities (stub / future broker integration)
  - Foreign Exchange (stub)
  - Futures (stub)
  - Options (stub)

The coordinator enforces per-asset-class capital limits, aggregates
portfolio exposure, and delegates execution to the appropriate broker
adapter. It integrates with HedgeFundStrategyRouter for signal generation
and the PortfolioVaRMonitor for real-time risk gating.

Usage
-----
    from bot.multi_asset_executor import MultiAssetExecutor, AssetAllocation

    executor = MultiAssetExecutor(total_capital=100_000)
    executor.set_allocation(AssetAllocation(crypto=0.60, equity=0.25, fx=0.10, futures=0.05))
    result = executor.execute_signal(signal_dict, asset_class="CRYPTO")

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("nija.multi_asset_executor")


# ---------------------------------------------------------------------------
# Asset class definitions
# ---------------------------------------------------------------------------

class AssetClass(str, Enum):
    CRYPTO   = "CRYPTO"
    EQUITY   = "EQUITY"
    FX       = "FX"
    FUTURES  = "FUTURES"
    OPTIONS  = "OPTIONS"


@dataclass
class AssetAllocation:
    """
    Fractional capital allocation per asset class. Must sum to ≤ 1.0.
    The remainder is treated as cash / undeployed capital.
    """
    crypto:  float = 1.0   # default: all crypto (Coinbase-focused)
    equity:  float = 0.0
    fx:      float = 0.0
    futures: float = 0.0
    options: float = 0.0

    def validate(self) -> None:
        total = self.crypto + self.equity + self.fx + self.futures + self.options
        if total > 1.0 + 1e-6:
            raise ValueError(f"Asset allocations sum to {total:.4f} > 1.0")

    def to_dict(self) -> Dict[str, float]:
        return {
            AssetClass.CRYPTO:  self.crypto,
            AssetClass.EQUITY:  self.equity,
            AssetClass.FX:      self.fx,
            AssetClass.FUTURES: self.futures,
            AssetClass.OPTIONS: self.options,
        }


# ---------------------------------------------------------------------------
# Position tracker
# ---------------------------------------------------------------------------

@dataclass
class AssetPosition:
    symbol:      str
    asset_class: AssetClass
    side:        str          # "LONG" | "SHORT"
    size:        float        # units / contracts
    entry_price: float
    current_price: float = 0.0
    unrealised_pnl: float = 0.0
    stop_loss:   Optional[float] = None
    take_profit: Optional[float] = None
    opened_at:   str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    broker:      str = "coinbase"

    def update_price(self, price: float) -> None:
        self.current_price = price
        multiplier = 1 if self.side == "LONG" else -1
        self.unrealised_pnl = multiplier * (price - self.entry_price) * self.size

    def market_value(self) -> float:
        p = self.current_price if self.current_price > 0 else self.entry_price
        return p * self.size

    def to_dict(self) -> Dict:
        return {
            "symbol": self.symbol,
            "asset_class": self.asset_class.value,
            "side": self.side,
            "size": self.size,
            "entry_price": self.entry_price,
            "current_price": self.current_price,
            "unrealised_pnl": round(self.unrealised_pnl, 4),
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "opened_at": self.opened_at,
            "broker": self.broker,
        }


# ---------------------------------------------------------------------------
# Execution result
# ---------------------------------------------------------------------------

@dataclass
class ExecutionResult:
    success:     bool
    symbol:      str
    asset_class: AssetClass
    action:      str
    filled_price: Optional[float]
    filled_size:  Optional[float]
    broker:       str
    order_id:     Optional[str] = None
    message:      str = ""
    timestamp:    str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict:
        return {
            "success": self.success,
            "symbol": self.symbol,
            "asset_class": self.asset_class.value,
            "action": self.action,
            "filled_price": self.filled_price,
            "filled_size": self.filled_size,
            "broker": self.broker,
            "order_id": self.order_id,
            "message": self.message,
            "timestamp": self.timestamp,
        }


# ---------------------------------------------------------------------------
# Broker adapter interface
# ---------------------------------------------------------------------------

class BrokerAdapter:
    """
    Minimal interface every broker adapter must implement.
    Concrete adapters (Coinbase, Kraken, …) should extend this class.
    """

    NAME = "base"
    SUPPORTED_ASSET_CLASSES: Tuple[AssetClass, ...] = ()

    def place_order(
        self,
        symbol: str,
        side: str,
        size: float,
        order_type: str = "MARKET",
        limit_price: Optional[float] = None,
    ) -> Dict:
        """Place an order. Returns broker response dict."""
        raise NotImplementedError

    def get_price(self, symbol: str) -> float:
        """Return best mid price for symbol."""
        raise NotImplementedError

    def cancel_order(self, order_id: str) -> bool:
        raise NotImplementedError


class CoinbaseBrokerAdapter(BrokerAdapter):
    """
    Thin wrapper around the existing CoinbaseAdvancedTrader client.
    Falls back to a logged stub if the integration is not configured.
    """

    NAME = "coinbase"
    SUPPORTED_ASSET_CLASSES = (AssetClass.CRYPTO,)

    def __init__(self, client=None):
        self._client = client  # coinbase_advanced_trader.RESTClient or None

    def place_order(self, symbol, side, size, order_type="MARKET", limit_price=None):
        if self._client is None:
            logger.warning("[Coinbase] No client configured — simulating order")
            return {"order_id": "sim_" + symbol, "status": "SIMULATED", "filled_size": size}
        try:
            if side.upper() == "BUY":
                resp = self._client.market_order_buy(product_id=symbol, base_size=str(size))
            else:
                resp = self._client.market_order_sell(product_id=symbol, base_size=str(size))
            return resp if isinstance(resp, dict) else {"order_id": str(resp), "status": "SUBMITTED"}
        except Exception as exc:
            logger.error("[Coinbase] order error: %s", exc)
            return {"error": str(exc), "status": "ERROR"}

    def get_price(self, symbol: str) -> float:
        if self._client is None:
            return 0.0
        try:
            ticker = self._client.get_best_bid_ask(product_ids=[symbol])
            bbo = ticker.get("pricebooks", [{}])[0]
            bid = float(bbo.get("bids", [{}])[0].get("price", 0))
            ask = float(bbo.get("asks", [{}])[0].get("price", 0))
            return (bid + ask) / 2 if bid and ask else 0.0
        except Exception as exc:
            logger.error("[Coinbase] price error: %s", exc)
            return 0.0

    def cancel_order(self, order_id: str) -> bool:
        if self._client is None:
            return True
        try:
            self._client.cancel_orders(order_ids=[order_id])
            return True
        except Exception as exc:
            logger.error("[Coinbase] cancel error: %s", exc)
            return False


class StubBrokerAdapter(BrokerAdapter):
    """
    Paper-trading stub for equity, FX, futures, and options.
    Records all orders in memory with simulated fills.
    """

    def __init__(self, asset_classes: Tuple[AssetClass, ...], name: str = "stub"):
        self.NAME = name
        self.SUPPORTED_ASSET_CLASSES = asset_classes
        self._orders: List[Dict] = []
        self._prices: Dict[str, float] = {}

    def place_order(self, symbol, side, size, order_type="MARKET", limit_price=None):
        price = self._prices.get(symbol, 100.0)
        order = {
            "order_id": f"stub_{len(self._orders)}_{symbol}",
            "symbol": symbol,
            "side": side,
            "size": size,
            "filled_price": price,
            "filled_size": size,
            "status": "FILLED",
        }
        self._orders.append(order)
        logger.info("[%s] Stub order filled: %s %s %.4f @ %.4f", self.NAME, side, symbol, size, price)
        return order

    def get_price(self, symbol: str) -> float:
        return self._prices.get(symbol, 0.0)

    def set_price(self, symbol: str, price: float) -> None:
        self._prices[symbol] = price

    def cancel_order(self, order_id: str) -> bool:
        return True


# ---------------------------------------------------------------------------
# Main executor
# ---------------------------------------------------------------------------

class MultiAssetExecutor:
    """
    Portfolio-wide multi-asset trade execution coordinator.

    Responsibilities
    ----------------
    1. Enforce per-asset-class capital limits.
    2. Route orders to the correct broker adapter.
    3. Track open positions across all asset classes.
    4. Report portfolio exposure for risk gating.
    5. Optionally call a risk-gate callback before execution.

    Args:
        total_capital: Total portfolio USD value.
        allocation: AssetAllocation object (default: 100 % crypto).
        risk_gate: Optional callable(signal_dict) → bool; if it returns
                   False the trade is blocked.
        coinbase_client: Optional pre-configured Coinbase RESTClient.
    """

    def __init__(
        self,
        total_capital: float,
        allocation: Optional[AssetAllocation] = None,
        risk_gate: Optional[Callable[[Dict], bool]] = None,
        coinbase_client=None,
        live_brokers: Optional[Dict[AssetClass, "BrokerAdapter"]] = None,
    ):
        """
        Args:
            total_capital:  Total portfolio USD value.
            allocation:     AssetAllocation object (default: 100% crypto).
            risk_gate:      Optional callable(signal_dict) → bool; False blocks trade.
            coinbase_client: Optional pre-configured Coinbase RESTClient.
            live_brokers:   Optional mapping of AssetClass → live BrokerAdapter.
                            Provided adapters replace the default stubs.  Use
                            ``bot.live_broker_adapters.build_live_adapters()`` to
                            construct them, or pass individual adapters.
        """
        self.total_capital = total_capital
        self.allocation = allocation or AssetAllocation()
        self.allocation.validate()
        self.risk_gate = risk_gate
        self._lock = threading.RLock()

        # Start with default adapters (stub for non-crypto asset classes)
        self._adapters: Dict[AssetClass, BrokerAdapter] = {
            AssetClass.CRYPTO:   CoinbaseBrokerAdapter(coinbase_client),
            AssetClass.EQUITY:   StubBrokerAdapter((AssetClass.EQUITY,), "equity_stub"),
            AssetClass.FX:       StubBrokerAdapter((AssetClass.FX,), "fx_stub"),
            AssetClass.FUTURES:  StubBrokerAdapter((AssetClass.FUTURES,), "futures_stub"),
            AssetClass.OPTIONS:  StubBrokerAdapter((AssetClass.OPTIONS,), "options_stub"),
        }

        # Override stubs with live adapters where provided
        if live_brokers:
            for asset_class, adapter in live_brokers.items():
                self._adapters[asset_class] = adapter
                logger.info(
                    "[MultiAssetExecutor] Live adapter registered for %s: %s",
                    asset_class.value, adapter.NAME,
                )

        # Open positions
        self._positions: Dict[str, AssetPosition] = {}   # key: symbol
        self._closed_positions: List[AssetPosition] = []
        self._execution_log: List[ExecutionResult] = []

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def set_allocation(self, allocation: AssetAllocation) -> None:
        allocation.validate()
        with self._lock:
            self.allocation = allocation
        logger.info("[MultiAssetExecutor] Allocation updated: %s", allocation.to_dict())

    def register_broker(self, asset_class: AssetClass, adapter: BrokerAdapter) -> None:
        with self._lock:
            self._adapters[asset_class] = adapter

    def update_capital(self, total_capital: float) -> None:
        with self._lock:
            self.total_capital = total_capital

    # ------------------------------------------------------------------
    # Capital management helpers
    # ------------------------------------------------------------------

    def _class_budget(self, asset_class: AssetClass) -> float:
        """Return USD budget allocated to a given asset class."""
        alloc_map = self.allocation.to_dict()
        pct = alloc_map.get(asset_class, 0.0)
        return self.total_capital * pct

    def _class_deployed(self, asset_class: AssetClass) -> float:
        """Return USD currently deployed in positions for this asset class."""
        with self._lock:
            return sum(
                p.market_value()
                for p in self._positions.values()
                if p.asset_class == asset_class
            )

    def _class_available(self, asset_class: AssetClass) -> float:
        return max(0.0, self._class_budget(asset_class) - self._class_deployed(asset_class))

    # ------------------------------------------------------------------
    # Core execution
    # ------------------------------------------------------------------

    def execute_signal(
        self,
        signal: Dict,
        asset_class: AssetClass | str = AssetClass.CRYPTO,
        dry_run: bool = False,
    ) -> ExecutionResult:
        """
        Execute a trade signal for a given asset class.

        Args:
            signal: Dict from HedgeFundStrategyRouter.get_consensus_signal()
            asset_class: Target asset class.
            dry_run: If True, compute sizing but skip actual order submission.

        Returns:
            ExecutionResult with fill details.
        """
        if isinstance(asset_class, str):
            asset_class = AssetClass(asset_class.upper())

        symbol = signal.get("symbol", "")
        action = signal.get("action", "HOLD")
        size_pct = signal.get("suggested_size_pct", 0.0)

        if action == "HOLD":
            return ExecutionResult(True, symbol, asset_class, "HOLD", None, None, "n/a", message="HOLD — no order")

        # Risk gate
        if self.risk_gate and not self.risk_gate(signal):
            return ExecutionResult(False, symbol, asset_class, action, None, None, "risk_gate",
                                   message="Risk gate blocked trade")

        available_usd = self._class_available(asset_class)
        trade_usd = available_usd * size_pct
        adapter = self._adapters.get(asset_class)
        if adapter is None:
            return ExecutionResult(False, symbol, asset_class, action, None, None, "none",
                                   message=f"No adapter for {asset_class.value}")

        price = adapter.get_price(symbol)
        if price <= 0:
            # Try signal-supplied price hints before refusing
            price = signal.get("entry_price", signal.get("current_price", 0.0))
        if price <= 0:
            return ExecutionResult(False, symbol, asset_class, action, None, None, adapter.NAME,
                                   message="Price unavailable")

        size = trade_usd / price
        if size <= 0:
            return ExecutionResult(False, symbol, asset_class, action, None, None, adapter.NAME,
                                   message=f"Insufficient capital: available=${available_usd:.2f}")

        if dry_run:
            logger.info("[MultiAssetExecutor] DRY RUN: %s %s %.4f @ %.4f", action, symbol, size, price)
            return ExecutionResult(True, symbol, asset_class, action, price, size, adapter.NAME,
                                   message="Dry run — not submitted")

        order_resp = adapter.place_order(symbol, action, size)
        success = order_resp.get("status", "ERROR") not in ("ERROR",)
        filled_price = order_resp.get("filled_price", price)
        filled_size  = order_resp.get("filled_size", size)
        order_id     = order_resp.get("order_id")

        result = ExecutionResult(
            success=success,
            symbol=symbol,
            asset_class=asset_class,
            action=action,
            filled_price=filled_price,
            filled_size=filled_size,
            broker=adapter.NAME,
            order_id=order_id,
            message=order_resp.get("error", "OK"),
        )

        if success:
            self._record_position(result, signal)

        with self._lock:
            self._execution_log.append(result)

        logger.info("[MultiAssetExecutor] %s %s %s %.4f @ %.4f (success=%s)",
                    action, symbol, asset_class.value, filled_size or 0, filled_price or 0, success)
        return result

    def _record_position(self, result: ExecutionResult, signal: Dict) -> None:
        side = "LONG" if result.action == "BUY" else "SHORT"
        price = result.filled_price or 0.0
        sl_pct = signal.get("stop_loss_pct", 0.03)
        tp_pct = signal.get("take_profit_pct", 0.06)

        if side == "LONG":
            stop = price * (1 - sl_pct)   # stop below entry for longs
            tp   = price * (1 + tp_pct)   # target above entry for longs
        else:
            stop = price * (1 + sl_pct)   # stop above entry for shorts
            tp   = price * (1 - tp_pct)   # target below entry for shorts

        position = AssetPosition(
            symbol=result.symbol,
            asset_class=result.asset_class,
            side=side,
            size=result.filled_size or 0.0,
            entry_price=price,
            current_price=price,
            stop_loss=stop,
            take_profit=tp,
            broker=result.broker,
        )
        with self._lock:
            self._positions[result.symbol] = position

    # ------------------------------------------------------------------
    # Position management
    # ------------------------------------------------------------------

    def close_position(self, symbol: str, reason: str = "manual") -> Optional[ExecutionResult]:
        with self._lock:
            position = self._positions.pop(symbol, None)
        if position is None:
            logger.warning("[MultiAssetExecutor] No position found for %s", symbol)
            return None

        close_action = "SELL" if position.side == "LONG" else "BUY"
        adapter = self._adapters.get(position.asset_class)
        if adapter is None:
            logger.error("[MultiAssetExecutor] No adapter for %s", position.asset_class)
            return None

        order_resp = adapter.place_order(symbol, close_action, position.size)
        result = ExecutionResult(
            success=order_resp.get("status", "ERROR") != "ERROR",
            symbol=symbol,
            asset_class=position.asset_class,
            action=close_action,
            filled_price=order_resp.get("filled_price", position.current_price),
            filled_size=position.size,
            broker=adapter.NAME,
            order_id=order_resp.get("order_id"),
            message=f"closed: {reason}",
        )

        with self._lock:
            self._closed_positions.append(position)
            self._execution_log.append(result)

        logger.info("[MultiAssetExecutor] Closed %s: %s", symbol, reason)
        return result

    def update_prices(self, prices: Dict[str, float]) -> None:
        """Update current prices for all tracked positions."""
        with self._lock:
            for symbol, price in prices.items():
                if symbol in self._positions:
                    self._positions[symbol].update_price(price)

    # ------------------------------------------------------------------
    # Portfolio snapshot
    # ------------------------------------------------------------------

    def portfolio_snapshot(self) -> Dict:
        with self._lock:
            positions = [p.to_dict() for p in self._positions.values()]
            total_deployed = sum(p.market_value() for p in self._positions.values())
            total_unrealised = sum(p.unrealised_pnl for p in self._positions.values())

        class_breakdown: Dict[str, float] = {}
        for ac in AssetClass:
            deployed = self._class_deployed(ac)
            if deployed > 0:
                class_breakdown[ac.value] = round(deployed, 2)

        return {
            "total_capital": self.total_capital,
            "total_deployed_usd": round(total_deployed, 2),
            "cash_usd": round(self.total_capital - total_deployed, 2),
            "total_unrealised_pnl": round(total_unrealised, 2),
            "open_positions": len(positions),
            "class_breakdown": class_breakdown,
            "allocation_pct": {k.value: round(v, 4) for k, v in self.allocation.to_dict().items()},
            "positions": positions,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def execution_history(self, limit: int = 50) -> List[Dict]:
        with self._lock:
            return [r.to_dict() for r in self._execution_log[-limit:]]


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_executor_instance: Optional[MultiAssetExecutor] = None
_executor_lock = threading.Lock()


def get_multi_asset_executor(
    total_capital: float = 10_000.0,
    allocation: Optional[AssetAllocation] = None,
    live_brokers: Optional[Dict[AssetClass, BrokerAdapter]] = None,
    reset: bool = False,
) -> MultiAssetExecutor:
    """
    Return module-level singleton MultiAssetExecutor.

    Args:
        total_capital: Portfolio capital in USD.
        allocation:    Optional AssetAllocation.
        live_brokers:  Optional dict of AssetClass → live BrokerAdapter to replace
                       stubs.  Constructed via
                       ``bot.live_broker_adapters.build_live_adapters()``.
        reset:         If True, create a fresh instance even if one exists.
    """
    global _executor_instance
    with _executor_lock:
        if _executor_instance is None or reset:
            _executor_instance = MultiAssetExecutor(
                total_capital=total_capital,
                allocation=allocation,
                live_brokers=live_brokers,
            )
    return _executor_instance
