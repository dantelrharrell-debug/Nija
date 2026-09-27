"""Bitcoin payment rail for the standalone NIJA billing service.

Security boundaries
-------------------
* Browser-controlled prices, offer codes, and customer IDs are never authority.
* BitPay IPNs are treated only as a wake-up signal. Every notification is
  reconciled with BitPay's authenticated invoice-retrieval API before state
  changes.
* A verified Bitcoin payment never grants broker execution authority.
* Customer payments never target a brokerage deposit address. Funds settle to
  NIJA's merchant/treasury account first; brokerage sweeps are a separate,
  downstream treasury operation and are disabled in this service.
"""
from __future__ import annotations

import logging
import os
import secrets
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Callable, Iterable, Optional

import requests
from flask import Blueprint, jsonify, request

from pricing_policy import OFFERS

logger = logging.getLogger("nija.billing.bitcoin")

_BITPAY_VERSION = "2.0.0"
_VERIFIED_STATES = {"confirmed", "complete"}
_PENDING_STATES = {"new", "paid"}
_FAILED_STATES = {"expired", "invalid", "declined"}


class BitcoinBillingError(ValueError):
    """Raised when provider state violates NIJA's Bitcoin billing contract."""


class BitPayClient:
    """Minimal server-side BitPay POS-facade client.

    The POS token is kept server-side. BitPay invoice notifications are not
    signed, so callers must always retrieve the invoice before trusting status.
    """

    def __init__(
        self,
        token: str,
        *,
        base_url: str = "https://bitpay.com",
        timeout_seconds: float = 10.0,
        session: Optional[requests.Session] = None,
    ) -> None:
        token = str(token or "").strip()
        if not token:
            raise RuntimeError("BITPAY_POS_TOKEN is not configured")
        self.token = token
        self.base_url = str(base_url or "https://bitpay.com").rstrip("/")
        self.timeout_seconds = max(1.0, float(timeout_seconds))
        self.session = session or requests.Session()

    @classmethod
    def from_env(cls) -> "BitPayClient":
        return cls(
            os.getenv("BITPAY_POS_TOKEN", ""),
            base_url=os.getenv("BITPAY_API_BASE_URL", "https://bitpay.com"),
            timeout_seconds=float(os.getenv("BITPAY_TIMEOUT_SECONDS", "10")),
        )

    @staticmethod
    def _unwrap(payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise BitcoinBillingError("bitpay_response_invalid")
        data = payload.get("data", payload)
        if not isinstance(data, dict):
            raise BitcoinBillingError("bitpay_response_invalid")
        return data

    @property
    def headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-Accept-Version": _BITPAY_VERSION,
        }

    def create_invoice(
        self,
        *,
        amount_usd: Decimal,
        order_id: str,
        item_desc: str,
        notification_url: str,
        redirect_url: str,
        buyer_email: str,
    ) -> dict[str, Any]:
        payload = {
            "token": self.token,
            "price": float(amount_usd.quantize(Decimal("0.01"))),
            "currency": "USD",
            "orderId": order_id,
            "itemDesc": item_desc,
            "notificationURL": notification_url,
            "redirectURL": redirect_url,
            "buyer": {"email": buyer_email},
            "forcedBuyerSelectedTransactionCurrency": "BTC",
            "fullNotifications": True,
            "extendedNotifications": True,
            "transactionSpeed": os.getenv("NIJA_BITCOIN_TRANSACTION_SPEED", "medium"),
            # BitPay supports GUID idempotence for POST resources. Reusing NIJA's
            # durable order ID makes provider-side retries deterministic.
            "guid": order_id,
        }
        response = self.session.post(
            f"{self.base_url}/invoices",
            json=payload,
            headers=self.headers,
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        return self._unwrap(response.json())

    def retrieve_invoice(self, invoice_id: str) -> dict[str, Any]:
        response = self.session.get(
            f"{self.base_url}/invoices/{invoice_id}",
            params={"token": self.token},
            headers=self.headers,
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        return self._unwrap(response.json())


def _enabled() -> bool:
    return os.getenv("NIJA_BITCOIN_PAYMENTS_ENABLED", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _enabled_offers() -> set[str]:
    raw = os.getenv("NIJA_BITCOIN_ENABLED_OFFERS", "lessons")
    return {part.strip() for part in raw.split(",") if part.strip()}


def _amount_to_cents(value: Any) -> int:
    try:
        amount = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise BitcoinBillingError("bitpay_amount_invalid") from exc
    cents = int(amount * 100)
    if cents <= 0:
        raise BitcoinBillingError("bitpay_amount_invalid")
    return cents


def _invoice_id_from_ipn(payload: Any) -> Optional[str]:
    if not isinstance(payload, dict):
        return None
    direct = payload.get("id")
    if direct:
        return str(direct)
    event = payload.get("event")
    if isinstance(event, dict):
        data = event.get("data")
        if isinstance(data, dict) and data.get("id"):
            return str(data["id"])
    data = payload.get("data")
    if isinstance(data, dict) and data.get("id"):
        return str(data["id"])
    return None


def _btc_satoshis(invoice: dict[str, Any]) -> Optional[int]:
    for field in ("paymentTotals", "paymentSubtotals"):
        values = invoice.get(field)
        if isinstance(values, dict) and values.get("BTC") is not None:
            try:
                amount = int(values["BTC"])
                return amount if amount >= 0 else None
            except (TypeError, ValueError):
                return None
    return None


def _validate_authoritative_invoice(
    invoice: dict[str, Any],
    record: dict[str, Any],
) -> str:
    invoice_id = str(invoice.get("id") or "")
    if invoice_id != str(record.get("bitpay_invoice_id") or ""):
        raise BitcoinBillingError("bitpay_invoice_id_mismatch")
    if str(invoice.get("orderId") or "") != str(record.get("order_id") or ""):
        raise BitcoinBillingError("bitpay_order_id_mismatch")
    if str(invoice.get("currency") or "").upper() != "USD":
        raise BitcoinBillingError("bitpay_currency_mismatch")
    if _amount_to_cents(invoice.get("price")) != int(record["amount_usd_cents"]):
        raise BitcoinBillingError("bitpay_price_mismatch")

    status = str(invoice.get("status") or "").strip().lower()
    if status not in (_VERIFIED_STATES | _PENDING_STATES | _FAILED_STATES):
        raise BitcoinBillingError("bitpay_status_unknown")
    return status


def register_bitcoin_routes(
    app: Any,
    *,
    store_getter: Callable[[], Any],
    identity_loader: Callable[[], Any],
    identity_error_types: Iterable[type[BaseException]],
    site_url: Callable[[], str],
    client_factory: Callable[[], BitPayClient] = BitPayClient.from_env,
) -> None:
    """Register Bitcoin checkout, verification, and provider-notification routes."""
    blueprint = Blueprint("bitcoin_billing", __name__)
    identity_errors = tuple(identity_error_types)

    @blueprint.post("/api/billing/bitcoin/checkout")
    def create_bitcoin_checkout():
        if not _enabled():
            return jsonify({"error": "bitcoin_payments_disabled"}), 503

        try:
            identity = identity_loader()
        except identity_errors as exc:
            return jsonify({"error": str(exc)}), 401
        except RuntimeError:
            logger.exception("Bitcoin checkout identity configuration is incomplete")
            return jsonify({"error": "billing_temporarily_unavailable"}), 503

        offer = OFFERS.get(identity.offer_code)
        if offer is None or identity.offer_code not in _enabled_offers():
            return jsonify({"error": "bitcoin_offer_not_enabled"}), 409
        if offer.recurring and not _bool_env("NIJA_BITCOIN_ALLOW_RECURRING_ONE_TIME_PAYMENTS"):
            # Bitcoin cannot be pulled automatically for future renewals. Keep
            # recurring membership on Stripe until NIJA explicitly defines a
            # manual-renewal entitlement policy.
            return jsonify({"error": "bitcoin_recurring_offer_not_enabled"}), 409

        billing_public_url = os.getenv("NIJA_BILLING_PUBLIC_URL", "").strip().rstrip("/")
        if not billing_public_url.startswith("https://"):
            return jsonify({"error": "bitcoin_notification_url_not_configured"}), 503

        order_id = f"nija-btc-{secrets.token_urlsafe(18)}"
        store = store_getter()
        try:
            store.create_bitcoin_order(
                order_id=order_id,
                user_id=identity.user_id,
                email=identity.email,
                offer_code=identity.offer_code,
                amount_usd_cents=_amount_to_cents(offer.amount_usd),
                recurring=bool(offer.recurring),
            )
        except Exception:
            logger.exception("Could not create durable NIJA Bitcoin order")
            return jsonify({"error": "bitcoin_order_persistence_failed"}), 503

        try:
            provider = client_factory()
            invoice = provider.create_invoice(
                amount_usd=offer.amount_usd,
                order_id=order_id,
                item_desc=f"NIJA {identity.offer_code}",
                notification_url=f"{billing_public_url}/api/billing/bitcoin/webhook",
                redirect_url=f"{site_url()}/bitcoin-success",
                buyer_email=identity.email,
            )
            invoice_id = str(invoice.get("id") or "").strip()
            checkout_url = str(invoice.get("url") or "").strip()
            returned_order_id = str(invoice.get("orderId") or order_id)
            if not invoice_id or not checkout_url or returned_order_id != order_id:
                raise BitcoinBillingError("bitpay_invoice_response_incomplete")
            store.bind_bitcoin_invoice(
                order_id=order_id,
                invoice_id=invoice_id,
                invoice_url=checkout_url,
                provider_status=str(invoice.get("status") or "new").lower(),
            )
        except Exception as exc:
            logger.exception("BitPay invoice creation failed")
            try:
                store.set_bitcoin_order_error(order_id, "provider_create_failed", "bitpay_invoice_creation_failed")
            except Exception:
                logger.exception("Could not persist BitPay creation failure")
            return jsonify({"error": "bitcoin_checkout_creation_failed"}), 502

        return jsonify(
            {
                "payment_method": "bitcoin",
                "invoice_id": invoice_id,
                "checkout_url": checkout_url,
                "payment_verified": False,
                "entitlement_granted": False,
                "brokerage_sweep_allowed": False,
                "recurring_manual_renewal": bool(offer.recurring),
            }
        )

    @blueprint.get("/api/billing/bitcoin/verify")
    def verify_bitcoin_checkout():
        invoice_id = str(request.args.get("invoice_id") or "").strip()
        if not invoice_id:
            return jsonify({"error": "invoice_id_required"}), 400
        record = store_getter().bitcoin_verification_record(invoice_id)
        if record is None:
            return jsonify(
                {
                    "invoice_id": invoice_id,
                    "state": "pending",
                    "payment_verified": False,
                    "entitlement_granted": False,
                    "brokerage_sweep_allowed": False,
                }
            ), 404
        response = jsonify(record)
        response.headers["Cache-Control"] = "no-store, max-age=0"
        return response

    @blueprint.post("/api/billing/bitcoin/webhook")
    def bitpay_webhook():
        # BitPay does not sign invoice IPNs. The payload is only a trigger; never
        # use its status/price/order fields as authority.
        payload = request.get_json(silent=True) or {}
        invoice_id = _invoice_id_from_ipn(payload)
        if not invoice_id:
            return ("", 200)

        store = store_getter()
        record = store.get_bitcoin_order_by_invoice(invoice_id)
        if not record:
            # Unknown/generic provider invoices must not create NIJA state.
            return ("", 200)

        try:
            invoice = client_factory().retrieve_invoice(invoice_id)
        except Exception:
            logger.exception("Could not reconcile BitPay invoice %s", invoice_id)
            # Non-2xx asks the provider to retry the notification.
            return jsonify({"error": "bitcoin_reconciliation_failed"}), 503

        try:
            status = _validate_authoritative_invoice(invoice, record)
        except BitcoinBillingError as exc:
            logger.warning("Rejected BitPay invoice authority mismatch %s: %s", invoice_id, exc)
            store.update_bitcoin_order_state(
                invoice_id=invoice_id,
                provider_status=str(invoice.get("status") or "mismatch").lower(),
                verification_status="mismatch",
                verification_reason=str(exc),
                verified=False,
                treasury_status="hold",
                btc_paid_satoshis=_btc_satoshis(invoice),
            )
            return ("", 200)

        if status in _VERIFIED_STATES:
            treasury_status = (
                "provider_complete" if status == "complete" else "awaiting_provider_completion"
            )
            store.update_bitcoin_order_state(
                invoice_id=invoice_id,
                provider_status=status,
                verification_status="verified",
                verification_reason="bitpay_authoritative_invoice_verified",
                verified=True,
                treasury_status=treasury_status,
                btc_paid_satoshis=_btc_satoshis(invoice),
            )
        elif status in _FAILED_STATES:
            store.update_bitcoin_order_state(
                invoice_id=invoice_id,
                provider_status=status,
                verification_status="failed",
                verification_reason=f"bitpay_{status}",
                verified=False,
                treasury_status="hold",
                btc_paid_satoshis=_btc_satoshis(invoice),
            )
        else:
            store.update_bitcoin_order_state(
                invoice_id=invoice_id,
                provider_status=status,
                verification_status="pending",
                verification_reason="awaiting_bitpay_confirmation",
                verified=False,
                treasury_status="hold",
                btc_paid_satoshis=_btc_satoshis(invoice),
            )

        return ("", 200)

    app.register_blueprint(blueprint)
