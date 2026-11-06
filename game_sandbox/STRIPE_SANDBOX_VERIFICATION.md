# Stripe sandbox verification — November 5, 2026

Actual Stripe-hosted Checkout tests were completed in the connected **Nija Ai Trading sandbox**, `livemode=false`. No real funds moved, and no production checkout or live resources were changed.

| Check | Verified result |
| --- | --- |
| Dedicated report product | Six challenges × twelve rounds, 72 decisions; adult-only optional report; free game preserved |
| Price | `price_1UYToJRS5Ezp77RQVkx96eS5`: USD 100 cents, one time, active, sandbox only |
| Hosted payment | Checkout completed; PaymentIntent succeeded; 100 cents received; charge initially unrefunded and undisputed |
| Full refund | 100-cent refund succeeded; subsequent API read reports `refunded=true` and `amount_refunded=100` |
| Dispute scenario | Stripe's documented dispute-test card produced a succeeded sandbox payment and a 100-cent fraudulent dispute with `needs_response` status |
| Receipt verification | Backend predicate accepts the recorded paid receipt and rejects the actual refunded/disputed records |
| Fail-closed access | A recorded API receipt alone never grants a report without an owned run and durable signed-webhook entitlement |

Sanitized provider snapshots are retained in `tests/fixtures/stripe_iq72_sandbox.py`. They contain only verification fields and sandbox resource IDs; no customer/card data, secret keys, Checkout URLs or browser ownership proofs. The tests replay these captured records; they do not fabricate successful provider states.

Both refunded and disputed Checkout Sessions continue to report `payment_status=paid`. The backend correctly checks the expanded charge rather than granting access from that field or a return URL alone.

The hosted Checkout tests used a synthetic buyer and Stripe's published test cards. Payment-information saving was disabled. Their return URLs point to the existing free game; the public report remains Coming Soon. These sessions tested the payment processor, not an installed IONOS paid-report flow.

## Still unverified

A dedicated hosted game staging service has not been deployed with its sandbox restricted API key and endpoint signing secret. The connected Stripe app authorizes this session's API operations but does not install server credentials into Render. The only currently registered sandbox webhook targets the separate course sandbox; it was not repurposed. Actual Stripe webhook delivery to the new game service, cookie-bound report access across Checkout and full browser reopening remain required before release. Existing simulated signed-webhook/ownership/reopening tests remain distinct from the processor evidence above.

Sandbox configuration identifiers are in `sandbox_offer.json`; that file contains no keys and enables no checkout. Production payments remain disabled for this new integration. PR/release checks and separate production approval are still required.
