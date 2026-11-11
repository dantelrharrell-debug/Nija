# Offline platform credential fixture review

This review classifies 57 exact keyword-detector identities in
`bot/test_platform_account_layer.py` as inert test fixtures. The raw detector
encounters these literals at 68 locations; repeated literals share one
candidate identity. No production credential, configuration or source file is
changed.

## Scope and evidence

The module tests credential discovery, routing, validation, masking and local
connection bookkeeping with synthetic labels. Its environment helper replaces
`os.environ` with the supplied fixture mapping. No real exchange credentials
are used. All 55 tests pass, including a separate run that blocks socket
connections and HTTP requests and records zero network attempts.

Each reviewed scanner identity was matched to the exact string literal in the
Python AST at the reported line. The values are short, descriptive fixture
labels, not tokens recovered from production. The tests and all their literal
values remain byte-identical to the existing public repository source.

The baseline adds only those 57 exact, file-scoped identities, marked
`is_secret: false`. No detector, file pattern, directory exclusion, source
integrity pin, approval rule or vulnerability threshold changes. No other
candidate is classified by this review. Existing baseline entries are preserved.

## Validation

- 55 existing platform-account tests pass.
- A network-blocked repeat of those tests passes with zero network attempts.
- The pinned baseline-aware hook passes the reviewed test module.
- Appending a new unreviewed synthetic candidate to that same file makes the
  hook fail. Original source bytes are restored immediately after the probe.
- The complete repository scan and independent security review remain required
  before this baseline change can be accepted for release.

The complete repository scan now reports 222 unresolved candidates, down from
279, and still returns exit status 1. These comprise 161 keyword, 30 basic
authentication, 23 private-key-marker, six base64-entropy and two hex-entropy
candidates. All remain blocking. No genuine exposure is ruled out by this
classification.

The 55 platform-account tests and the separate 49 security regression tests
pass locally (104 tests plus three subtests, in separate runs). A smaller
candidate count is not proof of credential safety or production trading
readiness.

## Production boundary

No collector installation, broker connection, ledger repair, nonce/writer
mutation, risk or kill-switch clearance, deployment or order is included.
Independent authenticated source bindings and certified backup/restore evidence
must be supplied and verified through the existing production controls. They
cannot be replaced with test fixtures or scanner classifications.
