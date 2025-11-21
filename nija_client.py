import time
import requests
import logging

# Defensive import for JWT
try:
    import jwt
except ImportError:
    raise RuntimeError(
        "PyJWT is required but not installed. "
        "Install it with: pip install PyJWT>=2.6.0"
    )

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


def check_live_safety():
    """
    Validate MODE and ACCOUNT rules for safe trading.
    Raises RuntimeError if safety checks fail.
    """
    if MODE == "LIVE":
        if not COINBASE_ACCOUNT_ID:
            raise RuntimeError(
                "LIVE mode requires COINBASE_ACCOUNT_ID environment variable to be set"
            )
        if not CONFIRM_LIVE:
            raise RuntimeError(
                "LIVE mode requires CONFIRM_LIVE=true environment variable to be set. "
                "This is a safety measure to prevent accidental live trading."
            )
        logger.warning("⚠️  LIVE TRADING MODE ENABLED - Real money will be used!")
    elif MODE == "SANDBOX":
        logger.info("🏖️  SANDBOX mode - using test environment")
    elif MODE == "DRY_RUN":
        logger.info("🔍 DRY_RUN mode - no real orders will be placed")
    else:
        raise RuntimeError(
            f"Invalid MODE: {MODE}. Must be one of: SANDBOX, DRY_RUN, LIVE"
        )


def check_api_key_permissions(client_instance):
    """
    Check if API key has withdraw permission and refuse to run if present.
    This is a safety measure to prevent unauthorized withdrawals.
    """
    try:
        # Try to get API key permissions if the method exists
        if hasattr(client_instance, 'get_api_key_permissions'):
            permissions = client_instance.get_api_key_permissions()
            if permissions and 'withdraw' in str(permissions).lower():
                raise RuntimeError(
                    "API key has WITHDRAW permission enabled. "
                    "For safety, please create a new API key without withdraw permission."
                )
        else:
            # Fallback: warn the user to manually verify
            logger.warning(
                "⚠️  Unable to verify API key permissions automatically. "
                "Please ensure your API key does NOT have withdraw permission enabled."
            )
    except Exception as e:
        if "withdraw" in str(e).lower():
            raise
        logger.warning(f"Could not check API key permissions: {e}")

class CoinbaseClient:
    def __init__(self):
        # Perform safety checks before initializing
        check_live_safety()
        
        self.base_url = COINBASE_API_BASE
        self.jwt_token = self.generate_jwt()
        self.headers = {
            "Authorization": f"Bearer {self.jwt_token}",
            "CB-VERSION": "2025-01-01",
            "Content-Type": "application/json"
        }
        
        # Check API key permissions for safety
        check_api_key_permissions(self)

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
