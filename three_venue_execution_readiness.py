"""Per-venue execution-readiness verifier for Kraken, Coinbase, and OKX.

This observer reports one stage matrix for every configured platform venue without
creating brokers, connecting accounts, placing probe orders, fabricating balances,
or bypassing writer/risk controls. Each brokerage remains independent: a degraded
venue is reported and excluded, but it never disables another venue that is fully
ready. The legacy ``NIJA_THREE_VENUE_EXECUTION_READY`` flag is retained for
compatibility and now means that the execution system has at least one ready venue.
"""
from __future__ import annotations

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
                or mapping.get(venue)
                or mapping.get(enum_name)
            )
            if candidate is not None:
                return candidate
    getter = getattr(broker_module, "get_platform_broker", None)
    if callable(getter):
        try:
            return getter(venue)
        except Exception:
            return None
    return None


def _connected(broker: Any) -> bool:
    if broker is None:
        return False
    for attr in ("connected", "is_connected"):
        if hasattr(broker, attr):
            try:
                value = getattr(broker, attr)
                return bool(value() if callable(value) else value)
            except Exception:
                return False
    return False


def _balance(broker: Any) -> tuple[bool, float, str]:
    if broker is None:
        return False, 0.0, "broker_missing"
    for method_name in ("get_account_balance_detailed", "get_account_balance"):
        method = getattr(broker, method_name, None)
        if not callable(method):
            continue
        try:
            try:
                payload = method(verbose=False)
            except TypeError:
                payload = method()
            if isinstance(payload, (int, float)):
                return True, max(0.0, float(payload)), method_name
            if isinstance(payload, Mapping):
                for key in (
                    "trading_balance",
                    "available_balance",
                    "available_usd",
                    "usd",
                    "usdt",
                    "usdc",
                    "total",
                ):
                    if key in payload:
                        return (
                            True,
                            max(0.0, float(payload.get(key) or 0.0)),
                            f"{method_name}:{key}",
                        )
                return True, 0.0, method_name
        except Exception as exc:
            return False, 0.0, f"{method_name}:{type(exc).__name__}"
    return False, 0.0, "balance_method_missing"


def _markets(broker: Any) -> tuple[bool, Optional[int], str]:
    if broker is None:
        return False, None, "broker_missing"
    for method_name in (
        "get_available_markets",
        "get_all_products",
        "get_tradable_symbols",
        "get_tradable_universe",
    ):
        method = getattr(broker, method_name, None)
        if not callable(method):
            continue
        try:
            payload = method()
            if isinstance(payload, Mapping):
                count = len(payload)
            elif isinstance(payload, (list, tuple, set)):
                count = len(payload)
            else:
                count = 0
            return count > 0, count, method_name
        except Exception as exc:
            return False, 0, f"{method_name}:{type(exc).__name__}"
    return False, None, "market_method_missing"


def _adapter_ready(broker: Any) -> bool:
    return broker is not None and any(
        callable(getattr(broker, name, None))
        for name in ("execute_order", "place_market_order", "place_order")
    )


def _manager_marks_eligible(
    manager: Any,
    broker_module: ModuleType,
    venue: str,
    broker: Any,
) -> bool:
    enum_value = getattr(getattr(broker_module, "BrokerType", None), venue.upper(), None)
    for attr in (
        "_connected_platform_brokers",
        "connected_platform_brokers",
        "eligible_brokers",
        "_eligible_brokers",
    ):
        value = getattr(manager, attr, None)
        if isinstance(value, Mapping):
            if any(key in value for key in (enum_value, venue, venue.upper())):
                return True
        elif isinstance(value, (set, list, tuple)):
            if any(item in value for item in (enum_value, venue, venue.upper(), broker)):
                return True
    return _connected(broker)


def evaluate_venue(
    venue: str,
    broker_module: Optional[ModuleType],
    manager: Any,
) -> VenueReadiness:
    credentials, credential_reason = _credentials_loaded(venue)
    activation = str(
        os.getenv(f"NIJA_{venue.upper()}_ACTIVATION_STATE", "") or ""
    ).strip().lower()
    broker = (
        _broker(manager, broker_module, venue)
        if broker_module is not None and manager is not None
        else None
    )
    connected = _connected(broker)
    balance_ok, spendable, balance_reason = _balance(broker)
    market_ok, market_count, market_reason = _markets(broker)
    adapter_ok = _adapter_ready(broker)

    if venue == "kraken":
        marked_ready = connected and balance_ok and spendable > 0
    else:
        marked_ready = activation == "ready" and _truthy(
            f"NIJA_{venue.upper()}_TRADING_READY"
        )
        if activation == "ready" and market_count is None:
            market_ok = True
            market_reason = "activation_ready:adapter_managed"

    eligible = bool(
        credentials
        and connected
        and balance_ok
        and spendable > 0
        and market_ok
        and adapter_ok
        and marked_ready
        and broker_module is not None
        and manager is not None
        and _manager_marks_eligible(manager, broker_module, venue, broker)
    )

    reasons = [
        reason
        for reason in (
            credential_reason,
            balance_reason if not balance_ok else "",
            market_reason if not market_ok else "",
        )
        if reason
    ]
    if not connected:
        reasons.append("not_connected")
    if balance_ok and spendable <= 0:
        reasons.append("no_spendable_quote")
    if not adapter_ok:
        reasons.append("order_adapter_missing")
    if not marked_ready:
        reasons.append(f"activation={activation or 'not_ready'}")
    if not eligible:
        reasons.append("not_execution_eligible")

    return VenueReadiness(
        venue=venue,
        credentials_loaded=credentials,
        authentication_succeeded=connected,
        balance_fetched=balance_ok and spendable > 0,
        market_metadata_loaded=market_ok,
        order_adapter_initialized=adapter_ok,
        venue_marked_ready=marked_ready,
        eligible_for_execution=eligible,
        connected=connected,
        spendable_quote=spendable,
        market_count=market_count,
        activation_state=activation or "unknown",
        reason=";".join(dict.fromkeys(reasons)) or "ready",
    )


def evaluate_all() -> dict[str, Any]:
    broker_module, manager = _runtime()
    rows = [evaluate_venue(name, broker_module, manager) for name in VENUES]
    ready_venues = [row.venue for row in rows if row.ready]
    degraded_venues = [row.venue for row in rows if not row.ready]
    writer_ready = _truthy("NIJA_WRITER_LEASE_ACQUIRED") and bool(
        os.getenv("NIJA_WRITER_FENCING_TOKEN", "").strip()
    )
    capital_ready = (
        _truthy("CAPITAL_SYSTEM_READY")
        or _truthy("NIJA_CAPITAL_READY")
        or str(os.getenv("NIJA_RUNTIME_TRADING_STATE", "")).strip() == "LIVE_ACTIVE"
    )
    any_venue_ready = bool(ready_venues)
    all_venues_ready = len(ready_venues) == len(VENUES)
    execution_ready = writer_ready and capital_ready and any_venue_ready

    return {
        "marker": MARKER,
        "timestamp": time.time(),
        "pid": os.getpid(),
        "writer_ready": writer_ready,
        "capital_ready": capital_ready,
        "any_venue_ready": any_venue_ready,
        "all_venues_ready": all_venues_ready,
        "execution_ready": execution_ready,
        # Backward-compatible legacy key. It no longer requires all three venues.
        "three_venue_execution_ready": execution_ready,
        "ready_venues": ready_venues,
        "degraded_venues": degraded_venues,
        "venues": {
            row.venue: {**asdict(row), "ready": row.ready}
            for row in rows
        },
    }


def _write_state(payload: dict[str, Any]) -> None:
    _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=_STATE_FILE.name + ".",
        dir=str(_STATE_FILE.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, _STATE_FILE)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass


def publish_once(*, force: bool = False) -> dict[str, Any]:
    global _LAST_SIGNATURE

    payload = evaluate_all()
    enabled = payload["execution_ready"]
    ready_csv = ",".join(payload["ready_venues"])
    degraded_csv = ",".join(payload["degraded_venues"])

    # Retain the old flag for compatibility, but give it broker-independent
    # semantics: at least one venue is ready under valid writer/capital authority.
    os.environ["NIJA_THREE_VENUE_EXECUTION_READY"] = "1" if enabled else "0"
    os.environ["NIJA_ANY_VENUE_EXECUTION_READY"] = "1" if enabled else "0"
    os.environ["NIJA_EXECUTION_READY_VENUES"] = ready_csv
    os.environ["NIJA_EXECUTION_DEGRADED_VENUES"] = degraded_csv
    os.environ["NIJA_THREE_VENUE_STAGE_VERIFIER_MARKER"] = MARKER
    _write_state(payload)

    signature = json.dumps(
        {
            "writer": payload["writer_ready"],
            "capital": payload["capital_ready"],
            "venues": payload["venues"],
        },
        sort_keys=True,
    )
    if force or signature != _LAST_SIGNATURE:
        _LAST_SIGNATURE = signature
        for venue in VENUES:
            item = payload["venues"][venue]
            logger.warning(
                "THREE_VENUE_STAGE venue=%s credentials=%s authentication=%s "
                "balance=%s markets=%s adapter=%s marked_ready=%s eligible=%s "
                "spendable=%.2f activation=%s reason=%s marker=%s",
                venue,
                item["credentials_loaded"],
                item["authentication_succeeded"],
                item["balance_fetched"],
                item["market_metadata_loaded"],
                item["order_adapter_initialized"],
                item["venue_marked_ready"],
                item["eligible_for_execution"],
                item["spendable_quote"],
                item["activation_state"],
                item["reason"],
                MARKER,
            )

        level = logging.CRITICAL if enabled else logging.WARNING
        logger.log(
            level,
            "BROKER_INDEPENDENT_EXECUTION_%s marker=%s writer_ready=%s "
            "capital_ready=%s ready_venues=%s degraded_venues=%s "
            "all_venues_ready=%s execution_enabled=%s",
            "READY" if enabled else "WAITING",
            MARKER,
            payload["writer_ready"],
            payload["capital_ready"],
            ready_csv or "none",
            degraded_csv or "none",
            payload["all_venues_ready"],
            enabled,
        )
        # Keep the historic summary marker for dashboards that parse it.
        logger.log(
            level,
            "THREE_VENUE_EXECUTION_%s marker=%s writer_ready=%s "
            "capital_ready=%s kraken=%s coinbase=%s okx=%s "
            "execution_enabled=%s mode=independent_any_ready",
            "READY" if enabled else "WAITING",
            MARKER,
            payload["writer_ready"],
            payload["capital_ready"],
            payload["venues"]["kraken"]["ready"],
            payload["venues"]["coinbase"]["ready"],
            payload["venues"]["okx"]["ready"],
            enabled,
        )
    return payload


def _monitor() -> None:
    interval = max(
        2.0,
        float(os.getenv("NIJA_THREE_VENUE_VERIFY_INTERVAL_S", "5") or 5),
    )
    while True:
        try:
            publish_once()
        except Exception as exc:
            os.environ["NIJA_THREE_VENUE_EXECUTION_READY"] = "0"
            os.environ["NIJA_ANY_VENUE_EXECUTION_READY"] = "0"
            os.environ["NIJA_EXECUTION_READY_VENUES"] = ""
            logger.exception(
                "THREE_VENUE_EXECUTION_VERIFIER_ERROR marker=%s error=%s",
                MARKER,
                exc,
            )
        time.sleep(interval)


def install() -> None:
    global _INSTALLED
    with _LOCK:
        if _INSTALLED:
            return
        _INSTALLED = True
        os.environ["NIJA_THREE_VENUE_EXECUTION_READY"] = "0"
        os.environ["NIJA_ANY_VENUE_EXECUTION_READY"] = "0"
        os.environ["NIJA_EXECUTION_READY_VENUES"] = ""
        os.environ["NIJA_EXECUTION_DEGRADED_VENUES"] = ",".join(VENUES)
        thread = threading.Thread(
            target=_monitor,
            name="three-venue-execution-readiness",
            daemon=True,
        )
        thread.start()
        logger.warning(
            "THREE_VENUE_EXECUTION_VERIFIER_INSTALLED marker=%s "
            "thread_alive=%s mode=independent_any_ready fail_closed_per_venue=true",
            MARKER,
            thread.is_alive(),
        )


__all__ = [
    "MARKER",
    "STAGES",
    "VENUES",
    "VenueReadiness",
    "evaluate_venue",
    "evaluate_all",
    "publish_once",
    "install",
]
