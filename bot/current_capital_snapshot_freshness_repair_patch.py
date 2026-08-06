"""Repair freshness only for confirmed current live-broker snapshots.

The coordinator historically derives a new snapshot's freshness from the prior
authority snapshot age. This patch repairs that inherited stale flag when the
current refresh uses live values or a cached value backed by a successful live
observation inside the configured freshness TTL. Unknown or expired cached
capital remains explicitly stale and cannot be promoted.
"""
from __future__ import annotations

from datetime import datetime, timezone
import functools
import logging
import os
import sys
import threading
from typing import Any, Iterable

logger = logging.getLogger("nija.current_capital_snapshot_freshness_repair")

_MARKER = "20260802-current-capital-snapshot-freshness-v3"
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}
_LOCK = threading.RLock()
_INSTALLED = False
_ORIGINAL_INIT = None


def _truthy_env(name: str, default: str = "false") -> bool:
    return str(os.environ.get(name, default) or "").strip().lower() in _TRUE


def _snapshot_age_s(snapshot: Any) -> float:
    computed_at = getattr(snapshot, "computed_at", None)
    if not isinstance(computed_at, datetime):
        return 0.0
    if computed_at.tzinfo is None:
        computed_at = computed_at.replace(tzinfo=timezone.utc)
    return max(0.0, (datetime.now(timezone.utc) - computed_at).total_seconds())


def _confidence_ready(snapshot: Any) -> bool:
    confidence = getattr(snapshot, "confidence", None)
    band = getattr(confidence, "band", "")
    band_value = str(getattr(band, "value", band) or "").upper()
    return band_value in {"HIGH", "MEDIUM"}


def _broker_threshold(snapshot: Any) -> int:
    opportunistic = _truthy_env("NIJA_CAPITAL_OPPORTUNISTIC", "true")
    if opportunistic:
        return 1
    eligible_brokers = _eligible_broker_names(snapshot)
    if eligible_brokers:
        return max(1, len(eligible_brokers))
    try:
        return max(1, int(getattr(snapshot, "expected_brokers", 1) or 1))
    except Exception:
        return 1


def _capital_freshness_ttl_s() -> float:
    try:
        module = __import__(
            "bot.capital_flow_state_machine",
            fromlist=["FRESHNESS_TTL_S"],
        )
        return max(5.0, float(getattr(module, "FRESHNESS_TTL_S", 90.0) or 90.0))
    except Exception:
        return 90.0


def _normalize_broker_name(broker: Any) -> str:
    if broker is None:
        return ""
    if isinstance(broker, str):
        return broker.strip().lower()
    broker_type = getattr(broker, "broker_type", None)
    broker_type_value = getattr(broker_type, "value", None)
    if broker_type_value:
        return str(broker_type_value).strip().lower()
    name = getattr(broker, "name", None)
    if name:
        return str(name).strip().lower()
    value = getattr(broker, "value", None)
    if value:
        return str(value).strip().lower()
    return str(broker).strip().lower()


def _normalize_broker_names(brokers: Iterable[Any] | None) -> set[str]:
    if not brokers:
        return set()
    normalized = {_normalize_broker_name(broker) for broker in brokers}
    return {name for name in normalized if name}


def _eligible_broker_names(snapshot: Any) -> set[str]:
    eligible = _normalize_broker_names(getattr(snapshot, "eligible_brokers", None))
    if eligible:
        return eligible
    active = _normalize_broker_names(getattr(snapshot, "active_brokers", None))
    if active:
        return active
    return _normalize_broker_names(dict(getattr(snapshot, "broker_balances", {}) or {}).keys())


def _current_refresh_fallback_status(
    *,
    active_brokers: Iterable[Any] | None = None,
    eligible_brokers: Iterable[Any] | None = None,
) -> dict[str, Any]:
    relevant_brokers = _normalize_broker_names(eligible_brokers) or _normalize_broker_names(active_brokers)
    for name in (
        "bot.capital_refresh_stall_guard_v35",
        "capital_refresh_stall_guard_v35",
    ):
        module = sys.modules.get(name)
        status_getter = getattr(module, "current_refresh_fallback_status", None)
        if callable(status_getter):
            try:
                status = dict(status_getter(_capital_freshness_ttl_s()))
            except Exception:
                status = {
                    "used_fallback": True,
                    "all_recent": False,
                    "brokers": {},
                }
            return _filter_fallback_status(status, relevant_brokers)
        checker = getattr(module, "current_refresh_used_fallback", None)
        if callable(checker):
            try:
                used = bool(checker())
            except Exception:
                used = True
            return _filter_fallback_status({
                "used_fallback": used,
                "all_recent": False,
                "brokers": {},
            }, relevant_brokers)
    return _filter_fallback_status({
        "used_fallback": False,
        "all_recent": True,
        "brokers": {},
    }, relevant_brokers)


def _filter_fallback_status(status: dict[str, Any], relevant_brokers: set[str]) -> dict[str, Any]:
    brokers = dict(status.get("brokers", {}) or {})
    if relevant_brokers:
        brokers = {
            broker_name: broker_status
            for broker_name, broker_status in brokers.items()
            if _normalize_broker_name(broker_name) in relevant_brokers
        }
        used_fallback = bool(status.get("used_fallback") and brokers)
    else:
        used_fallback = bool(status.get("used_fallback"))
    ttl_s = _capital_freshness_ttl_s()
    all_recent = bool(
        not used_fallback
        or (
            brokers
            and all(
                bool(record.get("observed"))
                and float(record.get("age_s", float("inf"))) <= ttl_s
                for record in brokers.values()
            )
        )
    )
    filtered = dict(status)
    filtered["used_fallback"] = used_fallback
    filtered["all_recent"] = all_recent
    filtered["brokers"] = brokers
    return filtered


def _current_refresh_requires_stale() -> bool:
    status = _current_refresh_fallback_status()
    return bool(status.get("used_fallback") and not status.get("all_recent"))


def _should_repair(snapshot: Any) -> bool:
    if _current_refresh_requires_stale():
        return False
    try:
        real_capital = float(getattr(snapshot, "real_capital", 0.0) or 0.0)
        broker_count = int(getattr(snapshot, "broker_count", 0) or 0)
        broker_balances = dict(getattr(snapshot, "broker_balances", {}) or {})
        fresh_ttl_s = _capital_freshness_ttl_s()
    except Exception:
        return False

    return bool(
        getattr(snapshot, "is_stale", False)
        and not getattr(snapshot, "is_fresh", False)
        and real_capital > 0.0
        and broker_count >= _broker_threshold(snapshot)
        and any(float(value or 0.0) > 0.0 for value in broker_balances.values())
        and _confidence_ready(snapshot)
        and _snapshot_age_s(snapshot) <= max(5.0, fresh_ttl_s)
    )


def install_import_hook() -> bool:
    global _INSTALLED, _ORIGINAL_INIT
    with _LOCK:
        if _INSTALLED:
            return True

        try:
            try:
                from bot import capital_flow_state_machine as cfsm
            except ImportError:
                import capital_flow_state_machine as cfsm  # type: ignore[import]

            cls = getattr(cfsm, "CapitalSnapshot", None)
            if cls is None:
                return False
            current_init = getattr(cls, "__init__", None)
            if current_init is None:
                return False
            if bool(getattr(current_init, "_nija_current_snapshot_freshness_repair", False)):
                _INSTALLED = True
                return True

            _ORIGINAL_INIT = current_init

            @functools.wraps(current_init)
            def _init_with_current_freshness(self: Any, *args: Any, **kwargs: Any) -> None:
                current_init(self, *args, **kwargs)
                fallback_status = _current_refresh_fallback_status(
                    active_brokers=getattr(self, "active_brokers", None),
                    eligible_brokers=getattr(self, "eligible_brokers", None),
                )
                if bool(
                    fallback_status.get("used_fallback")
                    and not fallback_status.get("all_recent")
                ):
                    object.__setattr__(self, "is_fresh", False)
                    object.__setattr__(self, "is_stale", True)
                    logger.warning(
                        "CURRENT_CAPITAL_SNAPSHOT_CACHE_FALLBACK_STALE marker=%s "
                        "real=%.2f broker_count=%s fallback_brokers=%s",
                        _MARKER,
                        float(getattr(self, "real_capital", 0.0) or 0.0),
                        getattr(self, "broker_count", "unknown"),
                        fallback_status.get("brokers", {}),
                    )
                    return
                if not _should_repair(self):
                    return
                object.__setattr__(self, "is_fresh", True)
                object.__setattr__(self, "is_stale", False)
                object.__setattr__(self, "snapshot_age_s", 0.0)
                logger.warning(
                    "CURRENT_CAPITAL_SNAPSHOT_FRESHNESS_REPAIRED marker=%s "
                    "real=%.2f broker_count=%s confidence=%s fallback_recent=%s",
                    _MARKER,
                    float(getattr(self, "real_capital", 0.0) or 0.0),
                    getattr(self, "broker_count", "unknown"),
                    getattr(getattr(self, "confidence", None), "band", "unknown"),
                    bool(fallback_status.get("used_fallback")),
                )

            setattr(_init_with_current_freshness, "_nija_current_snapshot_freshness_repair", True)
            cls.__init__ = _init_with_current_freshness
            os.environ["NIJA_CURRENT_CAPITAL_SNAPSHOT_FRESHNESS_REPAIR"] = "1"
            _INSTALLED = True
            logger.warning(
                "CURRENT_CAPITAL_SNAPSHOT_FRESHNESS_REPAIR_INSTALLED marker=%s",
                _MARKER,
            )
            return True
        except Exception as exc:
            logger.warning(
                "CURRENT_CAPITAL_SNAPSHOT_FRESHNESS_REPAIR_FAILED marker=%s err=%s",
                _MARKER,
                exc,
                exc_info=True,
            )
            return False


def install() -> bool:
    return install_import_hook()


__all__ = ["install", "install_import_hook"]
