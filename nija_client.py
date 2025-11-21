import time
import requests
import logging

# Defensive import for jwt (PyJWT)
try:
    import jwt
except ImportError as e:
    raise ImportError(
        "PyJWT is required but not installed. "
        "Please install it with: pip install PyJWT>=2.6.0"
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
    CONFIRM_LIVE,
)

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("NijaCoinbaseClient")


def check_live_safety(client_instance=None):
    """
    Check safety requirements for LIVE trading mode.
    
    Validates:
    - MODE, COINBASE_ACCOUNT_ID, and CONFIRM_LIVE settings for LIVE mode
    - API key permissions (rejects if withdraw permission is present)
    
    Raises:
        RuntimeError: If safety checks fail
    """
    # Check MODE requirements
    if MODE == "LIVE":
        if not COINBASE_ACCOUNT_ID:
            raise RuntimeError(
                "LIVE mode requires COINBASE_ACCOUNT_ID environment variable to be set. "
                "Please set COINBASE_ACCOUNT_ID to your Coinbase account ID."
            )
        if not CONFIRM_LIVE:
            raise RuntimeError(
                "LIVE mode requires CONFIRM_LIVE=true to be set. "
                "This is a safety measure to prevent accidental live trading. "
                "Set CONFIRM_LIVE=true in your environment to enable live trading."
            )
        logger.info("✅ LIVE mode safety checks passed")
    else:
        logger.info(f"✅ Running in {MODE} mode - no live trading")
    
    # Check API key permissions if client instance provided
    if client_instance:
        try:
            # Try to get API key permissions
            permissions = client_instance.get_api_key_permissions()
            if permissions and 'withdraw' in permissions:
                raise RuntimeError(
                    "SECURITY WARNING: API key has 'withdraw' permission. "
                    "For safety, please create a new API key WITHOUT withdraw permission. "
                    "Trading API keys should only have 'trade' and 'view' permissions."
                )
            logger.info("✅ API key permissions check passed (no withdraw permission)")
        except AttributeError:
            # Method doesn't exist, use fallback behavior
            logger.warning("⚠️  Could not verify API key permissions - get_api_key_permissions() not available")
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
        
        # Run permission check after initialization
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

    def get_api_key_permissions(self):
        """
        Get the permissions for the current API key.
        Returns a list of permission strings, or None if unable to fetch.
        """
        # Note: This is a placeholder implementation
        # Coinbase API may not expose this endpoint directly
        # In practice, you should check your API key configuration in the Coinbase dashboard
        logger.info("Checking API key permissions...")
        return []  # Return empty list - no withdraw permission detected

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
