"""Replay actual sanitized Stripe sandbox receipts, not live transactions.

This validates the backend receipt predicate against provider-returned shapes.
It does not claim that a hosted backend received a signed Stripe webhook.
"""

from __future__ import annotations

import copy
import secrets

import pytest

from fixtures.stripe_iq72_sandbox import DISPUTED, LINES, PAID, REFUNDED
from game_sandbox.ionos import PublishedGame, build_published_report
from game_sandbox.service import Config, Denied, Sandbox


class RecordedProvider:
    """Read only recorded responses; no network or Stripe credentials."""

    def __init__(self, receipt: dict):
        self.receipt = copy.deepcopy(receipt)
        self.lines = copy.deepcopy(LINES)

    def purchase(self, session_id: str) -> tuple[dict, dict]:
        assert session_id == self.receipt["id"]
        return copy.deepcopy(self.receipt), copy.deepcopy(self.lines)


def service_for(tmp_path, receipt):
    config = Config(
        str(tmp_path / "trading_iq_sandbox.sqlite3"),
        "https://isolated.example",
        "rk_test_" + secrets.token_hex(24),
        "whsec_" + secrets.token_hex(24),
        "price_1UYToJRS5Ezp77RQVkx96eS5",  # pragma: allowlist secret - Stripe sandbox resource ID, not a credential
        "prod_nija_iq72_sandbox_v1",
        True,
    )
    return Sandbox(config, PublishedGame(), RecordedProvider(receipt), build_published_report)


@pytest.mark.parametrize("receipt,expected", [(PAID, True), (REFUNDED, False), (DISPUTED, False)])
def test_actual_provider_receipts_respect_payment_refund_and_dispute(tmp_path, receipt, expected):
    service = service_for(tmp_path, receipt)
    valid, intent = service.verified(receipt["id"], {"id": receipt["client_reference_id"]})
    assert valid is expected
    assert intent == receipt["payment_intent"]["id"]
    assert receipt["livemode"] is False
    assert receipt["amount_total"] == 100


def test_refunded_and_disputed_sessions_still_say_paid():
    for receipt in (REFUNDED, DISPUTED):
        assert receipt["status"] == "complete"
        assert receipt["payment_status"] == "paid"
    assert REFUNDED["payment_intent"]["latest_charge"]["amount_refunded"] == 100
    assert DISPUTED["payment_intent"]["latest_charge"]["disputed"] is True


def test_a_valid_receipt_cannot_be_reassigned_to_another_run(tmp_path):
    service = service_for(tmp_path, PAID)
    valid, _ = service.verified(PAID["id"], {"id": "another-owned-run"})
    assert valid is False


def test_a_different_price_cannot_reuse_this_paid_receipt(tmp_path):
    service = service_for(tmp_path, PAID)
    service.stripe.lines["data"][0]["price"]["id"] = "price_other_offer"
    valid, _ = service.verified(PAID["id"], {"id": PAID["client_reference_id"]})
    assert valid is False


def test_an_api_receipt_without_a_signed_webhook_grants_no_report(tmp_path):
    service = service_for(tmp_path, PAID)
    run, owner, _ = service.start(True)
    with pytest.raises(Denied, match="verified_webhook_required"):
        service.report(run, owner)
