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
import importlib
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


def _float_env(name: str, default: float = 0.0) -> float:
    try:
        return float(os.getenv(name, default) or default)
    except (TypeError, ValueError):
        return default


def _writer_core_loop_alive() -> bool:
    raw = str(os.getenv("NIJA_CORE_THREAD_ALIVE", "") or "").strip().lower()
    if raw:
        return raw in {"1", "true", "yes", "on", "enabled", "y"}
    try:
        try:
            module = importlib.import_module("bot.entrypoint_writer_authority")
        except ImportError:
            module = importlib.import_module("entrypoint_writer_authority")
        runtime = getattr(module, "_SINGLETON", None)
        thread = getattr(runtime, "_core_thread", None)
        is_alive = getattr(thread, "is_alive", None)
        alive = bool(is_alive()) if callable(is_alive) else False
        if alive:
            os.environ["NIJA_CORE_THREAD_ALIVE"] = "1"
        return alive
    except Exception:
        return False


def writer_authority_snapshot(*, now: float | None = None) -> dict[str, Any]:
    try:
        from bot.writer_authority import WriterAuthority
    except ImportError:
        from writer_authority import WriterAuthority  # type: ignore[import]
    status = WriterAuthority.get_status(
        force_refresh=False,
        enforce_active_invariant=False,
    )
    current = time.time() if now is None else now
    heartbeat_alive_ts = _float_env("NIJA_WRITER_HEARTBEAT_ALIVE_TS", 0.0)
    heartbeat_max_age_s = max(
        5.0,
        _float_env("NIJA_RUNTIME_AUTHORITY_CONVERGENCE_HEARTBEAT_MAX_AGE_S", 90.0),
    )
    heartbeat_age_s = (
        max(0.0, current - heartbeat_alive_ts) if heartbeat_alive_ts > 0.0 else float("inf")
    )
    writer_state = status.state
    state_allows_execution = writer_state in {"ACTIVE", "REFRESHING"}
    checks = status.checks
    core_loop_alive = _writer_core_loop_alive()
    heartbeat_active = bool(checks.get("heartbeat_active", _truthy("NIJA_WRITER_HEARTBEAT_ACTIVE")))
    heartbeat_healthy = heartbeat_active and heartbeat_age_s <= heartbeat_max_age_s
    lease_effective = bool(checks.get("lease_acquired", _truthy("NIJA_WRITER_LEASE_ACQUIRED")))
    fencing_token = bool(
        checks.get(
            "fencing_token_active",
            bool(str(os.getenv("NIJA_WRITER_FENCING_TOKEN", "") or "").strip()),
        )
    )
    heartbeat_effective = bool(heartbeat_healthy or writer_state == "REFRESHING")
    # writer_lease_ready: does this process own the canonical Redis writer lease?
    # This is TRUE as soon as the lease + heartbeat + fencing are confirmed.
    # It must NOT require the core thread to be alive — the writer lease is
    # valid from the moment it is acquired, which happens BEFORE the core is
    # started (spec item AX).
    writer_lease_ready = bool(
        status.ready
        and state_allows_execution
        and lease_effective
        and fencing_token
        and heartbeat_effective
    )
    # strict_ready (legacy: previously required core_loop_alive) is kept for
    # backward compatibility but now equals writer_lease_ready.  Callers that
    # need core readiness must check core_loop_alive separately.
    strict_ready = writer_lease_ready
    return {
        "lease_acquired": lease_effective,
        "lease_acquired_raw": _truthy("NIJA_WRITER_LEASE_ACQUIRED"),
        "fencing_token": fencing_token,
        "writer_state": writer_state or "UNKNOWN",
        "state_allows_execution": state_allows_execution,
        "heartbeat_active": heartbeat_active,
        "heartbeat_alive_ts": heartbeat_alive_ts,
        "heartbeat_age_s": heartbeat_age_s,
        "heartbeat_max_age_s": heartbeat_max_age_s,
        "heartbeat_healthy": heartbeat_healthy,
        "heartbeat_effective": heartbeat_effective,
        "core_loop_alive": core_loop_alive,
        # Granular writer readiness fields (spec item AX):
        "writer_lease_ready": writer_lease_ready,
        "writer_heartbeat_ready": heartbeat_healthy,
        "writer_generation_ready": bool(
            str(os.getenv("NIJA_WRITER_LEASE_GENERATION", "") or "").strip()
        ),
        "core_thread_ready": core_loop_alive,
        "authority_verified": bool(checks.get("authority_verified", False)),
        "redis_reachable": bool(checks.get("redis_reachable", False)),
        "checks": checks,
        "missing": list(status.missing),
        "source": status.source,
        "reason": status.reason,
        "ready": strict_ready,
    }


def writer_authority_ready(*, now: float | None = None) -> bool:
    return bool(writer_authority_snapshot(now=now)["ready"])


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
    """Resolve a platform broker from the canonical manager registry only.

    Compatibility imports can create a BrokerType enum with different object
    identity.  Direct ``mapping.get(enum_value)`` then misses the real registry
    entry and the historical fallback returned a broker from a second global
    registry.  That produced contradictory reports such as Kraken platform
    connected in this observer but disconnected in the account registry.
    """

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
            for key, value in mapping.items():
                label = str(getattr(key, "value", key) or "").strip().lower()
                if label == venue and value is not None:
                    return value
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


def _okx_authenticated_spendable(broker: Any) -> float:
    if (
        broker is None
        or not _connected(broker)
        or not _truthy("NIJA_OKX_BALANCE_OBSERVED")
        or str(os.getenv("NIJA_OKX_FUNDING_STATUS", "") or "").strip().lower() != "funded"
    ):
        return 0.0
    candidates: list[float] = []
    for value in (
        getattr(broker, "_okx_trading_spendable_quote", None),
        os.getenv("NIJA_OKX_TRADING_SPENDABLE_QUOTE"),
        os.getenv("NIJA_OKX_SPENDABLE_QUOTE"),
    ):
        try:
            candidates.append(max(0.0, float(value or 0.0)))
        except (TypeError, ValueError, OverflowError):
            continue
    return max(candidates, default=0.0)


def _balance(venue: str, broker: Any) -> tuple[bool, float, str]:
    if broker is None:
        return False, 0.0, "broker_missing"

    # Consume the authenticated OKX snapshot before invoking another private
    # balance request. The proof is valid only while the broker is connected and
    # the observer reports a funded Trading wallet.
    if venue == "okx":
        spendable = _okx_authenticated_spendable(broker)
        if spendable > 0.0:
            return True, spendable, "okx_authenticated_wallet"

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
    balance_ok, spendable, balance_reason = _balance(venue, broker)
    market_ok, market_count, market_reason = _markets(broker)
    adapter_ok = _adapter_ready(broker)
    authenticated_okx_wallet_ready = (
        venue == "okx"
        and connected
        and balance_ok
        and spendable > 0.0
        and balance_reason == "okx_authenticated_wallet"
    )

    if venue == "kraken":
        marked_ready = connected and balance_ok and spendable > 0
    else:
        marked_ready = activation == "ready" and _truthy(
            f"NIJA_{venue.upper()}_TRADING_READY"
        )
        if authenticated_okx_wallet_ready:
            marked_ready = True
            activation = "ready"
            os.environ["NIJA_OKX_ACTIVATION_STATE"] = "ready"
            os.environ["NIJA_OKX_TRADING_READY"] = "1"
            os.environ["NIJA_OKX_ACTIVATED"] = "1"
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

    # Kraken is the primary venue and has no secondary-activation handshake.
    # Its activation state is therefore derived from the same complete,
    # fail-closed stage contract used to determine execution eligibility.
    if venue == "kraken":
        activation = "ready" if eligible else "not_ready"

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
    try:
        from bot.writer_authority import WriterAuthority
    except ImportError:
        from writer_authority import WriterAuthority  # type: ignore[import]
    WriterAuthority.get_status(force_refresh=False, enforce_active_invariant=True)
    broker_module, manager = _runtime()
    rows = [evaluate_venue(name, broker_module, manager) for name in VENUES]
    ready_venues = [row.venue for row in rows if row.ready]
    degraded_venues = [row.venue for row in rows if not row.ready]
    writer_state = writer_authority_snapshot()
    writer_ready = bool(writer_state["ready"])
    capital_ready = _capital_ready()
    any_venue_ready = bool(ready_venues)
    all_venues_ready = len(ready_venues) == len(VENUES)
    execution_ready = writer_ready and capital_ready and any_venue_ready

    return {
        "marker": MARKER,
        "timestamp": time.time(),
        "pid": os.getpid(),
        "writer_ready": writer_ready,
        "writer_state": writer_state,
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

    # Export the already-verified Kraken free quote snapshot for broker-independent
    # readiness/diagnostics. This is telemetry only: no additional private Kraken
    # request is made here and this value does not grant execution readiness.
    try:
        kraken_spendable = max(
            0.0,
            float(payload["venues"]["kraken"].get("spendable_quote", 0.0) or 0.0),
        )
    except (TypeError, ValueError, OverflowError, KeyError):
        kraken_spendable = 0.0
    os.environ["NIJA_KRAKEN_SPENDABLE_QUOTE"] = f"{kraken_spendable:.8f}"

    kraken_ready = bool(payload["venues"]["kraken"]["ready"])
    os.environ["NIJA_KRAKEN_ACTIVATION_STATE"] = "ready" if kraken_ready else "not_ready"
    os.environ["NIJA_KRAKEN_TRADING_READY"] = "1" if kraken_ready else "0"
    os.environ["NIJA_KRAKEN_ACTIVATED"] = "1" if kraken_ready else "0"
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


def reconcile_execution_readiness(*, trigger: str = "manual", force: bool = False) -> dict[str, Any]:
    payload = publish_once(force=force)
    runtime_enabled = _truthy("NIJA_RUNTIME_EXECUTION_AUTHORITY")
    if (
        payload["writer_ready"]
        and payload["capital_ready"]
        and payload["any_venue_ready"]
        and not runtime_enabled
    ):
        state = payload.get("writer_state", {})
        logger.critical(
            "WRITER_AUTHORITY_STATE_MACHINE_BUG marker=%s trigger=%s "
            "lease=%s token=%s heartbeat_healthy=%s core_loop_alive=%s "
            "capital_ready=%s ready_venues=%s runtime_execution_authority=%s auto_repair=true",
            MARKER,
            trigger,
            state.get("lease_acquired"),
            state.get("fencing_token"),
            state.get("heartbeat_healthy"),
            state.get("core_loop_alive"),
            payload["capital_ready"],
            ",".join(payload["ready_venues"]) or "none",
            runtime_enabled,
        )
    if payload["writer_ready"]:
        try:
            repair = importlib.import_module("bot.runtime_authority_convergence_repair_patch")
        except ImportError:
            try:
                repair = importlib.import_module("runtime_authority_convergence_repair_patch")
            except ImportError:
                return payload
        converge = getattr(repair, "converge_runtime_authority", None)
        if callable(converge):
            try:
                converge(f"three_venue_execution_readiness:{trigger}")
            except Exception:
                logger.exception(
                    "THREE_VENUE_EXECUTION_RECONCILE_FAILED marker=%s trigger=%s",
                    MARKER,
                    trigger,
                )
    return payload


def _monitor() -> None:
    interval = max(
        2.0,
        float(os.getenv("NIJA_THREE_VENUE_VERIFY_INTERVAL_S", "5") or 5),
    )
    while True:
        try:
            reconcile_execution_readiness(trigger="monitor")
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
    "writer_authority_snapshot",
    "writer_authority_ready",
    "evaluate_venue",
    "evaluate_all",
    "publish_once",
    "reconcile_execution_readiness",
    "install",
]
