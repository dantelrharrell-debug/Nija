"""NIJA execution-layer user/broker adapter.

This module is intentionally broker-agnostic.  New broker integrations register
an explicit client factory that returns a *canonical execution client* for one
user/account.  No placeholder balance, fake order success, or implicit broker
switching is allowed.

Canonical client contract
-------------------------
A registered factory must return an object exposing:

* ``get_account_balance()`` -> numeric or balance mapping;
* ``place_order(pair=..., side=..., size_usd=..., order_type=..., **kwargs)``;
* ``get_positions()``;
* ``close_position(pair=...)``.

The adapter validates user permissions and hard controls before calling that
client.  Missing credentials, missing factories, missing methods, or malformed
balances fail closed.  This makes the onboarding path safe for Kraken,
Coinbase, OKX, Alpaca, Binance, and future brokerages without adding another
``if broker == ...`` branch here.
"""

from __future__ import annotations

import logging
import math
import threading
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional

from auth import get_api_key_manager
from config import get_config_manager
from controls import get_hard_controls

logger = logging.getLogger("nija.execution.broker_adapter")

BrokerClientFactory = Callable[[str, Dict[str, Any]], Any]
_FACTORY_LOCK = threading.RLock()
_BROKER_CLIENT_FACTORIES: Dict[str, BrokerClientFactory] = {}


def _norm(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "_")


def register_broker_client_factory(
    broker_name: str,
    factory: BrokerClientFactory,
    *,
    replace: bool = False,
) -> None:
    """Register one explicit user-scoped broker client factory.

    ``replace=False`` prevents a later import from silently changing the live
    implementation for an already-registered broker.
    """
    name = _norm(broker_name)
    if not name:
        raise ValueError("broker_name is required")
    if not callable(factory):
        raise TypeError("factory must be callable")
    with _FACTORY_LOCK:
        if name in _BROKER_CLIENT_FACTORIES and not replace:
            raise RuntimeError(f"broker factory already registered: {name}")
        _BROKER_CLIENT_FACTORIES[name] = factory
    logger.info("BROKER_CLIENT_FACTORY_REGISTERED broker=%s replace=%s", name, replace)


def unregister_broker_client_factory(broker_name: str) -> None:
    """Remove a factory (primarily for tests/controlled reconfiguration)."""
    with _FACTORY_LOCK:
        _BROKER_CLIENT_FACTORIES.pop(_norm(broker_name), None)


def registered_broker_client_factories() -> tuple[str, ...]:
    with _FACTORY_LOCK:
        return tuple(sorted(_BROKER_CLIENT_FACTORIES))


def _coerce_balance(raw: Any) -> float:
    if isinstance(raw, dict):
        candidates = (
            raw.get("total_balance"),
            raw.get("total_funds"),
            raw.get("equity"),
            raw.get("balance"),
            raw.get("available_balance"),
            raw.get("available"),
        )
        value = next((item for item in candidates if item is not None), 0.0)
    else:
        value = raw
    try:
        amount = float(value or 0.0)
    except (TypeError, ValueError, OverflowError):
        return 0.0
    return amount if math.isfinite(amount) and amount >= 0.0 else 0.0


class SecureBrokerAdapter:
    """User-scoped broker adapter with permission and risk validation."""

    def __init__(self, user_id: str, broker_name: str):
        self.user_id = str(user_id or "").strip()
        self.broker_name = _norm(broker_name)
        if not self.user_id:
            raise ValueError("user_id is required")
        if not self.broker_name:
            raise ValueError("broker_name is required")

        self.api_key_manager = get_api_key_manager()
        self.config_manager = get_config_manager()
        self.hard_controls = get_hard_controls()
        self.broker_client: Any = None
        self._credentials_present = False
        self._load_broker_client()
        logger.info(
            "SECURE_BROKER_ADAPTER_INITIALIZED user=%s broker=%s client_ready=%s",
            self.user_id,
            self.broker_name,
            self.broker_client is not None,
        )

    def _load_broker_client(self) -> None:
        credentials = self.api_key_manager.get_user_api_key(
            self.user_id,
            self.broker_name,
        )
        self._credentials_present = bool(credentials)
        if not credentials:
            logger.warning(
                "SECURE_BROKER_ADAPTER_BLOCKED user=%s broker=%s reason=credentials_missing",
                self.user_id,
                self.broker_name,
            )
            return

        with _FACTORY_LOCK:
            factory = _BROKER_CLIENT_FACTORIES.get(self.broker_name)
        if factory is None:
            logger.error(
                "SECURE_BROKER_ADAPTER_BLOCKED user=%s broker=%s "
                "reason=broker_factory_not_registered registered=%s",
                self.user_id,
                self.broker_name,
                registered_broker_client_factories(),
            )
            return

        try:
            client = factory(self.user_id, dict(credentials))
        except Exception as exc:
            logger.error(
                "SECURE_BROKER_ADAPTER_FACTORY_FAILED user=%s broker=%s error=%s:%s",
                self.user_id,
                self.broker_name,
                type(exc).__name__,
                exc,
            )
            self.hard_controls.record_api_error(self.user_id)
            return

        required = (
            "get_account_balance",
            "place_order",
            "get_positions",
            "close_position",
        )
        missing = [name for name in required if not callable(getattr(client, name, None))]
        if missing:
            logger.error(
                "SECURE_BROKER_ADAPTER_BLOCKED user=%s broker=%s "
                "reason=canonical_client_contract_missing methods=%s",
                self.user_id,
                self.broker_name,
                ",".join(missing),
            )
            return

        self.broker_client = client
        logger.info(
            "SECURE_BROKER_ADAPTER_CLIENT_READY user=%s broker=%s client=%s",
            self.user_id,
            self.broker_name,
            type(client).__name__,
        )

    @property
    def execution_ready(self) -> bool:
        return bool(self._credentials_present and self.broker_client is not None)

    def _validate_trade_request(
        self,
        pair: str,
        position_size_usd: float,
        account_balance: float,
    ) -> tuple[bool, Optional[str]]:
        if not self.execution_ready:
            return False, "broker execution client is not ready"
        if not pair:
            return False, "trading pair is required"
        if not math.isfinite(float(position_size_usd)) or position_size_usd <= 0.0:
            return False, "position size must be positive and finite"
        if not math.isfinite(float(account_balance)) or account_balance <= 0.0:
            return False, "verified account balance unavailable"

        can_trade, error = self.hard_controls.can_trade(self.user_id)
        if not can_trade:
            return False, error

        can_trade, error = self.hard_controls.check_daily_trade_limit(self.user_id)
        if not can_trade:
            return False, error

        user_config = self.config_manager.get_user_config(self.user_id)
        if not user_config.can_trade_pair(pair):
            return False, f"Trading pair {pair} not allowed"

        valid, error = self.hard_controls.validate_position_size(
            self.user_id,
            position_size_usd,
            account_balance,
        )
        if not valid:
            return False, error

        valid, error = user_config.validate_position_size(position_size_usd)
        if not valid:
            return False, error

        max_daily_loss = user_config.get("max_total_exposure", 500.0) * 0.1
        valid, error = self.hard_controls.check_daily_loss_limit(
            self.user_id,
            max_daily_loss,
        )
        if not valid:
            return False, error

        return True, None

    def _verified_balance(self) -> tuple[float, Any]:
        if not self.execution_ready:
            return 0.0, None
        try:
            raw = self.broker_client.get_account_balance()
        except Exception as exc:
            logger.error(
                "SECURE_BROKER_BALANCE_FAILED user=%s broker=%s error=%s:%s",
                self.user_id,
                self.broker_name,
                type(exc).__name__,
                exc,
            )
            self.hard_controls.record_api_error(self.user_id)
            return 0.0, None
        return _coerce_balance(raw), raw

    def place_order(
        self,
        pair: str,
        side: str,
        size_usd: float,
        order_type: str = "market",
        **kwargs: Any,
    ) -> Optional[Dict[str, Any]]:
        side_norm = _norm(side)
        if side_norm not in {"buy", "sell"}:
            return {
                "success": False,
                "error": f"invalid side: {side}",
                "user_id": self.user_id,
                "broker": self.broker_name,
            }

        account_balance, _raw_balance = self._verified_balance()
        valid, error = self._validate_trade_request(pair, size_usd, account_balance)
        if not valid:
            logger.warning(
                "SECURE_BROKER_ORDER_BLOCKED user=%s broker=%s pair=%s reason=%s",
                self.user_id,
                self.broker_name,
                pair,
                error,
            )
            return {
                "success": False,
                "error": error,
                "user_id": self.user_id,
                "broker": self.broker_name,
                "pair": pair,
                "size_usd": size_usd,
            }

        try:
            result = self.broker_client.place_order(
                pair=pair,
                side=side_norm,
                size_usd=float(size_usd),
                order_type=order_type,
                **kwargs,
            )
        except Exception as exc:
            logger.error(
                "SECURE_BROKER_ORDER_FAILED user=%s broker=%s pair=%s error=%s:%s",
                self.user_id,
                self.broker_name,
                pair,
                type(exc).__name__,
                exc,
            )
            self.hard_controls.record_api_error(self.user_id)
            return {
                "success": False,
                "error": f"broker order exception: {type(exc).__name__}",
                "user_id": self.user_id,
                "broker": self.broker_name,
                "pair": pair,
            }

        if not isinstance(result, dict):
            return {
                "success": False,
                "error": "broker client returned malformed order result",
                "user_id": self.user_id,
                "broker": self.broker_name,
                "pair": pair,
            }

        # Do not convert an ambiguous broker response into success.  The
        # canonical client must explicitly report success/acceptance or a final
        # order status.  This is required for exchanges where transport timeout
        # can leave matching-engine status unknown.
        success = bool(result.get("success") or result.get("accepted"))
        status = _norm(result.get("status"))
        if status in {"filled", "open", "accepted", "new", "pending", "partially_filled"}:
            success = True
        if status in {"unknown", "timeout", "ambiguous"}:
            success = False
        result = dict(result)
        result.setdefault("success", success)
        result.setdefault("user_id", self.user_id)
        result.setdefault("broker", self.broker_name)
        result.setdefault("pair", pair)
        result.setdefault("submitted_at", datetime.now(timezone.utc).isoformat())
        return result

    def get_account_balance(self) -> Dict[str, Any]:
        balance, raw = self._verified_balance()
        if raw is None:
            return {
                "verified": False,
                "total_balance": 0.0,
                "available_balance": 0.0,
                "currency": "USD",
                "user_id": self.user_id,
                "broker": self.broker_name,
            }
        if isinstance(raw, dict):
            result = dict(raw)
        else:
            result = {"total_balance": balance, "available_balance": balance, "currency": "USD"}
        result["verified"] = True
        result.setdefault("total_balance", balance)
        result.setdefault("user_id", self.user_id)
        result.setdefault("broker", self.broker_name)
        return result

    def get_positions(self) -> list[Any]:
        if not self.execution_ready:
            return []
        try:
            positions = self.broker_client.get_positions()
        except Exception as exc:
            logger.error(
                "SECURE_BROKER_POSITIONS_FAILED user=%s broker=%s error=%s:%s",
                self.user_id,
                self.broker_name,
                type(exc).__name__,
                exc,
            )
            self.hard_controls.record_api_error(self.user_id)
            return []
        if isinstance(positions, dict):
            return list(positions.values())
        return list(positions or [])

    def close_position(self, pair: str) -> Optional[Dict[str, Any]]:
        if not self.execution_ready:
            return {
                "success": False,
                "error": "broker execution client is not ready",
                "user_id": self.user_id,
                "broker": self.broker_name,
                "pair": pair,
            }
        try:
            result = self.broker_client.close_position(pair=pair)
        except Exception as exc:
            logger.error(
                "SECURE_BROKER_CLOSE_FAILED user=%s broker=%s pair=%s error=%s:%s",
                self.user_id,
                self.broker_name,
                pair,
                type(exc).__name__,
                exc,
            )
            self.hard_controls.record_api_error(self.user_id)
            return {
                "success": False,
                "error": f"broker close exception: {type(exc).__name__}",
                "user_id": self.user_id,
                "broker": self.broker_name,
                "pair": pair,
            }
        if not isinstance(result, dict):
            return {
                "success": False,
                "error": "broker client returned malformed close result",
                "user_id": self.user_id,
                "broker": self.broker_name,
                "pair": pair,
            }
        payload = dict(result)
        payload.setdefault("user_id", self.user_id)
        payload.setdefault("broker", self.broker_name)
        payload.setdefault("pair", pair)
        return payload


__all__ = [
    "SecureBrokerAdapter",
    "register_broker_client_factory",
    "unregister_broker_client_factory",
    "registered_broker_client_factories",
]
