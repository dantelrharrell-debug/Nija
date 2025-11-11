#!/usr/bin/env python3
"""
start_bot.py - robust startup wrapper for Nija trading bot.

Fixes logging formatting so deployment logs display real values (loguru uses `{}`).
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

def env(key, default=None):
    v = os.getenv(key, default)
    if v is not None:
        v = v.strip()
    return v

ADV_ENV_SET = bool(env("COINBASE_ISS")) or bool(env("COINBASE_PEM_CONTENT"))
HMAC_ENV_SET = bool(env("COINBASE_API_KEY")) and bool(env("COINBASE_API_SECRET"))

try:
    from nija_client import CoinbaseClient  # root shim should import app.nija_client
except Exception as e:
    logger.error("Failed to import CoinbaseClient from nija_client: {}", e)
    logger.error("Traceback:\n{}", traceback.format_exc())
    logger.error("Ensure you have app/nija_client.py (implementation) and a root shim nija_client.py that exposes CoinbaseClient.")
    sys.exit(1)

def try_instantiate(client_cls):
    """Attempt several reasonable constructor calls. Return (instance, used_kwargs) or (None, None)."""
    tried = []
    base = env("COINBASE_API_BASE") or env("COINBASE_ADVANCED_BASE") or env("COINBASE_BASE") or None
    candidates = [
        {},
        {"advanced": True},
        {"advanced": False},
        {"base": base} if base else {},
        {"advanced": True, "base": base} if base else {},
    ]

    seen = []
    final_candidates = []
    for c in candidates:
        key = tuple(sorted(c.items()))
        if key not in seen:
            seen.append(key)
            final_candidates.append(c)

    for kwargs in final_candidates:
        try:
            sig = None
            try:
                sig = inspect.signature(client_cls)
            except Exception:
                sig = None

            usable_kwargs = {}
            if kwargs and sig:
                params = sig.parameters
                accepts_kwargs = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values())
                for k, v in kwargs.items():
                    if k in params or accepts_kwargs:
                        usable_kwargs[k] = v
            else:
                usable_kwargs = kwargs

            tried.append(usable_kwargs)
            if usable_kwargs:
                logger.debug("Trying CoinbaseClient(...) with {}", usable_kwargs)
                inst = client_cls(**usable_kwargs)
            else:
                logger.debug("Trying CoinbaseClient() with no kwargs")
                inst = client_cls()
            logger.info("CoinbaseClient initialized. constructor kwargs used: {}", usable_kwargs)
            return inst, usable_kwargs
        except TypeError as te:
            logger.debug("Constructor TypeError with {}: {}", kwargs, te)
            continue
        except Exception as exc:
            logger.warning("Constructor attempt raised exception with {}: {}", kwargs, exc)
            logger.debug("Traceback:\n{}", traceback.format_exc())
            continue

    logger.error("All instantiation attempts failed. Tried: {}", tried)
    return None, None

def test_client_connection(client):
    """
    Try a few methods to test connectivity / keys and return (status, resp, succeeded_bool).
    """
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
                    logger.info("Attempting connection test via {}()", name)
                    result = func()
                    if isinstance(result, tuple) and len(result) >= 2:
                        status, resp = result[0], result[1]
                        return status, resp, True
                    return "ok", result, True
                except Exception as e:
                    logger.warning("{}() raised exception: {}", name, e)
                    logger.debug("Traceback:\n{}", traceback.format_exc())
                    continue

    if hasattr(client, "_request") and callable(getattr(client, "_request")):
        try:
            logger.info("Attempting low-level _request GET /accounts")
            res = client._request("GET", "/accounts")
            return getattr(res, "status_code", "unknown"), res, True
        except Exception as e:
            logger.warning("_request failed: {}", e)
            logger.debug("Traceback:\n{}", traceback.format_exc())

    return None, None, False

def main():
    logger.info("Starting Nija loader (robust).")

    client, used_kwargs = try_instantiate(CoinbaseClient)
    if client is None:
        logger.error("Failed to create CoinbaseClient instance. Aborting.")
        sys.exit(2)

    status, resp, ok = test_client_connection(client)
    if ok:
        logger.info("Connection test succeeded. status={}", status)
        try:
            if isinstance(resp, (str, bytes)):
                logger.info("Response (truncated): {}", str(resp)[:1000])
            else:
                logger.info("Response type: {} repr (truncated): {}", type(resp), repr(resp)[:1000])
        except Exception:
            logger.debug("Could not stringify response.")
        return

    logger.error("❌ Coinbase API keys invalid or unauthorized, or endpoints returned no data.")
    logger.info("ENV CHECK: ADV_ENV_SET={} HMAC_ENV_SET={}", ADV_ENV_SET, HMAC_ENV_SET)
    logger.info("Make sure the correct environment variables are set (Railway / Render 'Variables') and keys are properly formatted (PEM content must be the full block)")
    logger.info("For Advanced (JWT) mode, set COINBASE_ISS and COINBASE_PEM_CONTENT.")
    logger.info("For HMAC mode, set COINBASE_API_KEY and COINBASE_API_SECRET.")
    sys.exit(3)

if __name__ == "__main__":
    main()
