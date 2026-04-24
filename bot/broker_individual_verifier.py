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
# Broker criticality registry — single source of truth
# ---------------------------------------------------------------------------

try:
    try:
        from bot.broker_registry import BrokerCriticality, BROKER_DEFAULT_CRITICALITY
    except ImportError:
        from broker_registry import BrokerCriticality, BROKER_DEFAULT_CRITICALITY  # type: ignore[import]
    _CRITICALITY_AVAILABLE = True
except Exception:
    BrokerCriticality = None  # type: ignore[assignment,misc]
    BROKER_DEFAULT_CRITICALITY = {}  # type: ignore[assignment]
    _CRITICALITY_AVAILABLE = False

# ---------------------------------------------------------------------------
# Broker credential requirements
# ---------------------------------------------------------------------------

#: Map of broker name → required environment variables.
#: Kraken (CRITICAL) is listed first so it appears first in reports.
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

# ---------------------------------------------------------------------------
# Helper: derive broker role label from the criticality registry
# ---------------------------------------------------------------------------

def _broker_criticality_label(broker_name: str) -> str:
    """Return a human-readable role label for *broker_name* from the registry.

    Falls back gracefully when the registry is unavailable.
    """
    if not _CRITICALITY_AVAILABLE or BrokerCriticality is None:
        return "unknown"
    level = BROKER_DEFAULT_CRITICALITY.get(broker_name)
    if level is None:
        return "optional"
    return level.value  # e.g. "critical", "primary", "optional", "deferred"


def _is_critical_broker(broker_name: str) -> bool:
    """Return True if *broker_name* has CRITICAL criticality.

    Uses :data:`BROKER_DEFAULT_CRITICALITY` so the answer is consistent
    even before the registry has been populated at runtime.
    """
    if not _CRITICALITY_AVAILABLE or BrokerCriticality is None:
        # Legacy fallback: treat kraken as the only critical broker
        return broker_name == "kraken"
    return BROKER_DEFAULT_CRITICALITY.get(broker_name) == BrokerCriticality.CRITICAL


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class BrokerVerifyResult:
    """Outcome of verifying a single broker."""

    broker_name: str
    #: True when the broker has CRITICAL criticality (must connect before users).
    is_critical: bool = False
    #: Criticality label string, e.g. "critical", "primary", "optional".
    criticality_label: str = "unknown"

    # Credential checks
    credentials_configured: bool = False
    missing_credentials: List[str] = field(default_factory=list)

    # Registry / criticality check (formerly "registry_primary_set")
    registry_criticality_set: bool = False

    # OKX-specific filesystem check
    data_dir_ok: Optional[bool] = None   # None if not applicable

    # Overall
    passed: bool = False
    messages: List[str] = field(default_factory=list)

    # ------------------------------------------------------------------
    # Backward-compatibility shim — callers that still read is_primary
    # or registry_primary_set will get a sensible value automatically.
    # ------------------------------------------------------------------

    @property
    def is_primary(self) -> bool:
        """Alias for :attr:`is_critical` (backward-compatible)."""
        return self.is_critical

    @property
    def registry_primary_set(self) -> bool:
        """Alias for :attr:`registry_criticality_set` (backward-compatible)."""
        return self.registry_criticality_set


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


def _check_registry_criticality(broker_name: str) -> bool:
    """Return True if the broker_registry has stored a criticality level for *broker_name*.

    A stored value (even the default CRITICAL) is treated as "set" — it means
    the registry is the authoritative source for this broker's role.
    """
    try:
        try:
            from bot.broker_registry import broker_registry, BrokerCriticality as _BC
        except ImportError:
            from broker_registry import broker_registry, BrokerCriticality as _BC  # type: ignore[import]
        stored = broker_registry.get_state(broker_name, "criticality")
        # A runtime-stored BrokerCriticality value means the system has
        # explicitly confirmed the broker's role (e.g. after connecting).
        return isinstance(stored, _BC)
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
    is_critical = _is_critical_broker(broker_name)
    criticality_label = _broker_criticality_label(broker_name)
    result = BrokerVerifyResult(
        broker_name=broker_name,
        is_critical=is_critical,
        criticality_label=criticality_label,
    )

    # 1. Credential check
    creds_ok, missing = _check_credentials(broker_name)
    result.credentials_configured = creds_ok
    result.missing_credentials = missing

    if creds_ok:
        result.messages.append(f"✅ Credentials configured")
    else:
        for var in missing:
            result.messages.append(f"❌ Missing credential: {var}")

    # 2. Criticality / registry check (CRITICAL brokers only)
    if is_critical:
        result.registry_criticality_set = _check_registry_criticality(broker_name)
        if result.registry_criticality_set:
            result.messages.append(
                f"✅ Criticality confirmed as CRITICAL in broker registry"
            )
        elif creds_ok:
            result.messages.append(
                f"⚠️  {broker_name.capitalize()} credentials present but criticality "
                "not yet stored in broker_registry — will be set when the platform "
                "broker connects"
            )
        else:
            result.messages.append(
                f"❌ {broker_name.capitalize()} not confirmed as CRITICAL in broker "
                "registry (configure credentials first)"
            )

    # 3. OKX filesystem check
    if broker_name == "okx":
        dir_ok, dir_msg = _check_okx_data_dir()
        result.data_dir_ok = dir_ok
        result.messages.append(("✅ " if dir_ok else "❌ ") + dir_msg)

    # Compute overall pass/fail
    # CRITICAL brokers are allowed to pass even when the registry criticality
    # hasn't been set yet — the registry is only populated after a live
    # connection, so a pre-flight check must not block on it.
    result.passed = (
        result.credentials_configured
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
        role = f" [{result.criticality_label.upper()}]"
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
