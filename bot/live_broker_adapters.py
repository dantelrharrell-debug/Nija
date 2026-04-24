"""
NIJA Live Broker Adapters
=========================

Production-ready broker adapters that wire the MultiAssetExecutor to live
trading APIs for equities, futures, options, and treasury profit extraction.

Supported backends
------------------
Equities  : Alpaca (REST + WebSocket)
Futures   : Interactive Brokers (via ib_insync) with Alpaca futures fallback
Options   : Tradier REST API
Treasury  : Configurable sweep via wire/ACH (pluggable bank connector)

Each adapter follows the BrokerAdapter interface defined in
``bot/multi_asset_executor.py`` and can be registered with
``MultiAssetExecutor.register_broker()``.

Usage
-----
    from bot.live_broker_adapters import build_live_adapters
    from bot.multi_asset_executor import get_multi_asset_executor, AssetClass

    adapters = build_live_adapters()
    executor = get_multi_asset_executor(total_capital=50_000)
    for asset_class, adapter in adapters.items():
        executor.register_broker(asset_class, adapter)

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional, Tuple

from bot.multi_asset_executor import AssetClass, BrokerAdapter

logger = logging.getLogger("nija.live_broker_adapters")


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# 1. Alpaca Equity Broker Adapter (live wiring)
# ---------------------------------------------------------------------------

class AlpacaEquityBrokerAdapter(BrokerAdapter):
    """
    Live equity adapter backed by Alpaca's commission-free REST API.

    Credentials are read from environment variables:
      - ALPACA_API_KEY
      - ALPACA_API_SECRET
      - ALPACA_PAPER (set to "false" for live trading; default = "true")

    Supports market and limit orders, fractional shares (qty < 1.0),
    real-time quotes, and position queries.
    """

    NAME = "alpaca_equity"
    SUPPORTED_ASSET_CLASSES = (AssetClass.EQUITY,)

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        paper: bool = True,
    ):
        self._api_key = api_key or os.getenv("ALPACA_API_KEY", "")
        self._api_secret = api_secret or os.getenv("ALPACA_API_SECRET", "")
        self._paper = paper if api_key else (os.getenv("ALPACA_PAPER", "true").lower() != "false")
        self._client = None
        self._data_client = None
        self._lock = threading.Lock()
        self._connected = False
        self._connect()

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def _connect(self) -> None:
        if not self._api_key or not self._api_secret:
            logger.warning("[AlpacaEquity] Credentials not configured — adapter in stub mode")
            return
        try:
            from alpaca.trading.client import TradingClient
            from alpaca.data.historical import StockHistoricalDataClient

            self._client = TradingClient(
                api_key=self._api_key,
                secret_key=self._api_secret,
                paper=self._paper,
            )
            self._data_client = StockHistoricalDataClient(self._api_key, self._api_secret)
            account = self._client.get_account()
            self._connected = True
            logger.info(
                "[AlpacaEquity] Connected (paper=%s) equity=$%.2f buying_power=$%.2f",
                self._paper, _safe_float(account.equity), _safe_float(account.buying_power),
            )
        except ImportError:
            logger.warning("[AlpacaEquity] alpaca-py not installed; run: pip install alpaca-py")
        except Exception as exc:
            logger.error("[AlpacaEquity] Connection failed: %s", exc)

    # ------------------------------------------------------------------
    # BrokerAdapter interface
    # ------------------------------------------------------------------

    def place_order(
        self,
        symbol: str,
        side: str,
        size: float,
        order_type: str = "MARKET",
        limit_price: Optional[float] = None,
    ) -> Dict:
        """
        Place an equity order on Alpaca.

        Supports fractional shares when size < 1.0 (uses 'notional' qty mode
        for fractional; integer shares use 'qty' mode).
        """
        if not self._connected or self._client is None:
            return self._stub_fill(symbol, side, size)

        try:
            from alpaca.trading.requests import MarketOrderRequest, LimitOrderRequest
            from alpaca.trading.enums import OrderSide as AlpacaSide, TimeInForce

            alpaca_side = AlpacaSide.BUY if side.upper() == "BUY" else AlpacaSide.SELL

            # Fractional share support: use qty for whole shares, notional otherwise
            use_fractional = size < 1.0 or (size != int(size))

            if order_type.upper() == "LIMIT" and limit_price:
                req = LimitOrderRequest(
                    symbol=symbol,
                    qty=size,
                    side=alpaca_side,
                    time_in_force=TimeInForce.DAY,
                    limit_price=limit_price,
                )
            else:
                if use_fractional:
                    # Alpaca fractional: pass qty as float
                    req = MarketOrderRequest(
                        symbol=symbol,
                        qty=round(size, 6),
                        side=alpaca_side,
                        time_in_force=TimeInForce.DAY,
                    )
                else:
                    req = MarketOrderRequest(
                        symbol=symbol,
                        qty=int(size),
                        side=alpaca_side,
                        time_in_force=TimeInForce.DAY,
                    )

            with self._lock:
                order = self._client.submit_order(order_data=req)

            logger.info("[AlpacaEquity] Order submitted: %s %s %.4f id=%s", side, symbol, size, order.id)
            return {
                "order_id": str(order.id),
                "status": str(order.status),
                "filled_price": _safe_float(getattr(order, "filled_avg_price", None)),
                "filled_size": size,
                "broker": self.NAME,
                "timestamp": _now_iso(),
            }

        except Exception as exc:
            logger.error("[AlpacaEquity] place_order error: %s", exc)
            return {"error": str(exc), "status": "ERROR"}

    def get_price(self, symbol: str) -> float:
        if not self._connected or self._data_client is None:
            return 0.0
        try:
            from alpaca.data.requests import StockLatestTradeRequest

            req = StockLatestTradeRequest(symbol_or_symbols=symbol)
            trades = self._data_client.get_stock_latest_trade(req)
            return _safe_float(trades[symbol].price) if symbol in trades else 0.0
        except Exception as exc:
            logger.error("[AlpacaEquity] get_price error: %s", exc)
            return 0.0

    def cancel_order(self, order_id: str) -> bool:
        if not self._connected or self._client is None:
            return True
        try:
            self._client.cancel_order_by_id(order_id)
            return True
        except Exception as exc:
            logger.error("[AlpacaEquity] cancel_order error: %s", exc)
            return False

    def get_account_balance(self) -> float:
        if not self._connected or self._client is None:
            return 0.0
        try:
            account = self._client.get_account()
            return _safe_float(account.equity)
        except Exception as exc:
            logger.error("[AlpacaEquity] get_account_balance error: %s", exc)
            return 0.0

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _stub_fill(self, symbol: str, side: str, size: float) -> Dict:
        logger.warning("[AlpacaEquity] Stub fill (not connected): %s %s %.4f", side, symbol, size)
        return {
            "order_id": f"stub_{uuid.uuid4().hex[:8]}",
            "status": "SIMULATED",
            "filled_price": 0.0,
            "filled_size": size,
            "broker": self.NAME,
        }


# ---------------------------------------------------------------------------
# 2. Interactive Brokers Futures Adapter
# ---------------------------------------------------------------------------

class InteractiveBrokersFuturesAdapter(BrokerAdapter):
    """
    Live futures adapter backed by Interactive Brokers TWS / Gateway via
    the ``ib_insync`` library.

    Credentials / connection
    ------------------------
    Interactive Brokers uses TWS or IB Gateway (running locally or on a VPS).
    Set environment variables:
      - IB_HOST      (default: "127.0.0.1")
      - IB_PORT      (default: 7497 for paper, 7496 for live)
      - IB_CLIENT_ID (default: 1)

    Supports:
    - Market / limit futures orders
    - Leveraged futures (E-mini S&P, crude oil, gold, BTC futures on CME, etc.)
    - Real-time bid/ask via IB snapshot quotes
    """

    NAME = "interactive_brokers_futures"
    SUPPORTED_ASSET_CLASSES = (AssetClass.FUTURES,)

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        client_id: Optional[int] = None,
    ):
        self._host = host or os.getenv("IB_HOST", "127.0.0.1")
        self._port = port or int(os.getenv("IB_PORT", "7497"))
        self._client_id = client_id or int(os.getenv("IB_CLIENT_ID", "1"))
        self._ib = None
        self._lock = threading.Lock()
        self._connected = False
        self._connect()

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def _connect(self) -> None:
        try:
            import ib_insync as ibi  # type: ignore

            self._ib = ibi.IB()
            self._ib.connect(self._host, self._port, clientId=self._client_id, timeout=10)
            self._connected = True
            logger.info(
                "[IBFutures] Connected to IB Gateway at %s:%s (clientId=%s)",
                self._host, self._port, self._client_id,
            )
        except ImportError:
            logger.warning("[IBFutures] ib_insync not installed; run: pip install ib_insync")
        except Exception as exc:
            logger.error("[IBFutures] Connection failed: %s", exc)

    # ------------------------------------------------------------------
    # BrokerAdapter interface
    # ------------------------------------------------------------------

    def place_order(
        self,
        symbol: str,
        side: str,
        size: float,
        order_type: str = "MARKET",
        limit_price: Optional[float] = None,
    ) -> Dict:
        """
        Place a futures order via IB.

        symbol format: ``ES2506`` (symbol + expiry YYMM) or ``BTC`` for crypto futures.
        The adapter maps NIJA symbol strings to IB Contract objects.
        """
        if not self._connected or self._ib is None:
            return self._stub_fill(symbol, side, size)

        try:
            import ib_insync as ibi

            contract = self._build_contract(symbol)
            action = "BUY" if side.upper() == "BUY" else "SELL"
            qty = int(max(1, round(size)))

            if order_type.upper() == "LIMIT" and limit_price:
                order = ibi.LimitOrder(action, qty, limit_price)
            else:
                order = ibi.MarketOrder(action, qty)

            with self._lock:
                trade = self._ib.placeOrder(contract, order)
                # Allow time for order to register
                self._ib.sleep(0.5)

            logger.info(
                "[IBFutures] Order placed: %s %s %d contract(s) orderId=%s",
                action, symbol, qty, trade.order.orderId,
            )
            return {
                "order_id": str(trade.order.orderId),
                "status": str(trade.orderStatus.status),
                "filled_price": _safe_float(trade.orderStatus.avgFillPrice),
                "filled_size": qty,
                "broker": self.NAME,
                "timestamp": _now_iso(),
            }

        except Exception as exc:
            logger.error("[IBFutures] place_order error: %s", exc)
            return {"error": str(exc), "status": "ERROR"}

    def get_price(self, symbol: str) -> float:
        if not self._connected or self._ib is None:
            return 0.0
        try:
            import ib_insync as ibi

            contract = self._build_contract(symbol)
            ticker = self._ib.reqMktData(contract, "", True, False)
            self._ib.sleep(1.0)
            mid = ((_safe_float(ticker.bid) + _safe_float(ticker.ask)) / 2
                   if ticker.bid and ticker.ask else _safe_float(ticker.last))
            self._ib.cancelMktData(contract)
            return mid
        except Exception as exc:
            logger.error("[IBFutures] get_price error: %s", exc)
            return 0.0

    def cancel_order(self, order_id: str) -> bool:
        if not self._connected or self._ib is None:
            return True
        try:
            import ib_insync as ibi

            trades = self._ib.trades()
            for trade in trades:
                if str(trade.order.orderId) == str(order_id):
                    self._ib.cancelOrder(trade.order)
                    return True
            logger.warning("[IBFutures] Order %s not found to cancel", order_id)
            return False
        except Exception as exc:
            logger.error("[IBFutures] cancel_order error: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_contract(self, symbol: str):
        """
        Convert a NIJA symbol string to an IB Future contract.

        Mapping examples:
          ES2506  → E-mini S&P 500 expiry Jun 2025
          BTC     → CME Bitcoin Futures (continuous)
          GC      → Gold futures (continuous)
          CL      → Crude Oil futures (continuous)
        """
        try:
            import ib_insync as ibi

            _EXCHANGE_MAP: Dict[str, Tuple[str, str]] = {
                "ES": ("CME", "USD"),
                "NQ": ("CME", "USD"),
                "RTY": ("CME", "USD"),
                "CL": ("NYMEX", "USD"),
                "GC": ("COMEX", "USD"),
                "SI": ("COMEX", "USD"),
                "BTC": ("CME", "USD"),
                "ETH": ("CME", "USD"),
            }
            root = symbol[:2] if len(symbol) >= 2 else symbol
            exchange, currency = _EXCHANGE_MAP.get(root.upper(), ("CME", "USD"))
            contract = ibi.Future(symbol=symbol, exchange=exchange, currency=currency)
            return contract
        except Exception:
            import ib_insync as ibi
            return ibi.Future(symbol=symbol, exchange="CME", currency="USD")

    def _stub_fill(self, symbol: str, side: str, size: float) -> Dict:
        logger.warning("[IBFutures] Stub fill (not connected): %s %s %.0f", side, symbol, size)
        return {
            "order_id": f"stub_{uuid.uuid4().hex[:8]}",
            "status": "SIMULATED",
            "filled_price": 0.0,
            "filled_size": size,
            "broker": self.NAME,
        }


# ---------------------------------------------------------------------------
# 3. Tradier Options Broker Adapter
# ---------------------------------------------------------------------------

class TradierOptionsAdapter(BrokerAdapter):
    """
    Live options adapter backed by the Tradier brokerage REST API.

    Credentials (environment variables):
      - TRADIER_API_TOKEN   (Bearer token from Tradier dashboard)
      - TRADIER_PAPER       ("true" / "false"; default "true")

    Supports:
    - Market / limit options orders (buy/sell to open/close)
    - Option chain quotes
    - Greeks retrieval
    - Standard, barrier, and exotic option orders (as supported by Tradier)
    """

    NAME = "tradier_options"
    SUPPORTED_ASSET_CLASSES = (AssetClass.OPTIONS,)

    _PAPER_BASE = "https://sandbox.tradier.com/v1"
    _LIVE_BASE  = "https://api.tradier.com/v1"

    def __init__(
        self,
        api_token: Optional[str] = None,
        paper: bool = True,
    ):
        self._token = api_token or os.getenv("TRADIER_API_TOKEN", "")
        self._paper = paper if api_token else (os.getenv("TRADIER_PAPER", "true").lower() != "false")
        self._base_url = self._PAPER_BASE if self._paper else self._LIVE_BASE
        self._headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
        }
        self._lock = threading.Lock()
        self._connected = bool(self._token)
        if self._connected:
            logger.info("[TradierOptions] Adapter ready (paper=%s)", self._paper)
        else:
            logger.warning("[TradierOptions] No API token — adapter in stub mode")

    # ------------------------------------------------------------------
    # BrokerAdapter interface
    # ------------------------------------------------------------------

    def place_order(
        self,
        symbol: str,
        side: str,
        size: float,
        order_type: str = "MARKET",
        limit_price: Optional[float] = None,
    ) -> Dict:
        """
        Place an options order via Tradier.

        symbol format: ``AAPL250117C00150000`` (OCC option symbol).
        side: BUY_TO_OPEN / SELL_TO_CLOSE / BUY_TO_CLOSE / SELL_TO_OPEN
              or plain BUY / SELL (mapped to BUY_TO_OPEN / SELL_TO_CLOSE).
        size: number of contracts.
        """
        if not self._connected:
            return self._stub_fill(symbol, side, size)

        try:
            import requests

            # Map plain BUY/SELL to Tradier option side strings
            _SIDE_MAP = {
                "BUY":          "buy_to_open",
                "SELL":         "sell_to_close",
                "BUY_TO_OPEN":  "buy_to_open",
                "BUY_TO_CLOSE": "buy_to_close",
                "SELL_TO_OPEN": "sell_to_open",
                "SELL_TO_CLOSE":"sell_to_close",
            }
            tradier_side = _SIDE_MAP.get(side.upper(), "buy_to_open")
            duration = "day"
            qty = max(1, int(round(size)))

            payload: Dict = {
                "class":    "option",
                "symbol":   symbol[:10] if len(symbol) > 10 else symbol,  # underlying
                "option_symbol": symbol,
                "side":     tradier_side,
                "quantity": qty,
                "type":     "limit" if order_type.upper() == "LIMIT" and limit_price else "market",
                "duration": duration,
            }
            if limit_price and order_type.upper() == "LIMIT":
                payload["price"] = limit_price

            with self._lock:
                resp = requests.post(
                    f"{self._base_url}/accounts/{self._account_id()}/orders",
                    data=payload,
                    headers=self._headers,
                    timeout=10,
                )
                resp.raise_for_status()
                data = resp.json()

            order_data = data.get("order", {})
            order_id = str(order_data.get("id", uuid.uuid4().hex[:8]))
            status = order_data.get("status", "submitted")

            logger.info("[TradierOptions] Order: %s %s %d contract(s) id=%s", side, symbol, qty, order_id)
            return {
                "order_id": order_id,
                "status": status,
                "filled_price": 0.0,  # filled price comes via order status poll
                "filled_size": qty,
                "broker": self.NAME,
                "timestamp": _now_iso(),
            }

        except Exception as exc:
            logger.error("[TradierOptions] place_order error: %s", exc)
            return {"error": str(exc), "status": "ERROR"}

    def get_price(self, symbol: str) -> float:
        """
        Fetch last trade price for an option symbol (OCC format).
        Falls back to mid of bid/ask if last is unavailable.
        """
        if not self._connected:
            return 0.0
        try:
            import requests

            resp = requests.get(
                f"{self._base_url}/markets/options/chains",
                params={"symbol": symbol[:10], "expiration": ""},
                headers=self._headers,
                timeout=10,
            )
            if resp.status_code != 200:
                return 0.0
            data = resp.json()
            options = data.get("options", {}).get("option", [])
            for opt in options:
                if opt.get("symbol") == symbol:
                    last = _safe_float(opt.get("last", 0))
                    bid = _safe_float(opt.get("bid", 0))
                    ask = _safe_float(opt.get("ask", 0))
                    return last if last > 0 else ((bid + ask) / 2 if bid and ask else 0.0)
            return 0.0
        except Exception as exc:
            logger.error("[TradierOptions] get_price error: %s", exc)
            return 0.0

    def cancel_order(self, order_id: str) -> bool:
        if not self._connected:
            return True
        try:
            import requests

            resp = requests.delete(
                f"{self._base_url}/accounts/{self._account_id()}/orders/{order_id}",
                headers=self._headers,
                timeout=10,
            )
            return resp.status_code == 200
        except Exception as exc:
            logger.error("[TradierOptions] cancel_order error: %s", exc)
            return False

    def get_option_chain(self, underlying: str, expiration: str) -> List[Dict]:
        """
        Return option chain for underlying and expiration date (YYYY-MM-DD).
        """
        if not self._connected:
            return []
        try:
            import requests

            resp = requests.get(
                f"{self._base_url}/markets/options/chains",
                params={"symbol": underlying, "expiration": expiration, "greeks": "true"},
                headers=self._headers,
                timeout=10,
            )
            if resp.status_code != 200:
                return []
            data = resp.json()
            return data.get("options", {}).get("option", [])
        except Exception as exc:
            logger.error("[TradierOptions] get_option_chain error: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _account_id(self) -> str:
        """Retrieve account ID (cached)."""
        if hasattr(self, "_cached_account_id"):
            return self._cached_account_id
        try:
            import requests

            resp = requests.get(
                f"{self._base_url}/user/profile",
                headers=self._headers,
                timeout=10,
            )
            data = resp.json()
            accounts = data.get("profile", {}).get("account", [])
            if isinstance(accounts, dict):
                accounts = [accounts]
            acct_id = str(accounts[0].get("account_number", "")) if accounts else ""
            self._cached_account_id = acct_id
            return acct_id
        except Exception:
            return ""

    def _stub_fill(self, symbol: str, side: str, size: float) -> Dict:
        logger.warning("[TradierOptions] Stub fill (not connected): %s %s %.0f", side, symbol, size)
        return {
            "order_id": f"stub_{uuid.uuid4().hex[:8]}",
            "status": "SIMULATED",
            "filled_price": 0.0,
            "filled_size": size,
            "broker": self.NAME,
        }


# ---------------------------------------------------------------------------
# 4. Treasury / Bank Profit Extraction Module
# ---------------------------------------------------------------------------

class TreasuryProfitExtractor:
    """
    Automates profit extraction sweeps from the trading account to a
    designated treasury or bank account.

    Supported backends
    ------------------
    - Alpaca ACH transfer (via Alpaca's funding API)
    - Stripe Payouts (for platform-model revenue)
    - Custom webhook (call any configured endpoint)

    Extraction policy
    -----------------
    When ``extract_profit()`` is called with a realized PnL amount:
    1. Applies the configured extraction ratio (default 20 % of profit).
    2. Checks the minimum transfer threshold (default $500).
    3. Dispatches the transfer via the configured backend.
    4. Logs an audit record.

    Environment variables
    ---------------------
    TREASURY_BACKEND        : "alpaca_ach" | "stripe" | "webhook" | "log_only"
    TREASURY_EXTRACTION_PCT : fraction of profit to sweep (0.0–1.0, default 0.20)
    TREASURY_MIN_USD        : minimum transfer amount (default 500.0)
    TREASURY_ACH_RELATION_ID: Alpaca ACH relationship ID (for alpaca_ach backend)
    STRIPE_API_KEY          : Stripe secret key (for stripe backend)
    TREASURY_WEBHOOK_URL    : URL for webhook backend
    """

    def __init__(
        self,
        backend: Optional[str] = None,
        extraction_pct: Optional[float] = None,
        min_transfer_usd: Optional[float] = None,
    ):
        self._backend = backend or os.getenv("TREASURY_BACKEND", "log_only")
        self._extraction_pct = extraction_pct or float(os.getenv("TREASURY_EXTRACTION_PCT", "0.20"))
        self._min_usd = min_transfer_usd or float(os.getenv("TREASURY_MIN_USD", "500.0"))
        self._audit_log: List[Dict] = []
        self._lock = threading.Lock()
        logger.info(
            "[Treasury] Extractor initialized (backend=%s, pct=%.0f%%, min=$%.0f)",
            self._backend, self._extraction_pct * 100, self._min_usd,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def extract_profit(self, realized_pnl: float, source: str = "trading") -> Dict:
        """
        Attempt to extract a fraction of ``realized_pnl`` to the treasury.

        Returns a result dict with keys: success, amount, backend, message.
        """
        if realized_pnl <= 0:
            return {"success": False, "amount": 0.0, "message": "No profit to extract"}

        amount = realized_pnl * self._extraction_pct
        if amount < self._min_usd:
            return {
                "success": False,
                "amount": amount,
                "message": f"Amount ${amount:.2f} below minimum ${self._min_usd:.2f}",
            }

        result = self._dispatch(amount, source)
        audit = {
            "timestamp": _now_iso(),
            "realized_pnl": realized_pnl,
            "amount": amount,
            "backend": self._backend,
            "source": source,
            "result": result,
        }
        with self._lock:
            self._audit_log.append(audit)

        logger.info(
            "[Treasury] Extraction: $%.2f (%.0f%% of $%.2f pnl) via %s → %s",
            amount, self._extraction_pct * 100, realized_pnl, self._backend,
            "OK" if result.get("success") else result.get("message", "FAILED"),
        )
        return result

    def audit_trail(self, limit: int = 100) -> List[Dict]:
        """Return last N audit records."""
        with self._lock:
            return list(self._audit_log[-limit:])

    def total_extracted(self) -> float:
        """Return cumulative USD successfully extracted."""
        with self._lock:
            return sum(
                r["amount"] for r in self._audit_log
                if r.get("result", {}).get("success")
            )

    # ------------------------------------------------------------------
    # Backend dispatchers
    # ------------------------------------------------------------------

    def _dispatch(self, amount: float, source: str) -> Dict:
        if self._backend == "alpaca_ach":
            return self._alpaca_ach(amount)
        if self._backend == "stripe":
            return self._stripe_payout(amount)
        if self._backend == "webhook":
            return self._webhook(amount, source)
        # Default: log_only
        logger.info("[Treasury] log_only: would transfer $%.2f", amount)
        return {"success": True, "amount": amount, "message": "log_only — no transfer made"}

    def _alpaca_ach(self, amount: float) -> Dict:
        """Transfer funds via Alpaca ACH funding API."""
        try:
            import requests

            api_key = os.getenv("ALPACA_API_KEY", "")
            api_secret = os.getenv("ALPACA_API_SECRET", "")
            ach_id = os.getenv("TREASURY_ACH_RELATION_ID", "")
            paper = os.getenv("ALPACA_PAPER", "true").lower() != "false"
            base = "https://paper-api.alpaca.markets" if paper else "https://api.alpaca.markets"

            if not api_key or not ach_id:
                return {"success": False, "message": "Missing ALPACA_API_KEY or TREASURY_ACH_RELATION_ID"}

            resp = requests.post(
                f"{base}/v2/account/ach/transfers",
                json={
                    "transfer_type": "outgoing",
                    "relationship_id": ach_id,
                    "amount": str(round(amount, 2)),
                    "direction": "OUTGOING",
                },
                auth=(api_key, api_secret),
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            return {"success": True, "amount": amount, "transfer_id": data.get("id"), "message": "ACH initiated"}

        except Exception as exc:
            return {"success": False, "amount": amount, "message": str(exc)}

    def _stripe_payout(self, amount: float) -> Dict:
        """Create a Stripe payout for the given amount."""
        try:
            import stripe  # type: ignore

            stripe.api_key = os.getenv("STRIPE_API_KEY", "")
            if not stripe.api_key:
                return {"success": False, "message": "Missing STRIPE_API_KEY"}

            payout = stripe.Payout.create(
                amount=int(amount * 100),  # Stripe uses cents
                currency="usd",
                description=f"NIJA treasury extraction ${amount:.2f}",
            )
            return {"success": True, "amount": amount, "payout_id": payout.id, "message": "Stripe payout created"}

        except Exception as exc:
            return {"success": False, "amount": amount, "message": str(exc)}

    def _webhook(self, amount: float, source: str) -> Dict:
        """POST extraction event to a configured webhook URL."""
        try:
            import requests

            url = os.getenv("TREASURY_WEBHOOK_URL", "")
            if not url:
                return {"success": False, "message": "Missing TREASURY_WEBHOOK_URL"}

            payload = {
                "event": "treasury_extraction",
                "amount": amount,
                "source": source,
                "timestamp": _now_iso(),
            }
            resp = requests.post(url, json=payload, timeout=10)
            resp.raise_for_status()
            return {"success": True, "amount": amount, "message": f"Webhook delivered (status {resp.status_code})"}

        except Exception as exc:
            return {"success": False, "amount": amount, "message": str(exc)}


# ---------------------------------------------------------------------------
# Factory helper
# ---------------------------------------------------------------------------

def build_live_adapters(
    equity_paper: bool = True,
    futures_host: Optional[str] = None,
    futures_port: Optional[int] = None,
    options_paper: bool = True,
) -> Dict[AssetClass, BrokerAdapter]:
    """
    Instantiate and return all live broker adapters keyed by AssetClass.

    Pass these to ``MultiAssetExecutor.register_broker()`` to replace the
    default stubs with live API connections.

    Example::

        adapters = build_live_adapters(equity_paper=False, options_paper=False)
        for ac, adapter in adapters.items():
            executor.register_broker(ac, adapter)
    """
    return {
        AssetClass.EQUITY:  AlpacaEquityBrokerAdapter(paper=equity_paper),
        AssetClass.FUTURES: InteractiveBrokersFuturesAdapter(
            host=futures_host, port=futures_port
        ),
        AssetClass.OPTIONS: TradierOptionsAdapter(paper=options_paper),
    }


# ---------------------------------------------------------------------------
# Module-level treasury singleton
# ---------------------------------------------------------------------------

_treasury_instance: Optional[TreasuryProfitExtractor] = None
_treasury_lock = threading.Lock()


def get_treasury_extractor() -> TreasuryProfitExtractor:
    """Return module-level singleton TreasuryProfitExtractor."""
    global _treasury_instance
    with _treasury_lock:
        if _treasury_instance is None:
            _treasury_instance = TreasuryProfitExtractor()
    return _treasury_instance
