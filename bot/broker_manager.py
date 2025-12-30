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
import json
import traceback

# Try to load dotenv if available, but don't fail if not
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv not available, env vars should be set externally

# Configure logger for broker operations
logger = logging.getLogger('nija.broker')

# Balance threshold constants
MINIMUM_BALANCE_PROTECTION = 10.50  # Absolute minimum to prevent failed orders
MINIMUM_TRADING_BALANCE = 25.00  # Recommended minimum for active trading
DUST_THRESHOLD_USD = 1.00  # USD value threshold for dust positions (consistent with enforcer)

# Credential validation constants
PLACEHOLDER_PASSPHRASE_VALUES = [
    'your_passphrase', 'YOUR_PASSPHRASE', 
    'passphrase', 'PASSPHRASE',
    'your_password', 'YOUR_PASSWORD',
    'password', 'PASSWORD'
]

# Fallback market list - popular crypto trading pairs used when API fails
FALLBACK_MARKETS = [
    'BTC-USD', 'ETH-USD', 'SOL-USD', 'XRP-USD', 'ADA-USD', 
    'DOGE-USD', 'MATIC-USD', 'DOT-USD', 'LINK-USD', 'UNI-USD',
    'AVAX-USD', 'ATOM-USD', 'LTC-USD', 'NEAR-USD', 'ALGO-USD',
    'XLM-USD', 'HBAR-USD', 'APT-USD', 'ARB-USD', 'OP-USD',
    'INJ-USD', 'SUI-USD', 'TIA-USD', 'SEI-USD', 'RUNE-USD',
    'FET-USD', 'IMX-USD', 'RENDER-USD', 'GRT-USD', 'AAVE-USD',
    'MKR-USD', 'SNX-USD', 'CRV-USD', 'LDO-USD', 'COMP-USD',
    'SAND-USD', 'MANA-USD', 'AXS-USD', 'FIL-USD', 'VET-USD',
    'ICP-USD', 'FLOW-USD', 'EOS-USD', 'XTZ-USD', 'THETA-USD',
    'ZEC-USD', 'ETC-USD', 'BAT-USD', 'ENJ-USD', 'CHZ-USD'
]


def _serialize_object_to_dict(obj) -> Dict:
    """
    Safely convert any object to a dictionary for JSON serialization.
    Handles nested objects, dataclasses, and Coinbase SDK response objects.
    
    Args:
        obj: Any object to convert
        
    Returns:
        dict: Flattened dictionary representation
    """
    if obj is None:
        return {}
    
    if isinstance(obj, dict):
        return obj

    # If it's already a string that looks like JSON/dict, try to parse
    if isinstance(obj, str):
        try:
            return json.loads(obj)
        except Exception:
            try:
                import ast
                return ast.literal_eval(obj)
            except Exception:
                return {"_raw": obj, "_type": type(obj).__name__}
    
    # Try JSON serialization first (handles dataclasses with json.JSONEncoder)
    try:
        json_str = json.dumps(obj, default=str)
        return json.loads(json_str)
    except Exception:
        pass
    
    # Fallback: convert object attributes
    try:
        result = {}
        if hasattr(obj, '__dict__'):
            for key, value in obj.__dict__.items():
                # Recursively serialize nested objects
                if isinstance(value, (dict, list, str, int, float, bool, type(None))):
                    result[key] = value
                else:
                    # For nested objects, convert to string representation
                    result[key] = str(value)
        return result
    except Exception:
        # Last resort: convert to string
        return {"_object": str(obj), "_type": type(obj).__name__}

class BrokerType(Enum):
    COINBASE = "coinbase"
    BINANCE = "binance"
    KRAKEN = "kraken"
    OKX = "okx"
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
        pass
    
    def _detect_portfolio(self):
        """DISABLED: Always use default Advanced Trade portfolio"""
        try:
            # CRITICAL FIX: Do NOT auto-detect portfolio
            # The Coinbase Advanced Trade API can ONLY trade from the default trading portfolio
            # Consumer wallets (even if they show up in accounts list) CANNOT be used for trading
            # The SDK's market_order_buy() always routes to the default portfolio
            
            logging.info("=" * 70)
            logging.info("🎯 PORTFOLIO ROUTING: DEFAULT ADVANCED TRADE")
            logging.info("=" * 70)
            logging.info("   Using default Advanced Trade portfolio (SDK default)")
            logging.info("   Consumer wallets are NOT accessible for trading")
            logging.info("   Transfer funds via: https://www.coinbase.com/advanced-portfolio")
            logging.info("=" * 70)
            
            # Do NOT set portfolio_uuid - let SDK use default
            self.portfolio_uuid = None
            
            # Still fetch accounts for balance reporting
            try:
                accounts_resp = self.client.get_accounts() if hasattr(self.client, 'get_accounts') else self.client.list_accounts()
                accounts = getattr(accounts_resp, 'accounts', [])
                
                logging.info("📊 ACCOUNT BALANCES (for information only):")
                logging.info("-" * 70)
                
                for account in accounts:
                    currency = getattr(account, 'currency', None)
                    available_obj = getattr(account, 'available_balance', None)
                    available = float(getattr(available_obj, 'value', 0) or 0)
                    account_name = getattr(account, 'name', 'Unknown')
                    account_type = getattr(account, 'type', 'Unknown')
                    
                    if currency in ['USD', 'USDC'] and available > 0:
                        tradeable = "✅ TRADEABLE" if account_type == "ACCOUNT_TYPE_CRYPTO" else "❌ NOT TRADEABLE (Consumer)"
                        logging.info(f"   {currency}: ${available:.2f} | {account_name} | {tradeable}")
                
                logging.info("=" * 70)
                    
            except Exception as e:
                logging.warning(f"⚠️  Portfolio detection failed: {e}")
                logging.info("   Will use default portfolio routing")
                
        except Exception as e:
            logging.error(f"❌ Portfolio detection error: {e}")
    
    def _is_account_tradeable(self, account_type: str, platform: str) -> bool:
        """
        IMPROVEMENT #3: Expanded account type matching patterns.
        Checks multiple patterns to identify tradeable accounts.
        
        Args:
            account_type: Type string from API (e.g., "ACCOUNT_TYPE_CRYPTO")
            platform: Platform string from API (e.g., "ADVANCED_TRADE")
            
        Returns:
            True if account is tradeable via Advanced Trade API
        """
        if not account_type:
            return False
            
        account_type_str = str(account_type).upper()
        platform_str = str(platform or "").upper()
        
        # Pattern 1: Explicit ACCOUNT_TYPE_CRYPTO
        if account_type_str == "ACCOUNT_TYPE_CRYPTO":
            return True
        
        # Pattern 2: Advanced Trade platform designation
        if "ADVANCED_TRADE" in platform_str or "ADVANCED" in platform_str:
            return True
        
        # Pattern 3: Trading portfolio indicators
        if "TRADING" in platform_str or "TRADING_PORTFOLIO" in account_type_str:
            return True
        
        # Pattern 4: Not explicitly a consumer/vault account
        if "CONSUMER" not in account_type_str and "VAULT" not in account_type_str and "WALLET" not in account_type_str:
            # If platform is not explicitly consumer, assume tradeable
            if platform_str and "ADVANCED" in platform_str:
                return True
        
        return False

    def get_all_products(self) -> list:
        """
        Fetch ALL available products (cryptocurrency pairs) from Coinbase.
        Handles pagination to retrieve 700+ markets without timeouts.
        
        Returns:
            List of product IDs (e.g., ['BTC-USD', 'ETH-USD', ...])
        """
        try:
            logging.info("📡 Fetching all products from Coinbase API (700+ markets)...")
            all_products = []
            
            # Get products with pagination
            if hasattr(self.client, 'get_products'):
                try:
                    # Request all products (Coinbase has 700+ markets)
                    products_resp = self.client.get_products(get_all_products=True)
                    
                    # Debug: Log response type and structure
                    logging.info(f"   Response type: {type(products_resp).__name__}")
                    
                    # Handle both object and dict responses
                    if hasattr(products_resp, 'products'):
                        products = products_resp.products
                        logging.info(f"   Extracted {len(products) if products else 0} products from .products attribute")
                    elif isinstance(products_resp, dict):
                        products = products_resp.get('products', [])
                        logging.info(f"   Extracted {len(products)} products from dict['products']")
                    else:
                        products = []
                        logging.warning(f"⚠️  Unexpected response type: {type(products_resp).__name__}")
                    
                    if not products:
                        logging.warning("⚠️  No products returned from API - response may be empty or malformed")
                        # Debug: Show what attributes/keys are available
                        if hasattr(products_resp, '__dict__'):
                            attrs = [k for k in dir(products_resp) if not k.startswith('_')][:10]
                            logging.info(f"   Available attributes: {attrs}")
                        elif isinstance(products_resp, dict):
                            logging.info(f"   Available keys: {list(products_resp.keys())}")
                        return []
                    
                    # Extract product IDs - handle various response formats
                    for i, product in enumerate(products):
                        product_id = None
                        
                        # Debug first product to understand structure
                        if i == 0:
                            if hasattr(product, '__dict__'):
                                attrs = [k for k in dir(product) if not k.startswith('_')][:10]
                                logging.info(f"   First product attributes: {attrs}")
                            elif isinstance(product, dict):
                                logging.info(f"   First product keys: {list(product.keys())[:10]}")
                        
                        # Try object attribute access (Coinbase uses 'product_id', not 'id')
                        if hasattr(product, 'product_id'):
                            product_id = getattr(product, 'product_id', None)
                        elif hasattr(product, 'id'):
                            product_id = getattr(product, 'id', None)
                        # Try dict access
                        elif isinstance(product, dict):
                            product_id = product.get('product_id') or product.get('id')
                        
                        # Filter: Only include USD trading pairs (exclude stablecoins on themselves)
                        if product_id and '-USD' in product_id:
                            all_products.append(product_id)
                    
                    logging.info(f"   Fetched {len(products)} total products, {len(all_products)} USD/USDC pairs after filtering")
                    
                    # Remove duplicates and sort
                    all_products = sorted(list(set(all_products)))
                    
                    logging.info(f"✅ Successfully fetched {len(all_products)} USD/USDC trading pairs from Coinbase API")
                    if all_products:
                        logging.info(f"   Sample markets: {', '.join(all_products[:10])}")
                    return all_products
                    
                except Exception as e:
                    logging.error(f"⚠️  get_products() failed: {e}")
                    logging.error(f"   Traceback: {traceback.format_exc()}")
                    # Don't return here - let it fall through to outer handler
            
            # Fallback: Use curated list of popular crypto markets
            logging.warning("⚠️  Could not fetch products from API, using fallback list of popular markets")
            logging.info(f"   Using {len(FALLBACK_MARKETS)} fallback markets")
            return FALLBACK_MARKETS
            
        except Exception as e:
            logging.error(f"🔥 Error fetching all products: {e}")
            return []

    def _get_account_balance_detailed(self):
        """Return ONLY tradable Advanced Trade USD/USDC balances (detailed version).

        Coinbase frequently shows Consumer wallet balances that **cannot** be used
        for Advanced Trade orders. To avoid false positives (and endless
        INSUFFICIENT_FUND rejections), we enumerate accounts and only count
        ones marked as Advanced Trade / crypto accounts.
        
        IMPROVEMENTS:
        1. Better consumer wallet diagnostics - tells user to transfer funds
        2. API permission validation - checks if we can see accounts
        3. Expanded account type matching - handles more Coinbase account types

        Returns dict with: {"usdc", "usd", "trading_balance", "crypto", "consumer_*"}
        """
        usd_balance = 0.0
        usdc_balance = 0.0
        consumer_usd = 0.0
        consumer_usdc = 0.0
        crypto_holdings = {}
        accounts_seen = 0
        tradeable_accounts = 0

        # Preferred path: portfolio breakdown (more reliable than get_accounts)
        try:
            logging.info("💰 Fetching account balance via portfolio breakdown (preferred)...")
            portfolios_resp = self.client.get_portfolios() if hasattr(self.client, 'get_portfolios') else None
            portfolios = getattr(portfolios_resp, 'portfolios', [])
            if isinstance(portfolios_resp, dict):
                portfolios = portfolios_resp.get('portfolios', [])

            default_portfolio = None
            for pf in portfolios:
                pf_type = getattr(pf, 'type', None) if not isinstance(pf, dict) else pf.get('type')
                if str(pf_type).upper() == 'DEFAULT':
                    default_portfolio = pf
                    break
            if not default_portfolio and portfolios:
                default_portfolio = portfolios[0]

            portfolio_uuid = None
            if default_portfolio:
                portfolio_uuid = getattr(default_portfolio, 'uuid', None)
                if isinstance(default_portfolio, dict):
                    portfolio_uuid = default_portfolio.get('uuid', portfolio_uuid)

            if default_portfolio and portfolio_uuid:
                breakdown_resp = self.client.get_portfolio_breakdown(portfolio_uuid=portfolio_uuid)
                breakdown = getattr(breakdown_resp, 'breakdown', None)
                if isinstance(breakdown_resp, dict):
                    breakdown = breakdown_resp.get('breakdown', breakdown)

                spot_positions = getattr(breakdown, 'spot_positions', []) if breakdown else []
                if isinstance(breakdown, dict):
                    spot_positions = breakdown.get('spot_positions', spot_positions)

                for pos in spot_positions:
                    asset = getattr(pos, 'asset', None) if not isinstance(pos, dict) else pos.get('asset')
                    available_val = getattr(pos, 'available_to_trade_fiat', None) if not isinstance(pos, dict) else pos.get('available_to_trade_fiat')
                    try:
                        available = float(available_val or 0)
                    except Exception:
                        available = 0.0

                    if asset == 'USD':
                        usd_balance += available
                    elif asset == 'USDC':
                        usdc_balance += available
                    elif asset:
                        crypto_holdings[asset] = crypto_holdings.get(asset, 0.0) + available

                trading_balance = usd_balance + usdc_balance
                logging.info("-" * 70)
                logging.info(f"   💰 Tradable USD (portfolio):  ${usd_balance:.2f}")
                logging.info(f"   💰 Tradable USDC (portfolio): ${usdc_balance:.2f}")
                logging.info(f"   💰 Total Trading Balance: ${trading_balance:.2f}")
                logging.info("   (Source: get_portfolio_breakdown)")
                logging.info("-" * 70)

                return {
                    "usdc": usdc_balance,
                    "usd": usd_balance,
                    "trading_balance": trading_balance,
                    "crypto": crypto_holdings,
                    "consumer_usd": consumer_usd,
                    "consumer_usdc": consumer_usdc,
                }
            else:
                logging.warning("⚠️  No default portfolio found; falling back to get_accounts()")
        except Exception as e:
            logging.warning(f"⚠️  Portfolio breakdown failed, falling back to get_accounts(): {e}")

        try:
            logging.info("💰 Fetching account balance (Advanced Trade only)...")

            resp = self.client.get_accounts()
            accounts = getattr(resp, 'accounts', []) or (resp.get('accounts', []) if isinstance(resp, dict) else [])

            # IMPROVEMENT #2: Validate API permissions
            if not accounts:
                logging.warning("=" * 70)
                logging.warning("⚠️  API PERMISSION CHECK: Zero accounts returned")
                logging.warning("=" * 70)
                logging.warning("This usually means:")
                logging.warning("  1. ❌ API key lacks 'View account details' permission")
                logging.warning("  2. ❌ No Advanced Trade portfolio created yet")
                logging.warning("  3. ❌ Wrong API credentials for this account")
                logging.warning("")
                logging.warning("FIX:")
                logging.warning("  1. Go to: https://portal.cloud.coinbase.com/access/api")
                logging.warning("  2. Edit your API key → Enable 'View' permission")
                logging.warning("  3. Or create portfolio: https://www.coinbase.com/advanced-portfolio")
                logging.warning("=" * 70)

            logging.info("=" * 70)
            logging.info("📊 ACCOUNT BALANCES (v3 get_accounts)")
            logging.info(f"📁 Total accounts returned: {len(accounts)}")
            logging.info("=" * 70)

            for acc in accounts:
                accounts_seen += 1
                # Normalize object/dict access
                if isinstance(acc, dict):
                    currency = acc.get('currency')
                    name = acc.get('name')
                    platform = acc.get('platform')
                    account_type = acc.get('type')
                    available_val = (acc.get('available_balance') or {}).get('value')
                    hold_val = (acc.get('hold') or {}).get('value')
                else:
                    currency = getattr(acc, 'currency', None)
                    name = getattr(acc, 'name', None)
                    platform = getattr(acc, 'platform', None)
                    account_type = getattr(acc, 'type', None)
                    available_val = getattr(getattr(acc, 'available_balance', None), 'value', None)
                    hold_val = getattr(getattr(acc, 'hold', None), 'value', None)

                try:
                    available = float(available_val or 0)
                    hold = float(hold_val or 0)
                except Exception:
                    available = 0.0
                    hold = 0.0

                # IMPROVEMENT #3: Use expanded matching function
                is_tradeable = self._is_account_tradeable(account_type, platform)
                if is_tradeable:
                    tradeable_accounts += 1

                if currency in ("USD", "USDC"):
                    location = "✅ TRADEABLE" if is_tradeable else "❌ CONSUMER"
                    logging.info(
                        f"   {currency:>4} | avail=${available:8.2f} | hold=${hold:8.2f} | type={account_type} | platform={platform} | {location}"
                    )

                    if is_tradeable:
                        if currency == "USD":
                            usd_balance += available
                        else:
                            usdc_balance += available
                    else:
                        # IMPROVEMENT #1: Better consumer wallet diagnostics
                        if currency == "USD":
                            consumer_usd += available
                        else:
                            consumer_usdc += available
                elif currency and available > 0:
                    # Track non-cash crypto holdings ONLY if tradeable via API
                    # Consumer wallet positions cannot be traded and will cause INSUFFICIENT_FUND errors
                    if is_tradeable:
                        crypto_holdings[currency] = available
                        logging.info(
                            f"   ✅ 🪙 {currency}: {available} (type={account_type}, platform={platform})"
                        )
                    else:
                        # Log consumer wallet holdings separately but don't add to crypto_holdings
                        logging.info(
                            f"   ⏭️  {currency}: {available} in CONSUMER wallet (not API-tradeable, skipping)"
                        )

            trading_balance = usd_balance + usdc_balance

            logging.info("-" * 70)
            logging.info(f"   💰 Tradable USD:  ${usd_balance:.2f}")
            logging.info(f"   💰 Tradable USDC: ${usdc_balance:.2f}")
            logging.info(f"   💰 Total Trading Balance: ${trading_balance:.2f}")
            logging.info(f"   🪙 Crypto Holdings: {len(crypto_holdings)} assets")
            
            # IMPROVEMENT #1: Enhanced consumer wallet detection and diagnosis
            if consumer_usd > 0 or consumer_usdc > 0:
                logging.warning("-" * 70)
                logging.warning("⚠️  CONSUMER WALLET DETECTED:")
                logging.warning(f"   🏦 Consumer USD:  ${consumer_usd:.2f}")
                logging.warning(f"   🏦 Consumer USDC: ${consumer_usdc:.2f}")
                logging.warning("")
                logging.warning("These funds are in your Coinbase Consumer wallet and")
                logging.warning("CANNOT be used for Advanced Trade API orders.")
                logging.warning("")
                logging.warning("TO FIX:")
                logging.warning("  1. Go to: https://www.coinbase.com/advanced-portfolio")
                logging.warning("  2. Click 'Deposit' on the Advanced Trade portfolio")
                logging.warning(f"  3. Transfer ${consumer_usd + consumer_usdc:.2f} from Consumer wallet")
                logging.warning("")
                logging.warning("After transfer, bot will see funds and start trading! ✅")
                logging.warning("-" * 70)
            
            logging.info(f"📊 API Status: Saw {accounts_seen} accounts, {tradeable_accounts} tradeable")
            logging.info(f"   💎 Tradeable crypto holdings: {len(crypto_holdings)} assets")
            logging.info("=" * 70)

            return {
                "usdc": usdc_balance,
                "usd": usd_balance,
                "trading_balance": trading_balance,
                "crypto": crypto_holdings,
                "consumer_usd": consumer_usd,
                "consumer_usdc": consumer_usdc,
            }
        except Exception as e:
            logging.error(f"🔥 ERROR get_account_balance: {e}")
            logging.error("This usually indicates:")
            logging.error("  1. Invalid API credentials")
            logging.error("  2. Network connectivity issue")
            logging.error("  3. Coinbase API temporarily unavailable")
            logging.error("")
            logging.error("Verify your credentials at:")
            logging.error("  https://portal.cloud.coinbase.com/access/api")
            import traceback
            logging.error(traceback.format_exc())
            return {
                "usdc": usdc_balance,
                "usd": usd_balance,
                "trading_balance": usd_balance + usdc_balance,
                "crypto": crypto_holdings,
                "consumer_usd": consumer_usd,
                "consumer_usdc": consumer_usdc,
            }
    
    def get_account_balance(self) -> float:
        """Get USD trading balance (conforms to BaseBroker interface).
        
        Returns:
            float: Total trading balance (USD + USDC)
        """
        balance_data = self._get_account_balance_detailed()
        if balance_data is None:
            return 0.0
        return float(balance_data.get('trading_balance', 0.0))
    
    def get_account_balance_detailed(self) -> dict:
        """Get detailed account balance information including crypto holdings.
        
        This is a public wrapper around _get_account_balance_detailed() for
        callers that need the full balance breakdown (crypto holdings, consumer wallets, etc).
        
        Returns:
            dict: Detailed balance info with keys: usdc, usd, trading_balance, crypto, consumer_usd, consumer_usdc
        """
        return self._get_account_balance_detailed()
    
    def get_account_balance_OLD_BROKEN_METHOD(self):
        """
        OLD METHOD - DOES NOT WORK - Kept for reference
        Parse balances from ONLY v3 Advanced Trade API
        
        CRITICAL: Consumer wallet balances are NOT usable for API trading.
        Only Advanced Trade portfolio balance can be used for orders.
        This method ONLY returns Advanced Trade balance to prevent mismatches.
        """
        usd_balance = 0.0
        usdc_balance = 0.0
        consumer_usd = 0.0
        consumer_usdc = 0.0
        crypto_holdings: Dict[str, float] = {}

        try:
            # Check v2 Consumer wallets for DIAGNOSTIC purposes only
            logging.info(f"💰 Checking v2 API (Consumer wallets - DIAGNOSTIC ONLY)...")
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
                    logging.info(f"📁 v2 Consumer API: {len(v2_accounts)} account(s)")
                    
                    for acc in v2_accounts:
                        currency_obj = acc.get('currency', {})
                        currency = currency_obj.get('code', 'N/A') if isinstance(currency_obj, dict) else currency_obj
                        balance_obj = acc.get('balance', {})
                        balance = float(balance_obj.get('amount', 0) if isinstance(balance_obj, dict) else balance_obj or 0)
                        account_type = acc.get('type', 'unknown')
                        name = acc.get('name', 'Unknown')
                        
                        if currency == "USD":
                            consumer_usd += balance
                            if balance > 0:
                                logging.info(f"   📊 Consumer USD: ${balance:.2f} (type={account_type}, name={name}) [NOT TRADABLE VIA API]")
                        elif currency == "USDC":
                            consumer_usdc += balance
                            if balance > 0:
                                logging.info(f"   📊 Consumer USDC: ${balance:.2f} (type={account_type}, name={name}) [NOT TRADABLE VIA API]")
                else:
                    logging.warning(f"⚠️  v2 API returned status {response.status_code}")
                    
            except Exception as v2_error:
                logging.warning(f"⚠️  v2 API check failed: {v2_error}")
            
            # Check v3 Advanced Trade API - THIS IS THE ONLY TRADABLE BALANCE
            logging.info(f"💰 Checking v3 API (Advanced Trade - TRADABLE BALANCE)...")
            try:
                logging.info(f"   🔍 Calling client.list_accounts()...")
                accounts_resp = self.client.list_accounts() if hasattr(self.client, 'list_accounts') else self.client.get_accounts()
                accounts = getattr(accounts_resp, 'accounts', [])
                logging.info(f"📁 v3 Advanced Trade API: {len(accounts)} account(s)")
                
                # ENHANCED DEBUG: Show ALL accounts
                if len(accounts) == 0:
                    logging.error(f"   🚨 API returned ZERO accounts!")
                    logging.error(f"   Response type: {type(accounts_resp)}")
                    logging.error(f"   Response object: {accounts_resp}")
                else:
                    logging.info(f"   📋 Listing all {len(accounts)} accounts:")

                for account in accounts:
                    currency = getattr(account, 'currency', None)
                    available_obj = getattr(account, 'available_balance', None)
                    available = float(getattr(available_obj, 'value', 0) or 0)
                    account_type = getattr(account, 'type', None)
                    account_name = getattr(account, 'name', 'Unknown')
                    account_uuid = getattr(account, 'uuid', 'no-uuid')
                    
                    # DEBUG: Log EVERY account we see
                    logging.info(f"      → {currency}: ${available:.2f} | {account_name} | {account_type} | UUID: {account_uuid[:8]}...")
                    
                    # ONLY count Advanced Trade balances for trading
                    if currency == "USD":
                        usd_balance += available
                        if available > 0:
                            logging.info(f"   ✅ Advanced Trade USD: ${available:.2f} (name={account_name}, type={account_type}) [TRADABLE]")
                    elif currency == "USDC":
                        usdc_balance += available
                        if available > 0:
                            logging.info(f"   ✅ Advanced Trade USDC: ${available:.2f} (name={account_name}, type={account_type}) [TRADABLE]")
                    elif available > 0:
                        crypto_holdings[currency] = crypto_holdings.get(currency, 0) + available
            except Exception as v3_error:
                logging.error(f"⚠️  v3 API check failed!")
                logging.error(f"   Error type: {type(v3_error).__name__}")
                logging.error(f"   Error message: {v3_error}")
                import traceback
                logging.error(f"   Traceback: {traceback.format_exc()}")

            # CRITICAL FIX: ONLY Advanced Trade balances are tradeable
            # Consumer wallet balances CANNOT be used for trading via API
            # The market_order_buy() function can ONLY access Advanced Trade portfolio
            trading_balance = usdc_balance if usdc_balance > 0 else usd_balance
            
            # IGNORE ALLOW_CONSUMER_USD flag - it's misleading
            # Consumer wallets are simply NOT accessible for API trading
            if self.allow_consumer_usd and (consumer_usd > 0 or consumer_usdc > 0):
                logging.warning("⚠️  ALLOW_CONSUMER_USD is enabled, but API cannot trade from Consumer wallets!")
                logging.warning("   This flag has no effect. Transfer funds to Advanced Trade instead.")

            logging.info("=" * 70)
            logging.info("💰 BALANCE SUMMARY:")
            logging.info(f"   Consumer USD:  ${consumer_usd:.2f} ❌ [NOT TRADABLE - API LIMITATION]")
            logging.info(f"   Consumer USDC: ${consumer_usdc:.2f} ❌ [NOT TRADABLE - API LIMITATION]")
            logging.info(f"   Advanced Trade USD:  ${usd_balance:.2f} ✅ [TRADABLE]")
            logging.info(f"   Advanced Trade USDC: ${usdc_balance:.2f} ✅ [TRADABLE]")
            logging.info(f"   ▶ TRADING BALANCE: ${trading_balance:.2f}")
            logging.info("")
            
            # Warn if funds are insufficient (using module-level constants)
            if trading_balance < MINIMUM_BALANCE_PROTECTION:
                funding_needed = MINIMUM_BALANCE_PROTECTION - trading_balance
                logging.error("=" * 70)
                logging.error("🚨 CRITICAL: INSUFFICIENT TRADING BALANCE!")
                logging.error(f"   Current balance: ${trading_balance:.2f}")
                logging.error(f"   MINIMUM_BALANCE (Protection): ${MINIMUM_BALANCE_PROTECTION:.2f}")
                logging.error(f"   💵 Funding Needed: ${funding_needed:.2f}")
                logging.error(f"   Why? $5.00 order + fees (~$0.50) + safety margin")
                logging.error("")
                if (consumer_usd > 0 or consumer_usdc > 0):
                    logging.error("   🔍 ROOT CAUSE: Your funds are in Consumer wallet!")
                    logging.error(f"   Consumer wallet has ${consumer_usd + consumer_usdc:.2f} (NOT TRADABLE)")
                    logging.error(f"   Advanced Trade has ${trading_balance:.2f} (TRADABLE)")
                    logging.error("")
                    logging.error("   🔧 SOLUTION: Transfer to Advanced Trade")
                    logging.error("      1. Go to: https://www.coinbase.com/advanced-portfolio")
                    logging.error("      2. Click 'Deposit' → 'From Coinbase'")
                    logging.error(f"      3. Transfer ${consumer_usd + consumer_usdc:.2f} USD/USDC to Advanced Trade")
                    logging.error("      4. Instant transfer, no fees")
                    logging.error("")
                    logging.error("   ❌ CANNOT FIX WITH CODE:")
                    logging.error("      The Coinbase Advanced Trade API cannot access Consumer wallets")
                    logging.error("      This is a Coinbase API limitation, not a bot issue")
                elif trading_balance == 0:
                    logging.error("   No funds detected in any account")
                    logging.error("   Add funds to your Coinbase account")
                else:
                    logging.error("   Your balance is too low for reliable trading")
                    logging.error("   💡 Note: Funds will become available as open positions are sold")
                    logging.error("   Each trade needs ~$5.50 ($5.00 + fees)")
                    logging.error(f"   With ${trading_balance:.2f}, you can't place ANY trades safely")
                    logging.error("")
                    logging.error("   🎯 RECOMMENDED: Deposit at least $50-$100")
                    logging.error("      - Allows 10-20 trades")
                    logging.error("      - Proper position sizing")
                    logging.error("      - Strategy works as designed")
                logging.error("=" * 70)
            elif trading_balance < MINIMUM_TRADING_BALANCE:
                funding_recommended = MINIMUM_TRADING_BALANCE - trading_balance
                logging.warning("=" * 70)
                logging.warning("⚠️  WARNING: Trading balance below recommended minimum")
                logging.warning(f"   Current balance: ${trading_balance:.2f}")
                logging.warning(f"   MINIMUM_TRADING_BALANCE (Recommended): ${MINIMUM_TRADING_BALANCE:.2f}")
                logging.warning(f"   💵 Additional Funding Recommended: ${funding_recommended:.2f}")
                logging.warning("")
                logging.warning("   Bot can operate but with limited capacity")
                logging.warning("   💡 Add funds for optimal trading performance")
                logging.warning("   💡 Or wait for positions to close and reinvest profits")
                logging.warning("=" * 70)
            else:
                logging.info(f"   ✅ Sufficient funds in Advanced Trade for trading!")
            
            logging.info("=" * 70)

            return {
                "usdc": usdc_balance,
                "usd": usd_balance,
                "trading_balance": trading_balance,
                "crypto": crypto_holdings,
                "consumer_usd": consumer_usd,
                "consumer_usdc": consumer_usdc,
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
                "consumer_usd": 0.0,
                "consumer_usdc": 0.0,
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
                    account_type = a.get('type')
                    av = (a.get('available_balance') or {}).get('value')
                    hd = (a.get('hold') or {}).get('value')
                else:
                    currency = getattr(a, 'currency', None)
                    name = getattr(a, 'name', None)
                    platform = getattr(a, 'platform', None)
                    account_type = getattr(a, 'type', None)
                    av = getattr(getattr(a, 'available_balance', None), 'value', None)
                    hd = getattr(getattr(a, 'hold', None), 'value', None)

                is_tradeable = account_type == "ACCOUNT_TYPE_CRYPTO" or (platform and "ADVANCED_TRADE" in str(platform))

                if currency in ("USD", "USDC"):
                    avf = _as_float(av)
                    hdf = _as_float(hd)
                    tag = "TRADEABLE" if is_tradeable else "CONSUMER"
                    lines.append(f"{currency:>4} | name={name} | platform={platform} | type={account_type} | avail={avf:>10.2f} | held={hdf:>10.2f} | {tag}")
                    if is_tradeable:
                        if currency == "USD":
                            usd_total += avf
                        else:
                            usdc_total += avf

            lines.append("-" * 70)
            trading = usd_total + usdc_total
            lines.append(f"Totals → USD: ${usd_total:.2f} | USDC: ${usdc_total:.2f} | Trading Balance: ${trading:.2f}")
            if usd_total == 0.0 and usdc_total == 0.0:
                lines.append("👉 Move funds into your Advanced Trade portfolio: https://www.coinbase.com/advanced-portfolio")
        except Exception as e:
            lines.append(f"⚠️ Failed to fetch USD/USDC inventory: {e}")

        return lines

    def _log_insufficient_fund_context(self, base_currency: str, quote_currency: str) -> None:
        """Log available balances for base/quote/USD/USDC across portfolios for diagnostics."""
        try:
            resp = self.client.get_accounts()
            accounts = getattr(resp, 'accounts', []) or (resp.get('accounts', []) if isinstance(resp, dict) else [])

            def _as_float(val):
                try:
                    return float(val)
                except Exception:
                    return 0.0

            interesting = {base_currency, quote_currency, 'USD', 'USDC'}
            logger.error(f"   Fund snapshot ({', '.join(sorted(interesting))})")
            for a in accounts:
                if isinstance(a, dict):
                    currency = a.get('currency')
                    platform = a.get('platform')
                    account_type = a.get('type')
                    av = (a.get('available_balance') or {}).get('value')
                    hd = (a.get('hold') or {}).get('value')
                else:
                    currency = getattr(a, 'currency', None)
                    platform = getattr(a, 'platform', None)
                    account_type = getattr(a, 'type', None)
                    av = getattr(getattr(a, 'available_balance', None), 'value', None)
                    hd = getattr(getattr(a, 'hold', None), 'value', None)

                if currency not in interesting:
                    continue

                avf = _as_float(av)
                hdf = _as_float(hd)
                tag = "TRADEABLE" if account_type == "ACCOUNT_TYPE_CRYPTO" or (platform and "ADVANCED_TRADE" in str(platform)) else "CONSUMER"
                logger.error(f"     {currency:>4} | avail={avf:>14.6f} | held={hdf:>12.6f} | type={account_type} | platform={platform} | {tag}")
        except Exception as diag_err:
            logger.error(f"   ⚠️ fund diagnostic failed: {diag_err}")

    def _get_product_metadata(self, symbol: str) -> Dict:
        """Fetch and cache product metadata (base_increment, quote_increment)."""
        # Ensure cache exists (defensive programming)
        if not hasattr(self, '_product_cache'):
            self._product_cache = {}
        
        if symbol in self._product_cache:
            return self._product_cache[symbol]

        meta: Dict = {}
        try:
            product = self.client.get_product(product_id=symbol)
            if isinstance(product, dict):
                meta = product
            else:
                # Serialize SDK object to dict
                meta = _serialize_object_to_dict(product)
            # Some SDK responses nest data under a top-level "product" key
            if isinstance(meta, dict) and 'product' in meta and isinstance(meta['product'], dict):
                meta = meta['product']
            # Some responses wrap the single product in a list under "products"
            if isinstance(meta, dict) and 'products' in meta and isinstance(meta['products'], list) and meta['products']:
                first = meta['products'][0]
                if isinstance(first, dict):
                    meta = first
        except Exception as e:
            logger.warning(f"⚠️ Could not fetch product metadata for {symbol}: {e}")

        self._product_cache[symbol] = meta
        return meta
    
    def place_market_order(self, symbol: str, side: str, quantity: float, size_type: str = 'quote') -> Dict:
        """
        Place market order with balance verification
        
        Args:
            symbol: Trading pair (e.g., 'BTC-USD')
            side: 'buy' or 'sell'
            quantity: Amount to trade
            size_type: 'quote' for USD amount (default) or 'base' for crypto amount
        
        Returns:
            Order response dictionary
        """
        try:
            # Global BUY guard: block all buys when emergency stop is active or HARD_BUY_OFF=1
            try:
                import os as _os
                lock_path = _os.path.join(_os.path.dirname(__file__), '..', 'TRADING_EMERGENCY_STOP.conf')
                hard_buy_off = (_os.getenv('HARD_BUY_OFF', '0') in ('1', 'true', 'True'))
                if side.lower() == 'buy' and (hard_buy_off or _os.path.exists(lock_path)):
                    logger.error("🛑 BUY BLOCKED at broker layer: SELL-ONLY mode or HARD_BUY_OFF active")
                    logger.error(f"   Symbol: {symbol}")
                    logger.error(f"   Reason: {'HARD_BUY_OFF' if hard_buy_off else 'TRADING_EMERGENCY_STOP.conf present'}")
                    return {
                        "status": "unfilled",
                        "error": "BUY_BLOCKED",
                        "message": "Global buy guard active (sell-only mode)",
                        "partial_fill": False,
                        "filled_pct": 0.0
                    }
            except Exception:
                # If guard check fails, proceed but log later if needed
                pass

            if quantity <= 0:
                raise ValueError(f"Refusing to place {side} order with non-positive size: {quantity}")

            base_currency, quote_currency = (symbol.split('-') + ['USD'])[:2]

            # PRE-FLIGHT CHECK: Verify sufficient balance before placing order
            if side.lower() == 'buy':
                balance_data = self._get_account_balance_detailed()
                trading_balance = float(balance_data.get('trading_balance', 0.0))
                
                logger.info(f"💰 Pre-flight balance check for {symbol}:")
                logger.info(f"   Available: ${trading_balance:.2f}")
                logger.info(f"   Required:  ${quantity:.2f}")
                
                # ADD FIX #2: Add 2% safety buffer for fees/rounding (Coinbase typically takes 0.5-1%)
                safety_buffer = quantity * 0.02  # 2% buffer
                required_with_buffer = quantity + safety_buffer
                
                if trading_balance < required_with_buffer:
                    error_msg = f"Insufficient funds: ${trading_balance:.2f} available, ${required_with_buffer:.2f} required (with 2% fee buffer)"
                    logger.error(f"❌ PRE-FLIGHT CHECK FAILED: {error_msg}")
                    logger.error(f"   Bot detected ${trading_balance:.2f} but needs ${required_with_buffer:.2f} for this order")
                    
                    # Log USD/USDC inventory for debugging
                    logger.error(f"   Account inventory:")
                    inventory_lines = self.get_usd_usdc_inventory()
                    for line in inventory_lines:
                        logger.error(f"     {line}")
                    
                    return {
                        "status": "unfilled",
                        "error": "INSUFFICIENT_FUND",
                        "message": error_msg,
                        "partial_fill": False,
                        "filled_pct": 0.0
                    }

            client_order_id = str(uuid.uuid4())
            
            if side.lower() == 'buy':
                # CRITICAL FIX: Round quote_size to 2 decimal places for Coinbase precision requirements
                # Floating point math can create values like 23.016000000000002
                # Coinbase rejects these with PREVIEW_INVALID_QUOTE_SIZE_PRECISION
                quote_size_rounded = round(quantity, 2)
                
                # Use positional client_order_id to avoid SDK signature mismatch
                logger.info(f"📤 Placing BUY order: {symbol}, quote_size=${quote_size_rounded:.2f}")
                logger.info(f"   Using Coinbase Advanced Trade v3 API (market_order_buy)")
                if self.portfolio_uuid:
                    logger.info(f"   Routing to portfolio: {self.portfolio_uuid[:8]}...")
                else:
                    logger.info(f"   This API can ONLY trade from Advanced Trade portfolio, NOT Consumer wallets")
                
                # Include portfolio_uuid if we have it
                order_kwargs = {
                    'client_order_id': client_order_id,
                    'product_id': symbol,
                    'quote_size': str(quote_size_rounded)
                }
                
                # Note: The Coinbase SDK market_order_buy may not support portfolio_uuid parameter
                # It routes to the default portfolio automatically
                # The real fix is to ensure funds are in the default trading portfolio
                order = self.client.market_order_buy(
                    client_order_id,
                    product_id=symbol,
                    quote_size=str(quote_size_rounded)
                )
            else:
                # SELL order - use base_size (crypto amount) or quote_size (USD value)
                if size_type == 'base':
                    base_currency = symbol.split('-')[0].upper()

                    precision_map = {
                        'XRP': 2,
                        'DOGE': 2,
                        'ADA': 2,
                        'SHIB': 0,
                        'BTC': 8,
                        'ETH': 6,
                        'SOL': 4,
                        'ATOM': 4,
                        'LTC': 8,
                        'BCH': 8,
                        'LINK': 4,
                        'IMX': 4,
                        'XLM': 4,
                        'CRV': 4,
                        'APT': 4,
                        'ICP': 5,
                        'NEAR': 5,
                        'AAVE': 4,
                    }

                    # CRITICAL FIX: Use ACTUAL Coinbase increment values
                    # Many coins only accept WHOLE numbers (increment=1) despite supporting decimal balances
                    fallback_increment_map = {
                        'BTC': 0.00000001,  # 8 decimals
                        'ETH': 0.000001,    # 6 decimals
                        'ADA': 1,           # WHOLE NUMBERS ONLY
                        'SOL': 0.001,       # 3 decimals
                        'XRP': 1,           # WHOLE NUMBERS ONLY
                        'DOGE': 1,          # WHOLE NUMBERS ONLY
                        'AVAX': 0.001,      # 3 decimals
                        'DOT': 0.1,         # 1 decimal
                        'LINK': 0.01,       # 2 decimals
                        'LTC': 0.00000001,  # 8 decimals
                        'UNI': 0.01,        # 2 decimals
                        'XLM': 1,           # WHOLE NUMBERS ONLY
                        'HBAR': 1,          # WHOLE NUMBERS ONLY
                        'APT': 0.01,        # 2 decimals
                        'ICP': 0.01,        # 2 decimals
                        'RENDER': 0.1,      # 1 decimal
                        'ZRX': 1,           # WHOLE NUMBERS ONLY
                        'CRV': 1,           # WHOLE NUMBERS ONLY
                        'FET': 1,           # WHOLE NUMBERS ONLY
                        'AAVE': 0.001,      # 3 decimals
                        'VET': 1,           # WHOLE NUMBERS ONLY
                        'SHIB': 1,          # WHOLE NUMBERS ONLY
                        'BCH': 0.00000001,  # 8 decimals
                        'ATOM': 0.0001,     # 4 decimals
                        'IMX': 0.0001,      # 4 decimals
                        'NEAR': 0.00001,    # 5 decimals
                    }

                    precision = max(0, min(precision_map.get(base_currency, 2), 8))
                    base_increment = None

                    # Emergency mode: skip preflight balance calls to reduce API 429s
                    emergency_file = os.path.join(os.path.dirname(__file__), '..', 'LIQUIDATE_ALL_NOW.conf')
                    skip_preflight = side.lower() == 'sell' and os.path.exists(emergency_file)

                    if not skip_preflight:
                        try:
                            balance_snapshot = self._get_account_balance_detailed()
                            holdings = (balance_snapshot or {}).get('crypto', {}) or {}
                            available_base = float(holdings.get(base_currency, 0.0))

                            try:
                                accounts = self.client.get_accounts()
                                hold_amount = 0.0
                                for a in accounts:
                                    if isinstance(a, dict):
                                        currency = a.get('currency')
                                        hd = (a.get('hold') or {}).get('value')
                                    else:
                                        currency = getattr(a, 'currency', None)
                                        hd = getattr(getattr(a, 'hold', None), 'value', None)
                                    if currency == base_currency and hd is not None:
                                        try:
                                            hold_amount = float(hd)
                                        except Exception:
                                            hold_amount = 0.0
                                        break
                                if hold_amount > 0:
                                    available_base = max(0.0, available_base - hold_amount)
                                    logger.info(f"   Adjusted for holds: {hold_amount:.8f} {base_currency} held → usable {available_base:.8f}")
                            except Exception as hold_err:
                                logger.warning(f"⚠️ Could not read holds for {base_currency}: {hold_err}")

                            logger.info(f"   Real-time balance check: {available_base:.8f} {base_currency} available")
                            logger.info(f"   Tracked position size: {quantity:.8f} {base_currency}")
                            
                            epsilon = 1e-8
                            if available_base <= epsilon:
                                logger.error(
                                    f"❌ PRE-FLIGHT CHECK FAILED: Zero {base_currency} balance "
                                    f"(available: {available_base:.8f})"
                                )
                                return {
                                    "status": "unfilled",
                                    "error": "INSUFFICIENT_FUND",
                                    "message": f"No {base_currency} balance available for sell (requested {quantity})",
                                    "partial_fill": False,
                                    "filled_pct": 0.0
                                }
                            
                            if available_base < quantity:
                                diff = quantity - available_base
                                logger.warning(
                                    f"⚠️ Balance mismatch: tracked {quantity:.8f} but only {available_base:.8f} available"
                                )
                                logger.warning(f"   Difference: {diff:.8f} {base_currency} (likely from partial fills or fees)")
                                logger.warning(f"   SOLUTION: Adjusting sell size to actual available balance")
                                quantity = available_base
                        except Exception as bal_err:
                            logger.warning(f"⚠️ Could not pre-check balance for {base_currency}: {bal_err}")
                    else:
                        logger.info("   EMERGENCY MODE: Skipping pre-flight balance checks")

                    meta = self._get_product_metadata(symbol)
                    inc_candidates = []
                    if isinstance(meta, dict):
                        inc_candidates = [
                            meta.get('base_increment'),
                            meta.get('base_increment_decimal'),
                            meta.get('base_increment_value'),
                            # base_min_size is a minimum size, not an increment; exclude from precision detection
                        ]
                        if meta.get('base_increment_exponent') is not None:
                            try:
                                exp_val = float(meta.get('base_increment_exponent'))
                                inc_candidates.append(10 ** exp_val)
                            except Exception as exp_err:
                                logger.warning(f"⚠️ Could not parse base_increment_exponent for {symbol}: {exp_err}")
                    for inc in inc_candidates:
                        if not inc:
                            continue
                        try:
                            base_increment = float(inc)
                            if base_increment > 0:
                                break
                        except Exception as inc_err:
                            logger.warning(f"⚠️ Could not parse base_increment for {symbol}: {inc_err}")

                    # If API metadata did not provide an increment, use a conservative fallback per asset
                    if base_increment is None and base_currency in fallback_increment_map:
                        base_increment = fallback_increment_map[base_currency]
                    
                    # Final safety: ensure we have an increment
                    if base_increment is None:
                        base_increment = 0.01  # Default to 2 decimal places
                    
                    # Calculate precision from increment CORRECTLY
                    import math
                    if base_increment >= 1:
                        precision = 0  # Whole numbers only
                    else:
                        # Count decimal places: 0.001 → 3, 0.0001 → 4, etc.
                        precision = int(abs(math.floor(math.log10(base_increment))))

                    # Adjust requested quantity against available balance with a safety margin
                    # FIX #3: Use a larger safety margin to account for fees and rounding
                    # Coinbase typically charges 0.5-1% in trading fees, plus potential precision rounding
                    requested_qty = float(quantity)  # Already adjusted to available if needed
                    
                    # CRITICAL FIX: For small positions (< $10 value), use minimal safety margin
                    # The 0.5% margin was causing tiny positions to round to 0 after subtraction
                    try:
                        current_price = self.get_current_price(symbol)
                        position_usd_value = requested_qty * current_price
                    except Exception as price_err:
                        # If we can't get price, assume it's a larger position (safer - uses percentage margin)
                        logger.warning(f"⚠️ Could not get price for {symbol}: {price_err}")
                        position_usd_value = 100  # Default to large position logic
                    
                    if position_usd_value < 10.0:
                        # For small positions, use tiny epsilon only (not percentage)
                        # These positions are too small for fees to matter much
                        safety_margin = 1e-8  # Minimal epsilon
                        logger.info(f"   Small position (${position_usd_value:.2f}) - using minimal safety margin")
                    else:
                        # For larger positions, use 0.5% margin
                        safety_margin = max(requested_qty * 0.005, 1e-8)
                    
                    # Subtract safety margin to leave room for fees and rounding
                    trade_qty = max(0.0, requested_qty - safety_margin)
                    
                    logger.info(f"   Safety margin: {safety_margin:.8f} {base_currency}")
                    logger.info(f"   Final trade qty: {trade_qty:.8f} {base_currency}")

                    # Quantize size DOWN to allowed increment using floor division
                    # This is more reliable than Decimal arithmetic
                    import math
                    
                    # Calculate how many increments fit into trade_qty (floor division)
                    num_increments = math.floor(trade_qty / base_increment)
                    base_size_rounded = num_increments * base_increment
                    
                    # Round to the correct decimal places to avoid floating point artifacts
                    base_size_rounded = round(base_size_rounded, precision)
                    
                    # CRITICAL FIX: If rounding resulted in 0 or too small, try selling FULL available balance
                    # This happens with very small positions where safety margin + rounding = 0
                    if base_size_rounded <= 0 or base_size_rounded < base_increment:
                        logger.warning(f"   ⚠️ Rounded size too small ({base_size_rounded}), attempting to sell FULL balance")
                        # Try using the full requested quantity without safety margin
                        num_increments = math.floor(requested_qty / base_increment)
                        base_size_rounded = num_increments * base_increment
                        base_size_rounded = round(base_size_rounded, precision)
                        logger.info(f"   Retry with full balance: {base_size_rounded} {base_currency}")
                    
                    logger.info(f"   Derived base_increment={base_increment} precision={precision} → rounded={base_size_rounded}")
                    
                    # FINAL CHECK: If still too small, log detailed error and try anyway
                    # Coinbase may accept it or provide better error message
                    if base_size_rounded <= 0 or base_size_rounded < base_increment:
                        logger.error(f"   ❌ Position too small to sell with current precision rules")
                        logger.error(f"   Symbol: {symbol}, Base: {base_currency}")
                        logger.error(f"   Available: {available_base:.8f}" if skip_preflight else f"   Available: (preflight skipped)")
                        logger.error(f"   Requested: {requested_qty}")
                        logger.error(f"   Increment: {base_increment}, Precision: {precision}")
                        logger.error(f"   Rounded: {base_size_rounded}")
                        logger.error(f"   ⚠️ This position cannot be sold via API and may need manual intervention")
                        
                        return {
                            "status": "unfilled",
                            "error": "INVALID_SIZE",
                            "message": f"Position too small: {symbol} rounded to {base_size_rounded} (min: {base_increment}). Manual sell may be required.",
                            "partial_fill": False,
                            "filled_pct": 0.0
                        }

                    logger.info(f"📤 Placing SELL order: {symbol}, base_size={base_size_rounded} ({precision} decimals)")
                    if self.portfolio_uuid:
                        logger.info(f"   Routing to portfolio: {self.portfolio_uuid[:8]}...")

                    # Prefer create_order; fallback to market_order_sell, with 429 backoff
                    def _with_backoff(fn, *args, **kwargs):
                        import time
                        delays = [1, 2, 4]
                        for i, d in enumerate(delays):
                            try:
                                return fn(*args, **kwargs)
                            except Exception as err:
                                msg = str(err)
                                if 'Too Many Requests' in msg or '429' in msg:
                                    logger.warning(f"⚠️ Rate limited, retrying in {d}s (attempt {i+1}/{len(delays)})")
                                    time.sleep(d)
                                    continue
                                raise
                        return fn(*args, **kwargs)

                    try:
                        order = _with_backoff(
                            self.client.create_order,
                            client_order_id=client_order_id,
                            product_id=symbol,
                            order_configuration={
                                'market_market_ioc': {
                                    'base_size': str(base_size_rounded),
                                    'reduce_only': True
                                }
                            },
                            **({'portfolio_id': self.portfolio_uuid} if getattr(self, 'portfolio_uuid', None) else {})
                        )
                    except Exception as co_err:
                        logger.warning(f"⚠️ create_order failed, falling back to market_order_sell: {co_err}")
                        order = _with_backoff(
                            self.client.market_order_sell,
                            client_order_id,
                            product_id=symbol,
                            base_size=str(base_size_rounded)
                        )
                else:
                    # Use quote_size for SELL (less common, but supported)
                    quote_size_rounded = round(quantity, 2)
                    logger.info(f"📤 Placing SELL order: {symbol}, quote_size=${quote_size_rounded:.2f}")
                    if self.portfolio_uuid:
                        logger.info(f"   Routing to portfolio: {self.portfolio_uuid[:8]}...")
                    
                    order = _with_backoff(
                        self.client.market_order_sell,
                        client_order_id,
                        product_id=symbol,
                        quote_size=str(quote_size_rounded)
                    )
            
            # CRITICAL: Parse order response to check for success/failure
            # Coinbase returns an object with 'success' field and 'error_response'
            # Use helper to safely serialize the response
            order_dict = _serialize_object_to_dict(order)

            # If SDK returns a stringified dict, coerce it to a dict to avoid false positives
            if isinstance(order_dict, str):
                try:
                    order_dict = json.loads(order_dict)
                except Exception:
                    try:
                        import ast
                        order_dict = ast.literal_eval(order_dict)
                    except Exception:
                        pass

            # Guard against SDK returning plain strings or unexpected types
            if not isinstance(order_dict, dict):
                logger.error("Received non-dict order response from Coinbase SDK")
                logger.error(f"   Raw response: {order_dict}")
                logger.error(f"   Response type: {type(order_dict)}")
                return {
                    "status": "error",
                    "error": "INVALID_ORDER_RESPONSE",
                    "message": "Coinbase SDK returned non-dict response",
                    "raw_response": str(order_dict)
                }
            
            # Check for Coinbase error response
            success = order_dict.get('success', True)
            error_response = order_dict.get('error_response', {})
            
            if not success or error_response:
                error_code = error_response.get('error', 'UNKNOWN_ERROR')
                error_message = error_response.get('message', 'Unknown error from broker')
                
                logger.error(f"❌ Trade failed for {symbol}:")
                logger.error(f"   Status: unfilled")
                logger.error(f"   Error: {error_message}")
                logger.error(f"   Full order response: {order_dict}")

                if error_code == 'INSUFFICIENT_FUND':
                    self._log_insufficient_fund_context(base_currency, quote_currency)
                elif error_code == 'INVALID_SIZE_PRECISION' and size_type == 'base':
                    # One-shot degradation retry: use stricter per-asset increment if available
                    logger.error(
                        f"   Hint: base_increment={base_increment} precision={precision} quantity={quantity} rounded={base_size_rounded}"
                    )
                    stricter_map = {
                        'APT': 0.001,
                        'NEAR': 0.0001,
                        'ICP': 0.0001,
                        'AAVE': 0.01,
                    }
                    base_currency = symbol.split('-')[0].upper()
                    alt_inc = stricter_map.get(base_currency)
                    if alt_inc and (base_increment is None or alt_inc != base_increment):
                        try:
                            from decimal import Decimal, ROUND_DOWN, getcontext
                            getcontext().prec = 18
                            step2 = Decimal(str(alt_inc))

                            # Recompute safe trade qty based on same available snapshot
                            safety_epsilon2 = max(alt_inc, 1e-6)
                            safe_available2 = max(0.0, (available_base if 'available_base' in locals() else 0.0) - safety_epsilon2)
                            trade_qty2 = min(float(quantity), safe_available2)

                            qty2 = (Decimal(str(trade_qty2)) / step2).to_integral_value(rounding=ROUND_DOWN) * step2
                            base_size_rounded2 = float(qty2)
                            inc_str2 = f"{alt_inc:.16f}".rstrip('0').rstrip('.')
                            precision2 = len(inc_str2.split('.')[1]) if '.' in inc_str2 else 0
                            logger.info(f"   Retry with alt increment {alt_inc} (precision {precision2}) → {base_size_rounded2}")

                            order2 = self.client.market_order_sell(
                                client_order_id,
                                product_id=symbol,
                                base_size=str(base_size_rounded2)
                            )
                            order_dict2 = _serialize_object_to_dict(order2)
                            if isinstance(order_dict2, str):
                                try:
                                    order_dict2 = json.loads(order_dict2)
                                except Exception:
                                    try:
                                        import ast
                                        order_dict2 = ast.literal_eval(order_dict2)
                                    except Exception:
                                        pass

                            success2 = isinstance(order_dict2, dict) and order_dict2.get('success', True) and not order_dict2.get('error_response')
                            if success2:
                                logger.info(f"✅ Order filled successfully (retry): {symbol}")
                                return {
                                    "status": "filled",
                                    "order": order_dict2,
                                    "filled_size": base_size_rounded2
                                }
                            else:
                                logger.error(f"   Retry failed: {order_dict2}")
                        except Exception as retry_err:
                            logger.error(f"   Retry with stricter increment failed: {retry_err}")

                # Generic fallback: decrement by one increment and retry a few times
                if size_type == 'base' and base_increment and error_code in ('INVALID_SIZE_PRECISION', 'INSUFFICIENT_FUND', 'PREVIEW_INVALID_SIZE_PRECISION', 'PREVIEW_INSUFFICIENT_FUND'):
                    try:
                        from decimal import Decimal, ROUND_DOWN, getcontext
                        getcontext().prec = 18
                        step = Decimal(str(base_increment))

                        max_attempts = 5
                        current_qty = Decimal(str(base_size_rounded if 'base_size_rounded' in locals() else quantity))
                        for attempt in range(1, max_attempts + 1):
                            # Reduce by one increment per attempt and quantize down
                            reduced = current_qty - step * attempt
                            if reduced <= Decimal('0'):
                                break
                            qtry = (reduced / step).to_integral_value(rounding=ROUND_DOWN) * step
                            new_size = float(qtry)
                            logger.info(f"   Fallback attempt {attempt}/{max_attempts}: base_size → {new_size} (decrement by {attempt}×{base_increment})")

                            order_try = self.client.market_order_sell(
                                client_order_id,
                                product_id=symbol,
                                base_size=str(new_size)
                            )
                            od_try = _serialize_object_to_dict(order_try)
                            if isinstance(od_try, str):
                                try:
                                    od_try = json.loads(od_try)
                                except Exception:
                                    try:
                                        import ast
                                        od_try = ast.literal_eval(od_try)
                                    except Exception:
                                        pass

                            if isinstance(od_try, dict) and od_try.get('success', True) and not od_try.get('error_response'):
                                logger.info(f"✅ Order filled successfully (fallback attempt {attempt}): {symbol}")
                                return {
                                    "status": "filled",
                                    "order": od_try,
                                    "filled_size": new_size
                                }
                            else:
                                emsg = od_try.get('error_response', {}).get('message') if isinstance(od_try, dict) else str(od_try)
                                logger.error(f"   Fallback attempt {attempt} failed: {emsg}")
                    except Exception as fb_err:
                        logger.error(f"   Fallback decrement retry failed: {fb_err}")
                
                return {
                    "status": "unfilled",
                    "error": error_code,
                    "message": error_message,
                    "order": order_dict,
                    "partial_fill": order_dict.get('partial_fill', False),
                    "filled_pct": order_dict.get('filled_pct', 0.0)
                }
            
            logger.info(f"✅ Order filled successfully: {symbol}")
            
            # Extract or estimate filled size
            # Coinbase API v3 doesn't return filled_size in the response,
            # so we estimate based on what we sent
            filled_size = None
            
            # Try to extract from success_response
            success_response = order_dict.get('success_response', {})
            if success_response:
                filled_size = success_response.get('filled_size')
            
            # If not available, estimate based on order configuration
            if not filled_size:
                order_config = order_dict.get('order_configuration', {})
                market_config = order_config.get('market_market_ioc', {})
                
                if side.upper() == 'BUY' and 'quote_size' in market_config:
                    # For buy orders, estimate crypto received = quote_size / price
                    try:
                        quote_size = float(market_config['quote_size'])
                        # Fetch current price to estimate
                        price_data = self.client.get_product(symbol)
                        if price_data and 'price' in price_data:
                            current_price = float(price_data['price'])
                            filled_size = quote_size / current_price
                    except:
                        # Fallback: use quantity as estimate
                        filled_size = quantity
                else:
                    # For sell orders or unknown, use quantity as estimate
                    filled_size = quantity
            
            if filled_size:
                logger.info(f"   Filled crypto amount: {filled_size:.6f}")
            
            # CRITICAL: Track position for profit-based exits
            if self.position_tracker:
                try:
                    if side.lower() == 'buy':
                        # Track entry for profit calculation
                        # Try to get actual fill price from order response first
                        fill_price = None
                        
                        # Try to extract actual fill price from success_response
                        if success_response and 'average_filled_price' in success_response:
                            try:
                                fill_price = float(success_response['average_filled_price'])
                            except:
                                pass
                        
                        # Fallback to current market price if fill price not available
                        if not fill_price or fill_price == 0:
                            fill_price = self.get_current_price(symbol)
                        
                        if fill_price > 0:
                            size_usd = quantity if size_type == 'quote' else (filled_size * fill_price if filled_size else 0)
                            self.position_tracker.track_entry(
                                symbol=symbol,
                                entry_price=fill_price,
                                quantity=filled_size if filled_size else 0,
                                size_usd=size_usd,
                                strategy="APEX_v7.1"
                            )
                            logger.info(f"   📊 Position tracked: entry=${fill_price:.2f}, size=${size_usd:.2f}")
                            
                            # Log BUY trade to journal
                            self._log_trade_to_journal(
                                symbol=symbol,
                                side='BUY',
                                price=fill_price,
                                size_usd=size_usd,
                                quantity=filled_size if filled_size else 0
                            )
                    else:
                        # Get P&L before tracking exit
                        fill_price = None
                        if success_response and 'average_filled_price' in success_response:
                            try:
                                fill_price = float(success_response['average_filled_price'])
                            except:
                                pass
                        if not fill_price or fill_price == 0:
                            fill_price = self.get_current_price(symbol)
                        
                        # Calculate P&L for this exit
                        pnl_data = None
                        if fill_price and fill_price > 0:
                            pnl_data = self.position_tracker.calculate_pnl(symbol, fill_price)
                            if pnl_data:
                                logger.info(f"   💰 Exit P&L: ${pnl_data['pnl_dollars']:+.2f} ({pnl_data['pnl_percent']:+.2f}%)")
                        
                        # Track exit (partial or full sell)
                        self.position_tracker.track_exit(
                            symbol=symbol,
                            exit_quantity=filled_size if filled_size else None
                        )
                        logger.info(f"   📊 Position exit tracked")
                        
                        # Log SELL trade to journal with P&L
                        self._log_trade_to_journal(
                            symbol=symbol,
                            side='SELL',
                            price=fill_price if fill_price else 0,
                            size_usd=quantity if size_type == 'quote' else (filled_size * fill_price if filled_size and fill_price else 0),
                            quantity=filled_size if filled_size else 0,
                            pnl_data=pnl_data
                        )
                except Exception as track_err:
                    logger.warning(f"   ⚠️ Position tracking failed: {track_err}")
            
            return {
                "status": "filled", 
                "order": order_dict,
                "filled_size": float(filled_size) if filled_size else 0.0
            }
            
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

    def close_position(
        self,
        symbol: str,
        base_size: Optional[float] = None,
        *,
        side: str = 'sell',
        quantity: Optional[float] = None,
        size_type: str = 'base',
        **_: Dict
    ) -> Dict:
        """Close a position by submitting a market order.

        Accepts both legacy (symbol, base_size) calls and newer keyword-based
        calls that provide ``side``/``quantity``/``size_type``. Defaults to
        selling a base-size amount when only ``base_size`` is provided.
        """
        # Prefer explicitly provided quantity; fall back to legacy base_size
        size = quantity if quantity is not None else base_size
        if size is None:
            raise ValueError("close_position requires a quantity or base_size")

        try:
            return self.place_market_order(
                symbol,
                side.lower() if side else 'sell',
                size,
                size_type=size_type or 'base'
            )
        except TypeError:
            # Graceful fallback if upstream signatures drift
            return self.place_market_order(symbol, 'sell', size, size_type='base')
    
    def get_positions(self) -> List[Dict]:
        """Return tradable crypto positions with base quantities.

        Prefers portfolio breakdown (Advanced Trade) for accurate, tradable amounts.
        Falls back to get_accounts() if breakdown is unavailable.
        """
        positions: List[Dict] = []

        # Preferred: Use portfolio breakdown to derive base quantities
        try:
            portfolios_resp = self.client.get_portfolios() if hasattr(self.client, 'get_portfolios') else None
            portfolios = getattr(portfolios_resp, 'portfolios', [])
            if isinstance(portfolios_resp, dict):
                portfolios = portfolios_resp.get('portfolios', [])

            default_portfolio = None
            for pf in portfolios:
                pf_type = getattr(pf, 'type', None) if not isinstance(pf, dict) else pf.get('type')
                if str(pf_type).upper() == 'DEFAULT':
                    default_portfolio = pf
                    break
            if not default_portfolio and portfolios:
                default_portfolio = portfolios[0]

            portfolio_uuid = None
            if default_portfolio:
                portfolio_uuid = getattr(default_portfolio, 'uuid', None)
                if isinstance(default_portfolio, dict):
                    portfolio_uuid = default_portfolio.get('uuid', portfolio_uuid)

            if default_portfolio and portfolio_uuid:
                breakdown_resp = self.client.get_portfolio_breakdown(portfolio_uuid=portfolio_uuid)
                breakdown = getattr(breakdown_resp, 'breakdown', None)
                if isinstance(breakdown_resp, dict):
                    breakdown = breakdown_resp.get('breakdown', breakdown)

                spot_positions = getattr(breakdown, 'spot_positions', []) if breakdown else []
                if isinstance(breakdown, dict):
                    spot_positions = breakdown.get('spot_positions', spot_positions)

                for pos in spot_positions:
                    asset = getattr(pos, 'asset', None) if not isinstance(pos, dict) else pos.get('asset')

                    # Skip fiat assets; we only return crypto positions
                    if not asset or asset in ['USD', 'USDC']:
                        continue

                    # Try to fetch base available to trade; if not present, derive from fiat value
                    base_avail = None
                    if isinstance(pos, dict):
                        base_avail = pos.get('available_to_trade') or pos.get('available_to_trade_base')
                        fiat_avail = pos.get('available_to_trade_fiat')
                    else:
                        base_avail = getattr(pos, 'available_to_trade', None) or getattr(pos, 'available_to_trade_base', None)
                        fiat_avail = getattr(pos, 'available_to_trade_fiat', None)

                    quantity = 0.0
                    try:
                        if base_avail is not None:
                            quantity = float(base_avail or 0)
                        else:
                            # Derive base qty from fiat using current price
                            fiat_val = float(fiat_avail or 0)
                            if fiat_val > 0:
                                symbol = f"{asset}-USD"
                                price = self.get_current_price(symbol)
                                if price > 0:
                                    quantity = fiat_val / price
                    except Exception:
                        quantity = 0.0

                    # CRITICAL FIX: Skip true dust positions to match enforcer
                    # Calculate USD value to filter consistently
                    if quantity > 0:
                        position_symbol = f"{asset}-USD"
                        try:
                            price = self.get_current_price(position_symbol)
                            usd_value = quantity * price if price > 0 else 0
                            # Only skip TRUE dust - count all other positions
                            if usd_value < DUST_THRESHOLD_USD:
                                logger.debug(f"Skipping dust position {position_symbol}: qty={quantity}, value=${usd_value:.4f}")
                                continue
                        except Exception:
                            # If we can't get price, include it anyway to be safe
                            pass
                        
                        positions.append({
                            'symbol': position_symbol,
                            'quantity': quantity,
                            'currency': asset
                        })

                # If we built positions from breakdown, return them
                if positions:
                    return positions
        except Exception as e:
            logger.warning(f"⚠️ Portfolio breakdown unavailable, falling back to get_accounts(): {e}")

        # Fallback: Use get_accounts available balances
        try:
            accounts = self.client.get_accounts()
            # Handle both dict and object responses from Coinbase SDK
            accounts_list = accounts.get('accounts') if isinstance(accounts, dict) else getattr(accounts, 'accounts', [])

            for account in accounts_list:
                if isinstance(account, dict):
                    currency = account.get('currency')
                    balance = float(account.get('available_balance', {}).get('value', 0)) if account.get('available_balance') else 0
                else:
                    currency = getattr(account, 'currency', None)
                    balance_obj = getattr(account, 'available_balance', {})
                    balance = float(balance_obj.get('value', 0)) if isinstance(balance_obj, dict) else float(getattr(balance_obj, 'value', 0)) if balance_obj else 0

                # CRITICAL FIX: Apply same dust filtering as primary path
                if currency and currency not in ['USD', 'USDC'] and balance > 0:
                    # Calculate USD value to filter consistently
                    position_symbol = f"{currency}-USD"
                    try:
                        price = self.get_current_price(position_symbol)
                        usd_value = balance * price if price > 0 else 0
                        # Only skip TRUE dust - count all other positions
                        if usd_value < DUST_THRESHOLD_USD:
                            logger.debug(f"Skipping dust position {position_symbol}: qty={balance}, value=${usd_value:.4f}")
                            continue
                    except Exception:
                        # If we can't get price, include it anyway to be safe
                        pass
                    
                    positions.append({
                        'symbol': position_symbol,
                        'quantity': balance,
                        'currency': currency
                    })
            return positions
        except Exception as e:
            logger.error(f"Error fetching positions: {e}")
            return []
    
    def get_market_data(self, symbol: str, timeframe: str = '5m', limit: int = 100) -> Dict:
        """
        Get market data (wrapper around get_candles for compatibility)
        Returns dict with 'candles' key containing list of candle dicts
        """
        candles = self.get_candles(symbol, timeframe, limit)
        return {'candles': candles}

    def get_current_price(self, symbol: str) -> float:
        """Fetch latest trade/last candle price for a product."""
        try:
            # Fast path: product ticker price
            try:
                product = self.client.get_product(symbol)
                price_val = product.get('price') if isinstance(product, dict) else getattr(product, 'price', None)
                if price_val:
                    return float(price_val)
            except Exception:
                # Ignore and fall back to candles
                pass

            # Fallback: last close from 1m candle
            candles = self.get_candles(symbol, '1m', 1)
            if candles:
                last = candles[-1]
                close = last.get('close') if isinstance(last, dict) else getattr(last, 'close', None)
                if close:
                    return float(close)
            raise RuntimeError("No price data available")
        except Exception as e:
            logging.error(f"⚠️ get_current_price failed for {symbol}: {e}")
            return 0.0
    
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


# Coinbase Broker - extends BaseBroker which has all Coinbase implementation
class CoinbaseBroker(BaseBroker):
    """Coinbase Advanced Trade broker implementation"""
    
    def __init__(self):
        """Initialize Coinbase broker"""
        super().__init__(BrokerType.COINBASE)
        self.client = None
        self.portfolio_uuid = None
        self._product_cache = {}  # Cache for product metadata (tick sizes, increments)
        
        # Initialize position tracker for profit-based exits
        try:
            from position_tracker import PositionTracker
            self.position_tracker = PositionTracker(storage_file="positions.json")
            logger.info("✅ Position tracker initialized for profit-based exits")
        except Exception as e:
            logger.warning(f"⚠️ Position tracker initialization failed: {e}")
            self.position_tracker = None
    
    def _log_trade_to_journal(self, symbol: str, side: str, price: float, 
                               size_usd: float, quantity: float, pnl_data: dict = None):
        """
        Log trade to trade_journal.jsonl with P&L tracking.
        
        Args:
            symbol: Trading symbol
            side: 'BUY' or 'SELL'
            price: Execution price
            size_usd: Trade size in USD
            quantity: Crypto quantity
            pnl_data: Optional P&L data for SELL orders (from position_tracker.calculate_pnl)
        """
        try:
            from datetime import datetime
            
            trade_entry = {
                "timestamp": datetime.now().isoformat(),
                "symbol": symbol,
                "side": side,
                "price": price,
                "size_usd": size_usd,
                "quantity": quantity
            }
            
            # Add P&L data for SELL orders
            if pnl_data and side == 'SELL':
                trade_entry["entry_price"] = pnl_data.get('entry_price', 0)
                trade_entry["pnl_dollars"] = pnl_data.get('pnl_dollars', 0)
                trade_entry["pnl_percent"] = pnl_data.get('pnl_percent', 0)
                trade_entry["entry_value"] = pnl_data.get('entry_value', 0)
            
            # Append to trade journal file
            journal_file = "trade_journal.jsonl"
            with open(journal_file, 'a') as f:
                f.write(json.dumps(trade_entry) + '\n')
            
            logger.debug(f"Trade logged to journal: {symbol} {side} @ ${price:.2f}")
        except Exception as e:
            logger.warning(f"Failed to log trade to journal: {e}")
    
    def connect(self) -> bool:
        """Connect to Coinbase Advanced Trade API"""
        try:
            from coinbase.rest import RESTClient
            import os
            
            # Get credentials from environment
            api_key = os.getenv("COINBASE_API_KEY")
            api_secret = os.getenv("COINBASE_API_SECRET")
            
            if not api_key or not api_secret:
                logging.error("❌ Coinbase API credentials not found")
                return False
            
            # Initialize REST client
            self.client = RESTClient(api_key=api_key, api_secret=api_secret)
            
            # Test connection by fetching accounts
            try:
                accounts_resp = self.client.get_accounts()
                self.connected = True
                logging.info("✅ Connected to Coinbase Advanced Trade API")
                
                # Portfolio detection (uses inherited method from BaseBroker)
                self._detect_portfolio()
                
                return True
                
            except Exception as e:
                logging.error(f"❌ Failed to verify Coinbase connection: {e}")
                return False
                
        except ImportError:
            logging.error("❌ Coinbase SDK not installed. Run: pip install coinbase-advanced-py")
            return False
        except Exception as e:
            logging.error(f"❌ Coinbase connection error: {e}")
            return False


class AlpacaBroker(BaseBroker):
    """Alpaca integration for stocks"""
    
    def __init__(self):
        super().__init__(BrokerType.ALPACA)
        self.api = None
    
    def connect(self) -> bool:
        """Connect to Alpaca"""
        try:
            from alpaca.trading.client import TradingClient
            
            api_key = os.getenv("ALPACA_API_KEY", "").strip()
            api_secret = os.getenv("ALPACA_API_SECRET", "").strip()
            paper = os.getenv("ALPACA_PAPER", "true").lower() == "true"
            
            if not api_key or not api_secret:
                # Silently skip - Alpaca is optional
                logging.info("⚠️  Alpaca credentials not configured (skipping)")
                return False
            
            self.api = TradingClient(api_key, api_secret, paper=paper)
            
            # Test connection
            account = self.api.get_account()
            self.connected = True
            logging.info(f"✅ Alpaca connected ({'PAPER' if paper else 'LIVE'})")
            return True
            
        except ImportError:
            # SDK not installed - skip silently
            return False
        except Exception as e:
            logging.warning(f"⚠️  Alpaca connection failed: {e}")
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
    """
    Binance Exchange integration for cryptocurrency spot trading.
    
    Features:
    - Spot trading (USDT pairs)
    - Market and limit orders
    - Real-time account balance
    - Historical candle data (OHLCV)
    
    Documentation: https://python-binance.readthedocs.io/
    """
    
    def __init__(self):
        super().__init__(BrokerType.BINANCE)
        self.client = None
    
    def connect(self) -> bool:
        """
        Connect to Binance API.
        
        Requires environment variables:
        - BINANCE_API_KEY: Your Binance API key
        - BINANCE_API_SECRET: Your Binance API secret
        - BINANCE_USE_TESTNET: 'true' for testnet, 'false' for live (optional, default: false)
        
        Returns:
            bool: True if connected successfully
        """
        try:
            from binance.client import Client
            
            api_key = os.getenv("BINANCE_API_KEY", "").strip()
            api_secret = os.getenv("BINANCE_API_SECRET", "").strip()
            use_testnet = os.getenv("BINANCE_USE_TESTNET", "false").lower() in ["true", "1", "yes"]
            
            if not api_key or not api_secret:
                # Silently skip - Binance is optional, no need for scary error messages
                logging.info("⚠️  Binance credentials not configured (skipping)")
                return False
            
            # Initialize Binance client
            if use_testnet:
                # Testnet base URL
                self.client = Client(api_key, api_secret, testnet=True)
            else:
                self.client = Client(api_key, api_secret)
            
            # Test connection by fetching account status
            account = self.client.get_account()
            
            if account:
                self.connected = True
                env_type = "🧪 TESTNET" if use_testnet else "🔴 LIVE"
                logging.info("=" * 70)
                logging.info(f"✅ BINANCE CONNECTED ({env_type})")
                logging.info("=" * 70)
                
                # Log account trading status
                can_trade = account.get('canTrade', False)
                logging.info(f"   Trading Enabled: {'✅' if can_trade else '❌'}")
                
                # Log USDT balance
                for balance in account.get('balances', []):
                    if balance['asset'] == 'USDT':
                        usdt_balance = float(balance['free'])
                        logging.info(f"   USDT Balance: ${usdt_balance:.2f}")
                        break
                
                logging.info("=" * 70)
                return True
            else:
                logging.warning("⚠️  Binance connection test failed: No account data returned")
                return False
                
        except ImportError:
            # SDK not installed - skip silently (it's optional)
            return False
        except Exception as e:
            # Handle authentication errors gracefully
            error_str = str(e).lower()
            if 'api' in error_str and ('key' in error_str or 'signature' in error_str or 'authentication' in error_str):
                logging.warning("⚠️  Binance authentication failed - invalid or expired API credentials")
                logging.warning("   Please check your BINANCE_API_KEY and BINANCE_API_SECRET")
            elif 'connection' in error_str or 'network' in error_str or 'timeout' in error_str:
                logging.warning("⚠️  Binance connection failed - network issue or API unavailable")
            else:
                logging.warning(f"⚠️  Binance connection failed: {e}")
            return False
    
    def get_account_balance(self) -> float:
        """
        Get USDT balance available for trading.
        
        Returns:
            float: Available USDT balance
        """
        try:
            if not self.client:
                return 0.0
            
            # Get account balances
            account = self.client.get_account()
            
            # Find USDT balance
            for balance in account.get('balances', []):
                if balance['asset'] == 'USDT':
                    available = float(balance.get('free', 0))
                    logging.info(f"💰 Binance USDT Balance: ${available:.2f}")
                    return available
            
            # No USDT found
            logging.warning("⚠️  No USDT balance found in Binance account")
            return 0.0
            
        except Exception as e:
            logging.error(f"Error fetching Binance balance: {e}")
            return 0.0
    
    def place_market_order(self, symbol: str, side: str, quantity: float) -> Dict:
        """
        Place market order on Binance.
        
        Args:
            symbol: Trading pair (e.g., 'BTC-USD' or 'BTCUSDT')
            side: 'buy' or 'sell'
            quantity: Order size in USDT (for buys) or base currency (for sells)
        
        Returns:
            dict: Order result with status, order_id, etc.
        """
        try:
            if not self.client:
                return {"status": "error", "error": "Not connected to Binance"}
            
            # Convert symbol format (BTC-USD -> BTCUSDT)
            binance_symbol = symbol.replace('-USD', 'USDT').replace('-', '')
            
            # Binance uses uppercase for side
            binance_side = side.upper()
            
            # Place market order
            # Note: Binance requires 'quantity' parameter for market orders
            # For buy orders, you may want to use quoteOrderQty instead
            if binance_side == 'BUY':
                # Use quoteOrderQty for buy orders (spend X USDT)
                order = self.client.order_market_buy(
                    symbol=binance_symbol,
                    quoteOrderQty=quantity
                )
            else:
                # Use quantity for sell orders (sell X crypto)
                order = self.client.order_market_sell(
                    symbol=binance_symbol,
                    quantity=quantity
                )
            
            if order:
                order_id = order.get('orderId')
                status = order.get('status', 'UNKNOWN')
                filled_qty = float(order.get('executedQty', 0))
                
                logging.info(f"✅ Binance order placed: {binance_side} {binance_symbol}")
                logging.info(f"   Order ID: {order_id}")
                logging.info(f"   Status: {status}")
                logging.info(f"   Filled: {filled_qty}")
                
                return {
                    "status": "filled" if status == "FILLED" else "unfilled",
                    "order_id": str(order_id),
                    "symbol": binance_symbol,
                    "side": binance_side.lower(),
                    "quantity": quantity,
                    "filled_quantity": filled_qty
                }
            
            logging.error("❌ Binance order failed: No order data returned")
            return {"status": "error", "error": "No order data"}
            
        except Exception as e:
            logging.error(f"Binance order error: {e}")
            return {"status": "error", "error": str(e)}
    
    def get_positions(self) -> List[Dict]:
        """
        Get open positions (non-zero balances).
        
        Returns:
            list: List of position dicts with symbol, quantity, currency
        """
        try:
            if not self.client:
                return []
            
            # Get account balances
            account = self.client.get_account()
            positions = []
            
            for balance in account.get('balances', []):
                asset = balance['asset']
                available = float(balance.get('free', 0))
                
                # Only include non-zero, non-USDT balances
                if asset != 'USDT' and available > 0:
                    # Convert to standard symbol format
                    symbol = f'{asset}USDT'
                    
                    positions.append({
                        'symbol': symbol,
                        'quantity': available,
                        'currency': asset
                    })
            
            return positions
            
        except Exception as e:
            logging.error(f"Error fetching Binance positions: {e}")
            return []
    
    def get_candles(self, symbol: str, timeframe: str, count: int) -> List[Dict]:
        """
        Get historical candle data from Binance.
        
        Args:
            symbol: Trading pair (e.g., 'BTC-USD' or 'BTCUSDT')
            timeframe: Candle interval ('1m', '5m', '15m', '1h', '1d', etc.)
            count: Number of candles to fetch (max 1000)
        
        Returns:
            list: List of candle dicts with OHLCV data
        """
        try:
            if not self.client:
                return []
            
            # Convert symbol format
            binance_symbol = symbol.replace('-USD', 'USDT').replace('-', '')
            
            # Map timeframe to Binance interval
            # Binance uses: 1m, 3m, 5m, 15m, 30m, 1h, 2h, 4h, 6h, 8h, 12h, 1d, 3d, 1w, 1M
            interval_map = {
                "1m": "1m",
                "5m": "5m",
                "15m": "15m",
                "1h": "1h",
                "4h": "4h",
                "1d": "1d"
            }
            
            binance_interval = interval_map.get(timeframe.lower(), "5m")
            
            # Fetch klines (candles)
            klines = self.client.get_klines(
                symbol=binance_symbol,
                interval=binance_interval,
                limit=min(count, 1000)  # Binance max is 1000
            )
            
            candles = []
            for kline in klines:
                # Binance kline format: [timestamp, open, high, low, close, volume, ...]
                candles.append({
                    'time': int(kline[0]),
                    'open': float(kline[1]),
                    'high': float(kline[2]),
                    'low': float(kline[3]),
                    'close': float(kline[4]),
                    'volume': float(kline[5])
                })
            
            return candles
            
        except Exception as e:
            logging.error(f"Error fetching Binance candles: {e}")
            return []
    
    def supports_asset_class(self, asset_class: str) -> bool:
        """Binance supports crypto spot trading"""
        return asset_class.lower() in ["crypto", "cryptocurrency"]


class KrakenBroker(BaseBroker):
    """
    Kraken Pro Exchange integration for cryptocurrency spot trading.
    
    Features:
    - Spot trading (USD/USDT pairs)
    - Market and limit orders
    - Real-time account balance
    - Historical candle data (OHLCV)
    
    Documentation: https://docs.kraken.com/rest/
    Python wrapper: https://github.com/veox/python3-krakenex
    """
    
    def __init__(self):
        super().__init__(BrokerType.KRAKEN)
        self.api = None
        self.kraken_api = None
    
    def connect(self) -> bool:
        """
        Connect to Kraken Pro API.
        
        Requires environment variables:
        - KRAKEN_API_KEY: Your Kraken API key
        - KRAKEN_API_SECRET: Your Kraken API private key
        
        Returns:
            bool: True if connected successfully
        """
        try:
            import krakenex
            from pykrakenapi import KrakenAPI
            
            api_key = os.getenv("KRAKEN_API_KEY", "").strip()
            api_secret = os.getenv("KRAKEN_API_SECRET", "").strip()
            
            if not api_key or not api_secret:
                # Silently skip - Kraken is optional, no need for scary error messages
                logging.info("⚠️  Kraken credentials not configured (skipping)")
                return False
            
            # Initialize Kraken API
            self.api = krakenex.API(key=api_key, secret=api_secret)
            self.kraken_api = KrakenAPI(self.api)
            
            # Test connection by fetching account balance
            balance = self.api.query_private('Balance')
            
            if balance and 'error' in balance:
                if balance['error']:
                    error_msgs = ', '.join(balance['error'])
                    logging.error(f"❌ Kraken connection test failed: {error_msgs}")
                    return False
            
            if balance and 'result' in balance:
                self.connected = True
                logging.info("=" * 70)
                logging.info("✅ KRAKEN PRO CONNECTED")
                logging.info("=" * 70)
                
                # Log USD/USDT balance
                result = balance.get('result', {})
                usd_balance = float(result.get('ZUSD', 0))  # Kraken uses ZUSD for USD
                usdt_balance = float(result.get('USDT', 0))
                
                total = usd_balance + usdt_balance
                logging.info(f"   USD Balance: ${usd_balance:.2f}")
                logging.info(f"   USDT Balance: ${usdt_balance:.2f}")
                logging.info(f"   Total: ${total:.2f}")
                logging.info("=" * 70)
                
                return True
            else:
                logging.error("❌ Kraken connection test failed: No balance data returned")
                return False
                
        except ImportError:
            # SDK not installed - skip silently (it's optional)
            return False
        except Exception as e:
            # Handle errors gracefully
            error_str = str(e).lower()
            if 'api' in error_str and ('key' in error_str or 'signature' in error_str or 'authentication' in error_str):
                logging.warning("⚠️  Kraken authentication failed - invalid or expired API credentials")
            elif 'connection' in error_str or 'network' in error_str or 'timeout' in error_str:
                logging.warning("⚠️  Kraken connection failed - network issue or API unavailable")
            else:
                logging.warning(f"⚠️  Kraken connection failed: {e}")
            return False
    
    def get_account_balance(self) -> float:
        """
        Get USD/USDT balance available for trading.
        
        Returns:
            float: Available USD + USDT balance
        """
        try:
            if not self.api:
                return 0.0
            
            # Get account balance
            balance = self.api.query_private('Balance')
            
            if balance and 'error' in balance and balance['error']:
                error_msgs = ', '.join(balance['error'])
                logging.error(f"Error fetching Kraken balance: {error_msgs}")
                return 0.0
            
            if balance and 'result' in balance:
                result = balance['result']
                
                # Kraken uses ZUSD for USD and USDT for Tether
                usd_balance = float(result.get('ZUSD', 0))
                usdt_balance = float(result.get('USDT', 0))
                
                total = usd_balance + usdt_balance
                logging.info(f"💰 Kraken Balance: USD ${usd_balance:.2f} + USDT ${usdt_balance:.2f} = ${total:.2f}")
                return total
            
            return 0.0
            
        except Exception as e:
            logging.error(f"Error fetching Kraken balance: {e}")
            return 0.0
    
    def place_market_order(self, symbol: str, side: str, quantity: float) -> Dict:
        """
        Place market order on Kraken.
        
        Args:
            symbol: Trading pair (e.g., 'BTC-USD' or 'XBTUSDT')
            side: 'buy' or 'sell'
            quantity: Order size in USD (for buys) or base currency (for sells)
        
        Returns:
            dict: Order result with status, order_id, etc.
        """
        try:
            if not self.api:
                return {"status": "error", "error": "Not connected to Kraken"}
            
            # Convert symbol format to Kraken format
            # Kraken uses XBTUSD, ETHUSD, etc. (no dash)
            # BTC-USD -> XBTUSD, ETH-USD -> ETHUSD
            kraken_symbol = symbol.replace('-', '').upper()
            
            # Kraken uses X prefix for BTC
            if kraken_symbol.startswith('BTC'):
                kraken_symbol = kraken_symbol.replace('BTC', 'XBT', 1)
            
            # Determine order type
            order_type = side.lower()  # 'buy' or 'sell'
            
            # Place market order
            # Kraken API: AddOrder(pair, type, ordertype, volume, ...)
            order_params = {
                'pair': kraken_symbol,
                'type': order_type,
                'ordertype': 'market',
                'volume': str(quantity)
            }
            
            result = self.api.query_private('AddOrder', order_params)
            
            if result and 'error' in result and result['error']:
                error_msgs = ', '.join(result['error'])
                logging.error(f"❌ Kraken order failed: {error_msgs}")
                return {"status": "error", "error": error_msgs}
            
            if result and 'result' in result:
                order_result = result['result']
                txid = order_result.get('txid', [])
                order_id = txid[0] if txid else None
                
                logging.info(f"✅ Kraken order placed: {order_type.upper()} {kraken_symbol}")
                logging.info(f"   Order ID: {order_id}")
                
                return {
                    "status": "filled",
                    "order_id": order_id,
                    "symbol": kraken_symbol,
                    "side": order_type,
                    "quantity": quantity
                }
            
            logging.error("❌ Kraken order failed: No result data")
            return {"status": "error", "error": "No result data"}
            
        except Exception as e:
            logging.error(f"Kraken order error: {e}")
            return {"status": "error", "error": str(e)}
    
    def get_positions(self) -> List[Dict]:
        """
        Get open positions (non-zero balances).
        
        Returns:
            list: List of position dicts with symbol, quantity, currency
        """
        try:
            if not self.api:
                return []
            
            # Get account balance
            balance = self.api.query_private('Balance')
            
            if balance and 'error' in balance and balance['error']:
                error_msgs = ', '.join(balance['error'])
                logging.error(f"Error fetching Kraken positions: {error_msgs}")
                return []
            
            if balance and 'result' in balance:
                result = balance['result']
                positions = []
                
                for asset, amount in result.items():
                    balance_val = float(amount)
                    
                    # Skip USD/USDT and zero balances
                    if asset in ['ZUSD', 'USDT'] or balance_val <= 0:
                        continue
                    
                    # Convert Kraken asset codes to standard format
                    # XXBT -> BTC, XETH -> ETH, etc.
                    currency = asset
                    if currency.startswith('X') and len(currency) == 4:
                        currency = currency[1:]
                    if currency == 'XBT':
                        currency = 'BTC'
                    
                    # Create symbol (e.g., BTCUSD)
                    symbol = f'{currency}USD'
                    
                    positions.append({
                        'symbol': symbol,
                        'quantity': balance_val,
                        'currency': currency
                    })
                
                return positions
            
            return []
            
        except Exception as e:
            logging.error(f"Error fetching Kraken positions: {e}")
            return []
    
    def get_candles(self, symbol: str, timeframe: str, count: int) -> List[Dict]:
        """
        Get historical candle data from Kraken.
        
        Args:
            symbol: Trading pair (e.g., 'BTC-USD' or 'XBTUSD')
            timeframe: Candle interval ('1m', '5m', '15m', '1h', '1d', etc.)
            count: Number of candles to fetch (max 720)
        
        Returns:
            list: List of candle dicts with OHLCV data
        """
        try:
            if not self.kraken_api:
                return []
            
            # Convert symbol format to Kraken format
            kraken_symbol = symbol.replace('-', '').upper()
            if kraken_symbol.startswith('BTC'):
                kraken_symbol = kraken_symbol.replace('BTC', 'XBT', 1)
            
            # Map timeframe to Kraken interval (in minutes)
            # Kraken supports: 1, 5, 15, 30, 60, 240, 1440, 10080, 21600
            interval_map = {
                "1m": 1,
                "5m": 5,
                "15m": 15,
                "30m": 30,
                "1h": 60,
                "4h": 240,
                "1d": 1440
            }
            
            kraken_interval = interval_map.get(timeframe.lower(), 5)
            
            # Fetch OHLC data using pykrakenapi
            ohlc, last = self.kraken_api.get_ohlc_data(
                kraken_symbol,
                interval=kraken_interval,
                ascending=True
            )
            
            # Convert to standard format
            candles = []
            for idx, row in ohlc.tail(count).iterrows():
                candles.append({
                    'time': int(idx.timestamp()),
                    'open': float(row['open']),
                    'high': float(row['high']),
                    'low': float(row['low']),
                    'close': float(row['close']),
                    'volume': float(row['volume'])
                })
            
            return candles
            
        except Exception as e:
            logging.error(f"Error fetching Kraken candles: {e}")
            return []
    
    def supports_asset_class(self, asset_class: str) -> bool:
        """Kraken supports crypto spot trading"""
        return asset_class.lower() in ["crypto", "cryptocurrency"]


class OKXBroker(BaseBroker):
    """
    OKX Exchange integration for crypto spot and futures trading.
    
    Features:
    - Spot trading (USDT pairs)
    - Futures/perpetual contracts  
    - Testnet support for paper trading
    - Advanced order types
    
    Documentation: https://www.okx.com/docs-v5/en/
    Python SDK: https://github.com/okx/okx-python-sdk
    """
    
    def __init__(self):
        super().__init__(BrokerType.OKX)
        self.client = None
        self.account_api = None
        self.market_api = None
        self.trade_api = None
        self.use_testnet = False
    
    def connect(self) -> bool:
        """
        Connect to OKX Exchange API.
        
        Requires environment variables:
        - OKX_API_KEY: Your OKX API key
        - OKX_API_SECRET: Your OKX API secret
        - OKX_PASSPHRASE: Your OKX API passphrase
        - OKX_USE_TESTNET: 'true' for testnet, 'false' for live (optional, default: false)
        
        Returns:
            bool: True if connected successfully
        """
        try:
            from okx.api import Account, Market, Trade
            
            api_key = os.getenv("OKX_API_KEY", "").strip()
            api_secret = os.getenv("OKX_API_SECRET", "").strip()
            passphrase = os.getenv("OKX_PASSPHRASE", "").strip()
            self.use_testnet = os.getenv("OKX_USE_TESTNET", "false").lower() in ["true", "1", "yes"]
            
            if not api_key or not api_secret or not passphrase:
                # Silently skip - OKX is optional, no need for scary error messages
                logging.info("⚠️  OKX credentials not configured (skipping)")
                return False
            
            
            # Check for placeholder passphrase (most common user error)
            # Note: Only checking passphrase because API keys are UUIDs/hex without obvious placeholder patterns
            if passphrase in PLACEHOLDER_PASSPHRASE_VALUES:
                logging.warning("⚠️  OKX passphrase appears to be a placeholder value")
                logging.warning("   Please set a valid OKX_PASSPHRASE in your environment")
                return False
            
            # Determine API flag (0 = live, 1 = testnet)
            flag = "1" if self.use_testnet else "0"
            
            # Initialize OKX API clients
            self.account_api = Account(api_key, api_secret, passphrase, flag)
            self.market_api = Market(api_key, api_secret, passphrase, flag)
            self.trade_api = Trade(api_key, api_secret, passphrase, flag)
            
            # Test connection by fetching account balance
            result = self.account_api.get_balance()
            
            if result and result.get('code') == '0':
                self.connected = True
                env_type = "🧪 TESTNET" if self.use_testnet else "🔴 LIVE"
                logging.info("=" * 70)
                logging.info(f"✅ OKX CONNECTED ({env_type})")
                logging.info("=" * 70)
                
                # Log account info
                data = result.get('data', [])
                if data and len(data) > 0:
                    total_eq = data[0].get('totalEq', '0')
                    logging.info(f"   Total Account Value: ${float(total_eq):.2f}")
                
                logging.info("=" * 70)
                return True
            else:
                error_msg = result.get('msg', 'Unknown error') if result else 'No response'
                logging.warning(f"⚠️  OKX connection test failed: {error_msg}")
                return False
                
        except ImportError:
            # SDK not installed - skip silently (it's optional)
            return False
        except Exception as e:
            # Handle authentication errors gracefully
            # Note: OKX error code 50119 = "API key doesn't exist"
            error_str = str(e).lower()
            if 'api key' in error_str or '401' in error_str or 'authentication' in error_str or '50119' in error_str:
                logging.warning("⚠️  OKX authentication failed - invalid or expired API credentials")
                logging.warning("   Please check your OKX_API_KEY, OKX_API_SECRET, and OKX_PASSPHRASE")
            elif 'connection' in error_str or 'network' in error_str or 'timeout' in error_str:
                logging.warning("⚠️  OKX connection failed - network issue or API unavailable")
            else:
                logging.warning(f"⚠️  OKX connection failed: {e}")
            return False
    
    def get_account_balance(self) -> float:
        """
        Get USDT balance available for trading.
        
        Returns:
            float: Available USDT balance
        """
        try:
            if not self.account_api:
                return 0.0
            
            # Get account balance
            result = self.account_api.get_balance()
            
            if result and result.get('code') == '0':
                data = result.get('data', [])
                if data and len(data) > 0:
                    details = data[0].get('details', [])
                    
                    # Find USDT balance
                    for detail in details:
                        if detail.get('ccy') == 'USDT':
                            available = float(detail.get('availBal', 0))
                            logging.info(f"💰 OKX USDT Balance: ${available:.2f}")
                            return available
                
                # No USDT found
                logging.warning("⚠️  No USDT balance found in OKX account")
                return 0.0
            else:
                error_msg = result.get('msg', 'Unknown error') if result else 'No response'
                logging.error(f"Error fetching OKX balance: {error_msg}")
                return 0.0
                
        except Exception as e:
            logging.error(f"Error fetching OKX balance: {e}")
            return 0.0
    
    def place_market_order(self, symbol: str, side: str, quantity: float) -> Dict:
        """
        Place market order on OKX.
        
        Args:
            symbol: Trading pair (e.g., 'BTC-USDT')
            side: 'buy' or 'sell'
            quantity: Order size in USDT (for buys) or base currency (for sells)
        
        Returns:
            dict: Order result with status, order_id, etc.
        """
        try:
            if not self.trade_api:
                return {"status": "error", "error": "Not connected to OKX"}
            
            # Convert symbol format if needed (BTC-USD -> BTC-USDT)
            okx_symbol = symbol.replace('-USD', '-USDT') if '-USD' in symbol else symbol
            
            # Determine order side (buy/sell)
            okx_side = side.lower()
            
            # Place market order
            # For spot trading: tdMode = 'cash'
            # For margin/futures: tdMode = 'cross' or 'isolated'
            result = self.trade_api.place_order(
                instId=okx_symbol,
                tdMode='cash',  # Spot trading mode
                side=okx_side,
                ordType='market',
                sz=str(quantity)
            )
            
            if result and result.get('code') == '0':
                data = result.get('data', [])
                if data and len(data) > 0:
                    order_id = data[0].get('ordId')
                    logging.info(f"✅ OKX order placed: {okx_side.upper()} {okx_symbol} (Order ID: {order_id})")
                    return {
                        "status": "filled",
                        "order_id": order_id,
                        "symbol": okx_symbol,
                        "side": okx_side,
                        "quantity": quantity
                    }
            
            error_msg = result.get('msg', 'Unknown error') if result else 'No response'
            logging.error(f"❌ OKX order failed: {error_msg}")
            return {"status": "error", "error": error_msg}
            
        except Exception as e:
            logging.error(f"OKX order error: {e}")
            return {"status": "error", "error": str(e)}
    
    def get_positions(self) -> List[Dict]:
        """
        Get open positions (non-zero balances).
        
        Returns:
            list: List of position dicts with symbol, quantity, currency
        """
        try:
            if not self.account_api:
                return []
            
            # Get account balance to see all assets
            result = self.account_api.get_balance()
            
            if result and result.get('code') == '0':
                positions = []
                data = result.get('data', [])
                
                if data and len(data) > 0:
                    details = data[0].get('details', [])
                    
                    for detail in details:
                        ccy = detail.get('ccy')
                        available = float(detail.get('availBal', 0))
                        
                        # Only include non-zero, non-USDT balances
                        if ccy != 'USDT' and available > 0:
                            positions.append({
                                'symbol': f'{ccy}-USDT',
                                'quantity': available,
                                'currency': ccy
                            })
                
                return positions
            
            return []
            
        except Exception as e:
            logging.error(f"Error fetching OKX positions: {e}")
            return []
    
    def get_candles(self, symbol: str, timeframe: str, count: int) -> List[Dict]:
        """
        Get historical candle data from OKX.
        
        Args:
            symbol: Trading pair (e.g., 'BTC-USDT')
            timeframe: Candle interval ('1m', '5m', '15m', '1H', '1D', etc.)
            count: Number of candles to fetch (max 100)
        
        Returns:
            list: List of candle dicts with OHLCV data
        """
        try:
            if not self.market_api:
                return []
            
            # Convert symbol format if needed
            okx_symbol = symbol.replace('-USD', '-USDT') if '-USD' in symbol else symbol
            
            # Map timeframe to OKX format
            # OKX uses: 1m, 3m, 5m, 15m, 30m, 1H, 2H, 4H, 6H, 12H, 1D, 1W, 1M
            timeframe_map = {
                "1m": "1m",
                "5m": "5m", 
                "15m": "15m",
                "1h": "1H",
                "4h": "4H",
                "1d": "1D"
            }
            
            okx_timeframe = timeframe_map.get(timeframe.lower(), "5m")
            
            # Fetch candles
            result = self.market_api.get_candles(
                instId=okx_symbol,
                bar=okx_timeframe,
                limit=str(min(count, 100))  # OKX max is 100
            )
            
            if result and result.get('code') == '0':
                data = result.get('data', [])
                candles = []
                
                for candle in data:
                    # OKX candle format: [timestamp, open, high, low, close, volume, volumeCcy, volumeCcyQuote, confirm]
                    candles.append({
                        'time': int(candle[0]),
                        'open': float(candle[1]),
                        'high': float(candle[2]),
                        'low': float(candle[3]),
                        'close': float(candle[4]),
                        'volume': float(candle[5])
                    })
                
                return candles
            
            return []
            
        except Exception as e:
            logging.error(f"Error fetching OKX candles: {e}")
            return []
    
    def supports_asset_class(self, asset_class: str) -> bool:
        """OKX supports crypto spot and futures"""
        return asset_class.lower() in ["crypto", "futures"]


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
