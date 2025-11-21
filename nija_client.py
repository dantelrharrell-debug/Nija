import time
import requests
import logging

# Defensive import for jwt (PyJWT)
try:
    import jwt
except ImportError as e:
    raise ImportError(
        "PyJWT is required. Install it with: pip install PyJWT>=2.6.0"
    ) from e

from config import (
    COINBASE_JWT_PEM,
    COINBASE_JWT_KID,
    COINBASE_JWT_ISSUER,
    COINBASE_API_BASE,
    TRADING_ACCOUNT_ID,
    LIVE_TRADING,
    SPOT_TICKERS,
    MIN_TRADE_PERCENT,
    MAX_TRADE_PERCENT,
    MODE,
    COINBASE_ACCOUNT_ID,
    CONFIRM_LIVE
)

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("NijaCoinbaseClient")

def check_live_safety(client=None):
    """
    Validate MODE, COINBASE_ACCOUNT_ID, and CONFIRM_LIVE requirements
    Also checks API key permissions to ensure withdraw permission is not present
    
    Args:
        client: Optional CoinbaseClient instance to check permissions
    
    Raises:
        RuntimeError: If safety checks fail
    """
    # Check MODE requirements
    if MODE == 'LIVE':
        if not COINBASE_ACCOUNT_ID:
            raise RuntimeError(
                "MODE=LIVE requires COINBASE_ACCOUNT_ID to be set. "
                "This prevents accidental trading from a funded account."
            )
        if not CONFIRM_LIVE:
            raise RuntimeError(
                "MODE=LIVE requires CONFIRM_LIVE=true to be set. "
                "This is a safety check to prevent accidental live trading."
            )
        logger.warning("🔴 LIVE TRADING MODE ENABLED - Real money at risk!")
    elif MODE == 'DRY_RUN':
        logger.info("✅ DRY_RUN mode - No real orders will be placed")
    elif MODE == 'SANDBOX':
        logger.info("✅ SANDBOX mode - Using test environment")
    else:
        raise RuntimeError(f"Invalid MODE={MODE}. Must be SANDBOX, DRY_RUN, or LIVE")
    
    # Check API key permissions if client is available
    if client:
        try:
            # Try to get API key permissions
            permissions = client.get_api_key_permissions()
            if permissions:
                # Check for withdraw in permissions more carefully
                # Look in common permission structures
                perms_str = str(permissions).lower()
                scopes = permissions.get('scopes', []) if isinstance(permissions, dict) else []
                
                # Check if withdraw is explicitly in scopes list
                has_withdraw = any('withdraw' in str(scope).lower() for scope in scopes)
                
                # Fallback to string search if scopes not available
                if not scopes and 'withdraw' in perms_str:
                    has_withdraw = True
                
                if has_withdraw:
                    raise RuntimeError(
                        "API key has WITHDRAW permission! This is unsafe. "
                        "Please create a new API key without withdraw permission."
                    )
                logger.info("✅ API key permissions check passed (no withdraw)")
            else:
                logger.warning("⚠️  Could not retrieve API key permissions")
        except AttributeError:
            # Method doesn't exist - use fallback check
            logger.warning("⚠️  Could not check API key permissions (method not available)")
        except RuntimeError:
            # Re-raise RuntimeError from permission check
            raise
        except Exception as e:
            logger.warning(f"⚠️  Could not verify API key permissions: {e}")

class CoinbaseClient:
    def __init__(self):
        # Run safety checks before initializing
        check_live_safety()
        
        self.base_url = COINBASE_API_BASE
        self.jwt_token = self.generate_jwt()
        self.headers = {
            "Authorization": f"Bearer {self.jwt_token}",
            "CB-VERSION": "2025-01-01",
            "Content-Type": "application/json"
        }
        
        # Check permissions after client is initialized
        check_live_safety(self)

    def generate_jwt(self):
        now = int(time.time())
        payload = {
            "iat": now,
            "exp": now + 60,  # short-lived token
            "sub": COINBASE_JWT_ISSUER
        }
        token = jwt.encode(
            payload,
            COINBASE_JWT_PEM,
            algorithm="ES256",
            headers={"kid": COINBASE_JWT_KID}
        )
        return token

    def get_accounts(self):
        url = f"{self.base_url}/v2/accounts"
        try:
            resp = requests.get(url, headers=self.headers)
            resp.raise_for_status()
            data = resp.json()
            logger.info(f"Fetched {len(data.get('data', []))} accounts")
            return data.get("data", [])
        except Exception as e:
            logger.error(f"Failed to fetch accounts: {e}")
            return []

    def get_api_key_permissions(self):
        """
        Get API key permissions to check for unsafe permissions like withdraw
        
        Returns:
            dict or list: API key permissions data, or None if unavailable
        """
        # Try different endpoints that might return permissions
        endpoints = [
            "/v2/user/auth",
            "/v2/user",
        ]
        
        for endpoint in endpoints:
            url = f"{self.base_url}{endpoint}"
            try:
                resp = requests.get(url, headers=self.headers)
                resp.raise_for_status()
                data = resp.json()
                
                # Look for permissions in the response
                if 'scopes' in data or 'permissions' in data:
                    return data
                
            except Exception:
                continue
        
        # Permissions not available through API
        return None

    def get_account_balance(self, account_id=TRADING_ACCOUNT_ID):
        url = f"{self.base_url}/v2/accounts/{account_id}"
        try:
            resp = requests.get(url, headers=self.headers)
            resp.raise_for_status()
            data = resp.json()
            balance = float(data.get("data", {}).get("balance", {}).get("amount", 0))
            logger.info(f"Account {account_id} balance: {balance}")
            return balance
        except Exception as e:
            logger.error(f"Failed to fetch account balance: {e}")
            return 0.0

    def place_order(self, symbol, side, size_usd):
        """
        Place a market order on Coinbase Advanced.
        - side: 'buy' or 'sell'
        - size_usd: order amount in USD
        """
        url = f"{self.base_url}/v2/accounts/{TRADING_ACCOUNT_ID}/orders"
        payload = {
            "type": "market",
            "side": side,
            "product_id": symbol,
            "funds": str(size_usd)  # amount in USD
        }
        if not LIVE_TRADING:
            logger.info(f"DRY RUN: {side.upper()} {size_usd}$ {symbol}")
            return {"status": "dry_run"}

        try:
            resp = requests.post(url, json=payload, headers=self.headers)
            resp.raise_for_status()
            data = resp.json()
            logger.info(f"Order placed: {data}")
            return data
        except Exception as e:
            logger.error(f"Failed to place order: {e}")
            return {"status": "failed", "error": str(e)}

    def auto_scale_order(self, balance, side, symbol):
        """
        Auto-scale trade size based on account balance and min/max percentages
        """
        size_usd = max(MIN_TRADE_PERCENT/100*balance,
                       min(MAX_TRADE_PERCENT/100*balance, balance))
        return self.place_order(symbol, side, size_usd)


# ===========================
# Example Usage
# ===========================
if __name__ == "__main__":
    client = CoinbaseClient()
    account_balance = client.get_account_balance()

    # Example: Place a scaled BUY for each ticker
    for ticker in SPOT_TICKERS:
        client.auto_scale_order(account_balance, "buy", ticker)
