#!/usr/bin/env python3
"""
Robust Coinbase client loader for Nija trading bot.

- Detects vendor.coinbase_advanced_py.client and other possible names.
- Attempts to instantiate the client using the environment variables that
  you already have:
    COINBASE_API_KEY
    COINBASE_API_SECRET
    COINBASE_JWT_ISSUER
    COINBASE_JWT_KID
    COINBASE_PEM_CONTENT

- If the detected client class expects different parameter names, this code
  tries to match environment variables to the constructor signature.
- If LIVE_TRADING != "1", runs in simulation mode (coinbase_client = None).
"""

import os
import logging
import inspect
import time

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=LOG_LEVEL, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("nija_client")

# Environment variables we expect
ENV = {
    "api_key": os.environ.get("COINBASE_API_KEY"),
    "api_secret": os.environ.get("COINBASE_API_SECRET"),
    "api_sub": os.environ.get("COINBASE_API_SUB"),
    "jwt_issuer": os.environ.get("COINBASE_JWT_ISSUER"),
    "jwt_kid": os.environ.get("COINBASE_JWT_KID"),
    "pem_content": os.environ.get("COINBASE_PEM_CONTENT"),
    "live_trading": os.environ.get("LIVE_TRADING", "0"),
}

LIVE_TRADING = ENV["live_trading"] == "1"

# Try imports in order of likelihood
IMPORT_CANDIDATES = [
    "vendor.coinbase_advanced_py.client",  # your local vendor
    "coinbase_advanced_py.client",         # pip package name some versions
    "coinbase_advanced.client",
    "coinbase_advanced.client",
    "coinbase_advanced_py",                # fallback
    "coinbase_advanced",
]

DetectedClientClass = None
DetectedModuleName = None

for cand in IMPORT_CANDIDATES:
    try:
        parts = cand.rsplit(".", 1)
        mod_name = parts[0] if len(parts) == 2 else cand
        attr = parts[1] if len(parts) == 2 else None
        mod = __import__(mod_name, fromlist=[attr] if attr else [])
        if attr:
            maybe = getattr(mod, attr, None)
            # candidate is module: try to find a class inside it
            if maybe:
                # maybe is a module object (if attr points to module name)
                # we still expect a Client/CoinbaseClient class inside
                mod_obj = maybe
            else:
                mod_obj = mod
        else:
            mod_obj = mod

        # search for likely class names
        for cls_name in ("CoinbaseClient", "Client", "Coinbase", "CoinbaseAPI"):
            cls = getattr(mod_obj, cls_name, None)
            if inspect.isclass(cls):
                DetectedClientClass = cls
                DetectedModuleName = cand
                break
        if DetectedClientClass:
            break
    except Exception:
        continue

if DetectedClientClass:
    logger.info("Detected Coinbase client class '%s' in module '%s'.",
                DetectedClientClass.__name__, DetectedModuleName)
else:
    logger.error("coinbase_advanced client class not found in candidates: %s", IMPORT_CANDIDATES)


def _match_signature_and_build_kwargs(cls):
    """
    Inspect constructor signature and produce kwargs from ENV as best we can.
    Returns dict of kwargs appropriate for constructor (may be empty).
    """
    try:
        sig = inspect.signature(cls.__init__)
        params = list(sig.parameters.values())[1:]  # drop 'self'
        accepted = [p.name for p in params]
    except Exception:
        accepted = []

    # possible env->param mapping guesses
    mapping_candidates = {
        "api_key": ["api_key", "key", "apiKey", "apikey"],
        "api_secret": ["api_secret", "secret", "apiSecret", "apisecret"],
        "api_sub": ["api_sub", "sub", "api_sub_id"],
        "jwt_issuer": ["jwt_issuer", "issuer", "jwtIssuer", "organization", "org"],
        "jwt_kid": ["jwt_kid", "kid", "jwtKid"],
        "pem_content": ["pem_content", "pem", "pem_content_str", "key_pem", "private_key"],
    }

    kwargs = {}
    for env_key, env_val in ENV.items():
        if env_val is None:
            continue
        # find a constructor arg name that matches one of mapping_candidates[env_key]
        candidates = mapping_candidates.get(env_key, [env_key])
        for cand in candidates:
            # match case-insensitively
            for accepted_name in accepted:
                if accepted_name.lower() == cand.lower():
                    kwargs[accepted_name] = env_val
                    break
            if any(a.lower() == cand.lower() for a in accepted):
                break

    # Extra fallback: if constructor accepts positional api_key, api_secret in that order
    if not kwargs and len(accepted) >= 2:
        # if the first two params look like key/secret names (heuristic)
        if any(x in accepted[0].lower() for x in ("api", "key")) and any(x in accepted[1].lower() for x in ("secret", "key")):
            # will instantiate with positional args later
            return {}

    return kwargs


def create_coinbase_client():
    if not DetectedClientClass:
        raise RuntimeError("Coinbase client class not available (vendor package missing).")

    # Build kwargs that match constructor
    kwargs = _match_signature_and_build_kwargs(DetectedClientClass)

    # If kwargs empty but env has key/secret, try positional construction
    try_positional = False
    if not kwargs:
        if ENV.get("api_key") and ENV.get("api_secret"):
            try_positional = True

    # Attempt instantiation
    try:
        if try_positional:
            logger.info("Attempting positional instantiation of Coinbase client.")
            client = DetectedClientClass(ENV.get("api_key"), ENV.get("api_secret"))
        else:
            logger.info("Attempting keyword instantiation of Coinbase client with keys: %s", list(kwargs.keys()))
            client = DetectedClientClass(**kwargs)
        logger.info("Coinbase client instantiated.")
        return client
    except TypeError as te:
        # last-ditch attempt: try common explicit param names
        logger.warning("Constructor TypeError: %s — trying alternate arg names", te)
        alt_kwargs = {}
        # common explicit mapping to try
        if ENV.get("api_key"):
            for alt in ("api_key", "key", "apiKey"):
                alt_kwargs[alt] = ENV["api_key"]
        if ENV.get("api_secret"):
            for alt in ("api_secret", "secret", "apiSecret"):
                alt_kwargs[alt] = ENV["api_secret"]
        if ENV.get("jwt_issuer"):
            for alt in ("jwt_issuer", "issuer", "organization"):
                alt_kwargs[alt] = ENV["jwt_issuer"]
        if ENV.get("jwt_kid"):
            for alt in ("jwt_kid", "kid"):
                alt_kwargs[alt] = ENV["jwt_kid"]
        if ENV.get("pem_content"):
            for alt in ("pem_content", "pem", "private_key", "key_pem"):
                alt_kwargs[alt] = ENV["pem_content"]

        # keep only keys that match constructor
        try:
            sig = inspect.signature(DetectedClientClass.__init__)
            accepted = [p.name for p in list(sig.parameters.values())[1:]]
        except Exception:
            accepted = []

        filtered = {k: v for k, v in alt_kwargs.items() if k in accepted}
        if filtered:
            try:
                client = DetectedClientClass(**filtered)
                logger.info("Coinbase client created with filtered alt kwargs: %s", list(filtered.keys()))
                return client
            except Exception as e:
                logger.exception("Alternate instantiation failed: %s", e)

        # final fail
        raise

    except Exception as e:
        logger.exception("Failed to instantiate Coinbase client: %s", e)
        raise


def test_coinbase_client(client) -> bool:
    """Try a light test call to confirm client works."""
    if client is None:
        return False
    try:
        # try known lightweight calls in decreasing confidence
        if hasattr(client, "ping"):
            client.ping()
            return True
        if hasattr(client, "get_system_status"):
            client.get_system_status()
            return True
        if hasattr(client, "list_products"):
            client.list_products(limit=1)
            return True
        if hasattr(client, "list_accounts"):
            client.list_accounts(limit=1)
            return True
        # if no test method, consider instantiation success enough
        return True
    except Exception as ex:
        logger.warning("Lightweight client test failed: %s", ex)
        return False


# Top-level: build coinbase_client or None
coinbase_client = None
simulation_mode = False

if LIVE_TRADING:
    try:
        coinbase_client = create_coinbase_client()
        if not test_coinbase_client(coinbase_client):
            logger.error("Coinbase client test failed; going to simulation mode.")
            coinbase_client = None
            simulation_mode = True
        else:
            logger.info("Coinbase client ready (LIVE TRADING).")
    except Exception as e:
        logger.error("Failed to create Coinbase client: %s", e)
        coinbase_client = None
        simulation_mode = True
else:
    logger.info("LIVE_TRADING not enabled; running in simulation mode.")
    simulation_mode = True


# Example trading loop entrypoint (keeps safe — no trades executed here).
def trading_loop():
    logger.info("Trading loop started. Simulation mode=%s", simulation_mode)
    # Example: poll every X seconds (you should replace this with your live loop)
    try:
        while True:
            # Example state/logging only
            if simulation_mode:
                logger.debug("Simulation tick — would poll market here.")
            else:
                # In live mode you would call client methods safely
                logger.debug("Live tick — client available: %s", bool(coinbase_client))
                # e.g. coinbase_client.list_accounts()  # uncomment only if safe
            time.sleep(5)
    except KeyboardInterrupt:
        logger.info("Trading loop interrupted (KeyboardInterrupt). Exiting.")
    except Exception:
        logger.exception("Unexpected error in trading loop. Exiting.")


if __name__ == "__main__":
    # If run directly, start the trading loop (non-blocking in start_all.sh we background it)
    trading_loop()
