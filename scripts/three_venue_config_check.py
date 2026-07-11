"""NIJA three-venue configuration gate.

Validates that Kraken, Coinbase, and OKX credentials, live-trading flags, and
Redis connectivity are all present before the main bot process starts.  Exits
with code 2 when the environment is incomplete so the bootstrap script can fail
fast and surface the missing pieces in the deployment logs.

Run with ``python3 -S`` to avoid triggering NIJA's site-customise trading hooks
before writer authority has been established.

Usage (from the repository root):
    python3 -S scripts/three_venue_config_check.py
"""

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

TRUE = {"1", "true", "yes", "on", "enabled"}
FALSE = {"0", "false", "no", "off", "disabled"}

required_secrets = [
    "KRAKEN_PLATFORM_API_KEY",
    "KRAKEN_PLATFORM_API_SECRET",
    "COINBASE_API_KEY",
    "COINBASE_API_SECRET",
    "OKX_API_KEY",
    "OKX_API_SECRET",
    "OKX_PASSPHRASE",
]

# Environment flags that must be set to a truthy value for three-venue live
# trading to be authorised.
true_flags = [
    "LIVE_TRADING",
    "LIVE_CAPITAL_VERIFIED",
    "ENABLE_COINBASE",
    "ENABLE_COINBASE_TRADING",
    "COINBASE_LIVE_TRADING_ENABLED",
    "ENABLE_OKX",
    "ENABLE_OKX_TRADING",
    "OKX_LIVE_TRADING_ENABLED",
    "NIJA_OKX_EXECUTION_ENABLED",
    "NIJA_OKX_LIVE_TRADING_ENABLED",
    "NIJA_BROKER_INDEPENDENT_LIVE_EXECUTION",
    "NIJA_INDEPENDENT_BROKER_TRADING",
    "NIJA_REQUIRE_SECONDARY_VENUES_READY",
    "NIJA_REQUIRE_DISTRIBUTED_LOCK",
    "STRICT_REDIS_WRITER_LOCK",
    "NIJA_STRICT_REDIS_LEASE",
]

# Environment flags that must be set to a falsy value (safety guards that must
# NOT be active in a live three-venue deployment).
false_flags = [
    "DRY_RUN_MODE",
    "PAPER_MODE",
    "NIJA_DISABLE_COINBASE",
    "NIJA_DISABLE_OKX",
]

missing = [name for name in required_secrets if not os.getenv(name, "").strip()]

bad_true = [
    name for name in true_flags
    if os.getenv(name, "").strip().lower() not in TRUE
]

bad_false = [
    name for name in false_flags
    if os.getenv(name, "false").strip().lower() not in FALSE
]

print("=== NIJA THREE-VENUE CONFIGURATION ===")

for name in required_secrets:
    value = os.getenv(name, "")
    print(f"{name}: {'SET' if value.strip() else 'MISSING'}")

for name in true_flags + false_flags:
    print(f"{name}: {os.getenv(name, 'UNSET')}")

redis_present = any(
    os.getenv(name, "").strip()
    for name in (
        "NIJA_REDIS_URL",
        "REDIS_URL",
        "REDIS_PRIVATE_URL",
        "REDIS_PUBLIC_URL",
        "REDIS_TLS_URL",
    )
)
print(f"REDIS CONNECTION: {'SET' if redis_present else 'MISSING'}")

if missing:
    print("\nMISSING SECRETS:", ", ".join(missing))
if bad_true:
    print("FLAGS THAT MUST BE TRUE:", ", ".join(bad_true))
if bad_false:
    print("FLAGS THAT MUST BE FALSE:", ", ".join(bad_false))
if not redis_present:
    print("REDIS URL IS NOT CONFIGURED")

print("\n=== LOCAL ENDPOINTS ===")

port = os.getenv("PORT", "5000")
for path in ("/healthz", "/readyz"):
    url = f"http://127.0.0.1:{port}{path}"
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            body = response.read().decode("utf-8", errors="replace")
            print(f"{path}: HTTP {response.status}")
            print(body)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        print(f"{path}: HTTP {exc.code}")
        print(body)
    except Exception as exc:
        print(f"{path}: ERROR {type(exc).__name__}: {exc}")

print("\n=== SHARED READINESS STATE ===")

state_path = Path(
    os.getenv(
        "NIJA_RENDER_READINESS_STATE_FILE",
        "/tmp/nija_render_readiness.json",
    )
)

if state_path.exists():
    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
        print(json.dumps(payload, indent=2, sort_keys=True))
    except Exception as exc:
        print(f"Could not parse {state_path}: {exc}")
else:
    print(f"Readiness state file not found: {state_path}")

if missing or bad_true or bad_false or not redis_present:
    print("\nRESULT: CONFIGURATION INCOMPLETE")
    sys.exit(2)

print("\nRESULT: ENVIRONMENT CONFIGURATION PRESENT")
print("NIJA must still prove writer authority, balances, markets and venue readiness.")
