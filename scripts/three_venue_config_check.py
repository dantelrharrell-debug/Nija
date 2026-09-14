"""NIJA broker-cell configuration gate.

Backward-compatible filename retained because production_bootstrap.sh invokes it.
The old three-venue/global semantics are intentionally removed: Kraken, Coinbase,
OKX and Alpaca are evaluated independently and an incomplete cell never prevents
another complete cell from starting. Only genuinely shared safety infrastructure
(e.g. Redis writer authority) can fail the whole deployment.

Run with ``python3 -S`` so this validation never imports trading runtime hooks.
"""
from __future__ import annotations

import json
import os
import sys
from typing import Dict, Tuple

TRUE = {"1", "true", "yes", "on", "enabled"}
FALSE = {"0", "false", "no", "off", "disabled", ""}

BROKERS: Dict[str, Dict[str, Tuple[str, ...]]] = {
    "kraken": {
        "secrets": ("KRAKEN_PLATFORM_API_KEY", "KRAKEN_PLATFORM_API_SECRET"),
        "true_flags": (),
        "false_flags": (),
    },
    "coinbase": {
        "secrets": ("COINBASE_API_KEY", "COINBASE_API_SECRET"),
        "true_flags": ("ENABLE_COINBASE", "ENABLE_COINBASE_TRADING", "COINBASE_LIVE_TRADING_ENABLED"),
        "false_flags": ("NIJA_DISABLE_COINBASE",),
    },
    "okx": {
        "secrets": ("OKX_API_KEY", "OKX_API_SECRET", "OKX_PASSPHRASE"),
        "true_flags": ("ENABLE_OKX", "ENABLE_OKX_TRADING", "OKX_LIVE_TRADING_ENABLED", "NIJA_OKX_EXECUTION_ENABLED", "NIJA_OKX_LIVE_TRADING_ENABLED"),
        "false_flags": ("NIJA_DISABLE_OKX",),
    },
    "alpaca": {
        "secrets": ("ALPACA_API_KEY", "ALPACA_API_SECRET"),
        "true_flags": (),
        "false_flags": ("NIJA_DISABLE_ALPACA",),
    },
}

SHARED_TRUE_FLAGS = (
    "LIVE_TRADING",
    "NIJA_BROKER_INDEPENDENT_LIVE_EXECUTION",
    "NIJA_INDEPENDENT_BROKER_TRADING",
    "NIJA_REQUIRE_DISTRIBUTED_LOCK",
    "STRICT_REDIS_WRITER_LOCK",
    "NIJA_STRICT_REDIS_LEASE",
)
SHARED_FALSE_FLAGS = ("DRY_RUN_MODE", "PAPER_MODE")
RUNTIME_DERIVED_FLAGS = ("LIVE_CAPITAL_VERIFIED",)
REDIS_NAMES = ("NIJA_REDIS_URL", "REDIS_URL", "REDIS_PRIVATE_URL", "REDIS_PUBLIC_URL", "REDIS_TLS_URL")


def _is_true(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in TRUE


def _is_false(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in FALSE


def _broker_status(name: str, contract: Dict[str, Tuple[str, ...]]) -> Dict[str, object]:
    secrets = contract["secrets"]
    true_flags = contract["true_flags"]
    false_flags = contract["false_flags"]
    present = [secret for secret in secrets if os.getenv(secret, "").strip()]
    missing = [secret for secret in secrets if secret not in present]
    bad_true = [flag for flag in true_flags if not _is_true(flag)]
    bad_false = [flag for flag in false_flags if not _is_false(flag)]
    any_config = bool(present) or any(flag in os.environ for flag in (*true_flags, *false_flags))
    ready = not missing and not bad_true and not bad_false

    if ready:
        state, reason = "ready", "configuration_complete"
    elif not any_config:
        state, reason = "not_configured", "no_credentials_or_flags"
    else:
        state = "degraded"
        reasons = []
        if missing:
            reasons.append("missing_secrets=" + ",".join(missing))
        if bad_true:
            reasons.append("flags_not_true=" + ",".join(bad_true))
        if bad_false:
            reasons.append("flags_not_false=" + ",".join(bad_false))
        reason = ";".join(reasons) or "configuration_incomplete"

    return {
        "broker": name,
        "cell": name,
        "ready": ready,
        "state": state,
        "reason": reason,
        "configured_secret_count": len(present),
        "required_secret_count": len(secrets),
        "missing_secrets": missing,
        "bad_true_flags": bad_true,
        "bad_false_flags": bad_false,
    }


def main() -> int:
    bad_shared_true = [name for name in SHARED_TRUE_FLAGS if not _is_true(name)]
    bad_shared_false = [name for name in SHARED_FALSE_FLAGS if not _is_false(name)]
    statuses = {name: _broker_status(name, contract) for name, contract in BROKERS.items()}
    ready = [name for name, status in statuses.items() if status["ready"]]
    degraded = [name for name, status in statuses.items() if status["state"] == "degraded"]
    redis_present = any(os.getenv(name, "").strip() for name in REDIS_NAMES)

    print("=== NIJA BROKER-CELL CONFIGURATION ===")
    print(json.dumps(statuses, indent=2, sort_keys=True))
    print("READY CELLS:", ", ".join(ready) or "none")
    print("DEGRADED CELLS:", ", ".join(degraded) or "none")
    print("CROSS_BROKER_FAILURE_PROPAGATION: disabled")
    print("USER_CAPITAL_AGGREGATION: isolated")
    print(f"REDIS CONNECTION: {'SET' if redis_present else 'MISSING'}")

    for name in SHARED_TRUE_FLAGS + SHARED_FALSE_FLAGS + RUNTIME_DERIVED_FLAGS:
        print(f"{name}: {os.getenv(name, 'UNSET')}")

    if not _is_true("LIVE_CAPITAL_VERIFIED"):
        print("RUNTIME PROOF PENDING: LIVE_CAPITAL_VERIFIED (re-proven after bootstrap; entries remain fail-closed)")
    if bad_shared_true:
        print("SHARED FLAGS THAT MUST BE TRUE:", ", ".join(bad_shared_true))
    if bad_shared_false:
        print("SHARED FLAGS THAT MUST BE FALSE:", ", ".join(bad_shared_false))
    if not ready:
        print("NO BROKER CELL HAS A COMPLETE INDEPENDENT CONFIGURATION")
    if not redis_present:
        print("REDIS URL IS NOT CONFIGURED")

    safe_off = not _is_true("LIVE_TRADING") and not _is_true("LIVE_CAPITAL_VERIFIED")
    shared_fatal = bool(bad_shared_true or bad_shared_false or not redis_present)
    no_live_cell = not ready

    if safe_off:
        print("RESULT: SAFE-OFF MAINTENANCE MODE")
        return 0
    if shared_fatal or no_live_cell:
        print("RESULT: BROKER-CELL CONFIGURATION INCOMPLETE")
        return 2

    print("RESULT: BROKER-CELL CONFIGURATION READY")
    print("Each cell activates, degrades, halts and recovers independently.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
