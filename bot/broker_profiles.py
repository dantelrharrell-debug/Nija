"""
NIJA Broker Profiles — Central Registry
========================================

Single source of truth for per-broker execution policies, capital rules,
risk modes, and execution modes.

Used by:
- GlobalController  (risk_check / execute_trade routing)
- CoinbaseController (micro-cap capital floor)
- KrakenController  (isolation enforcement)

Environment overrides
---------------------
COINBASE_MIN_CAPITAL  — minimum USD balance for Coinbase to trade (default 1.0)
COINBASE_MIN_ORDER    — minimum USD order size on Coinbase (default 1.0)
KRAKEN_MIN_CAPITAL    — minimum USD balance for Kraken (default 25.0)
KRAKEN_MIN_ORDER      — minimum USD order size on Kraken (default 10.0)
"""

import os

# ---------------------------------------------------------------------------
# Exchange-scoped capital constants (Steps 2 & 5)
# Coinbase uses its own floors — it must NOT inherit Kraken conservatism.
#
# Environment variables (Step 5):
#   COINBASE_MICRO_CAP_MODE             — enable micro-cap mode (default true)
#   COINBASE_MIN_ORDER_USD              — alias for COINBASE_MIN_ORDER
#   COINBASE_IGNORE_GLOBAL_CAPITAL_FLOOR — bypass global capital floor for Coinbase
#   KRAKEN_EXECUTION_DISABLED           — fully disable Kraken execution (default false)
# ---------------------------------------------------------------------------

#: Activate Coinbase micro-cap mode (Step 5). Default: true.
COINBASE_MICRO_CAP_MODE: bool = (
    os.getenv("COINBASE_MICRO_CAP_MODE", "true").strip().lower()
    in ("1", "true", "yes")
)

#: When true, Coinbase ignores the system-wide global capital floor (Step 5).
COINBASE_IGNORE_GLOBAL_CAPITAL_FLOOR: bool = (
    os.getenv("COINBASE_IGNORE_GLOBAL_CAPITAL_FLOOR", "false").strip().lower()
    in ("1", "true", "yes")
)

#: When true, all Kraken order execution is disabled (Step 5 & 6).
KRAKEN_EXECUTION_DISABLED: bool = (
    os.getenv("KRAKEN_EXECUTION_DISABLED", "false").strip().lower()
    in ("1", "true", "yes")
)

#: Minimum USD balance required for Coinbase to open new positions.
#: COINBASE_MIN_ORDER_USD is accepted as an alias (Step 5).
COINBASE_MIN_CAPITAL: float = float(
    os.getenv("COINBASE_MIN_CAPITAL", "1.0")
)

#: Minimum USD order size allowed on Coinbase.
#: COINBASE_MIN_ORDER_USD takes precedence when set (Step 5).
COINBASE_MIN_ORDER: float = float(
    os.getenv("COINBASE_MIN_ORDER_USD", os.getenv("COINBASE_MIN_ORDER", "1.0"))
)

#: Minimum USD balance required for Kraken to open new positions.
KRAKEN_MIN_CAPITAL: float = float(os.getenv("KRAKEN_MIN_CAPITAL", "25.0"))

#: Minimum USD order size on Kraken (exchange hard-floor is $10).
KRAKEN_MIN_ORDER: float = float(os.getenv("KRAKEN_MIN_ORDER", "10.0"))

# ---------------------------------------------------------------------------
# BROKER_PROFILES — per-broker policy registry
# ---------------------------------------------------------------------------

#: Profiles indexed by lower-case broker name (matches ``broker_type.value``).
BROKER_PROFILES: dict = {
    "coinbase": {
        # Capital rules — independent of Kraken
        "min_capital_usd": COINBASE_MIN_CAPITAL,
        "min_order_usd": COINBASE_MIN_ORDER,

        # Micro-cap trading enabled when COINBASE_MICRO_CAP_MODE=true
        "micro_cap_enabled": COINBASE_MICRO_CAP_MODE,

        # Ignore global capital floor when COINBASE_IGNORE_GLOBAL_CAPITAL_FLOOR=true
        "ignore_global_capital_floor": COINBASE_IGNORE_GLOBAL_CAPITAL_FLOOR,

        # Active execution: Coinbase is the live execution path
        "execution_mode": "active",

        # Risk mode: bypass global risk gating for micro-cap Coinbase trades
        # (global risk still logs; it does not block)
        "risk_mode": "bypass",

        # Coinbase is included in execution capital weighting
        "include_in_execution_capital": True,
    },
    "kraken": {
        # Capital rules
        "min_capital_usd": KRAKEN_MIN_CAPITAL,
        "min_order_usd": KRAKEN_MIN_ORDER,

        # Micro-cap not applicable — Kraken is isolated
        "micro_cap_enabled": False,

        # Isolated: no new entries; only exits allowed in STRICT mode.
        # When KRAKEN_EXECUTION_DISABLED=true, fully passive.
        "execution_mode": "passive" if KRAKEN_EXECUTION_DISABLED else "isolated",

        # Risk mode: log only — Kraken risk events are recorded but never
        # block execution on other brokers
        "risk_mode": "isolated",

        # Kraken is EXCLUDED from execution capital weighting (Step 4)
        "include_in_execution_capital": False,

        # Step 6: flag consumed by KrakenBroker.place_market_order guard
        "execution_disabled": KRAKEN_EXECUTION_DISABLED,
    },
}


def get_broker_profile(broker_name: str) -> dict:
    """Return the profile for *broker_name* (case-insensitive).

    Falls back to a permissive default so unknown brokers are not silently
    blocked.
    """
    return BROKER_PROFILES.get(broker_name.lower(), {
        "min_capital_usd": 1.0,
        "min_order_usd": 1.0,
        "micro_cap_enabled": False,
        "execution_mode": "active",
        "risk_mode": "default",
        "include_in_execution_capital": True,
    })
