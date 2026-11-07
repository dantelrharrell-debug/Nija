"""NIJA revenue command center: fail-closed, read-only owner access."""
import hmac
import os
from flask import Flask, Response, request, send_from_directory

app = Flask(__name__)
OWNERS = {
    "dante.harrell@nijaaitrading.com": "NIJA_OWNER_BUSINESS_PASSWORD",
    "dantelrharrell@gmail.com": "NIJA_OWNER_PERSONAL_PASSWORD",
}

@app.after_request
def headers(response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
    return response

@app.get("/healthz")
def health():
    return ("ready", 200) if all(len(os.environ.get(k, "")) >= 20 for k in OWNERS.values()) else ("unconfigured", 503)

@app.get("/")
def dashboard():
    if not all(len(os.environ.get(k, "")) >= 20 for k in OWNERS.values()):
        return Response("Owner authentication not configured", status=503)
    auth = request.authorization
    if not auth or auth.type.lower() != "basic":
        return Response("Owner login required", status=401, headers={"WWW-Authenticate": 'Basic realm="NIJA Revenue Owner"'})
    secret_key = OWNERS.get(auth.username.lower())
    expected = os.environ.get(secret_key, "") if secret_key else ""
    if not expected or not hmac.compare_digest(auth.password or "", expected):
        return Response("Unauthorized", status=401, headers={"WWW-Authenticate": 'Basic realm="NIJA Revenue Owner"'})
    return send_from_directory(os.path.dirname(__file__), "index.html")
