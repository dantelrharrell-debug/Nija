from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, Optional, Set, Tuple

logger = logging.getLogger("nija.execution.broker_capabilities")


@dataclass(frozen=True)
class BrokerCapability:
    supports_leverage: bool = True
    supports_margin_mode: bool = True
    supports_reduce_only: bool = True
    # Whether this broker supports short-selling on spot markets.
    # Kraken spot does NOT support shorting; Kraken futures/perps do.
    # Coinbase spot does NOT support shorting.
    supports_short: bool = True


# Broker-level defaults.  Kraken and Coinbase are spot-only by default and
# therefore cannot short.  The ``exchange_capabilities`` module provides
# symbol-level resolution (spot vs futures) for finer-grained checks.
_DEFAULT_CAPABILITIES: Dict[str, BrokerCapability] = {
    "coinbase": BrokerCapability(
        supports_leverage=False,
        supports_margin_mode=False,
        supports_reduce_only=True,
        supports_short=False,   # Coinbase spot: no shorting
    ),
    "kraken": BrokerCapability(
        supports_leverage=True,
        supports_margin_mode=True,
        supports_reduce_only=True,
        supports_short=False,   # Kraken spot: no shorting (futures/perps do)
    ),
    "okx": BrokerCapability(
        supports_leverage=True,
        supports_margin_mode=True,
        supports_reduce_only=True,
        supports_short=True,
    ),
    "binance": BrokerCapability(
        supports_leverage=True,
        supports_margin_mode=True,
        supports_reduce_only=True,
        supports_short=True,
    ),
    "alpaca": BrokerCapability(
        supports_leverage=False,
        supports_margin_mode=False,
        supports_reduce_only=True,
        supports_short=True,    # Alpaca supports stock shorting via locate/borrow
    ),
}

# Per-broker set of symbols that have been confirmed to NOT support shorting.
# Populated at runtime when a short order is rejected by the broker so that
# subsequent cycles skip the attempt without re-querying the exchange.
_SHORT_BLOCKED_PAIRS: Dict[str, Set[str]] = {}
_SHORT_BLOCKED_LOCK = threading.Lock()


def mark_short_unsupported(broker: str, symbol: str) -> None:
    """Record that *broker* does not support shorting *symbol*.

    Called by execution paths when a short order is rejected with a
    broker-level "shorting not supported" error.  Subsequent ``assess_short``
    calls for the same pair return ``False`` immediately without hitting the
    exchange again.
    """
    b = str(broker or "").strip().lower()
    s = str(symbol or "").strip().upper()
    if not b or not s:
        return
    with _SHORT_BLOCKED_LOCK:
        _SHORT_BLOCKED_PAIRS.setdefault(b, set()).add(s)
    logger.info(
        "BrokerCapabilityRegistry: short blocked for broker=%s symbol=%s "
        "(cached — future short attempts will be skipped)",
        b, s,
    )


def is_short_blocked(broker: str, symbol: str) -> bool:
    """Return True when *symbol* is in the cached short-blocked set for *broker*."""
    b = str(broker or "").strip().lower()
    s = str(symbol or "").strip().upper()
    with _SHORT_BLOCKED_LOCK:
        return s in _SHORT_BLOCKED_PAIRS.get(b, set())


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
                existing = self._capabilities.get(str(broker).strip().lower(), BrokerCapability())
                self._capabilities[str(broker).strip().lower()] = BrokerCapability(
                    supports_leverage=bool(item.get("supports_leverage", existing.supports_leverage)),
                    supports_margin_mode=bool(item.get("supports_margin_mode", existing.supports_margin_mode)),
                    supports_reduce_only=bool(item.get("supports_reduce_only", existing.supports_reduce_only)),
                    supports_short=bool(item.get("supports_short", existing.supports_short)),
                )
        except Exception as exc:
            logger.warning("broker capability overrides ignored: %s", exc)

    def get(self, broker: Optional[str]) -> BrokerCapability:
        b = str(broker or "coinbase").strip().lower() or "coinbase"
        return self._capabilities.get(b, BrokerCapability())

    def broker_supports_short(self, broker: Optional[str], symbol: str = "") -> bool:
        """Return True when *broker* can execute short orders for *symbol*.

        Checks both the broker-level capability flag and the runtime
        short-blocked cache populated by ``mark_short_unsupported()``.
        """
        b = str(broker or "coinbase").strip().lower() or "coinbase"
        cap = self.get(b)
        if not cap.supports_short:
            return False
        # Check the runtime cache for pair-level blocks.
        if symbol and is_short_blocked(b, symbol):
            return False
        # Delegate to exchange_capabilities for symbol-level resolution
        # (e.g. spot vs futures) when available.
        try:
            from bot.exchange_capabilities import can_short as _can_short
            return bool(_can_short(b, symbol))
        except ImportError:
            try:
                from exchange_capabilities import can_short as _can_short  # type: ignore[import]
                return bool(_can_short(b, symbol))
            except ImportError:
                pass
        return cap.supports_short

    def validate_pre_dispatch(self, request: Any) -> Tuple[bool, str]:
        broker = str(getattr(request, "preferred_broker", None) or "coinbase").strip().lower() or "coinbase"
        capability = self.get(broker)
        leverage = int(getattr(request, "leverage", 1) or 1)
        margin_mode = getattr(request, "margin_mode", None)
        reduce_only = getattr(request, "reduce_only", None)
        side = str(getattr(request, "side", "") or "").lower().strip()
        symbol = str(getattr(request, "symbol", "") or "").strip()

        if leverage > 1 and not capability.supports_leverage:
            return False, f"{broker}:leverage_unsupported"
        if margin_mode is not None and not capability.supports_margin_mode:
            return False, f"{broker}:margin_mode_unsupported"
        if reduce_only is not None and not capability.supports_reduce_only:
            return False, f"{broker}:reduce_only_unsupported"

        # Gate short orders on brokers/pairs that don't support them.
        # This prevents silent failures and repeated rejected attempts.
        if side in ("sell", "short") and not self.broker_supports_short(broker, symbol):
            logger.warning(
                "BrokerCapabilityRegistry: SHORT blocked for broker=%s symbol=%s "
                "— broker does not support shorting on this pair (spot market). "
                "Falling back to long-only trading for this symbol.",
                broker, symbol,
            )
            return False, f"{broker}:short_unsupported_for_{symbol or 'pair'}"

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
