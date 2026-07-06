from __future__ import annotations

import builtins
import logging
import sys
from functools import wraps
from types import ModuleType
from typing import Any

logger = logging.getLogger("nija.direct_broker_metadata_guard")
_MARKER = "DIRECT_BROKER_METADATA_GUARD_PATCHED marker=20260706a"
_PATCHED_PROFILE_ATTR = "_nija_direct_broker_metadata_profile_guard_20260706a"
_PATCHED_DISPATCH_ATTR = "_nija_direct_broker_metadata_dispatch_guard_20260706a"


def _norm(value: Any) -> str:
    text = str(value or "").strip().lower()
    compact = text.replace("-", "").replace("_", "").replace(" ", "")
    aliases = {
        "coinbasebrokeradapter": "coinbase",
        "coinbasebroker": "coinbase",
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
        getattr(client, "NAME", None),
        getattr(client, "name", None),
        getattr(client, "broker_name", None),
        client.__class__.__name__,
        client.__class__.__module__,
    )
    for candidate in candidates:
        name = _norm(candidate)
        if name in {"coinbase", "kraken", "okx"}:
            return name
    joined = " ".join(str(c or "") for c in candidates).lower()
    for name in ("coinbase", "kraken", "okx"):
        if name in joined:
            return name
    return ""


def _preferred_name(request: Any, meta: dict[str, Any], router: Any) -> str:
    preferred = getattr(request, "preferred_broker", None) or meta.get("broker_name") or meta.get("preferred_broker")
    normalizer = getattr(router, "_normalize_broker_label", None)
    if callable(normalizer):
        try:
            return str(normalizer(preferred) or "")
        except Exception:
            pass
    return _norm(preferred)


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
                logger.critical(
                    "DIRECT_BROKER_METADATA_MISMATCH_SKIPPED marker=20260706a requested_broker=%s client_broker=%s symbol=%s",
                    target_name,
                    client_name,
                    getattr(request, "symbol", ""),
                )
                print(
                    f"[NIJA-PRINT] DIRECT_BROKER_METADATA_MISMATCH_SKIPPED marker=20260706a requested_broker={target_name} client_broker={client_name} symbol={getattr(request, 'symbol', '')}",
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
                meta = _clean_meta_for_target(meta, broker_name)
                kwargs["metadata"] = meta
                logger.critical(
                    "DIRECT_BROKER_METADATA_CLEARED marker=20260706a broker=%s stale_client_broker=%s",
                    broker_name,
                    client_name,
                )
                print(
                    f"[NIJA-PRINT] DIRECT_BROKER_METADATA_CLEARED marker=20260706a broker={broker_name} stale_client_broker={client_name}",
                    flush=True,
                )
            return original_dispatch(self, *args, **kwargs)

        setattr(_dispatch_via_inner_router, _PATCHED_DISPATCH_ATTR, True)
        setattr(cls, "_dispatch_via_inner_router", _dispatch_via_inner_router)
        patched = True

    if patched:
        logger.warning("%s class=MultiBrokerExecutionRouter", _MARKER)
        print("[NIJA-PRINT] DIRECT_BROKER_METADATA_GUARD_PATCHED marker=20260706a", flush=True)
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
    if getattr(builtins, "_NIJA_DIRECT_BROKER_METADATA_GUARD_HOOK", False):
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
    setattr(builtins, "_NIJA_DIRECT_BROKER_METADATA_GUARD_HOOK", True)
    logger.warning("DIRECT_BROKER_METADATA_GUARD_IMPORT_HOOK marker=20260706a")


def install() -> None:
    install_import_hook()
