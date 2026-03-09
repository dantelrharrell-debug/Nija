"""
NIJA Individual Broker Verifier
=================================

Verifies that each broker is correctly configured and reachable.

The verifier checks, for every broker:
1. Required environment-variable credentials are present and non-empty.
2. The OKX data-directory exists and is writable (filesystem permission check).
3. The broker_registry marks Kraken as the platform (PRIMARY) broker.

Usage (CLI)::

    python bot/broker_individual_verifier.py

Usage (in code)::

    from bot.broker_individual_verifier import verify_all_brokers, verify_broker
    results = verify_all_brokers()        # {broker_name: BrokerVerifyResult}
    result  = verify_broker("kraken")     # BrokerVerifyResult
"""

from __future__ import annotations

import logging
import os
import stat
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger("nija.broker_verifier")

# ---------------------------------------------------------------------------
# Broker credential requirements
# ---------------------------------------------------------------------------

#: Map of broker name → required environment variables.
#: Kraken (PRIMARY) is listed first so it appears first in reports.
BROKER_CREDENTIALS: Dict[str, List[str]] = {
    "kraken": [
        "KRAKEN_PLATFORM_API_KEY",
        "KRAKEN_PLATFORM_API_SECRET",
    ],
    "coinbase": [
        "COINBASE_API_KEY",
        "COINBASE_API_SECRET",
    ],
    "binance": [
        "BINANCE_API_KEY",
        "BINANCE_API_SECRET",
    ],
    "okx": [
        "OKX_API_KEY",
        "OKX_API_SECRET",
        "OKX_PASSPHRASE",
    ],
    "alpaca": [
        "ALPACA_API_KEY",
        "ALPACA_API_SECRET",
    ],
}

# Broker that must be designated as the platform (PRIMARY) account.
PRIMARY_BROKER = "kraken"


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class BrokerVerifyResult:
    """Outcome of verifying a single broker."""

    broker_name: str
    is_primary: bool = False

    # Credential checks
    credentials_configured: bool = False
    missing_credentials: List[str] = field(default_factory=list)

    # Registry / primary check
    registry_primary_set: bool = False

    # OKX-specific filesystem check
    data_dir_ok: Optional[bool] = None   # None if not applicable

    # Overall
    passed: bool = False
    messages: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Individual broker verification helpers
# ---------------------------------------------------------------------------

def _check_credentials(broker_name: str) -> tuple[bool, list[str]]:
    """Return (all_present, list_of_missing_vars)."""
    required = BROKER_CREDENTIALS.get(broker_name, [])
    missing = [v for v in required if not os.getenv(v, "").strip()]
    return (len(missing) == 0), missing


def _check_okx_data_dir() -> tuple[bool, str]:
    """
    Ensure the OKX position-tracker data directory exists and is writable.

    The OKX broker writes `data/positions.json` relative to the *project root*
    (one level above `bot/`).  We create the directory here with mode 0o750
    (owner read/write/execute, group read/execute, no world access) to prevent
    world-readable credential artefacts.

    Returns:
        (ok, message) where ok is True when the directory is usable.
    """
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    data_dir = os.path.join(project_root, "data")

    try:
        os.makedirs(data_dir, mode=0o750, exist_ok=True)
    except OSError as exc:
        return False, f"Cannot create OKX data directory {data_dir!r}: {exc}"

    # Verify it is writable by the current process
    if not os.access(data_dir, os.W_OK):
        return False, f"OKX data directory {data_dir!r} is not writable"

    # Warn if the directory has overly permissive (world-writable) bits
    dir_mode = stat.S_IMODE(os.stat(data_dir).st_mode)
    if dir_mode & stat.S_IWOTH:
        logger.warning(
            "OKX data directory %r is world-writable (mode %04o) — "
            "tightening to 0o750",
            data_dir, dir_mode,
        )
        try:
            os.chmod(data_dir, 0o750)
        except OSError as exc:
            logger.warning("Could not chmod OKX data directory: %s", exc)

    return True, f"OKX data directory OK: {data_dir!r}"


def _check_registry_primary(broker_name: str) -> bool:
    """Return True if the broker_registry marks *broker_name* as platform."""
    try:
        try:
            from bot.broker_registry import broker_registry
        except ImportError:
            from broker_registry import broker_registry  # type: ignore[import]
        return broker_registry.is_platform(broker_name)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def verify_broker(broker_name: str) -> BrokerVerifyResult:
    """
    Verify configuration for a single broker.

    Args:
        broker_name: One of ``"kraken"``, ``"coinbase"``, ``"binance"``,
            ``"okx"``, ``"alpaca"``.

    Returns:
        :class:`BrokerVerifyResult` with detailed status.
    """
    broker_name = broker_name.lower()
    is_primary = broker_name == PRIMARY_BROKER
    result = BrokerVerifyResult(broker_name=broker_name, is_primary=is_primary)

    # 1. Credential check
    creds_ok, missing = _check_credentials(broker_name)
    result.credentials_configured = creds_ok
    result.missing_credentials = missing

    if creds_ok:
        result.messages.append(f"✅ Credentials configured")
    else:
        for var in missing:
            result.messages.append(f"❌ Missing credential: {var}")

    # 2. Primary / registry check (Kraken only)
    if is_primary:
        result.registry_primary_set = _check_registry_primary(broker_name)
        if result.registry_primary_set:
            result.messages.append(f"✅ Marked as PRIMARY in broker registry")
        elif creds_ok:
            result.messages.append(
                "⚠️  Kraken credentials present but not yet marked PRIMARY in "
                "broker_registry — will be set when the platform broker connects"
            )
        else:
            result.messages.append(
                "❌ Kraken not marked PRIMARY in broker registry "
                "(configure KRAKEN_PLATFORM_API_KEY / SECRET first)"
            )

    # 3. OKX filesystem check
    if broker_name == "okx":
        dir_ok, dir_msg = _check_okx_data_dir()
        result.data_dir_ok = dir_ok
        result.messages.append(("✅ " if dir_ok else "❌ ") + dir_msg)

    # Compute overall pass/fail
    result.passed = (
        result.credentials_configured
        and (not result.is_primary or result.registry_primary_set)
        and (result.data_dir_ok is None or result.data_dir_ok)
    )

    return result


def verify_all_brokers() -> Dict[str, BrokerVerifyResult]:
    """
    Verify all known brokers and return results keyed by broker name.

    Returns:
        Mapping of broker name → :class:`BrokerVerifyResult`.
    """
    return {name: verify_broker(name) for name in BROKER_CREDENTIALS}


def print_verification_report(results: Optional[Dict[str, BrokerVerifyResult]] = None) -> bool:
    """
    Print a human-readable verification report to stdout.

    Args:
        results: Pre-computed results dict; if ``None``, :func:`verify_all_brokers`
            is called automatically.

    Returns:
        ``True`` if all brokers passed, ``False`` otherwise.
    """
    if results is None:
        results = verify_all_brokers()

    width = 70
    print("=" * width)
    print("NIJA BROKER CONFIGURATION VERIFICATION".center(width))
    print("=" * width)

    all_passed = True
    for broker_name, result in results.items():
        role = " [PRIMARY]" if result.is_primary else " [secondary]"
        status = "✅ PASS" if result.passed else "❌ FAIL"
        print(f"\n{status}  {broker_name.upper()}{role}")
        for msg in result.messages:
            print(f"      {msg}")
        if not result.passed:
            all_passed = False

    print("\n" + "=" * width)
    if all_passed:
        print("✅  All brokers verified — NIJA is ready for multi-broker operation")
    else:
        print("❌  One or more brokers failed verification — see messages above")
        print("    Set the missing environment variables and re-run this script.")
    print("=" * width)
    return all_passed


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )

    passed = print_verification_report()
    sys.exit(0 if passed else 1)
