import os
import time
import requests
import jwt  # PyJWT library
from datetime import datetime, timedelta

# --- Configuration: Replace these environment variables or set them in a .env file ---
API_KEY_ID = os.getenv("COINBASE_API_KEY_ID")        # e.g., "organizations/{org_id}/apiKeys/{key_id}"
API_KEY_SECRET = os.getenv("COINBASE_API_KEY_SECRET")  # The private key string: "-----BEGIN PRIVATE KEY-----\n…\n-----END PRIVATE KEY-----\n"
REQUEST_METHOD = "GET"
REQUEST_HOST = "api.cdp.coinbase.com"
REQUEST_PATH = "/platform/v1/wallets"  # Example path; change for the endpoint you want to call

# --- Generate the JWT ---
def generate_jwt():
    now_ts = int(time.time())
    exp_ts = now_ts + 120  # valid for 2 minutes
    # Build payload
    payload = {
        "iss": "cdp",
        "sub": API_KEY_ID,
        "nbf": now_ts,
        "iat": now_ts,
        "exp": exp_ts,
        "uri": f"{REQUEST_METHOD} {REQUEST_HOST}{REQUEST_PATH}"
    }
    # header
    headers = {
        "alg": "ES256",      # Or "EdDSA"/"Ed25519" depending on your key algorithm
        "typ": "JWT",
        "kid": API_KEY_ID
    }
    token = jwt.encode(payload, API_KEY_SECRET, algorithm="ES256", headers=headers)
    return token

# --- Make the authenticated request ---
def make_request(jwt_token):
    url = f"https://{REQUEST_HOST}{REQUEST_PATH}"
    headers = {
        "Authorization": f"Bearer {jwt_token}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    resp = requests.request(REQUEST_METHOD, url, headers=headers)
    return resp

# --- Main execution ---
if __name__ == "__main__":
    if not API_KEY_ID or not API_KEY_SECRET:
        print("ERROR: Set COINBASE_API_KEY_ID and COINBASE_API_KEY_SECRET environment variables.")
        exit(1)

    token = generate_jwt()
    print("Generated JWT:", token)
    response = make_request(token)
    print("Status code:", response.status_code)
    print("Response body:", response.text)
