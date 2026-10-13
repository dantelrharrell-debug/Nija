"""Validation-only Kraken startup checks through the canonical nonce-owning adapter.

This module never creates a client, persists an approval, claims an attempt,
updates execution proof, submits a real order, or alters trading authority.
A passing preflight is not permission to run a live verification order.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Callable, Mapping

from bot.startup_verification_evidence import read_startup_broker_identity
from bot.startup_verification_plan import StartupVerificationPlan, decimal_value


class StartupPreflightError(RuntimeError):
    """Required current broker, owner, or protective-order fact is unverified."""


@dataclass(frozen=True)
class StartupPreflightReport:
    """Bounded validation evidence without authority to execute."""

    plan_digest: str
    account_fingerprint: str
    observed_at_epoch: float
    available_cash_usd: str
    fee_rate_max: str
    validation_only: bool = True
    orders_submitted: bool = False
    live_transport_verified: bool = False
    execution_ready: bool = False


def _result(payload: Any, method: str) -> dict[str, Any]:
    if not isinstance(payload, Mapping) or payload.get("error"):
        raise StartupPreflightError(f"startup_preflight_rejected:{method}")
    result = payload.get("result")
    if not isinstance(result, Mapping):
        raise StartupPreflightError(f"startup_preflight_result_missing:{method}")
    return dict(result)


def _read(broker: Any, method: str, params: dict[str, Any],
          assert_nonce_owner: Callable[[], None]) -> dict[str, Any]:
    if method not in {"BalanceEx", "OpenOrders", "OpenPositions", "TradeVolume", "AddOrder"}:
        raise StartupPreflightError("startup_preflight_method_forbidden")
    if method == "AddOrder" and params.get("validate") is not True:
        raise StartupPreflightError("startup_preflight_real_order_forbidden")
    assert_nonce_owner()
    call = getattr(broker, "_kraken_private_call", None)
    if not callable(call):
        raise StartupPreflightError("startup_preflight_serialized_owner_missing")
    try:
        result = _result(call(method, dict(params)), method)
    except StartupPreflightError:
        raise
    except Exception:
        raise StartupPreflightError(f"startup_preflight_call_failed:{method}") from None
    if method == "AddOrder":
        if result.get("txid"):
            raise StartupPreflightError("startup_preflight_unexpected_order_id")
        description = result.get("descr")
        if (not isinstance(description, Mapping)
                or not isinstance(description.get("order"), str)
                or not description["order"].strip()):
            raise StartupPreflightError("startup_preflight_order_description_missing")
        if not isinstance(description.get("close"), str) or not description["close"].strip():
            raise StartupPreflightError("startup_preflight_native_close_description_missing")
    return result


def _identity(broker: Any, plan: StartupVerificationPlan,
              assert_nonce_owner: Callable[[], None]) -> None:
    assert_nonce_owner()
    try:
        identity = read_startup_broker_identity(broker)
    except Exception:
        raise StartupPreflightError("startup_preflight_identity_unavailable") from None
    age = time.time() - identity.observed_at_epoch
    if not math.isfinite(age) or not 0 <= age <= 30:
        raise StartupPreflightError("startup_preflight_identity_stale")
    if (identity.account_fingerprint != plan.account_fingerprint
            or identity.api_key_fingerprint != plan.api_key_fingerprint):
        raise StartupPreflightError("startup_preflight_account_or_key_changed")


def run_kraken_startup_preflight(
    broker: Any,
    plan: StartupVerificationPlan,
    *,
    statement_account_fingerprint: str,
    read_asset_pair: Callable[[str], Mapping[str, Any]],
    assert_nonce_owner: Callable[[], None],
) -> StartupPreflightReport:
    """Check immutable exact terms and native protection, without executing.

    The caller must supply the already reviewed primary-ownership fingerprint,
    fresh AssetPairs reader, and genuine nonce-owner assertion from the existing
    serialized runtime. This function cannot establish legal ownership alone.
    It neither obtains real-money approval nor proves protection after fills.
    """
    plan.validate()
    started = time.time()
    if started >= plan.expires_at_epoch:
        raise StartupPreflightError("startup_preflight_plan_expired")
    if statement_account_fingerprint != plan.account_fingerprint:
        raise StartupPreflightError("startup_preflight_statement_account_mismatch")
    role = getattr(broker, "account_type", "")
    if str(getattr(role, "value", role)).strip().lower() != "platform":
        raise StartupPreflightError("startup_preflight_requires_explicit_platform_account")
    _identity(broker, plan, assert_nonce_owner)

    try:
        pair = dict(read_asset_pair(plan.pair))
        observed = float(pair.pop("observed_at_epoch"))
        if not math.isfinite(observed) or not 0 <= time.time() - observed <= 30:
            raise StartupPreflightError("startup_preflight_pair_stale")
        if pair.get("pair") != plan.pair or pair.get("quote") != "ZUSD" or pair.get("status") != "online":
            raise StartupPreflightError("startup_preflight_pair_not_exact_online_USD")
        lot_decimals = int(pair["lot_decimals"])
        pair_decimals = int(pair["pair_decimals"])
        if not 0 <= lot_decimals <= 18 or not 0 <= pair_decimals <= 18:
            raise StartupPreflightError("startup_preflight_precision_invalid")
        quantum = Decimal(1).scaleb(-lot_decimals)
        tick = decimal_value(pair["tick_size"])
        if tick <= 0 or tick % Decimal(1).scaleb(-pair_decimals) != 0:
            raise StartupPreflightError("startup_preflight_price_tick_invalid")
        if (decimal_value(plan.base_quantum) != quantum
                or decimal_value(plan.minimum_base) != decimal_value(pair["ordermin"])
                or decimal_value(plan.minimum_quote) != decimal_value(pair["costmin"])):
            raise StartupPreflightError("startup_preflight_broker_minima_changed")
        for price in (plan.entry_limit, plan.stop_trigger, plan.stop_limit, plan.close_limit):
            if decimal_value(price) % tick:
                raise StartupPreflightError("startup_preflight_price_precision_invalid")
    except StartupPreflightError:
        raise
    except Exception:
        raise StartupPreflightError("startup_preflight_pair_data_invalid") from None

    funds = _read(broker, "BalanceEx", {}, assert_nonce_owner)
    try:
        cash = funds["ZUSD"]
        balance = decimal_value(cash["balance"])
        holds = decimal_value(cash["hold_trade"])
        credit_used = decimal_value(cash.get("credit_used", "0"))
        if min(balance, holds, credit_used) < 0:
            raise ValueError
        available = balance - holds - credit_used
        if available < plan.maximum_cash_debit():
            raise StartupPreflightError("startup_preflight_cash_excluding_credit_insufficient")
    except StartupPreflightError:
        raise
    except Exception:
        raise StartupPreflightError("startup_preflight_cash_data_invalid") from None

    orders = _read(broker, "OpenOrders", {}, assert_nonce_owner)
    if not isinstance(orders.get("open"), Mapping):
        raise StartupPreflightError("startup_preflight_open_orders_incomplete")
    if orders["open"]:
        raise StartupPreflightError("startup_preflight_open_orders_require_review")
    if _read(broker, "OpenPositions", {}, assert_nonce_owner):
        raise StartupPreflightError("startup_preflight_margin_positions_require_review")

    fees = _read(broker, "TradeVolume", {"pair": plan.pair}, assert_nonce_owner)
    try:
        rate = decimal_value(fees["fees"][plan.pair]["maxfee"]) / 100
        if not 0 <= rate < 1:
            raise ValueError
        if rate > decimal_value(plan.fee_rate_max):
            raise StartupPreflightError("startup_preflight_fee_bound_exceeded")
    except StartupPreflightError:
        raise
    except Exception:
        raise StartupPreflightError("startup_preflight_fee_data_invalid") from None

    # Kraken AddOrder validation must preserve native protection as one payload;
    # an unowned independent sell order is never used as protective evidence.
    entry = plan.order_parameters("entry")
    entry.update({"close[ordertype]": "stop-loss-limit", "close[price]": plan.stop_trigger,
                  "close[price2]": plan.stop_limit, "validate": True})
    _identity(broker, plan, assert_nonce_owner)
    _read(broker, "AddOrder", entry, assert_nonce_owner)
    _identity(broker, plan, assert_nonce_owner)
    finished = time.time()
    if not 0 <= finished - started <= 30 or finished >= plan.expires_at_epoch:
        raise StartupPreflightError("startup_preflight_snapshot_expired")
    return StartupPreflightReport(plan.digest(), plan.account_fingerprint, finished, str(available), str(rate))
