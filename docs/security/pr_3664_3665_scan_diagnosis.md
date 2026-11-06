# Security diagnosis for PRs 3664 and 3665

Inspected 2026-11-06 UTC (November 5 Pacific). This is a source/CI investigation,
not deployment, trading authorization, credential validation or payment activation.

## Exact source and hosted evidence

- PR 3664: head `bb12026264e5d48fda78d66e6c1e9f64fa12f14e`, security run
  [42132455244](https://github.com/dantelrharrell-debug/Nija/actions/runs/42132455244).
  Now merged into `release/justcall-handoff-only-20261017` at `7954beda`.
- PR 3665: head `de4b79a56fbf4000e89d6ab474ee66eced0b6eab`, still open;
  [security](https://github.com/dantelrharrell-debug/Nija/actions/runs/42133116632),
  [artifact](https://github.com/dantelrharrell-debug/Nija/actions/runs/42133116780),
  [isolation](https://github.com/dantelrharrell-debug/Nija/actions/runs/42133116634).
- Both heads passed main CI and Python/JavaScript CodeQL. Both passed PR-range
  Gitleaks and verified-only TruffleHog. These are not clean full-source claims.

## Dependency failure: one advisory, duplicated records

Downloaded and inspected dependency-report artifacts **13463642685** (3664)
and **13464821484** (3665). Both contain scikit-learn **1.3.2**, with two
identical `PYSEC-2024-110` records. The aliases are **CVE-2024-5206** and
**GHSA-jw8x-6495-233v**. Thus the log's two vulnerabilities represent one
distinct advisory in one package, not two independent CVEs. Both reports list
**1.5.0** as fixed. Billing and member-broker pip-audit jobs passed separately.

Upstream [1.5 release notes](https://scikit-learn.org/1.5/whats_new/v1.5.html#security)
describe removing the training-token-retaining `stop_words_` attribute from
CountVectorizer/TfidfVectorizer. The supported fix is an upgrade to a fixed
version; previously persisted vectorizers also require retraining or clearing
that attribute. The inspected trading code uses classifiers and StandardScaler;
this specific vectorizer leakage path is not established here.

**Do not silently bump the production pin.** The existing
[migration investigation](dependency_remediation_20261104.md) documents failed
cross-version loading/prediction of persisted GradientBoosting/RandomForest
models. Upstream [model persistence guidance](https://scikit-learn.org/stable/model_persistence.html)
does not support loading models across sklearn versions. Remediation requires
owner-held representative artifacts/data, retraining under the selected fixed
version, a representative backtest, compatible pinned transitive dependencies,
and fresh resolved/container audits. No ignore flag, exception or dependency
change is introduced by this PR; the vulnerability remains blocking.

## Why baseline enforcement fails

The full tracked-file hook, unlike the PR-range scanners, compares every tracked
file against `.secrets.baseline`. Its exit 1 is translated to xargs exit 123.
This is a finding failure, not evidence of scanner installation failure.

- The committed baseline has version 1.5.0, 102 entries in 42 files.
- Hosted 3664 reports 322 candidate locations; hosted 3665 reports 316.
  None of those reported locations is in either PR's changed-file list.
  The different totals reflect different release/main trees, not six proven leaks.
- The baseline is incomplete relative to the tracked tree. Hook matching uses
  filename/type/secret hash; a line-number shift alone does not create a new
  candidate, though a baseline refresh can independently return status 3.
- Local pre-commit pins 1.4.0 while CI and the baseline use 1.5.0. Aligning the
  version removes inconsistent local tooling, but does not clear legacy findings.
- The pre-commit configuration excludes Markdown and the workflow allows that
  validation step to fail; its green job is not equivalent to the enforced full
  detect-secrets check. This PR does not broaden those exclusions.

Examples reviewed in source: `course_portal.py:32-39` contains SHA-256 asset
digests; `course_fulfillment.py:11,13` contains public Stripe price/payment-link
identifiers; the staging Blueprint's price ID and manifest digest are also
identifiers, not authentication secrets. PEM delimiter literals in validation
code are not complete private keys. Fixture/documentation context suggests many
other false positives but does not establish every candidate as benign.

The prior value-free inventory in `hosted_scan_blockers_20261104.json` includes
50 unresolved credential-risk locations. This is historical triage, not a fresh
claim that exactly 50 remain active or exposed. No credential is verified as live
by this investigation. Verified-only TruffleHog success cannot prove all
credentials are absent/revoked. Owner validation and provider rotation/revocation
are needed for any confirmed exposure; candidates are not sent to providers here.
No automatic baseline regeneration, broad allowlisting or candidate-value export
is an appropriate fix. The follow-up reviews **47 exact candidates** (43 digest,
revision, checksum or other non-authentication identifiers and four public Stripe
object IDs) with per-location reasons in
`reviewed_non_credentials_20261106.json`. Only those filename/type/value
identities are added with `is_secret=false`; no detector or path is disabled.
A replacement candidate still fails. All unreviewed candidates remain blocking.

## Independent failures on 3665

- **Isolated Trivy:** downloaded diagnostics artifact **13464352468** confirms
  DS-0002 HIGH in `game_sandbox/Dockerfile.staging`: no non-root USER instruction.
  Its launcher currently starts as root to chown the dedicated mounted disk,
  then uses gosu to drop privileges. Merely inserting USER would break that
  ownership step. The follow-up now starts directly as UID/GID 10001, refuses
  root execution, removes runtime chown/gosu and fails closed unless an enabled
  sandbox has the exact private, writable mounted disk. A dedicated container
  rehearsal is added to CI. Actual Render disk provisioning remains unverified;
  no service is deployed or enabled by this change.
- **Four container jobs:** images built and databases downloaded successfully;
  Trivy and Grype failed on actual HIGH/CRITICAL findings. Inspected root-image
  SARIF artifact **13463958143** includes util-linux/libacl/libcurl/libexpat/
  ncurses/SQLite and other findings, many without a reported fixed version.
  These are not explained by the moderate sklearn advisory alone. No-fix
  findings remain blocking pending vendor fix and exposure review.
- **GuardDog in all three Python manifests:** these are heuristic supply-chain
  findings, independent of pip-audit. Downloaded billing report **13463818093**
  shows findings for PyJWT, gunicorn, Flask, requests, setuptools, stripe and
  SQLAlchemy, with no per-package errors; Flask-CORS and psycopg2-binary have
  zero issues. Network/process/filesystem capability matches are not themselves
  proof of malicious releases. Rules such as download/execute and filesystem
  autostart require source/provenance review; the gate remains enforced.
- License compliance and build-artifact integrity jobs succeeded. There is no
  evidence that an artifact-upload failure caused the security findings.

## Focused changes and validation

Align local detect-secrets to 1.5.0. Replace opaque xargs failure output with a
pinned-hook wrapper that scans the same tracked source scope and emits only
path, line and detector type. It runs against a temporary baseline copy, so CI
cannot rewrite the reviewed baseline. Candidate findings (1), baseline drift
(3), scanner/configuration errors (2) remain nonzero. The workflow retains the
sanitized report even on failure; no finding is waived. Regression tests run in
the hosted security job before enforcement.

Offline tests exercise clean scans, existing baseline identities, newly injected
candidates, line-number drift, and malformed configuration, plus the existing
security-workflow enforcement tests. Full-source scanning is expected to remain
red until legacy candidates and independent findings are resolved. The named
`runtime-tools-secret_scanning` and `codeql_checker` executables are unavailable
in this environment; pinned detect-secrets, compilation and offline checks are
local validation only. Exact-head hosted checks remain required.

Rollback: revert the reporting/version-alignment and follow-up corrections.
Only the 47 documented non-credential identities change in the baseline. No
credentials, models, trading safeguards, deployment settings, production records,
or live payment settings change. Revert the non-root sandbox source changes as
part of the same rollback; no mounted disk was modified.
