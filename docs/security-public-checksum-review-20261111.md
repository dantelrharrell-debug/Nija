# Public checksum candidate review

The complete baseline-aware scan reported 336 unreviewed candidates. This
review classifies exactly 57 as public source checksums, leaving all other
candidates blocking. No credential value was copied into this document.

## Evidence reviewed

- All 56 entries in `web/trading-challenge/v515/approved-source-hashes.json`
  are SHA-256 checksums. Each value was recomputed from its corresponding
  original source file and matched exactly. No symlink or missing file was
  accepted.
- The single candidate in `web/trading-challenge/v515/server/release-status.mjs`
  is the published approved archive checksum, identical to the existing
  backend source pin in `game_sandbox/v515.py`.
- The pinned detector classified these as hexadecimal entropy candidates.
  Each scanner candidate hash was independently matched to the exact checksum
  literal before its existing baseline record format was used.

Only those two files receive explicit candidate identities in the baseline,
marked `is_secret: false`. No file pattern, detector, source integrity pin,
scanner threshold or whole-directory exclusion changes. Changing any reviewed
checksum to a new unreviewed value still blocks the hook; an offline mutation
probe verified that behavior and restored the source bytes afterwards.

## Validation and remaining gate

The targeted pinned scanner passes these reviewed checksum identities. The
existing baseline and TruffleHog regression suites pass: 19 tests. The approved
source hash test remains required, as do independent human review and the full
repository scan on the exact final commit.

The complete baseline-aware scan now reports 279 remaining candidates and
returns exit status 1, preserving the release hold. These comprise 218 keyword candidates, 30 basic
authentication candidates, 23 private-key-marker candidates, six base64 entropy
candidates and two hexadecimal entropy candidates. These categories do not
establish whether credentials are real. They remain unreviewed; none is marked
safe by this change. Any genuine exposure requires private incident review,
revocation/rotation and appropriate source/history remediation.

Combined local security regression validation passes 49 tests plus three
subtests. New source and workflow files also pass changed-file scanning without
baseline exceptions; the baseline metadata itself is checked with the scanner's
normal baseline-aware invocation.

This is not a release certificate. Container vulnerabilities, package-scanner
failures, copy-policy/source-approval conflicts and independent production
trading evidence still require their own resolution. No deployment, live order,
collector installation, ledger edit or safety-control change is included.

## Package scan completeness

The package workflow pins GuardDog 3.2.0, the version already used in the
inspected failed run. Its upstream JSON reporter emits a list of package
results; each result separates `issues` from `errors`. Upstream's
`exit_with_status_code` checks issue counts. The local report checker now also
rejects nonempty error maps, empty/malformed output and any nonzero scanner
exit. It prints counts only, never scanner payloads or exception details.

The original scanner status is captured and passed to the checker; findings
and infrastructure failures stay blocking. No sandbox option is disabled and
no scan rule is excluded. Application startup hooks are deferred only in the
CI package-scan job; production configuration is unchanged. Tests cover clean,
finding, incomplete/error, malformed, missing and nonzero-exit reports.

Upstream references inspected:

- https://github.com/DataDog/guarddog/blob/v3.2.0/guarddog/cli.py
- https://github.com/DataDog/guarddog/blob/v3.2.0/guarddog/reporters/json.py

This makes subsequent scan failures diagnosable; it does not resolve network
failures or classify a suspicious dependency as safe.
