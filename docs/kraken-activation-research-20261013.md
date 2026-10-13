# NIJA Kraken activation: official-API research and gate disposition (2026-10-13)

This document is a review of restrictions, not permission to execute real orders. No existing historical data or proof timestamps may be rewritten.

## Verified production state

- Current deployed commit `5c976553a23897732e94bf79481bd41cbd1dc61c` remains in `RUNNING_SUPERVISED`.
- `execution_ready=False`, `execution_authority=False`, `trading_engine_ready=False` despite broker, capital, nonce, strategy and position-sync readiness.
- Proof age ~341,740 seconds against a configured 1,800-second limit (2026-10-13 06:51 UTC).
- 13 historical Kraken pending-close entries have authenticated matching broker-side fills/fees in isolated evidence, but NIJA strategy intent and canonical opening-position attribution remain unverified.
- Registered Kraken user-account protective snapshots intermittently fail `authoritative_position_fetch_unproven`; a transient passing audit does not certify continuous coverage.
- PR #3066 validation-only preflight passed hosted startup-safety CI; it is not imported into the deployed runtime and is not a real-order pathway.

## Restrictions that must remain

1. **Proof authenticity and 1,800-second freshness.** No clock reset, timestamp rewrite, replayed old fill, or accepting `AddOrder(validate=true)` as an execution. A live broker event is required.
2. **Exact platform account/key identity and nonce ownership.** `GetApiKeyInfo` returns account IIBAN, key and permission list. Compare authenticated hashes without logging sensitive values. No user account can be silently substituted.
3. **One-attempt durable latch and unknown-outcome reconciliation.** Never retry a possibly submitted order on timeout, restart, or nonce error without authenticating its broker order state.
4. **Hard entry cash cap, fee reserve, minimum order size, no leverage, protective exit verification and emergency stop.** Kraken conditional stop-limit is not a guaranteed loss limit, and exchange-side protection must be checked on actual fills.
5. **Historical provenance.** Preserve 13 records as broker-matched / strategy-unattributed until opening positions and original intents are proven. No invented strategy P&L.

## Legitimate simplifications to evaluate, without disabling controls

- **Remove duplicate polling and redundant identity checks only after instrumented evidence shows the same fresh account/key fingerprint is reused within one atomic, serialized attempt.** Preserve a final key/account assertion immediately before a live submission. Do not expand proof freshness.
- **Separate exchange-history reconciliation from readiness of an unrelated, fully verified platform account** only if a written cross-account risk review proves no shared exposure, accounting dependency, collateral, nonce writer, or protective coverage requirement. No global switch that ignores unresolved Kraken risk.
- **Use exact exchange order/fee responses instead of arbitrary higher internal minimums** once a current AssetPairs/TradeVolume read proves precision, order minimum and max fee. The `maxfee` field is documented under `TradeVolume.result.fees[canonical_pair]` and is a conservative taker fee; maker fee discounts should not be assumed.
- **Treat a registered-user account's intermittent snapshot failure as a data-fetch repair**, not permission to trade that user account or mark its protection as verified. Correct retry/backoff and account-specific observability after ensuring no live exposure is being hidden.

## Concrete execution path still required

1. Complete supervised production access to existing runtime and immutable ledger evidence. No repeat backup requirement.
2. Inspect account-locked strategy provenance and pending-close records, reconcile only supported facts; keep unknown facts explicitly unknown.
3. Integrate reviewed PR #3066 preflight into existing nonce owner with real current `GetApiKeyInfo`, `BalanceEx`, `OpenOrders`, `OpenPositions`, `TradeVolume`, `AssetPairs` and `AddOrder(validate=true)` responses. No order yet.
4. Independently review a one-shot live transport with exact fee-inclusive budget, account, pair, quantity, limit, conditional exit and approval receipt; validate native stop handling and durable one-attempt latch.
5. Obtain explicit approval for that **specific** capital-bearing order, reconcile actual fill/fees/exit, publish proof from actual broker event time, and only then reassess all execution gates. Do not infer such approval from a general request to 'activate NIJA'.
6. Deploy only reviewed and CI-passing code, observe account-by-account protections and rollback on mismatch. Keep manual kill-switch authority.

## Official exchange references

- https://docs.kraken.com/api/docs/rest-api/get-api-key-info
- https://docs.kraken.com/api/docs/rest-api/get-trade-volume
- https://docs.kraken.com/api/docs/rest-api/add-order
- https://docs.kraken.com/api/blog/cl-ord-id/
- https://docs.kraken.com/api/docs/rest-api/get-tradable-asset-pairs

**Important:** Kraken Futures `cancelallordersafter` is a different API from Kraken Spot `CancelAllOrdersAfter`. Never use Futures authentication/endpoint for a Spot startup attempt.
