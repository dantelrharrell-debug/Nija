# Durable clearance and authenticated spot position synchronization

These are executable provider implementations wired into the existing v487
collector factory. They do not install themselves, grant execution authority,
clear a stop, adopt positions, or replace NIJA's existing execution writer.
The seven existing provider factories and v474 registration boundary remain.

## Production observations and limits

Read-only Render shell observation on 2026-11-02 at 20:26:37 UTC:

- Commit `258e5bc6e41f43fbbf94ad0939878e351e8f3f6d`.
- Durable kill-switch record present, schema 2, `is_active=false`, reason and
  timestamp present, Redis PTTL `-1`. This is state, not independent approval.
- Most recent canonical identity request
  `8715d1935c8c49209fda526777f66443` completed with
  `authenticated_api_key_identity_missing`. No configured key was substituted
  for the missing authenticated response field.

The operational ledger lacks the account/key attribution and exchange protective
IDs required by the existing ledger provider. The reviewed Redis inventory
manifest was absent in the prior authenticated inspection. Independent general
operator records, complete account risk snapshots, approved source bindings and
current backup/restore certification remain prerequisites. This change does not
establish any of them. Production collector installation remains unverified.

## Implementations

`kraken_kill_switch_evidence.make_kraken_kill_switch_provider` reads the existing
Redis client and kill-switch object. The binding includes the exact account,
API-key fingerprint, provider ID, durable key and independently approved
clearance-record digest. Its review callback must validate the actual object
binding and the legitimacy of the clearance, including global-to-account scope.
It must not be implemented as an unconditional true callback in production.

The provider requires an explicit schema-2 cleared record with a reason and
timezone-aware historical event timestamp. Its digest uses sorted compact UTF-8
JSON and rejects duplicate JSON fields and nonfinite values. Redis WATCH spans
local status reads and a read-only GET/PTTL transaction, so Redis modifications
including change-and-revert deny the observation. Missing, expiring, active,
unapproved, malformed or changed records deny. Local file, in-memory and
deployment stops also veto. It calls `get_status`, never the potentially mutating
`is_active`, and performs no Redis data writes. PTTL `-1` proves no key expiry,
not disk persistence, backup durability or cross-store atomicity.

`kraken_position_sync_evidence.make_kraken_position_sync_provider` uses the
canonical broker's existing private-call method. Independently pinned identity
brackets two Balance/OpenPositions reads and two ledger/runtime snapshots.
It compares exact Decimal quantities across exchange balances, reconciled
ledger lots and the adopted v285 runtime inventory. It preserves the oldest
source timestamp and any stricter ledger or configured runtime expiry.
Changes in source content/generation, malformed rows, missing adoption,
staleness, unsupported holdings and quantity mismatches deny.

Supported scope matches the existing ledger implementation: default platform
wallet, long BTC/USD and ETH/USD spot inventory with USD cash. Nonzero margin,
other assets, earn/staked variants and ambiguous asset aliases deny. This is
not complete coverage for all Kraken products or member accounts. An empty
OpenPositions response alone never certifies empty spot inventory. A matched
flat spot account can pass this one check, but existing protective-exit and
other providers still enforce their own requirements.

## Existing factory connection

`compose_reviewed_kraken_providers` retains its original API accepting all six
independent remaining providers. Its optional new arguments are
`kill_switch_binding` and `review_kill_switch_binding`.

When those arguments are supplied, `independent_remaining` must contain exactly:

| Requirement | Existing implementation / source owner |
|---|---|
| position_ledger_reconciliation | `make_kraken_ledger_evidence_provider` / independent ledger |
| duplicate_order_fence | `RedisEvidenceReader.collect` / writer authority |
| operator_authorization | `make_general_operator_authorization_provider` / operator authority |
| risk_limits | `make_kraken_risk_limits_provider` / risk governor |

The factory constructs the other two providers against the existing broker,
independent reconciled-position reader and approved clearance binding. It checks
the clearance account/key/provider pins against its existing registry. It
rejects ambiguous extra providers, missing callables and reused provider IDs.
Construction performs no broker/Redis reads and does not register a collector;
the external clearance review callback is consulted.

After independent source review and production change authorization, the trusted
composition root must supply real bindings and use the unchanged
`install_reviewed_kraken_collector` / `register_reviewed_account_registry` path.
Every source is read and validated there before installation. Do not fabricate
the required backup/restore, ledger/exit or independent-review approvals.
Registration still does not authorize new orders.

## Verified research used

- [Kraken GetApiKeyInfo](https://docs.kraken.com/api-reference/account-data/get-api-key-info)
  documents `apiKey` and `iban`. No documented missing-field fallback was found.
- [Kraken OpenPositions](https://docs.kraken.com/api-reference/account-data/get-open-positions)
  explicitly describes open **margin** positions, not a spot inventory ledger.
- [Kraken Ledgers](https://docs.kraken.com/api-reference/account-data/get-ledgers-info)
  documents cursor pagination with a null count; keep cursor exhaustion checks.
- [Redis transactions](https://redis.io/docs/latest/develop/using-commands/transactions/)
  describes WATCH invalidation and atomic execution. WATCH does not make SQLite
  and exchange reads part of one transaction.
- [TinyFish research report](https://agent.tinyfish.ai/playground/research/share/01a19dec-4ac9-7fd3-b51c-25f86d0a79f4)
  supplied a broader source survey. Recommendations were checked against the
  authoritative pages and existing NIJA contracts, not applied wholesale.

## Validation and required review

Local Python 3.12 focused providers, existing four sources, composition,
registration and v452/six-source validation: **293 passed, 7 skipped,
458 subtests passed**. The skipped tests require a real local Redis server,
which was unavailable. Fixtures are synthetic and do not certify production.
Both new suites are included in the mandatory CI selection for Python 3.11.
Changed Python files compile; Bandit reports no findings. Hosted CI/security
results must be checked on the actual PR head. The named local
`runtime-tools-secret_scanning` and `codeql_checker` tools are unavailable;
detect-secrets and hosted security checks are used and separately reported.

Per AGENTS.md, Redis guard and broker integration changes require human review
before merge. No trading logic, risk parameters or order submission paths change.
No current live certification or successful trade is claimed.
