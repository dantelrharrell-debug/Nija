"""Authoritative position-read liveness convergence v342.

Production evidence on 2026-09-01 exposed two read-path liveness defects while
all existing fail-closed safety gates were behaving correctly:

* Coinbase ``get_positions`` obtained a genuine portfolio breakdown and then
  issued one extra market-price request per crypto asset solely to compute dust
  value.  Under the live rate limiter that N+1 pattern exceeded v117's unchanged
  12-second authoritative position timeout, so Coinbase position truth remained
  stale even though the holdings payload itself was available.
* Kraken capital/position callers could join an old credential-scoped Balance
  flight even after a newer successful authenticated same-credential Balance
  observation had been recorded by v312/v321.  The joiner then waited on the old
  flight long enough for capital and position publications to expire.

v342 removes only those redundant waits:

* Coinbase derives ``size_usd`` and an observational current price from
  ``total_balance_fiat`` / ``available_to_trade_fiat`` already returned in the
  same Advanced Trade portfolio breakdown.  It performs no per-position market
  reads.  If the portfolio endpoint is unavailable, the existing authenticated
  accounts endpoint is used without market-price fan-out; positive crypto
  balances remain visible and downstream dust/protection policy remains
  authoritative.
* A Kraken credential-flight joiner may reuse only a structurally valid,
  credential-proven, still-fresh v312 authenticated Balance observation for the
  exact same credential.  The old owner is not cancelled or force-released and
  no duplicate private request is created.

Position snapshot TTL, capital publication TTL, broker transport/rate limits,
writer/nonce/risk/kill-switch/order/fill gates, execution proof, cost-basis
requirements, and protective-exit confirmation semantics are unchanged.  No
position, balance, price, readiness state, fill, execution proof, activation, or
profit is fabricated or forced.
"""
from __future__ import annotations

import importlib
import logging
import os
import sys
import threading
import time
from collections.abc import Mapping
from functools import wraps
from types import ModuleType
from typing import Any

LOGGER = logging.getLogger("nija.runtime_position_read_liveness_v342")
MARKER = "20260901-position-read-liveness-v342"
RELEASE_ID = "20260901-runtime-convergence-v342"
_READY_FLAG = "NIJA_RUNTIME_POSITION_READ_LIVENESS_V342_READY"
_COINBASE_PATCH_ATTR = "_nija_coinbase_position_read_liveness_v342"
_KRAKEN_PATCH_ATTR = "_nija_kraken_stale_credential_flight_handoff_v342"
_LOCK = threading.RLock()
_THREAD: threading.Thread | None = None


def _number(value: Any, default: float = 0.0) -> float:
    try:
        if isinstance(value, Mapping):
            value = value.get("value", value.get("amount", default))
        elif value is not None and not isinstance(value, (str, int, float)):
            nested = getattr(value, "value", None)
            if nested is not None:
                value = nested
        parsed = float(value if value is not None else default)
        return default if parsed != parsed else parsed
    except Exception:
        return default


def _field(row: Any, name: str, default: Any = None) -> Any:
    if isinstance(row, Mapping):
        return row.get(name, default)
    return getattr(row, name, default)


def _chain_has_attr(callable_obj: Any, attr: str) -> bool:
    seen: set[int] = set()
    current = callable_obj
    for _ in range(128):
        if not callable(current) or id(current) in seen:
            return False
        seen.add(id(current))
        if bool(getattr(current, attr, False)):
            return True
        current = getattr(current, "__wrapped__", None)
    return False


def _record_v285_snapshot(broker: Any, rows: list[dict[str, Any]]) -> None:
    try:
        v285 = importlib.import_module("bot.runtime_authoritative_position_coverage_v285_patch")
        recorder = getattr(v285, "_record_snapshot_success", None)
        if callable(recorder):
            recorder(broker, list(rows))
    except Exception:
        # v285 may not be loaded yet. Later wrappers/adoption still record the
        # exact returned list; lack of this optimization never grants readiness.
        pass


def _coinbase_fast_positions(broker: Any) -> list[dict[str, Any]]:
    client = getattr(broker, "client", None)
    if client is None:
        raise RuntimeError("coinbase_client_missing")

    api_call = getattr(broker, "_api_call_with_retry", None)

    def call(fn: Any, *args: Any, **kwargs: Any) -> Any:
        if callable(api_call):
            return api_call(fn, *args, **kwargs)
        return fn(*args, **kwargs)

    dust_threshold = 1.0
    try:
        module = importlib.import_module("bot.broker_manager")
        dust_threshold = max(0.0, float(getattr(module, "DUST_THRESHOLD_USD", 1.0) or 1.0))
    except Exception:
        pass

    positions: list[dict[str, Any]] = []
    portfolio_error: BaseException | None = None
    try:
        getter = getattr(client, "get_portfolios", None)
        breakdown_getter = getattr(client, "get_portfolio_breakdown", None)
        if not callable(getter) or not callable(breakdown_getter):
            raise RuntimeError("coinbase_portfolio_api_unavailable")
        response = call(getter)
        portfolios = _field(response, "portfolios", []) or []
        default = None
        for portfolio in portfolios:
            if str(_field(portfolio, "type", "") or "").upper() == "DEFAULT":
                default = portfolio
                break
        if default is None and portfolios:
            default = portfolios[0]
        portfolio_uuid = _field(default, "uuid", None) if default is not None else None
        if not portfolio_uuid:
            raise RuntimeError("coinbase_default_portfolio_missing")

        breakdown_response = call(breakdown_getter, portfolio_uuid=portfolio_uuid)
        breakdown = _field(breakdown_response, "breakdown", None)
        spot_positions = _field(breakdown, "spot_positions", []) if breakdown is not None else []
        for position in spot_positions or []:
            asset = str(_field(position, "asset", "") or "").strip().upper()
            if not asset or asset in {"USD", "USDC"}:
                continue
            quantity = _number(_field(position, "total_balance_crypto", None))
            if quantity <= 0.0:
                quantity = _number(_field(position, "available_to_trade_crypto", None))
            if quantity <= 0.0:
                continue

            fiat_total = _number(_field(position, "total_balance_fiat", None), -1.0)
            if fiat_total < 0.0:
                fiat_total = _number(_field(position, "available_to_trade_fiat", None), -1.0)
            if fiat_total >= 0.0 and fiat_total < dust_threshold:
                continue
            price = fiat_total / quantity if fiat_total > 0.0 and quantity > 0.0 else 0.0
            positions.append({
                "symbol": f"{asset}-USD",
                "quantity": quantity,
                "currency": asset,
                "current_price": price,
                "size_usd": max(0.0, fiat_total),
            })

        LOGGER.critical(
            "COINBASE_POSITION_V342_PORTFOLIO_SNAPSHOT marker=%s positions=%d "
            "portfolio_breakdown=true per_asset_market_reads=0 fiat_valuation_reused=true "
            "authenticated_holdings=true snapshot_ttl_unchanged=true dust_policy_unchanged=true "
            "position_fabricated=false price_fabricated=false readiness_granted=false "
            "execution_proof_fabricated=false safety_gates_bypassed=false",
            MARKER,
            len(positions),
        )
        return positions
    except BaseException as exc:
        portfolio_error = exc

    # Fallback remains a genuine authenticated holdings read, but deliberately
    # avoids the old per-asset ticker/candle fan-out. Positive balances are kept
    # visible; downstream authoritative dust policy decides actionability.
    accounts_getter = getattr(client, "get_accounts", None)
    if not callable(accounts_getter):
        raise portfolio_error if portfolio_error is not None else RuntimeError("coinbase_accounts_api_unavailable")
    accounts_response = call(accounts_getter)
    accounts = _field(accounts_response, "accounts", []) or []
    positions = []
    for account in accounts:
        currency = str(_field(account, "currency", "") or "").strip().upper()
        if not currency or currency in {"USD", "USDC"}:
            continue
        balance = _number(_field(account, "available_balance", None))
        if balance <= 0.0:
            continue
        positions.append({
            "symbol": f"{currency}-USD",
            "quantity": balance,
            "currency": currency,
            "current_price": 0.0,
            "size_usd": 0.0,
        })
    LOGGER.warning(
        "COINBASE_POSITION_V342_ACCOUNTS_FALLBACK marker=%s positions=%d "
        "portfolio_error=%s:%s authenticated_holdings=true per_asset_market_reads=0 "
        "unknown_usd_value_included=true downstream_dust_policy_authoritative=true "
        "position_fabricated=false price_fabricated=false readiness_granted=false "
        "execution_proof_fabricated=false safety_gates_bypassed=false",
        MARKER,
        len(positions),
        type(portfolio_error).__name__ if portfolio_error is not None else "none",
        portfolio_error if portfolio_error is not None else "none",
    )
    return positions


def _patch_coinbase() -> bool:
    module = sys.modules.get("bot.broker_manager")
    if not isinstance(module, ModuleType):
        return False
    cls = getattr(module, "CoinbaseBroker", None)
    if not isinstance(cls, type):
        return False
    current = getattr(cls, "get_positions", None)
    if not callable(current):
        return False
    if _chain_has_attr(current, _COINBASE_PATCH_ATTR):
        return True
    original = current

    @wraps(original)
    def get_positions_v342(self: Any, *args: Any, **kwargs: Any):
        try:
            rows = _coinbase_fast_positions(self)
            _record_v285_snapshot(self, rows)
            return rows
        except BaseException as exc:
            LOGGER.warning(
                "COINBASE_POSITION_V342_FAST_PATH_DEFERRED marker=%s error=%s:%s "
                "fallback=existing_get_positions exception_semantics_preserved=true "
                "position_success_fabricated=false readiness_granted=false safety_gates_bypassed=false",
                MARKER,
                type(exc).__name__,
                exc,
            )
            return original(self, *args, **kwargs)

    setattr(get_positions_v342, _COINBASE_PATCH_ATTR, True)
    setattr(get_positions_v342, "__wrapped__", original)
    cls.get_positions = get_positions_v342
    LOGGER.critical(
        "COINBASE_POSITION_READ_LIVENESS_V342_PATCHED marker=%s "
        "portfolio_fiat_valuation_reused=true per_asset_market_reads_removed=true "
        "existing_fallback_preserved=true position_timeout_unchanged=true "
        "snapshot_ttl_unchanged=true safety_gates_bypassed=false",
        MARKER,
    )
    return True


def _fresh_kraken_observation(broker: Any) -> dict[str, Any] | None:
    try:
        v312 = importlib.import_module("bot.runtime_kraken_balance_epoch_handoff_v312_patch")
        getter = getattr(v312, "_fresh_observation", None)
        if not callable(getter):
            return None
        row = getter(broker, not_before=0.0)
        return dict(row) if isinstance(row, Mapping) else None
    except Exception:
        return None


def _patch_kraken_stale_join() -> bool:
    v299 = sys.modules.get("bot.runtime_kraken_credential_read_convergence_v299_patch")
    if not isinstance(v299, ModuleType):
        return False
    current = getattr(v299, "_credential_balance_call", None)
    if not callable(current):
        return False
    if _chain_has_attr(current, _KRAKEN_PATCH_ATTR):
        return True
    original = current

    @wraps(original)
    def credential_balance_v342(broker: Any, call: Any) -> Any:
        observation = _fresh_kraken_observation(broker)
        if observation is not None:
            response = observation.get("response")
            if isinstance(response, Mapping):
                LOGGER.critical(
                    "KRAKEN_CREDENTIAL_V342_FRESH_HANDOFF marker=%s account=%s observation_age_s=%.3f "
                    "authenticated_balance=true same_credential=true credential_proven=true "
                    "old_owner_cancelled=false old_flight_removed=false duplicate_private_call=false "
                    "rate_interval_unchanged=true transport_timeout_unchanged=true "
                    "capital_ttl_unchanged=true position_ttl_unchanged=true readiness_granted=false "
                    "execution_proof_fabricated=false safety_gates_bypassed=false",
                    MARKER,
                    str(getattr(broker, "account_identifier", "unknown") or "unknown"),
                    _number(observation.get("age_s")),
                )
                try:
                    import copy
                    return copy.deepcopy(response)
                except Exception:
                    return dict(response)
        return original(broker, call)

    setattr(credential_balance_v342, _KRAKEN_PATCH_ATTR, True)
    setattr(credential_balance_v342, "__wrapped__", original)
    v299._credential_balance_call = credential_balance_v342
    LOGGER.critical(
        "KRAKEN_CREDENTIAL_STALE_JOIN_V342_PATCHED marker=%s "
        "fresh_authenticated_same_credential_handoff=true old_owner_cancelled=false "
        "duplicate_private_call=false ttl_unchanged=true safety_gates_bypassed=false",
        MARKER,
    )
    return True


def _patch_loaded() -> tuple[bool, bool]:
    coinbase = False
    kraken = False
    try:
        coinbase = _patch_coinbase()
    except Exception as exc:
        LOGGER.warning("POSITION_READ_V342_COINBASE_PATCH_DEFERRED marker=%s error=%s:%s", MARKER, type(exc).__name__, exc)
    try:
        kraken = _patch_kraken_stale_join()
    except Exception as exc:
        LOGGER.warning("POSITION_READ_V342_KRAKEN_PATCH_DEFERRED marker=%s error=%s:%s", MARKER, type(exc).__name__, exc)
    return coinbase, kraken


def _worker() -> None:
    # Reassert because legacy convergence installers can replace broker wrappers
    # later during startup. The worker performs no broker I/O.
    while True:
        try:
            _patch_loaded()
        except Exception:
            pass
        time.sleep(1.0)


def install() -> bool:
    global _THREAD
    with _LOCK:
        _patch_loaded()
        if _THREAD is None or not _THREAD.is_alive():
            _THREAD = threading.Thread(target=_worker, name="PositionReadLivenessV342", daemon=True)
            _THREAD.start()
        os.environ[_READY_FLAG] = "1"
    LOGGER.critical(
        "POSITION_READ_LIVENESS_V342_READY marker=%s ready=true self_reasserting=true "
        "coinbase_n_plus_one_market_reads_removed=true kraken_fresh_credential_handoff_armed=true "
        "position_ttl_unchanged=true capital_ttl_unchanged=true rate_limits_unchanged=true "
        "writer_nonce_risk_killswitch_order_fill_gates_unchanged=true execution_proof_fabricated=false "
        "forced_exit=false forced_trade=false forced_activation=false safety_gates_bypassed=false",
        MARKER,
    )
    return True


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "RELEASE_ID",
    "install",
    "install_import_hook",
    "_coinbase_fast_positions",
    "_patch_coinbase",
    "_patch_kraken_stale_join",
]
