# Dependency remediation and exposure triage — 2026-11-04

## Evidence and counting

The reported **166** is not a verified current Dependabot count: that API returns
403, explicitly stating alerts are disabled. The latest accessible baseline
`pip-audit-report` artifact (13299097031, Actions run 41780842521, source
`a0b4cf865a9cad48a184e9c65c97395ad4366908`) instead reports 215 resolved
packages, 27 affected packages, 264 advisory records and **167 unique primary
IDs**. Primary IDs are not necessarily unique incidents; aliases and duplicate
records are preserved rather than used to inflate remediation claims.

`dependency_triage_20261104.json` includes every primary ID, aliases, externally
queried GitHub severity, exposure, exploitability, fix branches, current direct
pin and disposition against the new fully resolved environment. Baseline
severity: 5 critical, 79 high, 71 moderate, 9 low and 3 unknown. Unknown is never
treated as low risk; withdrawn/missing GitHub metadata is not invented.
Inputs are SHA-256-bound in both generated JSON reports.

The full paginated open code-scanning inventory separately contained 4,965
alerts (365 CodeQL, 741 Trivy, 3,859 Grype), including historical source findings
and repeated OS/image findings. This is **not** a count of Python dependency
advisories. These findings are not dismissed by this change or by green
historical workflow conclusions.

## Implemented fixes

Flask-CORS is upgraded to 6.0.5 in both install surfaces, not merely 4.0.2:
later path/case-matching advisories also require 6.x. Every existing Flask CORS
integration explicitly disables private-network authorization. The shared
web/mobile app and Compose default now require exact approved origins; wildcard,
regex, empty and path-bearing origins fail closed. Both base-app and mobile
CORS layers are covered so an earlier wildcard layer cannot reauthorize a
denied browser origin. Authentication remains independently required.

The matched boto3/botocore 1.34.162 pair permits patched urllib3 2.8.0 on Python
3.11; upgrading urllib3 alone would violate the old SDK constraint. Patched
FastAPI 0.135.0 and Starlette 1.3.1 are pinned together while preserving the
existing Pydantic 2.7.0 API. JWT, cryptography, HTTP/TLS, WebSocket and installed
notebook/rendering/tool packages receive compatible resolved security updates.
Public Ed25519 signatures, AES-GCM vault behavior, JWT/billing authorization and
ASGI access-policy regressions pass with the upgraded libraries.
Flask-SocketIO 5.7.2 is paired with python-socketio 5.18.0: an in-process connection/event/acknowledgment
regression exposed the old 5.3.6 session setter incompatibility with current
Flask; the patched pair preserves threaded transport without changing handlers.
Hosted image scanning additionally reported CVE-2026-114140 despite the PyPI
audit not reporting it; nbconvert is patched to 7.17.2. The standalone service
manifests also pin setuptools 84.1.0: hosted installed-environment auditing
exposed three records in inherited setuptools 79.0.1. Fixing the inherited
build tool is preferable to excluding it or weakening the audit.

The unused direct `ecdsa` package was removed: no repository Python import/use
was found, and the resolved dependency graph attributed it only to the direct
requirements line. No SDK requires it in the new resolution. Canonical
cryptography-backed signing remains intact; no signing/order implementation
was removed or replaced. This removes its no-fixed-version timing advisory
without disabling a risk control.

Fresh PyPI-backed audits of fully resolved Python 3.11 environments report:

| Environment | Result |
| --- | --- |
| Root runtime | 200 packages; **one moderate primary advisory**, duplicated into two records; exit 1 |
| Standalone billing | No known vulnerabilities; exit 0 |
| Member credential service | No known vulnerabilities; exit 0 |

Of the baseline's 167 primary IDs, 164 are not reported by the fresh root audit,
two belong to the removed ECDSA package, and one remains. This is not a claim
that every OS, npm, source or future advisory is resolved. No vulnerability
ignore flags or scanner failure suppression were added.

## Sole remaining root dependency advisory

`dependency_residual_20261104.json` records **PYSEC-2024-110 /
CVE-2024-5206 / GHSA-jw8x-6495-233v**, moderate, in scikit-learn 1.3.2; the
reported fixed version is 1.5.0. The issue retains training tokens in
`TfidfVectorizer.stop_words_`. The inspected trading models use tree/linear
classifiers and StandardScaler, not that vectorizer; the specific leakage path
is not established. This is exposure analysis, **not an approved exception**.

The bot loads serialized model artifacts (`bot/ai_trade_quality_filter.py:525`).
Blindly changing its model-library version risks inference/serialization and
trading-decision changes. The model dependency is deliberately unchanged until
representative artifact compatibility, retraining if needed and a backtest
are available. Root pip-audit therefore remains failing; no production readiness
or merge approval is claimed. Owner-supplied authenticated model/data artifacts
and reviewed model-migration evidence are an explicit commissioning dependency.

## Reproduction and limits

Resolve each changed manifest with Python 3.11 before auditing. Exact local
commands used the session's Python 3.11 interpreter and resolved files:

```bash
uv pip compile --python "$PYTHON311" requirements.txt --quiet --output-file "$ROOT_RESOLVED"
uv pip compile --python "$PYTHON311" requirements-billing.txt --quiet --output-file "$BILLING_RESOLVED"
uv pip compile --python "$PYTHON311" requirements-member-broker.txt --quiet --output-file "$MEMBER_RESOLVED"
NIJA_DEFER_RUNTIME_SITE_HOOKS=1 "$PYTHON311" -m pip_audit \
  --vulnerability-service pypi --no-deps --disable-pip -r "$ROOT_RESOLVED" \
  --format json --output "$ROOT_AUDIT"
```

All three resolutions passed. The root audit failed as described above; billing
and member audits passed with their respective resolved files. `--no-deps` is
used only on the already fully resolved manifests, **not** top-level pins.

`scripts/nija_dependency_advisory_triage.py` reproduces both inventories from
offline pip-audit JSON and GitHub GraphQL `securityAdvisory` severity exports.
Its `--resolved-audit` option joins aliases against fresh findings; changing a
pin alone never counts as remediation. It does not install or activate anything.

Local checksum-pinned Trivy installation passed. This session could not acquire
its DB (mirror/ECR DNS and GHCR registry-token denial); deterministic acquisition
failure/fallback tests passed, and hosted exact-head scanning is still required.
Historical CodeQL Python/JavaScript run 41780842656 passed. Historical canary
31271068242 signed successfully but deployment failed; this is not current-release
signature verification. No tag/release/deployment workflow was triggered here.

The named `runtime-tools-secret_scanning` and `codeql_checker` executables are
unavailable locally. Changed-file baseline-aware detect-secrets and workflow
linting provide local checks; hosted CodeQL/secret/container jobs remain required.
No advisory is dismissed, no independent approval is fabricated, and no
production migration or live order was performed.

## Hosted follow-up, not a clean release claim

The review-head `ddad7f5c67055a2017e77a68edb5178008067d3b` produced successful
main CI and Python/JavaScript CodeQL analyses. All four container scans
successfully acquired the database from `mirror.gcr.io` and then failed on
findings, confirming the acquisition repair and nonzero vulnerability gate.
These results describe that head/its PR merge, not subsequent commits.

`hosted_scan_blockers_20261104.json` preserves value-free metadata for the image
findings and **322 credential candidates** in the full legacy scan. Of the 321
unreviewed locations, context-only review classifies 168 as likely test dummies,
56 as generated examples/documentation, 41 as identifiers/digests, 6 as
configuration placeholders, and 50 as unresolved credential-risk. One separate
public dummy-only test fixture has a narrow inline annotation. No live or active
credential can be confirmed from repository evidence alone. Candidate values
are not retained; none of the 321 has been blanket-baselined. Authenticated
owners must validate the 50 unresolved-risk locations and revoke/rotate any
confirmed exposure through the relevant provider; benign values need specific
reviewed dispositions, not a global scan bypass.

Image findings with no reported fixed version remain blocking, including
OS/library and kernel-header advisories. A header finding does not prove that
the container executes vulnerable kernel code, but this is not a waiver.
Vendor fixes and deployment/host exposure review remain required. nbconvert's
patch and the setuptools pins require fresh hosted confirmation.

The enforced configuration scan exposed three PostgreSQL findings after Redis
was hardened. PostgreSQL now uses Alpine's UID/GID 70, a read-only root,
dropped capabilities and writable data/socket/temp mounts. A no-network,
ephemeral Docker rehearsal initialized PostgreSQL and wrote/read a table under
these restrictions; existing secrets/PVC/init-script bindings are preserved.

The final-commit scan also identified root-default security contexts on the API
and founder-dashboard Kubernetes deployments. The follow-up hardens both with
explicit non-root UIDs (matching the API image's `nija` UID), read-only roots,
dropped capabilities, runtime-default seccomp and ephemeral `/tmp` mounts. The
API startup entrypoint continues to run its existing database checks and
migrations; this configuration has not been deployed.

The image policy scan also flagged dashboard images running as root and
unnecessary apt recommendations. The founder and read-only realtime dashboards
now use UID 10001, with the founder's existing log path kept writable; all
project Dockerfiles now omit unnecessary apt recommendations. The API gateway's
non-root conversion remains blocked on an owner decision: its auth SQLite
database defaults to a relative path under `/app`, so the durable writable data
path must be approved before changing its runtime identity.

Bandit's remaining three high/high-confidence hits were reviewed: two SHA-1
uses produce stable grouping/client tags, not authentication. Marking those
calls `usedforsecurity=False` preserves their exact digests. The fixed-literal
terminal clear has a narrow explained B605 annotation. The full enforced local
Bandit selection now passes. A stale member API test now requires both existing
sanitized failure logs rather than assuming initialization is the last log;
production error handling and secret redaction are unchanged.

Independent Grype scanning now still runs after a Trivy finding when the image
build succeeded, and raw SARIF is retained on failure. No image, legacy source
or credential finding is declared resolved merely because a scanner executes.
