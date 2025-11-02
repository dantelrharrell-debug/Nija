# nija_client.py
import os
import logging
from decimal import Decimal
from coinbase.rest import RESTClient as CoinbaseClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_client")

# -----------------------------
# --- Load Coinbase credentials
# -----------------------------
API_KEY = os.environ.get("COINBASE_API_KEY")
API_SECRET = os.environ.get("COINBASE_API_SECRET")
API_PASSPHRASE = os.environ.get("COINBASE_API_PASSPHRASE", None)  # optional

if not API_KEY or not API_SECRET:
    raise RuntimeError("❌ Missing Coinbase API_KEY or API_SECRET in environment")

# -----------------------------
# --- Initialize live client
# -----------------------------
try:
    client = CoinbaseClient(api_key=API_KEY, api_secret=API_SECRET)
    logger.info("[NIJA] Coinbase RESTClient initialized ✅")
except Exception as e:
    logger.error(f"❌ Failed to initialize Coinbase RESTClient: {e}")
    raise e

# -----------------------------
# --- Optional: Expose class
# -----------------------------
CLIENT_CLASS = CoinbaseClient

# -----------------------------
# --- Helper: Get USD balance
# -----------------------------
def get_usd_balance(client_obj=None) -> Decimal:
    """
    Fetch USD balance from Coinbase account.
    Returns Decimal(0) if fetch fails.
    """
    client_obj = client_obj or client
    try:
        accounts = client_obj.get_accounts()  # list of accounts
        usd_account = next(acc for acc in accounts if acc['currency'] == 'USD')
        balance = Decimal(usd_account['balance']['amount'])
        return balance
    except StopIteration:
        logger.warning("[NIJA] No USD account found")
        return Decimal(0)
    except Exception as e:
        logger.error(f"[NIJA] Failed to fetch USD balance: {e}")
        return Decimal(0)

# -----------------------------
# --- Test initialization
# -----------------------------
if __name__ == "__main__":
    balance = get_usd_balance()
    logger.info(f"[NIJA-TEST] USD Balance: {balance}")

# nija_client.py
import os
import logging
from decimal import Decimal
from pathlib import Path

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_client")

# ---- Config ----
PEM_PATH = os.getenv("COINBASE_PEM_PATH", "/opt/render/project/secrets/coinbase.pem")
PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT") or os.getenv("COINBASE_API_SECRET")
API_KEY = os.getenv("COINBASE_API_KEY")
API_PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE")

# ---- Try import popular Coinbase client implementations ----
CLIENT_CLASS = None
_client_ctor = None
_import_source = None

# Try coinbase_advanced_py (pip package coinbase-advanced-py)
try:
    # typical path seen in some installs
    from coinbase_advanced_py.client import CoinbaseClient as CAP_Client
    CLIENT_CLASS = CAP_Client
    _client_ctor = "coinbase_advanced_py"
    _import_source = "coinbase_advanced_py.client.CoinbaseClient"
    logger.info("[NIJA] Using coinbase_advanced_py CoinbaseClient.")
except Exception:
    pass

# Try coinbase_advancedtrade_python (another packaging name)
if CLIENT_CLASS is None:
    try:
        from coinbase_advancedtrade_python.client import Client as CAT_Client
        CLIENT_CLASS = CAT_Client
        _client_ctor = "coinbase_advancedtrade_python"
        _import_source = "coinbase_advancedtrade_python.client.Client"
        logger.info("[NIJA] Using coinbase_advancedtrade_python Client.")
    except Exception:
        pass

# If no client implementation found — fail loudly.
if CLIENT_CLASS is None:
    raise ImportError(
        "❌ Could not import Coinbase client class. "
        "Install one of: `pip install coinbase-advanced-py==1.8.2` or "
        "`pip install coinbase-advancedtrade-python` and ensure the import path matches."
    )

# ---- Helper: write PEM if provided via env ----
def _ensure_pem():
    if PEM_CONTENT:
        pem_path = Path(PEM_PATH)
        pem_path.parent.mkdir(parents=True, exist_ok=True)
        pem_path.write_text(PEM_CONTENT)
        logger.info(f"[NIJA] PEM written to {pem_path}")
        return str(pem_path)
    return None

# ---- Initialize client (raises if it cannot authenticate) ----
def init_client() -> object:
    """
    Initialize and return a live Coinbase client instance.
    This will raise an exception if initialization/auth fails.
    """
    pem_path = _ensure_pem()

    # prefer constructor signatures commonly used:
    # coinbase_advanced_py: CoinbaseClient(api_key=..., api_secret_path=..., api_passphrase=...)
    # coinbase_advancedtrade_python: Client(api_key=..., api_secret=..., passphrase=...)
    excs = []
    if _client_ctor == "coinbase_advanced_py":
        try:
            # try the path-based auth
            client = CLIENT_CLASS(
                api_key=API_KEY,
                api_secret_path=pem_path,
                api_passphrase=API_PASSPHRASE,
            )
            logger.info("[NIJA] Initialized client via coinbase_advanced_py signature.")
            return client
        except Exception as e:
            excs.append(e)
            logger.debug("coinbase_advanced_py ctor attempt failed: %s", e)

        # fallback: maybe requires raw secret instead of path
        try:
            client = CLIENT_CLASS(
                api_key=API_KEY,
                api_secret=PEM_CONTENT,
                api_passphrase=API_PASSPHRASE,
            )
            logger.info("[NIJA] Initialized client via coinbase_advanced_py alt signature.")
            return client
        except Exception as e:
            excs.append(e)
            logger.debug("coinbase_advanced_py alt ctor failed: %s", e)

    elif _client_ctor == "coinbase_advancedtrade_python":
        try:
            client = CLIENT_CLASS(
                api_key=API_KEY,
                api_secret=PEM_CONTENT or os.getenv("COINBASE_API_SECRET"),
                passphrase=API_PASSPHRASE,
            )
            logger.info("[NIJA] Initialized client via coinbase_advancedtrade_python signature.")
            return client
        except Exception as e:
            excs.append(e)
            logger.debug("coinbase_advancedtrade_python ctor failed: %s", e)

        # another fallback signature (api_secret_path)
        try:
            client = CLIENT_CLASS(
                api_key=API_KEY,
                api_secret_path=pem_path,
                passphrase=API_PASSPHRASE,
            )
            logger.info("[NIJA] Initialized client via coinbase_advancedtrade_python alt.")
            return client
        except Exception as e:
            excs.append(e)
            logger.debug("coinbase_advancedtrade_python alt ctor failed: %s", e)

    # If we get here, none of the constructor attempts worked — raise with collected info.
    raise RuntimeError(
        "Failed to initialize Coinbase client. Tried constructors for "
        f"{_import_source}. Errors: {excs}"
    )

# Create module-level client (so other modules can `from nija_client import client`)
client = None
try:
    client = init_client()
except Exception as e:
    # Do not swallow — re-raise so calling processes fail loudly (no DummyClient)
    logger.exception("[NIJA] Live client initialization failed.")
    raise

# ---- Helper: get USD balance ----
def get_usd_balance(c=None) -> Decimal:
    """
    Try several common client methods to return the available USD amount as Decimal.
    Will raise if client lacks expected methods.
    """
    from decimal import Decimal as D

    c = c or client
    if c is None:
        raise RuntimeError("Client is not initialized.")

    # Attempt #1: spot balances dict (common)
    try:
        if hasattr(c, "get_spot_account_balances"):
            balances = c.get_spot_account_balances()
            # expect dict like {"USD": {"available": "12.34", ...}, ...}
            usd = balances.get("USD") or balances.get("USDC") or {}
            avail = usd.get("available") if isinstance(usd, dict) else None
            if avail is not None:
                return D(str(avail))
    except Exception:
        logger.debug("get_spot_account_balances() failed", exc_info=True)

    # Attempt #2: generic accounts listing
    try:
        if hasattr(c, "get_accounts"):
            accounts = c.get_accounts()
            # accounts likely an iterable of dicts with currency/available
            for a in accounts:
                code = a.get("currency") or a.get("asset") or a.get("currency_code")
                if str(code).upper() in ("USD", "USDC"):
                    avail = a.get("available") or a.get("balance") or a.get("available_balance")
                    if avail is not None:
                        return D(str(avail))
    except Exception:
        logger.debug("get_accounts() attempt failed", exc_info=True)

    # Attempt #3: single-account method names
    try:
        for name in ("get_usd_balance", "get_account_balance", "get_balance"):
            if hasattr(c, name):
                val = getattr(c, name)()
                return D(str(val))
    except Exception:
        logger.debug("alternative balance methods failed", exc_info=True)

    # If none worked, raise so preflight fails (we want live and explicit failures)
    raise RuntimeError("Could not determine USD balance from Coinbase client instance.")
