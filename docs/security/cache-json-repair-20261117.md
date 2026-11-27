# Cache deserialization repair — November 17, 2026

Status: reviewed engineering candidate; not deployed or production certified.
Base: `6774fe96eb8ca9bf59c8508fa0f6bb9fcfa8bec2`.

## Repair

`cache/redis_client.py` previously attempted Python object deserialization when
Redis content was not JSON. An altered cache entry could therefore invoke a
Python callable. The repair reads JSON or legacy plain UTF-8 scalar strings and
never reconstructs Python objects. Writes accept JSON-compatible values only;
arbitrary objects and non-finite floats fail before any cache write.

All three in-repository wrappers write dictionaries: market data, user sessions,
and permissions. Their round trips are covered. The three dictionary getters now
return a dictionary or `None`; legacy strings, lists, scalar values and binary
object records are cache misses for these typed consumers. No key is deleted or
rewritten on a miss. Existing JSON and plain scalar records remain readable via
the generic `cache_get` interface. In particular, an ASCII protocol-0 pickle
record is returned there as an inert string, never reconstructed as an object;
other callers must validate the expected shape and repopulate unsupported old
objects from their authoritative source. This change does not migrate, delete,
or alter an existing Redis key. New string writes retain their string type even
for text such as `"123"`, `"true"` or `"null"`; boolean and null writes likewise
retain their JSON types. No broker, ledger, writer, nonce, stop,
execution-admission or production setting is changed.

The examples in `.env.example`, `.env.small_account_preset` and
`GETTING_STARTED.md` now describe private PEM configuration without embedding
private-key-shaped example blocks. Credential fields stay empty and their
private configuration instructions remain. No detector exclusion, baseline,
source fingerprint or scanner threshold is changed.

`docker-compose.yml` no longer substitutes public weak passwords when PostgreSQL
or Grafana credentials are absent. The existing environment-variable names now
use required nonempty interpolation. Service definitions and supplied credential
values are otherwise preserved. This changes the source configuration only;
no Compose service was started and no account password was changed.
Compose interpolates the whole file before selecting services, so even a
bot-only configuration requires both `POSTGRES_PASSWORD` and
`GF_SECURITY_ADMIN_PASSWORD`. The existing `DATABASE_URL` embeds the supplied
password directly. Passwords containing reserved URL characters still require a
separately validated connection-string solution; this repair does not add URL
encoding or resolve that pre-existing limitation.

## Verification performed

- 57 offline tests pass with an in-memory Redis substitute and stubbed imports;
  no application bootstrap, Redis connection or broker request occurs.
- The object-reconstruction regression fails against the original implementation
  because its harmless callable probe is invoked. It passes after the repair.
- Removing only the three dictionary shape checks in an isolated pre-fix copy
  reproduces 18 failing cases from the 30 negative-shape checks. With the checks
  present, all 30 pass without writing, deleting or flushing cached entries.
  Empty dictionaries and the existing dictionary round trips remain valid.
- Modified Python source compiles.
- Pinned Bandit 1.7.5 reports zero findings/errors for the cache module and its
  new tests, using the existing `.bandit.yml`.
- Gitleaks 8.18.1, with the repository configuration and redaction, reports zero
  findings in the changed-file staging directory. Its official release archive
  was verified against the published checksum before use.
- detect-secrets 1.5.0 reports no new identities. The existing Basic Auth example
  in `.env.example` remains unchanged; source-aware before/after scanning confirms
  that identity. No existing baseline is expanded.
- The repository's reviewed-source fingerprint validator passes unchanged.
- The private-key hook passes on all three repaired examples. Full-source marker
  detection is reduced from 17 files to 14, not certified clean.
- Official Docker Compose 5.8.0 was installed in isolated test tooling after its
  published binary digest was verified. `config --quiet`, with an empty env file
  and dummy values, passes with both credentials supplied and rejects four
  separate missing/empty PostgreSQL/Grafana cases. No resolved values are logged,
  and no service or Docker daemon is started. Required-value behavior is defined
  at https://docs.docker.com/compose/how-tos/environment-variables/variable-interpolation/ .
  A separate `config --quiet bot` check passes with both dummy credentials and
  fails when either variable is missing, confirming global interpolation before
  selecting just the bot service.

The named `runtime-tools-secret_scanning` and local `codeql_checker` are not
available in this environment. The actual scanners above are recorded rather
than claiming those unavailable tools ran. Hosted CodeQL and all required checks
must run on the exact candidate before any merge. Security-sensitive code
requires genuine review under `AGENTS.md`; deployment approval remains separate.

## Concrete remaining scan work

Current release push workflows:

- Security Scanning: https://github.com/dantelrharrell-debug/Nija/actions/runs/44111309531
- Artifact Scanning: https://github.com/dantelrharrell-debug/Nija/actions/runs/44111309496

The push secret job passes, while the same-head PR3993 secret job fails; these
are different checkout/scan contexts. The PR job reports
`tests/test_nija_lead_storage_preflight.py=committed_source_review_pin_mismatch`
and then a baseline scanner error with zero candidate findings. That merged
source needs its own exact review; it is not evidence of a newly leaked key.
Neither result closes the full-source pre-commit failures.

Private-key marker findings remaining after the three example repairs:

| Source role | Files | Required next work |
| --- | --- | --- |
| PEM recognition/diagnostics | `bot/coinbase_pem_quarantine_patch.py`, `bot/startup_validation.py`, `validate_all_env_vars.py`, `validate_broker_credentials.py`, `fix_balance_detection.py` | Preserve actual format checks. Four files have reviewed-source fingerprint bindings. Inspect any proposed parser/refactor and its regressions; do not split literals merely to conceal them from the detector. |
| Isolated fixtures | `bot/tests/test_broker_auth_recovery_patch.py`, `bot/tests/test_coinbase_connection_convergence_v2.py`, `bot/tests/test_coinbase_funding_readiness_repair_patch.py`, `bot/tests/test_coinbase_pem_quarantine.py`, `bot/tests/test_final_worker_position_coinbase_repair_patch.py`, `bot/tests/test_secondary_venue_runtime_diagnostics.py`, `test_v2_balance.py`, `tests/test_coinbase_authenticated_connect_wrapper_chain.py`, `tests/test_profit_optimization_env_template_guard.py` | Nine files are source-bound reviewed fixtures. Retain negative format coverage and require a fresh genuine source review for any changed fixture. No blanket ignore is added. |

An initial recursive Bandit inventory found 465 findings (410 LOW, 55 MEDIUM,
zero HIGH, zero parse errors). This is a broader recursive inventory, not the
exact pre-commit filename selection. The cache repair removes its B301 and B403
findings; `bot/live_rl_feedback.py:441` and `bot/meta_optimizer.py:418` still load
serialized Python model state and require a compatible, separately verified
state-format migration. Other categories include URL-scheme review, constructed
SQL and subprocess use. They require source-specific classification rather than
blanket suppression.

The initial formatting inventory spans 633 trailing-whitespace files and 103
EOF cases, with overlap. Some include signed-source contexts, embedded strings,
Markdown hard breaks or trading files. This patch does not blindly rewrite them.

The initial full-source pinned Gitleaks inventory found 29 candidates. Concrete
groups include six approved public source hashes, PEM examples/recognizers,
isolated Stripe fixtures, public status strings, and three Compose password
fallbacks. The Compose weak-default concern is repaired and independently
validated above. A full-source rerun reports 26 candidates, with zero Compose
candidates. Remaining candidates are not cleared by this patch. Do not
treat all candidates as confirmed leaked credentials or expand an allowlist
without exact source review.

## Container remediation availability

The exact root-image artifact is `14340957659` from run `44111309496`; its ZIP
SHA-256 is `ee3ed8db64de36adc4ae3ee9d8b486b075b11b3d4770f716f939ed34eeeb6446`.
At this source revision, the root Dockerfile default and the artifact workflow's
explicit build argument both select
`python:3.11-slim-trixie@sha256:07d4824036af339fa1b6ef769cc99d9c10a141769538b52b3b597c84f7a7b535`.
Job `134137336515` confirms that exact `FROM` and detects Debian **13.7**. Its
exported image manifest-list digest is
`sha256:4f514bac51267fdb9590e16be67f3764330223c12e054b0f8b28ca1e84fd083b`, matching
the Trivy SARIF image property; exported config digest is
`sha256:52fc557ab28ac625454da7a2ccf43fbc1174febbe2d3439c6391ec34da9603a7`.
These identify the CI image only and are not a verified Render image binding.
Trivy retains 119 HIGH results and no CRITICAL result. The Grype SARIF contains
419 results across severities. These are scanner findings, not a determination
that every issue is reachable in NIJA. All 119 Trivy results have an empty
fixed-version field; Grype does contain 15 fixed-version hints, including
Python and pip findings. Therefore this evidence does not support saying that
all image findings are unfixable.

Official Debian tracker checks show concrete unresolved package constraints:

- util-linux CVE-2026-76642: trixie `2.41.5-0+deb13u1` remains vulnerable; the
  tracker identifies an unstable fix and bookworm as not affected. Source:
  https://security-tracker.debian.org/tracker/CVE-2026-76642
- util-linux CVE-2026-78408/78409/78410: trixie remains vulnerable with no DSA;
  newer distributions have fixes. Source:
  https://security-tracker.debian.org/tracker/source-package/util-linux
- Git CVE-2026-105437: the tracker still marks available Debian branches
  vulnerable/unfixed. Source:
  https://security-tracker.debian.org/tracker/CVE-2026-105437
- Redis CVE-2026-92925: current trixie security package remains vulnerable;
  bookworm security and newer-distribution packages have fixes. The issue is in
  the Redis cluster-bus parser, so applicability to a client-tools-only image
  must be independently established. Source:
  https://security-tracker.debian.org/tracker/CVE-2026-92925

These checks do not establish that every image finding lacks a repair. A base
distribution change, removal of runtime tools, or an explicit applicability
disposition requires exact-image rebuilding, unchanged security enforcement and
runtime/startup regression evidence. This patch does not silently suppress
unfixed findings or claim a clean image.
