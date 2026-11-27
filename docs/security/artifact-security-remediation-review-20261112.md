# Artifact security remediation evidence — 2026-11-12

Status: REVIEW ONLY. No release certification. No trading, payment, or deployment authorization.

## Provenance
- Base commit: `c4c5f3cfb950def2456a68f3de12f591620d8d98`.
- Post-PR-3803 merge artifact run: https://github.com/dantelrharrell-debug/Nija/actions/runs/43240050904
- Post-merge security run: https://github.com/dantelrharrell-debug/Nija/actions/runs/43240050753
- Earlier artifact run: https://github.com/dantelrharrell-debug/Nija/actions/runs/43211552791

## Verified
- Post-merge: four image jobs fail Trivy and Grype; three requirements jobs fail GuardDog. License and artifact integrity succeed.
- Post-merge security: secret baseline enforcement and pre-commit fail; Bandit and dependency-vulnerability jobs succeed.
- Earlier member-broker: pip-audit reports no known vulnerabilities; GuardDog reports 39 findings across eight scanned packages (six with findings). This is NOT proof of malicious code.
- Earlier gateway Buildx setup failed on Docker CDN connection reset before image build; post-merge gateway builds and fails scanning. Do not conflate transport and vulnerability results.
- `Dockerfile`, `Dockerfile.api`, `Dockerfile.dashboard`, and `Dockerfile.gateway` use floating `python:3.11-slim` (CI overrides PYTHON_BASE with the same tag). Exact image digest and package-level fixed versions must be established before modifying.
- Dashboard earlier scanner output includes Redis tooling CVE-2026-92925 and Debian OS package findings; affected status alone does not establish exploitability in NIJA's runtime.

## Evidence still required before dependency/image edits
1. Download and inspect complete GuardDog JSON for all three manifests; enumerate package/version/rule/source path, and classify expected capability vs actionable threat. Retain failures for unreviewed findings.
2. Parse all four Trivy/Grype SARIF artifacts; record package, installed/fixed version, CVE, severity, image digest, and whether fixes exist. Verify against vendor advisories.
3. For each changed dependency, run isolated install, `pip check`, pip-audit, GuardDog, and relevant API/payment/broker regression tests.
4. For each changed Dockerfile, rebuild, generate SBOM, run Trivy and Grype with unchanged HIGH/CRITICAL enforcement, verify non-root identity and startup/health behavior.
5. Trading acceptance: Kraken collector, nonce/ledger reconciliation, kill switch, protective exits and `allow_new_orders=false`. Payment acceptance: Stripe webhook signatures, idempotency, refunds and production payment disabled.
6. Require hosted checks for the exact review-branch commit; no merge/deploy without separate approval.

## Guardrails
Do not baseline unknown GuardDog findings, lower scanner thresholds, skip failing jobs, rotate credentials, change live services, enable payments, or activate trading.

## Initial remediation disposition
No dependency or image version change is justified from summary counts alone. Hold code changes pending artifact-level classification. This review note does not claim that scanner artifacts were fully inspected.
