# Kraken identity transport freshness recovery

## Change and production evidence

On 2026-11-02 the deployed release was `b9d3e7f810e325a721a7825317efcb212c46af0d`,
Render deployment `dep-dbkb6dtg1s2s738t2jgg`, service `srv-d98dsr5aeets73fpbaqg`.
An existing, canonical, read-only identity request completed after 134.42 seconds
with `observation_clock_invalid_or_stale`. Source inspection found that v480
started its 60-second observation clock before rate admission. Existing runtime
read gates can deliberately wait 60 seconds before reaching the private API.
The receipt does not separately measure network latency, so this is a verified
source defect and plausible explanation of that failure, not a claim that a
production transport measurement has already proved the fix.

The canonical GetApiKeyInfo branch now records the start of its existing
`api.query_private` invocation after broker lock/rate/jitter admission. v480
accepts that timestamp only for one call, the same API object, the same returned
response object, ordered finite wall-clock values, and at most 60 seconds of
both wall and monotonic elapsed time through provider validation. Internal API
wrapper waits and retries still count against the deadline. Uninstrumented
and remote gateway paths retain the conservative whole-call deadline.

This changes no rate limits, nonces, writer locks, trading flags, provider
registration, account pins, signature requirements, orders, or ledger data.
Synthetic canonical-method regressions prove 134 seconds of admission waiting
plus a two-second read is stamped at transport start, not at completion. Slow
HTTP, post-read delays, clock rollback/freeze, response substitution, API swaps,
and repeated reads fail closed. Mutations retain both deadline checks and nonce
ownership validation. Thread-local capture is cleaned up after exceptions.

## Official research and application

Reviewed 2026-11-02:

| Source | Application |
| --- | --- |
| [Kraken GetApiKeyInfo](https://docs.kraken.com/api/docs/rest-api/get-api-key-info) | Use the authenticated existing broker to compare independently approved key/account pins; do not construct a second client. |
| [Kraken REST limits](https://docs.kraken.com/exchange/guides/rest/ratelimits) | Preserve admission scheduling; waiting before a request does not date the exchange observation. Do not reduce delays merely to make certification pass. |
| [Kraken TradesHistory](https://docs.kraken.com/api-reference/account-data/get-trades-history) | Cursor completeness and taker consolidation semantics need explicit reconciliation with actual persisted fill IDs. Do not reinterpret missing history as empty history. |
| [Redis distributed locks](https://redis.io/docs/latest/develop/clients/patterns/distributed-locks/) | Existing key-scoped writer lease, owner tokens, generation checks, and durability must remain authoritative; a live process or generic missing lock key proves neither ownership nor absence. |
| [SQLite Online Backup API](https://sqlite.org/backup.html) and [Render disks](https://render.com/docs/disks) | Use consistent database-native snapshots and isolated restores. Disk snapshots alone do not certify SQLite/Redis/JSON cross-store recovery. |
| [CodeQL weak-sensitive-data-hashing](https://codeql.github.com/codeql-query-help/python/py-weak-sensitive-data-hashing/) | Distinguish password-derived verifier storage from high-entropy API identifier fingerprint comparison; retain independent security review. |

## CodeQL 20153 triage for independent review

Alert [20153](https://github.com/dantelrharrell-debug/Nija/security/code-scanning/20153)
is open on `bot/kraken_ledger_evidence.py` at the SHA-256 API-key fingerprint.
The traced source is authenticated GetApiKeyInfo `result.apiKey`. The digest is
compared with an independently supplied pin using `hmac.compare_digest`; the
adjacent account comparison uses domain-separated normalized IIBAN. This is an
identifier pinning protocol, not a password-storage verifier. CodeQL guidance
distinguishes low-entropy passwords, requiring deliberately expensive hashing,
from other hash use cases. A false-positive disposition is plausible, conditional
on security review confirming key entropy, provenance and absence of verifier
reuse. No dismissal, suppression, password-hash substitution, or self-approval
is made here. The pinned protocol must not be silently changed.

## Deployment and acceptance

The repository requires human review for broker API integration changes and
passing CI/secret scanning before merge. Target the existing release branch.
After that review and production change authorization, use the existing Render
release process, verify deployed SHA, and submit a fresh uniquely identified
read-only identity request through the existing recovery boundary. Check the
receipt, actual transport timing, account binding, and all downstream freshness
checks. Never replay a consumed request. Revert this commit to roll back; no
data migration or state rollback is involved.

This patch alone cannot install the collector or authorize orders. At 17:21 UTC
the runtime still reported all 13 fields missing with `collector_missing`.
Prior authenticated inspection found legacy SQLite tables lacking required
account/key and fill provenance, missing ledger evidence tables, and no reviewed
Redis intent-inventory manifest. These require attributed source reconciliation,
not fabricated schema contents. Independently signed operator/status records,
current account-specific risk evidence, authenticated position/protective-exit
readback, and current off-host restore/cross-store certification remain required.
The six binding contracts and seven existing provider interfaces are preserved.
Do not register the collector until all reviewed sources are complete. Final
order activation requires separate authenticated approval for the exact account,
deployment, risk policy and scope.
