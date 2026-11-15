# GuardDog recovery investigation — 2026-11-12

Release: `170828fa630f6e08a640065318989850d13ca325` (merged PR #3788).
Evidence: [artifact workflow 43194749212](https://github.com/dantelrharrell-debug/Nija/actions/runs/43194749212).
Member-broker artifact ID `13932741638`, ZIP SHA-256
`0d28183c78f7cdfae598b33966c4f1c11b0d2cf5f2ff60c451141e591d68a7ec`.
Billing artifact ID `13933001007`, ZIP SHA-256
`15740c66b64d7f10ee1891fe2ab288d20f57d512052847bb63f7df472a828501`.

## Verified investigation

The retained reports contain 39 member-broker and 41 billing **scanner issue counts**,
not 80 proven vulnerabilities. Several shared packages occur in both reports;
GuardDog also includes derived risk entries in its count. Both jobs' pip-audit
steps reported no known vulnerabilities. That result is scoped to those jobs,
not all production containers, dependencies or credentials.

For every package with a finding in these two reports, the exact distribution
named by `pypi_dist_path` was downloaded from the corresponding version's PyPI
JSON metadata. Each archive SHA-256 matched PyPI's published digest. The reported
source location and match were checked against archive members without importing
or executing the package. All bundled executable digests reported for setuptools
were checked against members of that exact wheel. These checks verify the
reviewed bytes against the registry; they do not independently establish package
publisher identity or production image contents.

| Package | Version | Issue count per report | Inspected finding context |
|---|---|---:|---|
| requests | 2.33.0 | 3 | Temporary-file cleanup, upload-stream reads, and platform.system() diagnostics. |
| gunicorn | 23.0.0 | 6 | Worker/socket handling, pipe reads, PID cleanup; chmod mode 420 is octal 0644, without executable permission. |
| Flask | 3.1.3 | 6 | CLI shell startup and intended dotenv discovery/loading; these capabilities need application-specific configuration review. |
| setuptools | 84.1.0 | 9 | Packaging file handling and pip invocation in the develop command; bundled Windows launcher bytes matched the reported digests. |
| stripe | 7.11.0 | 4 | Response-stream reads and HTTP transport; a BECS documentation phrase matched the process-spawn heuristic. |
| SQLAlchemy | 2.0.25 | 11 | Database fixture cleanup and LOB reads; fetch/eval documentation; testing profiler data files matched startup-persistence heuristics. |
| PyJWT | 2.15.1 | 2 | JWKS request handling and platform.system() diagnostics. |

These contexts explain the observed matches. Some are genuine library
capabilities, while several process/autostart labels match documentation or
profiling rather than the labeled behavior. No global rule exemption, finding
baseline, malware clearance or independent release certification is granted.
The scanner failure remains enforced pending independent review of the exact
artifacts and their deployment relevance.

## Exact reviewed archives

| Package | Archive | SHA-256 |
|---|---|---|
| requests | `requests-2.33.0-py3-none-any.whl` | `3324635456fa185245e24865e810cecec7b4caf933d7eb133dcde67d48cee69b` |
| gunicorn | `gunicorn-23.0.0-py3-none-any.whl` | `ec400d38950de4dfd418cff8328b2c8faed0edb0d517d3394e457c317908ca4d` |
| Flask | `flask-3.1.3-py3-none-any.whl` | `f4bcbefc124291925f1a26446da31a5178f9483862233b23c0c96a20701f670c` |
| setuptools | `setuptools-84.1.0-py3-none-any.whl` | `5231689c6ac8156cd155cfb98c3fd6fb252c3e7e9bd3d78b64d3c55f132624c9` |
| stripe | `stripe-7.11.0-py2.py3-none-any.whl` | `400a6c76497c19fa58ac295ba3d37f6e03bbefa7fd97bdbaa75a092f0e013d50` |
| SQLAlchemy | `SQLAlchemy-2.0.25-cp310-cp310-macosx_10_9_x86_64.whl` | `4344d059265cc8b1b1be351bfb88749294b87a8b2bbe21dfbe066c4199541ebd` |
| PyJWT | `pyjwt-2.15.1-py3-none-any.whl` | `42d59d631f7768a1028a64c7ff581a9bf7519804daf91fc5b6c56e30eec5e193` |

The SQLAlchemy report selected a **CPython 3.10 macOS** archive despite the CI
job installing dependencies on Linux/Python 3.11. The zero-finding psycopg2 and
cryptography rows likewise name macOS wheels. Therefore this report cannot by
itself certify the actual production Linux wheel contents. Do not copy an
exception from these artifacts to another platform wheel. Production release
review still needs the actual image SBOM and container scan evidence.

## Corrected report enforcement

The previous checker said it rejected partial scans but only required a
nonempty list. A clean one-package report could pass for an eight-package
requirements file. The updated CLI requires that requirements file and checks
exact normalized package names and versions (including the inner scanned package
version), with no missing, duplicate,
substituted or unexpected rows. Unsupported requirement syntax denies rather
than silently dropping a dependency. Duplicate JSON keys, malformed finding
summaries, and zero counts hiding rule/risk entries also deny.

Failure summaries now print validated package/rule identifiers and counts.
Raw package code, paths, risk payloads and scanner error messages stay out of
logs. Nonzero scanner statuses and all findings remain failures. The actual
member-broker and billing artifacts still return status 1 after validation,
with their original 39 and 41 issue counts.

## Remaining release work

Review source matches independently and obtain scan evidence for actual Linux
production artifacts. Resolve other secret/container findings and release
checks. This change does not install the Kraken collector or provide the
reviewed startup factory, production public keys or signed certification
receipts. Production orders must stay disabled until the real observations,
reconciliation, protective controls, credential rotation and review pass.

## Other verified checks on this release

Full CI, CodeQL, Kraken collector regression and image build succeeded on the
merged release. They do not supersede the following failed gates:

- Secret-scanning job `131102695552`: 213 unbaselined candidates, exit 1.
  These are unreviewed candidates, not a determination of 213 exposed secrets.
- Main requirements job `131102695045`: pip-audit reported no known
  vulnerabilities; GuardDog scanned 149 packages with 577 issue counts, exit 1.
  That broader report has not received the seven-package source review above.
- Main Docker image job `131102695035`: Trivy reported Debian 13.7 and
  119 HIGH findings, zero CRITICAL, in the scanned image. The report includes
  system packages such as util-linux, Git, curl and redis-tools; the shown
  affected rows have no fixed version. These are scanner results requiring
  distro/advisory review, not a blanket risk acceptance.
- Pre-commit job `131102695550` and all four container scan jobs also failed.

These remaining failures are neither suppressed nor certified by this patch.

## Checked-out revision provenance

Use the release's **push** workflows for exact release conclusions. The earlier
references to pull-request workflows `43194970290` and `43194970238` correspond
to PR #3789's integration merge `69019925b15c5cfde239e93c9123dba07424e247`,
which merged release `170828fa` into main `cb0e8aeb`. The workflow `head_sha`
filter alone did not identify the checked-out tree. Its 201-candidate scan was
not the release-only report and must not replace that report's 213 candidates.

The release push secret report (artifact `13932552305`) and PR #3790's report
(artifact `13933379138`, integration commit
`20d7e9699477046f93f92dd499640ef6ee368e8f`) contain exactly the same 213
path/line/type entries. No candidate was introduced or removed by this patch.
The release-push GuardDog report findings, versions, risks and distribution
paths match the previously reviewed integration reports; the two release ZIPs
above were downloaded and their checksums verified separately.

Future baseline secret reports now record `checked_out_commit`,
`checked_out_tree`, and an allowlisted `ci_event`. The scanner denies a
`GITHUB_SHA` mismatch, dirty tracked files, or a revision change during scanning.
These fields identify the checked-out source, not production state or
independent certification. An integration merge remains integration evidence
unless its actual commit/tree is the approved release. Scanner tests use
committed isolated synthetic repositories, with separate mismatch, dirty-tree
and event-payload privacy tests. No production credential or evidence is used.
