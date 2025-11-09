# check_env.py
import os, sys, re

required_for_advanced = ["BASE_URL", "COINBASE_AUTH_MODE"]
adv_one_of = ["COINBASE_PEM_CONTENT", "COINBASE_PRIVATE_KEY_PATH"]
hmac_set = ["COINBASE_API_KEY", "COINBASE_API_SECRET", "COINBASE_API_PASSPHRASE"]

def present(k): return k in os.environ and bool(os.environ[k].strip())

print("ENV quick validator\n-------------------")
for k in required_for_advanced:
    print(f"{k:25}: {'SET' if present(k) else 'MISSING'}")

# check PEM or path
pem_present = any(present(x) for x in adv_one_of)
print(f"{'COINBASE_PEM/PRIVATE_KEY_PATH':25}: {'OK' if pem_present else 'MISSING (need PEM or path)'}")

# If COINBASE_AUTH_MODE is advanced, ensure PEM/key id
auth_mode = os.environ.get("COINBASE_AUTH_MODE","").lower()
if auth_mode == "advanced" or auth_mode == "jwt":
    if not pem_present:
        print("ERROR: COINBASE_AUTH_MODE=advanced but no PEM configured (COINBASE_PEM_CONTENT or COINBASE_PRIVATE_KEY_PATH).")
    if not present("COINBASE_KEY_ID"):
        print("WARN: COINBASE_KEY_ID (kid) not set — recommended for JWT header.")
    if not present("COINBASE_ISS"):
        print("WARN: COINBASE_ISS not set — some flows require issuer/org id.")

# If HMAC keys present, warn that they will be used if auth mode is hmac
if any(present(x) for x in hmac_set):
    print("HMAC keys detected (COINBASE_API_KEY/SECRET/PASSPHRASE) — ensure COINBASE_AUTH_MODE is 'hmac' if you want HMAC flow.")

# Basic format checks
base = os.environ.get("BASE_URL","")
if base and not base.startswith("https://"):
    print("WARN: BASE_URL does not start with https:// — verify correctness.")

# Numeric checks
for num_key in ("MAX_TRADE_PERCENT","MIN_TRADE_PERCENT","PORT"):
    val = os.environ.get(num_key)
    if val:
        try:
            float(val)
        except:
            print(f"WARN: {num_key} should be numeric. Current='{val}'")

# LIVE_TRADING
lt = os.environ.get("LIVE_TRADING")
if lt and lt not in ("0","1","false","true","False","True"):
    print("WARN: LIVE_TRADING should be 0 or 1 (or true/false).")

print("\nCompleted checks. Do NOT paste secrets here. If you see errors, fix env and re-run.")
