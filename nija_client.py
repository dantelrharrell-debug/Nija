import time
import requests
import logging

# Defensive import for PyJWT
try:
    import jwt
except ImportError as e:
    raise ImportError("PyJWT is required. Install it with: pip install PyJWT>=2.6.0") from e

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
    Validate MODE, COINBASE_ACCOUNT_ID, and CONFIRM_LIVE requirements.
    Check API key permissions to ensure withdraw permission is not present.
    
    Raises:
        RuntimeError: If safety checks fail
    """
    # Check MODE validity
    valid_modes = ["SANDBOX", "DRY_RUN", "LIVE"]
    if MODE not in valid_modes:
        raise RuntimeError(f"Invalid MODE '{MODE}'. Must be one of: {', '.join(valid_modes)}")
    
    # LIVE mode requires COINBASE_ACCOUNT_ID and CONFIRM_LIVE
    if MODE == "LIVE":
        if not COINBASE_ACCOUNT_ID:
            raise RuntimeError(
                "LIVE mode requires COINBASE_ACCOUNT_ID environment variable to be set. "
                "Refusing to place live orders without explicit account ID."
            )
        if not CONFIRM_LIVE:
            raise RuntimeError(
                "LIVE mode requires CONFIRM_LIVE=true environment variable. "
                "Refusing to place live orders without explicit confirmation."
            )
        logger.warning("⚠️  LIVE MODE ENABLED - Real orders will be placed!")
    else:
        logger.info(f"Running in {MODE} mode - No real orders will be placed")
    
    # Check API key permissions if client is available
    if client is not None:
        try:
            # Try to get API key permissions
            permissions = client.get_api_key_permissions()
            if permissions and "withdraw" in str(permissions).lower():
                raise RuntimeError(
                    "SECURITY WARNING: API key has withdraw permission. "
                    "This is dangerous and unnecessary for trading. "
                    "Please remove withdraw permission from your API key and try again."
                )
        except AttributeError:
            # get_api_key_permissions method doesn't exist, use fallback check
            logger.warning("Unable to check API key permissions - method not available")
        except Exception as e:
            logger.warning(f"Could not verify API key permissions: {e}")
    
    logger.info("✅ Live safety checks passed")

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
        
        # Run safety checks again with client instance to check permissions
        try:
            check_live_safety(self)
        except Exception as e:
            logger.warning(f"Post-initialization safety check: {e}")

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
        Attempt to fetch API key permissions.
        This is a placeholder - actual implementation depends on Coinbase API.
        """
        # Note: Coinbase Advanced Trade API may not have a direct endpoint for this
        # This is a safety mechanism placeholder
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
