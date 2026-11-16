"""Sanitized snapshots read from NIJA Stripe sandbox after hosted test payments.
No customer data, card data, secrets or Checkout URLs. These are recorded API
receipts, not synthetic payment statuses or evidence of a hosted webhook test.
"""

PAID = {
    "amount_total": 100,
    "client_reference_id": "iq72_processor_test_20261105_01",
    "currency": "usd",
    "id": "cs_test_a1rIX1L0JTSp8XwlhUTqL5r6xYyNfwAwJzK2jKZtIsme3hrWQbi9uIYICs",  # pragma: allowlist secret - Stripe sandbox resource ID, not a credential
    "livemode": False,
    "metadata": {
        "manifest": "fe6b84326e9c9401a7f3f658d4c29441e3505ee52b94d615b991a88a610f1c90",  # pragma: allowlist secret - public manifest SHA-256
        "offer": "nija-unified-iq-sandbox-v1",
        "run_id": "iq72_processor_test_20261105_01",
        "version": "ionos-served-iq72-e881c2de98a88e6c",
    },
    "mode": "payment",
    "payment_intent": {
        "amount_received": 100,
        "currency": "usd",
        "id": "pi_3UYTrDRS5Ezp77RQ02966rOT",  # pragma: allowlist secret - Stripe sandbox resource ID, not a credential
        "latest_charge": {
            "amount_refunded": 0,
            "disputed": False,
            "id": "ch_3UYTrDRS5Ezp77RQ0WuHlLhk",  # pragma: allowlist secret - Stripe sandbox resource ID, not a credential
            "livemode": False,
            "paid": True,
            "refunded": False,
            "status": "succeeded",
        },
        "livemode": False,
        "status": "succeeded",
    },
    "payment_status": "paid",
    "status": "complete",
}

REFUNDED = {
    "amount_total": 100,
    "client_reference_id": "iq72_processor_test_20261105_01",
    "currency": "usd",
    "id": "cs_test_a1rIX1L0JTSp8XwlhUTqL5r6xYyNfwAwJzK2jKZtIsme3hrWQbi9uIYICs",  # pragma: allowlist secret - Stripe sandbox resource ID, not a credential
    "livemode": False,
    "metadata": {
        "manifest": "fe6b84326e9c9401a7f3f658d4c29441e3505ee52b94d615b991a88a610f1c90",  # pragma: allowlist secret - public manifest SHA-256
        "offer": "nija-unified-iq-sandbox-v1",
        "run_id": "iq72_processor_test_20261105_01",
        "version": "ionos-served-iq72-e881c2de98a88e6c",
    },
    "mode": "payment",
    "payment_intent": {
        "amount_received": 100,
        "currency": "usd",
        "id": "pi_3UYTrDRS5Ezp77RQ02966rOT",  # pragma: allowlist secret - Stripe sandbox resource ID, not a credential
        "latest_charge": {
            "amount_refunded": 100,
            "disputed": False,
            "id": "ch_3UYTrDRS5Ezp77RQ0WuHlLhk",  # pragma: allowlist secret - Stripe sandbox resource ID, not a credential
            "livemode": False,
            "paid": True,
            "refunded": True,
            "status": "succeeded",
        },
        "livemode": False,
        "status": "succeeded",
    },
    "payment_status": "paid",
    "status": "complete",
}

DISPUTED = {
    "amount_total": 100,
    "client_reference_id": "iq72_processor_dispute_20261105_01",
    "currency": "usd",
    "id": "cs_test_a1sqzhVkUr8UQaonKWccPF8gu1BWCWdj6bQa37EolNlyBctDwqN7pgBXBB",  # pragma: allowlist secret - Stripe sandbox resource ID, not a credential
    "livemode": False,
    "metadata": {
        "manifest": "fe6b84326e9c9401a7f3f658d4c29441e3505ee52b94d615b991a88a610f1c90",  # pragma: allowlist secret - public manifest SHA-256
        "offer": "nija-unified-iq-sandbox-v1",
        "run_id": "iq72_processor_dispute_20261105_01",
        "version": "ionos-served-iq72-e881c2de98a88e6c",
    },
    "mode": "payment",
    "payment_intent": {
        "amount_received": 100,
        "currency": "usd",
        "id": "pi_3UYTwQRS5Ezp77RQ1qNRq05Q",  # pragma: allowlist secret - Stripe sandbox resource ID, not a credential
        "latest_charge": {
            "amount_refunded": 0,
            "disputed": True,
            "id": "ch_3UYTwQRS5Ezp77RQ1LEJOc6A",  # pragma: allowlist secret - Stripe sandbox resource ID, not a credential
            "livemode": False,
            "paid": True,
            "refunded": False,
            "status": "succeeded",
        },
        "livemode": False,
        "status": "succeeded",
    },
    "payment_status": "paid",
    "status": "complete",
}

LINES = {
    "data": [
        {
            "adjustable_quantity": None,
            "amount_discount": 0,
            "amount_subtotal": 100,
            "amount_tax": 0,
            "amount_total": 100,
            "currency": "usd",
            "description": "NIJA Trading IQ Personalized Report — Sandbox",
            "id": "li_1UYTpaRS5Ezp77RQ82LmD7aS",  # pragma: allowlist secret - Stripe sandbox resource ID, not a credential
            "metadata": {},
            "object": "item",
            "price": {
                "active": True,
                "billing_scheme": "per_unit",
                "created": 1793897207,
                "currency": "usd",
                "custom_unit_amount": None,
                "id": "price_1UYToJRS5Ezp77RQVkx96eS5",  # pragma: allowlist secret - Stripe sandbox resource ID, not a credential
                "livemode": False,
                "lookup_key": "nija_iq72_sandbox_usd100_v1",
                "metadata": {"environment": "sandbox", "offer": "nija-unified-iq-sandbox-v1"},
                "nickname": "Sandbox: one-time USD 1 for the existing 72-decision report",
                "object": "price",
                "product": "prod_nija_iq72_sandbox_v1",
                "recurring": None,
                "tax_behavior": "unspecified",
                "tiers_mode": None,
                "transform_quantity": None,
                "type": "one_time",
                "unit_amount": 100,
                "unit_amount_decimal": "100",
            },
            "quantity": 1,
        }
    ],
    "has_more": False,
    "object": "list",
    "url": "/v1/checkout/sessions/cs_test_a1rIX1L0JTSp8XwlhUTqL5r6xYyNfwAwJzK2jKZtIsme3hrWQbi9uIYICs/line_items",  # pragma: allowlist secret - Stripe sandbox resource ID, not a credential
}
