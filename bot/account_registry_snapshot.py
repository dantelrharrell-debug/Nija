"""Canonical, immutable account-registry status snapshots.

The broker manager and background connectivity monitors previously rebuilt
platform/user counts independently.  That allowed the same process to report
different answers for the same registry.  This module is deliberately free of
broker imports so every layer derives one snapshot without creating an import
cycle or another mutable registry.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple


def _label(value: Any) -> str:
    return str(getattr(value, "value", value) or "").strip().lower()


@dataclass(frozen=True)
class VenueAccountStatus:
    """Exact platform and user counts for one venue."""

    platform_registered: int
    platform_connected: int
    user_registered: int
    user_connected: int
    user_trading_eligible: int

    @property
    def all_registered_trading(self) -> bool:
        """Return true only when every registered account can trade."""

        return bool(
            self.platform_registered > 0
            and self.platform_connected == self.platform_registered
            and self.user_connected == self.user_registered
            and self.user_trading_eligible == self.user_registered
        )


@dataclass(frozen=True)
class AccountRegistrySnapshot:
    """Immutable aggregate view of the live platform/user registries."""

    platform_registered: int
    platform_connected: int
    user_registered: int
    user_connected: int
    user_trading_eligible: int
    user_failures: int
    user_without_credentials: int
    venues: Mapping[str, VenueAccountStatus]

    @property
    def platform_disconnected(self) -> int:
        return max(0, self.platform_registered - self.platform_connected)

    @property
    def user_disconnected(self) -> int:
        return max(0, self.user_registered - self.user_connected)

    @property
    def all_registered_trading(self) -> bool:
        return bool(
            self.platform_registered > 0
            and self.platform_connected == self.platform_registered
            and self.user_connected == self.user_registered
            and self.user_trading_eligible == self.user_registered
        )

    def venue(self, name: str) -> VenueAccountStatus:
        """Return one venue's status, or an all-zero status when absent."""

        return self.venues.get(
            str(name or "").strip().lower(),
            VenueAccountStatus(0, 0, 0, 0, 0),
        )

    def as_dict(self) -> Dict[str, Any]:
        """Return the compatibility dictionary used by existing loggers."""

        return {
            "platform_registered": self.platform_registered,
            "platform_connected": self.platform_connected,
            "platform_disconnected": self.platform_disconnected,
            "user_registered": self.user_registered,
            "user_connected": self.user_connected,
            "user_disconnected": self.user_disconnected,
            "user_trading_eligible": self.user_trading_eligible,
            "user_failures": self.user_failures,
            "user_without_credentials": self.user_without_credentials,
            "all_registered_trading": self.all_registered_trading,
        }


def _iter_mapping_items(value: Any) -> Iterable[Tuple[Any, Any]]:
    try:
        return tuple(value.items())
    except Exception:
        return ()


def build_account_registry_snapshot(
    manager: Any,
    connected_users: Optional[Dict[str, List[str]]] = None,
) -> AccountRegistrySnapshot:
    """Build one registry snapshot from a broker-manager instance.

    Failed registrations and missing credentials remain in the denominator.
    When ``connected_users`` is omitted, live connected broker objects are used
    as the trading-eligible view, excluding explicitly capital-blocked users.
    """

    platform_records: Dict[str, Any] = {}
    for broker_type, broker in _iter_mapping_items(
        getattr(manager, "_platform_brokers", {})
    ):
        venue = _label(broker_type)
        if venue:
            platform_records[venue] = broker
    for broker_type in tuple(getattr(manager, "_platform_failed_types", set()) or ()):
        venue = _label(broker_type)
        if venue:
            platform_records.setdefault(venue, None)

    user_records: Dict[Tuple[str, str], Any] = {}
    for key, broker in _iter_mapping_items(getattr(manager, "_all_user_brokers", {})):
        if not isinstance(key, tuple) or len(key) != 2:
            continue
        user_id, broker_type = key
        venue = _label(broker_type)
        if venue:
            user_records[(str(user_id), venue)] = broker
    for user_id, broker_map in _iter_mapping_items(getattr(manager, "user_brokers", {})):
        for broker_type, broker in _iter_mapping_items(broker_map):
            venue = _label(broker_type)
            if venue:
                user_records[(str(user_id), venue)] = broker
    for user_id, metadata in _iter_mapping_items(getattr(manager, "_user_metadata", {})):
        broker_map = metadata.get("brokers", {}) if isinstance(metadata, dict) else {}
        for broker_type, _value in _iter_mapping_items(broker_map):
            venue = _label(broker_type)
            if venue:
                user_records.setdefault((str(user_id), venue), None)
    for registry_name in ("_failed_user_connections", "_users_without_credentials"):
        registry = getattr(manager, registry_name, {}) or {}
        try:
            keys = tuple(registry)
        except Exception:
            keys = ()
        for key in keys:
            if not isinstance(key, tuple) or len(key) != 2:
                continue
            user_id, broker_type = key
            venue = _label(broker_type)
            if venue:
                user_records.setdefault((str(user_id), venue), None)

    if connected_users is None:
        capital_blocked_raw = set(
            getattr(manager, "_capital_blocked_users", {}) or {}
        )
        capital_blocked_users = {
            str(value[0] if isinstance(value, tuple) and value else value)
            for value in capital_blocked_raw
        }
        eligible_records = {
            key
            for key, broker in user_records.items()
            if bool(getattr(broker, "connected", False))
            and key[0] not in capital_blocked_users
        }
    else:
        eligible_records = {
            (str(user_id), str(venue).strip().lower())
            for venue, user_ids in (connected_users or {}).items()
            for user_id in user_ids
        }

    venue_names = sorted(
        set(platform_records)
        | {venue for _user_id, venue in user_records}
        | {venue for _user_id, venue in eligible_records}
    )
    venues: Dict[str, VenueAccountStatus] = {}
    for venue in venue_names:
        platform = [
            broker for name, broker in platform_records.items() if name == venue
        ]
        users = [
            broker for (_user_id, name), broker in user_records.items() if name == venue
        ]
        venues[venue] = VenueAccountStatus(
            platform_registered=len(platform),
            platform_connected=sum(
                1 for broker in platform if bool(getattr(broker, "connected", False))
            ),
            user_registered=len(users),
            user_connected=sum(
                1 for broker in users if bool(getattr(broker, "connected", False))
            ),
            user_trading_eligible=sum(
                1 for _user_id, name in eligible_records if name == venue
            ),
        )

    return AccountRegistrySnapshot(
        platform_registered=len(platform_records),
        platform_connected=sum(
            1
            for broker in platform_records.values()
            if bool(getattr(broker, "connected", False))
        ),
        user_registered=len(user_records),
        user_connected=sum(
            1
            for broker in user_records.values()
            if bool(getattr(broker, "connected", False))
        ),
        user_trading_eligible=len(eligible_records),
        user_failures=len(getattr(manager, "_failed_user_connections", {}) or {}),
        user_without_credentials=len(
            getattr(manager, "_users_without_credentials", {}) or {}
        ),
        venues=venues,
    )


__all__ = [
    "AccountRegistrySnapshot",
    "VenueAccountStatus",
    "build_account_registry_snapshot",
]
