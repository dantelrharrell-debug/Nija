# Exact-source secret candidate repair

The release push report for `15b64ddcb44fa67f33a336b799ee8f89b1bc1fe9`
contains 142 unbaselined candidates. Its source is security workflow
43501403346, artifact 14075205519. The ZIP digest and exact coordinates are
recorded in the companion JSON manifest. A local full scan and a targeted
detect-secrets 1.5.0 scan independently reproduced these same coordinates.
The integration report from workflow 43501590117 instead identifies
`f43983588fb59d4d8f75746c0146b872f267cb7f` and contains 144 candidates;
it is not the release report.

All 142 release findings were inspected in their source context. The manifest
records the reason for every classification: isolated test credentials,
documentation placeholders and insecure-code illustrations, environment-variable
names and labels, public marker/status strings, test-database credentials,
diagnostic URL templates, PEM delimiters and a test-key validation regex.
The Stripe price ID is a public resource identifier, not an API credential.
The documented former webhook default is an insecure-example quotation;
the current webhook implementation requires a supplied environment secret.
The short PEM bodies in the affected fixtures are synthetic format probes,
not cryptographic private keys. No production credential was used or verified.

The baseline adds only these exact filename/type/value identities. A subsequent
full scan required baseline housekeeping: ten absent old identities are removed,
and 33 existing entries have line/filename metadata refreshed. These changes
are listed separately in the manifest; retained value identities and audit flags
are unchanged. Plugin configuration, filters and generation metadata are preserved.
No wildcard ignore, detector exclusion or successful provider verification is
introduced. Actual credentials are not rotated, replaced or cleared by this
source review. Independent human review remains required before merging.

## Protect marker-only exceptions

A private-key detector can identify a PEM delimiter rather than the key body.
Consequently an unchanged detector identity alone cannot safely approve a new
payload. The manifest binds every affected file to its complete SHA-256 source
fingerprint. Fingerprints use colon-separated bytes, the conventional public
fingerprint representation. The baseline's review-manifest binding is enforced
by the full-scan wrapper; pre-commit also runs the validator unconditionally.
Missing, altered, malformed, substituted and symlinked reviewed source denies
the check. Any source change requires a new review, even if the detector's
candidate value is unchanged. The manifest is versioned review evidence, not
a signed independent certification or automatic approval mechanism.

Tests reproduce the PEM marker collision using the real pinned detector and
prove the source binding rejects the changed payload. They also exercise the
actual full-scan wrapper, malformed manifests, traversal, symlink substitution,
missing files, unchanged source and the exact baseline changes described above.
New candidates remain subject to the ordinary scanner.

## Remaining failures are enforced

This change does not waive GuardDog findings. Exact-release package artifacts
still require independent source/artifact review: the inspected billing and
member-broker reports have 41 and 39 issue counts. These are heuristic findings,
not 80 established vulnerabilities. The dependency vulnerability audit passed
on this release, but that does not settle the capability findings or certify
the final production image. The earlier source review in
`guarddog-findings-20261112.md` also documents platform-wheel discrepancies.
No all-findings exception or successful scan result is fabricated here.

Pre-commit additionally reports Bandit, docstring ordering, private-key marker,
formatting, Gitleaks and test-naming failures. The baseline repair does not
claim to resolve those independent hooks. Exact-release checks, image evidence,
independent review and separate deployment authorization remain required.
No Render setting, startup file, active collection, ledger or trading authority
is modified. The production collector and 13 genuine pretrade observations
are not certified by these offline changes.
