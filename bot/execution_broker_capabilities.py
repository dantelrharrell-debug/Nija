from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger("nija.execution.broker_capabilities")


@dataclass(frozen=True)
class BrokerCapability:
    supports_leverage: bool = True
    supports_margin_mode: bool = True
    supports_reduce_only: bool = True


_DEFAULT_CAPABILITIES: Dict[str, BrokerCapability] = {
    "coinbase": BrokerCapability(supports_leverage=False, supports_margin_mode=False, supports_reduce_only=True),
    "kraken": BrokerCapability(supports_leverage=True, supports_margin_mode=True, supports_reduce_only=True),
    "okx": BrokerCapability(supports_leverage=True, supports_margin_mode=True, supports_reduce_only=True),
    "binance": BrokerCapability(supports_leverage=True, supports_margin_mode=True, supports_reduce_only=True),
    "alpaca": BrokerCapability(supports_leverage=False, supports_margin_mode=False, supports_reduce_only=True),
}


class BrokerCapabilityRegistry:
    def __init__(self) -> None:
        self._capabilities: Dict[str, BrokerCapability] = dict(_DEFAULT_CAPABILITIES)
        self._load_overrides_from_env()

    def _load_overrides_from_env(self) -> None:
        raw = str(os.getenv("NIJA_BROKER_CAPABILITIES_JSON", "") or "").strip()
        if not raw:
            return
        try:
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                return
            for broker, item in payload.items():
                if not isinstance(item, dict):
                    continue
                self._capabilities[str(broker).strip().lower()] = BrokerCapability(
                    supports_leverage=bool(item.get("supports_leverage", True)),
                    supports_margin_mode=bool(item.get("supports_margin_mode", True)),
                    supports_reduce_only=bool(item.get("supports_reduce_only", True)),
                )
        except Exception as exc:
            logger.warning("broker capability overrides ignored: %s", exc)

    def get(self, broker: Optional[str]) -> BrokerCapability:
        b = str(broker or "coinbase").strip().lower() or "coinbase"
        return self._capabilities.get(b, BrokerCapability())

    def validate_pre_dispatch(self, request: Any) -> Tuple[bool, str]:
        broker = str(getattr(request, "preferred_broker", None) or "coinbase").strip().lower() or "coinbase"
        capability = self.get(broker)
        leverage = int(getattr(request, "leverage", 1) or 1)
        margin_mode = getattr(request, "margin_mode", None)
        reduce_only = getattr(request, "reduce_only", None)

        if leverage > 1 and not capability.supports_leverage:
            return False, f"{broker}:leverage_unsupported"
        if margin_mode is not None and not capability.supports_margin_mode:
            return False, f"{broker}:margin_mode_unsupported"
        if reduce_only is not None and not capability.supports_reduce_only:
            return False, f"{broker}:reduce_only_unsupported"
        return True, "ok"


_REGISTRY_SINGLETON: Optional[BrokerCapabilityRegistry] = None
_REGISTRY_LOCK = threading.Lock()


def get_broker_capability_registry() -> BrokerCapabilityRegistry:
    global _REGISTRY_SINGLETON
    if _REGISTRY_SINGLETON is not None:
        return _REGISTRY_SINGLETON
    with _REGISTRY_LOCK:
        if _REGISTRY_SINGLETON is None:
            _REGISTRY_SINGLETON = BrokerCapabilityRegistry()
    return _REGISTRY_SINGLETON
