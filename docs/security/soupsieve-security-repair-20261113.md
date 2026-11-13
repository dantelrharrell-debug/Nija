# Soup Sieve dependency security repair

Review-only; not merged or deployed. No production environment, trading safety
control, scanner configuration or baseline is changed.

Security run 43341932627, dependency job 131612062067, failed with two advisories
in soupsieve 2.9. Artifact 13999498130 identifies CVE-2026-126190
(GHSA-mmhr-3c5m-f64f, patched >=4.0) and CVE-2026-126192
(GHSA-4j63-6c4x-wfg4, patched >=2.10). The former was independently checked
against the GitHub-reviewed advisory; the latter was retrieved in the hosted
pip-audit artifact but its public advisory page could not be fetched.

- https://github.com/advisories/GHSA-mmhr-3c5m-f64f
- https://github.com/advisories/GHSA-4j63-6c4x-wfg4
- https://facelessuser.github.io/soupsieve/about/changelog/

Replace the vulnerable existing pin with soupsieve==4.1, the available current
release. Keep beautifulsoup4==4.14.2 and all other requirements unchanged. Local
isolated installation succeeds; the parser pair audit reports no known
vulnerabilities. This is not a full dependency-graph audit result; hosted
resolved-dependency auditing remains required on this PR.

Three bounded subprocess tests cover the deep-descendant advisory reproduction,
the patched strict rejection of the complex general-sibling :has selector, and
supported Beautiful Soup child-relative :has behavior. Each has a five-second
process timeout; no untrusted network markup or production data is used.

Compatibility risk: Soup Sieve 4 changes strict selector parsing. Complex
:has(a ~ b) syntax that worked in 2.9 now raises SelectorSyntaxError by default.
The test deliberately verifies this rejection rather than misrepresenting it as
matching compatibility. Review transitive callers before production approval;
no enable-legacy or NOCACHE workaround is introduced. A broad dependency audit
and hosted CI must pass before considering a separately approved deployment.

Rollback before merge: close this PR. No production rollback is required. Do not
redeploy vulnerable 2.9 merely to clear a compatibility failure: hold the release
and investigate. Repository runtime-tools-secret_scanning and codeql_checker
were unavailable in this session; local detect-secrets and hosted gates do not
stand in for an unavailable required tool. Remaining secret/precommit/artifact
findings remain blocking and are not dismissed by this dependency repair.
