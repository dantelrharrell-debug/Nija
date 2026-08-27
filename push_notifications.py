"""Provider-neutral push notification architecture for NIJA mobile clients.

The application can register APNs/FCM provider implementations later without
changing mobile route logic. Until credentials/provider implementations are
configured, delivery fails closed and reports ``not_configured`` rather than
pretending a notification was sent.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol

from mobile_device_store import get_mobile_device_store

logger = logging.getLogger("nija.push")


class PushProvider(Protocol):
    def is_configured(self) -> bool: ...

    def send(self, token: str, title: str, body: str, data: Dict[str, Any]) -> str: ...


@dataclass
class PushDeliveryResult:
    requested: int = 0
    sent: int = 0
    failed: int = 0
    not_configured: int = 0
    invalid_devices: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.sent > 0 and self.failed == 0,
            "requested": self.requested,
            "sent": self.sent,
            "failed": self.failed,
            "not_configured": self.not_configured,
        }


class UnconfiguredPushProvider:
    """Fail-closed placeholder used until APNs/FCM credentials are installed."""

    def __init__(self, platform: str) -> None:
        self.platform = platform

    def is_configured(self) -> bool:
        return False

    def send(self, token: str, title: str, body: str, data: Dict[str, Any]) -> str:
        raise RuntimeError(f"{self.platform} push provider is not configured")


class PushNotificationService:
    def __init__(self, providers: Optional[Dict[str, PushProvider]] = None) -> None:
        self.providers: Dict[str, PushProvider] = providers or {
            "ios": UnconfiguredPushProvider("APNs"),
            "android": UnconfiguredPushProvider("FCM"),
        }

    def register_provider(self, platform: str, provider: PushProvider) -> None:
        if platform not in {"ios", "android"}:
            raise ValueError("platform must be ios or android")
        self.providers[platform] = provider

    def send_to_user(
        self,
        user_id: str,
        title: str,
        body: str,
        data: Optional[Dict[str, Any]] = None,
    ) -> PushDeliveryResult:
        devices = get_mobile_device_store().list_devices(user_id, include_tokens=True)
        result = PushDeliveryResult(requested=len(devices))
        payload = data or {}

        for device in devices:
            platform = device.get("platform")
            provider = self.providers.get(str(platform))
            if provider is None or not provider.is_configured():
                result.not_configured += 1
                continue

            try:
                status = provider.send(
                    str(device["push_token"]), title, body, payload
                )
                if status == "invalid_token":
                    result.failed += 1
                    result.invalid_devices.append(str(device["device_id"]))
                else:
                    result.sent += 1
            except Exception as exc:
                result.failed += 1
                logger.warning(
                    "Push delivery failed user_id=%s device_id=%s platform=%s error=%s",
                    user_id,
                    device.get("device_id"),
                    platform,
                    type(exc).__name__,
                )

        # Provider-confirmed invalid tokens are revoked so they are not retried.
        store = get_mobile_device_store()
        for device_id in result.invalid_devices:
            store.unregister_device(user_id, device_id)

        return result


_service: Optional[PushNotificationService] = None


def get_push_notification_service() -> PushNotificationService:
    global _service
    if _service is None:
        _service = PushNotificationService()
    return _service


__all__ = [
    "PushProvider",
    "PushDeliveryResult",
    "PushNotificationService",
    "get_push_notification_service",
]
