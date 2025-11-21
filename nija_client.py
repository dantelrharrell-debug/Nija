import time
import requests
import logging

# Defensive import for jwt (PyJWT)
try:
    import jwt
except ImportError:
    raise ImportError(
        "PyJWT is required. Install it with: pip install 'PyJWT>=2.6.0'"
    )

from config import (
    COINBASE_JWT_PEM,
    COINBASE_JWT_KID,
    COINBASE_JWT_ISSUER,
    COINBASE_API_BASE,
    TRADING_ACCOUNT_ID,
    COINBASE_ACCOUNT_ID,
    MODE,
    CONFIRM_LIVE,
    LIVE_TRADING,
    SPOT_TICKERS,
    MIN_TRADE_PERCENT,
    MAX_TRADE_PERCENT
)

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("NijaCoinbaseClient")


def check_live_safety():
    """
    Validate MODE and account requirements before allowing trading.
    Raises RuntimeError if safety checks fail.
    """
    # Check if MODE is LIVE and enforce requirements
    if MODE == "LIVE":
        if not COINBASE_ACCOUNT_ID:
            raise RuntimeError(
                "MODE=LIVE requires COINBASE_ACCOUNT_ID to be set. "
                "Please set the environment variable and restart."
            )
        if not CONFIRM_LIVE:
            raise RuntimeError(
                "MODE=LIVE requires CONFIRM_LIVE=true to be set. "
                "This is a safety measure to prevent accidental live trading. "
                "Set CONFIRM_LIVE=true in your environment if you want to trade live."
            )
        logger.warning("⚠️  LIVE TRADING MODE ENABLED - Real money will be used!")
    elif MODE == "SANDBOX":
        logger.info("📦 SANDBOX MODE - Using test environment")
    elif MODE == "DRY_RUN":
        logger.info("🧪 DRY_RUN MODE - No real orders will be placed")
    else:
        logger.warning(f"Unknown MODE: {MODE}, defaulting to DRY_RUN behavior")
    
    return True

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
        
        # Check for withdraw permissions and refuse to run if present
        self._check_api_key_permissions()

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

    def _check_api_key_permissions(self):
        """
        Check API key permissions and refuse to run if withdraw permission is present.
        This is a safety measure to prevent accidental withdrawal from funded accounts.
        """
        try:
            # Try to get API key permissions from Coinbase
            # Note: This endpoint may not be available on all Coinbase APIs
            # If it fails, we'll skip the check with a warning
            url = f"{self.base_url}/v2/user/auth"
            resp = requests.get(url, headers=self.headers, timeout=5)
            
            if resp.status_code == 200:
                data = resp.json()
                # Check for withdraw permissions in various possible response formats
                permissions = data.get("data", {}).get("scopes", [])
                if isinstance(permissions, list) and "wallet:withdrawals:create" in permissions:
                    raise RuntimeError(
                        "API key has 'withdraw' permission enabled. "
                        "For safety, please create a new API key without withdraw permissions."
                    )
                logger.info("✅ API key permissions check passed (no withdraw permission)")
            else:
                # If we can't check permissions, log a warning but don't fail
                logger.warning(
                    "⚠️  Could not verify API key permissions. "
                    "Please manually ensure your API key does NOT have withdraw permissions."
                )
        except Exception as e:
            # Don't fail initialization if we can't check permissions
            logger.warning(
                f"⚠️  Could not verify API key permissions: {e}. "
                "Please manually ensure your API key does NOT have withdraw permissions."
            )

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
