from __future__ import annotations

import builtins
import logging
import sys
import time
from dataclasses import replace
from functools import wraps
from types import ModuleType
from typing import Any, Optional

logger = logging.getLogger("nija.final_stage_venue_routing_repair")
_MARKER = "20260709n"
_ROUTE_ATTR = "_nija_final_stage_venue_route_v20260709n"
_SCORE_ATTR = "_nija_final_stage_venue_score_v20260709n"
_DISPATCH_ATTR = "_nija_final_stage_venue_dispatch_v20260709n"
_RESOLVE_ATTR = "_nija_final_stage_venue_resolve_v20260709n"
_HOOK_FLAG = "_NIJA_FINAL_STAGE_VENUE_ROUTING_REPAIR_HOOK_V20260709N"

_COMPLIANCE_DISABLED: set[tuple[str, str]] = set()


def _norm_broker(value: Any) -> str:
    text = str(value or "").strip().lower()
    compact = text.replace("-", "").replace("_", "").replace(" ", "")
    aliases = {
        "coinbasebrokeradapter": "coinbase",
        "coinbasebroker": "coinbase",
        "coinbaseadvancedtradebroker": "coinbase",
        "coinbase": "coinbase",
        "krakenbrokeradapter": "kraken",
        "krakenbroker": "kraken",
        "kraken": "kraken",
        "okxbrokeradapter": "okx",
        "okxbroker": "okx",
        "okxrestclient": "okx",
        "okx": "okx",
        "binancebrokeradapter": "binance",
        "binancebroker": "binance",
        "binance": "binance",
    }
    return aliases.get(compact, text)


def _norm_symbol(value: Any) -> str:
    text = str(value or "").strip().upper().replace("/", "-").replace("_", "-").replace(":", "-")
    while "--" in text:
        text = text.replace("--", "-")
    if text.endswith("-USDTT"):
        text = text[:-6] + "-USDT"
    if text.endswith("-USDTC"):
        text = text[:-6] + "-USDC"
    return text


def _f(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        amount = float(value)
        if amount != amount:
            return default
        return amount
    except Exception:
        return default


def _is_compliance_error(error: Any) -> bool:
    text = str(error or "").lower()
    return "51155" in text or "local compliance" in text or "can't trade this pair" in text or "cannot trade this pair" in text


def _disable_compliance_route(broker: Any, symbol: Any, reason: Any = "") -> None:
    broker_n = _norm_broker(broker)
    symbol_n = _norm_symbol(symbol)
    if not broker_n or not symbol_n:
        return
    key = (broker_n, symbol_n)
    if key not in _COMPLIANCE_DISABLED:
        logger.critical(
            "BROKER_SYMBOL_COMPLIANCE_QUARANTINED marker=%s broker=%s symbol=%s reason=%s",
            _MARKER,
            broker_n,
            symbol_n,
            str(reason)[:240],
        )
        print(
            f"[NIJA-PRINT] BROKER_SYMBOL_COMPLIANCE_QUARANTINED marker={_MARKER} broker={broker_n} symbol={symbol_n}",
            flush=True,
        )
    _COMPLIANCE_DISABLED.add(key)


def _is_disabled(broker: Any, symbol: Any) -> bool:
    return (_norm_broker(broker), _norm_symbol(symbol)) in _COMPLIANCE_DISABLED


def _infer_client_name(client: Any) -> str:
    if client is None:
        return ""
    candidates = (
        getattr(getattr(client, "broker_type", None), "value", None),
        getattr(client, "broker_type", None),
        getattr(client, "exchange", None),
        getattr(client, "NAME", None),
        getattr(client, "name", None),
        getattr(client, "broker_name", None),
        getattr(client, "venue", None),
        client.__class__.__name__,
        client.__class__.__module__,
    )
    for candidate in candidates:
        name = _norm_broker(candidate)
        if name in {"coinbase", "kraken", "okx", "binance"}:
            return name
    joined = " ".join(str(c or "") for c in candidates).lower()
    for name in ("coinbase", "kraken", "okx", "binance"):
        if name in joined:
            return name
    return ""


def _is_live_client(obj: Any, target: str) -> bool:
    if obj is None or _infer_client_name(obj) != target:
        return False
    if getattr(obj, "connected", True) is False:
        return False
    methods = (
        "place_market_order",
        "place_order",
        "execute_order",
        "submit_order",
        "get_account_balance",
        "get_balance",
        "get_candles",
        "get_market_data",
    )
    return any(callable(getattr(obj, method, None)) for method in methods)


def _try_direct_guard_resolver(router: Any, target: str) -> Any | None:
    for mod_name in ("bot.direct_broker_metadata_guard_patch", "direct_broker_metadata_guard_patch"):
        try:
            mod = sys.modules.get(mod_name)
            if mod is None:
                mod = __import__(mod_name, fromlist=["*"])
            fn = getattr(mod, "_resolve_live_client", None)
            if callable(fn):
                client = fn(router, target)
                if _is_live_client(client, target):
                    return client
        except Exception:
            pass
    return None


def _iter_values(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, dict):
        return list(value.values())
    if isinstance(value, (list, tuple, set, frozenset)):
        return list(value)
    return [value]


def _scan_container(seed: Any, target: str) -> Any | None:
    seen: set[int] = set()
    queue: list[Any] = [seed]
    attrs = (
        "broker_client", "broker_adapter", "client", "adapter", "broker", "brokers", "_brokers",
        "broker_map", "_broker_map", "platform_brokers", "user_brokers", "connected_brokers",
        "active_brokers", "registered_brokers", "venue_brokers", "exchange_brokers",
        "GLOBAL_PLATFORM_BROKERS", "_PLATFORM_BROKER_INSTANCES", "_platform_brokers",
        "_platform_broker_instances", "broker_manager", "multi_account_manager", "capital_authority",
    )
    methods = (
        "get_all_brokers", "all_brokers", "get_brokers", "get_connected_brokers",
        "brokers_for_execution", "get_platform_brokers", "platform_broker_map",
    )
    while queue:
        obj = queue.pop(0)
        if obj is None:
            continue
        oid = id(obj)
        if oid in seen:
            continue
        seen.add(oid)
        if _is_live_client(obj, target):
            return obj
        if len(seen) > 1200:
            break
        for attr in attrs:
            try:
                queue.extend(_iter_values(getattr(obj, attr, None)))
            except Exception:
                pass
        for method in methods:
            try:
                fn = getattr(obj, method, None)
                if callable(fn):
                    queue.extend(_iter_values(fn()))
            except Exception:
                pass
    return None


def _module_candidates() -> list[Any]:
    names = (
        "bot.broker_manager", "broker_manager", "bot.multi_account_broker_manager", "multi_account_broker_manager",
        "bot.multi_account", "multi_account", "bot.capital_authority", "capital_authority",
        "bot.coinbase_broker", "coinbase_broker", "bot.kraken_broker", "kraken_broker", "bot.okx_broker", "okx_broker",
    )
    out: list[Any] = []
    for name in names:
        try:
            mod = sys.modules.get(name)
            if mod is None:
                mod = __import__(name, fromlist=["*"])
            out.append(mod)
            for attr in (
                "broker_manager", "multi_account_manager", "manager", "BROKER_MANAGER",
                "GLOBAL_PLATFORM_BROKERS", "_PLATFORM_BROKER_INSTANCES", "_PLATFORM_BROKER_CONNECTED",
                "coinbase_broker", "kraken_broker", "okx_broker", "capital_authority", "_capital_authority",
            ):
                try:
                    out.append(getattr(mod, attr, None))
                except Exception:
                    pass
            for maker in ("get_multi_account_broker_manager", "get_multi_account_manager", "get_broker_manager", "get_capital_authority"):
                fn = getattr(mod, maker, None)
                if callable(fn):
                    try:
                        out.append(fn())
                    except Exception:
                        pass
        except Exception:
            pass
    return out


def _resolve_live_client(router: Any, target: Any) -> Any | None:
    target_n = _norm_broker(target)
    if not target_n:
        return None
    client = _try_direct_guard_resolver(router, target_n)
    if client is not None:
        return client
    resolver = getattr(router, "_resolve_live_broker", None)
    if callable(resolver) and not getattr(resolver, _RESOLVE_ATTR, False):
        try:
            client = resolver(target_n)
            if _is_live_client(client, target_n):
                return client
        except Exception:
            pass
    client = _scan_container(router, target_n)
    if client is not None:
        return client
    for candidate in _module_candidates():
        client = _scan_container(candidate, target_n)
        if client is not None:
            return client
    return None


def _request_preferred(request: Any) -> str:
    meta = dict(getattr(request, "metadata", {}) or {})
    return _norm_broker(getattr(request, "preferred_broker", None) or meta.get("preferred_broker") or meta.get("broker_name") or meta.get("selected_broker") or meta.get("execution_broker"))


def _set_request_meta(request: Any, meta: dict[str, Any]) -> Any:
    try:
        setattr(request, "metadata", meta)
        return request
    except Exception:
        try:
            return replace(request, metadata=meta)
        except Exception:
            return request


def _replace_request(request: Any, **changes: Any) -> Any:
    try:
        return replace(request, **changes)
    except Exception:
        for key, value in changes.items():
            try:
                setattr(request, key, value)
            except Exception:
                pass
        return request


def _bind_preferred_live_client(router: Any, request: Any, *, reason: str) -> Any:
    preferred = _request_preferred(request)
    if not preferred or preferred not in {"coinbase", "kraken", "okx", "binance"}:
        return request
    if _is_disabled(preferred, getattr(request, "symbol", "")):
        meta = dict(getattr(request, "metadata", {}) or {})
        meta.pop("broker_client", None)
        meta.pop("broker_adapter", None)
        meta["disabled_broker_route"] = preferred
        meta["disabled_broker_route_reason"] = "compliance_quarantine"
        logger.critical(
            "BROKER_SYMBOL_COMPLIANCE_ROUTE_SKIPPED marker=%s broker=%s symbol=%s action=clear_preferred",
            _MARKER,
            preferred,
            _norm_symbol(getattr(request, "symbol", "")),
        )
        request = _set_request_meta(request, meta)
        request = _replace_request(request, preferred_broker=None)
        return request
    meta = dict(getattr(request, "metadata", {}) or {})
    existing = meta.get("broker_client") or meta.get("broker_adapter")
    if _is_live_client(existing, preferred):
        return request
    client = _resolve_live_client(router, preferred)
    if client is None:
        return request
    meta["broker_client"] = client
    meta.pop("broker_adapter", None)
    meta["broker_name"] = preferred
    meta["preferred_broker"] = preferred
    meta["final_stage_venue_binding"] = reason
    logger.critical(
        "ECEL_REPAIRED_BROKER_CLIENT_BOUND marker=%s broker=%s symbol=%s client_type=%s reason=%s",
        _MARKER,
        preferred,
        _norm_symbol(getattr(request, "symbol", "")),
        type(client).__name__,
        reason,
    )
    print(
        f"[NIJA-PRINT] ECEL_REPAIRED_BROKER_CLIENT_BOUND marker={_MARKER} broker={preferred} symbol={_norm_symbol(getattr(request, 'symbol', ''))} client_type={type(client).__name__}",
        flush=True,
    )
    return _set_request_meta(request, meta)


def _patch_router(module: ModuleType) -> bool:
    cls = getattr(module, "MultiBrokerExecutionRouter", None)
    score_cls = getattr(module, "BrokerRoutingScore", None)
    if not isinstance(cls, type):
        return False
    patched = False

    original_resolve = getattr(cls, "_resolve_live_broker", None)
    if callable(original_resolve) and not getattr(original_resolve, _RESOLVE_ATTR, False):
        @wraps(original_resolve)
        def _resolve_live_broker(self: Any, broker_name: str):
            base = original_resolve(self, broker_name)
            target = _norm_broker(broker_name)
            if _is_live_client(base, target):
                return base
            client = _try_direct_guard_resolver(self, target) or _scan_container(self, target)
            if client is None:
                for candidate in _module_candidates():
                    client = _scan_container(candidate, target)
                    if client is not None:
                        break
            if client is not None:
                logger.critical(
                    "LIVE_BROKER_RESOLUTION_REPAIRED marker=%s broker=%s client_type=%s",
                    _MARKER,
                    target,
                    type(client).__name__,
                )
            return client
        setattr(_resolve_live_broker, _RESOLVE_ATTR, True)
        setattr(_resolve_live_broker, "__wrapped__", original_resolve)
        setattr(cls, "_resolve_live_broker", _resolve_live_broker)
        patched = True

    original_score = getattr(cls, "_score_broker_candidate", None)
    if callable(original_score) and score_cls is not None and not getattr(original_score, _SCORE_ATTR, False):
        @wraps(original_score)
        def _score_broker_candidate(self: Any, profile: Any, asset_class: Any, side: str, size_usd: Optional[float]):
            symbol = getattr(self, "_pending_request_symbol", "")
            if _is_disabled(getattr(profile, "name", ""), symbol):
                required = max(_f(getattr(profile, "min_notional_usd", 0.0), 0.0), _f(size_usd, 0.0))
                return score_cls(
                    broker=getattr(profile, "name", ""),
                    eligible=False,
                    usd_balance=0.0,
                    capital_required_usd=required,
                    capital_score=0.0,
                    latency_score=0.0,
                    fee_score=0.0,
                    health_score=0.0,
                    total_score=-1.0,
                    reason="disabled_compliance_route",
                )
            score = original_score(self, profile, asset_class, side, size_usd)
            if str(getattr(score, "reason", "")) == "broker_not_registered":
                client = _resolve_live_client(self, getattr(profile, "name", ""))
                if client is not None:
                    balance = 0.0
                    for method in ("get_account_balance", "get_balance"):
                        fn = getattr(client, method, None)
                        if callable(fn):
                            try:
                                balance = max(balance, _f(fn(), 0.0))
                            except Exception:
                                pass
                    required = max(_f(getattr(profile, "min_notional_usd", 0.0), 0.0), _f(size_usd, 0.0))
                    if str(side or "").lower() in {"buy", "long"} and balance < required:
                        eligible = False
                        reason = f"registry_repaired_insufficient_usd:${balance:.2f}<${required:.2f}"
                    else:
                        eligible = True
                        reason = "registry_repaired_live_client"
                    logger.critical(
                        "BROKER_REGISTRY_ELIGIBILITY_REPAIRED marker=%s broker=%s symbol=%s eligible=%s balance=%.2f required=%.2f reason=%s",
                        _MARKER,
                        getattr(profile, "name", ""),
                        _norm_symbol(symbol),
                        eligible,
                        balance,
                        required,
                        reason,
                    )
                    return score_cls(
                        broker=getattr(profile, "name", ""),
                        eligible=eligible,
                        usd_balance=balance,
                        capital_required_usd=required,
                        capital_score=max(0.0, min(balance / required, 1.0)) if required > 0 else 1.0,
                        latency_score=max(_f(getattr(score, "latency_score", 0.5), 0.5), 0.5),
                        fee_score=max(_f(getattr(score, "fee_score", 0.9), 0.9), 0.9),
                        health_score=1.0 if eligible else 0.25,
                        total_score=1.0 if eligible else -1.0,
                        reason=reason,
                    )
            return score
        setattr(_score_broker_candidate, _SCORE_ATTR, True)
        setattr(_score_broker_candidate, "__wrapped__", original_score)
        setattr(cls, "_score_broker_candidate", _score_broker_candidate)
        patched = True

    original_dispatch = getattr(cls, "_dispatch_via_inner_router", None)
    if callable(original_dispatch) and not getattr(original_dispatch, _DISPATCH_ATTR, False):
        @wraps(original_dispatch)
        def _dispatch_via_inner_router(self: Any, *args: Any, **kwargs: Any):
            broker_name = _norm_broker(kwargs.get("broker_name", args[5] if len(args) > 5 else ""))
            metadata = kwargs.get("metadata", args[6] if len(args) > 6 else None)
            meta = dict(metadata or {})
            client = meta.get("broker_client") or meta.get("broker_adapter")
            if not _is_live_client(client, broker_name):
                replacement = _resolve_live_client(self, broker_name)
                if replacement is not None:
                    meta["broker_client"] = replacement
                    meta.pop("broker_adapter", None)
                    meta["broker_name"] = broker_name
                    meta["preferred_broker"] = broker_name
                    meta["final_stage_venue_binding"] = "dispatch_missing_or_stale_client"
                    kwargs["metadata"] = meta
                    logger.critical(
                        "BROKER_DISPATCH_CLIENT_BOUND marker=%s broker=%s client_type=%s",
                        _MARKER,
                        broker_name,
                        type(replacement).__name__,
                    )
            try:
                return original_dispatch(self, *args, **kwargs)
            except Exception as exc:
                if broker_name == "okx" and _is_compliance_error(exc):
                    symbol = kwargs.get("symbol", args[0] if args else "")
                    _disable_compliance_route("okx", symbol, exc)
                    raise RuntimeError(f"OKX_COMPLIANCE_ROUTE_QUARANTINED code=51155 symbol={_norm_symbol(symbol)} error={exc}") from exc
                raise
        setattr(_dispatch_via_inner_router, _DISPATCH_ATTR, True)
        setattr(_dispatch_via_inner_router, "__wrapped__", original_dispatch)
        setattr(cls, "_dispatch_via_inner_router", _dispatch_via_inner_router)
        patched = True

    original_route = getattr(cls, "route", None)
    if callable(original_route) and not getattr(original_route, _ROUTE_ATTR, False):
        @wraps(original_route)
        def route(self: Any, request: Any):
            request = _bind_preferred_live_client(self, request, reason="route_preferred_broker")
            result = original_route(self, request)
            err = getattr(result, "error", None)
            broker = getattr(result, "broker", None) or _request_preferred(request)
            symbol = getattr(request, "symbol", "")
            if _norm_broker(broker) == "okx" and _is_compliance_error(err):
                _disable_compliance_route("okx", symbol, err)
                meta = dict(getattr(request, "metadata", {}) or {})
                meta.pop("broker_client", None)
                meta.pop("broker_adapter", None)
                meta["okx_compliance_quarantined"] = _norm_symbol(symbol)
                retry = _replace_request(request, preferred_broker=None, metadata=meta)
                logger.critical(
                    "OKX_COMPLIANCE_REROUTE_ATTEMPT marker=%s symbol=%s side=%s size_usd=%.2f",
                    _MARKER,
                    _norm_symbol(symbol),
                    getattr(request, "side", ""),
                    _f(getattr(request, "size_usd", 0.0), 0.0),
                )
                retry = _bind_preferred_live_client(self, retry, reason="okx_compliance_retry")
                retry_result = original_route(self, retry)
                if getattr(retry_result, "success", False):
                    logger.critical(
                        "OKX_COMPLIANCE_REROUTE_SUCCESS marker=%s symbol=%s rerouted_broker=%s",
                        _MARKER,
                        _norm_symbol(symbol),
                        getattr(retry_result, "broker", ""),
                    )
                    return retry_result
                logger.warning(
                    "OKX_COMPLIANCE_REROUTE_FAILED marker=%s symbol=%s error=%s",
                    _MARKER,
                    _norm_symbol(symbol),
                    getattr(retry_result, "error", None),
                )
                return retry_result
            return result
        setattr(route, _ROUTE_ATTR, True)
        setattr(route, "__wrapped__", original_route)
        setattr(cls, "route", route)
        patched = True

    if patched:
        logger.warning("FINAL_STAGE_VENUE_ROUTING_REPAIR_PATCHED marker=%s module=%s", _MARKER, getattr(module, "__name__", ""))
        print(f"[NIJA-PRINT] FINAL_STAGE_VENUE_ROUTING_REPAIR_PATCHED marker={_MARKER} module={getattr(module, '__name__', '')}", flush=True)
    return patched


def _try_patch_loaded() -> bool:
    patched = False
    for name, module in list(sys.modules.items()):
        if isinstance(module, ModuleType) and name.endswith("multi_broker_execution_router"):
            try:
                patched = _patch_router(module) or patched
            except Exception as exc:
                logger.warning("FINAL_STAGE_VENUE_ROUTING_REPAIR_PATCH_FAILED marker=%s module=%s err=%s", _MARKER, name, exc)
    return patched


def install_import_hook() -> None:
    _try_patch_loaded()
    if getattr(builtins, _HOOK_FLAG, False):
        return
    original_import = builtins.__import__

    def guarded_import(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
        module = original_import(name, globals, locals, fromlist, level)
        try:
            if str(name).endswith("multi_broker_execution_router") or "broker" in str(name).lower():
                _try_patch_loaded()
        except Exception as exc:
            logger.warning("FINAL_STAGE_VENUE_ROUTING_REPAIR_IMPORT_HOOK_FAILED marker=%s name=%s err=%s", _MARKER, name, exc)
        return module

    builtins.__import__ = guarded_import
    setattr(builtins, _HOOK_FLAG, True)
    logger.warning("FINAL_STAGE_VENUE_ROUTING_REPAIR_IMPORT_HOOK marker=%s", _MARKER)


def install() -> None:
    install_import_hook()
