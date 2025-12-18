# bot/broker_manager.py
"""
NIJA Multi-Brokerage Manager
Supports: Coinbase, Interactive Brokers, TD Ameritrade, Alpaca, etc.
"""

from enum import Enum
from abc import ABC, abstractmethod
from typing import Dict, List, Optional
import logging
import os
import uuid

# Configure logger for broker operations
logger = logging.getLogger('nija.broker')

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
        # Read ALLOW_CONSUMER_USD flag once during initialization
        # Default to True to ensure Consumer USD balances are counted unless explicitly disabled.
        allow_flag = os.getenv("ALLOW_CONSUMER_USD")
        if allow_flag is None:
            self.allow_consumer_usd = True
            logging.info("⚙️ ALLOW_CONSUMER_USD defaulted to true — Consumer USD accounts will be counted")
        else:
            self.allow_consumer_usd = str(allow_flag).lower() in ("1", "true", "yes")
    
    def connect(self) -> bool:
        """Connect to Coinbase Advanced Trade using JWT authentication"""
        try:
            # Advanced Trade SDK uses JWT tokens signed with EC private keys
            if self.allow_consumer_usd:
                logging.info("⚙️ ALLOW_CONSUMER_USD enabled — Consumer USD accounts will be counted")
            
            from coinbase.rest import RESTClient
            
            # Get credentials
            api_key = os.getenv("COINBASE_API_KEY")
            api_secret = os.getenv("COINBASE_API_SECRET")
            
            print(f"🔍 CREDENTIAL CHECK:")
            print(f"   - COINBASE_API_KEY: {'✅ Set' if api_key else '❌ Missing'}")
            print(f"   - COINBASE_API_SECRET: {'✅ Set' if api_secret else '❌ Missing'}")
            
            if not api_key or not api_secret:
                print("❌ Missing required credentials!")
                print("   Set COINBASE_API_KEY and COINBASE_API_SECRET")
                return False
            
            # Normalize PEM key if it has escaped newlines
            if api_secret and '\\n' in api_secret:
                api_secret = api_secret.replace('\\n', '\n')
                print("   ℹ️  Normalized escaped newlines in API_SECRET")
            
            # Create RESTClient
            print("🔐 Initializing Coinbase RESTClient...")
            self.client = RESTClient(
                api_key=api_key,
                api_secret=api_secret,
            )
            
            # Test connection
            print("🧪 Testing connection with GET /v3/accounts...")
            accounts = self.client.get_accounts()
            self.connected = True
            print("✅ Coinbase Advanced Trade connected")
            return True
            
        except Exception as e:
            error_str = str(e)
            print(f"❌ Coinbase connection failed: {e}")
            
            # Show response details if available
            response = getattr(e, "response", None)
            if response:
                status_code = getattr(response, "status_code", None)
                if status_code:
                    print(f"   HTTP Status: {status_code}")
                try:
                    response_text = response.text
                    if response_text:
                        print(f"   Response: {response_text[:300]}")
                except Exception:
                    pass
            
            # Authentication error guidance
            if "401" in error_str or "Unauthorized" in error_str:
                print(f"\n🔴 AUTHENTICATION FAILED")
                print(f"   Possible causes:")
                print(f"   1. Invalid API Key or Secret")
                print(f"   2. Incorrect credentials format")
                print(f"   3. Expired or revoked API key")
                print(f"   4. Missing required permissions")
                print(f"\n   Required env variables:")
                print(f"   - COINBASE_API_KEY")
                print(f"   - COINBASE_API_SECRET")
            
            return False
    
    def get_account_balance(self):
        """Parse balances using v2 API (shows retail balances) with v3 fallback"""
        usd_balance = 0.0
        usdc_balance = 0.0
        crypto_holdings: Dict[str, float] = {}

        try:
            # Try v2 API first (shows retail/consumer balances)
            try:
                import requests
                import time
                import jwt
                from cryptography.hazmat.primitives import serialization
                
                api_key = os.getenv("COINBASE_API_KEY")
                api_secret = os.getenv("COINBASE_API_SECRET")
                
                # Normalize PEM
                if '\\n' in api_secret:
                    api_secret = api_secret.replace('\\n', '\n')
                
                private_key = serialization.load_pem_private_key(api_secret.encode('utf-8'), password=None)
                
                # Make v2 API call
                uri = "GET api.coinbase.com/v2/accounts"
                payload = {
                    'sub': api_key,
                    'iss': 'coinbase-cloud',
                    'nbf': int(time.time()),
                    'exp': int(time.time()) + 120,
                    'aud': ['coinbase-apis'],
                    'uri': uri
                }
                token = jwt.encode(payload, private_key, algorithm='ES256', 
                                  headers={'kid': api_key, 'nonce': str(int(time.time()))})
                headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
                response = requests.get(f"https://api.coinbase.com/v2/accounts", headers=headers)
                
                if response.status_code == 200:
                    data = response.json()
                    v2_accounts = data.get('data', [])
                    logging.info(f"📋 Using v2 API - found {len(v2_accounts)} accounts")
                    
                    for acc in v2_accounts:
                        currency = acc.get('currency', {}).get('code', '')
                        balance_data = acc.get('balance', {})
                        amount = float(balance_data.get('amount', 0))
                        
                        if currency == 'USD':
                            usd_balance += amount
                            if amount > 0:
                                logging.info(f"   ✅ USD: ${amount:.2f} ({acc.get('name', 'Unknown')})")
                        elif currency == 'USDC':
                            usdc_balance += amount
                            if amount > 0:
                                logging.info(f"   ✅ USDC: ${amount:.2f} ({acc.get('name', 'Unknown')})")
                        elif amount > 0:
                            crypto_holdings[currency] = amount
                else:
                    logging.warning(f"v2 API returned {response.status_code}, falling back to v3")
                    raise Exception("v2 API failed")
                    
            except Exception as v2_error:
                logging.warning(f"v2 API unavailable ({v2_error}), using v3 brokerage API")
                # Fall back to v3 API
                accounts_resp = self.client.list_accounts() if hasattr(self.client, 'list_accounts') else self.client.get_accounts()
                accounts = getattr(accounts_resp, 'accounts', [])
                logging.info(f"📁 Retrieved {len(accounts)} account(s) from v3 API")

                for account in accounts:
                    currency = getattr(account, 'currency', None)
                    available_obj = getattr(account, 'available_balance', None)
                    available = float(getattr(available_obj, 'value', 0) or 0)

                    # Accept ALL USD and USDC balances (including CONSUMER)
                    if currency == "USD":
                        usd_balance += available
                        logging.info(f"   ✅ USD: ${available:.2f}")
                    elif currency == "USDC":
                        usdc_balance += available
                        logging.info(f"   ✅ USDC: ${available:.2f}")
                    elif available > 0:
                        crypto_holdings[currency] = available

            trading_balance = usdc_balance if usdc_balance > 0 else usd_balance

            logging.info("=" * 70)
            logging.info("💰 TOTAL BALANCE:")
            logging.info(f"   USD:  ${usd_balance:.2f}")
            logging.info(f"   USDC: ${usdc_balance:.2f}")
            logging.info(f"   TRADING BALANCE: ${trading_balance:.2f}")
            logging.info("=" * 70)

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
            accounts_resp = self.client.get_accounts()
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
            logging.info(f"   Default portfolio | USD: ${usd_total:.2f} | USDC: ${usdc_total:.2f}")
        except Exception as e:
            logging.warning(f"⚠️ Portfolio summary failed: {e}")

    def get_usd_usdc_inventory(self) -> list[str]:
        """Return a formatted USD/USDC inventory for logging by callers.

        This method mirrors the inventory logic used by diagnostics but returns
        strings so the caller can log with its own logger configuration
        (important because some apps only attach handlers to the 'nija' logger).
        """
        lines: list[str] = []
        try:
            resp = self.client.get_accounts()
            accounts = getattr(resp, 'accounts', []) or (resp.get('accounts', []) if isinstance(resp, dict) else [])
            usd_total = 0.0
            usdc_total = 0.0

            def _as_float(v):
                try:
                    return float(v)
                except Exception:
                    return 0.0

            for a in accounts:
                if isinstance(a, dict):
                    currency = a.get('currency')
                    name = a.get('name')
                    platform = a.get('platform')
                    av = (a.get('available_balance') or {}).get('value')
                    hd = (a.get('hold') or {}).get('value')
                else:
                    currency = getattr(a, 'currency', None)
                    name = getattr(a, 'name', None)
                    platform = getattr(a, 'platform', None)
                    av = getattr(getattr(a, 'available_balance', None), 'value', None)
                    hd = getattr(getattr(a, 'hold', None), 'value', None)

                if currency in ("USD", "USDC"):
                    avf = _as_float(av)
                    hdf = _as_float(hd)
                    lines.append(f"{currency:>4} | name={name} | platform={platform} | avail={avf:>10.2f} | held={hdf:>10.2f}")
                    if currency == "USD":
                        usd_total += avf
                    else:
                        usdc_total += avf

            lines.append("-" * 70)
            trading = usdc_total if usdc_total > 0 else usd_total
            lines.append(f"Totals → USD: ${usd_total:.2f} | USDC: ${usdc_total:.2f} | Trading Balance: ${trading:.2f}")
            if usd_total == 0.0 and usdc_total == 0.0:
                lines.append("👉 Move funds into your Advanced Trade portfolio: https://www.coinbase.com/advanced-portfolio")
        except Exception as e:
            lines.append(f"⚠️ Failed to fetch USD/USDC inventory: {e}")

        return lines
    
    def place_market_order(self, symbol: str, side: str, quantity: float) -> Dict:
        """Place market order"""
        try:
            if quantity <= 0:
                raise ValueError(f"Refusing to place {side} order with non-positive size: {quantity}")

            client_order_id = str(uuid.uuid4())
            
            if side.lower() == 'buy':
                # Use positional client_order_id to avoid SDK signature mismatch
                logger.info(f"📤 Placing BUY order: {symbol}, quote_size=${quantity:.2f}")
                order = self.client.market_order_buy(
                    client_order_id,
                    product_id=symbol,
                    quote_size=str(quantity)
                )
            else:
                logger.info(f"📤 Placing SELL order: {symbol}, base_size={quantity:.8f}")
                order = self.client.market_order_sell(
                    client_order_id,
                    product_id=symbol,
                    base_size=str(quantity)
                )
            logger.info(f"✅ Order placed successfully: {symbol}")
            return {"status": "filled", "order": order}
        except Exception as e:
            # Enhanced error logging with full details
            error_msg = str(e)
            error_type = type(e).__name__
            logger.error(f"🚨 Coinbase order error for {symbol}:")
            logger.error(f"   Type: {error_type}")
            logger.error(f"   Message: {error_msg}")
            logger.error(f"   Side: {side}, Quantity: {quantity}")
            
            # Log additional context if available
            if hasattr(e, 'response'):
                logger.error(f"   Response: {e.response}")
            if hasattr(e, 'status_code'):
                logger.error(f"   Status code: {e.status_code}")
                
            return {"status": "error", "error": f"{error_type}: {error_msg}"}
    
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
            logger.error(f"Error fetching positions: {e}")
            return []
    
    def get_candles(self, symbol: str, timeframe: str, count: int) -> List[Dict]:
        """Get candle data with retry logic for rate limiting"""
        import time
        
        max_retries = 3
        retry_delay = 1  # Start with 1 second
        
        for attempt in range(max_retries):
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
                error_str = str(e)
                
                # Check if rate limited (429 status or rate limit message)
                is_rate_limited = '429' in error_str or 'rate limit' in error_str.lower() or 'too many' in error_str.lower()
                
                if is_rate_limited and attempt < max_retries - 1:
                    logging.warning(f"Rate limited on {symbol}, retrying in {retry_delay}s (attempt {attempt+1}/{max_retries})")
                    time.sleep(retry_delay)
                    retry_delay *= 2  # Exponential backoff
                    continue
                else:
                    if attempt == max_retries - 1:
                        logging.error(f"Failed to fetch candles for {symbol} after {max_retries} attempts: {e}")
                    else:
                        logging.error(f"Error fetching candles for {symbol}: {e}")
                    return []
        
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
