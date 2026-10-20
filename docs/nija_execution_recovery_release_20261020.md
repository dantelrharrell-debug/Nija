# Authenticated execution recovery release repair — October 20, 2026 UTC

This repair is based on the deployed release commit
`bb6fe7c835aff364d746b2d9bfa8cea46aed4de2`, on
`release/justcall-handoff-only-20261017`. It does not change strategy decisions,
risk limits, writer/nonce authority, emergency stops, production configuration,
account holdings, ledger records, or the 1,800-second proof requirement.

## Repaired behavior

The known-order recovery worker previously retried one remembered pending order
or a historical fallback. The multi-candidate/missing-close-time changes from
merged main PR #3228 are ported as individual hunks. A bounded recent-order
search now supplements those remembered candidates:

- Resolve an unambiguous registered **platform Kraken broker instance**. User or
  shared/unknown broker ownership cannot produce platform evidence.
- Use its canonical authenticated private-read path for `ClosedOrders`, with
  `closetime=close` and a fixed 1,800-second window. An old opening time does not
  exclude an order that really closed recently.
- Inspect at most one page (50 rows), at most once per minute. Check at most ten
  newly discovered candidates, newest first. A full page is explicitly logged
  as possibly truncated; this search never certifies account-wide completeness.
- Require final `closed` status, positive finite executed volume/cost, valid
  side/pair and the genuine closure timestamp. The listing is only discovery:
  the exact `QueryOrders` row and existing canonical proof chain still decide
  whether there is execution evidence.
- Recheck order identity, authenticated reconciliation flags, platform ownership
  and broker-event freshness after enrichment. A failed/stale second lookup
  cannot inherit the first lookup's freshness. No observation timestamp is used
  to refresh an old fill. Missing or future close timestamps fail closed.
- Try other eligible pending IDs when a first candidate is stale/unavailable.
  Historical per-order cooldowns never block a different newly discovered ID.

The independent read-only recovery classifier now requires literal `True` for
kill-switch, startup-attempt, protective-exit and ledger attestations. Strings,
numbers, missing values and self-reported dictionaries cannot produce a
`VERIFICATION_COMPLETE` diagnostic. The classifier never authorizes orders.

API references checked for this repair:

- [Kraken ClosedOrders](https://docs.kraken.com/api-reference/account-data/get-closed-orders)
- [Kraken QueryOrders](https://docs.kraken.com/api-reference/account-data/query-orders-info)

## Independent production acceptance remains mandatory

Offline tests and a running deployment cannot certify live broker evidence.
Before starting observation, an authorized production review must separately
establish all of the following with retained, current evidence:

1. A genuine exact-account, exact-order authenticated execution proof with
   positive executed volume/cost and broker event age no greater than 1,800
   seconds. Absence of an eligible real order leaves execution blocked; this
   repair cannot create that order or use an old fill to satisfy freshness.
2. Broker-authenticated positions and protective-order readback for every
   actionable account position, including exact symbol, closing side, remaining
   quantity, active status and account ownership. Tracker protection labels and
   dust exemptions do not prove a live protective exit.
3. Reconciliation of entries, exits, fees, pending Kraken closes, cost basis,
   position quantities and ledger rows. SQLite structural integrity alone
   cannot establish historical completeness or realized P&L.
4. A consistent SQLite/WAL backup, independently verified off-host custody,
   isolated restore and restart durability. Never restore into or mutate the
   production ledger merely to make a check pass.
5. Independent operator authorization, writer fencing, nonce, current capital,
   broker health, risk and emergency-stop checks, followed by canonical readiness
   readback. Fresh execution evidence cannot substitute for these controls.

Production inspection at the start of this repair still reported stale execution
evidence (about 946,000 seconds), Kraken read timeouts, unverified independent
exit/ledger attestations and `/readyz` not established as ready. Observation has
not been certified as started. This document records a repair and acceptance
boundary, not a deployment or live trading certification.

## Validation and release boundary

The dedicated workflow exercises the repaired worker, canonical proof freshness,
strict independent attestations, protective-coverage rejection, startup evidence
isolation, ledger storage/inventory and isolated snapshot/restore regressions.
These are synthetic offline tests, not live transaction certification.

Required repository-specific local tools `runtime-tools-secret_scanning` and
`codeql_checker` are unavailable in this environment. The repair uses the
repository's existing detect-secrets scanner locally and a dedicated hosted
CodeQL job; neither unavailable tool is reported as having run.

Broker API integration changes require human review under `AGENTS.md`. Review
the exact release-branch diff and passing CI before merging. The Render service
uses manual deployments; a PR or merge is not production coverage. After an
approved release, inspect the live commit and each independent evidence source
again. No live orders, force activation, kill-switch clearing, state migration,
database repair, or deployment is performed by this patch.
