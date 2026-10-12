# Account-scoped startup verification recovery

This change corrects startup account routing, duplicate capital-bearing attempts,
and exit sizing. It is preparation for an operator-reviewed recovery. It does not
authorize a trade or certify production readiness.

## Corrections

- Canonical platform adapters take precedence over legacy adapters on the same
  venue. Explicit user-account adapters cannot become startup candidates.
- The startup path authenticates Kraken account identity and permissions using
  the existing serialized private-call owner. A configured account fingerprint
  must match. Neither an account alias nor API-key possession proves legal
  ownership of the brokerage account.
- A SQLite attempt record on persistent storage consumes one attempt per real
  account before submission. A restart, new key, renamed alias, failed submission,
  unknown outcome, or completed attempt cannot silently rearm another buy.
- Exact order, trade and ledger references determine filled base quantity and
  fee-adjusted ownership. The close uses base quantity and explicit exit intent.
  Requested dollars or ticker prices are never promoted to filled quantity.
- An unresolved startup attempt cannot publish canonical activation proof. A
  confirmed buy alone cannot activate normal trading before its close is
  reconciled. Broker event timestamps remain the timestamps of proof.
- Read-only order validation always forces `validate=True`, rejects unexpected
  order IDs and explicitly reports that it is neither a fill nor ownership,
  approval, or cost certification.

## Operator prerequisites before any live startup order

1. Resolve the historical pending-close records from authenticated opening fills,
   fees and original account/strategy provenance. Do not invent missing history.
2. Verify the legal owner and the intended platform account independently, then
   bind the exact authenticated fingerprint. Never print raw account identity or
   API-key values into logs or a public pull request.
3. Specify and approve a numeric fee-inclusive total-cost limit. The existing
   `NIJA_HEARTBEAT_MAX_BUY_NOTIONAL_USD` guard bounds planned buy quote notional;
   it does not bound all fees or market slippage. This patch does not upgrade it
   into an all-in cost guarantee.
4. Validate a bounded order and a broker-supported protective exit for the exact
   account, pair, quantity and permissions. A conditional stop can become an
   independent order; a stop-limit can remain unfilled. Neither is a guaranteed
   maximum-loss mechanism. The current generic heartbeat market-order path must
   not be enabled as though it supplies native protection or a hard price bound.
5. Obtain explicit approval for the exact real-money plan, including its entry,
   closing leg and protection. Existing heartbeat flags or a read-only validation
   response are not that approval.
6. Complete human code review, hosted CI/security checks and a supervised
   deployment. Keep the single writer, nonce, capital, minimum-order, risk and
   emergency-stop checks enabled. Reconcile unknown outcomes before any retry.

## Persistence and rollback

`NIJA_STARTUP_ATTEMPT_DB` defaults to
`/data/startup_verification_attempts.db` and must be an absolute persistent path.
The attempt table is additive and separate from the trading ledger. Do not delete
or reset it to retry a startup order. Preserve it when reverting code or restoring
data. An unresolved attempt requires authenticated reconciliation and human
review; this change supplies no automatic retry or reset operation.

## Validation

The standalone regression suite uses synthetic authenticated responses and
SQLite databases. It exercises price changes, base and quote fees, missing and
wrong fill links, partial and pending results, account mismatches, concurrent
claims, restarts, corrupt storage, read-only validation and mid-round-trip proof
isolation. It does not connect to a brokerage or import runtime bootstrap. These
checks are execution replays, not an APEX strategy profitability backtest or a
live certification.

```bash
python -S bot/tests/test_startup_verification_evidence.py -q
```

Primary API references:

- <https://docs.kraken.com/api-reference/account-data/get-api-key-info>
- <https://docs.kraken.com/api-reference/account-data/query-orders-info>
- <https://docs.kraken.com/api-reference/account-data/query-trades-info>
- <https://docs.kraken.com/api-reference/account-data/query-ledgers>
- <https://docs.kraken.com/api-reference/trading/add-order>

No real-money order, production ledger restore, approval change or live restart
is included in this change.
