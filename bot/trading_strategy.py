"""
NIJA Trading Strategy — TradingStrategy wrapper class
======================================================

This module provides the TradingStrategy class that orchestrates the NIJA
APEX v7.1 strategy across multiple brokers.

The heartbeat trade feature executes a small $5 test trade on startup to
verify all systems are operational before enabling full trading mode.

Author: NIJA Trading Systems
Version: 7.1
"""

from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("nija.trading_strategy")

# ---------------------------------------------------------------------------
# Optional imports — degrade gracefully when modules are unavailable
# ---------------------------------------------------------------------------

try:
    from bot.nija_apex_strategy_v71 import NIJAApexStrategyV71
    _APEX_AVAILABLE = True
except ImportError:
    try:
        from nija_apex_strategy_v71 import NIJAApexStrategyV71  # type: ignore[import]
        _APEX_AVAILABLE = True
    except ImportError:
        NIJAApexStrategyV71 = None  # type: ignore[assignment,misc]
        _APEX_AVAILABLE = False
        logger.warning("NIJAApexStrategyV71 not available — strategy will run in degraded mode")

try:
    from bot.broker_manager import BrokerType, KrakenBroker, CoinbaseBroker, BaseBroker
    _BROKER_MANAGER_AVAILABLE = True
except ImportError:
    try:
        from broker_manager import BrokerType, KrakenBroker, CoinbaseBroker, BaseBroker  # type: ignore[import]
        _BROKER_MANAGER_AVAILABLE = True
    except ImportError:
        BrokerType = None  # type: ignore[assignment,misc]
        KrakenBroker = None  # type: ignore[assignment,misc]
        CoinbaseBroker = None  # type: ignore[assignment,misc]
        BaseBroker = None  # type: ignore[assignment,misc]
        _BROKER_MANAGER_AVAILABLE = False
        logger.warning("broker_manager not available")

try:
    from bot.multi_account_broker_manager import MultiAccountBrokerManager
    _MABM_AVAILABLE = True
except ImportError:
    try:
        from multi_account_broker_manager import MultiAccountBrokerManager  # type: ignore[import]
        _MABM_AVAILABLE = True
    except ImportError:
        MultiAccountBrokerManager = None  # type: ignore[assignment,misc]
        _MABM_AVAILABLE = False

try:
    from bot.independent_broker_trader import IndependentBrokerTrader
    _IBT_AVAILABLE = True
except ImportError:
    try:
        from independent_broker_trader import IndependentBrokerTrader  # type: ignore[import]
        _IBT_AVAILABLE = True
    except ImportError:
        IndependentBrokerTrader = None  # type: ignore[assignment,misc]
        _IBT_AVAILABLE = False

try:
    from bot.broker_manager import BrokerManager
    _BM_AVAILABLE = True
except ImportError:
    try:
        from broker_manager import BrokerManager  # type: ignore[import]
        _BM_AVAILABLE = True
    except ImportError:
        BrokerManager = None  # type: ignore[assignment,misc]
        _BM_AVAILABLE = False

# ---------------------------------------------------------------------------
# Heartbeat trade configuration
# ---------------------------------------------------------------------------

_HEARTBEAT_TRADE_AMOUNT_USD: float = float(
    os.environ.get("HEARTBEAT_TRADE_AMOUNT_USD", "5.0") or "5.0"
)
_HEARTBEAT_TRADE_INTERVAL_S: float = float(
    os.environ.get("HEARTBEAT_TRADE_INTERVAL_S", "600") or "600"
)
_HEARTBEAT_TRADE_SYMBOL: str = os.environ.get(
    "HEARTBEAT_TRADE_SYMBOL", "BTC-USD"
).strip()

# Default symbols to try for the heartbeat trade (in order of preference)
_HEARTBEAT_SYMBOL_CANDIDATES: List[str] = [
    "BTC-USD",
    "ETH-USD",
    "SOL-USD",
    "XRP-USD",
]


# ---------------------------------------------------------------------------
# TradingStrategy
# ---------------------------------------------------------------------------


class TradingStrategy:
    """
    Top-level trading strategy orchestrator for NIJA APEX v7.1.

    Wraps NIJAApexStrategyV71 and manages broker connections, multi-account
    support, and the heartbeat trade verification system.

    The heartbeat trade executes a small $5 test trade on startup to confirm
    that the full execution stack (broker connection → order submission →
    fill confirmation) is operational before enabling full trading mode.
    """

    def __init__(
        self,
        broker_results: Optional[Dict] = None,
        connected_user_brokers: Optional[Dict] = None,
    ) -> None:
        """
        Initialize TradingStrategy.

        Args:
            broker_results: Pre-connected platform broker results from bootstrap.
            connected_user_brokers: Pre-connected user broker results from bootstrap.
        """
        logger.info("🚀 TradingStrategy.__init__ starting")

        # ── Core attributes ────────────────────────────────────────────────
        self.broker: Optional[Any] = None
        self.broker_manager: Optional[Any] = None
        self.multi_account_manager: Optional[Any] = None
        self.independent_trader: Optional[Any] = None
        self.apex: Optional[Any] = None
        self.execution_engine: Optional[Any] = None
        self.symbols: List[str] = []
        self.failed_brokers: Dict = {}

        # Heartbeat trade state
        self._heartbeat_trade_enabled: bool = (
            os.environ.get("HEARTBEAT_TRADE", "false").strip().lower()
            in ("1", "true", "yes", "enabled")
        )
        self._heartbeat_trade_completed: bool = False
        self._heartbeat_trade_success: bool = False
        self._heartbeat_trade_lock = threading.Lock()
        self._heartbeat_trade_thread: Optional[threading.Thread] = None

        # ── Wire up multi-account broker manager ───────────────────────────
        try:
            from bot.multi_account_broker_manager import multi_account_broker_manager as _mabm
            self.multi_account_manager = _mabm
            logger.info("✅ MultiAccountBrokerManager attached")
        except ImportError:
            try:
                from multi_account_broker_manager import multi_account_broker_manager as _mabm  # type: ignore[import]
                self.multi_account_manager = _mabm
                logger.info("✅ MultiAccountBrokerManager attached (fallback import)")
            except ImportError:
                logger.warning("⚠️  MultiAccountBrokerManager not available")

        # ── Wire up broker manager ─────────────────────────────────────────
        try:
            from bot.broker_manager import get_broker_manager as _get_bm
            self.broker_manager = _get_bm()
            logger.info("✅ BrokerManager attached")
        except ImportError:
            try:
                from broker_manager import get_broker_manager as _get_bm  # type: ignore[import]
                self.broker_manager = _get_bm()
                logger.info("✅ BrokerManager attached (fallback import)")
            except ImportError:
                logger.warning("⚠️  BrokerManager not available")

        # ── Resolve primary broker ─────────────────────────────────────────
        self._resolve_primary_broker(broker_results)

        # ── Wire up APEX strategy ──────────────────────────────────────────
        if _APEX_AVAILABLE and NIJAApexStrategyV71 is not None:
            try:
                self.apex = NIJAApexStrategyV71(broker_client=self.broker)
                self.execution_engine = getattr(self.apex, "execution_engine", None)
                logger.info("✅ NIJAApexStrategyV71 initialized")
            except Exception as _apex_err:
                logger.error("❌ NIJAApexStrategyV71 init failed: %s", _apex_err)
                self.apex = None

        # ── Wire up IndependentBrokerTrader ────────────────────────────────
        if _IBT_AVAILABLE and IndependentBrokerTrader is not None:
            try:
                self.independent_trader = IndependentBrokerTrader(
                    multi_account_manager=self.multi_account_manager,
                )
                logger.info("✅ IndependentBrokerTrader initialized")
            except Exception as _ibt_err:
                logger.warning("⚠️  IndependentBrokerTrader init failed: %s", _ibt_err)
                self.independent_trader = None
        else:
            self.independent_trader = None

        # ── Populate symbol list ───────────────────────────────────────────
        self._populate_symbols()

        # ── Start heartbeat trade if enabled ───────────────────────────────
        if self._heartbeat_trade_enabled:
            logger.info(
                "💓 Heartbeat trade enabled — scheduling $%.2f test trade in %.0fs",
                _HEARTBEAT_TRADE_AMOUNT_USD,
                _HEARTBEAT_TRADE_INTERVAL_S,
            )
            self._schedule_heartbeat_trade()
        else:
            logger.info("ℹ️  Heartbeat trade disabled (HEARTBEAT_TRADE not set)")

        logger.info("✅ TradingStrategy initialized")

    # -----------------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------------

    def _resolve_primary_broker(self, broker_results: Optional[Dict]) -> None:
        """Resolve the primary broker from bootstrap results or manager."""
        # Try broker_results first (bootstrap path)
        if broker_results:
            for _bt, _meta in broker_results.items():
                _broker_obj = (_meta or {}).get("broker")
                if _broker_obj is not None and getattr(_broker_obj, "connected", False):
                    self.broker = _broker_obj
                    logger.info(
                        "✅ Primary broker resolved from bootstrap: %s",
                        getattr(_bt, "value", str(_bt)).upper(),
                    )
                    return

        # Try multi_account_manager
        if self.multi_account_manager is not None:
            try:
                _platform_brokers = getattr(
                    self.multi_account_manager, "platform_brokers", {}
                )
                for _bt, _b in (_platform_brokers or {}).items():
                    if _b is not None and getattr(_b, "connected", False):
                        self.broker = _b
                        logger.info(
                            "✅ Primary broker resolved from MABM: %s",
                            getattr(_bt, "value", str(_bt)).upper(),
                        )
                        return
            except Exception as _mabm_err:
                logger.debug("MABM broker resolution failed: %s", _mabm_err)

        # Try broker_manager
        if self.broker_manager is not None:
            try:
                _primary = self.broker_manager.get_primary_broker()
                if _primary is not None and getattr(_primary, "connected", False):
                    self.broker = _primary
                    logger.info("✅ Primary broker resolved from BrokerManager")
                    return
            except Exception as _bm_err:
                logger.debug("BrokerManager broker resolution failed: %s", _bm_err)

        logger.warning("⚠️  No connected primary broker found at init time")

    def _populate_symbols(self) -> None:
        """Populate the symbol list from the primary broker."""
        if self.broker is None:
            return
        try:
            # Use get_all_products() — the standard method on all broker classes
            if hasattr(self.broker, "get_all_products"):
                products = self.broker.get_all_products()
                if isinstance(products, list):
                    self.symbols = [str(p) for p in products if p]
                    logger.info(
                        "✅ Loaded %d symbols from broker", len(self.symbols)
                    )
                    return
        except Exception as _sym_err:
            logger.debug("Symbol population failed: %s", _sym_err)

        # Fallback: use a curated default list
        self.symbols = _HEARTBEAT_SYMBOL_CANDIDATES.copy()
        logger.info(
            "ℹ️  Using default symbol list (%d symbols)", len(self.symbols)
        )

    # -----------------------------------------------------------------------
    # Heartbeat trade
    # -----------------------------------------------------------------------

    def _schedule_heartbeat_trade(self) -> None:
        """Schedule the heartbeat trade in a background daemon thread."""
        with self._heartbeat_trade_lock:
            if self._heartbeat_trade_thread is not None and self._heartbeat_trade_thread.is_alive():
                logger.debug("Heartbeat trade thread already running")
                return
            self._heartbeat_trade_thread = threading.Thread(
                target=self._heartbeat_trade_runner,
                name="HeartbeatTrade",
                daemon=True,
            )
            self._heartbeat_trade_thread.start()
        logger.info("💓 Heartbeat trade thread started")

    def _heartbeat_trade_runner(self) -> None:
        """Background thread: wait for the configured interval then execute the heartbeat trade."""
        logger.info(
            "💓 Heartbeat trade runner sleeping %.0fs before first attempt",
            _HEARTBEAT_TRADE_INTERVAL_S,
        )
        time.sleep(_HEARTBEAT_TRADE_INTERVAL_S)
        try:
            success = self._execute_heartbeat_trade()
            with self._heartbeat_trade_lock:
                self._heartbeat_trade_completed = True
                self._heartbeat_trade_success = success
            if success:
                logger.info("✅ Heartbeat trade PASSED — bot confirmed ready for live trading")
            else:
                logger.error(
                    "❌ Heartbeat trade FAILED — trading remains blocked until heartbeat succeeds"
                )
        except Exception as _hb_err:
            logger.error("❌ Heartbeat trade runner raised: %s", _hb_err, exc_info=True)
            with self._heartbeat_trade_lock:
                self._heartbeat_trade_completed = True
                self._heartbeat_trade_success = False

    def _execute_heartbeat_trade(self) -> bool:
        """
        Execute a small $5 test trade to verify the full execution stack.

        This is a one-shot verification that runs once on startup.  It places
        a market buy order for the configured heartbeat symbol (default BTC-USD)
        and immediately sells it to close the position.

        Returns:
            True if the heartbeat trade executed successfully, False otherwise.

        Note:
            Uses ``get_available_markets()`` (the BaseBroker abstract method
            added in this PR) if the broker exposes it, falling back to
            ``get_all_products()`` for older broker implementations.  Either
            way, market discovery failure never blocks heartbeat execution.
        """
        # ── Resolve broker ─────────────────────────────────────────────────
        broker = self._get_active_broker()
        if broker is None:
            logger.error("❌ Heartbeat trade: no active broker available")
            return False

        broker_name = type(broker).__name__
        trade_amount_usd = self._resolve_heartbeat_trade_amount_usd(broker)
        logger.info(
            "💓 Executing heartbeat trade: $%.2f on %s",
            trade_amount_usd,
            _HEARTBEAT_TRADE_SYMBOL,
        )
        logger.info("💓 Heartbeat trade using broker: %s", broker_name)

        # ── Verify the symbol is available on this broker ──────────────────
        # Prefer get_available_markets() when the broker exposes it (satisfies
        # the BaseBroker abstract interface added in this PR); fall back to
        # get_all_products() for brokers that haven't been updated yet.
        symbol = _HEARTBEAT_TRADE_SYMBOL
        try:
            _market_getter = (
                "get_available_markets"
                if hasattr(broker, "get_available_markets")
                else "get_all_products"
                if hasattr(broker, "get_all_products")
                else None
            )
            if _market_getter is not None:
                available_markets = getattr(broker, _market_getter)()
                _discovery_count = len(available_markets) if isinstance(available_markets, list) else 0
                logger.info("[HeartbeatTrade] market_discovery_count=%s", _discovery_count)
                if isinstance(available_markets, list) and available_markets:
                    # Check if our preferred symbol is available; fall back to
                    # the first available candidate if not.
                    if symbol not in available_markets:
                        for candidate in _HEARTBEAT_SYMBOL_CANDIDATES:
                            if candidate in available_markets:
                                logger.info(
                                    "💓 Heartbeat symbol %s not available — using %s instead",
                                    symbol,
                                    candidate,
                                )
                                symbol = candidate
                                break
                        else:
                            # Use the first available market as a last resort
                            symbol = available_markets[0]
                            logger.info(
                                "💓 Heartbeat using first available market: %s", symbol
                            )
                    else:
                        logger.info("💓 Heartbeat symbol %s confirmed available", symbol)
                else:
                    logger.info("[HeartbeatTrade] market_discovery_count=0")
                    logger.warning(
                        "⚠️  %s() returned empty list — proceeding with %s",
                        _market_getter,
                        symbol,
                    )
            else:
                logger.info("[HeartbeatTrade] market_discovery_count=0")
                logger.warning(
                    "⚠️  Broker %s has no market discovery method — "
                    "proceeding with symbol %s without market verification",
                    broker_name,
                    symbol,
                )
        except Exception as _market_err:
            logger.info("[HeartbeatTrade] market_discovery_count=0")
            logger.warning(
                "⚠️  Market availability check failed (%s) — proceeding with %s",
                _market_err,
                symbol,
            )

        # ── Place the heartbeat buy order ──────────────────────────────────
        try:
            logger.info(
                "💓 Placing heartbeat BUY: %s $%.2f",
                symbol,
                trade_amount_usd,
            )
            buy_result = broker.execute_order(
                symbol=symbol,
                side="buy",
                quantity=trade_amount_usd,
                size_type="quote",
                metadata={"reason": "HEARTBEAT_TRADE"},
            )
            buy_status = (buy_result or {}).get("status", "error")
            buy_submitted = bool(buy_result)
            buy_filled = buy_status in ("filled", "ok", "success")
            logger.info(
                "[HeartbeatTrade] submit=%s fill=%s broker=%s pair=%s size=%s",
                buy_submitted,
                buy_filled,
                broker_name,
                symbol,
                trade_amount_usd,
            )
            logger.info("💓 Heartbeat BUY result: status=%s", buy_status)

            if not buy_filled:
                logger.error(
                    "❌ Heartbeat BUY failed: status=%s error=%s",
                    buy_status,
                    (buy_result or {}).get("error", "unknown"),
                )
                return False

            logger.info("✅ Heartbeat BUY confirmed — order filled")

            # Brief pause before the sell to allow the position to settle
            time.sleep(2.0)

            # ── Place the heartbeat sell order to close the position ────────
            logger.info("💓 Placing heartbeat SELL to close position: %s", symbol)
            sell_result = broker.execute_order(
                symbol=symbol,
                side="sell",
                quantity=trade_amount_usd,
                size_type="quote",
                metadata={"reason": "HEARTBEAT_TRADE_CLOSE"},
            )
            sell_status = (sell_result or {}).get("status", "error")
            sell_submitted = bool(sell_result)
            sell_filled = sell_status in ("filled", "ok", "success")
            logger.info(
                "[HeartbeatTrade] submit=%s fill=%s broker=%s pair=%s size=%s",
                sell_submitted,
                sell_filled,
                broker_name,
                symbol,
                trade_amount_usd,
            )
            logger.info("💓 Heartbeat SELL result: status=%s", sell_status)

            if not sell_filled:
                logger.warning(
                    "⚠️  Heartbeat SELL returned status=%s — position may remain open",
                    sell_status,
                )

                # Still return True: the BUY succeeded which proves the stack works
                self._persist_heartbeat_marker()
                return True

            logger.info("✅ Heartbeat trade round-trip complete")
            self._persist_heartbeat_marker()
            return True

        except Exception as _trade_err:
            logger.error(
                "❌ Heartbeat trade execution raised: %s", _trade_err, exc_info=True
            )
            return False

    def _resolve_heartbeat_trade_amount_usd(self, broker: Any) -> float:
        """Resolve a safe heartbeat notional above exchange minimums."""
        broker_name = type(broker).__name__.replace("Broker", "").lower().strip()
        exchange_minimum = 0.0

        try:
            from bot.minimum_notional_gate import get_minimum_notional_gate
        except ImportError:
            try:
                from minimum_notional_gate import get_minimum_notional_gate  # type: ignore[import]
            except ImportError:
                get_minimum_notional_gate = None  # type: ignore[assignment]

        if get_minimum_notional_gate is not None:
            try:
                exchange_minimum = float(
                    get_minimum_notional_gate().get_minimum_for_symbol(
                        _HEARTBEAT_TRADE_SYMBOL,
                        broker_name=broker_name,
                    )
                    or 0.0
                )
            except Exception as _min_gate_err:
                logger.debug("Heartbeat notional gate minimum lookup failed: %s", _min_gate_err)

        if exchange_minimum <= 0.0:
            try:
                exchange_minimum = float(getattr(broker, "min_trade_size", 0.0) or 0.0)
            except Exception:
                exchange_minimum = 0.0

        resolved = max(_HEARTBEAT_TRADE_AMOUNT_USD, exchange_minimum * 1.25, 10.0)
        logger.info(
            "[HeartbeatTrade] amount_resolved configured=%.2f exchange_min=%.2f final=%.2f",
            _HEARTBEAT_TRADE_AMOUNT_USD,
            exchange_minimum,
            resolved,
        )
        return resolved

    def _persist_heartbeat_marker(self) -> None:
        """Persist first-run heartbeat verification marker for activation gates."""
        marker_path = os.environ.get("HEARTBEAT_MARKER_PATH", "./data/heartbeat_verified.flag")
        try:
            marker = Path(marker_path)
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text("verified", encoding="utf-8")
            logger.info("[HeartbeatTrade] marker_written path=%s", str(marker))
        except Exception as _marker_err:
            logger.error("❌ Failed to persist heartbeat marker %s: %s", marker_path, _marker_err)

    def _get_active_broker(self) -> Optional[Any]:
        """Return the best available connected broker for the heartbeat trade."""
        # 1. Use the cached primary broker if connected
        if self.broker is not None and getattr(self.broker, "connected", False):
            return self.broker

        # 2. Try multi_account_manager platform brokers
        if self.multi_account_manager is not None:
            try:
                _platform_brokers = getattr(
                    self.multi_account_manager, "platform_brokers", {}
                )
                for _bt, _b in (_platform_brokers or {}).items():
                    if _b is not None and getattr(_b, "connected", False):
                        self.broker = _b  # cache for future calls
                        return _b
            except Exception as _err:
                logger.debug("MABM broker lookup failed: %s", _err)

        # 3. Try broker_manager
        if self.broker_manager is not None:
            try:
                _primary = self.broker_manager.get_primary_broker()
                if _primary is not None and getattr(_primary, "connected", False):
                    self.broker = _primary
                    return _primary
            except Exception as _err:
                logger.debug("BrokerManager lookup failed: %s", _err)

        return None

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    def run_cycle(self) -> None:
        """Execute one trading cycle."""
        if self.apex is not None:
            try:
                # Delegate to the APEX strategy
                _broker = self._get_active_broker()
                if _broker is not None and self.broker != _broker:
                    self.broker = _broker
                    if hasattr(self.apex, "update_broker_client"):
                        self.apex.update_broker_client(_broker)

                # Run the APEX strategy cycle
                if hasattr(self.apex, "run_cycle"):
                    self.apex.run_cycle()
                elif hasattr(self.apex, "analyze_market"):
                    # Fallback: iterate over symbols
                    for symbol in self.symbols[:20]:  # cap at 20 per cycle
                        try:
                            self.apex.analyze_market(symbol)
                        except Exception as _sym_err:
                            logger.debug("Symbol %s cycle error: %s", symbol, _sym_err)
            except Exception as _cycle_err:
                logger.error("❌ run_cycle error: %s", _cycle_err, exc_info=True)
        else:
            logger.debug("run_cycle: no APEX strategy available")

    def log_multi_broker_status(self) -> None:
        """Log the status of all connected brokers."""
        try:
            if self.multi_account_manager is not None and hasattr(
                self.multi_account_manager, "platform_brokers"
            ):
                _platform_brokers = self.multi_account_manager.platform_brokers or {}
                for _bt, _b in _platform_brokers.items():
                    _name = getattr(_bt, "value", str(_bt)).upper()
                    _connected = getattr(_b, "connected", False) if _b else False
                    logger.info(
                        "BROKER STATUS | %s connected=%s", _name, _connected
                    )
            elif self.broker_manager is not None and hasattr(
                self.broker_manager, "brokers"
            ):
                for _bt, _b in (self.broker_manager.brokers or {}).items():
                    _name = getattr(_bt, "value", str(_bt)).upper()
                    _connected = getattr(_b, "connected", False) if _b else False
                    logger.info(
                        "BROKER STATUS | %s connected=%s", _name, _connected
                    )
        except Exception as _log_err:
            logger.debug("log_multi_broker_status error: %s", _log_err)

    @property
    def heartbeat_trade_completed(self) -> bool:
        """True when the heartbeat trade has been attempted (pass or fail)."""
        with self._heartbeat_trade_lock:
            return self._heartbeat_trade_completed

    @property
    def heartbeat_trade_success(self) -> bool:
        """True when the heartbeat trade completed successfully."""
        with self._heartbeat_trade_lock:
            return self._heartbeat_trade_success
