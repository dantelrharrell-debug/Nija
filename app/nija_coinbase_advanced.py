# /app/nija_coinbase_advanced.py
import os
import time
import requests
from loguru import logger
import jwt as pyjwt

logger = logger.bind(name="nija_coinbase_advanced")

BASE_URL = os.getenv("COINBASE_API_BASE", "https://api.cdp.coinbase.com").rstrip("/")
PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT")
ISS = os.getenv("COINBASE_ISS")
JWT_EXP_SECONDS = 120

def _build_jwt():
    if not PEM_CONTENT:
        raise RuntimeError("COINBASE_PEM_CONTENT not set")
    now = int(time.time())
    payload = {
        "iat": now,
        "exp": now + JWT_EXP_SECONDS,
        "iss": ISS,
    }
    headers = {"alg": "ES256"}
    token = pyjwt.encode(payload, PEM_CONTENT, algorithm="ES256", headers=headers)
    if isinstance(token, bytes):
        token = token.decode()
    return token

def _bearer_headers():
    return {
        "Authorization": f"Bearer {_build_jwt()}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

def get_accounts():
    url = BASE_URL + "/platform/v2/evm/accounts"
    resp = requests.get(url, headers=_bearer_headers(), timeout=10)
    resp.raise_for_status()
    return resp.json()

def get_key_permissions():
    url = BASE_URL + "/platform/v2/evm/key_permissions"
    resp = requests.get(url, headers=_bearer_headers(), timeout=10)
    resp.raise_for_status()
    return resp
