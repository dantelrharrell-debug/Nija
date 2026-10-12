# Startup verification follow-up

This corrects the post-merge findings from PR #3050. It does not enable live
trading, submit an order, restore historical strategy attribution or bypass an
activation gate.

## Runtime corrections

- Resolve startup fill ledger entries through bounded authenticated `Ledgers`
  history. Match exact trade IDs in `refid`; do not assume `QueryTrades` returns
  ledger IDs. Limit the scan to eight 50-row pages and a 15-minute time window.
  An incomplete or changing page set fails closed.
- Check the durable startup attempt at the proof consumers as well as the
  publisher. A pre-existing fresh marker or cached ready verifier cannot grant
  activation during a claimed, pending, filled-but-unclosed or unknown attempt.
  Reapplying the v339 startup source installer preserves that check alongside
  the existing v169 provenance requirements and remains idempotent.
- Accept `Mapping` for the canonical platform broker collection. Production's
  `MappingProxyType` must not disappear from startup candidate selection.
- Derive the API-key identity with scrypt. The account fingerprint is unchanged,
  so the persistent one-time account latch is not reset by this change.

## Offline planning component

`bot/startup_verification_plan.py` checks immutable USD spot terms, an exact
operator receipt, the fee-inclusive cash-debit ceiling, account/key/symbol
binding, freshness, volume precision and protective-exit minima. It describes
limit/FOK entry and close orders and a stop-loss-limit protective order. Its
methods never submit an order. **It is not connected to the live pipeline.**

The selected $25 ceiling is a planning preference only. No real account IDs,
credentials, approval receipts or current trading recommendations are committed.
The test quantities and prices are synthetic. An operator receipt is an
attestation; its booleans are not independent proof of legal ownership or broker
validation. Check those facts using authenticated broker responses and primary
ownership evidence before recording any receipt.

`fciq` expresses a preference for fees in quote currency. It does not guarantee
the fee asset. The planner's maximum cash debit requires a fresh maximum broker
fee rate and explicitly budgeted cash reserves. A stop-loss-limit order can
remain unfilled in a price gap and does not guarantee a maximum realized loss.

## Remaining release and activation work

1. Obtain human review of the broker/startup/security changes and pass the full
   hosted CI and secret/security checks before merging. `AGENTS.md` requires it.
2. Implement and verify a canonical bounded startup transport with native
   protection, fee-adjusted owned quantity and verified protective-order handling
   before any separate closing order. The current Kraken market route can fall
   back to market; its notional cap excludes fees and does not satisfy the strict
   cash-debit requirement. Do not activate that route based on this planner.
3. Match the current authenticated broker account to the owner's primary Kraken
   statement through the existing nonce owner. Obtain fresh balances, holds,
   positions, open orders, pair minima/precision, fees and validation-only entry
   and protective-exit responses. Do not start a second private API client using
   the master key.
4. Keep historical broker facts separate from unproven strategy attribution.
   Missing journal entries cannot be reconstructed by guessing price, cost basis
   or strategy. Reconcile the outstanding records before treating them as closed.
5. Present the exact account-bound plan and obtain explicit real-money approval.
   Never convert the $25 planning selection or a successful validation-only
   response into order approval or execution proof.

## Primary API contracts checked

- https://docs.kraken.com/api-reference/account-data/get-ledgers-info
- https://docs.kraken.com/api-reference/account-data/get-trade-volume
- https://docs.kraken.com/api-reference/trading/add-order

## Rollback and verification

Revert the follow-up commit and keep startup/live orders disabled. Do not delete
or reset the durable attempt database, refresh a proof timestamp, or fabricate
fills. The key fingerprint format changes from SHA-256 to scrypt; any future
approved plan must bind the new freshly observed key fingerprint.

Run both standalone tests with `python -S`. They import no bot bootstrap, start
no runtime workers, require no credentials and place no real orders. The
dedicated workflow also compiles all changed runtime modules on Python 3.11.
