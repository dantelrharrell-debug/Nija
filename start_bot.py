#!/usr/bin/env python3
"""
start_bot.py

Robust startup wrapper for Nija trading bot.

- Automatically tries to instantiate the CoinbaseClient shim from nija_client in several ways
  (handles differing constructor signatures across versions).
- Detects Advanced (JWT) vs HMAC mode from environment variables.
- Attempts a connection test using available client methods (test_connection, get_accounts, fetch_accounts, etc).
- Prints/logs clear diagnostics for deployment logs (suitable for Render/Railway).
"""

import os
import sys
import time
import traceback
import inspect

# optional nice logging; falls back to print
try:
    from loguru import logger
except Exception:
    class _SimpleLogger:
        def info(self, *a, **k): print("[INFO]", *a)
        def warning(self, *a, **k): print("[WARN]", *a)
        def error(self, *a, **k): print("[ERR]", *a)
        def debug(self, *a, **k): print("[DBG]", *a)
    logger = _SimpleLogger()

# load .env locally if present (dev only)
if os.path.exists(".env"):
    try:
        from dotenv import load_dotenv
        load_dotenv(".env")
        logger.info(".env loaded for local dev")
    except Exception:
        logger.warning("python-dotenv not available; skipping .env")

# helper to read env convenience
def env(key, default=None):
    v = os.getenv(key, default)
    if v is not None:
        v = v.strip()
    return v

# Which envs imply advanced (JWT) mode?
ADV_ENV_SET = bool(env("COINBASE_ISS")) or bool(env("COINBASE_PEM_CONTENT"))
HMAC_ENV_SET = bool(env("COINBASE_API_KEY")) and bool(env("COINBASE_API_SECRET"))

# Try to import the client shim
try:
    from nija_client import CoinbaseClient  # root shim should import app.nija_client
except Exception as e:
    logger.error("Failed to import CoinbaseClient from nija_client: %s", e)
    logger.error("Traceback:\n%s", traceback.format_exc())
    # helpful message for deploy logs
    logger.error("Ensure you have app/nija_client.py (implementation) and a root shim nija_client.py that exposes CoinbaseClient.")
    sys.exit(1)

def try_instantiate(client_cls):
    """Attempt several reasonable constructor calls. Return (instance, used_kwargs) or (None, None)."""
    tried = []
    # candidate kwarg sets in order of preference
    base = env("COINBASE_API_BASE") or env("COINBASE_ADVANCED_BASE") or env("COINBASE_BASE") or None
    candidates = [
        {},  # plain
        {"advanced": True},
        {"advanced": False},
        {"base": base} if base else {},
        {"advanced": True, "base": base} if base else {},
    ]

    # dedupe while preserving order
    seen = []
    final_candidates = []
    for c in candidates:
        key = tuple(sorted(c.items()))
        if key not in seen:
            seen.append(key)
            final_candidates.append(c)

    for kwargs in final_candidates:
        # skip empty {} if nothing to try? still try {}
        try:
            # check signature to avoid TypeError if constructor doesn't accept kwargs
            sig = None
            try:
                sig = inspect.signature(client_cls)
            except Exception:
                sig = None

            usable_kwargs = {}
            if kwargs and sig:
                # only keep kwargs that appear in signature or accept **kwargs
                params = sig.parameters
                accepts_kwargs = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values())
                for k, v in kwargs.items():
                    if k in params or accepts_kwargs:
                        usable_kwargs[k] = v
            else:
                usable_kwargs = kwargs

            tried.append(usable_kwargs)
            if usable_kwargs:
                logger.debug("Trying CoinbaseClient(...) with %s", usable_kwargs)
                inst = client_cls(**usable_kwargs)
            else:
                logger.debug("Trying CoinbaseClient() with no kwargs")
                inst = client_cls()
            logger.info("CoinbaseClient initialized. constructor kwargs used: %s", usable_kwargs)
            return inst, usable_kwargs
        except TypeError as te:
            # constructor refused kwargs; keep trying others
            logger.debug("Constructor TypeError with %s: %s", kwargs, te)
            continue
        except Exception as exc:
            # some other error during construction — still log and try other options
            logger.warning("Constructor attempt raised exception with %s: %s", kwargs, exc)
            logger.debug("Traceback:\n%s", traceback.format_exc())
            continue

    logger.error("All instantiation attempts failed. Tried: %s", tried)
    return None, None

def test_client_connection(client):
    """
    Try a few methods to test connectivity / keys:
    - test_connection()
    - test_api() / ping() (common names)
    - get_accounts(), fetch_accounts(), fetch_advanced_accounts()
    - fallback: call client._raw or client.request if present (best-effort)
    Returns tuple(status_code_or_text, response_text_or_object, succeeded_bool)
    """
    # 1) test_connection
    candidates = [
        "test_connection",
        "test_api",
        "ping",
        "get_accounts",
        "fetch_accounts",
        "fetch_advanced_accounts",
        "get_accounts_raw",
        "get_accounts_response",
    ]

    for name in candidates:
        if hasattr(client, name):
            func = getattr(client, name)
            if callable(func):
                try:
                    logger.info("Attempting connection test via %s()", name)
                    result = func()
                    # many of your earlier logs show test_connection returns (status, resp)
                    if isinstance(result, tuple) and len(result) >= 2:
                        status, resp = result[0], result[1]
                        return status, resp, True
                    # if single value
                    return "ok", result, True
                except Exception as e:
                    logger.warning("%s() raised exception: %s", name, e)
                    logger.debug("Traceback:\n%s", traceback.format_exc())
                    # continue to next candidate

    # 2) try to access a generic request or low-level helper if available
    if hasattr(client, "_request") and callable(getattr(client, "_request")):
        try:
            logger.info("Attempting low-level _request GET /accounts")
            res = client._request("GET", "/accounts")
            return getattr(res, "status_code", "unknown"), res, True
        except Exception as e:
            logger.warning("_request failed: %s", e)
            logger.debug("Traceback:\n%s", traceback.format_exc())

    # 3) give up
    return None, None, False

def main():
    logger.info("Starting Nija loader (robust).")

    # instantiate
    client, used_kwargs = try_instantiate(CoinbaseClient)
    if client is None:
        logger.error("Failed to create CoinbaseClient instance. Aborting.")
        sys.exit(2)

    # run connection test
    status, resp, ok = test_client_connection(client)
    if ok:
        logger.info("Connection test succeeded. status=%s", status)
        # be careful about logging secrets; log response summary only
        try:
            if isinstance(resp, (str, bytes)):
                logger.info("Response (truncated): %s", str(resp)[:1000])
            else:
                # convert to small repr
                logger.info("Response type: %s repr (truncated): %s", type(resp), repr(resp)[:1000])
        except Exception:
            logger.debug("Could not stringify response.")
        # successful start — from here you can import/run the rest of your bot
        # e.g. from nija_bot import run_bot; run_bot(client)
        return

    # If we get here — connection tests failed
    logger.error("❌ Coinbase API keys invalid or unauthorized, or endpoints returned no data.")
    # Provide pointers that show up in deployment logs:
    logger.info("ENV CHECK: ADV_ENV_SET=%s HMAC_ENV_SET=%s", ADV_ENV_SET, HMAC_ENV_SET)
    logger.info("Make sure the correct environment variables are set (Railway / Render 'Variables') and keys are properly formatted (PEM content must be the full block)")
    logger.info("For Advanced (JWT) mode, set COINBASE_ISS and COINBASE_PEM_CONTENT.")
    logger.info("For HMAC mode, set COINBASE_API_KEY and COINBASE_API_SECRET.")
    sys.exit(3)

if __name__ == "__main__":
    main()
