# nija_client.py
import os
import logging
import traceback

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("nija-client")

def test_coinbase_connection():
    """
    Non-destructive test function: tries to import and instantiate Client and list accounts.
    Returns a dict summary (safe to print).
    """
    summary = {
        "import_ok": False,
        "env": {"COINBASE_API_KEY": False, "COINBASE_API_SECRET": False},
        "client_ok": False,
        "accounts": None,
        "errors": []
    }

    # check env presence (do NOT expose values)
    if os.environ.get("COINBASE_API_KEY"):
        summary["env"]["COINBASE_API_KEY"] = True
    if os.environ.get("COINBASE_API_SECRET"):
        summary["env"]["COINBASE_API_SECRET"] = True

    # Try to import client package
    try:
        from coinbase_advanced.client import Client  # type: ignore
        summary["import_ok"] = True
    except Exception as e:
        err = f"import_error: {type(e).__name__}: {e}"
        summary["errors"].append(err)
        logger.exception("coinbase_advanced import failed")
        return summary

    # require both envs to attempt init
    api_key = os.environ.get("COINBASE_API_KEY")
    api_secret = os.environ.get("COINBASE_API_SECRET")
    if not api_key or not api_secret:
        summary["errors"].append("missing_api_key_or_secret")
        return summary

    # normalize literal \n sequences in secrets if needed
    if "\\n" in api_secret:
        api_secret = api_secret.replace("\\n", "\n")

    # instantiate client
    try:
        client = Client(api_key=api_key, api_secret=api_secret)
        summary["client_ok"] = True
    except Exception as e:
        err = f"client_init_error: {type(e).__name__}: {e}"
        summary["errors"].append(err)
        logger.exception("Client instantiation failed")
        return summary

    # try listing accounts (redacted)
    try:
        accounts = client.get_accounts()
        safe_accounts = []
        if isinstance(accounts, (list, tuple)):
            for a in accounts:
                try:
                    if isinstance(a, dict):
                        cur = a.get("currency") or a.get("asset") or a.get("type")
                        bal = a.get("balance") or a.get("available") or a.get("amount")
                    else:
                        cur = getattr(a, "currency", None) or getattr(a, "asset", None) or getattr(a, "type", None)
                        bal = getattr(a, "balance", None) or getattr(a, "available", None)
                except Exception:
                    cur = str(a)[:40]
                    bal = None
                safe_accounts.append({"currency": cur, "balance": str(bal)})
        else:
            safe_accounts = str(accounts)[:800]
        summary["accounts"] = safe_accounts
    except Exception as e:
        err = f"accounts_error: {type(e).__name__}: {e}"
        summary["errors"].append(err)
        logger.exception("Failed to list accounts")

    return summary
