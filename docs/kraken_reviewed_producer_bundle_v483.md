# NIJA v483 partial authenticated Kraken provider composition

This module groups the four already implemented account-bound, read-only Kraken producer factories (key permissions, identity, balance and open orders) using one existing nonce-owning broker. It **does not** install or register a collector, grant order authority, or change startup behavior. It is restricted to independently reviewed `platform:kraken` default-wallet mappings.

Production remains fail-closed: nine additional v452 fields must be bound from independently audited broker, ledger, writer, risk-governor and operator sources before `register_reviewed_account_registry` can be called. Actual account scopes, credential/IIBAN fingerprint pins, broker monitoring category and current complete independent ledger snapshot callback must come from the trusted running process and independent review; never set identity pins from live self-reports. All live protective exits and missing historical opening orders/fills/fees must be separately reconciled, with off-host restore verification.

Do not deploy just to toggle collector flags. Deployment alone does not install this module; after authorized integration and evidence review, the existing execution controller must independently certify readiness before live orders.
