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

## Local validation

- Existing ledger-reader regression: 63 tests passed locally on Python 3.12.14.
- New scenario control flow: two tests passed using a temporary in-memory
  smoke adapter. That adapter is not committed and is not Redis durability proof.
- Official Redis 8.8.4 source compiled locally. The workspace denied Unix socket
  creation with `Operation not permitted`; the real Redis lifecycle tests have
  therefore **not passed locally**. No socket-policy bypass was attempted.
- The lifecycle test requires both `redis-server` and `redis-cli` and fails if
  either is missing. It never records missing Redis as a successful skip.

## Completed hosted verification

On 2026-11-17, GitHub Actions verified candidate
`b05d23299b73e5add50f063d4337494c0c4a85eb` in draft PR 3994 against base
`6774fe96eb8ca9bf59c8508fa0f6bb9fcfa8bec2`. Checkout logs identify the tested
synthetic PR merge as `2896b5f8d773f8b5be00803906e3755a7ba704fa`.

| Completed check | Observed result | Evidence |
| --- | --- | --- |
| Real Redis lifecycle component rehearsal | Both scenarios passed in 0.291 seconds on CPython 3.11.18, Redis server 8.0.5 and redis-cli 8.0.5. | [Collector run 44117541419, startup-evidence-binding job 134159635545](https://github.com/dantelrharrell-debug/Nija/actions/runs/44117541419/job/134159635545) |
| Cache JSON security regressions | 57 tests passed on CPython 3.11.18. | [Cache job 134159635162](https://github.com/dantelrharrell-debug/Nija/actions/runs/44117541419/job/134159635162) |
| Operator diagnostics and Render recovery regressions | Operator module: 38 unittest cases passed. Separate combined pytest block: 374 tests passed. | [Render recovery run 44117541442, job 134159634900](https://github.com/dantelrharrell-debug/Nija/actions/runs/44117541442/job/134159634900) |

All five jobs in the collector workflow completed successfully, including its
native-runtime regression with 257 passing tests. These are completed results
for the exact candidate and merge above, not for subsequent source changes.
Broad CI subsequently passed its baseline ratchet with 2,982 tests, 95 known
failures, 91 resolved and zero unexpected failures; its mandatory safety block
passed 1,047 tests and 671 subtests. Image build and both CodeQL jobs passed.
Security and artifact gates still failed as recorded below.
Local Unix socket restrictions remain unchanged; the actual AOF restart evidence
comes from the hosted job.

### Remaining failed jobs on the original candidate

| Exact job | Observed failure; next action |
| --- | --- |
| [Secret scan 134159634255](https://github.com/dantelrharrell-debug/Nija/actions/runs/44117541108/job/134159634255) | `baseline_refresh_required`, zero candidates, exit 3. Apply only the source-specific cleanup below and rerun the exact new head. |
| [Pre-commit 134159634812](https://github.com/dantelrharrell-debug/Nija/actions/runs/44117541108/job/134159634812) | `bandit`, `detect-private-key`, `end-of-file-fixer`, `gitleaks`, `trailing-whitespace`; report categories `hook_modified_files` and `source_diff_emitted`. Resolve each repository finding without suppressing hooks. |
| [GuardDog requirements 134159634990](https://github.com/dantelrharrell-debug/Nija/actions/runs/44117541426/job/134159634990) | 149 packages, 577 findings, zero scanner error entries. Review exact package artifacts and remediate unnecessary/unsafe dependencies. |
| [GuardDog member-broker 134159635457](https://github.com/dantelrharrell-debug/Nija/actions/runs/44117541426/job/134159635457) | 8 packages, 39 findings, zero scanner error entries; package-specific review required. |
| [GuardDog billing 134159635516](https://github.com/dantelrharrell-debug/Nija/actions/runs/44117541426/job/134159635516) | 9 packages, 41 findings, zero scanner error entries; package-specific review required. |
| [Main image 134159635571](https://github.com/dantelrharrell-debug/Nija/actions/runs/44117541426/job/134159635571) | Trivy: 119 HIGH OS findings. Grype also failed its severity threshold. Patch affected packages, rebuild and rescan the new digest. |
| [Gateway image 134159635469](https://github.com/dantelrharrell-debug/Nija/actions/runs/44117541426/job/134159635469) | Trivy: 48 HIGH OS + 2 HIGH Python findings; Grype threshold failure. Patch/rebuild/rescan. |
| [API image 134159635480](https://github.com/dantelrharrell-debug/Nija/actions/runs/44117541426/job/134159635480) | Trivy: 108 HIGH OS + 2 HIGH Python findings; Grype threshold failure. Patch/rebuild/rescan. |
| [Dashboard image 134159635691](https://github.com/dantelrharrell-debug/Nija/actions/runs/44117541426/job/134159635691) | Trivy: 107 HIGH OS + 2 HIGH Python findings; Grype threshold failure. Patch/rebuild/rescan. |

All four Trivy summaries identified Debian 13.7 and zero CRITICAL findings.
Counts are scanner rows, not unique CVEs. The three pip-audit blocks passed;
GuardDog capability findings alone do not establish malicious behavior. Dedicated
Bandit and dependency-audit jobs passed without overriding the failed gates.

### Source-specific baseline cleanup prepared after that run

Pinned detect-secrets 1.5.0, scanning all 4,112 candidate source paths with network
transport denied, found exactly one obsolete baseline identity: `GETTING_STARTED.md`,
`Private Key`, former line 62, hash `f0778f3e140a61d5bbbed5430773e52af2f5fba4`.
The replacement document's SHA-256 is
`2028afe025135553887979e6e1bfcdf16d2a9d0d9f0c0a6bc7d40914d521b633`.
Deleting only its nine baseline lines changes 454 identities to 453 with zero
additions or retained-metadata changes. Scanner configuration, timestamps,
manifest, source-review pins, other paths sharing the marker hash, and existing
`.env.*` exclusions remain unchanged. The full after-scan exits 0 and leaves its
temporary baseline byte-identical; the source-context check passes unchanged.

The historical 142-addition test checks those exact replacement bytes and absence
of the current path entry before restoring only the former row in a detached
comparison copy. Independent review verified that copy exactly equals the prior
454-entry baseline and that all original assertions remain intact. Source drift,
restored candidates, symlinks and unrelated additions/removals remain detectable.
The local feasible suite passed 36 tests; one historical-object test remains
required in hosted CI because this repository mirror lacks commit
`15b64ddcb44fa67f33a336b799ee8f89b1bc1fe9` and rejected its fetch. Neither a local
deselection nor the cleanup marks the hosted secret gate complete; rerun it on
the new exact candidate. No production approval is implied by this engineering review.

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
