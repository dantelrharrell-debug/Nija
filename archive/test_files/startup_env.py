# startup_env.py
import os
import sys
import tempfile
import stat
from loguru import logger

# Names your code likely expects — adjust if your code uses different names.
REQUIRED_KEYS = [
    "COINBASE_API_KEY",
    "COINBASE_API_SECRET",
    # If your client uses a passphrase (REST key)
    "COINBASE_PASSPHRASE",
    # If you're using Coinbase "advanced" with an org id:
    "COINBASE_ORG_ID",
    # PEM content (optional, used by some Coinbase client setups)
    "COINBASE_PEM_CONTENT",
    # Controls whether startup should abort when creds are missing
    "LIVE_TRADING",
]

def _env_is_set(key: str) -> bool:
    v = os.getenv(key)
    return bool(v and v.strip())

def write_pem_to_file(pem_content: str):
    # Write PEM to a secure temp file and return path
    fd, path = tempfile.mkstemp(prefix="coinbase_", suffix=".pem")
    with os.fdopen(fd, "w") as f:
        f.write(pem_content)
    # Restrict permissions
    os.chmod(path, 0o600)
    logger.info("Wrote COINBASE_PEM_CONTENT to %s (mode 600)", path)
    return path

def init_startup_env():
    """
    Call this once at startup BEFORE creating the Coinbase client.
    Returns: dict with keys:
      - dry_run: bool
      - missing: list of missing required non-secret keys
      - pem_path: path or None
      - client_config: dict you can pass to your client initializer
    May call sys.exit(1) if LIVE_TRADING=1 and required credentials are missing.
    """
    # Determine which keys are present
    present = {k: _env_is_set(k) for k in REQUIRED_KEYS}
    # List only the credentials we care about (don't list LIVE_TRADING as missing if absent; default handled)
    cred_keys = ["COINBASE_API_KEY", "COINBASE_API_SECRET", "COINBASE_ORG_ID"]
    missing = [k for k in cred_keys if not present.get(k, False)]

    live_trading = os.getenv("LIVE_TRADING", "0").strip() == "1"
    dry_run = not live_trading

    if missing:
        logger.error("Missing Coinbase credential keys: %s", missing)
        if dry_run:
            logger.warning("LIVE_TRADING != 1 (or unset). Continuing in dry-run mode.")
        else:
            logger.critical("LIVE_TRADING=1 and required Coinbase credentials missing. Aborting startup.")
            # Use non-zero exit to ensure host marks failure
            sys.exit(1)
    else:
        logger.info("All required Coinbase credential keys present.")

    # Handle PEM content (optional)
    pem_path = None
    if _env_is_set("COINBASE_PEM_CONTENT"):
        pem_content = os.getenv("COINBASE_PEM_CONTENT")
        # If PEM content contains literal '\n' sequences, convert them to real newlines
        if "\\n" in pem_content and "-----BEGIN" not in pem_content:
            # handle cases where env var has escaped newlines
            pem_content = pem_content.replace("\\n", "\n")
        try:
            pem_path = write_pem_to_file(pem_content)
        except Exception as e:
            logger.error("Failed to write PEM content to file: %s", e)
            if not dry_run:
                sys.exit(1)

    # Build client_config: the keys your client constructor will need
    client_config = {}
    if _env_is_set("COINBASE_API_KEY"):
        client_config["api_key"] = os.getenv("COINBASE_API_KEY").strip()
    if _env_is_set("COINBASE_API_SECRET"):
        client_config["api_secret"] = os.getenv("COINBASE_API_SECRET").strip()
    if _env_is_set("COINBASE_PASSPHRASE"):
        client_config["passphrase"] = os.getenv("COINBASE_PASSPHRASE").strip()
    if _env_is_set("COINBASE_ORG_ID"):
        client_config["org_id"] = os.getenv("COINBASE_ORG_ID").strip()
    if pem_path:
        client_config["pem_path"] = pem_path

    # Add a safe flag so your main app knows if it's dry-run
    result = {
        "dry_run": dry_run,
        "missing": missing,
        "pem_path": pem_path,
        "client_config": client_config,
    }

    return result

# If run directly for a quick check, print status (non-secret)
if __name__ == "__main__":
    s = init_startup_env()
    print("dry_run:", s["dry_run"])
    print("missing:", s["missing"])
    print("pem_path:", bool(s["pem_path"]))
    print("client_config_keys:", list(s["client_config"].keys()))
