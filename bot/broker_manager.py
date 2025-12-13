# bot/broker_manager.py
"""
NIJA Multi-Brokerage Manager
Supports: Coinbase, Interactive Brokers, TD Ameritrade, Alpaca, etc.
"""

from enum import Enum
from abc import ABC, abstractmethod
from typing import Dict, List, Optional
import os
import uuid

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
            from coinbase.rest import RESTClient
            
            api_key = os.getenv("COINBASE_API_KEY")
            api_secret = os.getenv("COINBASE_API_SECRET")
            
            if not api_key or not api_secret:
                print("❌ Coinbase credentials not found")
                return False
            
            self.client = RESTClient(api_key=api_key, api_secret=api_secret)
            
            # Test connection
            accounts = self.client.get_accounts()
            self.connected = True
            print("✅ Coinbase Advanced Trade connected")
            return True
            
        except Exception as e:
            print(f"❌ Coinbase connection failed: {e}")
            return False
    
    def get_account_balance(self) -> float:
        """Get total USD balance - scan all portfolios and prioritize USD, then crypto value, then stablecoins."""
        print("🔥 ENTERED get_account_balance()", flush=True)
        try:
            # STEP 1: Optional override from env (if user provides portfolio UUID explicitly)
            env_portfolio = os.getenv("COINBASE_RETAIL_PORTFOLIO_ID")
            portfolio_uuid = env_portfolio if env_portfolio else None

            # STEP 2: Try to get all portfolios and find the one with USD (if no override)
            print("🔥 SCANNING PORTFOLIOS FOR USD...", flush=True)
            try:
                portfolios_response = self.client.get_portfolios()
                if hasattr(portfolios_response, 'portfolios') and portfolios_response.portfolios:
                    print(f"🔥 FOUND {len(portfolios_response.portfolios)} PORTFOLIO(S)", flush=True)

                    # Check each portfolio for USD unless an override was provided
                    for portfolio in portfolios_response.portfolios:
                        p_uuid = getattr(portfolio, 'uuid', None)
                        p_name = getattr(portfolio, 'name', 'Unknown')
                        p_type = getattr(portfolio, 'type', 'Unknown')
                        print(f"🔥   Portfolio: {p_name} (UUID: {p_uuid}, Type: {p_type})", flush=True)

                        # If override exists, log and skip scanning
                        if env_portfolio:
                            continue

                        if p_uuid:
                            # Get accounts for this portfolio
                            try:
                                portfolio_accounts = self.client.get_accounts(retail_portfolio_id=p_uuid)
                                if hasattr(portfolio_accounts, 'accounts') and portfolio_accounts.accounts:
                                    for acct in portfolio_accounts.accounts:
                                        currency = getattr(acct, 'currency', None)
                                        if currency == "USD":
                                            available_obj = getattr(acct, 'available_balance', None)
                                            if available_obj:
                                                usd_val = float(getattr(available_obj, 'value', 0)) if hasattr(available_obj, 'value') else float(available_obj.get('value', 0))
                                                if usd_val > 0:
                                                    print(f"🔥   ✅ FOUND USD ${usd_val:.2f} IN PORTFOLIO '{p_name}'", flush=True)
                                                    portfolio_uuid = p_uuid
                                                    break
                            except Exception as portfolio_err:
                                print(f"🔥   ⚠️ Error checking portfolio {p_name}: {portfolio_err}", flush=True)

                        if portfolio_uuid:
                            break
                else:
                    print("🔥 NO PORTFOLIOS FOUND - using default account query", flush=True)
            except Exception as portfolio_scan_err:
                print(f"🔥 PORTFOLIO SCAN FAILED: {portfolio_scan_err} - falling back to default", flush=True)
            
            # STEP 3: Get accounts (with portfolio_uuid if found or env override)
            if portfolio_uuid:
                print(f"🔥 QUERYING ACCOUNTS FROM PORTFOLIO: {portfolio_uuid}", flush=True)
                accounts = self.client.get_accounts(retail_portfolio_id=portfolio_uuid)
            else:
                print("🔥 QUERYING DEFAULT ACCOUNTS (no portfolio filter)", flush=True)
                accounts = self.client.get_accounts()
            
            print("🔥 ACCOUNTS RESPONSE TYPE:", type(accounts), flush=True)

            usd_balance = 0.0
            crypto_value = 0.0
            stablecoin_balance = 0.0

            # Prefer SDK Account list via .accounts; fallback to dict/list
            acct_list = []
            if hasattr(accounts, "accounts"):
                acct_list = accounts.accounts
            elif isinstance(accounts, dict):
                acct_list = accounts.get("accounts", [])
            else:
                acct_list = accounts

            for acct in acct_list:
                try:
                    # Handle both object and dict access
                    if isinstance(acct, dict):
                        currency = acct.get('currency')
                        available = float(acct.get('available_balance', {}).get('value', 0))
                        held = float(acct.get('hold', {}).get('value', 0))
                    else:
                        currency = getattr(acct, "currency", None)
                        available_obj = getattr(acct, "available_balance", None)
                        held_obj = getattr(acct, "hold", None)
                        
                        # Extract available value
                        available = 0.0
                        if available_obj:
                            if isinstance(available_obj, dict):
                                available = float(available_obj.get('value', 0))
                            else:
                                available = float(getattr(available_obj, 'value', 0))
                        
                        # Extract held value
                        held = 0.0
                        if held_obj:
                            if isinstance(held_obj, dict):
                                held = float(held_obj.get('value', 0))
                            else:
                                held = float(getattr(held_obj, 'value', 0))
                    
                    total_in_account = available + held
                    
                    # Priority 1: USD (primary entry capital)
                    if currency == "USD":
                        print(f"🔥 FOUND USD ACCOUNT! Available: ${available}, Held: ${held}, Total: ${total_in_account}", flush=True)
                        usd_balance += available  # Only available for trading
                    
                    # Priority 2: Crypto holdings (for sell/buy)
                    elif currency in ["BTC", "ETH", "SOL", "AVAX", "XRP", "LTC", "DOGE", "MATIC", "LINK", "ADA"]:
                        if total_in_account > 0:
                            print(f"🔥 FOUND {currency} CRYPTO! Amount: {total_in_account} {currency}", flush=True)
                            crypto_value += total_in_account  # Track but don't add to balance
                    
                    # Priority 3: Stablecoins (fallback if no USD)
                    elif currency in ["USDC", "USDT", "DAI", "BUSD"]:
                        print(f"🔥 FOUND {currency} STABLECOIN! Available: ${available}, Held: ${held}", flush=True)
                        stablecoin_balance += available
                        
                except Exception as inner_e:
                    print(f"🔥 SKIP account due to parse error: {inner_e}", flush=True)

            # Use USD first, fallback to stablecoins if no USD
            trading_balance = usd_balance if usd_balance > 0 else stablecoin_balance
            
            print(f"🔥 BALANCE SUMMARY:", flush=True)
            print(f"   USD: ${usd_balance:.2f} (PRIMARY - for entry/buying)", flush=True)
            print(f"   Crypto holdings: ${crypto_value:.8f} worth (for sell/buy)", flush=True)
            print(f"   Stablecoins: ${stablecoin_balance:.2f} (fallback)", flush=True)
            print(f"   Trading balance: ${trading_balance:.2f}", flush=True)

            # If still zero, dump a concise inventory for debugging
            if trading_balance == 0:
                print("🔥 DEBUG ZERO BALANCE → dumping account inventory", flush=True)
                for acct in acct_list:
                    try:
                        if isinstance(acct, dict):
                            currency = acct.get('currency')
                            platform = acct.get('platform')
                            avail_val = float(acct.get('available_balance', {}).get('value', 0))
                            held_val = float(acct.get('hold', {}).get('value', 0))
                        else:
                            currency = getattr(acct, 'currency', None)
                            platform = getattr(acct, 'platform', None)
                            avail_obj = getattr(acct, 'available_balance', None)
                            held_obj = getattr(acct, 'hold', None)
                            avail_val = float(getattr(avail_obj, 'value', 0)) if avail_obj else 0.0
                            held_val = float(getattr(held_obj, 'value', 0)) if held_obj else 0.0
                        print(f"🔥   ACCT {currency} | platform={platform} | avail={avail_val} | held={held_val}", flush=True)
                    except Exception as inv_err:
                        print(f"🔥   ACCT dump error: {inv_err}", flush=True)
            
            return trading_balance
        except Exception as e:
            print(f"🔥 ERROR get_account_balance: {e}", flush=True)
            import traceback
            traceback.print_exc()
            return 0.0
    
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
