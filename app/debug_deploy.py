#!/usr/bin/env python3
# debug_deploy.py
# Run this in your deployed container to verify which code & env are active.

import os, time, hashlib
import jwt, requests
from loguru import logger
logger.remove()
logger.add(lambda msg: print(msg, end=""))

def show_file_head(path, n=200):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = f.read()
        h = hashlib.sha256(data.encode("utf-8")).hexdigest()
        print(f"\n--- FILE: {path} ---")
        print(f"SHA256: {h}")
        print("HEAD (first %d chars):" % n)
        print(data[:n].replace("\n", "\\n"))
        print("--- END FILE HEAD ---\n")
    except Exception as e:
        print(f"Could not read {path}: {e}")

def safe_len(name, val):
    if val is None:
        return f"{name}=<MISSING>"
    return f"{name}=len({len(val)})"

def fix_pem(pem_raw):
    if pem_raw is None:
        return None
    pem = pem_raw.strip()
    pem = pem.replace("\\n", "\n")
    if not pem.startswith("-----BEGIN EC PRIVATE KEY-----"):
        pem = "-----BEGIN EC PRIVATE KEY-----\n" + pem
    if not pem.strip().endswith("-----END EC PRIVATE KEY-----"):
        pem = pem + "\n-----END EC PRIVATE KEY-----"
    return pem

def generate_jwt(pem, kid, org_id):
    if not pem or not kid or not org_id:
        print("Cannot generate JWT: missing pem/kid/org_id")
        return None
    now = int(time.time())
    payload = {"iat": now, "exp": now + 300, "sub": org_id}
    headers = {"kid": kid}
    try:
        token = jwt.encode(payload, pem, algorithm="ES256", headers=headers)
        return token
    except Exception as e:
        print("JWT generation exception:", repr(e))
        return None

def main():
    print("\n=== DEBUG DEPLOY START ===\n")

    # 1) Show which file is running
    candidate_paths = [
        "/app/app/nija_client.py",
        "/opt/render/project/src/app/nija_client.py",
        "/app/nija_client.py",
        "./app/nija_client.py"
    ]
    for p in candidate_paths:
        show_file_head(p, n=300)

    # 2) Print environment var presence & lengths (do NOT print secrets)
    env_names = ["COINBASE_ORG_ID", "COINBASE_PEM_CONTENT", "COINBASE_API_KEY"]
    print("--- Environment var lengths ---")
    for name in env_names:
        val = os.environ.get(name)
        print(safe_len(name, val))
    print("-------------------------------\n")

    # 3) Show first/last lines of raw PEM (header/footer) without printing body
    raw = os.environ.get("COINBASE_PEM_CONTENT")
    if raw:
        raw_preview = raw.replace("\\n", "\n")
        lines = raw_preview.strip().splitlines()
        head = lines[0] if lines else "<no-lines>"
        tail = lines[-1] if len(lines) > 1 else "<no-lines>"
        print("Raw PEM preview (first line, last line):")
        print("  HEAD:", head)
        print("  TAIL:", tail)
    else:
        print("COINBASE_PEM_CONTENT is missing")

    # 4) Auto-fix PEM and show header/footer + length (still not printing secret body)
    fixed = fix_pem(raw)
    if fixed:
        lines = fixed.strip().splitlines()
        print("\nFixed PEM:")
        print("  HEAD:", lines[0])
        print("  TAIL:", lines[-1])
        print("  LENGTH:", len(fixed))
    else:
        print("\nFixed PEM: <none>\n")

    # 5) Generate JWT (preview)
    org = os.environ.get("COINBASE_ORG_ID")
    kid = os.environ.get("COINBASE_API_KEY")
    token = generate_jwt(fixed, kid, org)
    if token:
        preview = token[:50]
        print("\nGenerated JWT preview (first 50 chars):", preview)
    else:
        print("\nNo JWT generated.")

    # 6) If JWT generated, call Coinbase accounts endpoint and print response details
    if token:
        url = f"https://api.coinbase.com/api/v3/brokerage/organizations/{org}/accounts"
        headers = {
            "Authorization": f"Bearer {token}",
            "CB-VERSION": "2025-11-01",
            "User-Agent": "nija-debug/1.0"
        }
        try:
            resp = requests.get(url, headers=headers, timeout=15)
            print("\n--- Coinbase Response ---")
            print("Status Code:", resp.status_code)
            print("Response Headers:")
            for k, v in resp.headers.items():
                print(f"  {k}: {v}")
            print("Response Body (truncated 2000 chars):")
            body = resp.text
            print(body[:2000])
            print("\n--- END Coinbase Response ---\n")
        except Exception as e:
            print("HTTP request exception:", repr(e))
    else:
        print("Skipping Coinbase API call because JWT generation failed.")

    print("\n=== DEBUG DEPLOY END ===\n")

if __name__ == "__main__":
    main()
