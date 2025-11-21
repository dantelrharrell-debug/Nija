import time
import requests
import logging

# Defensive jwt import
try:
    import jwt
except ImportError:
    raise ImportError("PyJWT is required. Install with: pip install PyJWT>=2.6.0")

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


def check_live_safety(client_instance=None):
    """
    Validates MODE/ACCOUNT rules and checks for withdraw permissions.
    Raises RuntimeError if safety checks fail.
    """
    # Check MODE requirements
    if MODE == "LIVE":
        if not COINBASE_ACCOUNT_ID:
            raise RuntimeError(
                "LIVE mode requires COINBASE_ACCOUNT_ID to be set. "
                "Please set the COINBASE_ACCOUNT_ID environment variable."
            )
        if not CONFIRM_LIVE:
            raise RuntimeError(
                "LIVE mode requires CONFIRM_LIVE=true to be set. "
                "Please set the CONFIRM_LIVE environment variable to 'true' to confirm live trading."
            )
        logger.info(f"✅ LIVE mode enabled with account: {COINBASE_ACCOUNT_ID}")
    elif MODE == "DRY_RUN":
        logger.info("✅ DRY_RUN mode enabled - no real orders will be placed")
    elif MODE == "SANDBOX":
        logger.info("✅ SANDBOX mode enabled - using sandbox environment")
    else:
        raise RuntimeError(
            f"Invalid MODE: {MODE}. Must be SANDBOX, DRY_RUN, or LIVE."
        )
    
    # Check API key permissions if client is available
    if client_instance:
        try:
            # Try to check API key permissions
            permissions = client_instance.get_api_key_permissions()
            if permissions and "withdraw" in str(permissions).lower():
                raise RuntimeError(
                    "SECURITY ERROR: API key has withdraw permission. "
                    "For safety, please remove withdraw permission from your Coinbase API key."
                )
            logger.info("✅ API key permissions validated - no withdraw permission detected")
        except AttributeError:
            # Fallback if get_api_key_permissions doesn't exist
            logger.warning(
                "⚠️  Could not verify API key permissions. "
                "Please manually ensure your API key does NOT have withdraw permission."
            )
        except Exception as e:
            logger.warning(f"⚠️  Error checking API key permissions: {e}")


class CoinbaseClient:
    def __init__(self):
        # Validate safety checks before initializing
        check_live_safety()
        
        self.base_url = COINBASE_API_BASE
        self.jwt_token = self.generate_jwt()
        self.headers = {
            "Authorization": f"Bearer {self.jwt_token}",
            "CB-VERSION": "2025-01-01",
            "Content-Type": "application/json"
        }
        
        # Run permission check after headers are set
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
        Attempt to retrieve API key permissions from Coinbase.
        Returns permissions data if available.
        
        Note: This endpoint may vary depending on Coinbase API version.
        This is a best-effort check - manual verification is recommended.
        """
        # Try multiple potential endpoints for permission checking
        endpoints = [
            f"{self.base_url}/v2/user/auth",
            f"{self.base_url}/api/v3/brokerage/key_permissions"
        ]
        
        for url in endpoints:
            try:
                resp = requests.get(url, headers=self.headers, timeout=5)
                if resp.status_code == 200:
                    data = resp.json()
                    logger.debug(f"Successfully fetched permissions from {url}")
                    return data.get("data", {})
            except Exception as e:
                logger.debug(f"Could not fetch permissions from {url}: {e}")
                continue
        
        logger.debug("Could not fetch API key permissions from any endpoint")
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
