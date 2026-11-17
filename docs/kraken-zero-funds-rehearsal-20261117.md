# Kraken zero-funds component rehearsal — 2026-11-17

## Scope and safety boundary

`bot/tests/test_kraken_zero_funds_lifecycle.py` joins the actual intent
idempotency registry, confirmed-fill classifier, ledger/protection evidence
reader and pretrade certificate evaluator against synthetic exchange records
and disposable local storage. It does not import the trading dispatcher or
construct a broker capable of placing an order. Python socket connections and
DNS resolution are denied during each scenario. The only child processes are
the local Redis server and CLI; Redis uses an owned Unix socket with TCP disabled.

The `live`/`production` decision-context values exercise the registry's mandatory
shared-authority branch. They do not activate a trading runtime. No private
credentials, exchange connections, production Redis endpoint or production
ledger are used.

## Assertions covered

| Scenario | Required outcome |
| --- | --- |
| Ambiguous acknowledgment with plausible price and requested size | No fill or position is invented; reconciliation remains blocked. |
| One partial fill with matching synthetic cash movements | Incomplete execution remains pending and duplicate ownership is denied. |
| Restart with a pending intent | A newly created registry recovers the pending reservation from the same Redis AOF; a stale owner cannot finalize it. |
| Completed synthetic fill history with a missing stop | The ledger reader rejects the missing protection and the pending intent remains held. |
| Matching fill, fee, balance, position and protective-order records | The reader reconciles the synthetic evidence without modifying the SQLite database. |
| Repeated reads and restart after finalization | Reads do not create records; the finalized intent still denies duplicate ownership. |
| Stale evidence, position quantity mismatch or orphan protective order | Reconciliation fails and the duplicate fence remains pending. |
| Passing accounting observation alone | The overall certificate remains uncertified and cannot authorize orders. |

Synthetic fill and protection records are deliberately inserted by the fixture.
This verifies how production components classify and reconcile those records;
it does not verify exchange order creation, a real protective-order rejection,
dispatcher retries, or a real exchange fill. Duplicate assertions concern intent
ownership, not the number of orders submitted by a live dispatcher.

The Redis rehearsal uses `appendonly yes`, `appendfsync always`, orderly
`SHUTDOWN NOSAVE`, and a new server process loading the same private directory.
It tests persistence across an **orderly AOF restart**. It does not test a process
crash, host failure, corrupted AOF, managed Redis failover, or backup restoration.
The owned server is stopped and its temporary directory removed afterward.

## Validation status at preparation

- Existing ledger-reader regression: 63 tests passed locally on Python 3.12.14.
- New scenario control flow: two tests passed using a temporary in-memory
  smoke adapter. That adapter is not committed and is not Redis durability proof.
- Official Redis 8.8.4 source compiled locally. The workspace denied Unix socket
  creation with `Operation not permitted`; the real Redis lifecycle tests have
  therefore **not passed locally**. No socket-policy bypass was attempted.
- The lifecycle test requires both `redis-server` and `redis-cli` and fails if
  either is missing. It never records missing Redis as a successful skip.
- Hosted Python 3.11 execution and its actual Redis version remain pending.
  Passing hosted results must be recorded against the exact candidate SHA and
  Actions run before this component rehearsal is marked verified.

## Hosted checks and remaining certification work

The collector workflow explicitly runs the lifecycle module on Python 3.11 and
prints both Redis tool versions. The broad CI job provisions both tools before
its unittest inventory runs. The collector workflow also has an independent
Python 3.11 pytest job for `tests/test_cache_json_security.py`; cache source and
test changes trigger it. Operator diagnostic tests already run in both collector
and Render recovery regression workflows.

To exercise the collector checks, open a pull request targeting `main` or
`release/justcall-handoff-only-20261017` whose changes match its paths, or use
the existing manual workflow trigger. A push to an unrelated candidate branch
alone does not trigger this workflow.

After hosted success, a separate zero-funds integration must still exercise the
actual dispatcher and protection-order submission paths with transport denied
and independently assert that ambiguous acknowledgments never cause duplicate
submission. Production readiness also requires current authenticated account
permissions, live-source reconciliation, security controls, recovery/restore
evidence and all remaining canonical commissioning requirements. This rehearsal
provides no deployment approval or production order authorization.
