"""Observe OKX Trading and Funding wallets without conflating them.

The Trading account is authoritative for order sizing.  Funding-wallet probing
is only needed when Trading does not already contain executable quote capital.
This repair also recognizes USDG, which OKX US can return as the spendable
stable balance, and avoids the unauthenticated raw-client fallback that dropped
OK-ACCESS headers on /api/v5/asset/balances.
"""
from __future__ import annotations

import logging
import os
import sys
import threading
import time
from functools import wraps
from types import ModuleType
from typing import Any

logger = logging.getLogger("nija.okx_funding_wallet_readiness")
_MARKER = "20260719-okx-funding-wallet-v2"
_LOCK = threading.RLock()
_STARTED = False
_PATCH_ATTR = "_nija_okx_funding_wallet_readiness_v2"
_STABLES = {"USD", "USDG", "USDT", "USDC"}


def _float(value: Any) -> float:
    try:
        return max(0.0, float(value or 0.0))
    except Exception:
        return 0.0


def _minimum_trade() -> float:
    for name in ("OKX_MIN_ORDER_USD", "MIN_NOTIONAL_OVERRIDE", "MIN_TRADE_USD"):
        value = _float(os.environ.get(name))
        if value > 0:
            return value
    return 10.0


def _stable_sum(rows: Any, *, funding: bool) -> tuple[float, float]:
    spendable = 0.0
    total = 0.0
    if not isinstance(rows, (list, tuple)):
        return 0.0, 0.0
    for row in rows:
        if not isinstance(row, dict):
            continue
        ccy = str(row.get("ccy") or row.get("currency") or "").upper().strip()
        if ccy not in _STABLES:
            continue
        if funding:
            available = _float(row.get("availBal", row.get("available", row.get("bal", 0))))
            balance = _float(row.get("bal", row.get("balance", available)))
        else:
            available = _float(row.get("availBal", row.get("cashBal", row.get("eqUsd", 0))))
            balance = max(_float(row.get("cashBal")), _float(row.get("eqUsd")), available)
        spendable += available
        total += balance
    return spendable, total


def _trading_wallet(broker: Any) -> tuple[bool, float, float, str]:
    api = getattr(broker, "account_api", None)
    if api is None or not callable(getattr(api, "get_balance", None)):
        return False, 0.0, 0.0, "account_api_unavailable"
    try:
        payload = api.get_balance()
    except Exception as exc:
        return False, 0.0, 0.0, f"{type(exc).__name__}:{exc}"
    if not isinstance(payload, dict) or str(payload.get("code", "")) != "0":
        return False, 0.0, 0.0, f"code={getattr(payload, 'get', lambda *_: 'invalid')('code', 'invalid')}"
    data = payload.get("data") or []
    root = data[0] if isinstance(data, list) and data and isinstance(data[0], dict) else {}
    spendable, stable_total = _stable_sum(root.get("details") or [], funding=False)
    total_equity = _float(root.get("totalEq")) or stable_total
    return True, spendable, total_equity, "ok"


def _funding_payload_from_client(client: Any) -> Any:
    if client is None:
        return None
    # Only use documented authenticated SDK methods.  Calling a generic _request
    # method on the wrong client produced a Content-Type-only request and 50103.
    method = getattr(client, "get_balances", None)
    if callable(method):
        try:
            return method(ccy="USD,USDG,USDT,USDC")
        except TypeError:
            try:
                return method()
            except Exception:
                return None
        except Exception:
            return None
    return None


def _funding_wallet(broker: Any) -> tuple[bool, float, float, str]:
    clients: list[Any] = []
    for name in ("asset_api", "funding_api"):
        client = getattr(broker, name, None)
        if client is not None and all(client is not seen for seen in clients):
            clients.append(client)
    last_reason = "authenticated_funding_client_unavailable"
    for client in clients:
        try:
            payload = _funding_payload_from_client(client)
        except Exception as exc:
            last_reason = f"{type(exc).__name__}:{exc}"
            continue
        if not isinstance(payload, dict):
            continue
        code = str(payload.get("code", ""))
        if code != "0":
            last_reason = f"code={code or 'missing'}"
            continue
        spendable, total = _stable_sum(payload.get("data") or [], funding=True)
        return True, spendable, total, "ok"
    return False, 0.0, 0.0, last_reason


def _publish(broker: Any) -> None:
    trading_ok, trading_spendable, trading_total, trading_reason = _trading_wallet(broker)
    minimum = _minimum_trade()

    # A funded Trading wallet is sufficient for execution.  Do not issue an
    # unnecessary Funding request, which previously caused a false auth error.
    if trading_ok and trading_spendable >= minimum:
        funding_ok, funding_spendable, funding_total, funding_reason = False, 0.0, 0.0, "not_required"
    else:
        funding_ok, funding_spendable, funding_total, funding_reason = _funding_wallet(broker)

    observed = trading_ok or funding_ok
    total_observed = trading_total + funding_total

    if trading_ok and trading_spendable >= minimum:
        status = "funded"
        ready = True
    elif funding_ok and funding_spendable >= minimum:
        status = "funded_needs_transfer"
        ready = False
    elif observed:
        status = "under_minimum"
        ready = False
    else:
        status = "unobserved"
        ready = False

    values = {
        "NIJA_OKX_BALANCE_OBSERVED": "1" if observed else "0",
        "NIJA_OKX_FUNDING_STATUS": status,
        "NIJA_OKX_TRADING_SPENDABLE_QUOTE": f"{trading_spendable:.8f}" if trading_ok else "unknown",
        "NIJA_OKX_TRADING_TOTAL_QUOTE": f"{trading_total:.8f}" if trading_ok else "unknown",
        "NIJA_OKX_FUNDING_SPENDABLE_QUOTE": f"{funding_spendable:.8f}" if funding_ok else "unknown",
        "NIJA_OKX_FUNDING_TOTAL_QUOTE": f"{funding_total:.8f}" if funding_ok else "unknown",
        "NIJA_OKX_TOTAL_OBSERVED_QUOTE": f"{total_observed:.8f}" if observed else "unknown",
        "NIJA_OKX_TRADING_READY": "1" if ready else "0",
        "NIJA_OKX_SPENDABLE_QUOTE": f"{trading_spendable:.8f}" if trading_ok else "unknown",
    }
    os.environ.update(values)
    setattr(broker, "_okx_trading_spendable_quote", trading_spendable if trading_ok else None)
    setattr(broker, "_okx_funding_spendable_quote", funding_spendable if funding_ok else None)
    setattr(broker, "_okx_funding_status", status)
    setattr(broker, "trading_ready", ready)
    setattr(broker, "ready", ready)

    if observed:
        logger.critical(
            "OKX_DUAL_WALLET_BALANCE_OBSERVED marker=%s trading_spendable=$%.2f trading_total=$%.2f funding_spendable=$%.2f funding_total=$%.2f total_observed=$%.2f status=%s minimum=$%.2f funding_probe=%s",
            _MARKER, trading_spendable, trading_total, funding_spendable, funding_total,
            total_observed, status, minimum, funding_reason,
        )
    else:
        logger.warning(
            "OKX_BALANCE_UNOBSERVED_NOT_UNDERFUNDED marker=%s trading_reason=%s funding_reason=%s",
            _MARKER, trading_reason, funding_reason,
        )


def _patch_class(cls: type) -> bool:
    current = getattr(cls, "get_account_balance", None)
    if not callable(current) or getattr(current, _PATCH_ATTR, False):
        return False

    @wraps(current)
    def get_account_balance(self: Any, *args: Any, **kwargs: Any) -> float:
        result = current(self, *args, **kwargs)
        try:
            _publish(self)
        except Exception:
            logger.exception("OKX_DUAL_WALLET_PUBLISH_FAILED marker=%s", _MARKER)
        return float(result or 0.0)

    setattr(get_account_balance, _PATCH_ATTR, True)
    get_account_balance.__wrapped__ = current  # type: ignore[attr-defined]
    setattr(cls, "get_account_balance", get_account_balance)
    return True


def _patch_loaded() -> bool:
    changed = False
    for module_name in ("bot.broker_manager", "broker_manager", "bot.broker_integration"):
        module = sys.modules.get(module_name)
        if not isinstance(module, ModuleType):
            continue
        for class_name in ("OKXBroker", "OKXBrokerAdapter"):
            cls = getattr(module, class_name, None)
            if isinstance(cls, type):
                changed = _patch_class(cls) or changed
    return changed


def _monitor() -> None:
    deadline = time.monotonic() + max(120.0, float(os.environ.get("NIJA_PATCH_MONITOR_SECONDS", "600") or 600))
    while time.monotonic() < deadline:
        try:
            _patch_loaded()
        except Exception:
            logger.exception("OKX_FUNDING_WALLET_MONITOR_ERROR marker=%s", _MARKER)
        time.sleep(0.25)


def install() -> bool:
    global _STARTED
    with _LOCK:
        _patch_loaded()
        if not _STARTED:
            _STARTED = True
            threading.Thread(target=_monitor, name="OKXFundingWalletReadiness", daemon=True).start()
        os.environ["NIJA_OKX_FUNDING_WALLET_READINESS_INSTALLED"] = "1"
        os.environ.setdefault("NIJA_OKX_BALANCE_OBSERVED", "0")
        os.environ.setdefault("NIJA_OKX_FUNDING_STATUS", "unobserved")
        logger.critical("OKX_FUNDING_WALLET_READINESS_INSTALLED marker=%s auto_transfer=false authenticated_funding_only=true", _MARKER)
        return True


__all__ = ["install", "_stable_sum", "_trading_wallet", "_funding_wallet", "_publish"]
