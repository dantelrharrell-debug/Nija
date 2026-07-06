from __future__ import annotations

import builtins
import logging
import sys
from functools import wraps
from types import ModuleType
from typing import Any, Iterable

logger = logging.getLogger("nija.direct_broker_metadata_guard")
_MARKER = "DIRECT_BROKER_METADATA_GUARD_PATCHED marker=20260706f"
_PATCHED_PROFILE_ATTR = "_nija_direct_broker_metadata_profile_guard_20260706f"
_PATCHED_DISPATCH_ATTR = "_nija_direct_broker_metadata_dispatch_guard_20260706f"

_BROKER_NAMES = {"coinbase", "kraken", "okx"}


def _norm(value: Any) -> str:
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
    }
    return aliases.get(compact, text)


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
        name = _norm(candidate)
        if name in _BROKER_NAMES:
            return name
    joined = " ".join(str(c or "") for c in candidates).lower()
    for name in ("coinbase", "kraken", "okx"):
        if name in joined:
            return name
    return ""


def _is_live_client(obj: Any, target: str) -> bool:
    if obj is None:
        return False
    if _infer_client_name(obj) != target:
        return False
    if getattr(obj, "connected", True) is False:
        return False
    methods = (
        "place_market_order",
        "place_order",
        "submit_order",
        "buy_market",
        "sell_market",
        "get_account_balance",
        "get_balance",
        "get_candles",
        "get_market_data",
        "get_positions",
    )
    return any(callable(getattr(obj, method, None)) for method in methods)


def _iter_values(value: Any) -> Iterable[Any]:
    if value is None:
        return ()
    if isinstance(value, dict):
        return value.values()
    if isinstance(value, (list, tuple, set, frozenset)):
        return value
    return (value,)


def _candidate_attrs(container: Any) -> Iterable[Any]:
    if container is None:
        return ()
    names = (
        "broker_client",
        "broker_adapter",
        "client",
        "adapter",
        "broker",
        "brokers",
        "_brokers",
        "broker_map",
        "_broker_map",
        "platform_brokers",
        "user_brokers",
        "connected_brokers",
        "active_brokers",
        "registered_brokers",
        "venue_brokers",
        "exchange_brokers",
        "GLOBAL_PLATFORM_BROKERS",
        "_PLATFORM_BROKER_INSTANCES",
        "_platform_brokers",
        "_platform_broker_instances",
    )
    out: list[Any] = []
    for name in names:
        try:
            out.extend(list(_iter_values(getattr(container, name, None))))
        except Exception:
            pass
    for method in (
        "get_all_brokers",
        "all_brokers",
        "get_brokers",
        "get_connected_brokers",
        "brokers_for_execution",
        "get_platform_brokers",
        "platform_broker_map",
    ):
        fn = getattr(container, method, None)
        if callable(fn):
            try:
                out.extend(list(_iter_values(fn())))
            except Exception:
                pass
    return out


def _enum_candidate(module: Any, target: str) -> Any:
    for enum_name in ("BrokerType", "Broker", "Venue"):
        enum_cls = getattr(module, enum_name, None)
        if enum_cls is None:
            continue
        for key in (target, target.upper(), target.capitalize()):
            try:
                val = getattr(enum_cls, key)
                if val is not None:
                    return val
            except Exception:
                pass
        try:
            for member in enum_cls:  # type: ignore[operator]
                if _norm(getattr(member, "value", member)) == target or _norm(getattr(member, "name", "")) == target:
                    return member
        except Exception:
            pass
    return None


def _call_get_platform_broker(module: Any, target: str) -> list[Any]:
    out: list[Any] = []
    fn = getattr(module, "get_platform_broker", None)
    if not callable(fn):
        return out
    args: list[Any] = [target, target.upper(), _enum_candidate(module, target)]
    for arg in args:
        if arg is None:
            continue
        try:
            out.append(fn(arg))
        except Exception:
            pass
    return out


def _module_candidates(target: str = "") -> Iterable[Any]:
    module_names = (
        "bot.broker_manager",
        "broker_manager",
        "bot.multi_account_broker_manager",
        "multi_account_broker_manager",
        "bot.multi_account",
        "multi_account",
        "bot.capital_authority",
        "capital_authority",
        "bot.coinbase_broker",
        "coinbase_broker",
        "bot.kraken_broker",
        "kraken_broker",
        "bot.okx_broker",
        "okx_broker",
    )
    out: list[Any] = []
    for name in module_names:
        try:
            module = sys.modules.get(name)
            if module is None:
                module = __import__(name, fromlist=["*"])
            out.append(module)
            if target:
                out.extend(_call_get_platform_broker(module, target))
            for attr in (
                "broker_manager",
                "multi_account_manager",
                "manager",
                "BROKER_MANAGER",
                "GLOBAL_PLATFORM_BROKERS",
                "_PLATFORM_BROKER_INSTANCES",
                "_PLATFORM_BROKER_CONNECTED",
                "coinbase_broker",
                "kraken_broker",
                "okx_broker",
                "capital_authority",
                "_capital_authority",
            ):
                try:
                    out.append(getattr(module, attr, None))
                except Exception:
                    pass
            for maker in ("get_multi_account_broker_manager", "get_multi_account_manager", "get_broker_manager", "get_capital_authority"):
                fn = getattr(module, maker, None)
                if callable(fn):
                    try:
                        out.append(fn())
                    except Exception:
                        pass
        except Exception:
            pass
    # Last-resort scan: only broker/account/capital modules to avoid walking the whole process graph.
    for name, module in list(sys.modules.items()):
        low = str(name).lower()
        if not any(token in low for token in ("broker", "account", "capital")):
            continue
        out.append(module)
    return out


def _scan_for_client(seed: Any, target: str) -> Any | None:
    seen: set[int] = set()
    queue: list[Any] = [seed]
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
        if len(seen) > 1000:
            break
        try:
            queue.extend(list(_candidate_attrs(obj)))
        except Exception:
            pass
    return None


def _resolve_live_client(router: Any, target: str) -> Any | None:
    target = _norm(target)
    resolver = getattr(router, "_resolve_live_broker", None)
    if callable(resolver):
        try:
            client = resolver(target)
            if _is_live_client(client, target):
                logger.critical("DIRECT_BROKER_METADATA_RESOLVED marker=20260706f source=router_resolver target=%s type=%s", target, type(client).__name__)
                return client
        except Exception as exc:
            logger.warning("DIRECT_BROKER_METADATA_RESOLVE_FAILED marker=20260706f target=%s error=%s", target, exc)
    client = _scan_for_client(router, target)
    if client is not None:
        logger.critical("DIRECT_BROKER_METADATA_RESOLVED marker=20260706f source=router_graph target=%s type=%s", target, type(client).__name__)
        return client
    for candidate in _module_candidates(target):
        client = _scan_for_client(candidate, target)
        if client is not None:
            logger.critical("DIRECT_BROKER_METADATA_RESOLVED marker=20260706f source=platform_registry target=%s type=%s", target, type(client).__name__)
            return client
    logger.critical("DIRECT_BROKER_METADATA_RESOLVE_UNAVAILABLE marker=20260706f target=%s", target)
    return None


def _preferred_name(request: Any, meta: dict[str, Any], router: Any) -> str:
    preferred = getattr(request, "preferred_broker", None) or meta.get("broker_name") or meta.get("preferred_broker")
    normalizer = getattr(router, "_normalize_broker_label", None)
    if callable(normalizer):
        try:
            return str(normalizer(preferred) or "")
        except Exception:
            pass
    return _norm(preferred)


def _set_request_meta(req: Any, meta: dict[str, Any]) -> None:
    try:
        setattr(req, "metadata", meta)
    except Exception:
        pass


def _meta_with_client(meta: dict[str, Any], target: str, client: Any) -> dict[str, Any]:
    updated = dict(meta)
    updated["broker_client"] = client
    updated.pop("broker_adapter", None)
    updated["broker_name"] = target
    updated["preferred_broker"] = target
    updated["direct_broker_metadata_guard"] = "replaced_mismatched_client"
    return updated


def _clean_meta_for_target(meta: dict[str, Any], target: str) -> dict[str, Any]:
    cleaned = dict(meta)
    cleaned.pop("broker_client", None)
    cleaned.pop("broker_adapter", None)
    cleaned["broker_name"] = target
    cleaned["preferred_broker"] = target
    cleaned["direct_broker_metadata_guard"] = "removed_mismatched_client"
    return cleaned


def _patch_router(module: ModuleType) -> bool:
    cls = getattr(module, "MultiBrokerExecutionRouter", None)
    if not isinstance(cls, type):
        return False
    patched = False

    original_profile = getattr(cls, "_profile_for_direct_broker", None)
    if callable(original_profile) and not getattr(original_profile, _PATCHED_PROFILE_ATTR, False):
        @wraps(original_profile)
        def _profile_for_direct_broker(self: Any, asset_class: Any, request: Any):
            meta = dict(getattr(request, "metadata", {}) or {})
            client = meta.get("broker_client") or meta.get("broker_adapter")
            client_name = _infer_client_name(client)
            target_name = _preferred_name(request, meta, self)
            if client is not None and client_name and target_name and client_name != target_name:
                replacement = _resolve_live_client(self, target_name)
                if replacement is not None:
                    repaired_meta = _meta_with_client(meta, target_name, replacement)
                    _set_request_meta(request, repaired_meta)
                    logger.critical(
                        "DIRECT_BROKER_METADATA_REPLACED marker=20260706f requested_broker=%s stale_client_broker=%s replacement_type=%s symbol=%s",
                        target_name,
                        client_name,
                        type(replacement).__name__,
                        getattr(request, "symbol", ""),
                    )
                    print(
                        f"[NIJA-PRINT] DIRECT_BROKER_METADATA_REPLACED marker=20260706f requested_broker={target_name} stale_client_broker={client_name} replacement_type={type(replacement).__name__} symbol={getattr(request, 'symbol', '')}",
                        flush=True,
                    )
                    return original_profile(self, asset_class, request)
                logger.critical(
                    "DIRECT_BROKER_METADATA_MISMATCH_SKIPPED marker=20260706f requested_broker=%s client_broker=%s symbol=%s reason=replacement_unavailable",
                    target_name,
                    client_name,
                    getattr(request, "symbol", ""),
                )
                print(
                    f"[NIJA-PRINT] DIRECT_BROKER_METADATA_MISMATCH_SKIPPED marker=20260706f requested_broker={target_name} client_broker={client_name} symbol={getattr(request, 'symbol', '')} reason=replacement_unavailable",
                    flush=True,
                )
                return None
            return original_profile(self, asset_class, request)

        setattr(_profile_for_direct_broker, _PATCHED_PROFILE_ATTR, True)
        setattr(cls, "_profile_for_direct_broker", _profile_for_direct_broker)
        patched = True

    original_dispatch = getattr(cls, "_dispatch_via_inner_router", None)
    if callable(original_dispatch) and not getattr(original_dispatch, _PATCHED_DISPATCH_ATTR, False):
        @wraps(original_dispatch)
        def _dispatch_via_inner_router(self: Any, *args: Any, **kwargs: Any):
            broker_name = _norm(kwargs.get("broker_name", args[5] if len(args) > 5 else ""))
            metadata = kwargs.get("metadata", args[6] if len(args) > 6 else None)
            meta = dict(metadata or {})
            client = meta.get("broker_client") or meta.get("broker_adapter")
            client_name = _infer_client_name(client)
            if client is not None and client_name and broker_name and client_name != broker_name:
                replacement = _resolve_live_client(self, broker_name)
                if replacement is not None:
                    meta = _meta_with_client(meta, broker_name, replacement)
                    logger.critical(
                        "DIRECT_BROKER_METADATA_REPLACED_AT_DISPATCH marker=20260706f broker=%s stale_client_broker=%s replacement_type=%s",
                        broker_name,
                        client_name,
                        type(replacement).__name__,
                    )
                    print(
                        f"[NIJA-PRINT] DIRECT_BROKER_METADATA_REPLACED_AT_DISPATCH marker=20260706f broker={broker_name} stale_client_broker={client_name} replacement_type={type(replacement).__name__}",
                        flush=True,
                    )
                else:
                    meta = _clean_meta_for_target(meta, broker_name)
                    logger.critical(
                        "DIRECT_BROKER_METADATA_CLEARED marker=20260706f broker=%s stale_client_broker=%s reason=replacement_unavailable",
                        broker_name,
                        client_name,
                    )
                    print(
                        f"[NIJA-PRINT] DIRECT_BROKER_METADATA_CLEARED marker=20260706f broker={broker_name} stale_client_broker={client_name} reason=replacement_unavailable",
                        flush=True,
                    )
                kwargs["metadata"] = meta
            return original_dispatch(self, *args, **kwargs)

        setattr(_dispatch_via_inner_router, _PATCHED_DISPATCH_ATTR, True)
        setattr(cls, "_dispatch_via_inner_router", _dispatch_via_inner_router)
        patched = True

    if patched:
        logger.warning("%s class=MultiBrokerExecutionRouter", _MARKER)
        print("[NIJA-PRINT] DIRECT_BROKER_METADATA_GUARD_PATCHED marker=20260706f", flush=True)
    return patched


def _try_patch_loaded() -> bool:
    patched = False
    for name in ("bot.multi_broker_execution_router", "multi_broker_execution_router"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            patched = _patch_router(module) or patched
    return patched


def install_import_hook() -> None:
    _try_patch_loaded()
    if getattr(builtins, "_NIJA_DIRECT_BROKER_METADATA_GUARD_HOOK_V20260706F", False):
        return
    original_import = builtins.__import__

    def guarded_import(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
        module = original_import(name, globals, locals, fromlist, level)
        try:
            if name.endswith("multi_broker_execution_router"):
                _try_patch_loaded()
            else:
                _try_patch_loaded()
        except Exception as exc:
            logger.warning("DIRECT_BROKER_METADATA_GUARD hook failed name=%s error=%s", name, exc)
        return module

    builtins.__import__ = guarded_import
    setattr(builtins, "_NIJA_DIRECT_BROKER_METADATA_GUARD_HOOK_V20260706F", True)
    logger.warning("DIRECT_BROKER_METADATA_GUARD_IMPORT_HOOK marker=20260706f")


def install() -> None:
    install_import_hook()
