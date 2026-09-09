"""Deterministic user-account sharding and per-worker capacity guard.

This patch does not change trading strategy, risk thresholds, writer authority,
position protection, or order routing.  It only filters *new user broker
connections* before authenticated broker I/O so a worker owns a deterministic
subset of enabled users.

Safety properties:
- stable SHA-256 user -> shard assignment (no Python hash randomization)
- fail closed on invalid shard configuration
- hard per-worker admission ceiling
- overflow users are not connected for new entries on that worker
- already-connected brokers/positions are never deleted or disconnected
- no order is submitted/cancelled and no execution authority is granted
"""
from __future__ import annotations

import hashlib
import importlib
import logging
import os
import threading
from typing import Any, Iterable, List

LOGGER = logging.getLogger("nija.runtime_user_sharding_capacity_v410")
MARKER = "20260909-runtime-user-sharding-capacity-v410"
_READY_FLAG = "NIJA_USER_SHARDING_CAPACITY_V410_READY"
_PATCH_ATTR = "_nija_user_sharding_capacity_v410"
_LOCK = threading.RLock()
_CALL_LOCK = threading.RLock()


def _int_env(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = str(os.environ.get(name, str(default)) or str(default)).strip()
    try:
        value = int(raw)
    except Exception:
        raise ValueError(f"{name}_invalid:{raw}")
    if value < minimum or value > maximum:
        raise ValueError(f"{name}_out_of_range:{value}")
    return value


def _config() -> tuple[int, int, int]:
    shard_count = _int_env("NIJA_USER_SHARD_COUNT", 1, 1, 64)
    shard_index = _int_env("NIJA_USER_SHARD_INDEX", 0, 0, shard_count - 1)
    max_users = _int_env("NIJA_MAX_USERS_PER_SHARD", 25, 1, 1000)
    return shard_count, shard_index, max_users


def shard_for_user(user_id: str, shard_count: int) -> int:
    text = str(user_id or "").strip().lower()
    if not text:
        raise ValueError("empty_user_id")
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big", signed=False) % int(shard_count)


def _sorted_users(users: Iterable[Any]) -> List[Any]:
    return sorted(
        list(users or []),
        key=lambda user: str(getattr(user, "user_id", "") or "").strip().lower(),
    )


def _select_users(users: Iterable[Any]) -> tuple[List[Any], List[Any], dict[str, Any]]:
    shard_count, shard_index, max_users = _config()
    assigned: List[Any] = []
    for user in _sorted_users(users):
        user_id = str(getattr(user, "user_id", "") or "").strip()
        if not user_id:
            continue
        if shard_for_user(user_id, shard_count) == shard_index:
            assigned.append(user)

    admitted = assigned[:max_users]
    overflow = assigned[max_users:]
    meta = {
        "shard_count": shard_count,
        "shard_index": shard_index,
        "max_users": max_users,
        "assigned": len(assigned),
        "admitted": len(admitted),
        "overflow": len(overflow),
    }
    return admitted, overflow, meta


def _loader() -> Any:
    module = importlib.import_module("config.user_loader")
    getter = getattr(module, "get_user_config_loader", None)
    if not callable(getter):
        raise RuntimeError("user_loader_getter_missing")
    loader = getter()
    if loader is None or not callable(getattr(loader, "get_all_enabled_users", None)):
        raise RuntimeError("user_loader_contract_missing")
    return loader


def _patch_manager_class(cls: type) -> bool:
    original = getattr(cls, "connect_users_from_config", None)
    if not callable(original):
        return False
    if bool(getattr(original, _PATCH_ATTR, False)):
        return True

    def guarded(self: Any, *args: Any, **kwargs: Any) -> Any:
        # Serialize loader substitution within a process.  This guard changes no
        # global trading state and exists only around configuration discovery.
        with _CALL_LOCK:
            try:
                loader = _loader()
                loader_get = getattr(loader, "get_all_enabled_users")
                all_users = list(loader_get() or [])
                admitted, overflow, meta = _select_users(all_users)
            except Exception as exc:
                os.environ[_READY_FLAG] = "0"
                LOGGER.exception(
                    "USER_SHARD_V410_BLOCKED marker=%s reason=config_or_loader_error error=%s:%s "
                    "new_user_connections=false existing_positions_untouched=true trading_gates_unchanged=true",
                    MARKER,
                    type(exc).__name__,
                    exc,
                )
                return {}

            overflow_ids = [str(getattr(u, "user_id", "") or "") for u in overflow]
            if overflow:
                LOGGER.error(
                    "USER_SHARD_V410_CAPACITY_BLOCK marker=%s shard=%s/%s assigned=%s admitted=%s overflow=%s "
                    "overflow_users=%s new_user_connections_fail_closed=true existing_positions_untouched=true",
                    MARKER,
                    meta["shard_index"],
                    meta["shard_count"],
                    meta["assigned"],
                    meta["admitted"],
                    meta["overflow"],
                    overflow_ids[:20],
                )

            # Patch only this singleton loader instance for the duration of the
            # canonical method.  The original connection logic, platform-first
            # checks, nonce resync, capital audit, and broker construction remain
            # authoritative and unchanged.
            def local_enabled_users() -> List[Any]:
                return list(admitted)

            setattr(loader, "get_all_enabled_users", local_enabled_users)
            try:
                result = original(self, *args, **kwargs)
            finally:
                setattr(loader, "get_all_enabled_users", loader_get)

            try:
                setattr(self, "_nija_user_shard_meta_v410", dict(meta))
                setattr(self, "_nija_user_shard_overflow_v410", tuple(overflow_ids))
            except Exception:
                pass

            os.environ[_READY_FLAG] = "1"
            LOGGER.critical(
                "USER_SHARD_V410_STATE marker=%s shard=%s/%s assigned=%s admitted=%s overflow=%s "
                "stable_hash=sha256 per_worker_capacity=%s existing_positions_untouched=true "
                "orders_submitted=false orders_cancelled=false authority_granted=false safety_gates_bypassed=false",
                MARKER,
                meta["shard_index"],
                meta["shard_count"],
                meta["assigned"],
                meta["admitted"],
                meta["overflow"],
                meta["max_users"],
            )
            return result

    setattr(guarded, _PATCH_ATTR, True)
    setattr(guarded, "__wrapped__", original)
    setattr(cls, "connect_users_from_config", guarded)
    return True


def install() -> bool:
    with _LOCK:
        try:
            # Validate configuration even if MABM has not loaded yet.
            shard_count, shard_index, max_users = _config()
            module = importlib.import_module("bot.multi_account_broker_manager")
            cls = getattr(module, "MultiAccountBrokerManager", None)
            if not isinstance(cls, type) or not _patch_manager_class(cls):
                os.environ[_READY_FLAG] = "0"
                LOGGER.warning(
                    "USER_SHARD_V410_DEFERRED marker=%s reason=mabm_contract_not_loaded trading_fail_closed=true",
                    MARKER,
                )
                return False
            os.environ[_READY_FLAG] = "1"
            LOGGER.critical(
                "USER_SHARD_V410_READY marker=%s shard=%s/%s max_users_per_shard=%s stable_hash=sha256 "
                "platform_writer_unchanged=true risk_gates_unchanged=true exits_unchanged=true "
                "orders_submitted=false forced_activation=false safety_gates_bypassed=false",
                MARKER,
                shard_index,
                shard_count,
                max_users,
            )
            return True
        except Exception as exc:
            os.environ[_READY_FLAG] = "0"
            LOGGER.exception(
                "USER_SHARD_V410_INSTALL_ERROR marker=%s error=%s:%s trading_fail_closed=true",
                MARKER,
                type(exc).__name__,
                exc,
            )
            return False


install_import_hook = install

__all__ = ["MARKER", "install", "install_import_hook", "shard_for_user"]
