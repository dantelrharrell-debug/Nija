# nija_client.py
import os
import logging
import traceback

# --- Setup logging ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_client")

# --- Helper: try import multiple possible locations for CoinbaseClient ---
CoinbaseClient = None
_import_path_used = None
_import_errors = []

candidates = [
    "coinbase_advanced_py.client",        # preferred / newest
    "coinbase_advanced_py",               # older layout might export from top-level
    "coinbase_advanced_py.client.client", # defensive
]

for path in candidates:
    try:
        module = __import__(path, fromlist=["CoinbaseClient"])
        CoinbaseClient = getattr(module, "CoinbaseClient", None)
        if CoinbaseClient:
            _import_path_used = path
            logger.info(f"[NIJA] coinbase import succeeded from '{path}'")
            break
        else:
            raise ImportError(f"module '{path}' has no attribute CoinbaseClient")
    except Exception as e:
        _import_errors.append((path, str(e)))
        # continue trying next candidate

if CoinbaseClient is None:
    logger.warning("[NIJA] coinbase_advanced_py.client import failed for all candidates. See errors below:")
    for p, err in _import_errors:
        logger.warning(f" - tried {p}: {err}")

# --- Read environment / secrets (log presence only, not values) ---
env = {
    "API_KEY": bool(os.getenv("COINBASE_API_KEY")),
    "API_SECRET": bool(os.getenv("COINBASE_API_SECRET")),
    "PASSPHRASE": bool(os.getenv("COINBASE_PASSPHRASE")),
    "PEM": bool(os.getenv("COINBASE_PEM")),
    "PEM_PATH": bool(os.getenv("COINBASE_PEM_PATH")),
    "LIVE_TRADING": os.getenv("LIVE_TRADING", "False"),
    "DRY_RUN": os.getenv("DRY_RUN", "True"),
}
logger.info(f"[NIJA] env presence: API_KEY={env['API_KEY']} API_SECRET={env['API_SECRET']} PASSPHRASE={env['PASSPHRASE']} PEM={env['PEM']} PEM_PATH={env['PEM_PATH']} LIVE_TRADING={env['LIVE_TRADING']} DRY_RUN={env['DRY_RUN']}")

# --- If PEM provided as env var, write to well-known path ---
pem_path = None
if os.getenv("COINBASE_PEM"):
    try:
        pem_text = os.getenv("COINBASE_PEM")
        pem_path = "/opt/render/project/secrets/coinbase.pem"
        os.makedirs(os.path.dirname(pem_path), exist_ok=True)
        with open(pem_path, "w") as f:
            f.write(pem_text)
        logger.info(f"[NIJA] Wrote COINBASE_PEM -> {pem_path}")
    except Exception as e:
        logger.error(f"[NIJA] Failed to write COINBASE_PEM to path: {e}")
        pem_path = None
elif os.getenv("COINBASE_PEM_PATH"):
    pem_path = os.getenv("COINBASE_PEM_PATH")
    logger.info(f"[NIJA] Using COINBASE_PEM_PATH -> {pem_path}")

# --- Try to initialize Coinbase client if module found and keys/PEM present ---
client = None
client_is_dummy = True

def _try_init_client_ctor(client_cls, kwargs):
    """Try both positional and keyword constructor patterns and return instance or raise."""
    try:
        # try keyword args first (most explicit)
        return client_cls(**kwargs)
    except Exception as kw_exc:
        # try positional fallback
        try:
            args = []
            if "api_key" in kwargs:
                args.append(kwargs["api_key"])
            if "api_secret" in kwargs:
                args.append(kwargs["api_secret"])
            if "passphrase" in kwargs:
                args.append(kwargs["passphrase"])
            if "pem_path" in kwargs:
                args.append(kwargs["pem_path"])
            return client_cls(*args)
        except Exception as pos_exc:
            # raise combined
            raise Exception(f"keyword-init-error: {kw_exc}; positional-init-error: {pos_exc}")

if CoinbaseClient:
    init_attempts = []
    # Build kwargs from env if present
    kwargs = {}
    if os.getenv("COINBASE_API_KEY"):
        kwargs["api_key"] = os.getenv("COINBASE_API_KEY")
    if os.getenv("COINBASE_API_SECRET"):
        kwargs["api_secret"] = os.getenv("COINBASE_API_SECRET")
    if os.getenv("COINBASE_PASSPHRASE"):
        kwargs["passphrase"] = os.getenv("COINBASE_PASSPHRASE")
    # add pem path if we have it
    if pem_path:
        kwargs["pem_path"] = pem_path
    if kwargs:
        try:
            client = _try_init_client_ctor(CoinbaseClient, kwargs)
            client_is_dummy = False
            logger.info("[NIJA] CoinbaseClient initialized successfully using provided credentials/PEM. Live trading enabled.")
        except Exception as e:
            logger.error("[NIJA] CoinbaseClient initialization failed with provided credentials/PEM:")
            logger.error(traceback.format_exc())
            client = None
            client_is_dummy = True
    else:
        logger.warning("[NIJA] CoinbaseClient module available but no credentials/PEM found in environment. Not initializing real client.")
else:
    logger.warning("[NIJA] CoinbaseClient module not available; will use DummyClient.")

# --- Fallback DummyClient for safety/testing ---
class DummyClient:
    def place_order(self, **kwargs):
        logger.info(f"[DummyClient] Simulated order: {kwargs}")
        return {"simulated": True, **kwargs}
    def fetch_account(self):
        logger.info("[DummyClient] fetch_account simulated")
        return {"simulated_balance": True}
    def __repr__(self):
        return "<DummyClient simulated>"

# final
if client is None:
    client = DummyClient()
    client_is_dummy = True

# expose for importers
__all__ = ["client", "client_is_dummy", "CoinbaseClient", "pem_path"]
