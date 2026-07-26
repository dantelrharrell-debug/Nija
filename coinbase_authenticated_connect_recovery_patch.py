"""Recover false-negative Coinbase connect results with an authenticated account probe.

The patch never marks Coinbase connected from credential shape, public products, cached
balances, or environment flags alone.  A failed/falsey connect is upgraded only when a
private account endpoint succeeds on the broker or its authenticated SDK client.
"""
from __future__ import annotations

import hashlib
import importlib
import logging
import os
import sys
import threading
import time
import weakref
from functools import wraps
from types import ModuleType
from typing import Any, Mapping, Sequence

logger = logging.getLogger("nija.coinbase_authenticated_connect_recovery")
_MARKER = "20260726-coinbase-canonical-client-v4"
_PATCH_ATTR = "_nija_coinbase_authenticated_connect_v1"
_LOCK = threading.RLock()
_STARTED = False
_LAST_FAILURE: dict[str, float] = {}
_FAILED_PAIR_AT: dict[str, float] = {}
_PAIR_RETRY_COOLDOWN_S = 300.0
_CANONICAL_BROKERS: dict[str, weakref.ReferenceType[Any]] = {}


def _is_coinbase_class(cls: type) -> bool:
    return "coinbase" in cls.__name__.lower()


def _wrapper_chain_has_patch(current: Any) -> bool:
    """Return True when this recovery already exists anywhere in the chain."""
    seen: set[int] = set()
    candidate = current
    while callable(candidate) and id(candidate) not in seen:
        seen.add(id(candidate))
        if bool(getattr(candidate, _PATCH_ATTR, False)):
            return True
        candidate = getattr(candidate, "__wrapped__", None)
    return False


def _clients(broker: Any) -> list[Any]:
    found: list[Any] = []
    for attr in ("client", "api_client", "rest_client", "coinbase_client", "_client", "_api_client"):
        try:
            value = getattr(broker, attr, None)
        except Exception:
            value = None
        if value is not None and value not in found:
            found.append(value)
    found.insert(0, broker)
    return found


def _account_scope(broker: Any) -> str:
    """Return a stable account key so clients never cross account boundaries."""
    targets = _credential_targets(broker)
    target = targets[-1]
    account_type = getattr(target, "account_type", None)
    account_value = str(getattr(account_type, "value", account_type) or "platform").lower()
    if account_value.endswith(".platform"):
        account_value = "platform"
    elif account_value.endswith(".user"):
        account_value = "user"
    user_id = str(getattr(target, "user_id", "") or "").strip().lower()
    return f"{account_value}:{user_id}" if user_id else account_value


def _client_target(broker: Any) -> Any | None:
    """Find the concrete broker object that owns an authenticated SDK client."""
    for target in reversed(_credential_targets(broker)):
        client = getattr(target, "client", None)
        if (
            client is not None
            and not bool(getattr(target, "_auth_failed", False))
            and not bool(getattr(target, "auth_failed", False))
        ):
            return target
    return None


def _remember_canonical(broker: Any) -> Any | None:
    """Record and publish the verified concrete broker for its account scope."""
    target = _client_target(broker)
    if target is None:
        return None
    scope = _account_scope(target)
    with _LOCK:
        _CANONICAL_BROKERS[scope] = weakref.ref(target)

    manager = getattr(target, "_connection_stability_manager", None)
    register = getattr(manager, "register_broker", None)
    reconnect = getattr(target, "connect", None)
    if callable(register) and callable(reconnect):
        try:
            register(
                broker=target,
                reconnect_fn=reconnect,
                replace_existing=True,
            )
        except TypeError:
            # Compatibility with a lightweight/legacy manager that predates
            # explicit replacement.  The broker remains canonical locally.
            pass
        except Exception:
            logger.debug(
                "COINBASE_CANONICAL_WATCHDOG_REBIND_PENDING marker=%s scope=%s",
                _MARKER,
                scope,
            )

    if scope == "platform":
        try:
            manager_module = importlib.import_module("bot.broker_manager")
            register_platform = getattr(manager_module, "register_platform_broker", None)
            if callable(register_platform):
                register_platform("coinbase", target, connected=True)
        except Exception:
            logger.debug(
                "COINBASE_CANONICAL_PLATFORM_REGISTRY_PENDING marker=%s",
                _MARKER,
            )
    return target


def _canonical_for(broker: Any) -> Any | None:
    scope = _account_scope(broker)
    with _LOCK:
        reference = _CANONICAL_BROKERS.get(scope)
        target = reference() if reference is not None else None
        if reference is not None and target is None:
            _CANONICAL_BROKERS.pop(scope, None)
    if target is None and scope == "platform":
        try:
            manager_module = importlib.import_module("bot.broker_manager")
            getter = getattr(manager_module, "get_platform_broker", None)
            target = getter("coinbase") if callable(getter) else None
        except Exception:
            target = None
    if target is None or target is broker:
        return None
    if _client_target(target) is None or not bool(getattr(target, "connected", False)):
        return None
    return target


def adopt_canonical_client(broker: Any) -> bool:
    """Adopt a verified client from the same account's canonical broker.

    This repairs duplicate/stale runtime objects without converting missing
    transport state into authentication success.  Platform and user clients
    are never shared, and different users are isolated by ``user_id``.
    """
    if _client_target(broker) is not None:
        return True
    canonical = _canonical_for(broker)
    if canonical is None:
        return False
    source = _client_target(canonical)
    if source is None:
        return False

    client = getattr(source, "client", None)
    if client is None:
        return False
    for target in _credential_targets(broker):
        try:
            target.client = client
            target.connected = True
            target._auth_failed = False
            target._is_available = True
        except Exception:
            pass
        for attr in (
            "_accounts_cache",
            "_accounts_cache_time",
            "_balance_cache",
            "_balance_cache_time",
            "_last_known_balance",
            "_balance_last_updated",
            "portfolio_uuid",
        ):
            try:
                if hasattr(source, attr) and hasattr(target, attr):
                    setattr(target, attr, getattr(source, attr))
            except Exception:
                pass
    logger.warning(
        "COINBASE_CANONICAL_CLIENT_ADOPTED marker=%s scope=%s target=%s source=%s",
        _MARKER,
        _account_scope(broker),
        type(broker).__name__,
        type(source).__name__,
    )
    return True


def _forget_canonical(broker: Any) -> None:
    scope = _account_scope(broker)
    with _LOCK:
        _CANONICAL_BROKERS.pop(scope, None)


def _payload_success(payload: Any) -> bool:
    # A successful private endpoint may legitimately return an empty account list.
    if payload is None or payload is False:
        return False
    if isinstance(payload, Mapping):
        error = payload.get("error") or payload.get("errors")
        if error:
            return False
        return True
    if isinstance(payload, Sequence) and not isinstance(payload, (str, bytes, bytearray)):
        return True
    # Coinbase SDK response objects are valid even when their accounts collection is empty.
    return hasattr(payload, "accounts") or hasattr(payload, "to_dict") or bool(payload)


def _authenticated_probe(broker: Any) -> tuple[bool, str]:
    errors: list[str] = []
    for target in _clients(broker):
        for method_name in ("get_accounts", "list_accounts", "fetch_accounts"):
            method = getattr(target, method_name, None)
            if not callable(method):
                continue
            try:
                payload = method()
            except TypeError:
                continue
            except Exception as exc:
                errors.append(f"{type(target).__name__}.{method_name}:{type(exc).__name__}:{str(exc)[:100]}")
                continue
            if _payload_success(payload):
                return True, f"{type(target).__name__}.{method_name}"
            errors.append(f"{type(target).__name__}.{method_name}:falsey_payload")
    return False, ";".join(errors[-3:]) or "private_account_method_unavailable"


def _measure_spendable(broker: Any) -> float:
    try:
        helper = importlib.import_module("bot.coinbase_funding_readiness_repair_patch")
        measure = getattr(helper, "_measure_spendable", None)
        if callable(measure):
            return max(0.0, float(measure(broker) or 0.0))
    except Exception:
        pass
    return 0.0


def _publish_connected(broker: Any, source: str) -> None:
    _remember_canonical(broker)
    for target in _credential_targets(broker):
        for attr, value in (
            ("connected", True),
            ("_auth_failed", False),
            ("auth_failed", False),
            ("_is_available", True),
            ("_balance_fetch_errors", 0),
        ):
            try:
                if hasattr(target, attr) or attr in {"connected", "_auth_failed"}:
                    setattr(target, attr, value)
            except Exception:
                pass
        manager = getattr(target, "_connection_stability_manager", None)
        mark_connected = getattr(manager, "mark_connected", None)
        if callable(mark_connected):
            try:
                mark_connected()
            except Exception:
                pass
    spendable = _measure_spendable(broker)
    os.environ["NIJA_COINBASE_CREDENTIALS_QUARANTINED"] = "0"
    os.environ["NIJA_COINBASE_RECONNECT_DISABLED"] = "0"
    os.environ.pop("NIJA_COINBASE_QUARANTINED_CREDENTIAL_FINGERPRINT", None)
    os.environ["NIJA_COINBASE_CONNECTED"] = "1"
    os.environ["NIJA_COINBASE_BALANCE_OBSERVED"] = "1"
    os.environ["NIJA_COINBASE_SPENDABLE_QUOTE"] = f"{spendable:.8f}"
    os.environ["NIJA_COINBASE_FUNDING_STATUS"] = "funded" if spendable > 0 else "observed_zero"
    os.environ["NIJA_COINBASE_TRADING_READY"] = "1" if spendable > 0 else "0"
    os.environ["NIJA_COINBASE_ACTIVATED"] = "1"
    os.environ["NIJA_COINBASE_ACTIVATION_STATE"] = "ready" if spendable > 0 else "connected_unfunded"
    logger.critical(
        "COINBASE_AUTHENTICATED_CONNECT_RECOVERED marker=%s source=%s spendable=$%.2f",
        _MARKER, source, spendable,
    )


def _log_failure_once(cls: type, detail: str) -> None:
    key = cls.__module__ + "." + cls.__name__ + ":" + detail
    now = time.monotonic()
    if now - _LAST_FAILURE.get(key, 0.0) < 60.0:
        return
    _LAST_FAILURE[key] = now
    logger.error(
        "COINBASE_AUTHENTICATED_CONNECT_FAILED marker=%s class=%s detail=%s",
        _MARKER, cls.__name__, detail[:300],
    )


def _configured_pairs() -> list[tuple[str, str, str]]:
    try:
        diagnostics = importlib.import_module("secondary_venue_runtime_diagnostics")
        discover = getattr(diagnostics, "_configured_coinbase_pairs", None)
        if callable(discover):
            return list(discover())
    except Exception as exc:
        logger.debug(
            "COINBASE_CREDENTIAL_PAIR_DISCOVERY_PENDING marker=%s error=%s",
            _MARKER,
            type(exc).__name__,
        )
    return []


def _pair_fingerprint(key: str, secret: str) -> str:
    return hashlib.sha256((key + "\0" + secret).encode("utf-8")).hexdigest()[:16]


def _credential_targets(broker: Any) -> list[Any]:
    targets = [broker]
    try:
        nested = getattr(broker, "_broker", None)
    except Exception:
        nested = None
    if nested is not None and nested not in targets:
        targets.append(nested)
    return targets


def _apply_pair(
    broker: Any,
    source: str,
    key: str,
    secret: str,
    *,
    reset_failure: bool = True,
) -> None:
    os.environ["COINBASE_API_KEY"] = key
    os.environ["COINBASE_API_SECRET"] = secret
    os.environ["COINBASE_PEM_CONTENT"] = secret
    os.environ["NIJA_COINBASE_CREDENTIAL_PAIR_SOURCE"] = source
    for target in _credential_targets(broker):
        for attr, value in (
            ("api_key", key),
            ("api_secret", secret),
            ("secret", secret),
            ("private_key", secret),
        ):
            try:
                if hasattr(target, attr):
                    setattr(target, attr, value)
            except Exception:
                pass
        if reset_failure:
            for attr, value in (
                ("connected", False),
                ("client", None),
                ("api_client", None),
                ("rest_client", None),
                ("coinbase_client", None),
                ("_client", None),
                ("_api_client", None),
                ("_auth_failed", False),
                ("auth_failed", False),
                ("_is_available", True),
                ("_accounts_cache", None),
                ("_accounts_cache_time", None),
                ("_balance_cache", None),
                ("_balance_cache_time", None),
            ):
                try:
                    if hasattr(target, attr) or attr in {"connected", "client", "_auth_failed"}:
                        setattr(target, attr, value)
                except Exception:
                    pass


def _mark_auth_failed(broker: Any) -> None:
    for target in _credential_targets(broker):
        for attr, value in (
            ("connected", False),
            ("_auth_failed", True),
            ("auth_failed", True),
            ("_is_available", False),
        ):
            try:
                if hasattr(target, attr) or attr in {"connected", "_auth_failed"}:
                    setattr(target, attr, value)
            except Exception:
                pass


def _mark_connectivity_failed(broker: Any) -> None:
    """Keep the venue fail-closed while allowing authenticated reconnects."""
    for target in _credential_targets(broker):
        for attr, value in (
            ("connected", False),
            ("_auth_failed", False),
            ("auth_failed", False),
            ("_is_available", False),
        ):
            try:
                if hasattr(target, attr) or attr in {"connected", "_auth_failed"}:
                    setattr(target, attr, value)
            except Exception:
                pass
        manager = getattr(target, "_connection_stability_manager", None)
        mark_disconnected = getattr(manager, "mark_disconnected", None)
        if callable(mark_disconnected):
            try:
                mark_disconnected("coinbase_authenticated_reconnect_pending")
            except Exception:
                pass


def _flag(name: str) -> bool:
    return str(os.environ.get(name, "") or "").strip().lower() in {
        "1", "true", "yes", "on", "enabled",
    }


def _quarantined_for(key: str, secret: str) -> bool:
    if not _flag("NIJA_COINBASE_CREDENTIALS_QUARANTINED"):
        return False
    pinned = str(
        os.environ.get("NIJA_COINBASE_QUARANTINED_CREDENTIAL_FINGERPRINT", "") or ""
    )
    current = _pair_fingerprint(key, secret) if key and secret else ""
    if pinned and current and current != pinned:
        # A credential rotation is the only automatic release. The new pair must
        # still pass the private account probe before becoming connected.
        os.environ["NIJA_COINBASE_CREDENTIALS_QUARANTINED"] = "0"
        os.environ["NIJA_COINBASE_RECONNECT_DISABLED"] = "0"
        os.environ.pop("NIJA_COINBASE_QUARANTINED_CREDENTIAL_FINGERPRINT", None)
        return False
    return True


def _auth_failure_detail(detail: str) -> bool:
    value = str(detail or "").lower()
    return any(
        token in value
        for token in ("401", "unauthorized", "invalid api key", "invalid_api_key")
    )


def _quarantine(broker: Any, key: str, secret: str) -> None:
    _forget_canonical(broker)
    _mark_auth_failed(broker)
    fingerprint = _pair_fingerprint(key, secret) if key and secret else ""
    os.environ["NIJA_COINBASE_CREDENTIALS_QUARANTINED"] = "1"
    os.environ["NIJA_COINBASE_RECONNECT_DISABLED"] = "1"
    if fingerprint:
        os.environ["NIJA_COINBASE_QUARANTINED_CREDENTIAL_FINGERPRINT"] = fingerprint
    os.environ["NIJA_COINBASE_CONNECTED"] = "0"
    os.environ["NIJA_COINBASE_BALANCE_OBSERVED"] = "0"
    os.environ["NIJA_COINBASE_SPENDABLE_QUOTE"] = "0.00000000"
    os.environ["NIJA_COINBASE_TRADING_READY"] = "0"
    os.environ["NIJA_COINBASE_ACTIVATED"] = "0"
    os.environ["NIJA_COINBASE_ACTIVATION_STATE"] = "quarantined"


def _patch_class(cls: type) -> bool:
    if not _is_coinbase_class(cls):
        return False
    current = getattr(cls, "connect", None)
    if not callable(current) or _wrapper_chain_has_patch(current):
        return bool(callable(current) and _wrapper_chain_has_patch(current))

    @wraps(current)
    def connect(self: Any, *args: Any, **kwargs: Any):
        primary_key = str(os.environ.get("COINBASE_API_KEY", "") or "")
        primary_secret = str(
            os.environ.get("COINBASE_API_SECRET", "")
            or os.environ.get("COINBASE_PEM_CONTENT", "")
            or ""
        )
        primary_source = str(
            os.environ.get("NIJA_COINBASE_CREDENTIAL_PAIR_SOURCE", "canonical")
            or "canonical"
        )

        if _quarantined_for(primary_key, primary_secret):
            _mark_auth_failed(self)
            os.environ["NIJA_COINBASE_CONNECTED"] = "0"
            os.environ["NIJA_COINBASE_TRADING_READY"] = "0"
            os.environ["NIJA_COINBASE_ACTIVATION_STATE"] = "quarantined"
            return False

        # Rebuild the authenticated SDK client on every disconnected retry, or
        # when the client is absent despite connected=True.  A None client with
        # connected=True is an inconsistent state: the broker must re-authenticate
        # before recovery is declared; cached balances must not bypass this check.
        # Adapters own their concrete broker in ``_broker`` and intentionally
        # have no direct ``client`` attribute.  Inspect the full credential
        # target chain so an adapter reconnect cannot clear a healthy nested
        # client.
        _client_missing = _client_target(self) is None
        if _client_missing:
            adopt_canonical_client(self)
            _client_missing = _client_target(self) is None
        # Only clear credentials/client state when the complete adapter/broker
        # chain truly has no client.  An adapter's own ``connected`` flag may
        # still be False while its nested canonical broker is already healthy;
        # resetting on that flag would destroy the authenticated client just
        # before the adapter reuses it.
        if primary_key and primary_secret and _client_missing:
            _apply_pair(
                self,
                primary_source,
                primary_key,
                primary_secret,
                reset_failure=True,
            )

        first_error = ""
        try:
            result = current(self, *args, **kwargs)
        except Exception as exc:
            result = False
            first_error = f"{type(exc).__name__}:{str(exc)[:100]}"

        if (
            bool(result) or bool(getattr(self, "connected", False))
        ) and _client_target(self) is not None:
            _publish_connected(self, "connect_result")
            return True
        authenticated, detail = _authenticated_probe(self)
        if authenticated:
            _publish_connected(self, detail)
            return True

        primary_fp = (
            _pair_fingerprint(primary_key, primary_secret)
            if primary_key and primary_secret
            else ""
        )
        now = time.monotonic()
        attempted = 0
        failure_details = [value for value in (first_error, detail) if value]

        for source, key, secret in _configured_pairs():
            fingerprint = _pair_fingerprint(key, secret)
            if fingerprint == primary_fp:
                continue
            with _LOCK:
                failed_at = _FAILED_PAIR_AT.get(fingerprint)
            if (
                failed_at is not None
                and now - failed_at < _PAIR_RETRY_COOLDOWN_S
            ):
                continue

            attempted += 1
            logger.warning(
                "COINBASE_AUTHENTICATED_PAIR_RETRY marker=%s "
                "class=%s source=%s attempt=%d",
                _MARKER,
                cls.__name__,
                source,
                attempted,
            )
            _apply_pair(self, source, key, secret)
            retry_error = ""
            try:
                retry_result = current(self, *args, **kwargs)
            except Exception as exc:
                retry_result = False
                retry_error = f"{type(exc).__name__}:{str(exc)[:100]}"

            if (
                bool(retry_result) or bool(getattr(self, "connected", False))
            ) and _client_target(self) is not None:
                _publish_connected(self, f"credential_pair:{source}")
                logger.critical(
                    "COINBASE_AUTHENTICATED_PAIR_RECOVERED marker=%s "
                    "class=%s source=%s",
                    _MARKER,
                    cls.__name__,
                    source,
                )
                return True

            authenticated, retry_detail = _authenticated_probe(self)
            if authenticated:
                _publish_connected(self, f"{source}:{retry_detail}")
                logger.critical(
                    "COINBASE_AUTHENTICATED_PAIR_RECOVERED marker=%s "
                    "class=%s source=%s",
                    _MARKER,
                    cls.__name__,
                    source,
                )
                return True

            with _LOCK:
                _FAILED_PAIR_AT[fingerprint] = time.monotonic()
            failure_details.extend(
                value for value in (retry_error, retry_detail) if value
            )

        if primary_key and primary_secret:
            _apply_pair(
                self,
                primary_source,
                primary_key,
                primary_secret,
                reset_failure=False,
            )
        suffix = ";".join(failure_details[-4:]) or "authenticated_probe_failed"
        if _auth_failure_detail(suffix):
            _quarantine(self, primary_key, primary_secret)
            state = "quarantined"
        else:
            _mark_connectivity_failed(self)
            os.environ["NIJA_COINBASE_CONNECTED"] = "0"
            os.environ["NIJA_COINBASE_BALANCE_OBSERVED"] = "0"
            os.environ["NIJA_COINBASE_SPENDABLE_QUOTE"] = "0.00000000"
            os.environ["NIJA_COINBASE_TRADING_READY"] = "0"
            os.environ["NIJA_COINBASE_ACTIVATED"] = "0"
            os.environ["NIJA_COINBASE_ACTIVATION_STATE"] = "reconnect_pending"
            state = "reconnect_pending"
        _log_failure_once(
            cls,
            f"{suffix};alternative_pairs_attempted={attempted};state={state}",
        )
        return False

    setattr(connect, _PATCH_ATTR, True)
    connect.__wrapped__ = current  # type: ignore[attr-defined]
    setattr(cls, "connect", connect)
    logger.warning(
        "COINBASE_AUTHENTICATED_CONNECT_SURFACE_PATCHED marker=%s module=%s class=%s",
        _MARKER, cls.__module__, cls.__name__,
    )
    return True

def _patch_module(module: ModuleType) -> bool:
    changed = False
    for value in vars(module).values():
        if isinstance(value, type) and _is_coinbase_class(value):
            changed = _patch_class(value) or changed
    return changed


def _patch_loaded() -> bool:
    changed = False
    for name, module in list(sys.modules.items()):
        if isinstance(module, ModuleType) and name in {
            "bot.broker_manager", "broker_manager", "bot.broker_integration", "broker_integration"
        }:
            changed = _patch_module(module) or changed
    return changed


def _watchdog() -> None:
    deadline = time.monotonic() + 240.0
    while time.monotonic() < deadline:
        try:
            _patch_loaded()
        except Exception as exc:
            logger.debug("COINBASE_AUTHENTICATED_CONNECT_RETRY marker=%s error=%s", _MARKER, exc)
        time.sleep(0.25)


def install() -> bool:
    global _STARTED
    with _LOCK:
        _patch_loaded()
        if not _STARTED:
            _STARTED = True
            threading.Thread(target=_watchdog, name="CoinbaseAuthenticatedConnectRecovery", daemon=True).start()
        os.environ["NIJA_COINBASE_AUTHENTICATED_CONNECT_RECOVERY_INSTALLED"] = "1"
        logger.critical("COINBASE_AUTHENTICATED_CONNECT_RECOVERY_INSTALLED marker=%s", _MARKER)
        return True


__all__ = [
    "install",
    "_authenticated_probe",
    "adopt_canonical_client",
    "_configured_pairs",
    "_patch_class",
    "_quarantined_for",
    "_wrapper_chain_has_patch",
]
