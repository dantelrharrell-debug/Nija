# nija_client.py (robust instantiation, auto-adapts to SDK differences)
import os
import sys
import logging
import importlib
import inspect
import time
import shutil

# --- Logging ---
log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=getattr(logging, log_level, logging.INFO))
logger = logging.getLogger("nija_client")

# --- Ensure venv site-packages first if applicable (adjust path to your environment) ---
VENV_SITE_PACKAGES = '/opt/render/project/src/.venv/lib/python3.13/site-packages'
if VENV_SITE_PACKAGES not in sys.path:
    sys.path.insert(0, VENV_SITE_PACKAGES)

# --- Dummy fallback so import never crashes ---
class DummyClient:
    def get_accounts(self):
        logger.warning("[DummyClient] get_accounts called - no live trading!")
        return []

    def place_order(self, *args, **kwargs):
        logger.warning("[DummyClient] place_order called - no live trading!")
        return {"status": "dummy"}

# --- Helper: move local shadow folders to avoid shadowing installed package (safe) ---
def backup_and_move_shadow(name):
    project_root = os.path.abspath(os.path.dirname(__file__) or ".")
    local_path = os.path.join(project_root, name)
    if os.path.exists(local_path):
        ts = time.strftime("%Y%m%dT%H%M%S")
        backup_dir = os.path.join(project_root, "local_shadow_backups", f"{ts}_{name}")
        os.makedirs(os.path.dirname(backup_dir), exist_ok=True)
        try:
            shutil.move(local_path, backup_dir)
            logger.warning("[NIJA] Moved local shadow folder %s -> %s", local_path, backup_dir)
            return True
        except Exception as e:
            logger.exception("[NIJA] Failed to move shadow folder %s: %s", local_path, e)
    return False

for candidate in ("coinbase_advanced_py", "coinbase-advanced-py", "coinbase_advanced-py"):
    backup_and_move_shadow(candidate)

# --- Candidate import paths (ordered) ---
candidate_modules = [
    "coinbase.rest",                 # possible new layout
    "coinbase_advanced_py.client",   # old expectation
    "coinbase_advanced_py.clients",
    "coinbase_advanced_py.api.client",
    "coinbase_advanced_py",
    "coinbase",
    "coinbase.client",
    "coinbase_advanced_py.client_api",
    "coinbase_advanced_py._client",
]

def find_client_class():
    for mod_name in candidate_modules:
        try:
            logger.info("[NIJA] Trying import: %s", mod_name)
            mod = importlib.import_module(mod_name)
            # common names to check
            for attr in ("RESTClient", "CoinbaseClient", "REST", "Client", "REST"):
                if hasattr(mod, attr):
                    cls = getattr(mod, attr)
                    if inspect.isclass(cls):
                        logger.info("[NIJA] Found %s in %s", attr, mod_name)
                        return cls
            # fallback: scan module attributes
            for name, val in vars(mod).items():
                if inspect.isclass(val) and ("Coinbase" in name or "REST" in name or name.lower().startswith("rest")):
                    logger.info("[NIJA] Found candidate class %s in %s", name, mod_name)
                    return val
        except ModuleNotFoundError:
            logger.debug("[NIJA] Module not found: %s", mod_name)
        except Exception as e:
            logger.debug("[NIJA] Error importing %s: %s", mod_name, e)
    logger.info("[NIJA] No Coinbase client class found in known locations.")
    return None

ClientClass = find_client_class()

# --- Prepare possible constructor kwargs from environment ---
# Preferred secure pattern: provide PEM contents via COINBASE_PEM_CONTENT (Render env var)
COINBASE_API_KEY = os.environ.get("COINBASE_API_KEY")
COINBASE_API_SECRET = os.environ.get("COINBASE_API_SECRET")           # if used
COINBASE_API_SECRET_PATH = os.environ.get("COINBASE_API_SECRET_PATH") # optional secret path
COINBASE_PEM_PATH = os.environ.get("COINBASE_PEM_PATH", "/opt/render/project/secrets/coinbase.pem")
COINBASE_PEM_CONTENT = os.environ.get("COINBASE_PEM_CONTENT")        # recommended on Render
COINBASE_PASSPHRASE = os.environ.get("COINBASE_PASSPHRASE")
SANDBOX = os.environ.get("SANDBOX", "").lower() in ("1", "true", "yes")

# If PEM content provided, ensure file exists (write if needed) - ONLY if running in container
if COINBASE_PEM_CONTENT:
    try:
        os.makedirs(os.path.dirname(COINBASE_PEM_PATH), exist_ok=True)
        with open(COINBASE_PEM_PATH, "w", encoding="utf-8") as fh:
            fh.write(COINBASE_PEM_CONTENT)
        os.chmod(COINBASE_PEM_PATH, 0o600)
        logger.info("[NIJA] Wrote COINBASE_PEM_CONTENT to %s", COINBASE_PEM_PATH)
    except Exception as e:
        logger.exception("[NIJA] Failed to write PEM from env: %s", e)

# If PEM path required, assert existence for logging but don't crash here
if COINBASE_PEM_PATH and not os.path.exists(COINBASE_PEM_PATH):
    logger.info("[NIJA] PEM file not found at configured path: %s (may be fine if not required)", COINBASE_PEM_PATH)

# Build a candidate kwargs dict (we'll filter it by constructor signature)
candidate_kwargs = {
    "api_key": COINBASE_API_KEY,
    "api_secret": COINBASE_API_SECRET,
    "secret": COINBASE_API_SECRET,            # alternate naming
    "secret_path": COINBASE_API_SECRET_PATH,
    "secret_file": COINBASE_API_SECRET_PATH,
    "pem_file_path": COINBASE_PEM_PATH,
    "pem_path": COINBASE_PEM_PATH,
    "pem_file": COINBASE_PEM_PATH,
    "pem": COINBASE_PEM_PATH,
    "pem_file_contents": COINBASE_PEM_CONTENT,
    "pem_contents": COINBASE_PEM_CONTENT,
    "passphrase": COINBASE_PASSPHRASE,
    "passphrase_path": COINBASE_PASSPHRASE,
    "key": COINBASE_API_KEY,                  # alternate name
    "secret_key": COINBASE_API_SECRET,
    "sandbox": SANDBOX,
    "sandbox_mode": SANDBOX,
}

# Remove Nones
candidate_kwargs = {k: v for k, v in candidate_kwargs.items() if v is not None}

def instantiate_client(cls, kwargs):
    """Instantiate cls using only supported constructor args to avoid TypeErrors."""
    try:
        sig = inspect.signature(cls)
        supported = {}
        for name, param in sig.parameters.items():
            # skip varargs/kwargs; we'll allow **kwargs only if present
            if name in kwargs:
                supported[name] = kwargs[name]
        # If constructor accepts **kwargs, pass the whole candidate set
        accepts_varkw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
        if accepts_varkw:
            inst = cls(**kwargs)
        else:
            inst = cls(**supported)
        logger.info("[NIJA] Successfully instantiated %s with args: %s", cls.__name__, list(supported.keys()))
        return inst
    except TypeError as e:
        # Constructor mismatch — return None so fallback can happen
        logger.warning("[NIJA] Failed to instantiate %s with filtered args: %s", cls.__name__, e)
        return None
    except Exception as e:
        logger.exception("[NIJA] Exception while instantiating %s: %s", cls.__name__, e)
        return None

# --- Try to create a live client safely ---
client = None
if ClientClass:
    client = instantiate_client(ClientClass, candidate_kwargs)
    # If instantiate returned None, try a few common manual param sets (backwards compatibility)
    if client is None:
        tried_sets = [
            {"api_key": COINBASE_API_KEY, "pem_file_path": COINBASE_PEM_PATH},
            {"key": COINBASE_API_KEY, "secret_path": COINBASE_API_SECRET_PATH},
            {"api_key": COINBASE_API_KEY, "api_secret": COINBASE_API_SECRET},
            {"key": COINBASE_API_KEY, "secret": COINBASE_API_SECRET},
            {"api_key": COINBASE_API_KEY},  # fallback
        ]
        for s in tried_sets:
            s = {k: v for k, v in s.items() if v is not None}
            if not s:
                continue
            inst = instantiate_client(ClientClass, s)
            if inst:
                client = inst
                break

if client is None:
    # fallback to DummyClient
    client = DummyClient()
    logger.info("[NIJA] Falling back to DummyClient (live Coinbase client not available or failed to init)")

logger.info("[NIJA] Using client: %s", type(client).__name__)
logger.info("[NIJA] SANDBOX=%s", SANDBOX)

# --- Exports ---
def get_accounts():
    try:
        return client.get_accounts()
    except Exception as e:
        logger.exception("[NIJA] get_accounts failed: %s", e)
        return []

def place_order(*args, **kwargs):
    try:
        return client.place_order(*args, **kwargs)
    except Exception as e:
        logger.exception("[NIJA] place_order failed: %s", e)
        return {"status": "error", "error": str(e)}

def check_live_status():
    if isinstance(client, DummyClient):
        logger.warning("[NIJA] Trading not live (DummyClient active)")
        print("❌ NIJA is NOT live — using DummyClient")
        return False
    try:
        accounts = client.get_accounts()
        if accounts:
            logger.info("[NIJA] ✅ Live trading ready")
            print("✅ NIJA is live! Ready to trade.")
            return True
        else:
            logger.warning("[NIJA] No accounts returned by Coinbase client")
            print("❌ NIJA cannot access accounts")
            return False
    except Exception as e:
        logger.exception("[NIJA] Exception checking live status: %s", e)
        print(f"❌ NIJA live check failed: {e}")
        return False

# --- Startup live check (safe, won't raise) ---
def startup_live_check():
    logger.info("[NIJA] Performing startup live check...")
    try:
        ok = check_live_status()
        if ok:
            logger.info("[NIJA] ✅ Nija trading is LIVE!")
        else:
            logger.warning("[NIJA] ❌ Nija trading is NOT live — using DummyClient")
    except Exception:
        logger.exception("[NIJA] Startup live check failed")

startup_live_check()

# Run direct check if executed
if __name__ == "__main__":
    check_live_status()
