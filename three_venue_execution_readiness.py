"""Per-venue execution-readiness verifier for Kraken, Coinbase, and OKX.

This observer reports one stage matrix for every configured platform venue without
creating brokers, connecting accounts, placing probe orders, fabricating balances,
or bypassing writer/risk controls. Each brokerage remains independent: a degraded
venue is reported and excluded, but it never disables another venue that is fully
ready. The legacy ``NIJA_THREE_VENUE_EXECUTION_READY`` flag is retained for
compatibility and now means that the execution system has at least one ready venue.
"""
from __future__ import annotations

import inspect
import json
import logging
import os
import sys
import tempfile
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Mapping, Optional

logger = logging.getLogger("nija.three_venue_execution_readiness")
MARKER = "20260711n"
VENUES = ("kraken", "coinbase", "okx")
STAGES = (
    "credentials_loaded",
    "authentication_succeeded",
    "balance_fetched",
    "market_metadata_loaded",
    "order_adapter_initialized",
    "venue_marked_ready",
    "eligible_for_execution",
)
_STATE_FILE = Path(
    os.getenv(
        "NIJA_THREE_VENUE_READINESS_FILE",
        "/tmp/nija_three_venue_readiness.json",
    )
)
_LOCK = threading.RLock()
_INSTALLED = False
_LAST_SIGNATURE = ""


def _capital_snapshot_is_stale(authority: Any) -> bool:
    """Read snapshot staleness across legacy and canonical authority APIs."""
    reader = getattr(authority, "is_stale", None)
    if not callable(reader):
        return True

    try:
        parameters = inspect.signature(reader).parameters.values()
    except (TypeError, ValueError):
        # Some extension-backed callables do not expose a Python signature.
        try:
            return bool(reader(90.0))
        except TypeError:
            return bool(reader())

    parameters = tuple(parameters)
    if any(parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in parameters):
        return bool(reader(ttl_s=90.0))
    if any(parameter.name == "ttl_s" for parameter in parameters):
        return bool(reader(ttl_s=90.0))
    if any(
        parameter.kind
        in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
        for parameter in parameters
    ) or any(parameter.kind == inspect.Parameter.VAR_POSITIONAL for parameter in parameters):
        return bool(reader(90.0))
    return bool(reader())

_CREDENTIALS = {
    "kraken": (
        ("KRAKEN_PLATFORM_API_KEY", "KRAKEN_API_KEY"),
        ("KRAKEN_PLATFORM_API_SECRET", "KRAKEN_API_SECRET"),
    ),
    "coinbase": (
        (
            "COINBASE_API_KEY",
            "COINBASE_PLATFORM_API_KEY",
            "COINBASE_ADVANCED_API_KEY",
        ),
        (
            "COINBASE_API_SECRET",
            "COINBASE_PLATFORM_API_SECRET",
            "COINBASE_ADVANCED_API_SECRET",
        ),
    ),
    "okx": (
        ("OKX_API_KEY", "OKX_PLATFORM_API_KEY"),
        ("OKX_API_SECRET", "OKX_PLATFORM_API_SECRET"),
        (
            "OKX_PASSPHRASE",
            "OKX_API_PASSPHRASE",
            "OKX_PLATFORM_PASSPHRASE",
        ),
    ),
}


@dataclass(frozen=True)
class VenueReadiness:
    venue: str
    credentials_loaded: bool
    authentication_succeeded: bool
    balance_fetched: bool
    market_metadata_loaded: bool
    order_adapter_initialized: bool
    venue_marked_ready: bool
    eligible_for_execution: bool
    connected: bool
    spendable_quote: float
    market_count: Optional[int]
    activation_state: str
    reason: str

    @property
    def ready(self) -> bool:
        return all(bool(getattr(self, stage)) for stage in STAGES)


def _truthy(name: str) -> bool:
    return str(os.getenv(name, "") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
        "enabled",
        "y",
    }


def _capital_ready() -> bool:
    """Observe canonical capital readiness without using trading state as proof.

    ``LIVE_ACTIVE`` is a consumer of capital readiness, not a valid substitute
    for it.  Treating the runtime state as proof made this observer circular:
    a fully hydrated CapitalAuthority could still be reported as unready until
    activation, while activation diagnostics waited for this observer.
    """
    if _truthy("CAPITAL_SYSTEM_READY") or _truthy("NIJA_CAPITAL_READY"):
        return True

    capital_module = sys.modules.get("bot.capital_authority") or sys.modules.get(
        "capital_authority"
    )
    if not isinstance(capital_module, ModuleType):
        return False
    getter = getattr(capital_module, "get_capital_authority", None)
    if not callable(getter):
        return False
    try:
        authority = getter()
        if authority is None:
            return False

        hydrated_reader = getattr(authority, "is_hydrated", False)
        hydrated = bool(
            hydrated_reader() if callable(hydrated_reader) else hydrated_reader
        )
        if not hydrated:
            return False

        # Use 90-second TTL to match capital_authority._DEFAULT_FRESHNESS_TTL_S.
        # The default 60-second TTL caused false "stale" readings when capital was
        # refreshed 60-90 seconds ago, keeping execution_ready=False and producing
        # repeated THREE_VENUE_EXECUTION_WAITING log lines despite valid capital.
        stale = _capital_snapshot_is_stale(authority)
        capital_reader = getattr(authority, "get_real_capital", None)
        real_capital = float(
            capital_reader()
            if callable(capital_reader)
            else getattr(authority, "total_capital", 0.0)
            or 0.0
        )

        valid_brokers = 0
        for attr in ("valid_brokers", "broker_count", "_valid_broker_count"):
            try:
                candidate = int(getattr(authority, attr, 0) or 0)
            except Exception:
                candidate = 0
            if candidate > 0:
                valid_brokers = candidate
                break

        handoff_ready = (
            _truthy("NIJA_CAPITAL_READINESS_HANDOFF_V34")
            or _truthy("NIJA_CAPITAL_READINESS_HANDOFF_V34_READY")
            or (_truthy("CAPITAL_SYSTEM_READY") and _truthy("NIJA_CAPITAL_READY"))
        )
        if handoff_ready and real_capital > 0.0 and valid_brokers > 0:
            stale = False

        return real_capital > 0.0 and not stale
    except Exception:
        return False


def _credentials_loaded(venue: str) -> tuple[bool, str]:
    missing: list[str] = []
    for aliases in _CREDENTIALS[venue]:
        if not any(str(os.getenv(name, "") or "").strip() for name in aliases):
            missing.append(aliases[0])
    return (not missing, "" if not missing else "missing:" + ",".join(missing))


def _runtime() -> tuple[Optional[ModuleType], Any]:
    broker_module = sys.modules.get("bot.broker_manager") or sys.modules.get(
        "broker_manager"
    )
    mabm_module = sys.modules.get("bot.multi_account_broker_manager") or sys.modules.get(
        "multi_account_broker_manager"
    )
    if not isinstance(broker_module, ModuleType) or not isinstance(
        mabm_module, ModuleType
    ):
        return None, None
    manager = getattr(mabm_module, "multi_account_broker_manager", None)
    if manager is None:
        getter = getattr(mabm_module, "get_broker_manager", None)
        try:
            manager = getter() if callable(getter) else None
        except Exception:
            manager = None
    return broker_module, manager


def _broker(manager: Any, broker_module: ModuleType, venue: str) -> Any:
    enum_name = venue.upper()
    enum_value = getattr(getattr(broker_module, "BrokerType", None), enum_name, None)
    for attr in ("_platform_brokers", "platform_brokers", "brokers"):
        mapping = getattr(manager, attr, None)
        if isinstance(mapping, Mapping):
            candidate = (
                mapping.get(enum_value)
