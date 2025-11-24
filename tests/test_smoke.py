# tests/test_smoke.py
import os
import json
import hmac, hashlib
from web.wsgi import app

def sign(payload_bytes: bytes, secret: str):
    return hmac.new(secret.encode(), payload_bytes, hashlib.sha256).hexdigest()

def test_health():
    client = app.test_client()
    r = client.get("/health")
    assert r.status_code == 200
    assert r.data == b"OK"

def test_webhook_no_secret_allows_dev():
    client = app.test_client()
    payload = {"hello": "world"}
    r = client.post("/tv/webhook", json=payload)
    assert r.status_code == 200
    assert r.get_json().get("status") == "ok"

def test_webhook_with_secret_signature():
    # run this test only if TV_WEBHOOK_SECRET is set in env
    secret = os.getenv("TV_WEBHOOK_SECRET")
    if not secret:
        # skip if no secret configured in the test environment
        return
    client = app.test_client()
    payload_bytes = json.dumps({"a":1}).encode("utf-8")
    sig = sign(payload_bytes, secret)
    r = client.post("/tv/webhook", data=payload_bytes, headers={"Content-Type":"application/json", "X-TV-Signature": sig})
    assert r.status_code == 200
