"""NIJA independent-broker configuration check.

Validates shared live-trading safety settings and evaluates Kraken, Coinbase, and
OKX independently. Startup succeeds when at least one brokerage has a complete
configuration. Missing or incomplete credentials for another brokerage are
reported as degraded and that brokerage is excluded; they never stop a healthy
brokerage from starting.

Run with ``python3 -S`` to avoid triggering NIJA's site-customise trading hooks
before writer authority has been established.
"""

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

TRUE = {"1", "true", "yes", "on", "enabled"}
FALSE = {"0", "false", "no", "off", "disabled"}

BROKERS = {
    "kraken": {
        "secrets": ("KRAKEN_PLATFORM_API_KEY", "KRAKEN_PLATFORM_API_SECRET"),
        "true_flags": (),
        "false_flags": (),
    },
    "coinbase": {
        "secrets": ("COINBASE_API_KEY", "COINBASE_API_SECRET"),
        "true_flags": (
            "ENABLE_COINBASE",
            "ENABLE_COINBASE_TRADING",
            "COINBASE_LIVE_TRADING_ENABLED",
        ),
        "false_flags": ("NIJA_DISABLE_COINBASE",),
    },
    "okx": {
        "secrets": ("OKX_API_KEY", "OKX_API_SECRET", "OKX_PASSPHRASE"),
        "true_flags": (
            "ENABLE_OKX",
            "ENABLE_OKX_TRADING",
            "OKX_LIVE_TRADING_ENABLED",
            "NIJA_OKX_EXECUTION_ENABLED",
            "NIJA_OKX_LIVE_TRADING_ENABLED",
        ),
        "false_flags": ("NIJA_DISABLE_OKX",),
    },
}

SHARED_TRUE_FLAGS = (
    "LIVE_TRADING",
    "LIVE_CAPITAL_VERIFIED",
    "NIJA_BROKER_INDEPENDENT_LIVE_EXECUTION",
    "NIJA_INDEPENDENT_BROKER_TRADING",
    "NIJA_REQUIRE_DISTRIBUTED_LOCK",
    "STRICT_REDIS_WRITER_LOCK",
    "NIJA_STRICT_REDIS_LEASE",
)
SHARED_FALSE_FLAGS = ("DRY_RUN_MODE", "PAPER_MODE")


def _is_true(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in TRUE


def _is_false(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in FALSE


def _broker_status(name: str, contract: dict[str, tuple[str, ...]]) -> dict[str, object]:
    secrets = contract["secrets"]
    true_flags = contract["true_flags"]
    false_flags = contract["false_flags"]
    present_secrets = [secret for secret in secrets if os.getenv(secret, "").strip()]
    missing_secrets = [secret for secret in secrets if secret not in present_secrets]
    bad_true = [flag for flag in true_flags if not _is_true(flag)]
    bad_false = [flag for flag in false_flags if not _is_false(flag)]

    any_config = bool(present_secrets) or any(flag in os.environ for flag in (*true_flags, *false_flags))
    ready = not missing_secrets and not bad_true and not bad_false
    if ready:
        state = "ready"
        reason = "configuration_complete"
    elif not any_config:
        state = "not_configured"
        reason = "no_credentials_or_flags"
    else:
        state = "degraded"
        parts = []
        if missing_secrets:
            parts.append("missing_secrets=" + ",".join(missing_secrets))
        if bad_true:
            parts.append("flags_not_true=" + ",".join(bad_true))
        if bad_false:
            parts.append("flags_not_false=" + ",".join(bad_false))
        reason = ";".join(parts) or "configuration_incomplete"

    return {
        "broker": name,
        "ready": ready,
        "state": state,
        "reason": reason,
        "configured_secret_count": len(present_secrets),
        "required_secret_count": len(secrets),
        "missing_secrets": missing_secrets,
        "bad_true_flags": bad_true,
        "bad_false_flags": bad_false,
    }


bad_shared_true = [name for name in SHARED_TRUE_FLAGS if not _is_true(name)]
bad_shared_false = [name for name in SHARED_FALSE_FLAGS if not _is_false(name)]
broker_statuses = {name: _broker_status(name, contract) for name, contract in BROKERS.items()}
ready_brokers = [name for name, status in broker_statuses.items() if status["ready"]]
degraded_brokers = [name for name, status in broker_statuses.items() if status["state"] == "degraded"]

print("=== NIJA INDEPENDENT-BROKER CONFIGURATION ===")
print(json.dumps(broker_statuses, indent=2, sort_keys=True))
print("READY BROKERS:", ", ".join(ready_brokers) or "none")
print("DEGRADED BROKERS:", ", ".join(degraded_brokers) or "none")
print("LEGACY CROSS-VENUE GATE:", os.getenv("NIJA_REQUIRE_SECONDARY_VENUES_READY", "false"))

for name in SHARED_TRUE_FLAGS + SHARED_FALSE_FLAGS:
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

if bad_shared_true:
    print("SHARED FLAGS THAT MUST BE TRUE:", ", ".join(bad_shared_true))
if bad_shared_false:
    print("SHARED FLAGS THAT MUST BE FALSE:", ", ".join(bad_shared_false))
if not ready_brokers:
    print("NO BROKER HAS A COMPLETE INDEPENDENT CONFIGURATION")
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
    os.getenv("NIJA_RENDER_READINESS_STATE_FILE", "/tmp/nija_render_readiness.json")
)
if state_path.exists():
    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
        print(json.dumps(payload, indent=2, sort_keys=True))
    except Exception as exc:
        print(f"Could not parse {state_path}: {exc}")
else:
    print(f"Readiness state file not found: {state_path}")

fatal = bool(bad_shared_true or bad_shared_false or not redis_present or not ready_brokers)
if fatal:
    print("\nRESULT: INDEPENDENT-BROKER CONFIGURATION INCOMPLETE")
    sys.exit(2)

print("\nRESULT: AT LEAST ONE BROKER IS CONFIGURED")
print("Each remaining broker will activate or remain isolated according to its own connection state.")
