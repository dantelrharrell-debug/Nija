# put this inside nija_client.py (replace existing init_client)
import importlib
from decimal import Decimal

_client_candidates = []
_import_attempts = []

def _discover_clients():
    tries = [
        ("coinbase.rest.RESTClient", "from coinbase.rest import RESTClient"),
        ("coinbase.rest_client.RESTClient", "from coinbase.rest_client import RESTClient"),
        ("coinbase_advanced_py.client.RESTClient", "from coinbase_advanced_py.client import RESTClient"),
        ("coinbase_advanced_py.RESTClient", "from coinbase_advanced_py import RESTClient"),
        ("coinbase.RESTClient", "from coinbase import RESTClient"),
    ]
    for _, hint in tries:
        try:
            parts = hint.replace("from ", "").split(" import ")
            mod_name, cls_name = parts[0].strip(), parts[1].strip()
            mod = importlib.import_module(mod_name)
            cls = getattr(mod, cls_name)
            _client_candidates.append((f"{mod_name}.{cls_name}", cls))
            _import_attempts.append((hint, "ok"))
            logger.info(f"[NIJA] Import succeeded: {hint}")
        except Exception as e:
            _import_attempts.append((hint, f"failed: {e}"))
            logger.debug(f"[NIJA-DEBUG] Import attempt {hint} failed: {e}")

_discover_clients()

def _instantiate_and_test(client_cls, *args, **kwargs):
    try:
        inst = client_cls(*args, **kwargs)
    except Exception as e:
        logger.debug(f"[NIJA-DEBUG] Instantiation failed for {client_cls} args={args} kwargs={kwargs}: {e}")
        return None
    try:
        # try common balance methods
        if hasattr(inst, "get_spot_account_balances"):
            _ = inst.get_spot_account_balances()
        elif hasattr(inst, "get_accounts"):
            _ = inst.get_accounts()
        else:
            logger.debug(f"[NIJA-DEBUG] No balance method on {client_cls}, accepted instance.")
        return inst
    except Exception as e:
        logger.debug(f"[NIJA-DEBUG] Test call failed for {client_cls}: {e}")
        return None

def init_client():
    logger.info(f"[NIJA] API_KEY present: {'yes' if API_KEY else 'no'}")
    logger.info(f"[NIJA] API_SECRET present: {'yes' if API_SECRET else 'no'}")
    logger.info(f"[NIJA] API_PASSPHRASE present: {'yes' if API_PASSPHRASE else 'no'}")

    if not (API_KEY and API_SECRET):
        logger.warning("[NIJA] Missing API key/secret — using DummyClient")
        return DummyClient()

    for name, cls in _client_candidates:
        logger.info(f"[NIJA] Trying candidate client: {name}")
        # positional
        inst = _instantiate_and_test(cls, API_KEY, API_SECRET)
        if inst:
            logger.info(f"[NIJA] Authenticated using {name} with positional args")
            return inst
        # keyword
        try:
            inst = _instantiate_and_test(cls, api_key=API_KEY, api_secret=API_SECRET)
            if inst:
                logger.info(f"[NIJA] Authenticated using {name} with keyword api_key/api_secret")
                return inst
        except Exception:
            pass
        # passphrase forms
        if API_PASSPHRASE:
            inst = _instantiate_and_test(cls, API_KEY, API_SECRET, API_PASSPHRASE)
            if inst:
                logger.info(f"[NIJA] Authenticated using {name} with positional passphrase")
                return inst
            try:
                inst = _instantiate_and_test(cls, api_key=API_KEY, api_secret=API_SECRET, api_passphrase=API_PASSPHRASE)
                if inst:
                    logger.info(f"[NIJA] Authenticated using {name} with keyword passphrase")
                    return inst
            except Exception:
                pass

    logger.warning("[NIJA] No working Coinbase client found. Falling back to DummyClient.")
    for attempt, result in _import_attempts:
        logger.debug(f"[NIJA-DEBUG] Import attempt: {attempt} -> {result}")
    return DummyClient()
