"""Canonical broker/account scope for every ExecutionPipeline request.

Pre-trade exposure and risk bookkeeping must never share generic account keys or
borrow global CapitalAuthority equity. Requests are normalized to
``<broker>:<account>`` and pre-trade cap base is computed from that account's
cash plus that account's tracked exposure only. Transient broker selection is
also kept out of process-global environment variables.
"""
from __future__ import annotations

import copy
import logging
import threading
from dataclasses import is_dataclass, replace
from typing import Any, Dict

logger = logging.getLogger("nija.execution_account_scope_v421")
MARKER = "20260914-execution-account-scope-v421"
_LOCK = threading.RLock()
_PATCH_ATTR = "_nija_execution_account_scope_v421"
_CAP_PATCH_ATTR = "_nija_account_local_cap_base_v421"


def _clean(value: Any) -> str:
    return str(value or "").strip().lower()


def _broker_from_request(request: Any) -> str:
    preferred = _clean(getattr(request, "preferred_broker", ""))
    metadata: Dict[str, Any] = dict(getattr(request, "metadata", {}) or {})
    if preferred:
        return preferred
    named = _clean(metadata.get("broker_name"))
    if named:
        return named
    broker = metadata.get("broker_client")
    if broker is not None:
        bt = getattr(broker, "broker_type", None)
        value = getattr(bt, "value", bt)
        if value:
            return _clean(value)
        name = _clean(getattr(broker, "NAME", "") or getattr(broker, "broker_name", ""))
        if name:
            return name.replace("broker", "").strip("_:- ")
    return "unknown"


def _account_from_request(request: Any) -> str:
    metadata: Dict[str, Any] = dict(getattr(request, "metadata", {}) or {})
    broker = metadata.get("broker_client")
    raw = _clean(getattr(request, "account_id", ""))
    if raw not in {"", "default", "unknown", "none"}:
        return raw
    for value in (
        metadata.get("account_id"),
        metadata.get("user_id"),
        getattr(broker, "nija_account_scope", None) if broker is not None else None,
        getattr(broker, "account_id", None) if broker is not None else None,
        getattr(broker, "user_id", None) if broker is not None else None,
        getattr(broker, "nija_user_id", None) if broker is not None else None,
        getattr(broker, "account_identifier", None) if broker is not None else None,
    ):
        cleaned = _clean(value)
        if cleaned and cleaned not in {"default", "unknown", "none"}:
            return cleaned
    account_type = _clean(getattr(request, "account_type", ""))
    return "platform" if account_type in {"", "platform"} else account_type


def canonical_account_id(request: Any) -> str:
    broker = _broker_from_request(request)
    account = _account_from_request(request)
    if account.startswith(f"{broker}:"):
        return account
    if account.startswith("user:") and account.endswith(f":{broker}"):
        account = account[len("user:") : -(len(broker) + 1)]
    return f"{broker}:{account}"


def _with_account_id(request: Any, account_id: str) -> Any:
    metadata = dict(getattr(request, "metadata", {}) or {})
    metadata["account_id"] = account_id
    metadata["risk_scope"] = account_id
    if is_dataclass(request):
        try:
            return replace(request, account_id=account_id, metadata=metadata)
        except TypeError:
            try:
                return replace(request, account_id=account_id)
            except Exception:
                pass
    cloned = copy.copy(request)
    try:
        setattr(cloned, "account_id", account_id)
        setattr(cloned, "metadata", metadata)
        return cloned
    except Exception:
        return request


def _patch_pre_trade_capital_base() -> bool:
    """Remove global-equity borrowing from the account exposure gate."""
    try:
        from bot.pre_trade_risk_engine import PreTradeRiskEngine
    except Exception:
        return False
    current = getattr(PreTradeRiskEngine, "_cap_base_usd", None)
    if not callable(current):
        return False
    if getattr(current, _CAP_PATCH_ATTR, False):
        return True

    def account_local_cap_base(
        self: Any,
        *,
        available_balance_usd: float | None,
        current_total_exposure: float,
    ) -> float:
        try:
            available = max(0.0, float(available_balance_usd or 0.0))
        except (TypeError, ValueError, OverflowError):
            available = 0.0
        try:
            exposure = max(0.0, float(current_total_exposure or 0.0))
        except (TypeError, ValueError, OverflowError):
            exposure = 0.0
        cap_base = available + exposure
        logger.debug(
            "ACCOUNT_LOCAL_CAP_BASE marker=%s available_usd=%.2f exposure_usd=%.2f cap_base_usd=%.2f global_equity_used=false",
            MARKER,
            available,
            exposure,
            cap_base,
        )
        return cap_base

    setattr(account_local_cap_base, _CAP_PATCH_ATTR, True)
    setattr(account_local_cap_base, "__wrapped__", current)
    PreTradeRiskEngine._cap_base_usd = account_local_cap_base
    return True


def _patch_execution_pipeline() -> bool:
    try:
        from bot.execution_pipeline import ExecutionPipeline
    except Exception:
        return False
    current = getattr(ExecutionPipeline, "execute", None)
    if not callable(current):
        return False
    if getattr(current, _PATCH_ATTR, False):
        return True
    original = current

    def execute(self: Any, request: Any, *args: Any, **kwargs: Any):
        account_id = canonical_account_id(request)
        scoped_request = _with_account_id(request, account_id)
        broker, _, account = account_id.partition(":")
        try:
            from bot.broker_account_scope import broker_account_scope
        except Exception:
            broker_account_scope = None

        logger.debug(
            "EXECUTION_ACCOUNT_SCOPE marker=%s broker=%s account=%s account_id=%s",
            MARKER,
            broker,
            account,
            account_id,
        )
        if broker_account_scope is None:
            return original(self, scoped_request, *args, **kwargs)
        with broker_account_scope(broker, account):
            return original(self, scoped_request, *args, **kwargs)

    setattr(execute, _PATCH_ATTR, True)
    setattr(execute, "__wrapped__", original)
    ExecutionPipeline.execute = execute
    return True


def _patch_execution_engine() -> bool:
    try:
        from bot.execution_engine import ExecutionEngine
    except Exception:
        return False
    current = getattr(ExecutionEngine, "_submit_market_order_via_pipeline", None)
    if not callable(current):
        return False
    if getattr(current, _PATCH_ATTR, False):
        return True
    original = current

    def scoped_submit(self: Any, broker_client: Any, symbol: str, side: str, size_usd: float, *args: Any, **kwargs: Any):
        preferred = _clean(kwargs.get("preferred_broker"))
        if not preferred and broker_client is not None:
            bt = getattr(broker_client, "broker_type", None)
            preferred = _clean(getattr(bt, "value", bt))
        preferred = preferred or "unknown"

        raw_account = _clean(kwargs.get("account_id"))
        if raw_account in {"", "default", "unknown", "none"}:
            for value in (
                getattr(broker_client, "nija_account_scope", None),
                getattr(broker_client, "account_id", None),
                getattr(broker_client, "user_id", None),
                getattr(broker_client, "nija_user_id", None),
                getattr(self, "user_id", None),
            ):
                cleaned = _clean(value)
                if cleaned and cleaned not in {"default", "unknown", "none"}:
                    raw_account = cleaned
                    break
        raw_account = raw_account or "platform"
        canonical = raw_account if raw_account.startswith(f"{preferred}:") else f"{preferred}:{raw_account}"
        kwargs["account_id"] = canonical
        return original(self, broker_client, symbol, side, size_usd, *args, **kwargs)

    setattr(scoped_submit, _PATCH_ATTR, True)
    setattr(scoped_submit, "__wrapped__", original)
    ExecutionEngine._submit_market_order_via_pipeline = scoped_submit
    return True


def _install_context_locality() -> bool:
    try:
        from bot.broker_context_locality_v422_patch import install as install_locality
        return bool(install_locality())
    except Exception as exc:
        logger.warning(
            "BROKER_CONTEXT_LOCALITY_INSTALL_DEFERRED marker=%s error=%s:%s",
            MARKER,
            type(exc).__name__,
            exc,
        )
        return False


def install() -> bool:
    with _LOCK:
        cap_base = _patch_pre_trade_capital_base()
        pipeline = _patch_execution_pipeline()
        engine = _patch_execution_engine()
        context_locality = _install_context_locality()
        ready = cap_base and (pipeline or engine) and context_locality
        logger.critical(
            "EXECUTION_ACCOUNT_SCOPE_V421 marker=%s cap_base=%s pipeline=%s engine=%s context_locality=%s ready=%s",
            MARKER,
            cap_base,
            pipeline,
            engine,
            context_locality,
            ready,
        )
        return ready


install_import_hook = install

__all__ = [
    "MARKER",
    "canonical_account_id",
    "install",
    "install_import_hook",
    "_patch_pre_trade_capital_base",
]
