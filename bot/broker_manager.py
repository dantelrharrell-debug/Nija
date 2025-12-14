# bot/broker_manager.py
"""
NIJA Multi-Brokerage Manager
Supports: Coinbase, Interactive Brokers, TD Ameritrade, Alpaca, etc.
"""

from enum import Enum
from abc import ABC, abstractmethod
from typing import Dict, List, Optional
import logging
import base64
import os
import uuid
import tempfile

class BrokerType(Enum):
    COINBASE = "coinbase"
    BINANCE = "binance"
    INTERACTIVE_BROKERS = "interactive_brokers"
    TD_AMERITRADE = "td_ameritrade"
    ALPACA = "alpaca"
    TRADIER = "tradier"

class BaseBroker(ABC):
    """Base class for all broker integrations"""
    
    def __init__(self, broker_type: BrokerType):
        self.broker_type = broker_type
        self.connected = False
    
    @abstractmethod
    def connect(self) -> bool:
        """Establish connection to broker"""
        pass
    
    @abstractmethod
    def get_account_balance(self) -> float:
        """Get USD account balance"""
        pass
    
    @abstractmethod
    def place_market_order(self, symbol: str, side: str, quantity: float) -> Dict:
        """Place market order (buy/sell)"""
        pass
    
    @abstractmethod
    def get_positions(self) -> List[Dict]:
        """Get all open positions"""
        pass
    
    @abstractmethod
    def get_candles(self, symbol: str, timeframe: str, count: int) -> List[Dict]:
        """Get historical candle data"""
        pass
    
    @abstractmethod
    def supports_asset_class(self, asset_class: str) -> bool:
        """Check if broker supports asset class (crypto, stocks, futures, options)"""
        pass

class CoinbaseBroker(BaseBroker):
    """Coinbase Advanced Trade integration"""
    
    def __init__(self):
        super().__init__(BrokerType.COINBASE)
        self.client = None
    
    def connect(self) -> bool:
        """Connect to Coinbase Advanced Trade"""
        try:
            allow_consumer_usd = str(os.getenv("ALLOW_CONSUMER_USD", "")).lower() in ("1", "true", "yes")
            if allow_consumer_usd:
                logging.info("⚙️ ALLOW_CONSUMER_USD enabled — Consumer USD accounts will be counted")
            from coinbase.rest import RESTClient
            
            api_key = os.getenv("COINBASE_API_KEY")
            api_secret = os.getenv("COINBASE_API_SECRET")
            pem_content = os.getenv("COINBASE_PEM_CONTENT")
            pem_content_base64 = os.getenv("COINBASE_PEM_CONTENT_BASE64") or os.getenv("COINBASE_PEM_BASE64")
            pem_path = os.getenv("COINBASE_PEM_PATH")
            
            key_file_arg = None
            temp_pem_file = None

            # If a PEM path is provided, prefer it but verify the file exists.
            if pem_path:
                if os.path.isfile(pem_path):
                    key_file_arg = pem_path
                else:
                    print(f"⚠️ COINBASE_PEM_PATH is set but file not found: {pem_path}")
                    # Explicitly ignore the invalid path to allow fallbacks
                    pem_path = None

            # Fallback: allow PEM content (plain or base64) to be materialized to a temp file.
            if not key_file_arg:
                raw_pem = None
                if pem_content and pem_content.strip():
                    raw_pem = pem_content
                elif pem_content_base64 and pem_content_base64.strip():
                    try:
                        raw_pem = base64.b64decode(pem_content_base64).decode("utf-8")
                    except Exception as decode_err:
                        print(f"❌ Failed to decode COINBASE_PEM_CONTENT_BASE64: {decode_err}")

                # Only accept PEM if it looks like a real PEM (has header/footer)
                if raw_pem:
                    normalized = raw_pem.replace("\\n", "\n").strip()
                    if "BEGIN" in normalized and "END" in normalized:
                        temp_pem_file = tempfile.NamedTemporaryFile(delete=False, mode="w", suffix=".pem")
                        temp_pem_file.write(normalized)
                        temp_pem_file.flush()
                        key_file_arg = temp_pem_file.name
                    else:
                        print("⚠️ Provided PEM content does not contain BEGIN/END headers; ignoring.")

            # RESTClient does NOT allow both api_key and key_file. Use one OR the other.
            if key_file_arg:
                # PEM file authentication - do NOT pass api_key/api_secret to avoid conflicts.
                print("🔐 Using PEM authentication (key_file)")
                self.client = RESTClient(
                    api_key=None,
                    api_secret=None,
                    key_file=key_file_arg,
                )
            elif api_key and api_secret:
                # JWT authentication with api_key + api_secret
                print("🔐 Using API Key + Secret authentication (JWT)")
                self.client = RESTClient(
                    api_key=api_key,
                    api_secret=api_secret,
                )
            else:
                print("❌ No valid Coinbase credentials detected. Configure one of: \n- COINBASE_PEM_PATH (mounted file), or\n- COINBASE_PEM_CONTENT (full PEM), or\n- COINBASE_PEM_BASE64 (base64 PEM), or\n- COINBASE_API_KEY and COINBASE_API_SECRET (JWT).")
                return False
            
            # Test connection
            accounts = self.client.get_accounts()
            self.connected = True
            print("✅ Coinbase Advanced Trade connected")
            return True
            
        except Exception as e:
            print(f"❌ Coinbase connection failed: {e}")
            return False
    
    def get_account_balance(self):
        """Parse balances across portfolios using explicit USD/USDC rules and return a summary dict."""
        usd_balance = 0.0
        usdc_balance = 0.0
        crypto_holdings: Dict[str, float] = {}

        try:
            # Fetch portfolios (support both list_* and get_* depending on SDK version)
            portfolios_resp = None
            if hasattr(self.client, 'list_portfolios'):
                portfolios_resp = self.client.list_portfolios()
            else:
                portfolios_resp = self.client.get_portfolios()

            portfolios = getattr(portfolios_resp, 'portfolios', [])
            logging.info(f"🔥 FOUND {len(portfolios)} PORTFOLIO(S)")

            for p in portfolios:
                name = getattr(p, 'name', 'Unknown')
                uuid_val = getattr(p, 'uuid', None)
                p_type = getattr(p, 'type', 'Unknown')
                logging.info(f"🔥   Portfolio: {name} (UUID: {uuid_val}, Type: {p_type})")

                # Fetch accounts for each portfolio
                accounts_resp = None
                if hasattr(self.client, 'list_accounts'):
                    accounts_resp = self.client.list_accounts(portfolio_uuid=uuid_val)
                else:
                    accounts_resp = self.client.get_accounts(retail_portfolio_id=uuid_val)

                logging.info(f"🔥 QUERYING ACCOUNTS FROM PORTFOLIO: {uuid_val}")
                accounts = getattr(accounts_resp, 'accounts', [])

                # Fallback: if portfolio-scoped query returns no accounts, also fetch default accounts
                if not accounts:
                    try:
                        default_accounts_resp = self.client.get_accounts()
                        default_accounts = getattr(default_accounts_resp, 'accounts', [])
                        if default_accounts:
                            logging.info("⚠️ Portfolio accounts empty; including default account list for diagnostics")
                            accounts = default_accounts
                    except Exception as fallback_err:
                        logging.warning(f"⚠️ Failed default account fallback: {fallback_err}")

                for acct in accounts:
                    currency = getattr(acct, 'currency', None)
                    acct_name = (getattr(acct, 'name', '') or '').lower()
                    platform = getattr(acct, 'platform', None)

                    avail_obj = getattr(acct, 'available_balance', None)
                    hold_obj = getattr(acct, 'hold', None)
                    available = float(getattr(avail_obj, 'value', 0) or 0)
                    held = float(getattr(hold_obj, 'value', 0) or 0)

                    # Log ALL accounts to diagnose filtering
                    logging.info(
                        f"🔍 ACCT {currency} | name={getattr(acct, 'name', None)} | platform={platform} "
                        f"| avail={available} | held={held}"
                    )

                    # ✅ USDC — PRIMARY TRADING BALANCE
                    if currency == "USDC":
                        usdc_balance += available
                        logging.info(f"🔥 FOUND USDC! Available: ${available}")

                    # ✅ USD — ACCEPT CBI SPOT / ADVANCED, or Consumer if toggle enabled
                    elif currency == "USD":
                        usd_eligible = (
                            "spot" in acct_name or
                            "cbi" in acct_name or
                            platform != "ACCOUNT_PLATFORM_CONSUMER" or
                            allow_consumer_usd
                        )
                        if usd_eligible:
                            usd_balance += available
                            logging.info(f"🔥 FOUND USD (eligible) Available: ${available} | platform={platform} | name={getattr(acct, 'name', None)}")
                        else:
                            logging.warning(
                                f"⚠️ SKIPPED USD ACCOUNT (Consumer platform) | name={getattr(acct, 'name', None)} "
                                f"| platform={platform} | avail=${available}"
                            )
                    
                    # Log rejected USD accounts
                    elif currency == "USD":
                        logging.warning(
                            f"⚠️ SKIPPED USD ACCOUNT (Consumer platform) | name={getattr(acct, 'name', None)} "
                            f"| platform={platform} | avail=${available}"
                        )

                    # ✅ CRYPTO (for selling later)
                    elif currency not in ["USD", "USDC"]:
                        if available > 0:
                            crypto_holdings[currency] = available
                            logging.info(f"🔥 FOUND CRYPTO {currency}: {available}")

            # ✅ PRIORITY SELECTION
            trading_balance = usdc_balance if usdc_balance > 0 else usd_balance

            logging.info("🔥 BALANCE SUMMARY:")
            logging.info(f"   USDC: ${usdc_balance:.2f}")
            logging.info(f"   USD:  ${usd_balance:.2f}")
            logging.info(f"   Trading balance: ${trading_balance:.2f}")

            # Always log USD/USDC account inventory after scan for diagnostics
            try:
                logging.info("📋 FULL ACCOUNT INVENTORY (USD/USDC only):")
                all_resp = self.client.get_accounts()
                all_accounts = getattr(all_resp, 'accounts', [])
                found_usd_usdc = False
                for a in all_accounts:
                    curr = getattr(a, 'currency', None)
                    nm = getattr(a, 'name', None)
                    plat = getattr(a, 'platform', None)
                    av = float(getattr(getattr(a, 'available_balance', None), 'value', 0) or 0)
                    hd = float(getattr(getattr(a, 'hold', None), 'value', 0) or 0)
                    if curr in ["USD", "USDC"]:
                        found_usd_usdc = True
                        logging.info(f"   {curr} | name={nm} | platform={plat} | avail={av:.2f} | held={hd:.2f}")
                if not found_usd_usdc:
                    logging.info("   ⚠️ NO USD/USDC ACCOUNTS FOUND in default account list")
                    # If zero balance, also dump portfolio-level summary
                    if trading_balance == 0:
                        logging.info("💼 PORTFOLIO SUMMARY (all portfolios):")
                        self._dump_portfolio_summary()
            except Exception as dump_err:
                logging.warning(f"⚠️ Account inventory dump failed: {dump_err}")

            return {
                "usdc": usdc_balance,
                "usd": usd_balance,
                "trading_balance": trading_balance,
                "crypto": crypto_holdings,
            }
        except Exception as e:
            logging.error(f"🔥 ERROR get_account_balance: {e}")
            import traceback
            traceback.print_exc()
            return {
                "usdc": 0.0,
                "usd": 0.0,
                "trading_balance": 0.0,
                "crypto": {},
            }
    
    def _dump_portfolio_summary(self):
        """Diagnostic: dump all portfolios and their USD/USDC balances"""
        try:
            portfolios_resp = self.client.list_portfolios()
            portfolios = getattr(portfolios_resp, 'portfolios', [])
            for p in portfolios:
                p_name = getattr(p, 'name', 'Unknown')
                p_uuid = getattr(p, 'uuid', None)
                
                # Fetch accounts for this portfolio
                try:
                    accounts_resp = self.client.list_accounts(portfolio_uuid=p_uuid)
                    accounts = getattr(accounts_resp, 'accounts', [])
                    usd_total = 0.0
                    usdc_total = 0.0
                    for a in accounts:
                        curr = getattr(a, 'currency', None)
                        av = float(getattr(getattr(a, 'available_balance', None), 'value', 0) or 0)
                        if curr == "USD":
                            usd_total += av
                        elif curr == "USDC":
                            usdc_total += av
                    logging.info(f"   {p_name} (UUID: {p_uuid}) | USD: ${usd_total:.2f} | USDC: ${usdc_total:.2f}")
                except Exception as p_err:
                    logging.warning(f"   {p_name} — error fetching accounts: {p_err}")
        except Exception as e:
            logging.warning(f"⚠️ Portfolio summary failed: {e}")
    
    def place_market_order(self, symbol: str, side: str, quantity: float) -> Dict:
        """Place market order"""
        try:
            if quantity <= 0:
                raise ValueError(f"Refusing to place {side} order with non-positive size: {quantity}")

            client_order_id = str(uuid.uuid4())
            
            if side.lower() == 'buy':
                # Use positional client_order_id to avoid SDK signature mismatch
                order = self.client.market_order_buy(
                    client_order_id,
                    product_id=symbol,
                    quote_size=str(quantity)
                )
            else:
                order = self.client.market_order_sell(
                    client_order_id,
                    product_id=symbol,
                    base_size=str(quantity)
                )
            return {"status": "filled", "order": order}
        except Exception as e:
            print(f"Coinbase order error: {e}")
            return {"status": "error", "error": str(e)}
    
    def get_positions(self) -> List[Dict]:
        """Get open positions (Coinbase doesn't track positions, returns accounts)"""
        try:
            accounts = self.client.get_accounts()
            positions = []
            for account in accounts['accounts']:
                if account['currency'] != 'USD' and float(account['available_balance']['value']) > 0:
                    positions.append({
                        'symbol': f"{account['currency']}-USD",
                        'quantity': float(account['available_balance']['value']),
                        'currency': account['currency']
                    })
            return positions
        except Exception as e:
            print(f"Error fetching positions: {e}")
            return []
    
    def get_candles(self, symbol: str, timeframe: str, count: int) -> List[Dict]:
        """Get candle data"""
        import time
        try:
            granularity_map = {
                "1m": "ONE_MINUTE",
                "5m": "FIVE_MINUTE",
                "15m": "FIFTEEN_MINUTE",
                "1h": "ONE_HOUR",
                "1d": "ONE_DAY"
            }
            
            granularity = granularity_map.get(timeframe, "FIVE_MINUTE")
            
            end = int(time.time())
            start = end - (300 * count)  # 5 min candles
            
            candles = self.client.get_candles(
                product_id=symbol,
                start=start,
                end=end,
                granularity=granularity
            )
            
            if hasattr(candles, 'candles'):
                return [vars(c) for c in candles.candles]
            elif isinstance(candles, dict) and 'candles' in candles:
                return candles['candles']
            return []
            
        except Exception as e:
            print(f"Error fetching candles: {e}")
            return []
    
    def supports_asset_class(self, asset_class: str) -> bool:
        """Coinbase supports crypto only"""
        return asset_class.lower() == "crypto"

class AlpacaBroker(BaseBroker):
    """Alpaca integration for stocks"""
    
    def __init__(self):
        super().__init__(BrokerType.ALPACA)
        self.api = None
    
    def connect(self) -> bool:
        """Connect to Alpaca"""
        try:
            from alpaca.trading.client import TradingClient
            
            api_key = os.getenv("ALPACA_API_KEY")
            api_secret = os.getenv("ALPACA_API_SECRET")
            paper = os.getenv("ALPACA_PAPER", "true").lower() == "true"
            
            if not api_key or not api_secret:
                print("❌ Alpaca credentials not found")
                return False
            
            self.api = TradingClient(api_key, api_secret, paper=paper)
            
            # Test connection
            account = self.api.get_account()
            self.connected = True
            print(f"✅ Alpaca connected ({'PAPER' if paper else 'LIVE'})")
            return True
            
        except Exception as e:
            print(f"❌ Alpaca connection failed: {e}")
            return False
    
    def get_account_balance(self) -> float:
        """Get USD balance"""
        try:
            account = self.api.get_account()
            return float(account.cash)
        except Exception as e:
            print(f"Error fetching Alpaca balance: {e}")
            return 0.0
    
    def place_market_order(self, symbol: str, side: str, quantity: float) -> Dict:
        """Place market order"""
        try:
            from alpaca.trading.requests import MarketOrderRequest
            from alpaca.trading.enums import OrderSide, TimeInForce
            
            order_side = OrderSide.BUY if side.lower() == 'buy' else OrderSide.SELL
            
            order_data = MarketOrderRequest(
                symbol=symbol,
                qty=quantity,
                side=order_side,
                time_in_force=TimeInForce.DAY
            )
            
            order = self.api.submit_order(order_data)
            return {"status": "submitted", "order": order}
            
        except Exception as e:
            print(f"Alpaca order error: {e}")
            return {"status": "error", "error": str(e)}
    
    def get_positions(self) -> List[Dict]:
        """Get open positions"""
        try:
            positions = self.api.get_all_positions()
            return [{
                'symbol': pos.symbol,
                'quantity': float(pos.qty),
                'avg_entry_price': float(pos.avg_entry_price),
                'market_value': float(pos.market_value),
                'unrealized_pl': float(pos.unrealized_pl)
            } for pos in positions]
        except Exception as e:
            print(f"Error fetching positions: {e}")
            return []
    
    def get_candles(self, symbol: str, timeframe: str, count: int) -> List[Dict]:
        """Get candle data"""
        try:
            from alpaca.data.historical import StockHistoricalDataClient
            from alpaca.data.requests import StockBarsRequest
            from alpaca.data.timeframe import TimeFrame
            from datetime import datetime, timedelta
            
            api_key = os.getenv("ALPACA_API_KEY")
            api_secret = os.getenv("ALPACA_API_SECRET")
            
            data_client = StockHistoricalDataClient(api_key, api_secret)
            
            timeframe_map = {
                "1m": TimeFrame.Minute,
                "5m": TimeFrame(5, TimeFrame.Minute),
                "15m": TimeFrame(15, TimeFrame.Minute),
                "1h": TimeFrame.Hour,
                "1d": TimeFrame.Day
            }
            
            tf = timeframe_map.get(timeframe, TimeFrame(5, TimeFrame.Minute))
            
            request_params = StockBarsRequest(
                symbol_or_symbols=symbol,
                timeframe=tf,
                start=datetime.now() - timedelta(days=7)
            )
            
            bars = data_client.get_stock_bars(request_params)
            
            candles = []
            for bar in bars[symbol]:
                candles.append({
                    'time': bar.timestamp,
                    'open': float(bar.open),
                    'high': float(bar.high),
                    'low': float(bar.low),
                    'close': float(bar.close),
                    'volume': float(bar.volume)
                })
            
            return candles[-count:] if len(candles) > count else candles
            
        except Exception as e:
            print(f"Error fetching candles: {e}")
            return []
    
    def supports_asset_class(self, asset_class: str) -> bool:
        """Alpaca supports stocks"""
        return asset_class.lower() in ["stocks", "stock"]

class BinanceBroker(BaseBroker):
    """Binance integration for crypto and futures (PLACEHOLDER)"""
    """
    Binance integration for crypto trading (SKELETON - PLACEHOLDER)
    
    To implement:
    1. Install binance-connector: pip install binance-connector
    2. Set environment variables: BINANCE_API_KEY, BINANCE_API_SECRET
    3. Uncomment and implement methods below
    
    Documentation: https://github.com/binance/binance-connector-python
    """
    
    def __init__(self):
        super().__init__(BrokerType.BINANCE)
        self.client = None
    
    def connect(self) -> bool:
        """
        Connect to Binance
        
        This is a placeholder implementation. To use Binance:
        1. Install python-binance: pip install python-binance
        2. Set BINANCE_API_KEY and BINANCE_API_SECRET environment variables
        3. Uncomment and implement the connection logic below
        """
        print("⚠️ Binance broker is a placeholder - not yet implemented")
        print("To enable Binance:")
        print("  1. pip install python-binance")
        print("  2. Set BINANCE_API_KEY and BINANCE_API_SECRET")
        print("  3. Implement connection logic in broker_manager.py")
        
        # Placeholder - would implement actual connection here
        # try:
        #     from binance.client import Client
        #     
        #     api_key = os.getenv("BINANCE_API_KEY")
        #     api_secret = os.getenv("BINANCE_API_SECRET")
        #     
        #     if not api_key or not api_secret:
        #         print("❌ Binance credentials not found")
        #         return False
        #     
        #     self.client = Client(api_key, api_secret)
        #     
        #     # Test connection
        #     self.client.get_account()
        #     self.connected = True
        #     print("✅ Binance connected")
        #     return True
        #     
        # except Exception as e:
        #     print(f"❌ Binance connection failed: {e}")
        #     return False
        
        return False
    
    def get_account_balance(self) -> float:
        """Get USD balance (placeholder)"""
        if not self.connected:
            return 0.0
        
        # Placeholder - would fetch actual balance
        print("⚠️ Binance get_account_balance not implemented")
        return 0.0
    
    def place_market_order(self, symbol: str, side: str, quantity: float) -> Dict:
        """Place market order (placeholder)"""
        print("⚠️ Binance place_market_order not implemented")
        return {"status": "error", "error": "Binance broker not implemented"}
    
    def get_positions(self) -> List[Dict]:
        """Get open positions (placeholder)"""
        if not self.connected:
            return []
        
        print("⚠️ Binance get_positions not implemented")
        return []
    
    def get_candles(self, symbol: str, timeframe: str, count: int) -> List[Dict]:
        """Get candle data (placeholder)"""
        print("⚠️ Binance get_candles not implemented")
        return []
    
    def supports_asset_class(self, asset_class: str) -> bool:
        """Binance supports crypto and futures"""
        return asset_class.lower() in ["crypto", "futures"]
        """Connect to Binance (SKELETON)"""
        try:
            # TODO: Uncomment when binance-connector is installed
            # from binance.spot import Spot
            
            api_key = os.getenv("BINANCE_API_KEY")
            api_secret = os.getenv("BINANCE_API_SECRET")
            
            if not api_key or not api_secret:
                print("❌ Binance credentials not found (set BINANCE_API_KEY and BINANCE_API_SECRET)")
                return False
            
            # TODO: Initialize Binance client
            # self.client = Spot(api_key=api_key, api_secret=api_secret)
            
            # TODO: Test connection
            # account = self.client.account()
            # self.connected = True
            # print("✅ Binance connected")
            
            print("⚠️  Binance integration is a skeleton - implement connection logic")
            return False
            
        except Exception as e:
            print(f"❌ Binance connection failed: {e}")
            return False
    
    def get_account_balance(self) -> float:
        """Get USD balance (SKELETON)"""
        try:
            if not self.client:
                return 0.0
            
            # TODO: Implement balance fetching
            # account = self.client.account()
            # for balance in account['balances']:
            #     if balance['asset'] == 'USDT':
            #         return float(balance['free'])
            
            return 0.0
        except Exception as e:
            print(f"Error fetching Binance balance: {e}")
            return 0.0
    
    def place_market_order(self, symbol: str, side: str, quantity: float) -> Dict:
        """Place market order (SKELETON)"""
        try:
            if not self.client:
                return {"status": "error", "error": "Not connected"}
            
            # TODO: Implement order placement
            # Convert symbol format (e.g., BTC-USD -> BTCUSDT)
            # binance_symbol = symbol.replace('-', '')
            
            # order = self.client.new_order(
            #     symbol=binance_symbol,
            #     side=side.upper(),
            #     type='MARKET',
            #     quantity=quantity
            # )
            
            # return {"status": "filled", "order": order}
            
            return {"status": "error", "error": "Skeleton implementation"}
            
        except Exception as e:
            print(f"Binance order error: {e}")
            return {"status": "error", "error": str(e)}
    
    def get_positions(self) -> List[Dict]:
        """Get open positions (SKELETON)"""
        try:
            if not self.client:
                return []
            
            # TODO: Implement position fetching
            # account = self.client.account()
            # positions = []
            # for balance in account['balances']:
            #     if float(balance['free']) > 0 and balance['asset'] != 'USDT':
            #         positions.append({
            #             'symbol': f"{balance['asset']}USDT",
            #             'quantity': float(balance['free']),
            #             'currency': balance['asset']
            #         })
            # return positions
            
            return []
        except Exception as e:
            print(f"Error fetching positions: {e}")
            return []
    
    def get_candles(self, symbol: str, timeframe: str, count: int) -> List[Dict]:
        """Get candle data (SKELETON)"""
        try:
            if not self.client:
                return []
            
            # TODO: Implement candle fetching
            # Convert symbol and timeframe
            # binance_symbol = symbol.replace('-', '')
            # interval_map = {
            #     "1m": "1m",
            #     "5m": "5m",
            #     "15m": "15m",
            #     "1h": "1h",
            #     "1d": "1d"
            # }
            
            # klines = self.client.klines(
            #     symbol=binance_symbol,
            #     interval=interval_map.get(timeframe, "5m"),
            #     limit=count
            # )
            
            # candles = []
            # for k in klines:
            #     candles.append({
            #         'time': k[0],
            #         'open': float(k[1]),
            #         'high': float(k[2]),
            #         'low': float(k[3]),
            #         'close': float(k[4]),
            #         'volume': float(k[5])
            #     })
            
            # return candles
            
            return []
            
        except Exception as e:
            print(f"Error fetching candles: {e}")
            return []
    
    def supports_asset_class(self, asset_class: str) -> bool:
        """Binance supports crypto"""
        return asset_class.lower() == "crypto"

class BrokerManager:
    """Manages multiple broker connections"""
    
    def __init__(self):
        self.brokers: Dict[BrokerType, BaseBroker] = {}
        self.active_broker: Optional[BaseBroker] = None
    
    def add_broker(self, broker: BaseBroker):
        """Add a broker to the manager"""
        self.brokers[broker.broker_type] = broker
        print(f"📊 Added {broker.broker_type.value} broker")
    
    def connect_all(self):
        """Connect to all configured brokers"""
        print("\n🔌 Connecting to brokers...")
        for broker in self.brokers.values():
            broker.connect()
    
    def get_broker_for_symbol(self, symbol: str) -> Optional[BaseBroker]:
        """Get appropriate broker for a symbol"""
        from market_adapter import market_adapter
        
        # Detect market type
        market_type = market_adapter.detect_market_type(symbol)
        
        # Map to asset class
        asset_class_map = {
            "crypto": "crypto",
            "stocks": "stocks",
            "futures": "futures",
            "options": "options"
        }
        
        asset_class = asset_class_map.get(market_type.value, "stocks")
        
        # Find broker that supports this asset class
        for broker in self.brokers.values():
            if broker.connected and broker.supports_asset_class(asset_class):
                return broker
        
        return None
    
    def place_order(self, symbol: str, side: str, quantity: float) -> Dict:
        """Route order to appropriate broker"""
        broker = self.get_broker_for_symbol(symbol)
        
        if not broker:
            return {
                "status": "error",
                "error": f"No broker available for {symbol}"
            }
        
        print(f"📤 Routing {side} order for {symbol} to {broker.broker_type.value}")
        return broker.place_market_order(symbol, side, quantity)
    
    def get_total_balance(self) -> float:
        """Get total USD balance across all brokers"""
        total = 0.0
        for broker in self.brokers.values():
            if broker.connected:
                total += broker.get_account_balance()
        return total
    
    def get_all_positions(self) -> List[Dict]:
        """Get positions from all brokers"""
        all_positions = []
        for broker_type, broker in self.brokers.items():
            if broker.connected:
                positions = broker.get_positions()
                for pos in positions:
                    pos['broker'] = broker_type.value
                all_positions.extend(positions)
        return all_positions
    
    def get_connected_brokers(self) -> List[str]:
        """Get list of connected broker names"""
        return [b.broker_type.value for b in self.brokers.values() if b.connected]

# Global instance
broker_manager = BrokerManager()
