# v482 reviewed Kraken open-order producer — release-only proposal

This change adds one opt-in, read-only provider for the v452 `open_order_reconciliation` field. The trusted composition root must bind:
- The existing, serialized nonce-owning Kraken client and its monitoring request category.
- Independently approved Kraken API-key/IIBAN SHA-256 pins and exact account scope.
- A separately audited **independent ledger** snapshot callback with a verified immutable snapshot ID and zero unresolved submissions; never derive it from broker orders.
- Review-approved provider identities for distinct authority classes.

The producer reads identity before and after two complete OpenOrders retrieval passes, brackets them with two complete independently reviewed ledger snapshots, requires strict equality and freshness (60 seconds), and returns only redacted v452-compatible evidence. Missing cursor proof or a different actual API schema denies certification. Endpoint pagination semantics and all fee/order-type variations must be independently validated against the live Kraken API before enabling the provider. Passing unit tests cannot prove live API compatibility.

Not installed at startup, not registered into the production collector, not a pretrade/admission override, not a historical trade/lot/fee ledger reconciler, not a protective-exit readback, and not execution authority. The broader collector still requires all 13 independent checks for every registered account.

## Release acceptance
1. Confirm current authenticated Kraken API return schema and cursor support using approved read-only evidence without logging private rows. If cursor proof is not supported, retain fail-closed and revise implementation with reviewed API-complete enumeration.
2. Independently bind the current ledger and pending/open-intent snapshot; reconcile legacy pending closes, original fills and fees, position lots, and protective exits separately.
3. Complete real per-account production provider composition (all 13 fields) with reviewed bindings, current off-host restore evidence and approved account mapping.
4. Review all CI and secret-scanning checks, verify exact release diff, and obtain separate production release approval.
5. After any deployment, independently certify scope, producer, ledger, orders, exits, writer/nonce/risk/operator gates. Existing execution controller makes the decision. Never fabricate a test trade or clear a kill switch to force readiness.
